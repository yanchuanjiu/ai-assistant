"""
端到端 Smoke 测试：真实 LLM 全链路验证

场景选取原则：
  - 问题有确定性答案（数学、语言事实）
  - 不依赖外部工具（不调飞书/钉钉 API）
  - 执行时间可控（< 30s）

覆盖：
  E2E-1x  基础问答（无话题，验证 agent 正常工作）
  E2E-2x  话题隔离（不同 thread_id 上下文互不干扰）
"""
import time
import pytest

# ── 跳过条件：无法导入 graph.agent 或无 LLM 配置时跳过 ────────────────────
try:
    from graph.agent import invoke
    _AGENT_AVAILABLE = True
except Exception:
    _AGENT_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _AGENT_AVAILABLE,
    reason="graph.agent 不可用，跳过 E2E 测试"
)


# ── E2E-1x: 基础问答 ─────────────────────────────────────────────────────────

class TestBasicQA:
    """E2E-1x: 简单问题，验证 agent.invoke() 返回有效答复"""

    def test_math_addition(self):
        """E2E-11: 2+3=5，模型应包含正确答案"""
        reply = invoke(
            message="2加3等于几？请直接给出数字答案",
            platform="test",
            user_id="e2e_u1",
            chat_id="e2e_c1",
        )
        assert reply, "回复不应为空"
        assert "5" in reply, f"数学加法答案应含 '5'，实际回复: {reply!r}"

    def test_python_inventor(self):
        """E2E-12: Python 发明者，模型应提及 Guido"""
        reply = invoke(
            message="Python 编程语言是谁发明的？只说名字",
            platform="test",
            user_id="e2e_u1",
            chat_id="e2e_c1",
        )
        assert reply, "回复不应为空"
        assert "guido" in reply.lower() or "吉多" in reply, (
            f"应提及 Guido van Rossum，实际回复: {reply!r}"
        )

    def test_simple_math_multiplication(self):
        """E2E-13: 6×7=42，验证乘法"""
        reply = invoke(
            message="6乘以7等于多少？",
            platform="test",
            user_id="e2e_u1",
            chat_id="e2e_c2",
        )
        assert reply, "回复不应为空"
        assert "42" in reply, f"乘法答案应含 '42'，实际: {reply!r}"


# ── E2E-2x: 话题上下文隔离 ───────────────────────────────────────────────────

class TestTopicContextIsolation:
    """E2E-2x: 不同 thread_id 上下文完全独立，互不干扰"""

    def test_two_topics_context_isolated(self):
        """
        E2E-21: 话题 A 记住 x=42，话题 B 记住 x=99；
        各自查询 x 时应回答各自的值，不互相污染。
        """
        suffix = str(int(time.time()))
        tid_a = f"test:e2e_chat#topic#alpha_{suffix}"
        tid_b = f"test:e2e_chat#topic#beta_{suffix}"

        # 话题 A: 存入 x=42
        invoke(
            message="请记住一个数字：x等于42。确认后不需要多解释",
            platform="test",
            user_id="e2e_iso",
            chat_id="e2e_chat",
            thread_id=tid_a,
        )

        # 话题 B: 存入 x=99
        invoke(
            message="请记住一个数字：x等于99。确认后不需要多解释",
            platform="test",
            user_id="e2e_iso",
            chat_id="e2e_chat",
            thread_id=tid_b,
        )

        # 话题 A 查询 x
        reply_a = invoke(
            message="x等于多少？只说数字",
            platform="test",
            user_id="e2e_iso",
            chat_id="e2e_chat",
            thread_id=tid_a,
        )

        # 话题 B 查询 x
        reply_b = invoke(
            message="x等于多少？只说数字",
            platform="test",
            user_id="e2e_iso",
            chat_id="e2e_chat",
            thread_id=tid_b,
        )

        assert "42" in reply_a, (
            f"话题 A 应回答 42（上下文独立），实际: {reply_a!r}"
        )
        assert "99" in reply_b, (
            f"话题 B 应回答 99（上下文独立），实际: {reply_b!r}"
        )
        # 确认未发生污染
        assert "99" not in reply_a, f"话题 A 不应含有 B 的值 99，实际: {reply_a!r}"
        assert "42" not in reply_b, f"话题 B 不应含有 A 的值 42，实际: {reply_b!r}"

    def test_math_within_topic_context(self):
        """
        E2E-22: 在同一话题内连续对话，后续消息能引用前面的上下文。
        先给出 5 的平方，再问"结果是多少"，应回答 25。
        """
        suffix = str(int(time.time()))
        tid = f"test:e2e_chat#topic#math_{suffix}"

        # 第一轮：触发计算，存入上下文
        invoke(
            message="5的平方是多少？",
            platform="test",
            user_id="e2e_math",
            chat_id="e2e_chat",
            thread_id=tid,
        )

        # 第二轮：引用上下文
        reply = invoke(
            message="你刚才说的那个结果是多少？只说数字",
            platform="test",
            user_id="e2e_math",
            chat_id="e2e_chat",
            thread_id=tid,
        )

        assert "25" in reply, (
            f"话题内上下文延续失败，应回答 25，实际: {reply!r}"
        )
