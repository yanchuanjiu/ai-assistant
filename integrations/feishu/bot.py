"""
飞书机器人 — 长连接模式（WebSocket，无需公网 Webhook）
使用官方 lark-oapi SDK: pip install lark-oapi
"""
import json
import logging
import sqlite3
import threading
import time

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)
from pydantic_settings import BaseSettings
from integrations.feishu.client import feishu_post, feishu_delete, feishu_get

logger = logging.getLogger(__name__)


class FeishuBotSettings(BaseSettings):
    feishu_app_id: str = ""
    feishu_app_secret: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


_cfg = FeishuBotSettings()

# 全局 lark client（用于发消息）
_lark_client = lark.Client.builder() \
    .app_id(_cfg.feishu_app_id) \
    .app_secret(_cfg.feishu_app_secret) \
    .log_level(lark.LogLevel.WARNING) \
    .build()

# --------------------------------------------------------------------------- #
# 消息去重（防止 WebSocket 断线重连时重放同一消息）
# --------------------------------------------------------------------------- #
_seen_message_ids: dict[str, float] = {}
_seen_lock = threading.Lock()
_DEDUP_TTL = 120  # 2 分钟内相同 message_id 视为重复

# --------------------------------------------------------------------------- #
# 话题锚点（thread reply）：记录每个 thread_id 的第一条消息 ID
# 后续回复使用 reply_in_thread 模式，利用飞书线程隔离上下文
# --------------------------------------------------------------------------- #
_thread_anchor: dict[str, str] = {}          # thread_id  → anchor message_id
_anchor_to_thread: dict[str, str] = {}       # message_id → thread_id（反向映射）
_anchor_lock = threading.Lock()

# SQLite 持久化（重启后 root_id 路由仍有效）
_anchor_db: sqlite3.Connection | None = None
_anchor_db_lock = threading.Lock()
_ANCHOR_TTL = 86400 * 7  # 7 天 TTL


def _get_anchor_db() -> sqlite3.Connection:
    """懒加载 SQLite 连接，首次调用时建表并加载历史记录到内存。"""
    global _anchor_db
    if _anchor_db is not None:
        return _anchor_db
    with _anchor_db_lock:
        if _anchor_db is not None:
            return _anchor_db
        import os
        os.makedirs("data", exist_ok=True)
        conn = sqlite3.connect("data/memory.db", check_same_thread=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feishu_anchors (
                message_id TEXT PRIMARY KEY,
                thread_id  TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.commit()
        # 加载未过期条目到内存
        now = time.time()
        rows = conn.execute(
            "SELECT message_id, thread_id FROM feishu_anchors WHERE created_at > ?",
            (now - _ANCHOR_TTL,),
        ).fetchall()
        with _anchor_lock:
            for msg_id, tid in rows:
                _anchor_to_thread[msg_id] = tid
        logger.info(f"[飞书] 已加载 {len(rows)} 条 anchor 记录（跨重启保持线程路由）")
        _anchor_db = conn
        return conn


def _persist_anchor(message_id: str, thread_id: str) -> None:
    """将 message_id → thread_id 持久化到 SQLite（异步写，失败不影响主流程）。"""
    try:
        db = _get_anchor_db()
        db.execute(
            "INSERT OR REPLACE INTO feishu_anchors (message_id, thread_id, created_at) VALUES (?, ?, ?)",
            (message_id, thread_id, time.time()),
        )
        db.commit()
    except Exception as e:
        logger.warning(f"[飞书] anchor 持久化失败: {e}")


def _is_duplicate(message_id: str) -> bool:
    """检查 message_id 是否已处理过，同时清理过期条目。"""
    now = time.time()
    with _seen_lock:
        expired = [k for k, v in _seen_message_ids.items() if now - v > _DEDUP_TTL]
        for k in expired:
            del _seen_message_ids[k]
        if message_id in _seen_message_ids:
            return True
        _seen_message_ids[message_id] = now
        return False


# --------------------------------------------------------------------------- #
# 每话题串行锁（防止同一话题并发处理导致乱序；不同话题可并行）
# --------------------------------------------------------------------------- #
_topic_locks: dict[str, threading.Lock] = {}
_topic_locks_mutex = threading.Lock()


def _get_topic_lock(thread_id: str) -> threading.Lock:
    """按 thread_id（含话题前缀）加锁，不同话题可并行处理。"""
    with _topic_locks_mutex:
        if thread_id not in _topic_locks:
            _topic_locks[thread_id] = threading.Lock()
        return _topic_locks[thread_id]


# --------------------------------------------------------------------------- #
# 消息类型中文标签
# --------------------------------------------------------------------------- #
_MSG_TYPE_LABELS: dict[str, str] = {
    "image": "图片",
    "file": "文件",
    "audio": "语音",
    "video": "视频",
    "sticker": "表情包",
    "media": "媒体",
    "interactive": "卡片消息",
    "merge_forward": "合并转发消息",
    "location": "位置",
    "hongbao": "红包",
    "share_card": "名片",
    "post": "富文本",
    "system": "系统消息",
}


# --------------------------------------------------------------------------- #
# 合并转发消息展开
# --------------------------------------------------------------------------- #
def _expand_merge_forward(content_str: str) -> str:
    """
    尝试展开合并转发消息的子消息文本。
    content JSON 含 merge_forward_id，通过 IM API 获取子消息列表。
    失败时返回简单描述。
    """
    try:
        content = json.loads(content_str)
        merge_forward_id = content.get("merge_forward_id", "")
        if not merge_forward_id:
            return "[合并转发消息，无法获取内容]"

        # 获取转发消息的子消息列表
        resp = feishu_get(
            "/im/v1/messages",
            params={
                "container_id_type": "merge_forward_chat",
                "container_id": merge_forward_id,
                "page_size": 30,
                "sort_type": "ByCreateTimeAsc",
            },
        )
        items = resp.get("data", {}).get("items", [])
        if not items:
            return "[合并转发消息（无法读取内容，可能需要权限）]"

        lines = [f"[合并转发消息，共 {len(items)} 条：]"]
        for item in items:
            sender_id = item.get("sender", {}).get("id", "?")
            msg_type = item.get("msg_type", "text")
            body_content = item.get("body", {}).get("content", "")
            if msg_type == "text":
                try:
                    text = json.loads(body_content).get("text", body_content)
                except Exception:
                    text = body_content
            elif msg_type == "image":
                text = "[图片]"
            elif msg_type in ("file", "audio", "video"):
                text = f"[{_MSG_TYPE_LABELS.get(msg_type, msg_type)}]"
            else:
                text = f"[{msg_type}]"
            lines.append(f"  · {sender_id}: {text[:200]}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[飞书] 展开合并转发消息失败: {e}")
        return "[合并转发消息，展开失败，请告知具体内容]"


# --------------------------------------------------------------------------- #
# 纯函数：消息解析（无副作用，可单测）
# --------------------------------------------------------------------------- #
def _parse_feishu_message(data: P2ImMessageReceiveV1) -> dict | None:
    """
    解析飞书消息事件，返回标准化 dict 或 None（系统消息等返回 None）。

    返回字段：text, user_id, chat_id, message_id, thread_id, root_id, msg_type
    thread_id 规则：
      - 帖子内回复（root_id 非空）→ 从反向映射查找已知话题 thread_id
      - 反向映射未命中（未知线程）→ feishu:{chat_id}（回退到主聊天上下文，避免孤立会话）
      - 普通群聊/单聊 → feishu:{chat_id}
    root_id 字段：原始 root_id，供 _run_agent 用于精确线程回复定位。
    """
    msg = data.event.message
    sender = data.event.sender

    msg_type = msg.message_type or "text"
    chat_id = msg.chat_id or ""
    root_id = getattr(msg, "root_id", None) or ""
    if root_id:
        # 优先从反向映射查找已知话题 thread_id（重启后也有效，已从 SQLite 恢复）
        # 未命中时回退到 feishu:{chat_id}（比创建孤立新会话更好：保留对话历史）
        thread_id = _anchor_to_thread.get(root_id) or f"feishu:{chat_id}"
    else:
        thread_id = f"feishu:{chat_id}"
    message_id = msg.message_id or ""
    user_id = sender.sender_id.open_id or ""

    # 系统消息直接忽略
    if msg_type == "system":
        return None

    try:
        content_str = msg.content or "{}"
    except Exception:
        content_str = "{}"

    # ── 文本消息 ────────────────────────────────────────────────────────────
    if msg_type == "text":
        try:
            text = json.loads(content_str).get("text", "").strip()
        except Exception:
            text = content_str.strip()
        if not text:
            return None
        return {
            "text": text,
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "thread_id": thread_id,
            "root_id": root_id,
            "msg_type": "text",
        }

    # ── 富文本消息（post）：提取纯文本 ────────────────────────────────────
    if msg_type == "post":
        try:
            post_data = json.loads(content_str)
            zh = post_data.get("zh_cn") or post_data.get("en_us") or {}
            parts = []
            for para in zh.get("content", []):
                for el in para:
                    if el.get("tag") in ("text", "md"):
                        parts.append(el.get("text", ""))
            text = " ".join(parts).strip() or "[富文本消息]"
        except Exception:
            text = "[富文本消息]"
        return {
            "text": text,
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "thread_id": thread_id,
            "root_id": root_id,
            "msg_type": "post",
        }

    # ── 合并转发消息 ──────────────────────────────────────────────────────
    if msg_type == "merge_forward":
        text = _expand_merge_forward(content_str)
        return {
            "text": text,
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "thread_id": thread_id,
            "root_id": root_id,
            "msg_type": "merge_forward",
        }

    # ── 图片消息：传递文件 key 供 AI 参考 ───────────────────────────────
    if msg_type == "image":
        try:
            img_data = json.loads(content_str)
            image_key = img_data.get("image_key", "")
            text = f"[收到图片，image_key={image_key}，暂时还不能直接分析图片内容，请描述你想问什么]"
        except Exception:
            text = "[收到图片消息]"
        return {
            "text": text,
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "thread_id": thread_id,
            "root_id": root_id,
            "msg_type": "image",
        }

    # ── 文件/音频/视频：传递文件名 ─────────────────────────────────────
    if msg_type in ("file", "audio", "video"):
        try:
            file_data = json.loads(content_str)
            file_name = file_data.get("file_name", "") or file_data.get("file_key", "")
            file_key = file_data.get("file_key", "")
            duration = file_data.get("duration", "")
            label = _MSG_TYPE_LABELS.get(msg_type, msg_type)
            # Excel 文件：提供可直接用于 excel_import 工具的 file_source
            if msg_type == "file" and file_name.lower().endswith((".xlsx", ".xls")):
                text = (
                    f"[收到 Excel 文件：{file_name}，"
                    f"可使用 excel_import 工具导入。"
                    f"file_source=feishu_im:{message_id}:{file_key}]"
                )
            else:
                info = f"文件名：{file_name}" if file_name else ""
                if duration:
                    info += f"，时长：{duration}ms"
                text = f"[收到{label}消息{('，' + info) if info else ''}，暂不支持处理，请发文字说明需求]"
        except Exception:
            label = _MSG_TYPE_LABELS.get(msg_type, msg_type)
            text = f"[收到{label}消息，暂不支持处理]"
        return {
            "text": text,
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "thread_id": thread_id,
            "root_id": root_id,
            "msg_type": msg_type,
        }

    # ── 卡片消息（interactive）：提取文本 ───────────────────────────────
    if msg_type == "interactive":
        try:
            card_data = json.loads(content_str)
            # 卡片 body 中的文本块
            elements = card_data.get("body", {}).get("elements", []) or card_data.get("elements", [])
            texts = []
            for el in elements:
                if el.get("tag") == "plain_text":
                    texts.append(el.get("content", ""))
                elif el.get("tag") == "markdown":
                    texts.append(el.get("content", ""))
            text = " ".join(texts).strip() or "[卡片消息，无法提取文字内容]"
        except Exception:
            text = "[卡片消息]"
        return {
            "text": text,
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "thread_id": thread_id,
            "root_id": root_id,
            "msg_type": "interactive",
        }

    # ── 其他类型：友好提示 ───────────────────────────────────────────────
    label = _MSG_TYPE_LABELS.get(msg_type, msg_type)
    return {
        "text": f"[收到{label}，暂不支持处理，请发文字消息]",
        "user_id": user_id,
        "chat_id": chat_id,
        "message_id": message_id,
        "thread_id": thread_id,
        "root_id": root_id,
        "msg_type": msg_type,
    }


def _handle_slash_command(text: str, thread_id: str, chat_id: str) -> str | None:
    """
    处理斜杠命令。返回响应文本，如果不是已知命令则返回 None。

    支持的命令：
      /status — 查看服务状态
      /clear  — 清空当前会话历史
      /stop   — 停止当前 Claude Code 会话
      /topics — 查看所有活跃话题
    """
    parts = text.strip().split()
    cmd = parts[0].lower() if parts else ""

    if cmd == "/status":
        from graph.tools import get_service_status
        return get_service_status.invoke({})

    elif cmd == "/clear":
        from graph.agent import clear_history
        ok = clear_history(thread_id)
        return "✅ 对话历史已清空" if ok else "❌ 清空失败，请查看日志"

    elif cmd == "/stop":
        from integrations.claude_code.session import session_manager
        if session_manager.get(thread_id):
            session_manager.kill(thread_id)
            return "✅ Claude 会话已停止"
        return "当前没有运行中的 Claude 会话"

    elif cmd == "/topics":
        from integrations.topic_manager import format_topics
        return format_topics(chat_id)

    return None


def _run_agent(parsed: dict, bot: "FeishuBot") -> None:
    """在线程中运行 agent（已持有话题锁），发送回复。"""
    from graph.agent import invoke

    processing_reaction_id = bot.add_reaction(parsed["message_id"], "Typing")
    try:
        reply = invoke(
            message=parsed["text"],
            platform="feishu",
            user_id=parsed["user_id"],
            chat_id=parsed["chat_id"],
            thread_id=parsed["thread_id"],
        )
        # ── 回复定位策略 ───────────────────────────────────────────────────
        # root_id 非空 = 用户在飞书话题/线程窗口回复，需把机器人回复打到同一线程
        # root_id 为空 = 普通主聊天消息，走 send_text 保持原有行为
        root_id = parsed.get("root_id", "")
        # 优先用 root_id 作为回复锚点（确保落入同一话题窗口）；否则用注册的首条锚点
        anchor = root_id or _get_anchor(parsed["thread_id"])
        default_thread_id = f"feishu:{parsed['chat_id']}"
        # 满足以下任一条件时走 reply_in_thread：
        # 1. 话题前缀消息（thread_id != default）
        # 2. 用户从飞书话题/线程窗口回复（root_id 非空）
        is_threaded = parsed["thread_id"] != default_thread_id or bool(root_id)
        sent = False
        if anchor and is_threaded:
            sent = bot.reply_in_thread(anchor, reply, thread_id=parsed["thread_id"])
        if not sent:
            bot_msg_id = bot.send_text(chat_id=parsed["chat_id"], text=reply)
            sent = bool(bot_msg_id)
            # 注册机器人消息 ID：让用户后续回复该消息时能找到正确上下文
            if bot_msg_id and isinstance(bot_msg_id, str) and bot_msg_id not in ("True", "sent"):
                with _anchor_lock:
                    _anchor_to_thread[bot_msg_id] = parsed["thread_id"]
                _persist_anchor(bot_msg_id, parsed["thread_id"])
        bot.remove_reaction(parsed["message_id"], processing_reaction_id)
        if sent:
            bot.add_reaction(parsed["message_id"], "OK")
        else:
            bot.send_text(
                chat_id=parsed["chat_id"],
                text="⚠️ 回复生成成功但发送失败，请重试或查看服务日志。",
            )
    except Exception as e:
        logger.error(f"[飞书] Agent 处理失败: {e}")
        bot.remove_reaction(parsed["message_id"], processing_reaction_id)
        bot.send_text(chat_id=parsed["chat_id"], text=f"处理出错：{e}")


# --------------------------------------------------------------------------- #
# 消息处理（协调层）
# --------------------------------------------------------------------------- #
def _on_message(data: P2ImMessageReceiveV1) -> None:
    from integrations.claude_code.session import reply_fn_registry, session_manager

    parsed = _parse_feishu_message(data)
    if not parsed:
        return

    message_id = parsed["message_id"]
    text = parsed["text"]
    thread_id = parsed["thread_id"]
    chat_id = parsed["chat_id"]
    msg_type = parsed.get("msg_type", "text")

    # ── 去重：防止断线重连时重放 ────────────────────────────────────────
    if message_id and _is_duplicate(message_id):
        logger.info(f"[飞书] 跳过重复消息 message_id={message_id}")
        return

    logger.info(f"[飞书长连接] user={parsed['user_id']} chat={chat_id} thread={thread_id} type={msg_type} msg={text[:80]}")

    bot = FeishuBot()

    # ── 登记线程锚点：首条消息的 message_id 作为后续 reply_in_thread 基准 ──
    _set_anchor(thread_id, message_id)

    # 注册 reply_fn（绑定到 thread_id，供工具回调使用）
    reply_fn_registry[thread_id] = lambda t, _cid=chat_id: bot.send_text(chat_id=_cid, text=t)

    # ── 斜杠命令（优先处理，不走 chat lock）──────────────────────────────
    if text.startswith("/") and msg_type == "text":
        resp = _handle_slash_command(text, thread_id, chat_id)
        if resp is not None:
            bot.send_text(chat_id=chat_id, text=resp)
            return

    # ── 话题解析：#话题名 前缀 → 隔离对话上下文 ──────────────────────────
    from integrations.topic_manager import (
        extract_topic, make_topic_thread_id, register_topic, WELCOME_MESSAGE,
    )
    topic_name, cleaned_text = extract_topic(text)
    if topic_name:
        thread_id = make_topic_thread_id("feishu", chat_id, topic_name)
        text = cleaned_text  # 去掉前缀后的实际消息
        parsed["text"] = text
        parsed["thread_id"] = thread_id
        register_topic(chat_id, topic_name, thread_id, preview=text[:60])
        # 话题首条消息也登记锚点（话题 thread_id 维度）
        _set_anchor(thread_id, message_id)
        # 重新注册 reply_fn（绑定到话题 thread_id）
        reply_fn_registry[thread_id] = lambda t, _cid=chat_id: bot.send_text(chat_id=_cid, text=t)

    # ── 问候快速路径（0ms，不走 LLM）────────────────────────────────────
    _GREETINGS = {"你好", "hi", "hello", "嗨", "哈喽", "在吗", "在不在", "hey", "yo", "早", "早上好"}
    if text.strip().lower() in _GREETINGS and msg_type == "text" and not topic_name:
        bot.send_text(chat_id=chat_id, text=WELCOME_MESSAGE)
        return

    # ── 检查是否有活跃 Claude Code 会话 ──────────────────────────────────
    if session_manager.get(thread_id) and msg_type == "text":
        session_manager.relay_input(thread_id, text)
        bot.send_text(chat_id=chat_id, text="↩️ 已转发给 Claude")
        return

    # 话题消息但内容为空：只切换话题，不触发 Agent
    if topic_name and not text:
        from integrations.topic_manager import format_topics
        bot.send_text(chat_id=chat_id, text=f"已切换到话题 **#{topic_name}**\n\n{format_topics(chat_id)}")
        return

    # ── 正常 Agent 流程（每话题串行，不同话题可并行）────────────────────────
    topic_lock = _get_topic_lock(thread_id)

    def _run_with_lock():
        with topic_lock:
            _run_agent(parsed, bot)

    threading.Thread(target=_run_with_lock, daemon=True).start()


# --------------------------------------------------------------------------- #
# 长连接客户端
# --------------------------------------------------------------------------- #
def start_feishu_longconn():
    """启动飞书长连接，阻塞运行（在独立线程中调用）。"""
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_message)
        .build()
    )

    ws_client = lark.ws.Client(
        _cfg.feishu_app_id,
        _cfg.feishu_app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.WARNING,
    )

    logger.info("[飞书] 长连接启动中...")
    ws_client.start()  # 阻塞


# --------------------------------------------------------------------------- #
# 发消息（REST API）
# --------------------------------------------------------------------------- #
def _get_anchor(thread_id: str) -> str | None:
    """返回 thread_id 对应的锚点消息 ID（线程首消息），无则返回 None。"""
    return _thread_anchor.get(thread_id)


def _set_anchor(thread_id: str, message_id: str) -> None:
    """登记 thread_id 的锚点（仅首次有效），同时维护反向映射并持久化。"""
    if not message_id:
        return
    with _anchor_lock:
        if thread_id not in _thread_anchor:
            _thread_anchor[thread_id] = message_id
            _anchor_to_thread[message_id] = thread_id
    _persist_anchor(message_id, thread_id)


class FeishuBot:
    def add_reaction(self, message_id: str, emoji_type: str) -> str:
        """给消息加 emoji reaction，返回 reaction_id（删除时用）。"""
        if not message_id:
            return ""
        try:
            resp = feishu_post(
                f"/im/v1/messages/{message_id}/reactions",
                json={"reaction_type": {"emoji_type": emoji_type}},
            )
            return resp.get("data", {}).get("reaction_id", "")
        except Exception as e:
            logger.warning(f"[飞书] 添加 reaction 失败: {e}")
            return ""

    def remove_reaction(self, message_id: str, reaction_id: str):
        """删除消息上的 emoji reaction。"""
        if not message_id or not reaction_id:
            return
        try:
            feishu_delete(f"/im/v1/messages/{message_id}/reactions/{reaction_id}")
        except Exception as e:
            logger.warning(f"[飞书] 删除 reaction 失败: {e}")

    def reply_in_thread(self, anchor_message_id: str, text: str, thread_id: str = "") -> bool:
        """
        回复指定消息，并在其线程中展示（reply_in_thread=True）。
        用于话题/线程上下文的所有回复（含首条），使飞书 UI 自动形成线程视图。
        失败时返回 False（调用方可降级为 send_text）。

        thread_id: 传入后，bot 回复的 message_id 也会注册进反向映射，
                   确保后续 root_id 路由始终能找到正确话题上下文。
        """
        if not anchor_message_id:
            return False
        # 超长消息降级走 send_text 的存 wiki 逻辑：这里只做 ≤800 字符的快路径
        _IM_LIMIT = 800
        if len(text) > _IM_LIMIT:
            return False  # 让调用方降级到 send_text
        content = json.dumps(
            {"zh_cn": {"content": [[{"tag": "md", "text": text}]]}},
            ensure_ascii=False,
        )
        request = (
            ReplyMessageRequest.builder()
            .message_id(anchor_message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type("post")
                .content(content)
                .reply_in_thread(True)
                .build()
            )
            .build()
        )
        resp = _lark_client.im.v1.message.reply(request)
        if not resp.success():
            logger.warning(f"[飞书] reply_in_thread 失败(code={resp.code}): {resp.msg}")
            return False
        # 注册 bot 回复的 message_id 到反向映射
        # 飞书同一线程中所有消息共享同一 root_id（= anchor_message_id），
        # 但保留 bot 消息 ID 方便未来扩展
        if thread_id:
            try:
                bot_msg_id = getattr(getattr(resp, "data", None), "message_id", None)
                if bot_msg_id:
                    with _anchor_lock:
                        _anchor_to_thread[bot_msg_id] = thread_id
                    _persist_anchor(bot_msg_id, thread_id)
            except Exception:
                pass
        return True

    def _send_single(self, chat_id: str, text: str) -> str | None:
        """
        发送单条消息（post 富文本格式，支持 Markdown 渲染）。
        返回消息 message_id（成功）或 None（失败）。
        """
        content = json.dumps(
            {"zh_cn": {"content": [[{"tag": "md", "text": text}]]}},
            ensure_ascii=False,
        )
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("post")
                .content(content)
                .build()
            )
            .build()
        )
        resp = _lark_client.im.v1.message.create(request)
        if not resp.success():
            logger.warning(
                f"[飞书] post 格式发送失败(code={resp.code})，降级纯文本: {resp.msg}"
            )
            # 降级：用纯文本重试
            return self._send_single_text(chat_id, text)
        try:
            return resp.data.message_id or "sent"
        except Exception:
            return "sent"

    def _send_single_text(self, chat_id: str, text: str) -> str | None:
        """纯文本降级发送（post 失败时使用）。返回 message_id 或 None。"""
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .build()
            )
            .build()
        )
        resp = _lark_client.im.v1.message.create(request)
        if not resp.success():
            logger.error(f"[飞书] 发消息失败: code={resp.code} msg={resp.msg}")
            return None
        try:
            return resp.data.message_id or "sent"
        except Exception:
            return "sent"

    def send_text(self, chat_id: str, text: str) -> str | None:
        """发送文本消息，超长时自动存飞书并发摘要+链接。返回 message_id（成功）或 None（失败）。"""
        if not chat_id:
            logger.warning("[飞书] chat_id 为空，跳过发送")
            return None

        # IM 回复字符上限：超出时存飞书+发摘要
        _IM_LIMIT = 800
        if len(text) <= _IM_LIMIT:
            return self._send_single(chat_id, text)

        # ── 兜底：存飞书知识库，IM 发摘要+链接 ──────────────────────────
        try:
            wiki_token = self._save_to_feishu_wiki(text)
            if wiki_token:
                summary = text[:300].rstrip() + "…" if len(text) > 300 else text
                link_text = (
                    f"{summary}\n\n"
                    f"📄 详细内容：https://feishu.cn/wiki/{wiki_token}"
                )
                return self._send_single(chat_id, link_text)
        except Exception as e:
            logger.warning(f"[飞书] 存知识库失败，降级分段发送: {e}")

        # ── 最终降级：按段落分割 ──────────────────────────────────────
        _CHUNK_LIMIT = 3800
        chunks: list[str] = []
        current = ""
        for para in text.split("\n"):
            line = para + "\n"
            if len(current) + len(line) > _CHUNK_LIMIT:
                if current:
                    chunks.append(current.rstrip())
                current = line
            else:
                current += line
        if current.strip():
            chunks.append(current.rstrip())

        first_id: str | None = None
        for i, chunk in enumerate(chunks):
            prefix = f"（{i+1}/{len(chunks)}）\n" if len(chunks) > 1 else ""
            msg_id = self._send_single(chat_id, prefix + chunk)
            if msg_id and first_id is None:
                first_id = msg_id
        return first_id

    def _save_to_feishu_wiki(self, text: str) -> str:
        """
        将长文本追加到飞书知识库"📝 AI 回复详情"页，返回 wiki node_token。
        失败时抛出异常，由调用方决定降级策略。
        自动处理缓存失效：若写入失败（页面被删除/移动），清缓存后重新创建。
        """
        import os
        from datetime import datetime
        from integrations.feishu.knowledge import FeishuKnowledge
        from integrations.storage.config_store import delete as cfg_delete

        context_page = os.getenv("FEISHU_WIKI_CONTEXT_PAGE", "")
        if not context_page:
            raise ValueError("FEISHU_WIKI_CONTEXT_PAGE 未配置")

        wiki = FeishuKnowledge()

        def _get_page_token():
            return wiki.find_or_create_child_page(
                title="📝 AI 回复详情",
                parent_wiki_token=context_page,
                cache_key="AI_REPLY_DETAIL_PAGE",
            )

        page_token = _get_page_token()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = f"## {timestamp} 回复\n\n{text}\n\n---\n"

        try:
            wiki.append_to_page(page_token, content)
        except Exception:
            logger.warning(f"[飞书Bot] 写入详情页失败，清缓存后重试: {page_token!r}")
            cfg_delete("AI_REPLY_DETAIL_PAGE")
            page_token = _get_page_token()
            wiki.append_to_page(page_token, content)

        return page_token
