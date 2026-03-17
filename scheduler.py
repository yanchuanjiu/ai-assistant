"""
APScheduler 定时任务：
- 每5分钟：轮询 163 邮件，发现会议信息自动写入飞书
- 每30分钟：SQLite ↔ 飞书知识库同步
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


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
            content = _format_meeting(info)
            kb.create_or_update_page(title=f"[会议] {title}", content=content)
            logger.info(f"会议纪要已写入飞书: {title}")


def sync_context():
    from sync.context_sync import ContextSync
    logger.info("[Scheduler] 开始同步上下文至飞书...")
    ContextSync().push_to_feishu()


def _format_meeting(info: dict) -> str:
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


def start():
    scheduler.add_job(poll_email, "interval", minutes=60, id="email_poll")
    scheduler.add_job(sync_context, "interval", minutes=30, id="ctx_sync")
    scheduler.start()
    logger.info("Scheduler 已启动")


def stop():
    scheduler.shutdown()
