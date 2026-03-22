"""
多话题管理器：为同一 IM 聊天窗口中的独立话题维护隔离的对话上下文。

话题标识格式：#话题名（如 #项目A、#日程、#采购）
话题 thread_id 格式：{platform}:{chat_id}#topic#{safe_name}

该格式确保：
- thread_id.split(":", 1)[0] 仍是平台名（feishu/dingtalk）
- #topic# 分隔符不会出现在正常 chat_id 中
- 不同话题有独立的 SQLite checkpoint → 完全隔离的对话历史
"""
import re
import time
import sqlite3
import threading
from collections import defaultdict

_topics: dict[str, dict[str, dict]] = defaultdict(dict)
_lock = threading.Lock()

_TOPIC_TTL = 86400 * 7  # 7天不活跃则过期（内存清理用）
_MAX_TOPICS_PER_CHAT = 20  # 单个聊天最多话题数

# SQLite 持久化
_topic_db: sqlite3.Connection | None = None
_topic_db_lock = threading.Lock()


def _get_topic_db() -> sqlite3.Connection:
    """懒加载 SQLite 连接，首次调用时建表并加载历史记录到内存。"""
    global _topic_db
    if _topic_db is not None:
        return _topic_db
    with _topic_db_lock:
        if _topic_db is not None:
            return _topic_db
        import os
        os.makedirs("data", exist_ok=True)
        conn = sqlite3.connect("data/memory.db", check_same_thread=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_topics (
                chat_id      TEXT NOT NULL,
                topic_name   TEXT NOT NULL,
                thread_id    TEXT NOT NULL,
                last_activity REAL NOT NULL,
                preview      TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (chat_id, topic_name)
            )
        """)
        conn.commit()
        # 加载所有已知话题到内存
        rows = conn.execute(
            "SELECT chat_id, topic_name, thread_id, last_activity, preview FROM chat_topics"
        ).fetchall()
        with _lock:
            for chat_id, topic_name, thread_id, last_activity, preview in rows:
                _topics[chat_id][topic_name] = {
                    "thread_id": thread_id,
                    "last_activity": last_activity,
                    "preview": preview,
                }
        _topic_db = conn
        return conn


def _persist_topic(chat_id: str, topic_name: str, thread_id: str, last_activity: float, preview: str) -> None:
    """将话题状态持久化到 SQLite（UPSERT）。"""
    try:
        db = _get_topic_db()
        db.execute(
            """INSERT INTO chat_topics (chat_id, topic_name, thread_id, last_activity, preview)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(chat_id, topic_name) DO UPDATE SET
                   thread_id=excluded.thread_id,
                   last_activity=excluded.last_activity,
                   preview=excluded.preview""",
            (chat_id, topic_name, thread_id, last_activity, preview),
        )
        db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[TopicManager] 持久化话题失败: {e}")


def extract_topic(text: str) -> tuple[str | None, str]:
    """
    从消息文本中提取话题名前缀。

    支持格式：
      "#项目A 进展如何？" → ("项目A", "进展如何？")
      "#日程" → ("日程", "")            ← 仅切换话题，无新消息
      "新话题：预算 Q2情况" → ("预算", "Q2情况")
      "新话题 预算 Q2情况" → ("预算", "Q2情况")
      "开始新话题：预算 Q2情况" → ("预算", "Q2情况")
      "普通消息" → (None, "普通消息")

    话题名：非空白字符序列，最多 20 个字符。
    """
    t = text.strip()

    # ── #话题名 格式（优先）────────────────────────────────────────────────
    m = re.match(r'^#(\S{1,20})\s*(.*)', t, re.DOTALL)
    if m:
        return m.group(1), m.group(2).strip()

    # ── 自然语言格式：新话题[：:\s]+话题名 ──────────────────────────────
    m = re.match(
        r'^(?:开始)?新话题[：:\s]+([^\s，,。！？]{1,20})\s*(.*)',
        t, re.DOTALL
    )
    if m:
        return m.group(1), m.group(2).strip()

    return None, text


def make_topic_thread_id(platform: str, chat_id: str, topic_name: str) -> str:
    """
    生成话题专属的 thread_id（用于 SQLite checkpointing 隔离）。

    格式：{platform}:{chat_id}#topic#{safe_name}
    """
    safe = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', topic_name)[:20]
    return f"{platform}:{chat_id}#topic#{safe}"


def extract_real_chat_id(thread_id: str) -> str:
    """
    从话题 thread_id 中提取真实 chat_id（用于 IM API 调用）。

    "feishu:oc_xxx#topic#项目A" → "oc_xxx"
    "feishu:oc_xxx" → "oc_xxx"（无话题后缀）
    """
    parts = thread_id.split(":", 1)
    rest = parts[1] if len(parts) == 2 else thread_id
    return rest.split("#topic#")[0]


def register_topic(chat_id: str, topic_name: str, thread_id: str, preview: str = "") -> None:
    """注册/更新话题活跃状态（内存 + SQLite）。"""
    last_activity = time.time()
    with _lock:
        _topics[chat_id][topic_name] = {
            "thread_id": thread_id,
            "last_activity": last_activity,
            "preview": preview[:60],
        }
    _persist_topic(chat_id, topic_name, thread_id, last_activity, preview[:60])


def get_topics(chat_id: str) -> dict[str, dict]:
    """返回指定 chat 下所有话题，按最后活动时间降序排列（含历史，从 SQLite 加载）。"""
    # 确保 SQLite 已加载
    _get_topic_db()
    with _lock:
        topics = dict(_topics[chat_id])
    return dict(sorted(topics.items(), key=lambda x: -x[1]["last_activity"]))


def format_topics(chat_id: str) -> str:
    """生成话题列表，供 /topics 命令返回给用户。包含历史话题，支持直接 resume。"""
    import datetime
    topics = get_topics(chat_id)
    if not topics:
        return (
            "当前没有话题记录。\n\n"
            "💡 **多话题用法**：在消息前加 `#话题名` 即可隔离上下文：\n"
            "• `#项目A 进展如何？` — 开始/切换到项目A话题\n"
            "• `#日程 明天有什么安排？` — 独立处理日程\n"
            "• `/topics` — 查看所有话题"
        )

    now = time.time()
    active = []    # 7天内
    history = []   # 7天以上

    for name, info in topics.items():
        age = now - info["last_activity"]
        ts = datetime.datetime.fromtimestamp(info["last_activity"]).strftime("%m-%d %H:%M")
        preview = info["preview"]
        preview_str = f"「{preview}」" if preview else ""
        entry = f"• `#{name}` — {ts} {preview_str}"
        if age < _TOPIC_TTL:
            active.append(entry)
        else:
            history.append(entry)

    lines = []
    if active:
        lines.append(f"**近期话题（{len(active)} 个）：**\n")
        lines.extend(active)
    if history:
        if lines:
            lines.append("")
        lines.append(f"**历史话题（{len(history)} 个）：**\n")
        lines.extend(history)

    lines.append(
        "\n💡 发 `#话题名 消息` 可恢复任意话题的完整对话历史\n"
        "发 `/clear` 清空当前话题记录"
    )
    return "\n".join(lines)


# 欢迎消息（含多话题引导）
WELCOME_MESSAGE = (
    "你好！有什么可以帮你的？\n\n"
    "💡 **同一窗口，多话题并行**：\n"
    "• `#项目A 进展如何？` — 在项目A话题下问\n"
    "• `#日程 明天有什么安排？` — 切换到日程话题\n"
    "• `/topics` — 查看所有话题（含历史，可直接 resume）\n"
    "• `/clear` — 清空当前话题历史"
)
