"""
钉钉机器人 — 流模式（Stream，无需公网 Webhook）
使用官方 SDK: pip install dingtalk-stream
"""
import logging

import dingtalk_stream
from dingtalk_stream import AckMessage
from dingtalk_stream.chatbot import ChatbotHandler as _ChatbotHandlerBase
from pydantic_settings import BaseSettings

from integrations.base_bot import BaseBotHandler
from integrations.message_context import MessageContext

logger = logging.getLogger(__name__)


class DingTalkBotSettings(BaseSettings):
    dingtalk_client_id: str = ""
    dingtalk_client_secret: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


_cfg = DingTalkBotSettings()


# --------------------------------------------------------------------------- #
# DingTalk 业务处理（继承 BaseBotHandler，实现平台特定接口）
# --------------------------------------------------------------------------- #
class DingTalkBotHandler(BaseBotHandler):
    """钉钉消息处理器，继承平台无关的 BaseBotHandler。

    平台特定实现：
    - parse_message()  — 解析钉钉 ChatbotMessage
    - send_reply()     — 更新 MarkdownCard 或降级 REST 单聊消息
    - _on_pre_handle() — 注册 reply_fn 供工具回调使用
    """

    def parse_message(self, raw: dict) -> MessageContext | None:
        """从 raw dict 中解析 MessageContext。

        raw 由 _BotHandler.process() 构建，包含：
          - "incoming": dingtalk_stream.ChatbotMessage
          - "card": MarkdownCardInstance | None（提前创建避免 5 秒超时）
        """
        incoming: dingtalk_stream.ChatbotMessage = raw["incoming"]
        text = incoming.text.content.strip() if incoming.text else ""
        if not text:
            return None

        user_id = incoming.sender_staff_id or ""
        chat_id = incoming.conversation_id or user_id

        ctx = MessageContext(
            text=text,
            user_id=user_id,
            chat_id=chat_id,
            thread_id=f"dingtalk:{chat_id}",
            platform="dingtalk",
            raw=incoming,
        )
        ctx.extra["card"] = raw.get("card")  # MarkdownCard（可能为 None）
        return ctx

    def send_reply(self, text: str, ctx: MessageContext) -> None:
        """发送回复：优先更新 MarkdownCard，否则 REST 单聊消息。"""
        card = ctx.extra.get("card")
        if card:
            try:
                card.update(text)
                return
            except Exception as e:
                logger.warning(f"[钉钉] 卡片更新失败，降级普通消息: {e}")
        DingTalkBot().send_text(user_id=ctx.user_id, text=text)

    def _on_pre_handle(self, ctx: MessageContext) -> None:
        """注册 reply_fn，供工具在执行中向用户发送中间消息。"""
        from integrations.claude_code.session import reply_fn_registry
        reply_fn_registry[ctx.thread_id] = lambda t: DingTalkBot().send_text(
            user_id=ctx.user_id, text=t
        )
        # 话题变更后 reply_fn 也需更新（在 _on_extract_topic 之前注册初始值，之后可能被覆盖）


# --------------------------------------------------------------------------- #
# SDK Handler（适配层，将 SDK 回调桥接到 DingTalkBotHandler）
# --------------------------------------------------------------------------- #
class _BotHandler(_ChatbotHandlerBase):
    """钉钉流模式 SDK Handler（适配层）。

    职责：
    1. 接收 SDK CallbackMessage
    2. 提前创建 MarkdownCard（避免钉钉 5 秒回调超时）
    3. 委托 DingTalkBotHandler 处理业务逻辑
    """

    def __init__(self):
        self._handler = DingTalkBotHandler()

    def process(self, callback: dingtalk_stream.CallbackMessage):
        incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)

        # 提前创建 MarkdownCard（dingtalk_client 来自 _ChatbotHandlerBase 基类）
        card = None
        try:
            from dingtalk_stream.card_instance import MarkdownCardInstance
            card_instance = MarkdownCardInstance(self.dingtalk_client, incoming)
            card_id = card_instance.reply("⏳ 处理中，请稍候...", at_sender=False)
            if card_id:
                card_instance.card_instance_id = card_id
                card = card_instance
        except Exception as e:
            logger.warning(f"[钉钉] 创建处理中卡片失败，将降级为普通消息: {e}")

        self._handler.handle({"incoming": incoming, "card": card})
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
