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
def _build_email_prompt(mail: dict) -> str:
    subject = mail.get("subject", "（无主题）")
    sender = mail.get("sender", "")
    date = mail.get("date", "")
    body = (mail.get("body", "") or "")[:3000]
    return (
        "请处理以下邮件：判断是否为会议相关邮件（会议邀请、纪要、日程等）。\n"
        "如果是会议邮件，提取关键信息（标题、时间、地点、参与者、议程、备注），"
        "整理为 Markdown 并追加到飞书知识库上下文页面（feishu_append_to_page）。\n"
        "如果不是会议邮件，回复【非会议邮件，已跳过】，不需要写飞书。\n\n"
        f"主题：{subject}\n发件人：{sender}\n日期：{date}\n\n{body}"
    )


def poll_email():
    from integrations.email.imap_client import IMAPPoller
    from graph.agent import invoke

    logger.info("[Scheduler] 开始轮询邮件...")
    poller = IMAPPoller()
    try:
        emails = poller.fetch_unread()
    except Exception as e:
        logger.error(f"[Scheduler] 邮件拉取失败: {e}")
        return

    if not emails:
        return

    processed = 0
    for mail in emails:
        try:
            prompt = _build_email_prompt(mail)
            result = invoke(
                message=prompt,
                platform="scheduler",
                user_id="scheduler",
                chat_id="email_poll",
            )
            logger.info(f"[Scheduler] 邮件处理完毕: {mail.get('subject', '')} → {result[:100]}")
            processed += 1
        except Exception as e:
            logger.error(f"[Scheduler] 处理邮件失败 ({mail.get('subject', '')}): {e}")

    if processed:
        logger.info(f"[Scheduler] 本轮处理 {processed} 封邮件")


# --------------------------------------------------------------------------- #
# 上下文同步
# --------------------------------------------------------------------------- #
def sync_context():
    from sync.context_sync import ContextSync
    logger.info("[Scheduler] 开始同步上下文至飞书...")
    ContextSync().push_to_feishu()


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
