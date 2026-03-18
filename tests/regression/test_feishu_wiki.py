"""
回归测试：飞书知识库能力
  T1  读取已知页面
  T2  追加内容（小量，分批写入）
  T3  列出子页面
  T4  查找或创建子页面（find_or_create）
  T5  feishu_wiki_page 工具端到端
"""
import os
import pytest
from integrations.feishu.knowledge import FeishuKnowledge, parse_wiki_token, wiki_token_to_obj_token

CONTEXT_PAGE = os.getenv("FEISHU_WIKI_CONTEXT_PAGE", "FalZwGDOkiqpbQkeAjGc8jaznMd")
TEST_CHILD_TITLE = "🧪 回归测试子页面（可删）"
CACHE_KEY = "WIKI_PAGE_REGRESSION_TEST"


@pytest.fixture(scope="module")
def kb():
    return FeishuKnowledge()


# ── T1 ────────────────────────────────────────────────────────────────────────
class TestRead:
    def test_parse_wiki_token_url(self):
        url = "https://pw46ob73t1c.feishu.cn/wiki/FalZwGDOkiqpbQkeAjGc8jaznMd"
        assert parse_wiki_token(url) == "FalZwGDOkiqpbQkeAjGc8jaznMd"

    def test_parse_wiki_token_bare(self):
        assert parse_wiki_token("FalZwGDOkiqpbQkeAjGc8jaznMd") == "FalZwGDOkiqpbQkeAjGc8jaznMd"

    def test_wiki_token_to_obj_token(self):
        obj_token, obj_type = wiki_token_to_obj_token(CONTEXT_PAGE)
        assert obj_token, "obj_token 不应为空"
        assert obj_type == "docx"

    def test_read_context_page(self, kb):
        content = kb.read_page(CONTEXT_PAGE)
        assert isinstance(content, str)
        assert len(content) > 0, "页面内容不应为空"


# ── T2 ────────────────────────────────────────────────────────────────────────
class TestAppend:
    def test_append_small_content(self, kb):
        """追加单行，验证不报错且内容存在"""
        marker = "【回归测试-T2-追加】"
        kb.append_to_page(CONTEXT_PAGE, marker)
        content = kb.read_page(CONTEXT_PAGE)
        assert marker in content, "追加的内容应在页面中可读"

    def test_append_large_content_chunked(self, kb):
        """追加 >40 行，验证分批写入正常（超 50 块限制）"""
        lines = [f"回归测试行 {i:03d}" for i in range(55)]
        big_text = "\n".join(lines)
        kb.append_to_page(CONTEXT_PAGE, big_text)  # 不应抛异常


# ── T3 ────────────────────────────────────────────────────────────────────────
class TestListChildren:
    def test_list_children_returns_list(self, kb):
        children = kb.list_wiki_children(CONTEXT_PAGE)
        assert isinstance(children, list)

    def test_list_children_has_fields(self, kb):
        children = kb.list_wiki_children(CONTEXT_PAGE)
        for child in children:
            assert "node_token" in child
            assert "title" in child


# ── T4 ────────────────────────────────────────────────────────────────────────
class TestFindOrCreate:
    def test_find_or_create_new(self, kb):
        """首次调用应创建子页面并返回 token"""
        # 先删除缓存，确保走完整流程
        from integrations.storage.config_store import delete as cfg_del
        cfg_del(CACHE_KEY)

        token = kb.find_or_create_child_page(TEST_CHILD_TITLE, CONTEXT_PAGE, CACHE_KEY)
        assert token, "返回 token 不应为空"
        assert len(token) > 5

    def test_find_or_create_cached(self, kb):
        """二次调用应命中缓存，返回相同 token"""
        from integrations.storage.config_store import get as cfg_get
        cached = cfg_get(CACHE_KEY)
        assert cached, "第一次调用后缓存应已写入"

        token = kb.find_or_create_child_page(TEST_CHILD_TITLE, CONTEXT_PAGE, CACHE_KEY)
        assert token == cached, "缓存命中应返回相同 token"

    def test_find_or_create_finds_existing(self, kb):
        """删除缓存后，应通过 list_children 找到已存在的页面"""
        from integrations.storage.config_store import delete as cfg_del, get as cfg_get
        first_token = cfg_get(CACHE_KEY)
        cfg_del(CACHE_KEY)  # 清缓存

        token = kb.find_or_create_child_page(TEST_CHILD_TITLE, CONTEXT_PAGE, CACHE_KEY)
        assert token == first_token, "应找到已有页面而不是新建"


# ── T5 ────────────────────────────────────────────────────────────────────────
class TestFeishuWikiPageTool:
    def test_list_children_tool(self):
        from graph.tools import feishu_wiki_page
        result = feishu_wiki_page.invoke({
            "action": "list_children",
            "parent_wiki_token": CONTEXT_PAGE,
        })
        assert isinstance(result, str)
        assert "token=" in result or "暂无" in result

    def test_find_or_create_tool(self):
        from graph.tools import feishu_wiki_page
        result = feishu_wiki_page.invoke({
            "action": "find_or_create",
            "title": TEST_CHILD_TITLE,
            "parent_wiki_token": CONTEXT_PAGE,
            "cache_key": CACHE_KEY,
        })
        assert "token=" in result
        assert "feishu.cn/wiki/" in result

    def test_unknown_action(self):
        from graph.tools import feishu_wiki_page
        result = feishu_wiki_page.invoke({"action": "invalid"})
        assert "未知" in result
