"""平台无关的消息处理基类。

设计原则：
- handle() 是模板方法，定义消息处理流程（不可覆盖）
- parse_message() / send_reply() 由子类实现平台特定逻辑
- _on_* 钩子由子类可选覆盖，处理平台特有副作用（如 reaction、per-topic 锁）
- 公共逻辑（去重、斜杠命令、问候、Claude relay、Agent 调用）在基类实现

飞书和钉钉各继承此类，仅实现平台差异部分。
"""
import threading
import time
import logging
from abc import ABC, abstractmethod
from integrations.message_context import MessageContext

logger = logging.getLogger(__name__)

_GREETINGS = {"你好", "hi", "hello", "嗨", "哈喽", "在吗", "在不在", "hey", "yo", "早", "早上好"}


class BaseBotHandler(ABC):
    """平台无关的消息处理基类。"""

    _DEDUP_TTL = 120  # 2 分钟内相同 message_id 视为重复

    def __init__(self):
        self._dedup_ids: dict[str, float] = {}
        self._dedup_lock = threading.Lock()

    # ── 子类必须实现 ───────────────────────────────────────────────────────────

    @abstractmethod
    def parse_message(self, raw) -> MessageContext | None:
        """解析平台原始消息为 MessageContext，无法解析或忽略则返回 None。"""
        ...

    @abstractmethod
    def send_reply(self, text: str, ctx: MessageContext) -> None:
        """向用户发送回复消息。"""
        ...

    # ── 模板方法（公共流程，不可覆盖）────────────────────────────────────────

    def handle(self, raw) -> None:
        """消息处理主流程。"""
        ctx = self.parse_message(raw)
        if not ctx:
            return
        if ctx.message_id and self._is_duplicate(ctx.message_id):
            logger.info(f"[{ctx.platform}] 跳过重复消息 message_id={ctx.message_id}")
            return

        self._on_pre_handle(ctx)
        try:
            if self._handle_slash(ctx):
                return
            self._on_extract_topic(ctx)
            if self._handle_greeting(ctx):
                return
            if self._relay_claude(ctx):
                return
            # 话题有名但无正文：切换话题，不触发 Agent
            if ctx.topic_name and not ctx.text:
                from integrations.topic_manager import format_topics
                self.send_reply(f"已切换到话题 **#{ctx.topic_name}**\n\n{format_topics(ctx.chat_id)}", ctx)
                return
            self._invoke_agent(ctx)
        except Exception as e:
            logger.error(f"[{ctx.platform}] 消息处理失败: {e}", exc_info=True)
            try:
                self.send_reply(f"⚠️ 处理出错：{e}", ctx)
            except Exception:
                pass

    # ── 可覆盖的钩子（子类按需重写）──────────────────────────────────────────

    def _on_pre_handle(self, ctx: MessageContext) -> None:
        """消息处理前钩子（注册 reply_fn、锚点等平台特定操作）。"""
        pass

    def _on_extract_topic(self, ctx: MessageContext) -> None:
        """话题提取与路由，默认处理 #话题名 前缀。飞书可覆盖以实现短标题检测。"""
        from integrations.topic_manager import extract_topic, make_topic_thread_id, register_topic
        topic_name, cleaned_text = extract_topic(ctx.text)
        if topic_name:
            ctx.topic_name = topic_name
            ctx.thread_id = make_topic_thread_id(ctx.platform, ctx.chat_id, topic_name)
            ctx.text = cleaned_text
            register_topic(ctx.chat_id, topic_name, ctx.thread_id, preview=cleaned_text[:60])

    def _on_agent_start(self, ctx: MessageContext) -> None:
        """Agent 调用前钩子（飞书可覆盖以添加 Typing reaction）。"""
        pass

    def _on_agent_done(self, ctx: MessageContext, reply: str) -> None:
        """Agent 调用成功后钩子（飞书可覆盖以添加 OK reaction）。"""
        pass

    def _on_agent_error(self, ctx: MessageContext, error: Exception) -> None:
        """Agent 调用失败后钩子。"""
        pass

    # ── 公共逻辑实现 ──────────────────────────────────────────────────────────

    def _is_duplicate(self, message_id: str) -> bool:
        now = time.time()
        with self._dedup_lock:
            expired = [k for k, t in self._dedup_ids.items() if now - t > self._DEDUP_TTL]
            for k in expired:
                del self._dedup_ids[k]
            if message_id in self._dedup_ids:
                return True
            self._dedup_ids[message_id] = now
            return False

    def _handle_slash(self, ctx: MessageContext) -> bool:
        """处理斜杠命令，返回 True 表示已处理（终止后续流程）。"""
        if not ctx.text.startswith("/"):
            return False
        parts = ctx.text.strip().split()
        cmd = parts[0].lower() if parts else ""
        resp = None

        if cmd == "/status":
            from graph.tools import get_service_status
            resp = get_service_status.invoke({})
        elif cmd == "/clear":
            from graph.agent import clear_history
            ok = clear_history(ctx.thread_id)
            resp = "✅ 对话历史已清空" if ok else "❌ 清空失败，请查看日志"
        elif cmd == "/stop":
            from integrations.claude_code.session import session_manager
            if session_manager.get(ctx.thread_id):
                session_manager.kill(ctx.thread_id)
                resp = "✅ Claude 会话已停止"
            else:
                resp = "当前没有运行中的 Claude 会话"
        elif cmd == "/topics":
            from integrations.topic_manager import format_topics
            resp = format_topics(ctx.chat_id)

        if resp is not None:
            self.send_reply(resp, ctx)
            return True
        return False

    def _handle_greeting(self, ctx: MessageContext) -> bool:
        """问候快速路径，返回 True 表示已处理。"""
        if ctx.text.strip().lower() in _GREETINGS and not ctx.topic_name:
            from integrations.topic_manager import WELCOME_MESSAGE
            self.send_reply(WELCOME_MESSAGE, ctx)
            return True
        return False

    def _relay_claude(self, ctx: MessageContext) -> bool:
        """检测活跃 Claude 会话并中继输入，返回 True 表示已处理。"""
        from integrations.claude_code.session import session_manager
        if session_manager.get(ctx.thread_id):
            session_manager.relay_input(ctx.thread_id, ctx.text)
            self.send_reply("↩️ 已转发给 Claude", ctx)
            return True
        return False

    def _invoke_agent(self, ctx: MessageContext) -> None:
        """在后台线程中调用 LangGraph Agent 并发送回复。"""
        def run():
            self._on_agent_start(ctx)
            try:
                from graph.agent import invoke
                reply = invoke(
                    message=ctx.text,
                    platform=ctx.platform,
                    user_id=ctx.user_id,
                    chat_id=ctx.chat_id,
                    thread_id=ctx.thread_id,
                )
                self._on_agent_done(ctx, reply)
                self.send_reply(reply, ctx)
            except Exception as e:
                logger.error(f"[{ctx.platform}] Agent 处理失败: {e}", exc_info=True)
                self._on_agent_error(ctx, e)
                self.send_reply(f"处理出错：{e}", ctx)

        threading.Thread(target=run, daemon=True).start()
