"""
APScheduler 定时任务：
- 每30分钟：轮询钉钉知识库，发现新会议纪要自动分析并写入飞书
- 每60分钟：轮询 163 邮件，发现会议邮件写入飞书
- 每30分钟：SQLite ↔ 飞书知识库同步
- 每30分钟：Heartbeat 心跳（LangGraph 适配版）——Agent 主动检查并决定是否需要做什么
"""
import json
import logging
import os
import time
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


# --------------------------------------------------------------------------- #
# 会议路由辅助（项目感知写入）
# --------------------------------------------------------------------------- #
def _route_and_write_meeting(info: dict, doc_url: str, analyzer) -> tuple:
    """
    根据 info 中的项目信息决定写入目标：
    - 能识别项目 → 写项目 04_会议纪要（及 06_RAID 日志）
    - 无法识别 → 降级到全局「📋 会议纪要汇总」页

    返回 (feishu_page, project_name, project_code, folder_token, raid_written)
    """
    project_name = (info.get("project_name") or "").strip()
    project_code = (info.get("project_code") or "").strip().upper()

    if project_name or project_code:
        try:
            from integrations.meeting.project_router import ProjectRouter
            router = ProjectRouter()
            folder_token = router.get_or_create_project_folder(project_name, project_code)
            routing = router.route_meeting(info, folder_token)

            feishu_page = analyzer.write_to_project_page(
                info, routing["meeting_notes_token"], doc_url
            )

            raid_written = False
            raid = info.get("raid_elements") or {}
            has_raid = any(raid.get(k) for k in ("risks", "actions", "issues", "decisions"))
            if has_raid and routing.get("raid_token"):
                analyzer.write_raid_rows(
                    raid, routing["raid_token"], date=info.get("date") or ""
                )
                raid_written = True

            return feishu_page, project_name, project_code, folder_token, raid_written
        except Exception as e:
            logger.warning(f"[Scheduler] 项目路由失败，降级到全局汇总页: {e}")

    # 降级：写全局汇总页
    feishu_page = analyzer.write_to_feishu(info, doc_url=doc_url)
    return feishu_page, "", "", "", False


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
                tracker.mark_processed(doc_id, docs.url_space_id, doc_name, "empty")
                continue

            info = analyzer.analyze(content, doc_name=doc_name)
            if info is None:
                tracker.mark_processed(doc_id, docs.url_space_id, doc_name, "not_meeting")
                continue

            doc_url = item.get("url", "")
            feishu_page, project_name, project_code, folder_token, raid_written = (
                _route_and_write_meeting(info, doc_url, analyzer)
            )
            tracker.mark_processed(
                doc_id, docs.url_space_id, doc_name, feishu_page,
                project_name=project_name, project_code=project_code,
                project_folder_token=folder_token, raid_written=raid_written,
            )
            new_count += 1
            proj_hint = f" [{project_code}]" if project_code else ""
            logger.info(f"[Scheduler] 会议纪要已写入飞书{proj_hint}: {doc_name!r}")
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
    from graph.parallel import get_task_queue, Priority

    logger.info("[Scheduler] 开始轮询邮件...")
    poller = IMAPPoller()
    try:
        emails = poller.fetch_unread()
    except Exception as e:
        logger.error(f"[Scheduler] 邮件拉取失败: {e}")
        return

    if not emails:
        return

    queue = get_task_queue()
    processed = 0
    for mail in emails:
        subject = mail.get("subject", "（无主题）")
        try:
            prompt = _build_email_prompt(mail)

            def _process_mail(p=prompt, s=subject):
                result = invoke(
                    message=p,
                    platform="scheduler",
                    user_id="scheduler",
                    chat_id="email_poll",
                )
                logger.info(f"[Scheduler] 邮件处理完毕: {s} → {result[:100]}")

            queue.submit(
                _process_mail,
                priority=Priority.NORMAL,
                description=f"邮件轮询: {subject[:40]}",
            )
            processed += 1
        except Exception as e:
            logger.error(f"[Scheduler] 提交邮件处理失败 ({subject}): {e}")

    if processed:
        logger.info(f"[Scheduler] 本轮提交 {processed} 封邮件到任务队列")


# --------------------------------------------------------------------------- #
# 上下文同步
# --------------------------------------------------------------------------- #
def sync_context():
    from sync.context_sync import ContextSync
    logger.info("[Scheduler] 开始同步上下文至飞书...")
    ContextSync().push_to_feishu()


# --------------------------------------------------------------------------- #
# Heartbeat 心跳（LangGraph 适配版）
# --------------------------------------------------------------------------- #
_HEARTBEAT_STATE_FILE = "workspace/heartbeat_state.json"


def _load_heartbeat_state() -> dict:
    try:
        with open(_HEARTBEAT_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_heartbeat_state(state: dict):
    os.makedirs("workspace", exist_ok=True)
    with open(_HEARTBEAT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def heartbeat():
    """
    心跳任务（LangGraph 适配版）。

    每30分钟触发一次，让 Agent 主动读取 HEARTBEAT.md 并决定是否需要做什么。
    与普通 cron 任务的关键区别：Agent 自己判断优先级和行动，而不是执行固定脚本。

    如果 Agent 回复 HEARTBEAT_OK，静默完成；有实质内容则发送给 Owner。
    每次使用独立 thread_id，避免上下文无限增长（workspace 文件是跨会话记忆）。
    通过优先级队列提交，避免与用户实时消息竞争 worker。
    """
    # 优先读 config_store（IM 对话中 agent_config 设置，无需重启），fallback 到 .env
    from integrations.storage.config_store import get as config_get
    owner_chat_id = config_get("OWNER_FEISHU_CHAT_ID") or os.getenv("OWNER_FEISHU_CHAT_ID", "")
    if not owner_chat_id:
        logger.debug("[Heartbeat] 未配置 OWNER_FEISHU_CHAT_ID，跳过心跳")
        return

    # 检查深夜静默时段（23:00—07:00）
    hour = int(time.strftime("%H"))
    if hour >= 23 or hour < 7:
        logger.debug(f"[Heartbeat] 深夜静默时段（{hour}:xx），跳过")
        return

    # 读取 HEARTBEAT.md 内容作为任务清单
    try:
        with open("workspace/HEARTBEAT.md", encoding="utf-8") as f:
            heartbeat_md = f.read().strip()
    except FileNotFoundError:
        heartbeat_md = "暂无心跳任务清单"

    hb_state = _load_heartbeat_state()
    state_json = json.dumps(hb_state, ensure_ascii=False)

    prompt = (
        "【心跳检查】这是一条自动触发的心跳消息。\n\n"
        "请根据下方任务清单，判断当前是否有需要主动执行的任务。\n"
        "- 若无需处理，直接回复 `HEARTBEAT_OK`，不要发任何消息\n"
        "- 若有任务需要执行，请执行并在完成后给出简短说明\n"
        "- 执行完任务后，将本次检查时间戳写入 "
        f"`workspace/heartbeat_state.json`（当前状态：{state_json}）\n\n"
        f"## 心跳任务清单\n\n{heartbeat_md}"
    )

    from graph.parallel import get_task_queue, Priority

    def _run_heartbeat(p=prompt, chat_id=owner_chat_id):
        try:
            from graph.agent import invoke
            unique_chat_id = f"heartbeat_{int(time.time())}"
            result = invoke(
                message=p,
                platform="heartbeat",
                user_id="scheduler",
                chat_id=unique_chat_id,
            )
            result_stripped = (result or "").strip()
            if result_stripped and result_stripped != "HEARTBEAT_OK":
                from integrations.feishu.bot import bot as feishu_bot
                feishu_bot.send_text(chat_id=chat_id, text=f"🔔 心跳提醒\n\n{result_stripped}")
                logger.info(f"[Heartbeat] 主动发送消息给 owner: {result_stripped[:80]}")
            else:
                logger.debug("[Heartbeat] 无需主动响应")
        except Exception as e:
            logger.error(f"[Heartbeat] 执行失败: {e}")

    get_task_queue().submit(
        _run_heartbeat,
        priority=Priority.LOW,
        description="心跳检查",
    )


# --------------------------------------------------------------------------- #
# 每日会议纪要迁移（富文本格式，保留原始时间）
# --------------------------------------------------------------------------- #
def daily_meeting_migration():
    """每日执行一次：拉取钉钉新会议纪要，以飞书富文本块格式写入对应项目 04_会议纪要 页面。"""
    from integrations.meeting.daily_migration import run_daily_migration
    logger.info("[Scheduler] 触发每日会议迁移...")
    try:
        summary = run_daily_migration()
        logger.info(f"[Scheduler] 每日迁移结果: {summary}")
    except Exception as e:
        logger.error(f"[Scheduler] 每日迁移失败: {e}")


# --------------------------------------------------------------------------- #
# 启动 / 停止
# --------------------------------------------------------------------------- #
def start():
    from integrations.storage.config_store import get as cfg_get

    scheduler.add_job(poll_dingtalk_meetings, "interval", minutes=30, id="dingtalk_meetings")
    scheduler.add_job(poll_email, "interval", minutes=60, id="email_poll")
    scheduler.add_job(sync_context, "interval", minutes=30, id="ctx_sync")
    scheduler.add_job(heartbeat, "interval", minutes=30, id="heartbeat",
                      # 启动后 5 分钟再执行第一次，避免刚启动就触发
                      start_date=None)

    # 每日会议迁移（可配置执行小时，默认 08:00）
    try:
        run_hour = int(cfg_get("DAILY_MIGRATION_RUN_HOUR") or "8")
    except Exception:
        run_hour = 8
    scheduler.add_job(
        daily_meeting_migration,
        "cron",
        hour=run_hour,
        minute=0,
        id="daily_meeting_migration",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(f"Scheduler 已启动（每日迁移 {run_hour:02d}:00 触发）")


def stop():
    scheduler.shutdown()
