"""
飞书机器人：
- Webhook 事件接收（FastAPI router）
- 主动发送消息
"""
import hashlib
import hmac
import json
import logging
import time
import base64
from fastapi import APIRouter, Request, Response
from pydantic_settings import BaseSettings
from integrations.feishu.client import feishu_post

logger = logging.getLogger(__name__)
router = APIRouter()


class BotSettings(BaseSettings):
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


_cfg = BotSettings()


# --------------------------------------------------------------------------- #
# Webhook 入口
# --------------------------------------------------------------------------- #
@router.post("/feishu/webhook")
async def feishu_webhook(request: Request):
    body = await request.json()

    # 1. URL 验证（首次配置时飞书发送 challenge）
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    # 2. 事件分发
    schema = body.get("schema", "1.0")
    if schema == "2.0":
        event_type = body.get("header", {}).get("event_type", "")
        event = body.get("event", {})
    else:
        event_type = body.get("event", {}).get("type", "")
        event = body.get("event", {})

    if event_type == "im.message.receive_v1":
        await _handle_message(event)

    return Response(status_code=200)


async def _handle_message(event: dict):
    from graph.agent import invoke  # 延迟导入避免循环

    msg = event.get("message", {})
    sender = event.get("sender", {})

    msg_type = msg.get("message_type", "")
    if msg_type != "text":
        return  # 暂只处理文本

    content = json.loads(msg.get("content", "{}"))
    text = content.get("text", "").strip()
    if not text:
        return

    user_id = sender.get("sender_id", {}).get("open_id", "")
    chat_id = msg.get("chat_id", "")

    logger.info(f"[Feishu] user={user_id} chat={chat_id} msg={text[:80]}")
    invoke(message=text, platform="feishu", user_id=user_id, chat_id=chat_id)


# --------------------------------------------------------------------------- #
# 发送消息
# --------------------------------------------------------------------------- #
class FeishuBot:
    def send_text(self, chat_id: str, text: str):
        feishu_post(
            "/im/v1/messages",
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
        )

    def send_markdown(self, chat_id: str, markdown: str):
        """飞书卡片形式发送 Markdown 内容（富文本降级为 text）。"""
        self.send_text(chat_id, markdown)
