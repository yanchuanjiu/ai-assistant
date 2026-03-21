#!/usr/bin/env python3
"""
回归测试 CLI 入口

用法：
  python tests/regression/run_all.py           # 运行全部
  python tests/regression/run_all.py feishu    # 只跑飞书知识库
  python tests/regression/run_all.py dingtalk  # 只跑钉钉 MCP
  python tests/regression/run_all.py e2e       # 只跑端到端流水线
  python tests/regression/run_all.py error     # 只跑历史 bug 修复场景
  python tests/regression/run_all.py context   # 只跑上下文管理逻辑
  python tests/regression/run_all.py bot         # 只跑 Bot 层行为
  python tests/regression/run_all.py volcengine # 只跑火山云解析器
  python tests/regression/run_all.py tracker    # 只跑 error_tracker
  python tests/regression/run_all.py tools      # 只跑工具调用路径
  python tests/regression/run_all.py concurrency # 只跑并发安全

退出码：
  0 — 全部通过
  1 — 有测试失败
"""
import sys
import os

# 确保项目根在 path
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import subprocess

SUITE_MAP = {
    "feishu":      "tests/regression/test_feishu_wiki.py",
    "dingtalk":    "tests/regression/test_dingtalk_mcp.py",
    "e2e":         "tests/regression/test_e2e_pipeline.py",
    "error":       "tests/regression/test_error_scenarios.py",
    "context":     "tests/regression/test_context_management.py",
    "bot":         "tests/regression/test_bot_behavior.py",
    "volcengine":  "tests/regression/test_volcengine_parser.py",
    "tracker":     "tests/regression/test_error_tracker.py",
    "tools":       "tests/regression/test_tool_invocation.py",
    "concurrency": "tests/regression/test_concurrency.py",
}

def main():
    args = sys.argv[1:]

    if args and args[0] in SUITE_MAP:
        targets = [SUITE_MAP[args[0]]]
        label = args[0]
    else:
        targets = list(SUITE_MAP.values())
        label = "all"

    print(f"\n{'='*60}")
    print(f"  AI 助理回归测试 — {label.upper()}")
    print(f"{'='*60}\n")

    cmd = [
        sys.executable, "-m", "pytest",
        "-v", "--tb=short", "--no-header",
        "--color=yes",
    ] + targets

    result = subprocess.run(cmd, cwd=ROOT)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
