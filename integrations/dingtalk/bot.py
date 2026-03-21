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
# 纯函数：消息解析（无副作用，可单测）
# --------------------------------------------------------------------------- #
def _parse_dingtalk_message(incoming: dingtalk_stream.ChatbotMessage) -> dict | None:
    """
    解析钉钉消息，返回标准化 dict 或 None（空消息返回 None）。

    返回字段：text, user_id, chat_id, thread_id
    """
    text = incoming.text.content.strip() if incoming.text else ""
    if not text:
        return None

    user_id = incoming.sender_staff_id or ""
    chat_id = incoming.conversation_id or user_id
    thread_id = f"dingtalk:{chat_id}"

    return {
        "text": text,
        "user_id": user_id,
        "chat_id": chat_id,
        "thread_id": thread_id,
    }


def _handle_slash_command(text: str, thread_id: str, chat_id: str = "") -> str | None:
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
        return format_topics(chat_id or thread_id)

    return None


# --------------------------------------------------------------------------- #
# 消息处理 Handler
# --------------------------------------------------------------------------- #
class _BotHandler(_ChatbotHandlerBase):
    def process(self, callback: dingtalk_stream.CallbackMessage):
        from integrations.claude_code.session import reply_fn_registry, session_manager

        incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        parsed = _parse_dingtalk_message(incoming)

        if not parsed:
            return AckMessage.STATUS_OK, "OK"

        text = parsed["text"]
        thread_id = parsed["thread_id"]
        chat_id = parsed["chat_id"]
        user_id = parsed["user_id"]

        logger.info(f"[钉钉流模式] user={user_id} msg={text[:80]}")

        dt_bot = DingTalkBot()

        # 注册 reply_fn（供工具回调使用）
        reply_fn_registry[thread_id] = lambda t, _uid=user_id: dt_bot.send_text(user_id=_uid, text=t)

        # ── 斜杠命令（优先处理）────────────────────────────────────────
        if text.startswith("/"):
            resp = _handle_slash_command(text, thread_id, chat_id)
            if resp is not None:
                self.reply_text(resp, incoming)
                return AckMessage.STATUS_OK, "OK"

        # ── 话题解析：#话题名 / 自然语言 前缀 → 隔离对话上下文 ──────────
        from integrations.topic_manager import (
            extract_topic, make_topic_thread_id, register_topic, WELCOME_MESSAGE,
        )
        topic_name, cleaned_text = extract_topic(text)
        if topic_name:
            thread_id = make_topic_thread_id("dingtalk", chat_id, topic_name)
            text = cleaned_text
            parsed["text"] = text
            parsed["thread_id"] = thread_id
            register_topic(chat_id, topic_name, thread_id, preview=text[:60])
            reply_fn_registry[thread_id] = lambda t, _uid=user_id: dt_bot.send_text(user_id=_uid, text=t)

        # ── 问候快速路径（0ms，不走 LLM）────────────────────────────
        _GREETINGS = {"你好", "hi", "hello", "嗨", "哈喽", "在吗", "在不在", "hey", "yo", "早", "早上好"}
        if text.strip().lower() in _GREETINGS and not topic_name:
            self.reply_text(WELCOME_MESSAGE, incoming)
            return AckMessage.STATUS_OK, "OK"

        # ── 检查是否有活跃 Claude Code 会话 ──────────────────────────
        if session_manager.get(thread_id):
            session_manager.relay_input(thread_id, text)
            self.reply_text("↩️ 已转发给 Claude", incoming)
            return AckMessage.STATUS_OK, "OK"

        # 话题消息但内容为空：只切换话题，不触发 Agent
        if topic_name and not text:
            from integrations.topic_manager import format_topics
            self.reply_text(f"已切换到话题 #{topic_name}\n\n{format_topics(chat_id)}", incoming)
            return AckMessage.STATUS_OK, "OK"

        # ── 正常 Agent 流程 ───────────────────────────────────────────
        # 用 MarkdownCard 回复：绑定到当前消息，无 session_webhook 5秒过期限制
        # 先创建 "处理中..." 卡片（避免钉钉 5 秒回调超时），LLM 完成后原地 update
        card_instance = None
        try:
            from dingtalk_stream.card_instance import MarkdownCardInstance
            card_instance = MarkdownCardInstance(self.dingtalk_client, incoming)
            card_id = card_instance.reply("⏳ 处理中，请稍候...", at_sender=False)
            if card_id:
                card_instance.card_instance_id = card_id
            else:
                card_instance = None  # 创建失败，降级到 send_text
        except Exception as e:
            logger.warning(f"[钉钉] 创建处理中卡片失败，将降级为普通消息: {e}")
            card_instance = None

        _card = card_instance  # 闭包捕获

        def run():
            try:
                from graph.agent import invoke
                reply = invoke(
                    message=text,
                    platform="dingtalk",
                    user_id=user_id,
                    chat_id=chat_id,
                    thread_id=thread_id,
                )
                if _card:
                    try:
                        _card.update(reply)
                        return
                    except Exception as e:
                        logger.warning(f"[钉钉] 卡片更新失败，降级普通消息: {e}")
                dt_bot.send_text(user_id=user_id, text=reply)
            except Exception as e:
                logger.error(f"[钉钉] Agent 处理失败: {e}")
                dt_bot.send_text(user_id=user_id, text=f"处理出错：{e}")

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
