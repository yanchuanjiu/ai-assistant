"""
Agent 回复错误追踪器。

当 Agent 回复中出现错误/异常关键词时，自动记录并触发 Claude Code 修复。
同一错误模式超过 MAX_AUTO_FIX_ATTEMPTS 次后，停止自动修复并通知用户 + 创建 GitHub Issue。
"""
import re
import json
import logging
import os
import time
import subprocess
import threading

logger = logging.getLogger(__name__)

# Agent 回复中触发自动修复的关键词
ERROR_RESPONSE_KEYWORDS = [
    # 中文
    "错误", "异常", "失败", "出错", "报错", "无法", "不支持",
    "找不到", "超时", "崩溃", "连接失败", "请求失败", "调用失败",
    # 英文
    "Exception", "Traceback", "Error:", "failed", "timeout",
    "not found", "unauthorized", "forbidden", "invalid",
]

# 不触发自动修复的误报词（这些词出现在正常回复中）
_FALSE_POSITIVE_PATTERNS = [
    "没有错误", "无错误", "不是错误", "修复了错误", "解决了错误",
    "no error", "fixed the error", "without error",
]

# 分析/描述性上下文前缀词 — 这些词之后出现的"错误/失败"是描述性的，不是实际错误
# e.g. "分析错误率", "识别错误模式", "统计失败率", "检测错误关键词"
_ANALYTICAL_CONTEXT_PREFIXES = [
    "分析", "统计", "识别", "检测", "记录", "追踪", "监控", "评估", "汇总",
    "纠正率", "错误率", "失败率", "成功率", "占比", "次数",
    "错误模式", "错误关键词", "失败案例", "错误案例",
    "自动修复", "自我改进", "自我优化", "改进评估", "优化评估",
    # 能力/功能描述性上下文 — "无法并行"/"无法同时"等是设计说明，不是实际错误
    "并发", "并行", "串行", "能力", "说明", "描述", "限制", "不支持同时",
    "依赖", "顺序执行", "处理模式", "单会话", "功能",
]

# 响应长度下限：超过此长度且包含分析性上下文词时，认为是描述性回复而非真实错误
_MIN_DESCRIPTIVE_RESPONSE_LEN = 300

MAX_AUTO_FIX_ATTEMPTS = 3  # 同一错误模式的最大自动修复次数
_TRACKER_FILE = "data/auto_fix_tracker.json"
_LOCK = threading.Lock()


def _load_tracker() -> dict:
    try:
        if os.path.exists(_TRACKER_FILE):
            with open(_TRACKER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[ErrorTracker] 读取追踪文件失败: {e}")
    return {"patterns": {}}


def _save_tracker(data: dict):
    try:
        os.makedirs(os.path.dirname(_TRACKER_FILE), exist_ok=True)
        with open(_TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[ErrorTracker] 写入追踪文件失败: {e}")


def _is_analytical_context(response: str, kw_idx: int) -> bool:
    """
    检查关键词出现的上下文是否是分析/描述性的（而非实际错误）。

    规则：
    1. 关键词前后100字符内出现分析性前缀词（"统计"/"分析"/"识别"等）
    2. 或回复整体含多个分析性词汇（>=2个），且回复长度超过阈值（描述性文本）
    """
    # 检查关键词附近（前后100字符）是否有分析性前缀
    nearby = response[max(0, kw_idx - 100): kw_idx + 100]
    for prefix in _ANALYTICAL_CONTEXT_PREFIXES:
        if prefix in nearby:
            return True

    # 次级检查：整体回复含多个分析性词汇 + 足够长
    if len(response) >= _MIN_DESCRIPTIVE_RESPONSE_LEN:
        hit_count = sum(1 for prefix in _ANALYTICAL_CONTEXT_PREFIXES if prefix in response)
        if hit_count >= 2:
            return True

    return False


def detect_error_in_response(response: str) -> str | None:
    """
    检测回复中是否有错误关键词。

    返回归一化的错误模式字符串，如果是正常回复则返回 None。
    """
    resp_lower = response.lower()

    # 检查是否是误报（"没有错误" 等）
    for fp in _FALSE_POSITIVE_PATTERNS:
        if fp.lower() in resp_lower:
            return None

    for kw in ERROR_RESPONSE_KEYWORDS:
        if kw.lower() in resp_lower:
            idx = resp_lower.find(kw.lower())

            # 检查是否是分析/描述性上下文（误报过滤）
            if _is_analytical_context(response, idx):
                logger.debug(f"[ErrorTracker] 误报过滤：关键词 '{kw}' 出现在分析性上下文中，跳过")
                continue

            # 提取关键词周围上下文（前20后60字符）
            context = response[max(0, idx - 20): idx + 60].strip()
            # 归一化：去掉数字、时间戳、具体 token 等变量
            normalized = re.sub(r'\d{4}-\d{2}-\d{2}T[\d:]+', 'TIMESTAMP', context)
            normalized = re.sub(r'\b[0-9a-f]{8,}\b', 'HASH', normalized)
            normalized = re.sub(r'\d+', 'N', normalized)
            normalized = re.sub(r'\s+', ' ', normalized).strip()
            # 截断到80字符作为key
            return normalized[:80]

    return None


def get_fix_status(pattern: str) -> dict:
    """
    获取某个错误模式的修复状态。

    返回 dict：{count, last_ts, github_issue, resolved}
    """
    with _LOCK:
        data = _load_tracker()
        return data["patterns"].get(pattern, {
            "count": 0, "last_ts": None, "github_issue": None, "resolved": False
        })


def record_error(pattern: str, response_snippet: str, platform: str, chat_id: str) -> int:
    """
    记录一次错误出现，返回累计出现次数（含本次）。
    """
    with _LOCK:
        data = _load_tracker()
        if pattern not in data["patterns"]:
            data["patterns"][pattern] = {
                "count": 0,
                "first_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "last_ts": None,
                "snippet": response_snippet[:200],
                "platform": platform,
                "chat_id": chat_id,
                "github_issue": None,
                "resolved": False,
            }
        entry = data["patterns"][pattern]
        entry["count"] += 1
        entry["last_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry["snippet"] = response_snippet[:200]  # 更新为最新片段
        _save_tracker(data)
        return entry["count"]


def record_github_issue(pattern: str, issue_url: str):
    """记录 GitHub issue URL 到追踪文件。"""
    with _LOCK:
        data = _load_tracker()
        if pattern in data["patterns"]:
            data["patterns"][pattern]["github_issue"] = issue_url
        _save_tracker(data)


def create_github_issue(pattern: str, count: int, snippet: str) -> str | None:
    """
    创建 GitHub issue 记录反复出现的错误，返回 issue URL 或 None。
    """
    title = f"[自动报告] 反复出现的 Agent 错误（{count} 次未修复）"
    body = f"""## 问题描述

Agent 回复中持续出现错误关键词，自动修复已达上限（{MAX_AUTO_FIX_ATTEMPTS} 次）仍未解决。

**错误模式**:
```
{pattern}
```

**最新错误片段**:
```
{snippet}
```

**出现次数**: {count}

## 复现步骤

请查看 `logs/interactions.jsonl` 中包含以下模式的记录：
```
{pattern[:60]}
```

## 建议排查

1. 查看 `logs/app.log` 和 `logs/crash.log`
2. 运行回归测试：`python tests/regression/run_all.py`
3. 手动触发自我改进：在 IM 发送「自我改进」

---
*由 AI 助理自动创建 at {time.strftime("%Y-%m-%d %H:%M:%S")}*
"""
    try:
        result = subprocess.run(
            ["gh", "issue", "create",
             "--title", title,
             "--body", body,
             "--label", "bug"],
            capture_output=True, text=True,
            cwd="/root/ai-assistant",
            timeout=30,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            logger.info(f"[ErrorTracker] GitHub issue 已创建: {url}")
            return url
        else:
            logger.warning(f"[ErrorTracker] gh issue 创建失败: {result.stderr}")
    except FileNotFoundError:
        logger.warning("[ErrorTracker] gh CLI 未安装，跳过 issue 创建")
    except Exception as e:
        logger.warning(f"[ErrorTracker] 创建 GitHub issue 时出错: {e}")
    return None
