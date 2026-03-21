"""
回归测试：error_tracker 错误追踪与 GitHub Issue 创建（v0.8.11）

覆盖 integrations/logging/error_tracker.py：
  ET-1x  detect_error_in_response — 关键词检测与误报过滤
  ET-2x  record_error — 计数递增与持久化
  ET-3x  get_fix_status — 状态读取
  ET-4x  GitHub issue 创建逻辑（mock subprocess）
  ET-5x  分析性上下文过滤（不误报自我改进报告）
"""
import json
import os
import pytest
import tempfile
import threading
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def isolated_tracker(tmp_path, monkeypatch):
    """每个测试使用独立的临时 tracker 文件，避免测试间污染。"""
    import integrations.logging.error_tracker as et
    tracker_path = str(tmp_path / "auto_fix_tracker.json")
    monkeypatch.setattr(et, "_TRACKER_FILE", tracker_path)
    yield tracker_path


# ── ET-1x: detect_error_in_response ──────────────────────────────────────────
class TestDetectErrorInResponse:

    def _detect(self, text):
        from integrations.logging.error_tracker import detect_error_in_response
        return detect_error_in_response(text)

    def test_no_error_returns_none(self):
        """正常回复（无错误词）→ 返回 None"""
        assert self._detect("任务已完成，数据已写入飞书知识库。") is None

    def test_error_keyword_detected(self):
        """包含'失败'→ 返回非空模式字符串"""
        result = self._detect("操作失败：连接超时，请稍后重试。")
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

    def test_exception_keyword_detected(self):
        """包含'Exception' → 检测到错误"""
        result = self._detect("Traceback (most recent call last):\nException: 连接被拒绝")
        assert result is not None

    def test_false_positive_no_error(self):
        """'没有错误' → 误报过滤，返回 None"""
        assert self._detect("运行完成，没有错误发生。") is None

    def test_false_positive_fixed_error(self):
        """'修复了错误' → 误报过滤，返回 None"""
        assert self._detect("已修复了错误，现在功能正常。") is None

    def test_pattern_normalized(self):
        """错误模式中的数字被归一化为 N"""
        result = self._detect("调用失败：HTTP 404 Not Found at 2024-01-01T12:34:56")
        assert result is not None
        # 数字应被替换
        import re
        assert not re.search(r'\b\d{4}\b', result), "日期数字应已被归一化"

    def test_pattern_truncated_to_80_chars(self):
        """返回的模式字符串不超过 80 字符"""
        long_error = "调用失败：" + "x" * 200
        result = self._detect(long_error)
        assert result is not None
        assert len(result) <= 80

    def test_english_error_detected(self):
        """英文 'failed' → 也能检测"""
        result = self._detect("Request failed with status 500")
        assert result is not None


# ── ET-2x: record_error — 计数递增─────────────────────────────────────────
class TestRecordError:

    def _record(self, pattern="测试错误模式", snippet="错误片段", platform="feishu", chat_id="oc_test"):
        from integrations.logging.error_tracker import record_error
        return record_error(pattern, snippet, platform, chat_id)

    def test_first_occurrence_returns_1(self):
        """第一次记录 → 返回 1"""
        count = self._record()
        assert count == 1

    def test_second_occurrence_returns_2(self):
        """同一模式第二次 → 返回 2"""
        self._record()
        count = self._record()
        assert count == 2

    def test_third_occurrence_returns_3(self):
        """第三次 → 返回 3"""
        for _ in range(3):
            count = self._record()
        assert count == 3

    def test_different_patterns_independent(self):
        """不同错误模式独立计数"""
        from integrations.logging.error_tracker import record_error
        count_a = record_error("pattern_A", "snippet_a", "feishu", "chat1")
        count_b = record_error("pattern_B", "snippet_b", "dingtalk", "chat2")
        assert count_a == 1
        assert count_b == 1

    def test_snippet_stored(self, isolated_tracker):
        """记录后，snippet 写入追踪文件"""
        from integrations.logging.error_tracker import record_error
        record_error("test_pattern", "最新错误片段", "feishu", "chat123")
        with open(isolated_tracker, "r", encoding="utf-8") as f:
            data = json.load(f)
        entry = data["patterns"]["test_pattern"]
        assert "最新错误片段" in entry["snippet"]
        assert entry["platform"] == "feishu"

    def test_snippet_truncated_to_200_chars(self, isolated_tracker):
        """snippet 超过 200 字符时截断"""
        from integrations.logging.error_tracker import record_error
        long_snippet = "x" * 500
        record_error("trunc_pattern", long_snippet, "feishu", "chat")
        with open(isolated_tracker, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["patterns"]["trunc_pattern"]["snippet"]) <= 200


# ── ET-3x: get_fix_status ────────────────────────────────────────────────────
class TestGetFixStatus:

    def test_unknown_pattern_returns_default(self):
        """未记录过的模式 → 返回默认状态"""
        from integrations.logging.error_tracker import get_fix_status
        status = get_fix_status("nonexistent_pattern")
        assert status["count"] == 0
        assert status["github_issue"] is None
        assert status["resolved"] is False

    def test_known_pattern_returns_count(self):
        """已记录的模式 → 返回正确计数"""
        from integrations.logging.error_tracker import record_error, get_fix_status
        record_error("known_pattern", "err", "feishu", "chat")
        record_error("known_pattern", "err", "feishu", "chat")
        status = get_fix_status("known_pattern")
        assert status["count"] == 2

    def test_github_issue_recorded(self):
        """record_github_issue 后，get_fix_status 能读取到 issue URL"""
        from integrations.logging.error_tracker import record_error, record_github_issue, get_fix_status
        record_error("issue_pattern", "err", "feishu", "chat")
        record_github_issue("issue_pattern", "https://github.com/test/repo/issues/42")
        status = get_fix_status("issue_pattern")
        assert status["github_issue"] == "https://github.com/test/repo/issues/42"


# ── ET-4x: GitHub issue 创建（mock subprocess）───────────────────────────────
class TestCreateGithubIssue:

    def test_issue_created_on_success(self):
        """gh CLI 成功 → 返回 issue URL"""
        from integrations.logging.error_tracker import create_github_issue
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/owner/repo/issues/99\n"
        with patch("subprocess.run", return_value=mock_result):
            url = create_github_issue("test_pattern", 3, "测试错误片段")
        assert url == "https://github.com/owner/repo/issues/99"

    def test_issue_returns_none_on_failure(self):
        """gh CLI 失败 → 返回 None，不抛异常"""
        from integrations.logging.error_tracker import create_github_issue
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "authentication failed"
        with patch("subprocess.run", return_value=mock_result):
            url = create_github_issue("test_pattern", 3, "snippet")
        assert url is None

    def test_issue_returns_none_if_gh_not_found(self):
        """gh CLI 未安装（FileNotFoundError）→ 返回 None，不崩溃"""
        from integrations.logging.error_tracker import create_github_issue
        with patch("subprocess.run", side_effect=FileNotFoundError):
            url = create_github_issue("test_pattern", 3, "snippet")
        assert url is None

    def test_issue_title_contains_count(self):
        """issue 标题中包含出现次数"""
        from integrations.logging.error_tracker import create_github_issue
        captured_args = {}
        mock_result = MagicMock(returncode=0, stdout="https://gh/i/1\n")

        def fake_run(cmd, **kwargs):
            captured_args["cmd"] = cmd
            return mock_result

        with patch("subprocess.run", side_effect=fake_run):
            create_github_issue("test_pattern", 5, "snippet")

        title_idx = captured_args["cmd"].index("--title") + 1
        assert "5" in captured_args["cmd"][title_idx]


# ── ET-5x: 分析性上下文过滤（不误报自我改进报告）─────────────────────────────
class TestAnalyticalContextFilter:

    def _detect(self, text):
        from integrations.logging.error_tracker import detect_error_in_response
        return detect_error_in_response(text)

    def test_self_improvement_report_not_flagged(self):
        """自我改进报告包含错误统计，但不应触发 error_tracker"""
        report = """## 🔍 自我改进报告

**分析周期**: 最近200条交互
**用户纠正率**: 5%（含重复提及的隐式纠正）

**发现的问题**:
- 统计失败率为 3%，主要集中在飞书 API 调用超时
- 分析错误模式：feishu_read_page 在大文档时超时失败
- 识别错误关键词：'连接失败' 出现 12 次

**已做的改进**:
- 更新了超时阈值
"""
        result = self._detect(report)
        assert result is None, f"自我改进报告不应被误报为错误，但得到: {result}"

    def test_real_error_still_detected(self):
        """真实错误回复（短且直接）仍能被检测"""
        result = self._detect("操作失败：API 返回 401 Unauthorized")
        assert result is not None

    def test_nearby_analytical_word_suppresses_detection(self):
        """错误词前100字符内有分析性词汇 → 过滤"""
        content = "统计失败率" + "x" * 5 + "操作失败了"
        result = self._detect(content)
        assert result is None

    def test_thread_safety_concurrent_records(self):
        """并发记录同一模式时，计数一致（无竞态条件）"""
        from integrations.logging.error_tracker import record_error
        results = []
        errors = []

        def record_fn():
            try:
                count = record_error("concurrent_pattern", "err", "feishu", "chat")
                results.append(count)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_fn) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发记录时出现异常: {errors}"
        assert len(results) == 10
        # 最终计数应该等于线程数（每次都是递增的唯一值）
        assert max(results) == 10
