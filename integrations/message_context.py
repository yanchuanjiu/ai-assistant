"""统一消息上下文结构，供各平台 Bot 共享。"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MessageContext:
    """平台无关的消息上下文，由各 bot 的 parse_message() 构建。"""
    text: str
    user_id: str
    chat_id: str
    thread_id: str
    platform: str           # "feishu" | "dingtalk"
    message_id: str = ""
    topic_name: str = ""    # 提取出的话题名（若有）
    raw: Any = None         # 原始平台消息对象
    extra: dict = field(default_factory=dict)  # 平台特定附加字段
