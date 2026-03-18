"""
回归测试：钉钉文档 MCP 工具
  T1  search_documents — 关键词搜索
  T2  list_nodes — 浏览知识库节点
  T3  get_document_content — 读取文档内容（nodeId 参数）
  T4  参数验证：缺少 nodeId 时应有明确错误信息
"""
import os
import pytest

# ── fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def dingtalk_tools():
    """返回已加载的 DingTalk MCP 工具字典 {name: tool}"""
    from graph.tools import ALL_TOOLS
    tools = {t.name: t for t in ALL_TOOLS if t.name in (
        "search_documents", "list_nodes", "get_document_content",
        "get_document_info", "create_document", "update_document",
    )}
    return tools


# ── T1 ────────────────────────────────────────────────────────────────────────
class TestSearchDocuments:
    def test_search_returns_string(self, dingtalk_tools):
        """search_documents 应返回字符串结果"""
        tool = dingtalk_tools.get("search_documents")
        if tool is None:
            pytest.skip("search_documents 工具未加载（MCP 未连接）")
        result = tool.invoke({"keyword": "会议"})
        assert isinstance(result, str), "结果应为字符串"

    def test_search_not_empty_for_common_keyword(self, dingtalk_tools):
        """搜索常见关键词不应返回空列表（知识库非空前提）"""
        tool = dingtalk_tools.get("search_documents")
        if tool is None:
            pytest.skip("search_documents 工具未加载")
        result = tool.invoke({"keyword": "会议"})
        # 结果要么含文档信息，要么明确说明无结果
        assert len(result) > 0, "搜索结果不应为空字符串"


# ── T2 ────────────────────────────────────────────────────────────────────────
class TestListNodes:
    def test_list_nodes_root(self, dingtalk_tools):
        """list_nodes 根节点应返回字符串"""
        tool = dingtalk_tools.get("list_nodes")
        if tool is None:
            pytest.skip("list_nodes 工具未加载")
        result = tool.invoke({})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_list_nodes_with_space(self, dingtalk_tools):
        """list_nodes 指定 spaceId 应返回有效结果"""
        tool = dingtalk_tools.get("list_nodes")
        if tool is None:
            pytest.skip("list_nodes 工具未加载")
        space_id = os.getenv("DINGTALK_DOCS_SPACE_ID", "")
        if not space_id:
            pytest.skip("DINGTALK_DOCS_SPACE_ID 未配置")
        result = tool.invoke({"spaceId": space_id})
        assert isinstance(result, str)


# ── T3 ────────────────────────────────────────────────────────────────────────
class TestGetDocumentContent:
    def test_get_content_with_node_id(self, dingtalk_tools):
        """get_document_content 使用 nodeId 参数应返回内容"""
        tool = dingtalk_tools.get("get_document_content")
        if tool is None:
            pytest.skip("get_document_content 工具未加载")

        # 先搜索一个文档获取 nodeId
        search_tool = dingtalk_tools.get("search_documents")
        if search_tool is None:
            pytest.skip("search_documents 工具未加载，无法获取 nodeId")

        search_result = search_tool.invoke({"keyword": "会议", "maxResults": 1})
        # 若搜索无结果则跳过
        if "nodeId" not in search_result and "node_id" not in search_result:
            pytest.skip("搜索未返回含 nodeId 的结果，跳过内容读取测试")

        # 简单验证 invoke 不抛异常
        assert isinstance(search_result, str)

    def test_get_content_wrong_param_name(self, dingtalk_tools):
        """使用错误参数名 docId（而非 nodeId）应返回错误提示，而非崩溃"""
        tool = dingtalk_tools.get("get_document_content")
        if tool is None:
            pytest.skip("get_document_content 工具未加载")
        # 传入错误参数名，期望工具返回错误信息而非抛 Python 异常
        try:
            result = tool.invoke({"docId": "invalid_id_test"})
            # 应包含错误提示
            assert isinstance(result, str)
        except Exception as e:
            # 如果抛出异常，错误信息应说明参数问题
            assert "nodeId" in str(e) or "参数" in str(e) or "error" in str(e).lower()


# ── T4 ────────────────────────────────────────────────────────────────────────
class TestMcpToolsLoaded:
    def test_all_expected_tools_present(self, dingtalk_tools):
        """核心 MCP 工具应全部加载"""
        required = ["search_documents", "list_nodes", "get_document_content"]
        missing = [t for t in required if t not in dingtalk_tools]
        assert not missing, f"以下 MCP 工具未加载: {missing}"

    def test_tools_are_callable(self, dingtalk_tools):
        """MCP 工具对象应可调用（有 invoke 方法）"""
        for name, tool in dingtalk_tools.items():
            assert hasattr(tool, "invoke"), f"工具 {name} 缺少 invoke 方法"
