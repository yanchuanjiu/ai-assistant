"""
conftest.py — AI 场景测试公共 fixtures 与配置
"""
import os
import sys
import json
import pytest

# 项目根目录加入 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# ── 测试用例库路径 ────────────────────────────────────────────────────────────
TEST_CASES_PATH = os.path.join(os.path.dirname(__file__), "test_cases.json")


def load_test_cases(scenario: str) -> list[dict]:
    """从 test_cases.json 加载指定场景的用例列表"""
    if not os.path.exists(TEST_CASES_PATH):
        return []
    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get(scenario, [])


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def sensetime_api_key():
    """商汤 API Key（从环境变量读取，CI 中注入 Secret）"""
    key = os.getenv("SENSETIME_API_KEY", "")
    if not key:
        pytest.skip("SENSETIME_API_KEY 未配置，跳过需要真实 API 的用例")
    return key


@pytest.fixture(scope="session")
def color_test_cases():
    return load_test_cases("color_value")


@pytest.fixture(scope="session")
def live_stream_test_cases():
    return load_test_cases("live_stream")


@pytest.fixture(scope="session")
def platform_test_cases():
    return load_test_cases("cross_platform")


@pytest.fixture(autouse=True)
def log_test_name(request, capfd):
    """每个测试开始/结束时打印标准日志，便于 CI 报告追踪"""
    print(f"\n[START] {request.node.nodeid}")
    yield
    captured = capfd.readouterr()
    if captured.out:
        print(captured.out, end="")
    print(f"[END]   {request.node.nodeid}")
