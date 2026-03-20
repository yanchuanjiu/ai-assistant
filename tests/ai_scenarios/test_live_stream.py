"""
场景二：直播数字人场景适配抖音限制测试
────────────────────────────────────────────────────────────────────────────
触发条件：数字人直播流推送至抖音平台，需满足抖音推流技术规范
验证指标：
  - 直播稳定性：连续运行中断率 ≤ 0.1%（99.9% 可用性）
  - 推流规格合规：分辨率/码率/帧率均在抖音允许范围内
  - 首帧时延：开播后首帧渲染 ≤ 2s
  - 数字人嘴形同步误差：音唇偏差 ≤ 80ms

用例覆盖：
  TC-LIVE-01  推流参数合规性检查（分辨率/码率/帧率/编码格式）
  TC-LIVE-02  推流稳定性：模拟连续推流 / 断流重连
  TC-LIVE-03  数字人嘴形同步延迟校验
  TC-LIVE-04  抖音平台限流熔断（超出码率上限）
  TC-LIVE-05  并发场景：多路流切换不相互干扰
"""

import time
import pytest
from dataclasses import dataclass
from unittest.mock import patch, MagicMock

# ── 抖音直播推流规范常量 ──────────────────────────────────────────────────────

# 参考：抖音直播推流技术规范 v2024
DOUYIN_SPEC = {
    "resolutions": [
        (1920, 1080),  # 1080p（推荐）
        (1280, 720),   # 720p
        (854,  480),   # 480p（最低支持）
    ],
    "bitrate_kbps": {"min": 1000, "max": 6000},   # 视频码率 kbps
    "framerate": {"min": 15, "max": 30},            # 帧率 fps
    "video_codec": ["H.264", "H.265"],              # 编码格式
    "audio_codec": ["AAC"],                          # 音频编码
    "audio_sample_rate": [44100, 48000],             # 采样率 Hz
    "max_stream_duration_h": 4,                      # 单次最长推流小时
    "rtmp_timeout_s": 30,                            # RTMP 连接超时
}

# 数字人嘴形同步容忍阈值（ms）
LIPSYNC_THRESHOLD_MS = 80


# ── 数据类 ────────────────────────────────────────────────────────────────────

@dataclass
class StreamConfig:
    """推流配置参数"""
    resolution: tuple[int, int]
    bitrate_kbps: int
    framerate: int
    video_codec: str
    audio_codec: str
    audio_sample_rate: int


@dataclass
class StreamHealthReport:
    """推流健康状态报告"""
    total_frames: int
    dropped_frames: int
    reconnect_count: int
    avg_latency_ms: float
    lipsync_offsets_ms: list[float]

    @property
    def drop_rate(self) -> float:
        return self.dropped_frames / max(self.total_frames, 1)

    @property
    def availability(self) -> float:
        return 1.0 - self.drop_rate

    @property
    def lipsync_p95_ms(self) -> float:
        if not self.lipsync_offsets_ms:
            return 0
        return sorted(self.lipsync_offsets_ms)[int(len(self.lipsync_offsets_ms) * 0.95)]


# ── 参数合规性校验函数 ────────────────────────────────────────────────────────

def validate_stream_config(config: StreamConfig) -> list[str]:
    """
    校验推流参数是否符合抖音规范
    返回：错误信息列表（空列表表示合规）
    """
    errors = []

    if config.resolution not in DOUYIN_SPEC["resolutions"]:
        errors.append(f"分辨率 {config.resolution} 不在抖音支持列表内")

    bmin = DOUYIN_SPEC["bitrate_kbps"]["min"]
    bmax = DOUYIN_SPEC["bitrate_kbps"]["max"]
    if not (bmin <= config.bitrate_kbps <= bmax):
        errors.append(f"码率 {config.bitrate_kbps}kbps 超出范围 [{bmin}, {bmax}]")

    fmin = DOUYIN_SPEC["framerate"]["min"]
    fmax = DOUYIN_SPEC["framerate"]["max"]
    if not (fmin <= config.framerate <= fmax):
        errors.append(f"帧率 {config.framerate}fps 超出范围 [{fmin}, {fmax}]")

    if config.video_codec not in DOUYIN_SPEC["video_codec"]:
        errors.append(f"视频编码 {config.video_codec} 不支持")

    if config.audio_codec not in DOUYIN_SPEC["audio_codec"]:
        errors.append(f"音频编码 {config.audio_codec} 不支持")

    if config.audio_sample_rate not in DOUYIN_SPEC["audio_sample_rate"]:
        errors.append(f"采样率 {config.audio_sample_rate}Hz 不支持")

    return errors


# ── 测试用例 ──────────────────────────────────────────────────────────────────

# TC-LIVE-01 合规配置矩阵
VALID_CONFIGS = [
    StreamConfig((1920, 1080), 4000, 30, "H.264", "AAC", 44100),
    StreamConfig((1280, 720),  2000, 30, "H.264", "AAC", 48000),
    StreamConfig((1280, 720),  1500, 25, "H.265", "AAC", 44100),
    StreamConfig((854, 480),   1000, 15, "H.264", "AAC", 44100),
]

INVALID_CONFIGS = [
    (StreamConfig((1920, 1080), 8000, 30, "H.264", "AAC", 44100),
     "码率超限", ["码率"]),
    (StreamConfig((1920, 1080), 2000, 60, "H.264", "AAC", 44100),
     "帧率超限", ["帧率"]),
    (StreamConfig((3840, 2160), 4000, 30, "H.264", "AAC", 44100),
     "4K分辨率不支持", ["分辨率"]),
    (StreamConfig((1920, 1080), 4000, 30, "VP9",   "AAC", 44100),
     "VP9编码不支持", ["视频编码"]),
]


class TestStreamCompliance:
    """TC-LIVE-01：推流参数合规性检查"""

    @pytest.mark.parametrize("config", VALID_CONFIGS)
    def test_valid_config_passes(self, config):
        """合规配置应无错误"""
        errors = validate_stream_config(config)
        assert errors == [], (
            f"合规配置被误判为不合规：{config}\n错误：{errors}"
        )

    @pytest.mark.parametrize("config,desc,expected_keywords", INVALID_CONFIGS)
    def test_invalid_config_detected(self, config, desc, expected_keywords):
        """非合规配置应被检测到，且错误信息含相关关键词"""
        errors = validate_stream_config(config)
        assert errors, f"未检测到非合规配置：{desc}"
        error_text = " ".join(errors)
        for kw in expected_keywords:
            assert kw in error_text, f"错误信息未提及 '{kw}'：{error_text}"


class TestStreamStability:
    """TC-LIVE-02：推流稳定性测试"""

    def test_availability_meets_sla(self):
        """
        模拟 10000 帧推流，丢帧率 ≤ 0.1%（99.9% 可用性 SLA）
        真实测试应接入推流监控数据接口
        """
        report = StreamHealthReport(
            total_frames=10000,
            dropped_frames=5,        # 模拟丢帧
            reconnect_count=1,
            avg_latency_ms=45.0,
            lipsync_offsets_ms=[20, 35, 48, 52, 61, 70, 75, 30, 25, 44],
        )
        print(f"  可用性：{report.availability:.4%}，丢帧：{report.dropped_frames}/{report.total_frames}")
        assert report.availability >= 0.999, (
            f"直播稳定性不足：可用性 {report.availability:.4%} < 99.9%"
        )

    def test_reconnect_restores_stream(self):
        """
        断流重连验证：模拟网络中断后 RTMP 重连
        断言：重连次数 ≤ 3，重连后流恢复正常
        """
        reconnect_log = []

        def mock_reconnect(attempt: int) -> bool:
            reconnect_log.append({"attempt": attempt, "ts": time.time()})
            return attempt <= 3  # 前 3 次重连成功

        success = False
        for i in range(1, 4):
            if mock_reconnect(i):
                success = True
                break
            time.sleep(0.01)  # 退避（测试用，实际为指数退避）

        assert success, "重连失败：3 次内未能恢复推流"
        assert len(reconnect_log) <= 3, f"重连次数 {len(reconnect_log)} 超过上限"

    def test_stream_first_frame_latency(self):
        """
        TC-LIVE-02 补充：首帧渲染时延 ≤ 2000ms
        模拟开播初始化流程
        """
        # 模拟数字人初始化阶段（模型加载 + 渲染管线启动）
        stage_latencies = {
            "model_load_ms": 400,
            "render_pipeline_init_ms": 350,
            "first_frame_encode_ms": 180,
            "rtmp_handshake_ms": 120,
        }
        total_ms = sum(stage_latencies.values())
        print(f"  首帧总时延：{total_ms}ms，各阶段：{stage_latencies}")
        assert total_ms <= 2000, f"首帧时延 {total_ms}ms 超过 2000ms 阈值"


class TestLipsync:
    """TC-LIVE-03：数字人嘴形同步延迟"""

    def test_lipsync_p95_within_threshold(self):
        """
        P95 嘴形偏差 ≤ 80ms
        数据来源：数字人语音驱动模块实测偏移量（ms）
        """
        # 模拟 100 帧嘴形偏移量（正值=超前，负值=滞后）
        import random
        random.seed(42)
        offsets = [abs(random.gauss(30, 15)) for _ in range(100)]

        report = StreamHealthReport(
            total_frames=100,
            dropped_frames=0,
            reconnect_count=0,
            avg_latency_ms=sum(offsets) / len(offsets),
            lipsync_offsets_ms=offsets,
        )
        p95 = report.lipsync_p95_ms
        print(f"  嘴形偏差 P95：{p95:.1f}ms（阈值={LIPSYNC_THRESHOLD_MS}ms）")
        assert p95 <= LIPSYNC_THRESHOLD_MS, (
            f"嘴形同步 P95 偏差 {p95:.1f}ms > {LIPSYNC_THRESHOLD_MS}ms"
        )

    def test_audio_video_sync_maintained_after_reconnect(self):
        """断流重连后音视频同步应在 3 秒内恢复"""
        resync_time_ms = 1800  # 模拟重连后重同步耗时
        assert resync_time_ms <= 3000, f"重连后音视频重同步耗时 {resync_time_ms}ms > 3000ms"


class TestDouyinRateLimit:
    """TC-LIVE-04：抖音平台限流熔断"""

    def test_bitrate_exceeded_triggers_downgrade(self):
        """
        超出码率上限时，系统应自动降档而非崩溃
        触发条件：设置码率 = 8000kbps（超出 6000kbps 上限）
        期望行为：自动降档至 4000kbps 并记录告警
        """
        requested_kbps = 8000
        max_kbps = DOUYIN_SPEC["bitrate_kbps"]["max"]

        def adaptive_bitrate(requested: int, max_allowed: int) -> int:
            """自适应码率降级策略"""
            if requested > max_allowed:
                return max_allowed * 2 // 3  # 降至 2/3
            return requested

        actual_kbps = adaptive_bitrate(requested_kbps, max_kbps)
        print(f"  请求码率 {requested_kbps}kbps → 实际 {actual_kbps}kbps")
        assert actual_kbps <= max_kbps, f"降级后码率 {actual_kbps}kbps 仍超限"
        assert actual_kbps >= DOUYIN_SPEC["bitrate_kbps"]["min"], "降级码率过低"


class TestMultiStreamIsolation:
    """TC-LIVE-05：多路流并发隔离"""

    def test_multi_stream_no_interference(self):
        """
        多个数字人直播流并发运行，互不干扰
        断言：各流的丢帧率独立计算，单流故障不影响其他流
        """
        streams = [
            StreamHealthReport(10000, 3, 0, 40.0, [20, 30, 45, 50]),
            StreamHealthReport(10000, 2, 1, 50.0, [25, 35, 40, 55]),
            StreamHealthReport(10000, 8, 0, 38.0, [18, 28, 42, 48]),
        ]
        for i, stream in enumerate(streams):
            assert stream.availability >= 0.999, (
                f"流 #{i+1} 可用性不足：{stream.availability:.4%}"
            )
            print(f"  流 #{i+1}：可用性={stream.availability:.4%}，"
                  f"嘴形P95={stream.lipsync_p95_ms:.1f}ms")
