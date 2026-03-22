"""
回归测试：Bot 层行为验证（全量 mock，无外部 SDK 依赖）

覆盖：
  BOT-1x  飞书 Bot 问候快速路径（v0.8.22）
  BOT-2x  钉钉 Bot 问候快速路径（v0.8.22）
  BOT-3x  FeishuBot.send_text 长回复压缩（v0.8.6）
  BOT-4x  _save_to_feishu_wiki 缓存失效恢复（v0.8.6）
  BOT-5x  飞书多话题并行与线程隔离（v1.0.0）
  BOT-6x  钉钉 MarkdownCard 替代旧 session_webhook（v1.0.0）
"""
import json
import pytest
from unittest.mock import patch, MagicMock, call


# ── BOT-1x: 飞书问候快速路径（v0.8.22）──────────────────────────────────────
class TestFeishuGreetingFastPath:
    """飞书 Bot：纯问候词直接回复，不走 LLM / Agent"""

    # 问候词集合（与 bot.py 中定义一致）
    GREETINGS = {"你好", "hi", "hello", "嗨", "哈喽", "在吗", "在不在", "hey", "yo", "早", "早上好"}

    @pytest.fixture(autouse=True)
    def _clear_seen(self):
        """每个测试前清空去重缓存，避免跨测试的 message_id 碰撞。"""
        import integrations.feishu.bot as fb
        fb._feishu_handler._dedup_ids.clear()
        yield
        fb._feishu_handler._dedup_ids.clear()

    def _make_message_data(self, text: str, msg_id: str = None):
        """构造最小可用的飞书消息 mock 对象"""
        import time
        data = MagicMock()
        data.event.message.message_type = "text"
        data.event.message.content = json.dumps({"text": text})
        data.event.message.chat_id = "chat_test_001"
        data.event.message.message_id = msg_id or f"msg_{text}_{time.time_ns()}"
        data.event.message.root_id = None
        data.event.sender.sender_id.open_id = "user_test_001"
        return data

    @pytest.mark.parametrize("greeting", ["你好", "hi", "hello", "嗨", "早上好", "在吗"])
    def test_greeting_bypasses_agent(self, greeting):
        """标准问候词 → send_text 被调用，agent.invoke 不被调用"""
        from integrations.feishu import bot as feishu_bot
        data = self._make_message_data(greeting)

        sent = []
        with patch.object(feishu_bot.FeishuBot, "send_text",
                          side_effect=lambda chat_id, text: sent.append(text) or True):
            with patch("integrations.claude_code.session.session_manager") as mock_sm:
                with patch("integrations.feishu.bot.threading") as mock_thread:
                    mock_sm.get.return_value = None
                    feishu_bot._on_message(data)

        # 问候路径：send_text 被调用
        assert len(sent) > 0, f"问候 '{greeting}' 应触发 send_text"
        # 正常 Agent 路径未启动（线程未创建）
        mock_thread.Thread.assert_not_called()

    def test_greeting_case_insensitive(self):
        """'Hi'（大写首字母）也触发问候路径（lower() 处理）"""
        from integrations.feishu import bot as feishu_bot
        data = self._make_message_data("Hi")

        sent = []
        with patch.object(feishu_bot.FeishuBot, "send_text",
                          side_effect=lambda chat_id, text: sent.append(text) or True):
            with patch("integrations.claude_code.session.session_manager") as mock_sm:
                with patch("integrations.feishu.bot.threading") as mock_thread:
                    mock_sm.get.return_value = None
                    feishu_bot._on_message(data)

        assert len(sent) > 0
        mock_thread.Thread.assert_not_called()

    def test_non_greeting_uses_agent_thread(self):
        """'你好吗' 不在问候集合 → 启动 Agent 线程"""
        from integrations.feishu import bot as feishu_bot
        data = self._make_message_data("你好吗")

        with patch.object(feishu_bot.FeishuBot, "send_text", return_value=True):
            with patch("integrations.claude_code.session.session_manager") as mock_sm:
                with patch("integrations.feishu.bot.threading") as mock_thread:
                    mock_sm.get.return_value = None
                    mock_thread.Thread = MagicMock(return_value=MagicMock())
                    feishu_bot._on_message(data)

        mock_thread.Thread.assert_called_once()

    def test_greeting_set_completeness(self):
        """验证 _GREETINGS 集合包含所有预期的问候词"""
        import time
        from integrations.feishu import bot as feishu_bot
        for greeting in self.GREETINGS:
            # 每次用唯一 message_id 避免去重（dedup TTL=2min）
            data = self._make_message_data(greeting, msg_id=f"completeness_{greeting}_{time.time_ns()}")
            sent = []
            with patch.object(feishu_bot.FeishuBot, "send_text",
                               side_effect=lambda chat_id, text: sent.append(text) or True):
                with patch("integrations.claude_code.session.session_manager") as mock_sm:
                    with patch("integrations.feishu.bot.threading") as mock_thread:
                        mock_sm.get.return_value = None
                        feishu_bot._on_message(data)
            assert len(sent) > 0, f"'{greeting}' 应触发快速路径"


# ── BOT-2x: 钉钉问候快速路径（v0.8.22）──────────────────────────────────────
class TestDingTalkGreetingFastPath:
    """钉钉 Bot：问候词直接回复，不走 Agent"""

    def _make_handler_and_callback(self, text: str):
        """构造 _BotHandler 实例和 fake callback"""
        from integrations.dingtalk import bot as dd_bot
        handler = dd_bot._BotHandler.__new__(dd_bot._BotHandler)
        handler._handler = dd_bot.DingTalkBotHandler()
        handler.dingtalk_client = MagicMock()
        callback = MagicMock()
        callback.data = {}
        return handler, callback

    def _make_ctx(self, text: str):
        from integrations.message_context import MessageContext
        ctx = MessageContext(
            text=text,
            user_id="user_001",
            chat_id="conv_001",
            thread_id="dingtalk:conv_001",
            platform="dingtalk",
        )
        ctx.extra["card"] = None
        return ctx

    @pytest.mark.parametrize("greeting", ["你好", "hi", "嗨", "早上好"])
    def test_greeting_bypasses_agent(self, greeting):
        """标准问候 → send_reply 被调用，agent 线程不启动"""
        from integrations.dingtalk import bot as dd_bot
        handler, callback = self._make_handler_and_callback(greeting)
        ctx = self._make_ctx(greeting)
        replied = []

        with patch("dingtalk_stream.ChatbotMessage.from_dict", return_value=MagicMock()):
            with patch.object(dd_bot.DingTalkBotHandler, "parse_message", return_value=ctx):
                with patch.object(dd_bot.DingTalkBotHandler, "send_reply",
                                  side_effect=lambda text, c: replied.append(text)):
                    with patch("integrations.claude_code.session.session_manager") as mock_sm:
                        with patch("integrations.base_bot.threading") as mock_thread:
                            mock_sm.get.return_value = None
                            handler.process(callback)

        assert len(replied) > 0, f"钉钉问候 '{greeting}' 应触发 send_reply"
        mock_thread.Thread.assert_not_called()

    def test_non_greeting_starts_agent(self):
        """非问候消息 → 启动 Agent 流程（threading.Thread 被调用）"""
        from integrations.dingtalk import bot as dd_bot
        handler, callback = self._make_handler_and_callback("帮我查一下飞书")
        ctx = self._make_ctx("帮我查一下飞书")

        with patch("dingtalk_stream.ChatbotMessage.from_dict", return_value=MagicMock()):
            with patch.object(dd_bot.DingTalkBotHandler, "parse_message", return_value=ctx):
                with patch("integrations.claude_code.session.session_manager") as mock_sm:
                    with patch("integrations.base_bot.threading") as mock_thread:
                        mock_sm.get.return_value = None
                        mock_thread.Thread = MagicMock(return_value=MagicMock())
                        handler.process(callback)

        mock_thread.Thread.assert_called_once()


# ── BOT-3x: FeishuBot.send_text 长回复压缩（v0.8.6）─────────────────────────
class TestFeishuSendTextLongReply:
    """≤800字符直接发；>800字符存飞书+摘要；wiki失败时降级分段"""

    @pytest.fixture
    def bot(self):
        from integrations.feishu.bot import FeishuBot
        return FeishuBot.__new__(FeishuBot)

    def test_short_text_direct_send(self, bot):
        """≤800 字符 → _send_single 被调用，不调 _save_to_feishu_wiki"""
        text = "x" * 799
        with patch.object(bot, "_send_single", return_value=True) as mock_send:
            with patch.object(bot, "_save_to_feishu_wiki") as mock_wiki:
                result = bot.send_text("chat_001", text)
        mock_send.assert_called_once_with("chat_001", text)
        mock_wiki.assert_not_called()
        assert result is True

    def test_exactly_800_chars_direct_send(self, bot):
        """恰好 800 字符 → 直接发（边界值）"""
        text = "x" * 800
        with patch.object(bot, "_send_single", return_value=True) as mock_send:
            with patch.object(bot, "_save_to_feishu_wiki") as mock_wiki:
                bot.send_text("chat_001", text)
        mock_send.assert_called_once()
        mock_wiki.assert_not_called()

    def test_long_text_saves_to_wiki(self, bot):
        """>800 字符 → 调 _save_to_feishu_wiki"""
        text = "x" * 1000
        with patch.object(bot, "_send_single", return_value=True):
            with patch.object(bot, "_save_to_feishu_wiki", return_value="wiki_tok_abc") as mock_wiki:
                bot.send_text("chat_001", text)
        mock_wiki.assert_called_once_with(text)

    def test_long_text_sends_summary_with_link(self, bot):
        """>800 字符存飞书成功 → IM 发的文本含 wiki 链接和'详细内容'"""
        text = "y" * 1000
        sent_text = []
        with patch.object(bot, "_send_single",
                           side_effect=lambda chat_id, t: sent_text.append(t) or True):
            with patch.object(bot, "_save_to_feishu_wiki", return_value="wiki_tok_xyz"):
                bot.send_text("chat_001", text)
        assert len(sent_text) == 1
        assert "wiki_tok_xyz" in sent_text[0]
        assert "📄 详细内容" in sent_text[0]

    def test_wiki_failure_falls_back_to_split(self, bot):
        """wiki 写入失败 → 降级分段发送（_send_single 被多次调用）"""
        # 100行，每行50字符（含换行共51字符），总计 5100 字符 → 超过3800应产生2段
        text = "\n".join(["z" * 50] * 100)
        call_count = [0]

        def count_send(chat_id, t):
            call_count[0] += 1
            return True

        with patch.object(bot, "_send_single", side_effect=count_send):
            with patch.object(bot, "_save_to_feishu_wiki", side_effect=Exception("写入失败")):
                bot.send_text("chat_001", text)

        assert call_count[0] >= 2, f"降级分段应多次调用，实际 {call_count[0]} 次"

    def test_empty_chat_id_returns_false(self, bot):
        """chat_id 为空 → 直接返回 None，不发送"""
        with patch.object(bot, "_send_single") as mock_send:
            result = bot.send_text("", "任意内容")
        assert result is None
        mock_send.assert_not_called()


# ── BOT-4x: _save_to_feishu_wiki 缓存失效恢复（v0.8.6）──────────────────────
class TestSaveToFeishuWiki:
    """写入失败时清缓存后重试一次"""

    @pytest.fixture
    def bot(self):
        from integrations.feishu.bot import FeishuBot
        b = FeishuBot.__new__(FeishuBot)
        return b

    def test_success_returns_page_token(self, bot):
        """正常路径：append 成功 → 返回 page_token"""
        with patch.dict("os.environ", {"FEISHU_WIKI_CONTEXT_PAGE": "ctx_page_tok"}):
            with patch("integrations.feishu.knowledge.FeishuKnowledge") as MockKB:
                mock_kb = MagicMock()
                MockKB.return_value = mock_kb
                mock_kb.find_or_create_child_page.return_value = "detail_page_tok"
                mock_kb.append_to_page.return_value = None

                result = bot._save_to_feishu_wiki("长文本内容")

        assert result == "detail_page_tok"

    def test_append_failure_clears_cache_and_retries(self, bot):
        """append 失败 → 清缓存后重试一次（find_or_create 被调用 2 次）"""
        append_count = [0]

        def fail_first_append(token, content):
            append_count[0] += 1
            if append_count[0] == 1:
                raise Exception("页面已删除")
            # 第二次成功

        with patch.dict("os.environ", {"FEISHU_WIKI_CONTEXT_PAGE": "ctx_page_tok"}):
            # FeishuKnowledge 在函数内部 import，patch 源模块
            with patch("integrations.feishu.knowledge.FeishuKnowledge") as MockKB:
                with patch("integrations.storage.config_store.delete") as mock_del:
                    mock_kb = MagicMock()
                    MockKB.return_value = mock_kb
                    mock_kb.find_or_create_child_page.return_value = "new_page_tok"
                    mock_kb.append_to_page.side_effect = fail_first_append

                    result = bot._save_to_feishu_wiki("长文本内容")

        mock_del.assert_called_once_with("AI_REPLY_DETAIL_PAGE")
        assert mock_kb.find_or_create_child_page.call_count == 2
        assert result == "new_page_tok"

    def test_both_appends_fail_raises(self, bot):
        """两次 append 都失败 → 异常向上传播"""
        with patch.dict("os.environ", {"FEISHU_WIKI_CONTEXT_PAGE": "ctx_page_tok"}):
            with patch("integrations.feishu.knowledge.FeishuKnowledge") as MockKB:
                with patch("integrations.storage.config_store.delete"):
                    mock_kb = MagicMock()
                    MockKB.return_value = mock_kb
                    mock_kb.find_or_create_child_page.return_value = "page_tok"
                    mock_kb.append_to_page.side_effect = Exception("持续失败")

                    with pytest.raises(Exception, match="持续失败"):
                        bot._save_to_feishu_wiki("长文本内容")

    def test_no_context_page_raises(self, bot):
        """FEISHU_WIKI_CONTEXT_PAGE 未配置 → 抛 ValueError"""
        with patch.dict("os.environ", {}, clear=True):
            # 确保环境变量不存在
            import os
            os.environ.pop("FEISHU_WIKI_CONTEXT_PAGE", None)
            with pytest.raises(ValueError, match="FEISHU_WIKI_CONTEXT_PAGE"):
                bot._save_to_feishu_wiki("内容")

    def test_timestamp_in_written_content(self, bot):
        """写入飞书的内容包含时间戳"""
        written = []
        with patch.dict("os.environ", {"FEISHU_WIKI_CONTEXT_PAGE": "ctx_page_tok"}):
            with patch("integrations.feishu.knowledge.FeishuKnowledge") as MockKB:
                mock_kb = MagicMock()
                MockKB.return_value = mock_kb
                mock_kb.find_or_create_child_page.return_value = "page_tok"
                mock_kb.append_to_page.side_effect = lambda tok, content: written.append(content)

                bot._save_to_feishu_wiki("测试内容")

        assert len(written) == 1
        assert "回复" in written[0]
        # 时间格式：YYYY-MM-DD HH:MM
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", written[0])


# ── BOT-5x: 飞书多话题并行与线程隔离（v1.0.0）───────────────────────────────
class TestFeishuMultiTopicIsolation:
    """BOT-5x: 同一 chat 的不同话题各自独立 thread_id 与 _topic_lock"""

    @pytest.fixture(autouse=True)
    def _isolate(self):
        """每个测试隔离飞书 bot 全局状态。"""
        import integrations.feishu.bot as fb
        saved_anchor = dict(fb._thread_anchor)
        saved_reverse = dict(fb._anchor_to_thread)
        saved_seen = dict(fb._feishu_handler._dedup_ids)
        saved_locks = dict(fb._topic_locks)
        saved_db = fb._anchor_db

        fb._thread_anchor.clear()
        fb._anchor_to_thread.clear()
        fb._feishu_handler._dedup_ids.clear()
        fb._topic_locks.clear()
        fb._anchor_db = None
        yield fb

        fb._thread_anchor.clear()
        fb._thread_anchor.update(saved_anchor)
        fb._anchor_to_thread.clear()
        fb._anchor_to_thread.update(saved_reverse)
        fb._feishu_handler._dedup_ids.clear()
        fb._feishu_handler._dedup_ids.update(saved_seen)
        fb._topic_locks.clear()
        fb._topic_locks.update(saved_locks)
        fb._anchor_db = saved_db

    def _make_msg(self, text, chat_id="oc_multi", msg_id="msg_001", root_id=None):
        data = MagicMock()
        data.event.message.message_type = "text"
        data.event.message.content = json.dumps({"text": text})
        data.event.message.chat_id = chat_id
        data.event.message.message_id = msg_id
        data.event.message.root_id = root_id
        data.event.sender.sender_id.open_id = "user_multi_001"
        return data

    def test_two_topics_get_different_thread_ids(self, _isolate):
        """BOT-51: 同一 chat 两条不同话题消息 → 两个不同 thread_id"""
        fb = _isolate
        from integrations.feishu.bot import FeishuBot

        thread_ids_seen = []
        original_get_lock = fb._get_topic_lock

        def capture_lock(tid):
            thread_ids_seen.append(tid)
            return original_get_lock(tid)

        with patch("integrations.feishu.bot._get_topic_lock", side_effect=capture_lock):
            with patch("integrations.claude_code.session.session_manager") as mock_sm:
                with patch("integrations.feishu.bot.threading") as mock_thread:
                    with patch.object(FeishuBot, "send_text", return_value=True):
                        mock_sm.get.return_value = None
                        mock_thread.Thread = MagicMock(return_value=MagicMock())
                        fb._on_message(self._make_msg("#项目A 进展如何", msg_id="msg_a1"))
                        fb._on_message(self._make_msg("#日程 明天安排", msg_id="msg_b1"))

        assert len(thread_ids_seen) >= 2
        assert thread_ids_seen[0] != thread_ids_seen[1], (
            f"两个话题应有不同 thread_id，实际: {thread_ids_seen}"
        )
        assert "#topic#项目A" in thread_ids_seen[0]
        assert "#topic#日程" in thread_ids_seen[1]

    def test_two_topics_get_independent_locks(self, _isolate):
        """BOT-51: 两个不同话题的 _topic_lock 对象独立（不是同一把锁）"""
        fb = _isolate
        lock_a = fb._get_topic_lock("feishu:oc_chat#topic#项目A")
        lock_b = fb._get_topic_lock("feishu:oc_chat#topic#日程")
        assert lock_a is not lock_b, "不同话题应各自独立的锁"

    def test_same_topic_reuses_lock(self, _isolate):
        """同一话题两次调用 _get_topic_lock → 返回同一把锁对象"""
        fb = _isolate
        lock1 = fb._get_topic_lock("feishu:oc_chat#topic#项目A")
        lock2 = fb._get_topic_lock("feishu:oc_chat#topic#项目A")
        assert lock1 is lock2

    def test_empty_topic_body_no_agent(self, _isolate):
        """BOT-52: 消息仅为 '#日程'（内容为空）→ 回复切换提示，不启动 Agent 线程"""
        fb = _isolate
        from integrations.feishu.bot import FeishuBot

        sent_texts = []
        with patch("integrations.claude_code.session.session_manager") as mock_sm:
            with patch("integrations.feishu.bot.threading") as mock_thread:
                with patch.object(
                    FeishuBot, "send_text",
                    side_effect=lambda chat_id, text: sent_texts.append(text) or True,
                ):
                    mock_sm.get.return_value = None
                    mock_thread.Thread = MagicMock(return_value=MagicMock())
                    fb._on_message(self._make_msg("#日程", msg_id="msg_empty"))

        mock_thread.Thread.assert_not_called()
        assert len(sent_texts) > 0
        assert any("日程" in t for t in sent_texts), f"应提及话题名，实际: {sent_texts}"

    def test_duplicate_message_id_skipped(self, _isolate):
        """BOT-53: 同一 message_id 发两次 → 第二次被去重跳过"""
        fb = _isolate
        from integrations.feishu.bot import FeishuBot

        thread_count = [0]

        def count_thread(*args, **kwargs):
            thread_count[0] += 1
            return MagicMock()

        with patch("integrations.claude_code.session.session_manager") as mock_sm:
            with patch("integrations.feishu.bot.threading") as mock_thread:
                with patch.object(FeishuBot, "send_text", return_value=True):
                    mock_sm.get.return_value = None
                    mock_thread.Thread = MagicMock(side_effect=count_thread)
                    fb._on_message(self._make_msg("你好吗", msg_id="dup_msg_001"))
                    fb._on_message(self._make_msg("你好吗", msg_id="dup_msg_001"))

        assert thread_count[0] <= 1, (
            f"重复消息应被去重，Agent 线程最多启动 1 次，实际: {thread_count[0]}"
        )


# ── BOT-6x: 钉钉 MarkdownCard 替代旧 session_webhook（v1.0.0）──────────────
class TestDingTalkMarkdownCardReplacement:
    """BOT-6x: 确认 MarkdownCard 已取代旧 session_webhook"""

    def test_non_greeting_instantiates_markdown_card(self):
        """BOT-61: 非问候钉钉消息 → MarkdownCardInstance 被实例化"""
        from integrations.dingtalk import bot as dd_bot
        from integrations.message_context import MessageContext
        handler = dd_bot._BotHandler.__new__(dd_bot._BotHandler)
        handler._handler = dd_bot.DingTalkBotHandler()
        handler.dingtalk_client = MagicMock()
        callback = MagicMock()
        callback.data = {}

        ctx = MessageContext(
            text="帮我查一下钉钉文档",
            user_id="user_bot6",
            chat_id="conv_bot6",
            thread_id="dingtalk:conv_bot6",
            platform="dingtalk",
        )
        ctx.extra["card"] = None
        mock_card = MagicMock()
        mock_card.reply.return_value = "card_id_bot6"

        with patch("dingtalk_stream.ChatbotMessage.from_dict", return_value=MagicMock()):
            with patch.object(dd_bot.DingTalkBotHandler, "parse_message", return_value=ctx):
                with patch("integrations.claude_code.session.session_manager") as mock_sm:
                    with patch(
                        "dingtalk_stream.card_instance.MarkdownCardInstance",
                        return_value=mock_card,
                    ) as MockCard:
                        with patch("integrations.base_bot.threading") as mock_thread:
                            mock_sm.get.return_value = None
                            mock_thread.Thread = MagicMock(return_value=MagicMock())
                            handler.process(callback)

        MockCard.assert_called_once()
        mock_card.reply.assert_called_once()

    def test_session_webhook_symbol_removed(self):
        """BOT-62: session_webhook 相关旧符号已从钉钉 bot 移除"""
        import integrations.dingtalk.bot as dd_bot
        assert not hasattr(dd_bot, "_reply_via_webhook"), \
            "_reply_via_webhook 应已移除"
        assert not hasattr(dd_bot, "_thread_anchor"), \
            "钉钉的 _thread_anchor 应已移除（仅飞书有）"
        assert not hasattr(dd_bot, "_get_anchor"), \
            "_get_anchor 应已从钉钉 bot 移除"
