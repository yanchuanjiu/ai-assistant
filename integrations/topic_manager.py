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


def find_similar_topics(name: str, topics: dict[str, dict]) -> list[str]:
    """
    找出与 name 相近的话题名称（子串匹配或字符集重叠 >= 60%），排除完全相同项。
    返回列表按最后活动时间降序排列。
    """
    similar = []
    for existing_name, info in topics.items():
        if existing_name == name:
            continue
        # 子串匹配
        if name in existing_name or existing_name in name:
            similar.append((existing_name, info.get("last_activity", 0)))
            continue
        # 字符集重叠（适合中文短标题）
        overlap = len(set(name) & set(existing_name))
        threshold = min(len(name), len(existing_name)) * 0.6
        if overlap >= threshold and overlap >= 2:
            similar.append((existing_name, info.get("last_activity", 0)))
    similar.sort(key=lambda x: -x[1])
    return [n for n, _ in similar]


def _get_all_sessions(chat_id: str) -> list[dict]:
    """
    从 LangGraph checkpoints + feishu_anchors 获取该 chat 的所有对话 session。
    返回列表，每项：{thread_id, label, last_activity, kind}
    kind: 'topic'(#话题名) / 'thread'(飞书线程) / 'main'(主对话)
    """
    import os
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "memory.db")
    sessions = {}
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        # 1. 从 feishu_anchors 获取每个 thread_id 的最后活动时间
        anchor_rows = conn.execute(
            "SELECT thread_id, MAX(created_at) FROM feishu_anchors GROUP BY thread_id"
        ).fetchall()
        for tid, ts in anchor_rows:
            if chat_id in tid:
                sessions[tid] = {"thread_id": tid, "last_activity": ts}

        # 2. 从 checkpoints 补充没有在 anchors 里的 thread_id
        cp_rows = conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE ?",
            (f"feishu:%{chat_id}%",)
        ).fetchall()
        for (tid,) in cp_rows:
            if tid not in sessions:
                sessions[tid] = {"thread_id": tid, "last_activity": 0}

        # 也包含 feishu:thread:om_xxx（来自飞书话题线程，可能不含 chat_id 字符串）
        thread_rows = conn.execute(
            "SELECT thread_id, MAX(created_at) FROM feishu_anchors "
            "WHERE thread_id LIKE 'feishu:thread:%' GROUP BY thread_id"
        ).fetchall()
        for tid, ts in thread_rows:
            if tid not in sessions:
                sessions[tid] = {"thread_id": tid, "last_activity": ts}

        conn.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[TopicManager] 获取 session 列表失败: {e}")

    # 3. 合并 chat_topics 表里的已知话题（有 label 和 preview）
    _get_topic_db()
    with _lock:
        named = dict(_topics.get(chat_id, {}))

    result = []
    for tid, info in sessions.items():
        ts = info["last_activity"]
        if "#topic#" in tid:
            name = tid.split("#topic#", 1)[1]
            preview = named.get(name, {}).get("preview", "")
            result.append({"thread_id": tid, "label": f"#{name}", "last_activity": ts,
                           "kind": "topic", "preview": preview})
        elif tid == f"feishu:{chat_id}":
            result.append({"thread_id": tid, "label": "主对话", "last_activity": ts,
                           "kind": "main", "preview": ""})
        elif tid.startswith("feishu:thread:"):
            short = tid.split("feishu:thread:", 1)[1][:16]
            result.append({"thread_id": tid, "label": f"线程 {short}…", "last_activity": ts,
                           "kind": "thread", "preview": ""})
        else:
            result.append({"thread_id": tid, "label": tid, "last_activity": ts,
                           "kind": "other", "preview": ""})

    result.sort(key=lambda x: -x["last_activity"])
    return result


def format_topics(chat_id: str) -> str:
    """生成话题列表，供 /topics 命令返回给用户。显示所有历史对话 session，支持 resume。"""
    import datetime
    sessions = _get_all_sessions(chat_id)

    if not sessions:
        return (
            "当前没有历史对话记录。\n\n"
            "💡 **多话题用法**：在消息前加 `#话题名` 即可隔离上下文：\n"
            "• `#项目A 进展如何？` — 开始/切换到项目A话题\n"
            "• `#日程 明天有什么安排？` — 独立处理日程\n"
            "• `/topics` — 查看所有话题"
        )

    now = time.time()
    topic_lines = []
    thread_lines = []
    main_line = None

    for s in sessions:
        ts_str = datetime.datetime.fromtimestamp(s["last_activity"]).strftime("%m-%d %H:%M") \
            if s["last_activity"] > 0 else "未知"
        preview_str = f"「{s['preview']}」" if s.get("preview") else ""

        if s["kind"] == "topic":
            topic_lines.append(f"• `{s['label']}` — {ts_str} {preview_str}")
        elif s["kind"] == "main":
            main_line = f"• 主对话 — {ts_str}（直接发消息即可继续）"
        elif s["kind"] == "thread":
            thread_lines.append(f"• {s['label']} — {ts_str}（在原飞书话题里回复即可继续）")

    lines = []
    if main_line:
        lines.append("**主对话：**\n")
        lines.append(main_line)
    if topic_lines:
        if lines:
            lines.append("")
        lines.append(f"**命名话题（{len(topic_lines)} 个）：**\n")
        lines.extend(topic_lines)
    if thread_lines:
        if lines:
            lines.append("")
        lines.append(f"**飞书话题线程（{len(thread_lines)} 个）：**\n")
        lines.extend(thread_lines)

    lines.append(
        "\n💡 命名话题：发 `#话题名 消息` 恢复（历史记录完整保留）\n"
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
