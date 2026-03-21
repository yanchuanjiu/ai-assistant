"""
回归测试：核心工具调用路径（mock API，验证参数传递与错误处理）

覆盖维度（P0）：
  TI-1x  agent_config — get/set/delete/list（临时 SQLite）
  TI-2x  get_service_status — crash.log 读取逻辑（mock subprocess）
  TI-3x  run_command / python_execute — 基础执行 + 超时
  TI-4x  list_claude_sessions / kill_claude_session — tmux mock
  TI-5x  feishu_bitable_record / feishu_bitable_meta — placeholder guard
  TI-6x  get_recent_chat_context — thread_id 解析
"""
import json
import os
import pytest
import tempfile
import threading
from unittest.mock import patch, MagicMock


# ── TI-1x: agent_config（隔离 SQLite）───────────────────────────────────────
class TestAgentConfig:
    """agent_config get/set/delete/list 使用临时 SQLite，不污染 data/memory.db"""

    @pytest.fixture(autouse=True)
    def isolate_db(self, tmp_path, monkeypatch):
        """将 config_store 的数据库重定向到临时文件"""
        import integrations.storage.config_store as cs
        tmp_db = str(tmp_path / "test_memory.db")
        monkeypatch.setattr(cs, "_DB_PATH", tmp_db)
        yield

    def _call(self, **kwargs):
        from graph.tools import agent_config
        return agent_config.invoke(kwargs)

    def test_set_and_get(self):
        """set 写入，get 读取 → 值一致"""
        self._call(action="set", key="TEST_KEY", value="hello_world")
        result = self._call(action="get", key="TEST_KEY")
        assert "hello_world" in result

    def test_get_nonexistent_key(self):
        """get 不存在的 key → 提示未配置"""
        result = self._call(action="get", key="NONEXISTENT_KEY")
        assert "未配置" in result or "NONEXISTENT_KEY" in result

    def test_set_empty_value_rejected(self):
        """set 空 key → 提示需要 key"""
        result = self._call(action="set", key="", value="something")
        assert "需要" in result or "key" in result.lower()

    def test_delete_existing_key(self):
        """delete 已存在的 key → 提示已删除"""
        self._call(action="set", key="DEL_KEY", value="val")
        result = self._call(action="delete", key="DEL_KEY")
        assert "已删除" in result

    def test_delete_nonexistent_key(self):
        """delete 不存在的 key → 提示不存在"""
        result = self._call(action="delete", key="GHOST_KEY")
        assert "不存在" in result

    def test_list_shows_all_keys(self):
        """list → 包含已设置的 key"""
        self._call(action="set", key="KEY_A", value="val_a")
        self._call(action="set", key="KEY_B", value="val_b")
        result = self._call(action="list")
        assert "KEY_A" in result
        assert "KEY_B" in result

    def test_list_empty_store(self):
        """空 store 时 list → 提示暂无配置"""
        result = self._call(action="list")
        assert "暂无配置" in result

    def test_unknown_action(self):
        """未知 action → 错误提示"""
        result = self._call(action="invalid_action", key="K", value="V")
        assert "未知" in result or "action" in result.lower()

    def test_update_overwrites_previous_value(self):
        """set 同一 key 两次 → 后者覆盖前者"""
        self._call(action="set", key="UPDATE_KEY", value="first")
        self._call(action="set", key="UPDATE_KEY", value="second")
        result = self._call(action="get", key="UPDATE_KEY")
        assert "second" in result
        assert "first" not in result


# ── TI-2x: get_service_status ────────────────────────────────────────────────
class TestGetServiceStatus:

    def test_reads_crash_log_entries(self, tmp_path, monkeypatch):
        """crash.log 存在时，最近 5 条崩溃记录被包含在输出中"""
        # 创建临时 crash.log
        crash_log = tmp_path / "logs" / "crash.log"
        crash_log.parent.mkdir(parents=True)
        entry = {"time": "2026-03-21T10:00:00", "thread": "feishu-ws", "error": "ConnectionError"}
        crash_log.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.stdout = "=== 主进程 ===\npython main.py\n"
        mock_result.stderr = ""

        import graph.tools as gt
        monkeypatch.setattr(gt, "PROJECT_DIR", str(tmp_path))

        with patch("subprocess.run", return_value=mock_result):
            from graph.tools import get_service_status
            result = get_service_status.invoke({})

        assert "feishu-ws" in result or "ConnectionError" in result

    def test_no_crash_log_shows_no_record(self, tmp_path, monkeypatch):
        """crash.log 不存在 → 输出'无崩溃记录'"""
        mock_result = MagicMock(stdout="=== 主进程 ===\n", stderr="")
        import graph.tools as gt
        monkeypatch.setattr(gt, "PROJECT_DIR", str(tmp_path))

        with patch("subprocess.run", return_value=mock_result):
            from graph.tools import get_service_status
            result = get_service_status.invoke({})

        assert "无崩溃记录" in result

    def test_output_within_4000_chars(self, tmp_path, monkeypatch):
        """输出截断不超过 4000 字符"""
        # 生成超长日志
        long_stdout = "x" * 10000
        mock_result = MagicMock(stdout=long_stdout, stderr="")
        import graph.tools as gt
        monkeypatch.setattr(gt, "PROJECT_DIR", str(tmp_path))

        with patch("subprocess.run", return_value=mock_result):
            from graph.tools import get_service_status
            result = get_service_status.invoke({})

        assert len(result) <= 4000


# ── TI-3x: run_command / python_execute──────────────────────────────────────
class TestRunCommandAndPythonExecute:

    def test_run_command_basic(self):
        """run_command 执行简单命令 → 返回输出"""
        from graph.tools import run_command
        result = run_command.invoke({"command": "echo hello_test"})
        assert "hello_test" in result

    def test_run_command_error_returns_stderr(self):
        """run_command 执行失败命令 → 返回错误信息（不崩溃）"""
        from graph.tools import run_command
        result = run_command.invoke({"command": "ls /nonexistent_path_xyz123"})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_run_command_output_truncated(self):
        """run_command 超长输出 → 截断至 3000 字符"""
        from graph.tools import run_command
        result = run_command.invoke({"command": "python3 -c \"print('x' * 10000)\""})
        assert len(result) <= 3000

    def test_python_execute_basic(self):
        """python_execute 执行 print → 返回输出"""
        from graph.tools import python_execute
        result = python_execute.invoke({"code": "print('hi_from_test')"})
        assert "hi_from_test" in result

    def test_python_execute_math(self):
        """python_execute 执行数学运算 → 正确结果"""
        from graph.tools import python_execute
        result = python_execute.invoke({"code": "print(2 + 2)"})
        assert "4" in result

    def test_python_execute_exception_captured(self):
        """python_execute 代码抛异常 → 返回 stderr 内容，不崩溃"""
        from graph.tools import python_execute
        result = python_execute.invoke({"code": "raise ValueError('test_error')"})
        assert isinstance(result, str)
        assert "ValueError" in result or "test_error" in result

    def test_python_execute_timeout_mock(self):
        """模拟超时 → 返回超时提示"""
        import subprocess
        from graph.tools import python_execute
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python3", timeout=30)):
            result = python_execute.invoke({"code": "import time; time.sleep(999)"})
        assert "超时" in result


# ── TI-4x: list/kill_claude_sessions（tmux mock）───────────────────────────
class TestClaudeSessionTools:

    def test_list_sessions_no_sessions(self):
        """无活跃 tmux 会话 → 返回'没有活跃'"""
        with patch("integrations.claude_code.tmux_session.list_active_sessions", return_value=[]):
            from graph.tools import list_claude_sessions
            result = list_claude_sessions.invoke({})
        assert "没有活跃" in result

    def test_list_sessions_shows_sessions(self):
        """有活跃会话 → 包含会话名称"""
        fake_sessions = [
            {"session_name": "ai-claude-feishu-test", "thread_id": "feishu:oc_123", "created": "2026-03-21T10:00:00"}
        ]
        with patch("integrations.claude_code.tmux_session.list_active_sessions", return_value=fake_sessions):
            from graph.tools import list_claude_sessions
            result = list_claude_sessions.invoke({})
        assert "ai-claude-feishu-test" in result
        assert "feishu:oc_123" in result

    def test_kill_session_not_found(self):
        """kill 不存在的会话 → 提示未找到"""
        # Mock _sessions（空 dict），_tmux 返回失败
        with patch("integrations.claude_code.tmux_session._sessions", {}), \
             patch("integrations.claude_code.tmux_session._sessions_lock", threading.Lock()), \
             patch("integrations.claude_code.tmux_session._tmux", return_value=(1, "no session")), \
             patch("integrations.claude_code.tmux_session.list_active_sessions", return_value=[]):
            from graph.tools import kill_claude_session
            result = kill_claude_session.invoke({"thread_id": "feishu:oc_nonexistent"})
        assert "未找到" in result or "不存在" in result


# ── TI-5x: feishu_bitable_record / feishu_bitable_meta ──────────────────────
class TestBitableTools:
    """Bitable 工具安全守卫与正常路径（mock API）"""

    def test_bitable_record_placeholder_blocked(self):
        """app_token 含 'placeholder' → 直接拒绝，不调 API"""
        from graph.tools import feishu_bitable_record
        result = feishu_bitable_record.invoke({
            "action": "list",
            "app_token": "placeholder_token",
            "table_id": "tbl123",
        })
        assert "无效" in result or "placeholder" in result.lower()

    def test_bitable_record_empty_app_token_blocked(self):
        """空 app_token → 拒绝"""
        from graph.tools import feishu_bitable_record
        result = feishu_bitable_record.invoke({
            "action": "list",
            "app_token": "",
            "table_id": "tbl123",
        })
        assert "无效" in result or "app_token" in result.lower()

    def test_bitable_meta_placeholder_blocked(self):
        """feishu_bitable_meta: placeholder app_token → 拒绝"""
        from graph.tools import feishu_bitable_meta
        result = feishu_bitable_meta.invoke({
            "action": "list_tables",
            "app_token": "PLACEHOLDER",
            "table_id": "",
        })
        assert "无效" in result or "PLACEHOLDER" in result

    def test_bitable_record_list_calls_api(self):
        """正常 list 操作 → 调用 feishu_post API（list 用 search endpoint）"""
        fake_resp = {"data": {"items": [{"record_id": "rec1", "fields": {"name": "测试"}}], "total": 1}}
        with patch("graph.tools.feishu_post", return_value=fake_resp) as mock_post:
            from graph.tools import feishu_bitable_record
            result = feishu_bitable_record.invoke({
                "action": "list",
                "app_token": "bascABC123",
                "table_id": "tblXYZ",
            })
        assert mock_post.called
        assert "rec1" in result or "测试" in result or "1" in result

    def test_bitable_record_unknown_action(self):
        """未知 action → 提示无效或返回错误提示"""
        from graph.tools import feishu_bitable_record
        result = feishu_bitable_record.invoke({
            "action": "undefined_action",
            "app_token": "bascABC123",
            "table_id": "tblXYZ",
        })
        # 不应崩溃
        assert isinstance(result, str)


# ── TI-6x: get_recent_chat_context — thread_id 解析 ─────────────────────────
class TestGetRecentChatContext:

    def test_no_thread_id_returns_error(self):
        """无 thread_id 上下文 → 返回错误提示"""
        with patch("graph.nodes.get_tool_ctx", return_value=(None, None)):
            from graph.tools import get_recent_chat_context
            result = get_recent_chat_context.invoke({"limit": 3})
        assert "无法" in result or "获取" in result

    def test_invalid_thread_id_format(self):
        """thread_id 格式错误（无冒号）→ 返回解析错误"""
        with patch("graph.nodes.get_tool_ctx", return_value=("invalid_no_colon", None)):
            from graph.tools import get_recent_chat_context
            result = get_recent_chat_context.invoke({"limit": 3})
        assert "无法解析" in result or "无法" in result

    def test_dingtalk_platform_not_supported(self):
        """钉钉平台 → 返回'暂不支持'"""
        with patch("graph.nodes.get_tool_ctx", return_value=("dingtalk:chat_123", None)):
            from graph.tools import get_recent_chat_context
            result = get_recent_chat_context.invoke({"limit": 3})
        assert "钉钉" in result or "暂不支持" in result

    def test_feishu_platform_calls_api(self):
        """飞书平台 → 调用 feishu_get API，返回历史消息"""
        fake_resp = {
            "data": {
                "items": [
                    {"body": {"content": json.dumps({"text": "你好"})}, "sender": {"id": "ou_test"}}
                ]
            }
        }
        with patch("graph.nodes.get_tool_ctx", return_value=("feishu:oc_test_chat", None)), \
             patch("graph.tools.feishu_get", return_value=fake_resp):
            from graph.tools import get_recent_chat_context
            result = get_recent_chat_context.invoke({"limit": 3})
        assert "ou_test" in result or "你好" in result
