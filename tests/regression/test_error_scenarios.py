"""
回归测试：历史 Bug 修复场景验证（全量 mock，无外部 API 依赖）

覆盖 CHANGELOG v0.8.6 ~ v0.8.23 中的 bug fix：
  ES-1x  feishu_bitable_meta/record placeholder 守门（v0.8.23）
  ES-2x  wiki_token_to_obj_token 空 obj_token 改为 WARNING（v0.8.23）
  ES-3x  space 级 token 检测 + list_wiki_children 不调 API（v0.8.8/v0.8.15）
  ES-4x  create_wiki_child_page obj_type 必须是 'docx'（v0.8.15）
  ES-5x  _append_text 分批写入，每批 40 行（v0.7.6）
"""
import logging
import pytest
from unittest.mock import patch, MagicMock


# ── ES-1x: Bitable placeholder 守门（v0.8.23）────────────────────────────────
class TestBitablePlaceholderGuard:
    """feishu_bitable_record / feishu_bitable_meta 的 placeholder 校验"""

    def test_bitable_record_placeholder_blocked(self):
        """app_token='placeholder' → 立即返回错误提示，不发 API 请求"""
        from graph.tools import feishu_bitable_record
        with patch("graph.tools.feishu_post") as mock_post:
            result = feishu_bitable_record.invoke({
                "action": "list", "app_token": "placeholder", "table_id": "tbl_001"
            })
        assert "app_token 无效" in result
        assert "feishu.cn/base" in result
        mock_post.assert_not_called()

    def test_bitable_record_empty_token_blocked(self):
        """app_token='' → 被 guard 拦截，不调 API"""
        from graph.tools import feishu_bitable_record
        with patch("graph.tools.feishu_post") as mock_post:
            result = feishu_bitable_record.invoke({
                "action": "list", "app_token": "", "table_id": "tbl_001"
            })
        assert "app_token 无效" in result
        mock_post.assert_not_called()

    def test_bitable_meta_placeholder_blocked(self):
        """feishu_bitable_meta: app_token 含 'placeholder' → 被拦截"""
        from graph.tools import feishu_bitable_meta
        with patch("graph.tools.feishu_get") as mock_get:
            result = feishu_bitable_meta.invoke({
                "action": "list_tables", "app_token": "my_placeholder_token"
            })
        assert "app_token 无效" in result
        mock_get.assert_not_called()

    def test_bitable_meta_empty_blocked(self):
        """feishu_bitable_meta: app_token='' → 被拦截"""
        from graph.tools import feishu_bitable_meta
        with patch("graph.tools.feishu_get") as mock_get:
            result = feishu_bitable_meta.invoke({
                "action": "list_tables", "app_token": ""
            })
        assert "app_token 无效" in result
        mock_get.assert_not_called()

    def test_bitable_record_valid_token_not_blocked(self):
        """有效 app_token → 不被 guard 拦截，正常发起 API 调用"""
        from graph.tools import feishu_bitable_record
        with patch("graph.tools.feishu_post", return_value={"data": {"items": [], "total": 0}}) as mock_post:
            feishu_bitable_record.invoke({
                "action": "list", "app_token": "real_token_abc123", "table_id": "tbl_001"
            })
        mock_post.assert_called_once()


# ── ES-2x: wiki_token_to_obj_token 改进（v0.8.23）────────────────────────────
class TestWikiTokenToObjToken:
    """空 obj_token 时应发 WARNING 日志而非静默失败"""

    def test_empty_obj_token_logs_warning(self, caplog):
        """API 返回空 node → warning 日志含 token 信息，函数返回 ('', 'docx')"""
        from integrations.feishu.knowledge import wiki_token_to_obj_token
        with patch("integrations.feishu.knowledge.feishu_get", return_value={
            "data": {"node": {}}
        }):
            with caplog.at_level(logging.WARNING, logger="integrations.feishu.knowledge"):
                obj_token, obj_type = wiki_token_to_obj_token("FakeDeletedToken")
        assert obj_token == ""
        assert obj_type == "docx"
        assert any("FakeDeletedToken" in r.message for r in caplog.records), \
            f"WARNING 日志应含 token，实际日志: {[r.message for r in caplog.records]}"

    def test_valid_token_returns_obj_token(self):
        """正常情况：返回 (obj_token, obj_type)，不发 WARNING"""
        from integrations.feishu.knowledge import wiki_token_to_obj_token
        with patch("integrations.feishu.knowledge.feishu_get", return_value={
            "data": {"node": {"obj_token": "docx_abc123", "obj_type": "docx"}}
        }):
            obj_token, obj_type = wiki_token_to_obj_token("ValidToken")
        assert obj_token == "docx_abc123"
        assert obj_type == "docx"

    def test_api_exception_propagates(self):
        """feishu_get 抛异常时，异常向上传播（不被吞掉）"""
        from integrations.feishu.knowledge import wiki_token_to_obj_token
        with patch("integrations.feishu.knowledge.feishu_get", side_effect=RuntimeError("网络错误")):
            with pytest.raises(RuntimeError, match="网络错误"):
                wiki_token_to_obj_token("AnyToken")


# ── ES-3x: space 级 token 处理（v0.8.8 / v0.8.15）──────────────────────────
class TestSpaceLevelToken:
    """_is_space_level_token 检测 + list_wiki_children 收到 space_id 不调 API"""

    @pytest.fixture(scope="class")
    def kb(self):
        from integrations.feishu.knowledge import FeishuKnowledge
        return FeishuKnowledge()

    @pytest.mark.parametrize("token,expected", [
        ("7618158120166034630", True),              # 纯数字 space_id
        ("space_7618158120166034630", True),        # space_ 前缀
        ("FalZwGDOkiqpbQkeAjGc8jaznMd", False),    # 正常 node token
        ("ObjTokenXyz123", False),                  # 正常 token
        ("", False),                                # 空字符串
    ])
    def test_is_space_level_token(self, kb, token, expected):
        assert kb._is_space_level_token(token) == expected, \
            f"_is_space_level_token({token!r}) 应为 {expected}"

    def test_list_children_space_id_no_api_call(self, kb):
        """传入 space_id → 返回空列表，不调用 feishu_get"""
        with patch("integrations.feishu.knowledge.feishu_get") as mock_get:
            result = kb.list_wiki_children("7618158120166034630")
        assert result == []
        mock_get.assert_not_called()

    def test_list_children_space_prefix_no_api_call(self, kb):
        """传入 space_XXX → 返回空列表，不调用 feishu_get"""
        with patch("integrations.feishu.knowledge.feishu_get") as mock_get:
            result = kb.list_wiki_children("space_7618158120166034630")
        assert result == []
        mock_get.assert_not_called()

    def test_list_children_normal_token_calls_api(self, kb):
        """传入正常 node token → 调用 feishu_get，返回子页面列表"""
        with patch("integrations.feishu.knowledge.feishu_get", return_value={
            "data": {"items": [{"node_token": "child_tok1", "title": "子页面1"}]}
        }) as mock_get:
            result = kb.list_wiki_children("FalZwGDOkiqpbQkeAjGc8jaznMd")
        mock_get.assert_called_once()
        assert len(result) == 1
        assert result[0]["node_token"] == "child_tok1"


# ── ES-4x: create_wiki_child_page obj_type（v0.8.15）────────────────────────
class TestCreateWikiChildPage:
    """方案A：obj_type 必须是 'docx'；space 父页面不传 parent_node_token"""

    @pytest.fixture(scope="class")
    def kb(self):
        from integrations.feishu.knowledge import FeishuKnowledge
        return FeishuKnowledge()

    def test_obj_type_is_docx_not_wiki(self, kb):
        """方案A payload 中 obj_type == 'docx'，不能是 'wiki'"""
        captured = {}

        def capture_post(path, json=None, **kwargs):
            if "/wiki/v2/spaces" in path and json:
                captured.update(json)
            return {"data": {"node": {"node_token": "new_tok_abc", "obj_token": "docx_xyz"}}}

        with patch("integrations.feishu.knowledge.feishu_post", side_effect=capture_post):
            kb.create_wiki_child_page("测试页面", "FalZwGDOkiqpbQkeAjGc8jaznMd")

        assert "obj_type" in captured, "payload 应含 obj_type 字段"
        assert captured["obj_type"] == "docx", f"obj_type 应为 docx，实际: {captured.get('obj_type')}"
        assert captured["obj_type"] != "wiki", "obj_type 不能是 'wiki'（无效枚举）"

    def test_space_parent_no_parent_node_token(self, kb):
        """space_id 作为父页面时，payload 不含 parent_node_token（在根目录创建）"""
        captured = {}

        def capture_post(path, json=None, **kwargs):
            if "/wiki/v2/spaces" in path and json:
                captured.update(json)
            return {"data": {"node": {"node_token": "root_tok", "obj_token": "docx_root"}}}

        with patch("integrations.feishu.knowledge.feishu_post", side_effect=capture_post):
            kb.create_wiki_child_page("根目录页面", "7618158120166034630")

        assert "parent_node_token" not in captured, \
            "space 级父页面创建时不应有 parent_node_token"

    def test_normal_parent_has_parent_node_token(self, kb):
        """普通 node token 作为父页面时，payload 含 parent_node_token"""
        captured = {}

        def capture_post(path, json=None, **kwargs):
            if "/wiki/v2/spaces" in path and json:
                captured.update(json)
            return {"data": {"node": {"node_token": "child_tok", "obj_token": "docx_child"}}}

        with patch("integrations.feishu.knowledge.feishu_post", side_effect=capture_post):
            kb.create_wiki_child_page("子页面", "FalZwGDOkiqpbQkeAjGc8jaznMd")

        assert "parent_node_token" in captured, "普通父页面应有 parent_node_token"
        assert captured["parent_node_token"] == "FalZwGDOkiqpbQkeAjGc8jaznMd"


# ── ES-5x: _append_text 分批写入（v0.7.6）────────────────────────────────────
class TestAppendTextChunking:
    """超过 50 块限制时自动分批，每批 40 行；批次间有 sleep"""

    @pytest.fixture(scope="class")
    def kb(self):
        from integrations.feishu.knowledge import FeishuKnowledge
        return FeishuKnowledge()

    def test_55_lines_split_into_2_batches(self, kb):
        """55 行内容 → 2 批（40 + 15），feishu_post 被调用 2 次"""
        content = "\n".join([f"行{i}" for i in range(55)])
        post_count = [0]

        def count_post(path, json=None, **kwargs):
            post_count[0] += 1
            return {}

        with patch("integrations.feishu.knowledge.feishu_post", side_effect=count_post):
            with patch("time.sleep"):
                kb._append_text("docx_abc", content)

        assert post_count[0] == 2, f"55行应分2批，实际调用 feishu_post {post_count[0]} 次"

    def test_40_lines_single_batch(self, kb):
        """恰好 40 行 → 1 批，feishu_post 被调用 1 次"""
        content = "\n".join([f"行{i}" for i in range(40)])
        post_count = [0]

        def count_post(path, json=None, **kwargs):
            post_count[0] += 1
            return {}

        with patch("integrations.feishu.knowledge.feishu_post", side_effect=count_post):
            with patch("time.sleep"):
                kb._append_text("docx_abc", content)

        assert post_count[0] == 1, f"40行应1批，实际调用 {post_count[0]} 次"

    def test_sleep_between_batches(self, kb):
        """55 行 → 2 批，批次之间有且仅有 1 次 sleep(0.3)"""
        content = "\n".join([f"行{i}" for i in range(55)])

        with patch("integrations.feishu.knowledge.feishu_post", return_value={}):
            with patch("time.sleep") as mock_sleep:
                kb._append_text("docx_abc", content)

        # 2批之间 sleep 1次，最后一批后不 sleep
        assert mock_sleep.call_count == 1, \
            f"2批应有1次sleep，实际 {mock_sleep.call_count} 次"
        mock_sleep.assert_called_with(0.3)

    def test_single_line_no_sleep(self, kb):
        """1 行内容 → 1 批，不需要 sleep"""
        with patch("integrations.feishu.knowledge.feishu_post", return_value={}):
            with patch("time.sleep") as mock_sleep:
                kb._append_text("docx_abc", "只有一行")

        assert mock_sleep.call_count == 0, "单批不应有 sleep"
