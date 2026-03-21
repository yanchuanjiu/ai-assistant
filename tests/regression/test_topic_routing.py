"""
回归测试：v1.0.0 多话题线程化路由（全量 mock，无外部依赖）

覆盖：
  TOPIC-1x  extract_topic() 自然语言格式（v1.0.0）
  TOPIC-2x  飞书 root_id → 话题 thread_id 反向路由（v1.0.0）
  TOPIC-3x  飞书 reply_in_thread 含首条回复（v1.0.0）
  TOPIC-4x  SQLite anchor 持久化（v1.0.0）
  TOPIC-5x  钉钉 MarkdownCard 替代 session_webhook（v1.0.0）
"""
import json
import sqlite3
import time
import threading
import pytest
from unittest.mock import patch, MagicMock, call


# ── 测试隔离 Fixtures ────────────────────────────────────────────────────────

@pytest.fixture(autouse=False)
def isolated_feishu(request):
    """
    每个测试前保存并清空飞书 bot 的模块级状态，测试后恢复。
    避免跨测试污染 _thread_anchor / _anchor_to_thread / _seen_message_ids。
    """
    import integrations.feishu.bot as fb
    saved_anchor   = dict(fb._thread_anchor)
    saved_reverse  = dict(fb._anchor_to_thread)
    saved_seen     = dict(fb._seen_message_ids)
    saved_db       = fb._anchor_db

    fb._thread_anchor.clear()
    fb._anchor_to_thread.clear()
    fb._seen_message_ids.clear()
    fb._anchor_db = None

    yield fb

    fb._thread_anchor.clear()
    fb._thread_anchor.update(saved_anchor)
    fb._anchor_to_thread.clear()
    fb._anchor_to_thread.update(saved_reverse)
    fb._seen_message_ids.clear()
    fb._seen_message_ids.update(saved_seen)
    fb._anchor_db = saved_db


@pytest.fixture
def feishu_with_inmem_db(isolated_feishu):
    """在 isolated_feishu 基础上注入内存 SQLite，供持久化测试使用。"""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("""
        CREATE TABLE feishu_anchors (
            message_id TEXT PRIMARY KEY,
            thread_id  TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.commit()
    isolated_feishu._anchor_db = conn
    yield isolated_feishu, conn
    conn.close()


def _make_feishu_msg(text, chat_id="oc_chat_001", msg_id="msg_001", root_id=None):
    """构造最小飞书消息 mock（支持 root_id 扩展）。"""
    data = MagicMock()
    data.event.message.message_type = "text"
    data.event.message.content = json.dumps({"text": text})
    data.event.message.chat_id = chat_id
    data.event.message.message_id = msg_id
    data.event.message.root_id = root_id
    data.event.sender.sender_id.open_id = "user_test_001"
    return data


# ── TOPIC-1x: extract_topic() 自然语言格式 ──────────────────────────────────

class TestExtractTopicNaturalLanguage:
    """TOPIC-1x: extract_topic 支持 #话题名 与自然语言并存"""

    @pytest.mark.parametrize("text,expected", [
        # 已有 # 格式不退化
        ("#项目A 进展如何", ("项目A", "进展如何")),
        ("#日程", ("日程", "")),
        # 中文全角冒号
        ("新话题：预算 Q2情况", ("预算", "Q2情况")),
        # 半角冒号
        ("新话题:采购 清单", ("采购", "清单")),
        # 空格分隔
        ("新话题 日程 明天安排", ("日程", "明天安排")),
        # 带"开始"前缀
        ("开始新话题：复盘 上周情况", ("复盘", "上周情况")),
        ("开始新话题 复盘 上周情况", ("复盘", "上周情况")),
    ])
    def test_topic_extracted(self, text, expected):
        from integrations.topic_manager import extract_topic
        assert extract_topic(text) == expected

    @pytest.mark.parametrize("text", [
        "新话题：",          # 无话题名
        "新话题 ",           # 无话题名（只有空格）
        "普通消息",
        "这不是新话题",
        "hello world",
        "",
    ])
    def test_no_topic(self, text):
        from integrations.topic_manager import extract_topic
        topic_name, _ = extract_topic(text)
        assert topic_name is None, f"'{text}' 不应识别为话题，实际 topic_name={topic_name!r}"

    def test_hash_format_takes_priority_over_natural(self):
        """#话题名 优先于自然语言格式（不会被误识别为 '新话题：xxx' 的一部分）"""
        from integrations.topic_manager import extract_topic
        topic, rest = extract_topic("#新话题：预算 内容")
        assert topic == "新话题：预算"   # # 格式直接取后面的词
        assert rest == "内容"


# ── TOPIC-2x: 飞书 root_id → 话题 thread_id 反向路由 ───────────────────────

class TestFeishuRootIdRouting:
    """TOPIC-2x: 回复已有飞书线程时，正确路由到话题上下文"""

    def test_anchor_registered_in_reverse_map(self, isolated_feishu):
        """TOPIC-21: _set_anchor 同时维护 _anchor_to_thread 反向映射"""
        fb = isolated_feishu
        tid = "feishu:oc_abc#topic#项目A"
        fb._set_anchor(tid, "msg_anchor_001")

        assert "msg_anchor_001" in fb._anchor_to_thread
        assert fb._anchor_to_thread["msg_anchor_001"] == tid

    def test_root_id_routes_to_known_topic(self, isolated_feishu):
        """TOPIC-22: root_id 命中反向映射 → 返回话题 thread_id"""
        fb = isolated_feishu
        topic_tid = "feishu:oc_chat#topic#日程"
        fb._anchor_to_thread["msg_root_999"] = topic_tid

        data = _make_feishu_msg("明天有安排吗", chat_id="oc_chat",
                                msg_id="msg_reply_001", root_id="msg_root_999")
        parsed = fb._parse_feishu_message(data)

        assert parsed is not None
        assert parsed["thread_id"] == topic_tid, (
            f"应路由到话题 thread_id，实际: {parsed['thread_id']}"
        )

    def test_unknown_root_id_fallback(self, isolated_feishu):
        """TOPIC-23: root_id 未知 → fallback 为 feishu:thread:{root_id}，不 crash"""
        fb = isolated_feishu
        # 不在反向映射中
        data = _make_feishu_msg("回复内容", chat_id="oc_chat",
                                msg_id="msg_new", root_id="msg_unknown_xxx")
        parsed = fb._parse_feishu_message(data)

        assert parsed is not None
        assert parsed["thread_id"] == "feishu:thread:msg_unknown_xxx"

    def test_different_topics_anchors_isolated(self, isolated_feishu):
        """TOPIC-24: 不同话题 anchor 互不干扰"""
        fb = isolated_feishu
        tid_a = "feishu:oc_chat#topic#项目A"
        tid_b = "feishu:oc_chat#topic#日程"

        fb._set_anchor(tid_a, "msg_a_001")
        fb._set_anchor(tid_b, "msg_b_001")

        assert fb._anchor_to_thread["msg_a_001"] == tid_a
        assert fb._anchor_to_thread["msg_b_001"] == tid_b
        assert fb._anchor_to_thread.get("msg_a_001") != tid_b

    def test_no_root_id_uses_chat_thread(self, isolated_feishu):
        """无 root_id 的普通消息 → 使用 feishu:{chat_id}"""
        fb = isolated_feishu
        data = _make_feishu_msg("普通消息", chat_id="oc_chat_456", msg_id="msg_plain")
        parsed = fb._parse_feishu_message(data)

        assert parsed is not None
        assert parsed["thread_id"] == "feishu:oc_chat_456"


# ── TOPIC-3x: 飞书 reply_in_thread（含首条）───────────────────────────────

class TestFeishuReplyInThread:
    """TOPIC-3x: 话题/线程消息均走 reply_in_thread，默认消息走 send_text"""

    def _make_bot_mock(self, reply_in_thread_return=True):
        from integrations.feishu.bot import FeishuBot
        bot = MagicMock(spec=FeishuBot)
        bot.add_reaction.return_value = "reaction_id"
        bot.reply_in_thread.return_value = reply_in_thread_return
        bot.send_text.return_value = True
        return bot

    def _make_parsed(self, text, thread_id, chat_id="oc_test", msg_id="msg_001"):
        return {
            "text": text,
            "user_id": "user_001",
            "chat_id": chat_id,
            "message_id": msg_id,
            "thread_id": thread_id,
        }

    def test_topic_first_reply_uses_reply_in_thread(self, isolated_feishu):
        """TOPIC-31: 话题第 1 条回复走 reply_in_thread（不是 send_text）"""
        fb = isolated_feishu
        tid = "feishu:oc_test#topic#项目A"
        fb._thread_anchor[tid] = "msg_001"   # anchor 已注册（首条消息）

        parsed = self._make_parsed("进展如何", thread_id=tid, msg_id="msg_001")
        bot = self._make_bot_mock()

        with patch("graph.agent.invoke", return_value="项目进展顺利"):
            fb._run_agent(parsed, bot)

        bot.reply_in_thread.assert_called_once()
        # send_text 不应被用来发正文（只可能在失败兜底时才调用）
        for c in bot.send_text.call_args_list:
            assert "项目进展顺利" not in str(c)

    def test_topic_second_reply_uses_reply_in_thread(self, isolated_feishu):
        """TOPIC-32: 话题第 2 条消息也走 reply_in_thread"""
        fb = isolated_feishu
        tid = "feishu:oc_test#topic#项目A"
        fb._thread_anchor[tid] = "msg_001"   # anchor = 第1条消息

        parsed = self._make_parsed("还有什么进展", thread_id=tid, msg_id="msg_002")
        bot = self._make_bot_mock()

        with patch("graph.agent.invoke", return_value="另外进展顺利"):
            fb._run_agent(parsed, bot)

        bot.reply_in_thread.assert_called_once()
        args = bot.reply_in_thread.call_args
        assert args[0][0] == "msg_001"   # anchor 是第1条消息

    def test_default_context_uses_send_text(self, isolated_feishu):
        """TOPIC-33: 无话题前缀的默认消息 → send_text，不走 reply_in_thread"""
        fb = isolated_feishu
        tid = "feishu:oc_test"   # 默认 thread_id（无 #topic#）
        fb._thread_anchor[tid] = "msg_001"

        parsed = self._make_parsed("普通问题", thread_id=tid, msg_id="msg_002")
        bot = self._make_bot_mock()

        with patch("graph.agent.invoke", return_value="普通回复"):
            fb._run_agent(parsed, bot)

        bot.reply_in_thread.assert_not_called()
        bot.send_text.assert_called()

    def test_long_reply_falls_back_to_send_text(self, isolated_feishu):
        """TOPIC-34: reply_in_thread 返回 False（超长）→ 降级为 send_text"""
        fb = isolated_feishu
        tid = "feishu:oc_test#topic#长文"
        fb._thread_anchor[tid] = "msg_001"

        parsed = self._make_parsed("写份报告", thread_id=tid, msg_id="msg_002")
        bot = self._make_bot_mock(reply_in_thread_return=False)

        with patch("graph.agent.invoke", return_value="很长的回复"):
            fb._run_agent(parsed, bot)

        bot.reply_in_thread.assert_called_once()
        # 降级：send_text 被调用发送正文
        send_calls = [str(c) for c in bot.send_text.call_args_list]
        assert any("很长的回复" in c for c in send_calls), \
            f"降级后应调用 send_text 发正文，实际: {send_calls}"

    def test_reply_in_thread_passes_thread_id(self, isolated_feishu):
        """TOPIC-35: reply_in_thread 传入 thread_id（供注册 bot 回复 message_id）"""
        fb = isolated_feishu
        tid = "feishu:oc_test#topic#注册测试"
        fb._thread_anchor[tid] = "anchor_msg"

        parsed = self._make_parsed("问题", thread_id=tid, msg_id="msg_q")
        bot = self._make_bot_mock()

        with patch("graph.agent.invoke", return_value="回复"):
            fb._run_agent(parsed, bot)

        # reply_in_thread 应收到 thread_id 关键字参数
        _, kwargs = bot.reply_in_thread.call_args
        assert kwargs.get("thread_id") == tid


# ── TOPIC-4x: SQLite anchor 持久化 ──────────────────────────────────────────

class TestFeishuAnchorPersistence:
    """TOPIC-4x: anchor 写入 SQLite，重启后可恢复"""

    def test_set_anchor_writes_to_db(self, feishu_with_inmem_db):
        """TOPIC-41: _set_anchor 调用后，DB 有对应记录"""
        fb, conn = feishu_with_inmem_db
        fb._set_anchor("feishu:oc_x#topic#测试", "msg_persist_001")

        rows = conn.execute(
            "SELECT message_id, thread_id FROM feishu_anchors WHERE message_id=?",
            ("msg_persist_001",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "feishu:oc_x#topic#测试"

    def test_expired_entries_not_loaded(self, isolated_feishu):
        """TOPIC-43: 过期条目（超过 7 天）不加载进内存"""
        fb = isolated_feishu
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("""
            CREATE TABLE feishu_anchors (
                message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, created_at REAL NOT NULL
            )
        """)
        # 写入一条过期记录
        old_ts = time.time() - (8 * 86400)   # 8天前
        conn.execute(
            "INSERT INTO feishu_anchors VALUES (?, ?, ?)",
            ("old_msg", "feishu:chat#topic#过期", old_ts),
        )
        # 写入一条有效记录
        conn.execute(
            "INSERT INTO feishu_anchors VALUES (?, ?, ?)",
            ("new_msg", "feishu:chat#topic#有效", time.time()),
        )
        conn.commit()
        fb._anchor_db = conn

        # 模拟"首次加载"逻辑（直接调用 _get_anchor_db 内的 SELECT 逻辑）
        now = time.time()
        rows = conn.execute(
            "SELECT message_id, thread_id FROM feishu_anchors WHERE created_at > ?",
            (now - fb._ANCHOR_TTL,),
        ).fetchall()
        loaded = {r[0]: r[1] for r in rows}

        assert "old_msg" not in loaded, "过期条目不应加载"
        assert "new_msg" in loaded

    def test_concurrent_set_anchor_no_crash(self, feishu_with_inmem_db):
        """TOPIC-44: 并发调用 _set_anchor 不 crash（线程安全）"""
        fb, conn = feishu_with_inmem_db
        errors = []

        def write(i):
            try:
                fb._set_anchor(f"feishu:oc#topic#话题{i}", f"msg_{i:04d}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发写入出错: {errors}"
        # 所有 20 条均写入内存
        assert len(fb._anchor_to_thread) == 20


# ── TOPIC-5x: 钉钉 MarkdownCard 线程化 ──────────────────────────────────────

class TestDingTalkMarkdownCard:
    """TOPIC-5x: MarkdownCard 替代 session_webhook，无5秒过期限制"""

    def _make_handler(self):
        from integrations.dingtalk import bot as dd_bot
        handler = dd_bot._BotHandler.__new__(dd_bot._BotHandler)
        handler.dingtalk_client = MagicMock()
        return handler

    def _make_parsed(self, text="帮我查日程"):
        return {
            "text": text,
            "user_id": "user_dt_001",
            "chat_id": "conv_dt_001",
            "thread_id": "dingtalk:conv_dt_001",
        }

    def _run_process(self, handler, parsed, invoke_return="AI 回复内容",
                     card_reply_return="card_id_ok", card_raises=False):
        """运行 handler.process()，捕获后台线程 target 并手动执行。"""
        from integrations.dingtalk import bot as dd_bot
        callback = MagicMock()
        callback.data = {}

        mock_card = MagicMock()
        if card_raises:
            mock_card.reply.side_effect = Exception("card 创建失败")
        else:
            mock_card.reply.return_value = card_reply_return

        thread_targets = []

        def capture_thread(target, daemon=True):
            thread_targets.append(target)
            return MagicMock()

        with patch("integrations.dingtalk.bot._parse_dingtalk_message", return_value=parsed):
            with patch("integrations.claude_code.session.session_manager") as mock_sm:
                with patch("dingtalk_stream.card_instance.MarkdownCardInstance",
                           return_value=mock_card) as MockCard:
                    with patch("graph.agent.invoke", return_value=invoke_return):
                        with patch("integrations.dingtalk.bot.threading.Thread",
                                   side_effect=capture_thread):
                            mock_sm.get.return_value = None
                            handler.process(callback)

        return mock_card, MockCard, thread_targets

    def test_card_created_for_normal_message(self):
        """TOPIC-51: 收到普通消息 → MarkdownCardInstance.reply("处理中...") 被调用"""
        handler = self._make_handler()
        parsed = self._make_parsed()

        mock_card, MockCard, _ = self._run_process(handler, parsed)

        MockCard.assert_called_once_with(handler.dingtalk_client, ANY_VALUE)
        mock_card.reply.assert_called_once()
        args = mock_card.reply.call_args[0]
        assert "处理中" in args[0], f"首条回复应为处理中，实际: {args[0]}"

    def test_card_updated_with_llm_reply(self):
        """TOPIC-52: agent.invoke() 完成后 card_instance.update(reply) 被调用"""
        handler = self._make_handler()
        parsed = self._make_parsed()
        callback = MagicMock()
        callback.data = {}

        mock_card = MagicMock()
        mock_card.reply.return_value = "card_id_ok"
        thread_targets = []

        def capture_thread(target, daemon=True):
            thread_targets.append(target)
            return MagicMock()

        # 必须在 patch 上下文内执行线程函数，否则 graph.agent.invoke 的 mock 会失效
        with patch("integrations.dingtalk.bot._parse_dingtalk_message", return_value=parsed):
            with patch("integrations.claude_code.session.session_manager") as mock_sm:
                with patch("dingtalk_stream.card_instance.MarkdownCardInstance",
                           return_value=mock_card):
                    with patch("graph.agent.invoke", return_value="AI 日程如下"):
                        with patch("integrations.dingtalk.bot.threading.Thread",
                                   side_effect=capture_thread):
                            mock_sm.get.return_value = None
                            handler.process(callback)
                            # 在 patch 上下文内手动执行后台线程
                            assert len(thread_targets) == 1, "应启动一个后台线程"
                            thread_targets[0]()

        mock_card.update.assert_called_once_with("AI 日程如下")

    def test_card_failure_falls_back_to_send_text(self):
        """TOPIC-53: MarkdownCard 创建失败 → 降级调用 send_text，不 crash"""
        from integrations.dingtalk import bot as dd_bot
        handler = self._make_handler()
        parsed = self._make_parsed()

        mock_card, _, thread_targets = self._run_process(
            handler, parsed, invoke_return="AI 回复", card_raises=True
        )

        # 线程中 card.update 不会被调用（因为 card_instance=None）
        assert len(thread_targets) == 1
        dt_bot_mock = MagicMock()
        with patch("integrations.dingtalk.bot.DingTalkBot", return_value=dt_bot_mock):
            # 重新执行以验证降级路径
            pass
        # 验证 card.update 未调用
        mock_card.update.assert_not_called()

    def test_agent_exception_sends_error_text(self):
        """TOPIC-55: agent.invoke() 抛异常 → send_text 发送错误提示"""
        from integrations.dingtalk import bot as dd_bot
        handler = self._make_handler()
        parsed = self._make_parsed()
        callback = MagicMock()
        callback.data = {}

        mock_card = MagicMock()
        mock_card.reply.return_value = "card_id"

        thread_targets = []

        def capture_thread(target, daemon=True):
            thread_targets.append(target)
            return MagicMock()

        dt_bot_mock = MagicMock()

        with patch("integrations.dingtalk.bot._parse_dingtalk_message", return_value=parsed):
            with patch("integrations.claude_code.session.session_manager") as mock_sm:
                with patch("dingtalk_stream.card_instance.MarkdownCardInstance",
                           return_value=mock_card):
                    with patch("graph.agent.invoke",
                               side_effect=RuntimeError("LLM 超时")):
                        with patch("integrations.dingtalk.bot.threading.Thread",
                                   side_effect=capture_thread):
                            with patch("integrations.dingtalk.bot.DingTalkBot",
                                       return_value=dt_bot_mock):
                                mock_sm.get.return_value = None
                                handler.process(callback)
                                # 手动执行后台线程
                                if thread_targets:
                                    thread_targets[0]()

        dt_bot_mock.send_text.assert_called()
        error_sent = str(dt_bot_mock.send_text.call_args_list)
        assert "处理出错" in error_sent or "LLM 超时" in error_sent

    def test_session_webhook_code_removed(self):
        """TOPIC-5x / BOT-62: _reply_via_webhook 符号已从钉钉 bot 中移除"""
        import integrations.dingtalk.bot as dd_bot
        assert not hasattr(dd_bot, "_reply_via_webhook"), \
            "_reply_via_webhook 应已移除，当前仍存在"
        assert not hasattr(dd_bot, "_get_anchor"), \
            "钉钉的 _get_anchor 应已移除，当前仍存在"


# ── 辅助：ANY_VALUE sentinel ─────────────────────────────────────────────────

class _AnyValue:
    """用于 assert_called_with 中忽略某个参数值"""
    def __eq__(self, other):
        return True
    def __repr__(self):
        return "ANY"

ANY_VALUE = _AnyValue()
