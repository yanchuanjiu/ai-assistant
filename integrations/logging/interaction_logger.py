"""
交互日志记录器。

记录每次 user ↔ agent 的完整对话到 logs/interactions.jsonl，
供自我改进系统分析用户行为模式、工具使用情况和纠正信号。
"""
import json
import os
import time
import logging

logger = logging.getLogger(__name__)

INTERACTION_LOG = "logs/interactions.jsonl"

# 用户纠正信号关键词（中英文）
_CORRECTION_KEYWORDS = [
    "不对", "错了", "不是", "纠正", "重新", "不要这样", "搞错了",
    "wrong", "incorrect", "not right", "redo", "that's not",
]

# 跳过记录的内部平台
_SKIP_PLATFORMS = {"heartbeat", "scheduler"}


def log_interaction(
    platform: str,
    user_id: str,
    chat_id: str,
    user_message: str,
    agent_response: str,
    tools_used: list,
    latency_ms: float = 0,
):
    """记录一次完整的 user ↔ agent 交互。"""
    if platform in _SKIP_PLATFORMS:
        return

    try:
        msg_lower = user_message.lower()
        has_correction = any(kw in msg_lower for kw in _CORRECTION_KEYWORDS)

        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "platform": platform,
            "user_id": user_id,
            "chat_id": chat_id,
            "thread_id": f"{platform}:{chat_id}",
            "user_message": user_message[:500],
            "agent_response": agent_response[:500],
            "tools_used": tools_used,
            "latency_ms": round(latency_ms),
            "has_correction": has_correction,
        }
        os.makedirs("logs", exist_ok=True)
        with open(INTERACTION_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[InteractionLog] 写入失败: {e}")
