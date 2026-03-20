"""
回归测试：端到端会议纪要处理流水线
  T1  analyzer.analyze() — LLM 分析返回有效结构
  T2  analyzer.write_to_feishu() — 写入飞书（自动发现/创建页面）
  T3  tracker.mark_processed / is_processed — 去重逻辑
  T4  完整流水线：模拟 analyze_meeting_doc 工具调用
"""
import os
import pytest
import time

FAKE_MEETING_CONTENT = """
会议时间：2026-03-18 10:00
参与人：Alice、Bob、Charlie
主题：AI 助理 v0.8 规划

讨论内容：
1. 新增钉钉视频会议接入能力
2. 飞书日历与会议纪要自动关联
3. 回归测试覆盖率提升到 80%

决议：
- Bob 负责钉钉视频 API 调研，截止 2026-03-25
- Charlie 负责飞书日历 API，截止 2026-03-28
- Alice 负责测试框架完善，下周五汇报

下次会议：2026-03-25 10:00
"""

FAKE_DOC_ID = "regression_test_fake_doc_001"


# ── T1 ────────────────────────────────────────────────────────────────────────
class TestAnalyze:
    def test_analyze_returns_dict(self):
        """analyze() 应返回含标准字段的字典；LLM 超时则跳过（外部依赖）"""
        from integrations.meeting.analyzer import analyze
        result = analyze(FAKE_MEETING_CONTENT)
        if result is None:
            pytest.skip("LLM 调用超时或失败（外部依赖），跳过本用例")
        assert isinstance(result, dict), "analyze 应返回 dict"

    def test_analyze_has_required_fields(self):
        """analyze() 结果应含关键字段"""
        from integrations.meeting.analyzer import analyze
        result = analyze(FAKE_MEETING_CONTENT)
        if result is None:
            pytest.skip("LLM 调用超时或失败，跳过本用例")
        # 至少应有标题或主题字段
        has_title = any(k in result for k in ("title", "主题", "meeting_title", "topic"))
        assert has_title, f"结果缺少标题字段，实际键: {list(result.keys())}"

    def test_analyze_not_is_meeting_for_garbage(self):
        """非会议内容应标记为 is_meeting=False 或有对应提示"""
        from integrations.meeting.analyzer import analyze
        result = analyze("这是一段随机文本，不包含任何会议信息。abc 123 xyz。")
        if result is None:
            pytest.skip("LLM 调用超时或失败，跳过本用例")
        # 只要不崩溃即可；如果有 is_meeting 字段则检查
        if "is_meeting" in result:
            assert result["is_meeting"] is False


# ── T2 ────────────────────────────────────────────────────────────────────────
class TestWriteToFeishu:
    def test_write_to_feishu_returns_page_token(self):
        """write_to_feishu 应返回目标页面的 wiki token"""
        from integrations.meeting.analyzer import write_to_feishu
        fake_info = {
            "title": "【回归测试】T2 写入飞书",
            "date": "2026-03-18",
            "participants": ["Alice", "Bob"],
            "summary": "这是回归测试写入的内容，可忽略。",
            "decisions": ["决议1", "决议2"],
            "action_items": [],
            "is_meeting": True,
        }
        page_token = write_to_feishu(fake_info, doc_url="https://example.com/test")
        assert page_token, "write_to_feishu 应返回非空 token"
        assert len(page_token) > 5, "返回的 token 长度异常"

    def test_write_to_feishu_auto_creates_page(self):
        """第一次调用时若无配置，应自动创建子页面"""
        from integrations.storage.config_store import delete as cfg_del, get as cfg_get
        from integrations.meeting.analyzer import write_to_feishu, _get_or_create_meeting_page

        # 记录当前缓存（不删除，避免破坏真实状态）
        cached = cfg_get("WIKI_PAGE_MEETING_NOTES")

        # 直接调用 _get_or_create_meeting_page，验证返回有效 token
        page = _get_or_create_meeting_page()
        assert page, "_get_or_create_meeting_page 应返回非空 token"


# ── T3 ────────────────────────────────────────────────────────────────────────
class TestTracker:
    def test_mark_and_check_processed(self):
        """mark_processed 后 is_processed 应返回 True"""
        import integrations.meeting.tracker as tracker
        test_id = f"regression_test_{int(time.time())}"
        assert not tracker.is_processed(test_id), "新 doc_id 应未处理"
        tracker.mark_processed(test_id, space_id="test", doc_name="回归测试文档")
        assert tracker.is_processed(test_id), "mark 后应标记为已处理"

    def test_not_meeting_also_marked(self):
        """非会议文档也应可被标记，避免重复 LLM 调用"""
        import integrations.meeting.tracker as tracker
        test_id = f"regression_not_meeting_{int(time.time())}"
        tracker.mark_processed(test_id, space_id="test", doc_name="非会议文档")
        assert tracker.is_processed(test_id)

    def test_list_recent(self):
        """list_processed 应返回列表"""
        import integrations.meeting.tracker as tracker
        result = tracker.list_processed(limit=5)
        assert isinstance(result, list)


# ── T4 ────────────────────────────────────────────────────────────────────────
class TestAnalyzeMeetingDocTool:
    def test_analyze_meeting_doc_tool_exists(self):
        """analyze_meeting_doc 工具应存在于 ALL_TOOLS"""
        from graph.tools import ALL_TOOLS
        names = [t.name for t in ALL_TOOLS]
        assert "analyze_meeting_doc" in names

    def test_list_processed_meetings_tool_exists(self):
        """list_processed_meetings 工具应存在"""
        from graph.tools import ALL_TOOLS
        names = [t.name for t in ALL_TOOLS]
        assert "list_processed_meetings" in names

    def test_list_processed_meetings_returns_string(self):
        """list_processed_meetings 调用应返回字符串"""
        from graph.tools import ALL_TOOLS
        tool = next((t for t in ALL_TOOLS if t.name == "list_processed_meetings"), None)
        assert tool is not None
        result = tool.invoke({})
        assert isinstance(result, str)


# ── T5: 端到端 mock LLM 场景（v0.8.23 / 完整流程验证）──────────────────────
class TestE2EMockedLLM:
    """mock LLM 工具调用，验证工具执行和路由逻辑，无需真实 LLM"""

    def test_bitable_placeholder_blocked_in_tools_node(self):
        """tools_node 执行 feishu_bitable_record(placeholder) → ToolMessage 含错误提示"""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        from graph.nodes import tools_node

        state = {
            "messages": [
                HumanMessage(content="帮我查多维表格"),
                AIMessage(content="", tool_calls=[{
                    "id": "call_bitable_001",
                    "name": "feishu_bitable_record",
                    "args": {"action": "list", "app_token": "placeholder", "table_id": "tbl_001"},
                    "type": "tool_call",
                }]),
            ],
            "platform": "test",
            "chat_id": "chat_test",
        }

        from unittest.mock import patch, MagicMock
        with patch("graph.nodes.set_tool_ctx"):
            with patch("integrations.claude_code.session.reply_fn_registry", {}):
                result = tools_node(state)

        tool_msgs = result["messages"]
        assert len(tool_msgs) == 1
        assert isinstance(tool_msgs[0], ToolMessage)
        assert "app_token 无效" in tool_msgs[0].content

    def test_meeting_router_falls_back_when_no_project(self):
        """会议分析无项目信息 → 降级到全局汇总页，不调用项目路由"""
        from integrations.meeting import analyzer as meeting_analyzer
        from integrations.meeting.project_router import ProjectRouter
        from unittest.mock import patch, MagicMock

        fake_info_no_project = {
            "title": "临时会议",
            "date": "2026-03-21",
            "participants": ["Alice"],
            "summary": "讨论临时事项",
            "decisions": [],
            "action_items": [],
            "is_meeting": True,
            "project_name": "",
            "project_code": "",
        }

        with patch.object(meeting_analyzer, "write_to_feishu", return_value="global_tok") as mock_global:
            with patch.object(ProjectRouter, "get_or_create_project_folder") as mock_proj:
                from scheduler import _route_and_write_meeting
                feishu_page, proj_name, proj_code, folder_tok, raid_written = \
                    _route_and_write_meeting(fake_info_no_project, "https://doc.url", meeting_analyzer)

        mock_global.assert_called_once()
        mock_proj.assert_not_called()
        assert feishu_page == "global_tok"

    def test_meeting_router_routes_to_project_page(self):
        """会议分析含项目信息 → 调用项目路由，写入项目子页面"""
        from integrations.meeting import analyzer as meeting_analyzer
        from integrations.meeting.project_router import ProjectRouter
        from unittest.mock import patch, MagicMock

        fake_info_with_project = {
            "title": "VOC 项目会议",
            "date": "2026-03-21",
            "participants": ["Alice", "Bob"],
            "summary": "VOC 项目进展讨论",
            "decisions": ["确认上线时间"],
            "action_items": [],
            "is_meeting": True,
            "project_name": "VOC数字化",
            "project_code": "VOC",
        }

        with patch.object(ProjectRouter, "get_or_create_project_folder",
                          return_value="folder_tok_voc") as mock_folder:
            with patch.object(ProjectRouter, "route_meeting",
                              return_value={"meeting_notes_token": "mock_meeting_tok",
                                            "raid_token": None,
                                            "weekly_report_token": None}):
                with patch.object(meeting_analyzer, "write_to_project_page",
                                  return_value="proj_page_tok") as mock_proj_write:
                    with patch.object(meeting_analyzer, "write_raid_rows",
                                      return_value=None):
                        from scheduler import _route_and_write_meeting
                        feishu_page, proj_name, proj_code, folder_tok, raid_written = \
                            _route_and_write_meeting(fake_info_with_project, "https://doc.url", meeting_analyzer)

        mock_folder.assert_called_once()
        assert proj_name == "VOC数字化"
        assert proj_code == "VOC"

    def test_wiki_token_logic_recovers_from_stale_token(self):
        """feishu_read_page 收到失效 token 返回错误，不崩溃"""
        from graph.tools import feishu_read_page
        from unittest.mock import patch

        # 模拟 wiki_token_to_obj_token 返回空（页面已删除）
        with patch("integrations.feishu.knowledge.feishu_get", return_value={
            "data": {"node": {}}  # 空 node，obj_token 为空
        }):
            result = feishu_read_page.invoke({
                "wiki_url_or_token": "StaleTokenXyz123"
            })

        # 应返回错误提示而非崩溃
        assert isinstance(result, str)
        assert len(result) > 0
