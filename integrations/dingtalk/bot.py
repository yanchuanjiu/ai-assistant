"""
钉钉机器人 — 流模式（Stream，无需公网 Webhook）
使用官方 SDK: pip install dingtalk-stream
"""
import logging
import threading

import dingtalk_stream
from dingtalk_stream import AckMessage
from dingtalk_stream.chatbot import ChatbotHandler as _ChatbotHandlerBase
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class DingTalkBotSettings(BaseSettings):
    dingtalk_client_id: str = ""
    dingtalk_client_secret: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


_cfg = DingTalkBotSettings()


# --------------------------------------------------------------------------- #
# 消息处理 Handler
# --------------------------------------------------------------------------- #
class _BotHandler(_ChatbotHandlerBase):
    def process(self, callback: dingtalk_stream.CallbackMessage):
        from graph.agent import invoke  # 延迟导入避免循环

        incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        text = incoming.text.content.strip() if incoming.text else ""

        if not text:
            return AckMessage.STATUS_OK, "OK"

        user_id = incoming.sender_staff_id or ""
        chat_id = incoming.conversation_id or user_id

        logger.info(f"[钉钉流模式] user={user_id} msg={text[:80]}")

        # 先回复"处理中"避免钉钉超时重试（5秒限制）
        self.reply_text("处理中，请稍候...", incoming)

        # 在新线程里跑 Agent，完成后用 REST API 发结果
        def run():
            try:
                reply = invoke(
                    message=text,
                    platform="dingtalk",
                    user_id=user_id,
                    chat_id=chat_id,
                )
                DingTalkBot().send_text(user_id=user_id, text=reply)
            except Exception as e:
                logger.error(f"[钉钉] Agent 处理失败: {e}")
                DingTalkBot().send_text(user_id=user_id, text=f"处理出错：{e}")

        threading.Thread(target=run, daemon=True).start()
        return AckMessage.STATUS_OK, "OK"


# --------------------------------------------------------------------------- #
# 流模式客户端
# --------------------------------------------------------------------------- #
def start_dingtalk_stream():
    """启动钉钉流模式，阻塞运行（在独立线程中调用）。"""
    credential = dingtalk_stream.Credential(
        _cfg.dingtalk_client_id,
        _cfg.dingtalk_client_secret,
    )
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.ChatbotMessage.TOPIC, _BotHandler()
    )

    logger.info("[钉钉] 流模式启动中...")
    client.start_forever()  # 阻塞


# --------------------------------------------------------------------------- #
# 发消息（REST API，用于主动推送）
# --------------------------------------------------------------------------- #
class DingTalkBot:
    def send_text(self, user_id: str, text: str):
        """通过企业内部机器人发送单聊消息。"""
        if not user_id:
            logger.warning("[钉钉] user_id 为空，跳过发送")
            return
        try:
            from integrations.dingtalk.client import dt_post, _settings
            import json
            dt_post(
                "/v1.0/robot/oToMessages/batchSend",
                json={
                    "robotCode": _settings.dingtalk_client_id,
                    "userIds": [user_id],
                    "msgKey": "sampleText",
                    "msgParam": json.dumps({"content": text}, ensure_ascii=False),
                },
            )
        except Exception as e:
            logger.error(f"[钉钉] REST 发消息失败: {e}")
