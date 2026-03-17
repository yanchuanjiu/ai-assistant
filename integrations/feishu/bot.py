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
# 消息处理
# --------------------------------------------------------------------------- #
def _on_message(data: P2ImMessageReceiveV1) -> None:
    from graph.agent import invoke  # 延迟导入避免循环
    from integrations.claude_code.session import reply_fn_registry, session_manager

    msg = data.event.message
    sender = data.event.sender

    if msg.message_type != "text":
        return

    try:
        content = json.loads(msg.content)
        text = content.get("text", "").strip()
    except Exception:
        return

    if not text:
        return

    user_id = sender.sender_id.open_id or ""
    chat_id = msg.chat_id or ""
    message_id = msg.message_id or ""
    thread_id = f"feishu:{chat_id}"

    logger.info(f"[飞书长连接] user={user_id} chat={chat_id} msg={text[:80]}")

    bot = FeishuBot()

    # 注册 reply_fn（每次消息更新，确保 chat_id 绑定正确）
    reply_fn_registry[thread_id] = lambda t, _cid=chat_id: bot.send_text(chat_id=_cid, text=t)

    # ── 检查是否有活跃 Claude Code 会话 ──────────────────────────────
    if session_manager.get(thread_id):
        session_manager.relay_input(thread_id, text)
        bot.send_text(chat_id=chat_id, text="↩️ 已转发给 Claude")
        return

    # ── 正常 Agent 流程 ───────────────────────────────────────────────
    def run():
        processing_reaction_id = bot.add_reaction(message_id, "THUMBSUP")
        try:
            reply = invoke(
                message=text,
                platform="feishu",
                user_id=user_id,
                chat_id=chat_id,
            )
            bot.send_text(chat_id=chat_id, text=reply)
            bot.remove_reaction(message_id, processing_reaction_id)
            bot.add_reaction(message_id, "OK")
        except Exception as e:
            logger.error(f"[飞书] Agent 处理失败: {e}")
            bot.remove_reaction(message_id, processing_reaction_id)
            bot.send_text(chat_id=chat_id, text=f"处理出错：{e}")

    threading.Thread(target=run, daemon=True).start()


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
