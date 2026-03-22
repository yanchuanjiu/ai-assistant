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
from integrations.base_bot import BaseBotHandler
from integrations.message_context import MessageContext

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
        # 加载未过期条目到内存，同时重建 _thread_anchor（thread_id → 最早的 anchor msg_id）
        now = time.time()
        rows = conn.execute(
            "SELECT message_id, thread_id, created_at FROM feishu_anchors WHERE created_at > ?",
            (now - _ANCHOR_TTL,),
        ).fetchall()
        thread_earliest: dict[str, tuple[float, str]] = {}
        with _anchor_lock:
            for msg_id, tid, created_at in rows:
                _anchor_to_thread[msg_id] = tid
                # 记录每个 thread_id 最早的 message_id 作为锚点
                if tid not in thread_earliest or created_at < thread_earliest[tid][0]:
                    thread_earliest[tid] = (created_at, msg_id)
            for tid, (_, msg_id) in thread_earliest.items():
                _thread_anchor[tid] = msg_id
        logger.info(f"[飞书] 已加载 {len(rows)} 条 anchor 记录，恢复 {len(thread_earliest)} 个话题锚点")
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
    parent_id = getattr(msg, "parent_id", None) or ""
    if root_id:
        # 优先从反向映射查找已知话题 thread_id（重启后也有效，已从 SQLite 恢复）
        # 未命中时回退到 feishu:{chat_id}（比创建孤立新会话更好：保留对话历史）
        thread_id = _anchor_to_thread.get(root_id) or f"feishu:{chat_id}"
    elif parent_id and parent_id in _anchor_to_thread:
        # BUG-002 修复：用户通过"引用回复"(quote-reply) 话题消息时，
        # root_id 为空但 parent_id 命中已知话题 → 路由到对应话题上下文
        thread_id = _anchor_to_thread[parent_id]
        root_id = parent_id  # 让 _send_reply 用引用消息作为 anchor，保持回复可见性
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



# --------------------------------------------------------------------------- #
# 飞书业务处理（继承 BaseBotHandler，实现平台特定接口）
# --------------------------------------------------------------------------- #
class FeishuBotHandler(BaseBotHandler):
    """飞书消息处理器，继承平台无关的 BaseBotHandler。

    平台特定实现：
    - parse_message()      — 解析飞书 P2ImMessageReceiveV1
    - send_reply()         — 话题线程走 reply_in_thread，主聊天走 send_text
    - _on_pre_handle()     — 登记锚点、注册 reply_fn
    - _on_extract_topic()  — 飞书短标题检测 + 话题路由
    - _handle_slash()      — 仅文本消息处理斜杠命令
    - _handle_greeting()   — 仅文本消息处理问候
    - _relay_claude()      — 仅文本消息中继 Claude
    - _invoke_agent()      — 话题串行锁 + _replied 短路 + 飞书 reaction
    """

    def parse_message(self, raw: P2ImMessageReceiveV1) -> MessageContext | None:
        parsed = _parse_feishu_message(raw)
        if parsed is None:
            return None
        ctx = MessageContext(
            text=parsed["text"],
            user_id=parsed["user_id"],
            chat_id=parsed["chat_id"],
            message_id=parsed["message_id"],
            thread_id=parsed["thread_id"],
            platform="feishu",
            raw=raw,
        )
        ctx.extra["root_id"] = parsed.get("root_id", "")
        ctx.extra["msg_type"] = parsed.get("msg_type", "text")
        ctx.extra["bot"] = FeishuBot()
        logger.info(
            f"[飞书长连接] user={ctx.user_id} chat={ctx.chat_id} "
            f"thread={ctx.thread_id} type={ctx.extra['msg_type']} msg={ctx.text[:80]}"
        )
        return ctx

    def send_reply(self, text: str, ctx: MessageContext) -> None:
        """发送回复：话题/线程走 reply_in_thread，主聊天走 send_text。"""
        bot = ctx.extra.get("bot") or FeishuBot()
        root_id = ctx.extra.get("root_id", "")
        anchor = root_id or _get_anchor(ctx.thread_id)
        is_threaded = ctx.thread_id != f"feishu:{ctx.chat_id}" or bool(root_id)

        if anchor and is_threaded:
            sent = bot.reply_in_thread(anchor, text, thread_id=ctx.thread_id)
            if sent:
                ctx.extra["_last_send_ok"] = True
                return

        bot_msg_id = bot.send_text(chat_id=ctx.chat_id, text=text)
        ctx.extra["_last_send_ok"] = bool(bot_msg_id)
        if bot_msg_id and isinstance(bot_msg_id, str) and bot_msg_id not in ("True", "sent"):
            with _anchor_lock:
                _anchor_to_thread[bot_msg_id] = ctx.thread_id
            _persist_anchor(bot_msg_id, ctx.thread_id)

    def _on_pre_handle(self, ctx: MessageContext) -> None:
        """登记线程锚点，注册 reply_fn 供工具回调使用。"""
        bot = ctx.extra.get("bot") or FeishuBot()
        ctx.extra["bot"] = bot
        _set_anchor(ctx.thread_id, ctx.message_id)
        from integrations.claude_code.session import reply_fn_registry
        reply_fn_registry[ctx.thread_id] = lambda t, _cid=ctx.chat_id: bot.send_text(chat_id=_cid, text=t)

    def _on_extract_topic(self, ctx: MessageContext) -> None:
        """飞书特有：短标题话题检测 + 话题路由。"""
        from integrations.topic_manager import (
            extract_topic, make_topic_thread_id, register_topic,
            get_topics, find_similar_topics,
        )
        from integrations.claude_code.session import reply_fn_registry
        bot = ctx.extra.get("bot") or FeishuBot()
        original_text = ctx.text
        topic_name, cleaned_text = extract_topic(ctx.text)

        is_main_window = ctx.thread_id == f"feishu:{ctx.chat_id}"
        if (topic_name and not cleaned_text and len(original_text) < 10
                and original_text.startswith("#") and is_main_window):
            existing = get_topics(ctx.chat_id)
            if topic_name not in existing:
                similar = find_similar_topics(topic_name, existing)
                if similar:
                    sim_list = "\n".join(f"• `#{n}`" for n in similar[:3])
                    self.send_reply(
                        f"发现相近话题：\n{sim_list}\n\n"
                        f"• 如需合并到已有话题，发 `#已有话题名 消息内容`\n"
                        f"• 如需新建 **#{topic_name}**，发 `#{topic_name} 消息内容`（带上正文即可创建）",
                        ctx,
                    )
                    ctx.extra["_replied"] = True
                    return
                else:
                    new_thread_id = make_topic_thread_id("feishu", ctx.chat_id, topic_name)
                    register_topic(ctx.chat_id, topic_name, new_thread_id, preview="")
                    _set_anchor(new_thread_id, ctx.message_id)
                    reply_fn_registry[new_thread_id] = lambda t, _cid=ctx.chat_id: bot.send_text(chat_id=_cid, text=t)
                    self.send_reply(
                        f"✅ 已创建新话题 **#{topic_name}**\n\n"
                        f"发 `#{topic_name} 消息内容` 即可在此话题下对话",
                        ctx,
                    )
                    ctx.extra["_replied"] = True
                    return

        if topic_name:
            ctx.topic_name = topic_name
            ctx.thread_id = make_topic_thread_id("feishu", ctx.chat_id, topic_name)
            ctx.text = cleaned_text
            register_topic(ctx.chat_id, ctx.topic_name, ctx.thread_id, preview=ctx.text[:60])
            _set_anchor(ctx.thread_id, ctx.message_id)
            reply_fn_registry[ctx.thread_id] = lambda t, _cid=ctx.chat_id: bot.send_text(chat_id=_cid, text=t)

    def _handle_slash(self, ctx: MessageContext) -> bool:
        if ctx.extra.get("msg_type") != "text":
            return False
        return super()._handle_slash(ctx)

    def _handle_greeting(self, ctx: MessageContext) -> bool:
        if ctx.extra.get("msg_type") != "text":
            return False
        return super()._handle_greeting(ctx)

    def _relay_claude(self, ctx: MessageContext) -> bool:
        if ctx.extra.get("msg_type") != "text":
            return False
        return super()._relay_claude(ctx)

    def _invoke_agent(self, ctx: MessageContext) -> None:
        """话题串行锁 + _replied 短路 + 飞书 Typing/OK reaction。"""
        if ctx.extra.get("_replied"):
            return
        bot = ctx.extra.get("bot") or FeishuBot()
        ctx.extra["bot"] = bot
        reaction_target = ctx.extra.get("root_id") or ctx.message_id
        topic_lock = _get_topic_lock(ctx.thread_id)

        def run():
            with topic_lock:
                reaction_id = bot.add_reaction(reaction_target, "Typing")
                try:
                    from graph.agent import invoke
                    reply = invoke(
                        message=ctx.text,
                        platform=ctx.platform,
                        user_id=ctx.user_id,
                        chat_id=ctx.chat_id,
                        thread_id=ctx.thread_id,
                    )
                    self.send_reply(reply, ctx)
                    bot.remove_reaction(reaction_target, reaction_id)
                    if ctx.extra.get("_last_send_ok", True):
                        bot.add_reaction(reaction_target, "OK")
                    else:
                        self.send_reply("⚠️ 回复生成成功但发送失败，请重试或查看服务日志。", ctx)
                except Exception as e:
                    logger.error(f"[飞书] Agent 处理失败: {e}", exc_info=True)
                    bot.remove_reaction(reaction_target, reaction_id)
                    self.send_reply(f"处理出错：{e}", ctx)

        threading.Thread(target=run, daemon=True).start()


_feishu_handler = FeishuBotHandler()


# --------------------------------------------------------------------------- #
# 消息处理（协调层）
# --------------------------------------------------------------------------- #
def _on_message(data: P2ImMessageReceiveV1) -> None:
    _feishu_handler.handle(data)


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

    def _reply_in_thread_single(self, anchor_message_id: str, text: str, thread_id: str = "") -> bool:
        """发送单条 reply_in_thread，注册 bot 回复 ID 到反向映射。"""
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

    def reply_in_thread(self, anchor_message_id: str, text: str, thread_id: str = "") -> bool:
        """
        回复指定消息，并在其线程中展示（reply_in_thread=True）。
        用于话题/线程上下文的所有回复（含首条），使飞书 UI 自动形成线程视图。
        长消息自动处理：先尝试存知识库发摘要链接，失败则分块发送。
        失败时返回 False（调用方可降级为 send_text）。
        """
        if not anchor_message_id:
            return False

        _IM_LIMIT = 4000  # 单条消息字符上限

        if len(text) <= _IM_LIMIT:
            return self._reply_in_thread_single(anchor_message_id, text, thread_id)

        # 超长消息：尝试存知识库，发摘要+链接到 thread
        try:
            wiki_token = self._save_to_feishu_wiki(text)
            if wiki_token:
                summary = text[:300].rstrip() + "…" if len(text) > 300 else text
                short_text = f"{summary}\n\n📄 详细内容：https://feishu.cn/wiki/{wiki_token}"
                return self._reply_in_thread_single(anchor_message_id, short_text, thread_id)
        except Exception as e:
            logger.warning(f"[飞书] thread 回复存知识库失败，降级分块: {e}")

        # 知识库失败：按段落分块，逐块 reply_in_thread
        _CHUNK = 3800
        chunks: list[str] = []
        current = ""
        for line in text.split("\n"):
            segment = line + "\n"
            if len(current) + len(segment) > _CHUNK:
                if current:
                    chunks.append(current.rstrip())
                current = segment
            else:
                current += segment
        if current.strip():
            chunks.append(current.rstrip())

        success = False
        for i, chunk in enumerate(chunks):
            prefix = f"（{i+1}/{len(chunks)}）\n" if len(chunks) > 1 else ""
            ok = self._reply_in_thread_single(
                anchor_message_id, prefix + chunk, thread_id if i == 0 else ""
            )
            if ok:
                success = True
        return success

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
