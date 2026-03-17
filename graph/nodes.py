"""
LangGraph 节点定义。

LLM 策略（三层，with_fallbacks 自动切换）：
  1. 火山云 Ark     — 主力，日常对话 & 工具调用
  2. OpenRouter     — 备用，复杂推理 / 火山云失败时
  3. Claude API     — 仅供 Claude Code CLI，不在此使用

LangChain with_fallbacks 在以下情况自动降级：
  - HTTP 错误（5xx / 429 / 连接超时）
  - 模型返回空响应
"""
import os
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, ToolMessage
from graph.state import AgentState
from graph.tools import ALL_TOOLS

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# LLM 初始化
# --------------------------------------------------------------------------- #
def _make_volcengine() -> ChatOpenAI | None:
    key = os.getenv("VOLCENGINE_API_KEY", "")
    if not key:
        return None
    return ChatOpenAI(
        model=os.getenv("VOLCENGINE_MODEL", "doubao-pro-32k"),
        api_key=key,
        base_url=os.getenv("VOLCENGINE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        max_tokens=4096,
        timeout=30,
    )


def _make_openrouter() -> ChatOpenAI | None:
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        return None
    return ChatOpenAI(
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-5"),
        api_key=key,
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        max_tokens=4096,
        timeout=60,
        default_headers={
            "HTTP-Referer": "https://github.com/yanchuanjiu/ai-assistant",
            "X-Title": "AI Personal Assistant",
        },
    )


def _build_llm_chain():
    """返回绑定了 tools 的 LLM，按优先级构建 fallback 链。"""
    ark = _make_volcengine()
    router = _make_openrouter()

    candidates = [c for c in [ark, router] if c is not None]
    if not candidates:
        raise RuntimeError("没有可用的 LLM：请至少配置 VOLCENGINE_API_KEY 或 OPENROUTER_API_KEY")

    primary, *fallbacks = candidates
    llm = primary.with_fallbacks(fallbacks) if fallbacks else primary

    model_names = []
    if ark:
        model_names.append(f"火山云({os.getenv('VOLCENGINE_MODEL')})")
    if router:
        model_names.append(f"OpenRouter({os.getenv('OPENROUTER_MODEL')})")
    logger.info(f"LLM 链：{' → '.join(model_names)}")

    return llm.bind_tools(ALL_TOOLS)


llm_with_tools = _build_llm_chain()
tools_by_name = {t.name: t for t in ALL_TOOLS}


def _load_system_prompt() -> str:
    from datetime import date
    try:
        with open("prompts/system.md", encoding="utf-8") as f:
            return f.read().replace("{current_date}", date.today().isoformat())
    except FileNotFoundError:
        return "你是一个智能个人助理，帮助用户管理会议、项目和开发任务。"


SYSTEM_PROMPT = _load_system_prompt()


# --------------------------------------------------------------------------- #
# 节点：调用 LLM（ReAct loop）
# --------------------------------------------------------------------------- #
def agent_node(state: AgentState) -> dict:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


# --------------------------------------------------------------------------- #
# 节点：执行 Tool 调用
# --------------------------------------------------------------------------- #
def tools_node(state: AgentState) -> dict:
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
                logger.error(f"Tool {call['name']} 执行失败: {e}")
        tool_messages.append(
            ToolMessage(content=str(result), tool_call_id=call["id"])
        )
    return {"messages": tool_messages}


# --------------------------------------------------------------------------- #
# 节点：发送回复到来源平台
# --------------------------------------------------------------------------- #
def respond_node(state: AgentState) -> dict:
    last_msg = state["messages"][-1]
    content = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
    platform = state.get("platform", "feishu")
    chat_id = state.get("chat_id", "")

    try:
        if platform == "feishu":
            from integrations.feishu.bot import FeishuBot
            FeishuBot().send_text(chat_id=chat_id, text=content)
        elif platform == "dingtalk":
            from integrations.dingtalk.bot import DingTalkBot
            DingTalkBot().send_text(user_id=chat_id, text=content)
    except Exception as e:
        logger.error(f"发送消息失败 [{platform}]: {e}")

    return {}


# --------------------------------------------------------------------------- #
# 路由：是否继续 tool 调用
# --------------------------------------------------------------------------- #
def should_continue(state: AgentState) -> str:
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "respond"
