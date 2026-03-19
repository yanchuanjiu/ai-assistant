"""
LangGraph 节点。

LLM 链：火山云 Ark → OpenRouter（with_fallbacks 自动降级）
工具渐进式披露：每次 LLM 调用只传递当前上下文相关的工具，节省 token。
Claude API 不在此使用，仅供 Claude Code CLI。
"""
import os
import re
import json
import time
import logging
import threading
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, ToolMessage, AIMessage
from graph.state import AgentState
from graph.tools import ALL_TOOLS, CORE_TOOLS, TOOL_CATEGORIES, CATEGORY_KEYWORDS

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

# 工具名 → 分类映射（用于多轮连续性检测）
_TOOL_TO_CATEGORY: dict[str, str] = {
    t.name: cat
    for cat, tools in TOOL_CATEGORIES.items()
    for t in tools
}

# --------------------------------------------------------------------------- #
# LLM 链（不预先 bind_tools，动态绑定）
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


def _build_base_llm():
    """构建不绑定工具的基础 LLM 链（工具在每次调用时动态绑定）。"""
    ark = _make_llm(
        model=os.getenv("VOLCENGINE_MODEL", "doubao-pro-32k"),
        api_key=os.getenv("VOLCENGINE_API_KEY", ""),
        base_url=os.getenv("VOLCENGINE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        timeout=120,
    )
    router = _make_llm(
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-5"),
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        timeout=120,
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
    return llm


_llm_base = _build_base_llm()
tools_by_name = {t.name: t for t in ALL_TOOLS}

# 火山云 Ark 有时以文本形式返回工具调用，格式为：
# <|FunctionCallBegin|>[...] 或 <|FunctionCallBeginBegin|>[...]（双 Begin 变体）
# 兼容单/双 Begin 和 End 的所有变体
_FUNC_CALL_RE = re.compile(
    r"<\|FunctionCallBegin(?:Begin)?\|>(.*?)(?:<\|FunctionCallEnd(?:End)?\|>|$)",
    re.DOTALL,
)


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


def _build_system_prompt() -> str:
    """动态构建系统提示词，每次 agent_node 调用时加载最新 workspace 文件。"""
    from datetime import date

    parts = []

    # 基础 system prompt
    try:
        with open("prompts/system.md", encoding="utf-8") as f:
            parts.append(f.read().replace("{current_date}", date.today().isoformat()))
    except FileNotFoundError:
        parts.append("你是一个智能个人助理，帮助用户管理会议、项目和开发任务。")

    # 注入 workspace 文件（SOUL / USER / MEMORY），每次都读最新版本
    for fp, label in [
        ("workspace/SOUL.md", "SOUL"),
        ("workspace/USER.md", "USER"),
        ("workspace/MEMORY.md", "MEMORY"),
        ("workspace/SKILLS_PROJECT_MGMT.md", "SKILL_PROJECT_MGMT"),
    ]:
        try:
            with open(fp, encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                parts.append(f"\n---\n## Workspace: {label}\n{content}")
        except FileNotFoundError:
            pass

    return "\n".join(parts)

_LLM_LOG_PATH = "logs/llm.jsonl"


# --------------------------------------------------------------------------- #
# 渐进式工具选择
# --------------------------------------------------------------------------- #
def _select_tools(messages: list) -> list:
    """
    根据对话内容动态选择工具集，实现渐进式披露。

    规则：
    1. 始终包含 CORE_TOOLS（6个，~911 tokens）
    2. 扫描最近 5 条消息的文本关键词，加载匹配分类
    3. 扫描历史消息中已实际调用的工具，保持同类工具连续可用

    目标：从全量 ~6795 tokens 降至 ~1000-3000 tokens/call。
    """
    selected_categories: set[str] = set()

    # 1. 关键词触发：检查最近 5 条消息
    recent_text = ""
    for m in messages[-5:]:
        content = m.content if isinstance(m.content, str) else ""
        recent_text += content.lower() + " "

    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in recent_text for kw in keywords):
            selected_categories.add(cat)

    # 2. 连续性保持：历史中已调用过的工具，保持其分类可用
    for m in messages:
        for tc in getattr(m, "tool_calls", None) or []:
            cat = _TOOL_TO_CATEGORY.get(tc.get("name", ""))
            if cat:
                selected_categories.add(cat)

    # 组装最终工具列表
    tools = list(CORE_TOOLS)
    for cat in selected_categories:
        tools.extend(TOOL_CATEGORIES[cat])

    if selected_categories:
        logger.debug(f"[ToolSelect] 激活分类: {sorted(selected_categories)}，工具数: {len(tools)}")

    return tools


# --------------------------------------------------------------------------- #
# 日志
# --------------------------------------------------------------------------- #
def _log_llm_call(thread_id: str, messages: list, response, latency_ms: float, tools: list):
    """将每次 LLM 调用记录到 logs/llm.jsonl（JSONL 格式，供后续分析）。"""
    try:
        def _msg_repr(m) -> dict:
            content = m.content if isinstance(m.content, str) else str(m.content)
            return {"role": getattr(m, "type", "?"), "content": content[:800]}

        meta = getattr(response, "response_metadata", {}) or {}
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "thread": thread_id,
            "latency_ms": round(latency_ms),
            "model": meta.get("model_name") or meta.get("model") or "",
            "tools_count": len(tools),
            "tools_active": [t.name for t in tools],
            "usage": meta.get("token_usage") or meta.get("usage") or {},
            "input_msgs": [_msg_repr(m) for m in messages],
            "output": response.content[:1000] if isinstance(response.content, str) else str(response.content)[:1000],
            "tool_calls": [{"name": c["name"], "args": c.get("args", {})} for c in (getattr(response, "tool_calls", None) or [])],
        }
        os.makedirs("logs", exist_ok=True)
        with open(_LLM_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[LLM log] 写入失败: {e}")


# --------------------------------------------------------------------------- #
# 节点
# --------------------------------------------------------------------------- #
def agent_node(state: AgentState) -> dict:
    thread_id = f"{state.get('platform', '?')}:{state.get('chat_id', '?')}"
    messages = [SystemMessage(content=_build_system_prompt())] + state["messages"]

    # 动态选择工具（渐进式披露）
    tools = _select_tools(messages)
    llm = _llm_base.bind_tools(tools)

    t0 = time.monotonic()
    response = llm.invoke(messages)
    latency_ms = (time.monotonic() - t0) * 1000

    # 处理火山云文本格式工具调用
    if (
        isinstance(response.content, str)
        and "<|FunctionCall" in response.content
        and not getattr(response, "tool_calls", None)
    ):
        tool_calls = _extract_text_tool_calls(response.content)
        if tool_calls:
            logger.debug(f"解析文本格式工具调用: {[c['name'] for c in tool_calls]}")
            response = AIMessage(content="", tool_calls=tool_calls)
        else:
            # 解析失败：隐藏原始 JSON，避免泄漏给用户
            logger.warning(f"[FunctionCall] 解析失败，原始内容: {response.content[:300]}")
            response = AIMessage(content="（工具调用格式异常，请重试）")

    _log_llm_call(thread_id, messages, response, latency_ms, tools)

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
