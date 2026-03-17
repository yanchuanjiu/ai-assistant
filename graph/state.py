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
    chat_id: str

    # 意图分类结果
    intent: Optional[str]   # meeting | knowledge | dev | general | sync

    # 技能执行结果（传递给 respond node）
    skill_result: Optional[str]

    # 错误信息
    error: Optional[str]
