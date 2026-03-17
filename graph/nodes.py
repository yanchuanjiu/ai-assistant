"""
LangGraph 节点。

LLM 链：火山云 Ark → OpenRouter（with_fallbacks 自动降级）
Claude API 不在此使用，仅供 Claude Code CLI。
"""
import os
import re
import json
import logging
import threading
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, ToolMessage, AIMessage
from graph.state import AgentState
from graph.tools import ALL_TOOLS

# ------------------------------------------------------------------ #
# Tool 执行上下文（线程局部变量，供工具读取当前会话信息）
# ------------------------------------------------------------------ #
_tool_ctx = threading.local()


def set_tool_ctx(thread_id: str, send_fn):
    _tool_ctx.thread_id = thread_id
    _tool_ctx.send_fn = send_fn


def get_tool_ctx() -> tuple[str | None, object]:
    """返回 (thread_id, send_fn)。"""
    return getattr(_tool_ctx, "thread_id", None), getattr(_tool_ctx, "send_fn", None)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# LLM 链
# --------------------------------------------------------------------------- #
def _make_llm(model: str, api_key: str, base_url: str, timeout: int) -> ChatOpenAI | None:
    if not api_key:
        return None
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=4096,
        timeout=timeout,
    )


def _build_llm_chain():
    ark = _make_llm(
        model=os.getenv("VOLCENGINE_MODEL", "doubao-pro-32k"),
        api_key=os.getenv("VOLCENGINE_API_KEY", ""),
        base_url=os.getenv("VOLCENGINE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        timeout=30,
    )
    router = _make_llm(
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-5"),
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        timeout=60,
    )
    candidates = [c for c in [ark, router] if c is not None]
    if not candidates:
        raise RuntimeError("没有可用 LLM：请配置 VOLCENGINE_API_KEY 或 OPENROUTER_API_KEY")

    primary, *fallbacks = candidates
    llm = primary.with_fallbacks(fallbacks) if fallbacks else primary

    names = []
    if ark:
        names.append(f"火山云({os.getenv('VOLCENGINE_MODEL')})")
    if router:
        names.append(f"OpenRouter({os.getenv('OPENROUTER_MODEL')})")
    logger.info(f"LLM 链：{' → '.join(names)}")

    return llm.bind_tools(ALL_TOOLS)


llm_with_tools = _build_llm_chain()
tools_by_name = {t.name: t for t in ALL_TOOLS}

# 火山云 Ark 有时以文本形式返回工具调用，格式为：
# <|FunctionCallBeginBegin|>[{"name":...,"parameters":...,"id":...}]
_FUNC_CALL_RE = re.compile(r"<\|FunctionCallBeginBegin\|>(.*?)(?:<\|FunctionCallEndEnd\|>|$)", re.DOTALL)


def _extract_text_tool_calls(content: str) -> list[dict] | None:
    """将火山云文本格式的工具调用解析为 LangChain tool_calls 列表。"""
    match = _FUNC_CALL_RE.search(content)
    if not match:
        return None
    try:
        raw = json.loads(match.group(1).strip())
        return [
            {
                "id": f"call_{c.get('id', i)}",
                "name": c["name"],
                "args": c.get("parameters", c.get("arguments", {})),
                "type": "tool_call",
            }
            for i, c in enumerate(raw)
        ]
    except Exception:
        return None


def _load_system_prompt() -> str:
    from datetime import date
    try:
        with open("prompts/system.md", encoding="utf-8") as f:
            return f.read().replace("{current_date}", date.today().isoformat())
    except FileNotFoundError:
        return "你是一个智能个人助理，帮助用户管理会议、项目和开发任务。"


SYSTEM_PROMPT = _load_system_prompt()


# --------------------------------------------------------------------------- #
# 节点
# --------------------------------------------------------------------------- #
def agent_node(state: AgentState) -> dict:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm_with_tools.invoke(messages)

    # 处理火山云文本格式工具调用
    if (
        isinstance(response.content, str)
        and "<|FunctionCallBeginBegin|>" in response.content
        and not getattr(response, "tool_calls", None)
    ):
        tool_calls = _extract_text_tool_calls(response.content)
        if tool_calls:
            logger.debug(f"解析文本格式工具调用: {[c['name'] for c in tool_calls]}")
            response = AIMessage(content="", tool_calls=tool_calls)

    return {"messages": [response]}


def tools_node(state: AgentState) -> dict:
    from integrations.claude_code.session import reply_fn_registry

    # 注入当前会话上下文，供 trigger_self_iteration 等工具使用
    thread_id = f"{state['platform']}:{state['chat_id']}"
    send_fn = reply_fn_registry.get(thread_id)
    set_tool_ctx(thread_id, send_fn)

    last_msg = state["messages"][-1]
    tool_messages = []
    for call in last_msg.tool_calls:
        tool = tools_by_name.get(call["name"])
        if tool is None:
            result = f"未找到工具：{call['name']}"
        else:
            try:
                result = tool.invoke(call["args"])
            except Exception as e:
                result = f"工具执行出错：{e}"
                logger.error(f"Tool {call['name']} 失败: {e}")
        tool_messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
    return {"messages": tool_messages}


def should_continue(state: AgentState) -> str:
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "end"
