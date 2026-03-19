"""
飞书机器人 — 长连接模式（WebSocket，无需公网 Webhook）
使用官方 lark-oapi SDK: pip install lark-oapi
"""
import json
import logging
import threading

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    CreateMessageRequest,
    CreateMessageRequestBody,
)
from pydantic_settings import BaseSettings
from integrations.feishu.client import feishu_post, feishu_delete

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
# 纯函数：消息解析（无副作用，可单测）
# --------------------------------------------------------------------------- #
def _parse_feishu_message(data: P2ImMessageReceiveV1) -> dict | None:
    """
    解析飞书消息事件，返回标准化 dict 或 None（非文本/空消息返回 None）。

    返回字段：text, user_id, chat_id, message_id, thread_id
    thread_id 规则：
      - 帖子内回复（root_id 非空）→ feishu:thread:{root_id}（独立会话）
      - 普通群聊/单聊 → feishu:{chat_id}
    """
    msg = data.event.message
    sender = data.event.sender

    if msg.message_type != "text":
        return None

    try:
        content = json.loads(msg.content)
        text = content.get("text", "").strip()
    except Exception:
        return None

    if not text:
        return None

    chat_id = msg.chat_id or ""
    root_id = getattr(msg, "root_id", None) or ""
    thread_id = f"feishu:thread:{root_id}" if root_id else f"feishu:{chat_id}"

    return {
        "text": text,
        "user_id": sender.sender_id.open_id or "",
        "chat_id": chat_id,
        "message_id": msg.message_id or "",
        "thread_id": thread_id,
    }


def _handle_slash_command(text: str, thread_id: str, chat_id: str) -> str | None:
    """
    处理斜杠命令。返回响应文本，如果不是已知命令则返回 None。

    支持的命令：
      /status — 查看服务状态
      /clear  — 清空当前会话历史
      /stop   — 停止当前 Claude Code 会话
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

    return None


def _run_agent(parsed: dict, bot: "FeishuBot") -> None:
    """在线程中运行 agent，发送回复。"""
    from graph.agent import invoke

    processing_reaction_id = bot.add_reaction(parsed["message_id"], "Typing")
    try:
        reply = invoke(
            message=parsed["text"],
            platform="feishu",
            user_id=parsed["user_id"],
            chat_id=parsed["chat_id"],
        )
        bot.send_text(chat_id=parsed["chat_id"], text=reply)
        bot.remove_reaction(parsed["message_id"], processing_reaction_id)
        bot.add_reaction(parsed["message_id"], "OK")
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

    text = parsed["text"]
    thread_id = parsed["thread_id"]
    chat_id = parsed["chat_id"]

    logger.info(f"[飞书长连接] user={parsed['user_id']} chat={chat_id} thread={thread_id} msg={text[:80]}")

    bot = FeishuBot()

    # 注册 reply_fn（绑定到 thread_id，供工具回调使用）
    reply_fn_registry[thread_id] = lambda t, _cid=chat_id: bot.send_text(chat_id=_cid, text=t)

    # ── 斜杠命令（优先处理）────────────────────────────────────────────
    if text.startswith("/"):
        resp = _handle_slash_command(text, thread_id, chat_id)
        if resp is not None:
            bot.send_text(chat_id=chat_id, text=resp)
            return

    # ── 检查是否有活跃 Claude Code 会话 ──────────────────────────────
    if session_manager.get(thread_id):
        session_manager.relay_input(thread_id, text)
        bot.send_text(chat_id=chat_id, text="↩️ 已转发给 Claude")
        return

    # ── 正常 Agent 流程 ───────────────────────────────────────────────
    threading.Thread(target=_run_agent, args=(parsed, bot), daemon=True).start()


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

    def send_text(self, chat_id: str, text: str):
        if not chat_id:
            logger.warning("[飞书] chat_id 为空，跳过发送")
            return

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
            logger.error(
                f"[飞书] 发消息失败: code={resp.code} msg={resp.msg}"
            )
