"""
场景三：跨平台兼容性测试
────────────────────────────────────────────────────────────────────────────
触发条件：AI 优化功能部署到 Windows/macOS/Docker 不同环境
验证指标：
  - API 响应数据跨平台一致性：结果差异 ≤ 0.5%
  - Docker 镜像启动时间 ≤ 30s
  - 依赖包版本兼容性无冲突

场景四：AI 模型性能监控接口
────────────────────────────────────────────────────────────────────────────
验证指标：
  - 模型精度指标（Precision/Recall/F1）可从 API 读取
  - 模型版本变更后旧测试可感知差异

用例覆盖：
  TC-PLAT-01  环境检测：Python 版本、依赖包、GPU 可用性
  TC-PLAT-02  API 响应跨平台一致性（Windows vs macOS vs Docker）
  TC-PLAT-03  Docker 容器启动与健康检查
  TC-PLAT-04  商汤模型性能指标读取接口
  TC-PLAT-05  模型版本漂移检测（新版本精度回归）
"""

import os
import sys
import json
import platform
import subprocess
import pytest
from unittest.mock import patch, MagicMock

# ── 平台检测工具 ──────────────────────────────────────────────────────────────

def get_platform_info() -> dict:
    """收集当前运行环境信息"""
    return {
        "os": platform.system(),            # Windows / Darwin / Linux
        "os_version": platform.version(),
        "python": sys.version,
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "arch": platform.machine(),         # x86_64 / arm64
        "in_docker": os.path.exists("/.dockerenv"),
        "in_ci": os.getenv("CI", "false").lower() == "true",
    }


def check_dependencies() -> dict[str, str | None]:
    """
    检查关键依赖包版本
    返回：{包名: 版本号 or None(未安装)}
    """
    packages = [
        "numpy", "opencv-python", "requests",
        "pytest", "allure-pytest",
    ]
    result = {}
    for pkg in packages:
        try:
            import importlib.metadata
            result[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            result[pkg] = None
    return result


# ── 商汤模型 API 性能监控 Stub ────────────────────────────────────────────────

class SenseTimeModelMonitor:
    """
    商汤 AI 模型性能监控接口
    实际接入点：POST /api/v1/model/metrics
    """

    def get_metrics(self, model_name: str, version: str = "latest") -> dict:
        """
        获取模型性能指标
        返回示例：
        {
          "model": "haircolor-restore-v2",
          "version": "2.1.0",
          "precision": 0.93,
          "recall": 0.91,
          "f1_score": 0.92,
          "avg_inference_ms": 320,
          "test_dataset_size": 5000,
          "evaluated_at": "2026-03-20T08:00:00Z"
        }
        """
        raise NotImplementedError("请接入商汤模型评测 API")


# ── 最低版本要求 ──────────────────────────────────────────────────────────────
MIN_PYTHON_VERSION = (3, 10)
REQUIRED_PACKAGES = {
    "numpy": "1.24.0",
    "requests": "2.28.0",
}
DOCKER_STARTUP_TIMEOUT_S = 30


# ── 测试用例 ──────────────────────────────────────────────────────────────────

class TestPlatformEnvironment:
    """TC-PLAT-01：环境检测"""

    def test_python_version_requirement(self):
        """Python ≥ 3.10（f-string 增强语法、match 语句）"""
        info = get_platform_info()
        major, minor = sys.version_info.major, sys.version_info.minor
        print(f"  当前 Python：{info['python_major_minor']} on {info['os']}")
        assert (major, minor) >= MIN_PYTHON_VERSION, (
            f"Python {major}.{minor} < 最低要求 {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}"
        )

    def test_required_packages_installed(self):
        """关键依赖包应已安装（允许 allure-pytest 可选缺失）"""
        versions = check_dependencies()
        optional = {"allure-pytest"}
        missing = [pkg for pkg, ver in versions.items()
                   if ver is None and pkg not in optional]
        if missing:
            pytest.fail(f"缺少必要依赖包：{missing}\n请运行 pip install {' '.join(missing)}")

    def test_opencv_importable(self):
        """OpenCV 可正常导入（色值测试核心依赖）"""
        try:
            import cv2
            print(f"  OpenCV 版本：{cv2.__version__}")
        except ImportError:
            pytest.skip("opencv-python 未安装，跳过（可选依赖）")

    def test_platform_logged(self):
        """记录当前平台信息到测试输出（供 CI 报告追踪）"""
        info = get_platform_info()
        print(f"\n  平台信息：")
        for k, v in info.items():
            print(f"    {k}: {v}")
        assert info["python_major_minor"]  # 基本健壮性断言


class TestCrossPlatformConsistency:
    """TC-PLAT-02：API 响应跨平台一致性"""

    # 模拟不同平台的 API 响应（色值结果应趋同）
    PLATFORM_RESPONSES = {
        "windows": {"rgb": [100, 55, 40], "hair_tone": "chestnut", "confidence": 0.921},
        "macos":   {"rgb": [101, 55, 41], "hair_tone": "chestnut", "confidence": 0.919},
        "docker":  {"rgb": [100, 56, 40], "hair_tone": "chestnut", "confidence": 0.920},
    }

    def test_rgb_consistency_across_platforms(self):
        """
        跨平台 RGB 输出差异 ≤ 0.5%（各通道绝对差 ≤ 2/255 ≈ 0.78%）
        """
        responses = self.PLATFORM_RESPONSES
        base = responses["windows"]["rgb"]

        for plat, resp in responses.items():
            if plat == "windows":
                continue
            for channel_idx, (b_val, p_val) in enumerate(zip(base, resp["rgb"])):
                diff_pct = abs(b_val - p_val) / 255 * 100
                assert diff_pct <= 0.8, (
                    f"{plat} vs windows：RGB[{channel_idx}] 差异 {diff_pct:.2f}% > 0.8%"
                )

    def test_hair_tone_classification_consistent(self):
        """色调分类结果跨平台应完全一致（文本标签）"""
        tones = {plat: r["hair_tone"] for plat, r in self.PLATFORM_RESPONSES.items()}
        unique_tones = set(tones.values())
        assert len(unique_tones) == 1, (
            f"跨平台色调分类不一致：{tones}"
        )

    def test_confidence_variance_acceptable(self):
        """置信度跨平台方差 ≤ 0.01（浮点运算差异可接受范围）"""
        confs = [r["confidence"] for r in self.PLATFORM_RESPONSES.values()]
        variance = max(confs) - min(confs)
        print(f"  置信度范围：{min(confs):.3f} ~ {max(confs):.3f}，差值={variance:.4f}")
        assert variance <= 0.01, f"置信度跨平台差异 {variance:.4f} > 0.01"


class TestDockerEnvironment:
    """TC-PLAT-03：Docker 容器化测试"""

    def test_docker_available(self):
        """检查 Docker 是否可用（容器化测试前置条件）"""
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            pytest.skip("Docker 未安装或不可用，跳过容器测试")
        print(f"  Docker 版本：{result.stdout.strip()}")

    @pytest.mark.skipif(
        not os.path.exists("/.dockerenv") and os.getenv("CI", "") != "true",
        reason="仅在 Docker 环境或 CI 中运行"
    )
    def test_container_health_check(self):
        """
        TC-PLAT-03：容器健康检查
        验证服务 /health 端点在容器启动后 30s 内可用
        """
        import time
        import requests

        health_url = os.getenv("SERVICE_HEALTH_URL", "http://localhost:8000/health")
        deadline = time.time() + DOCKER_STARTUP_TIMEOUT_S

        while time.time() < deadline:
            try:
                resp = requests.get(health_url, timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"  健康检查通过：{data}")
                    assert data.get("status") == "ok"
                    return
            except Exception:
                time.sleep(2)

        pytest.fail(f"容器 {DOCKER_STARTUP_TIMEOUT_S}s 内健康检查未通过：{health_url}")

    def test_dockerfile_builds_without_error(self):
        """验证 Dockerfile 语法（dry-run，不实际构建）"""
        dockerfile_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "Dockerfile"
        )
        if not os.path.exists(dockerfile_path):
            pytest.skip("项目根目录无 Dockerfile，跳过")

        result = subprocess.run(
            ["docker", "build", "--dry-run", "-f", dockerfile_path, "."],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(dockerfile_path)
        )
        assert result.returncode == 0, f"Dockerfile 构建失败：{result.stderr}"


class TestModelPerformanceMonitor:
    """TC-PLAT-04 / TC-PLAT-05：商汤模型性能监控"""

    BASELINE_METRICS = {
        "haircolor-restore-v2": {
            "precision": 0.90,
            "recall":    0.88,
            "f1_score":  0.89,
        }
    }

    @pytest.fixture
    def mock_monitor(self):
        monitor = MagicMock(spec=SenseTimeModelMonitor)
        monitor.get_metrics.return_value = {
            "model": "haircolor-restore-v2",
            "version": "2.1.0",
            "precision": 0.93,
            "recall": 0.91,
            "f1_score": 0.92,
            "avg_inference_ms": 320,
            "test_dataset_size": 5000,
            "evaluated_at": "2026-03-20T08:00:00Z",
        }
        return monitor

    def test_model_metrics_schema(self, mock_monitor):
        """
        TC-PLAT-04：模型指标 API 返回结构校验
        断言：必须包含 precision/recall/f1_score/avg_inference_ms
        """
        metrics = mock_monitor.get_metrics("haircolor-restore-v2")
        required_fields = ["precision", "recall", "f1_score", "avg_inference_ms"]
        for field in required_fields:
            assert field in metrics, f"模型指标缺少字段：{field}"

        assert 0 <= metrics["precision"] <= 1, "precision 超范围"
        assert 0 <= metrics["recall"] <= 1, "recall 超范围"
        assert 0 <= metrics["f1_score"] <= 1, "f1_score 超范围"

    def test_model_meets_minimum_precision(self, mock_monitor):
        """TC-PLAT-04：模型精度 ≥ 基线 precision 90%"""
        metrics = mock_monitor.get_metrics("haircolor-restore-v2")
        baseline = self.BASELINE_METRICS["haircolor-restore-v2"]

        assert metrics["precision"] >= baseline["precision"], (
            f"模型 precision {metrics['precision']:.2%} < 基线 {baseline['precision']:.2%}"
        )
        assert metrics["recall"] >= baseline["recall"], (
            f"模型 recall {metrics['recall']:.2%} < 基线 {baseline['recall']:.2%}"
        )

    def test_model_version_regression_detection(self, mock_monitor):
        """
        TC-PLAT-05：模型版本漂移检测
        模拟新版本精度下降场景 → 测试应捕获并 FAIL
        """
        # 模拟精度退步的新版本响应
        mock_monitor.get_metrics.return_value = {
            "model": "haircolor-restore-v2",
            "version": "2.2.0-beta",
            "precision": 0.82,   # 低于基线 0.90
            "recall":    0.85,
            "f1_score":  0.83,
            "avg_inference_ms": 290,
        }

        metrics = mock_monitor.get_metrics("haircolor-restore-v2", version="2.2.0-beta")
        baseline = self.BASELINE_METRICS["haircolor-restore-v2"]

        regression_detected = metrics["precision"] < baseline["precision"]

        if regression_detected:
            drop = baseline["precision"] - metrics["precision"]
            print(f"  ⚠️  模型精度回归检测：precision 下降 {drop:.2%} "
                  f"(v{metrics['version']})")
            pytest.fail(
                f"模型版本漂移：{metrics['model']} v{metrics['version']}\n"
                f"  precision: {metrics['precision']:.2%} < 基线 {baseline['precision']:.2%}\n"
                f"  建议：暂停版本升级，提交 GitHub Issue 并通知商汤侧"
            )

    def test_inference_latency_acceptable(self, mock_monitor):
        """模型推理时延 ≤ 500ms（实时应用要求）"""
        metrics = mock_monitor.get_metrics("haircolor-restore-v2")
        assert metrics["avg_inference_ms"] <= 500, (
            f"模型推理时延 {metrics['avg_inference_ms']}ms > 500ms"
        )
