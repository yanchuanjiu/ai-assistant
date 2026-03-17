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

    logger.info(f"[飞书长连接] user={user_id} chat={chat_id} msg={text[:80]}")

    # 在新线程里跑 Agent，避免阻塞 WebSocket 事件循环
    def run():
        try:
            reply = invoke(
                message=text,
                platform="feishu",
                user_id=user_id,
                chat_id=chat_id,
            )
            FeishuBot().send_text(chat_id=chat_id, text=reply)
        except Exception as e:
            logger.error(f"[飞书] Agent 处理失败: {e}")
            FeishuBot().send_text(chat_id=chat_id, text=f"处理出错：{e}")

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
