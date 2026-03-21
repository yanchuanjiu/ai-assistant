"""
回归测试：火山云 Ark 文本格式工具调用解析器（v0.8.23）

覆盖 graph/nodes.py 的 _extract_text_tool_calls()：
  VEP-1x  单个工具调用（标准 Begin 变体）
  VEP-2x  双 Begin 变体（BeginBegin）
  VEP-3x  多个工具调用
  VEP-4x  缺失工具调用标记 → 返回 None
  VEP-5x  格式损坏 → 安全降级返回 None
  VEP-6x  参数字段兼容性（parameters vs arguments）
"""
import pytest
from graph.nodes import _extract_text_tool_calls


# ── VEP-1x: 单个工具调用（FunctionCallBegin）─────────────────────────────────
class TestSingleToolCall:

    def test_basic_single_call(self):
        """标准单个工具调用 → 解析为1项 tool_call"""
        content = (
            '<|FunctionCallBegin|>'
            '[{"name": "feishu_read_page", "parameters": {"wiki_url_or_token": "abc123"}}]'
            '<|FunctionCallEnd|>'
        )
        result = _extract_text_tool_calls(content)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "feishu_read_page"
        assert result[0]["args"] == {"wiki_url_or_token": "abc123"}
        assert result[0]["type"] == "tool_call"

    def test_call_id_generated(self):
        """tool_call 应有 id 字段，格式为 call_{...}"""
        content = (
            '<|FunctionCallBegin|>'
            '[{"name": "web_search", "parameters": {"query": "天气"}}]'
            '<|FunctionCallEnd|>'
        )
        result = _extract_text_tool_calls(content)
        assert result[0]["id"].startswith("call_")

    def test_with_explicit_id(self):
        """工具调用中带 id 字段 → id 被保留"""
        content = (
            '<|FunctionCallBegin|>'
            '[{"id": "xyz", "name": "run_command", "parameters": {"command": "ls"}}]'
            '<|FunctionCallEnd|>'
        )
        result = _extract_text_tool_calls(content)
        assert result[0]["id"] == "call_xyz"

    def test_content_before_and_after_marker(self):
        """标记前后有普通文本 → 只解析标记内部"""
        content = (
            "这是思考过程...\n"
            '<|FunctionCallBegin|>'
            '[{"name": "get_system_status", "parameters": {}}]'
            '<|FunctionCallEnd|>'
            "\n后续文本"
        )
        result = _extract_text_tool_calls(content)
        assert result is not None
        assert result[0]["name"] == "get_system_status"


# ── VEP-2x: 双 Begin 变体（BeginBegin）───────────────────────────────────────
class TestDoubleBeginVariant:

    def test_begin_begin_variant(self):
        """<|FunctionCallBeginBegin|> 变体也能正确解析"""
        content = (
            '<|FunctionCallBeginBegin|>'
            '[{"name": "agent_config", "parameters": {"action": "list"}}]'
            '<|FunctionCallEndEnd|>'
        )
        result = _extract_text_tool_calls(content)
        assert result is not None
        assert result[0]["name"] == "agent_config"
        assert result[0]["args"] == {"action": "list"}

    def test_begin_begin_without_end_tag(self):
        """有 BeginBegin 但无 EndEnd → 仍能解析（$ 锚定）"""
        content = (
            '<|FunctionCallBeginBegin|>'
            '[{"name": "feishu_search_wiki", "parameters": {"query": "项目"}}]'
        )
        result = _extract_text_tool_calls(content)
        assert result is not None
        assert result[0]["name"] == "feishu_search_wiki"


# ── VEP-3x: 多个工具调用─────────────────────────────────────────────────────
class TestMultipleToolCalls:

    def test_two_tool_calls(self):
        """数组包含两个工具调用 → 解析为2项"""
        content = (
            '<|FunctionCallBegin|>'
            '[{"name": "web_search", "parameters": {"query": "Python"}}, '
            '{"name": "web_fetch", "parameters": {"url": "https://example.com"}}]'
            '<|FunctionCallEnd|>'
        )
        result = _extract_text_tool_calls(content)
        assert result is not None
        assert len(result) == 2
        assert result[0]["name"] == "web_search"
        assert result[1]["name"] == "web_fetch"

    def test_multiple_calls_indexed_ids(self):
        """多个调用没有 id 时，id 使用索引（call_0, call_1 ...）"""
        content = (
            '<|FunctionCallBegin|>'
            '[{"name": "tool_a", "parameters": {}}, {"name": "tool_b", "parameters": {}}]'
            '<|FunctionCallEnd|>'
        )
        result = _extract_text_tool_calls(content)
        # id 用到了 i（索引）
        ids = [r["id"] for r in result]
        assert ids[0] == "call_0"
        assert ids[1] == "call_1"


# ── VEP-4x: 无工具调用标记 → 返回 None──────────────────────────────────────
class TestNoMarker:

    def test_plain_text_returns_none(self):
        """普通文本（无标记）→ 返回 None"""
        result = _extract_text_tool_calls("你好，有什么可以帮你？")
        assert result is None

    def test_empty_string_returns_none(self):
        """空字符串 → 返回 None"""
        result = _extract_text_tool_calls("")
        assert result is None

    def test_similar_but_invalid_marker(self):
        """相似但无效的标记 → 返回 None"""
        result = _extract_text_tool_calls("<|FunctionCall|>[{\"name\": \"test\"}]")
        assert result is None


# ── VEP-5x: 格式损坏 → 安全降级──────────────────────────────────────────────
class TestMalformedContent:

    def test_invalid_json_returns_none(self):
        """标记内 JSON 损坏 → 返回 None，不抛出异常"""
        content = '<|FunctionCallBegin|>NOT VALID JSON<|FunctionCallEnd|>'
        result = _extract_text_tool_calls(content)
        assert result is None

    def test_empty_array_returns_empty_list(self):
        """空数组 → 返回空列表（非 None）"""
        content = '<|FunctionCallBegin|>[]<|FunctionCallEnd|>'
        result = _extract_text_tool_calls(content)
        assert result == []

    def test_truncated_json_returns_none(self):
        """JSON 被截断（无 End 标记，且 JSON 不完整）→ 返回 None"""
        content = '<|FunctionCallBegin|>[{"name": "feishu_read_page", "para'
        result = _extract_text_tool_calls(content)
        assert result is None

    def test_missing_name_field_raises_no_exception(self):
        """缺少 name 字段 → 抛出 KeyError，被 except 捕获，返回 None"""
        content = (
            '<|FunctionCallBegin|>'
            '[{"parameters": {"key": "val"}}]'
            '<|FunctionCallEnd|>'
        )
        result = _extract_text_tool_calls(content)
        assert result is None


# ── VEP-6x: 参数字段兼容性─────────────────────────────────────────────────
class TestParameterFieldCompat:

    def test_parameters_field(self):
        """parameters 字段 → 映射到 args"""
        content = (
            '<|FunctionCallBegin|>'
            '[{"name": "agent_config", "parameters": {"action": "get", "key": "FOO"}}]'
            '<|FunctionCallEnd|>'
        )
        result = _extract_text_tool_calls(content)
        assert result[0]["args"] == {"action": "get", "key": "FOO"}

    def test_arguments_field(self):
        """arguments 字段（备用）→ 也能映射到 args"""
        content = (
            '<|FunctionCallBegin|>'
            '[{"name": "run_command", "arguments": {"command": "uptime"}}]'
            '<|FunctionCallEnd|>'
        )
        result = _extract_text_tool_calls(content)
        assert result[0]["args"] == {"command": "uptime"}

    def test_neither_field_returns_empty_args(self):
        """既无 parameters 也无 arguments → args 为空 dict"""
        content = (
            '<|FunctionCallBegin|>'
            '[{"name": "get_system_status"}]'
            '<|FunctionCallEnd|>'
        )
        result = _extract_text_tool_calls(content)
        assert result[0]["args"] == {}
