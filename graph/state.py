from typing import Annotated, Optional
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # 消息历史，LangGraph 自动 append
    messages: Annotated[list[BaseMessage], add_messages]

    # 来源平台：feishu | dingtalk
    platform: str

    # 发送者 & 会话信息
    user_id: str
    chat_id: str  # 真实 IM chat_id（用于 API 调用）

    # 话题专属 thread_id（覆盖默认的 platform:chat_id）
    # 格式：{platform}:{chat_id}#topic#{safe_name}（有话题时）或 {platform}:{chat_id}（无话题）
    thread_id: Optional[str]

    # 意图分类结果
    intent: Optional[str]   # meeting | knowledge | dev | general | sync

    # 技能执行结果（传递给 respond node）
    skill_result: Optional[str]

    # 错误信息
    error: Optional[str]
