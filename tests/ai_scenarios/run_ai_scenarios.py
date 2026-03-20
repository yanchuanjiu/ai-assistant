#!/usr/bin/env python3
"""
AI 优化场景回归测试入口
────────────────────────────────────────────────────────────────────────────
用法：
  python tests/ai_scenarios/run_ai_scenarios.py           # 运行全部
  python tests/ai_scenarios/run_ai_scenarios.py color     # 只跑色值场景
  python tests/ai_scenarios/run_ai_scenarios.py live      # 只跑直播场景
  python tests/ai_scenarios/run_ai_scenarios.py platform  # 只跑跨平台场景
  python tests/ai_scenarios/run_ai_scenarios.py --smoke   # 只跑 smoke 用例
  python tests/ai_scenarios/run_ai_scenarios.py --allure  # 生成 Allure 报告
"""

import sys
import os
import subprocess
import argparse
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENARIO_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports", "ai_scenarios")

SUITE_MAP = {
    "color":    "test_color_value.py",
    "live":     "test_live_stream.py",
    "platform": "test_cross_platform.py",
}


def build_pytest_args(suite: str | None, smoke: bool, allure: bool) -> list[str]:
    args = ["python", "-m", "pytest", "-v", "--tb=short"]

    # 选择测试文件
    if suite:
        if suite not in SUITE_MAP:
            print(f"[ERROR] 未知场景：{suite}，可选：{list(SUITE_MAP.keys())}")
            sys.exit(1)
        args.append(os.path.join(SCENARIO_DIR, SUITE_MAP[suite]))
    else:
        args.append(SCENARIO_DIR)

    # Smoke 标签过滤
    if smoke:
        args.extend(["-m", "smoke"])

    # Allure 报告
    if allure:
        allure_dir = os.path.join(REPORT_DIR, "allure_results")
        os.makedirs(allure_dir, exist_ok=True)
        args.extend([f"--allure-resultsdir={allure_dir}"])

    # JUnit XML 报告（CI 必需）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(REPORT_DIR, exist_ok=True)
    xml_path = os.path.join(REPORT_DIR, f"report_{ts}.xml")
    args.extend([f"--junitxml={xml_path}"])

    return args, xml_path


def main():
    parser = argparse.ArgumentParser(description="AI 优化场景回归测试")
    parser.add_argument("suite", nargs="?", choices=list(SUITE_MAP.keys()),
                        help="指定测试套件：color / live / platform（省略则运行全部）")
    parser.add_argument("--smoke", action="store_true", help="仅运行 smoke 标签用例")
    parser.add_argument("--allure", action="store_true", help="生成 Allure 报告")
    args = parser.parse_args()

    pytest_args, xml_path = build_pytest_args(args.suite, args.smoke, args.allure)

    print("=" * 60)
    print(f"AI 场景回归测试  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"套件：{args.suite or '全部'}")
    print(f"命令：{' '.join(pytest_args)}")
    print("=" * 60)

    result = subprocess.run(pytest_args, cwd=PROJECT_ROOT)

    print("=" * 60)
    print(f"JUnit XML：{xml_path}")
    if args.allure:
        allure_dir = os.path.join(REPORT_DIR, "allure_results")
        print(f"Allure 结果：{allure_dir}")
        print(f"查看报告：allure serve {allure_dir}")
    print("=" * 60)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
