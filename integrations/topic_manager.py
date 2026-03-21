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
import threading
from collections import defaultdict

_topics: dict[str, dict[str, dict]] = defaultdict(dict)
_lock = threading.Lock()

_TOPIC_TTL = 86400 * 7  # 7天不活跃则过期
_MAX_TOPICS_PER_CHAT = 20  # 单个聊天最多话题数


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
    """注册/更新话题活跃状态。"""
    with _lock:
        _topics[chat_id][topic_name] = {
            "thread_id": thread_id,
            "last_activity": time.time(),
            "preview": preview[:60],
        }


def get_topics(chat_id: str) -> dict[str, dict]:
    """返回指定 chat 下所有未过期的活跃话题，按最后活动时间降序排列。"""
    now = time.time()
    with _lock:
        active = {
            k: v for k, v in _topics[chat_id].items()
            if now - v["last_activity"] < _TOPIC_TTL
        }
        _topics[chat_id] = active
        return dict(sorted(active.items(), key=lambda x: -x[1]["last_activity"]))


def format_topics(chat_id: str) -> str:
    """生成话题列表的可读文本，供 /topics 命令返回给用户。"""
    import datetime
    topics = get_topics(chat_id)
    if not topics:
        return (
            "当前没有活跃话题。\n\n"
            "💡 **多话题用法**：在消息前加 `#话题名` 即可隔离上下文：\n"
            "• `#项目A 进展如何？` — 开始/切换到项目A话题\n"
            "• `#日程 明天有什么安排？` — 独立处理日程\n"
            "• `/topics` — 查看所有活跃话题"
        )
    lines = [f"**活跃话题（{len(topics)} 个）：**\n"]
    for name, info in topics.items():
        ts = datetime.datetime.fromtimestamp(info["last_activity"]).strftime("%m-%d %H:%M")
        preview = info["preview"]
        preview_str = f"「{preview}」" if preview else ""
        lines.append(f"• `#{name}` — 最后活动 {ts} {preview_str}")
    lines.append("\n发 `#话题名 消息` 继续对话，发 `/topics` 刷新列表")
    return "\n".join(lines)


# 欢迎消息（含多话题引导）
WELCOME_MESSAGE = (
    "你好！有什么可以帮你的？\n\n"
    "💡 **同一窗口，多话题并行**：\n"
    "• `#项目A 进展如何？` — 在项目A话题下问\n"
    "• `#日程 明天有什么安排？` — 切换到日程话题\n"
    "• `/topics` — 查看所有活跃话题\n"
    "• `/clear` — 清空当前话题历史"
)
