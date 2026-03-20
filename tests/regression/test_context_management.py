"""
回归测试：上下文管理逻辑（纯单元测试，无外部依赖）

覆盖 graph/nodes.py 的三个核心函数：
  CTX-1x  _trim_to_user_turns（v0.8.20/v0.8.22）
  CTX-2x  _build_system_prompt 按需加载（v0.8.21）
  CTX-3x  _select_tools 渐进式披露（v0.8.10/v0.8.22）
"""
import os
import pytest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage


# ── CTX-1x: _trim_to_user_turns ──────────────────────────────────────────────
class TestTrimToUserTurns:
    """MAX_USER_TURNS=2，历史 ToolMessage 截断至 100 字符"""

    @pytest.fixture(autouse=True)
    def import_fn(self):
        from graph.nodes import _trim_to_user_turns
        self.trim = _trim_to_user_turns

    def test_empty_messages_returns_empty(self):
        """空列表 → 返回空列表，不崩溃"""
        assert self.trim([]) == []

    def test_single_turn_not_trimmed(self):
        """只有 1 轮 → 全部返回（不触发截断）"""
        msgs = [HumanMessage(content="你好"), AIMessage(content="你好！")]
        result = self.trim(msgs)
        assert len(result) == 2

    def test_three_turns_keeps_last_two(self):
        """3 轮 → 只保留最近 2 轮（MAX_USER_TURNS=2）"""
        msgs = [
            HumanMessage(content="第1轮"),
            AIMessage(content="回复1"),
            HumanMessage(content="第2轮"),
            AIMessage(content="回复2"),
            HumanMessage(content="第3轮"),
            AIMessage(content="回复3"),
        ]
        result = self.trim(msgs)
        human_msgs = [m for m in result if isinstance(m, HumanMessage)]
        assert len(human_msgs) == 2
        assert human_msgs[0].content == "第2轮"
        assert human_msgs[1].content == "第3轮"

    def test_history_tool_message_truncated(self):
        """历史轮（非当前轮）的 ToolMessage 内容超 300 字符 → 截断至 100 + 省略标记"""
        long_content = "飞书页面全文内容" * 50  # 400 字符
        msgs = [
            HumanMessage(content="第1轮"),
            AIMessage(content="", tool_calls=[{"id": "c1", "name": "feishu_read_page", "args": {}, "type": "tool_call"}]),
            ToolMessage(content=long_content, tool_call_id="c1"),
            HumanMessage(content="第2轮"),
        ]
        result = self.trim(msgs)
        tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 1
        assert len(tool_msgs[0].content) < 300
        assert "工具结果已省略" in tool_msgs[0].content
        assert tool_msgs[0].content[:100] == long_content[:100]

    def test_current_turn_tool_message_not_truncated(self):
        """当前轮的 ToolMessage 内容超 300 字符 → 不截断"""
        long_content = "当前轮工具结果" * 60  # 420 字符
        msgs = [
            HumanMessage(content="第1轮"),
            AIMessage(content="回复1"),
            HumanMessage(content="第2轮"),
            AIMessage(content="", tool_calls=[{"id": "c2", "name": "feishu_read_page", "args": {}, "type": "tool_call"}]),
            ToolMessage(content=long_content, tool_call_id="c2"),
        ]
        result = self.trim(msgs)
        tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].content == long_content, "当前轮 ToolMessage 不应被截断"

    def test_short_tool_message_not_truncated(self):
        """历史轮 ToolMessage 内容 <= 300 字符 → 不截断"""
        short_content = "短结果" * 10  # 30 字符
        msgs = [
            HumanMessage(content="第1轮"),
            AIMessage(content="", tool_calls=[{"id": "c3", "name": "feishu_read_page", "args": {}, "type": "tool_call"}]),
            ToolMessage(content=short_content, tool_call_id="c3"),
            HumanMessage(content="第2轮"),
        ]
        result = self.trim(msgs)
        tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
        assert tool_msgs[0].content == short_content

    def test_only_one_turn_tool_messages_not_touched(self):
        """只有 1 轮用户消息时，步骤2 直接跳过（human_indices <= 1）"""
        long_content = "x" * 500
        msgs = [
            HumanMessage(content="唯一一轮"),
            AIMessage(content="", tool_calls=[{"id": "c4", "name": "feishu_read_page", "args": {}, "type": "tool_call"}]),
            ToolMessage(content=long_content, tool_call_id="c4"),
        ]
        result = self.trim(msgs)
        tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
        assert tool_msgs[0].content == long_content


# ── CTX-2x: _build_system_prompt 按需加载（v0.8.21）──────────────────────────
class TestBuildSystemPrompt:
    """简单消息跳过 MEMORY_HISTORY；关键词触发 SKILLS 注入"""

    @pytest.fixture
    def workspace(self, tmp_path, monkeypatch):
        """在 tmp_path 创建最小 workspace 文件结构，并切换工作目录"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "prompts").mkdir()
        (tmp_path / "prompts" / "system.md").write_text("系统提示词 {current_date}", encoding="utf-8")
        (tmp_path / "workspace").mkdir()
        (tmp_path / "workspace" / "SOUL.md").write_text("我是AI助理", encoding="utf-8")
        (tmp_path / "workspace" / "USER.md").write_text("用户信息", encoding="utf-8")
        (tmp_path / "workspace" / "MEMORY_CORE.md").write_text("核心记忆", encoding="utf-8")
        (tmp_path / "workspace" / "MEMORY_HISTORY.md").write_text("历史记忆内容_唯一标识", encoding="utf-8")
        (tmp_path / "workspace" / "SKILLS_PROJECT_MGMT.md").write_text("项目管理技能_唯一标识", encoding="utf-8")
        (tmp_path / "workspace" / "SKILLS_FEISHU_BITABLE.md").write_text("Bitable技能_唯一标识", encoding="utf-8")
        return tmp_path

    def test_simple_message_skips_memory_history(self, workspace):
        """简单消息（<30字，无复杂关键词）→ 不注入 MEMORY_HISTORY"""
        from graph.nodes import _build_system_prompt
        result = _build_system_prompt([HumanMessage(content="你好")])
        assert "历史记忆内容_唯一标识" not in result

    def test_simple_message_skips_skills(self, workspace):
        """简单消息 → 不注入 SKILLS_PROJECT_MGMT"""
        from graph.nodes import _build_system_prompt
        result = _build_system_prompt([HumanMessage(content="你好")])
        assert "项目管理技能_唯一标识" not in result

    def test_simple_message_includes_soul(self, workspace):
        """简单消息也应包含 SOUL（始终注入）"""
        from graph.nodes import _build_system_prompt
        result = _build_system_prompt([HumanMessage(content="你好")])
        assert "我是AI助理" in result

    def test_complex_message_includes_memory_history(self, workspace):
        """复杂消息（含"飞书"关键词）→ 注入 MEMORY_HISTORY"""
        from graph.nodes import _build_system_prompt
        result = _build_system_prompt([HumanMessage(content="帮我查一下飞书知识库的内容")])
        assert "历史记忆内容_唯一标识" in result

    def test_project_keyword_loads_skills(self, workspace):
        """消息含'项目'关键词 → 注入 SKILLS_PROJECT_MGMT"""
        from graph.nodes import _build_system_prompt
        result = _build_system_prompt([HumanMessage(content="帮我创建项目章程")])
        assert "项目管理技能_唯一标识" in result

    def test_bitable_keyword_loads_bitable_skill(self, workspace):
        """消息含'多维表格'→ 注入 SKILLS_FEISHU_BITABLE"""
        from graph.nodes import _build_system_prompt
        result = _build_system_prompt([HumanMessage(content="帮我操作多维表格")])
        assert "Bitable技能_唯一标识" in result

    def test_none_messages_treated_as_simple(self, workspace):
        """messages=None → 当作简单消息处理，只含基础内容"""
        from graph.nodes import _build_system_prompt
        result = _build_system_prompt(None)
        assert "我是AI助理" in result
        assert "历史记忆内容_唯一标识" not in result

    def test_date_placeholder_replaced(self, workspace):
        """{current_date} 占位符应被今天日期替换"""
        from graph.nodes import _build_system_prompt
        from datetime import date
        result = _build_system_prompt([HumanMessage(content="你好")])
        assert date.today().isoformat() in result
        assert "{current_date}" not in result

    def test_missing_file_does_not_crash(self, workspace):
        """workspace 文件不存在时，不崩溃，跳过该文件"""
        import os
        os.remove(workspace / "workspace" / "SOUL.md")
        from graph.nodes import _build_system_prompt
        result = _build_system_prompt([HumanMessage(content="你好")])
        assert isinstance(result, str)  # 不崩溃


# ── CTX-3x: _select_tools 渐进式披露（v0.8.10/v0.8.22）──────────────────────
class TestSelectTools:
    """短消息只返回 CORE_TOOLS；关键词触发对应分类"""

    @pytest.fixture(autouse=True)
    def import_fn(self):
        from graph.nodes import _select_tools
        from graph.tools import CORE_TOOLS
        self.select = _select_tools
        self.core_names = {t.name for t in CORE_TOOLS}

    def _tool_names(self, tools):
        return {t.name for t in tools}

    def test_short_greeting_returns_core_only(self):
        """纯问候'你好'（2字符）→ 只返回 CORE_TOOLS"""
        result = self.select([HumanMessage(content="你好")])
        names = self._tool_names(result)
        assert names == self.core_names, \
            f"问候应只含 CORE_TOOLS，多余工具: {names - self.core_names}"

    def test_empty_content_returns_core_only(self):
        """空内容 → 只返回 CORE_TOOLS"""
        result = self.select([HumanMessage(content="")])
        assert self._tool_names(result) == self.core_names

    def test_feishu_keyword_loads_wiki_tools(self):
        """消息含'飞书'→ 激活 feishu_wiki 分类，含 feishu_read_page"""
        result = self.select([HumanMessage(content="帮我读取飞书知识库")])
        names = self._tool_names(result)
        assert "feishu_read_page" in names, f"feishu_wiki 分类应被激活，实际: {names}"

    def test_wiki_keyword_loads_wiki_tools(self):
        """消息含'wiki'→ 激活 feishu_wiki 分类"""
        result = self.select([HumanMessage(content="查一下 wiki 页面")])
        names = self._tool_names(result)
        assert "feishu_read_page" in names

    def test_project_keyword_loads_wiki_tools(self):
        """消息含'项目'→ 激活 feishu_wiki 分类"""
        result = self.select([HumanMessage(content="帮我创建项目章程")])
        names = self._tool_names(result)
        assert "feishu_wiki_page" in names

    def test_bitable_keyword_loads_advanced_tools(self):
        """消息含'多维表格'→ 激活 feishu_advanced 分类，含 feishu_bitable_meta"""
        result = self.select([HumanMessage(content="查一下多维表格数据")])
        names = self._tool_names(result)
        assert "feishu_bitable_meta" in names

    def test_claude_keyword_loads_claude_tools(self):
        """消息含'迭代'→ 激活 claude 分类，含 trigger_self_iteration"""
        result = self.select([HumanMessage(content="帮我迭代这个功能")])
        names = self._tool_names(result)
        assert "trigger_self_iteration" in names

    def test_continuity_from_tool_calls(self):
        """历史消息含已调用的飞书工具 → 连续性保持，下一轮仍激活 feishu_wiki"""
        prev_ai = AIMessage(
            content="",
            tool_calls=[{"id": "c1", "name": "feishu_read_page", "args": {}, "type": "tool_call"}]
        )
        msgs = [
            HumanMessage(content="第1轮"),
            prev_ai,
            ToolMessage(content="页面内容", tool_call_id="c1"),
            # 消息需 >= 25 字符以绕过短消息快速返回，但不含飞书关键词
            HumanMessage(content="好的，我已经理解了，这件事情就先这样，不用继续处理"),
        ]
        result = self.select(msgs)
        names = self._tool_names(result)
        assert "feishu_read_page" in names, \
            "历史使用过 feishu_read_page，应通过连续性保持激活"

    def test_core_tools_always_present(self):
        """无论什么消息，CORE_TOOLS 始终存在"""
        for content in ["你好", "帮我操作飞书", "迭代功能", "多维表格", ""]:
            result = self.select([HumanMessage(content=content)])
            names = self._tool_names(result)
            missing = self.core_names - names
            assert not missing, f"消息'{content}'时 CORE_TOOLS 缺少: {missing}"
