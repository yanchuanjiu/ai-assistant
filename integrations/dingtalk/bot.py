"""
钉钉机器人：
- Webhook 事件接收（FastAPI router）
- 主动发送消息（企业内部应用）
"""
import json
import logging
from fastapi import APIRouter, Request, Response
from pydantic_settings import BaseSettings
from integrations.dingtalk.client import dt_post, _settings as dt_settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/dingtalk/webhook")
async def dingtalk_webhook(request: Request):
    body = await request.json()
    logger.debug(f"[DingTalk] webhook body: {str(body)[:200]}")

    msg_type = body.get("msgtype", "")
    if msg_type == "text":
        await _handle_message(body)

    return Response(status_code=200)


async def _handle_message(body: dict):
    from graph.agent import invoke

    text = body.get("text", {}).get("content", "").strip()
    sender = body.get("senderStaffId", "") or body.get("senderId", "")
    conversation_id = body.get("conversationId", sender)

    if not text:
        return

    logger.info(f"[DingTalk] user={sender} msg={text[:80]}")
    invoke(message=text, platform="dingtalk", user_id=sender, chat_id=conversation_id)


class DingTalkBot:
    def send_text(self, user_id: str, text: str):
        """通过企业内部机器人发送单聊消息。"""
        dt_post(
            "/v1.0/robot/oToMessages/batchSend",
            json={
                "robotCode": dt_settings.dingtalk_client_id,
                "userIds": [user_id],
                "msgKey": "sampleText",
                "msgParam": json.dumps({"content": text}),
            },
        )
