"""
APScheduler 定时任务：
- 每30分钟：轮询钉钉知识库，发现新会议纪要自动分析并写入飞书
- 每60分钟：轮询 163 邮件，发现会议邮件写入飞书
- 每30分钟：SQLite ↔ 飞书知识库同步
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


# --------------------------------------------------------------------------- #
# 钉钉会议纪要轮询（主流程）
# --------------------------------------------------------------------------- #
def poll_dingtalk_meetings():
    """轮询钉钉知识库，对新文档进行 LLM 分析并写入飞书。"""
    from integrations.dingtalk.docs import DingTalkDocs
    from integrations.meeting import analyzer, tracker

    logger.info("[Scheduler] 开始轮询钉钉会议纪要...")
    try:
        docs = DingTalkDocs()
        items = docs.list_recent_files(limit=50)
    except Exception as e:
        logger.error(f"[Scheduler] 获取钉钉文档列表失败: {e}")
        return

    new_count = 0
    for item in items:
        doc_id = item.get("id", "")
        doc_name = item.get("name", "")
        if not doc_id or tracker.is_processed(doc_id):
            continue

        logger.info(f"[Scheduler] 处理新文档: {doc_name!r} ({doc_id})")
        try:
            content = docs.read_file_content(doc_id)
            if not content:
                logger.warning(f"[Scheduler] 文档内容为空，跳过: {doc_name!r}")
                tracker.mark_processed(doc_id, docs.space_id, doc_name, "empty")
                continue

            info = analyzer.analyze(content, doc_name=doc_name)
            if info is None:
                # 非会议文档，仍标记为已处理避免下次重复
                tracker.mark_processed(doc_id, docs.space_id, doc_name, "not_meeting")
                continue

            doc_url = item.get("url", "")
            feishu_page = analyzer.write_to_feishu(info, doc_url=doc_url)
            tracker.mark_processed(doc_id, docs.space_id, doc_name, feishu_page)
            new_count += 1
            logger.info(f"[Scheduler] 会议纪要已写入飞书: {doc_name!r}")
        except Exception as e:
            logger.error(f"[Scheduler] 处理文档失败 ({doc_name}): {e}")

    if new_count:
        logger.info(f"[Scheduler] 本轮处理 {new_count} 篇会议纪要")
    else:
        logger.debug("[Scheduler] 无新会议纪要")


# --------------------------------------------------------------------------- #
# 163 邮件轮询（辅助流程）
# --------------------------------------------------------------------------- #
def poll_email():
    from integrations.email.imap_client import IMAPPoller
    from integrations.email.parser import extract_meeting_info
    from integrations.feishu.knowledge import FeishuKnowledge

    logger.info("[Scheduler] 开始轮询邮件...")
    poller = IMAPPoller()
    emails = poller.fetch_unread()
    if not emails:
        return

    kb = FeishuKnowledge()
    for mail in emails:
        info = extract_meeting_info(mail)
        if info:
            title = info.get("title", mail["subject"])
            content = _format_email_meeting(info)
            kb.create_or_update_page(title=f"[会议] {title}", content=content)
            logger.info(f"会议邮件已写入飞书: {title}")


# --------------------------------------------------------------------------- #
# 上下文同步
# --------------------------------------------------------------------------- #
def sync_context():
    from sync.context_sync import ContextSync
    logger.info("[Scheduler] 开始同步上下文至飞书...")
    ContextSync().push_to_feishu()


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _format_email_meeting(info: dict) -> str:
    lines = [f"# {info.get('title', '会议')}\n"]
    if info.get("time"):
        lines.append(f"**时间**: {info['time']}")
    if info.get("location"):
        lines.append(f"**地点**: {info['location']}")
    if info.get("attendees"):
        lines.append(f"**参与者**: {', '.join(info['attendees'])}")
    if info.get("agenda"):
        lines.append(f"\n## 议程\n{info['agenda']}")
    if info.get("notes"):
        lines.append(f"\n## 纪要\n{info['notes']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 启动 / 停止
# --------------------------------------------------------------------------- #
def start():
    scheduler.add_job(poll_dingtalk_meetings, "interval", minutes=30, id="dingtalk_meetings")
    scheduler.add_job(poll_email, "interval", minutes=60, id="email_poll")
    scheduler.add_job(sync_context, "interval", minutes=30, id="ctx_sync")
    scheduler.start()
    logger.info("Scheduler 已启动")


def stop():
    scheduler.shutdown()
