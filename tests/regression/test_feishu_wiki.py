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

CONTEXT_PAGE = os.getenv("FEISHU_WIKI_CONTEXT_PAGE", "LkmAwSTmbivFy9klt9RcTA50nde")
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


# ── T6: 错误场景回归（v0.8.18 修复）─────────────────────────────────────────
class TestErrorScenarios:
    """
    回归测试：覆盖实际发生过的错误场景
    SC-001: list_wiki_children 收到已删除/移动页面 token（400 Bad Request）应返回 []
    SC-002: _save_to_feishu_wiki 缓存 token 失效（页面被删）后自动恢复
    """

    def test_list_children_deleted_page_returns_empty(self, kb):
        """SC-001: 有效格式 token 但页面已删除/不在本空间，应返回 [] 而非抛异常"""
        from unittest.mock import patch

        # 模拟 feishu_get 对该 token 返回 400
        import httpx

        fake_400 = httpx.HTTPStatusError(
            "Client error '400 Bad Request'",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(400),
        )
        with patch("integrations.feishu.knowledge.feishu_get", side_effect=fake_400):
            result = kb.list_wiki_children("G1DKw2zgV2gLxvDycBLbyKkYJB5r9YAn")
        assert result == [], "400 错误应返回空列表，不应抛异常"

    def test_list_children_other_error_propagates(self, kb):
        """SC-001 变体：非 400 错误应正常抛出"""
        from unittest.mock import patch
        import httpx

        fake_500 = httpx.HTTPStatusError(
            "Server error '500'",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(500),
        )
        with patch("integrations.feishu.knowledge.feishu_get", side_effect=fake_500):
            with pytest.raises(Exception):
                kb.list_wiki_children("SomeValidToken123")

    def test_list_children_tool_invalid_token_no_crash(self):
        """SC-001 工具层：list_children 传入已删除 token，工具不崩溃，返回字符串"""
        from unittest.mock import patch
        import httpx
        from graph.tools import feishu_wiki_page

        fake_400 = httpx.HTTPStatusError(
            "Client error '400 Bad Request'",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(400),
        )
        with patch("integrations.feishu.knowledge.feishu_get", side_effect=fake_400):
            result = feishu_wiki_page.invoke({
                "action": "list_children",
                "parent_wiki_token": "G1DKw2zgV2gLxvDycBLbyKkYJB5r9YAn",
            })
        # 应返回"暂无子页面"或报错字符串，而不是抛异常
        assert isinstance(result, str)

    def test_save_to_wiki_stale_cache_recovery(self):
        """SC-002: _save_to_feishu_wiki 第一次 append 失败（缓存 token 已失效），
        清缓存后第二次应成功，且缓存被清除。"""
        from unittest.mock import patch, MagicMock

        call_count = {"n": 0}
        good_token = "NewFreshToken123"

        def mock_find_or_create(title, parent_wiki_token, cache_key=""):
            return good_token

        def mock_append(wiki_token, content):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("Client error '400 Bad Request'")
            # 第二次成功

        deleted_keys = []

        def mock_cfg_delete(key):
            deleted_keys.append(key)

        with patch("integrations.feishu.knowledge.FeishuKnowledge") as MockKB, \
             patch("integrations.feishu.bot.cfg_delete", mock_cfg_delete, create=True):
            mock_kb = MagicMock()
            mock_kb.find_or_create_child_page.side_effect = mock_find_or_create
            mock_kb.append_to_page.side_effect = mock_append
            MockKB.return_value = mock_kb

            import os
            import importlib
            import integrations.feishu.bot as bot_module

            # 直接测试 _save_to_feishu_wiki 逻辑（用 patch 替换 config_store.delete）
            with patch.dict(os.environ, {"FEISHU_WIKI_CONTEXT_PAGE": "FalZwGDOkiqpbQkeAjGc8jaznMd"}):
                with patch("integrations.storage.config_store.delete") as mock_store_del:
                    # 创建一个 FeishuBot 实例（不启动真正的连接）
                    bot = bot_module.FeishuBot.__new__(bot_module.FeishuBot)
                    result = bot._save_to_feishu_wiki("测试内容")

            assert result == good_token, "恢复后应返回新 token"
            assert call_count["n"] == 2, "append_to_page 应被调用两次（第一次失败，第二次成功）"
            mock_store_del.assert_called_once_with("AI_REPLY_DETAIL_PAGE")
