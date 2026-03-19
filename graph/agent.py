"""
LangGraph 主图：ReAct agent with SQLite checkpointing。

流程：START → agent → [tool_calls?] → tools → agent → ... → END
消息发送由各平台 bot 模块负责，图本身只负责推理和工具调用。
"""
import os
import sqlite3
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from graph.state import AgentState
from graph.nodes import agent_node, tools_node, should_continue

os.makedirs("data", exist_ok=True)

# 直接用 sqlite3 连接初始化，避免 from_conn_string 返回 context manager
_conn = sqlite3.connect("data/memory.db", check_same_thread=False)
checkpointer = SqliteSaver(_conn)


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)

    g.set_entry_point("agent")

    g.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end": END},
    )
    g.add_edge("tools", "agent")

    return g.compile(checkpointer=checkpointer)


graph = build_graph()


def invoke(message: str, platform: str, user_id: str, chat_id: str) -> str:
    """
    外部调用入口：传入用户消息，返回 AI 回复文本。
    消息发送由调用方（bot handler）负责。
    """
    import time
    from integrations.logging.interaction_logger import log_interaction

    config = {"configurable": {"thread_id": f"{platform}:{chat_id}"}}
    state = {
        "messages": [HumanMessage(content=message)],
        "platform": platform,
        "user_id": user_id,
        "chat_id": chat_id,
        "intent": None,
        "skill_result": None,
        "error": None,
    }

    t0 = time.monotonic()
    result = graph.invoke(state, config=config)
    latency_ms = (time.monotonic() - t0) * 1000

    last = result["messages"][-1]
    response_text = last.content if isinstance(last.content, str) else str(last.content)

    # 收集本次调用的工具列表（去重保序）
    tools_used = []
    for msg in result["messages"]:
        for tc in getattr(msg, "tool_calls", None) or []:
            name = tc.get("name", "")
            if name and name not in tools_used:
                tools_used.append(name)

    log_interaction(
        platform=platform,
        user_id=user_id,
        chat_id=chat_id,
        user_message=message,
        agent_response=response_text,
        tools_used=tools_used,
        latency_ms=latency_ms,
    )

    return response_text
