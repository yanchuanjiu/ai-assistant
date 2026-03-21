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
from langchain_core.messages import SystemMessage, ToolMessage, AIMessage, HumanMessage
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
# 也可能缺少 Begin 标记，只有 End 标记：[...]<|FunctionCallEnd|>
# 兼容单/双 Begin/End 的所有变体，以及缺少 Begin 标记的情况
_FUNC_CALL_RE = re.compile(
    r"<\|FunctionCallBegin(?:Begin)?\|>(.*?)(?:<\|FunctionCallEnd(?:End)?\|>|$)",
    re.DOTALL,
)
# 缺少 Begin 标记的变体：JSON 数组直接跟 End 标记
_FUNC_CALL_NO_BEGIN_RE = re.compile(
    r"(\[.*?\])\s*<\|FunctionCallEnd(?:End)?\|>",
    re.DOTALL,
)


def _extract_text_tool_calls(content: str) -> list[dict] | None:
    """将火山云文本格式的工具调用解析为 LangChain tool_calls 列表。"""
    match = _FUNC_CALL_RE.search(content)
    if not match:
        # 尝试缺少 Begin 标记的变体
        match = _FUNC_CALL_NO_BEGIN_RE.search(content)
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


_PROJECT_MGMT_KEYWORDS = [
    "项目", "章程", "周报", "里程碑", "raid", "portfolio",
    "迭代", "sprint", "需求清单", "验收", "立项",
]
_BITABLE_KEYWORDS = [
    "多维表格", "bitable", "表格记录", "任务", "待办", "清单", "task",
]
_COMPLEX_MSG_KEYWORDS = [
    "项目", "会议", "纪要", "飞书", "钉钉", "知识库", "wiki",
    "分析", "整理", "写入", "迭代", "开发", "修复", "帮我",
    "搜索", "查找", "创建", "多维表格", "任务", "周报",
]


def _build_system_prompt(messages: list | None = None) -> str:
    """动态构建系统提示词，每次 agent_node 调用时加载最新 workspace 文件。

    - SOUL/USER/MEMORY_CORE：始终注入
    - MEMORY_HISTORY：简单消息时跳过（~1K tokens）
    - SKILLS_PROJECT_MGMT：仅在消息含项目管理关键词时注入（~0.4K tokens）
    - SKILLS_FEISHU_BITABLE：仅在消息含 Bitable/任务关键词时注入
    """
    from datetime import date

    parts = []

    # 基础 system prompt
    try:
        with open("prompts/system.md", encoding="utf-8") as f:
            parts.append(f.read().replace("{current_date}", date.today().isoformat()))
    except FileNotFoundError:
        parts.append("你是一个智能个人助理，帮助用户管理会议、项目和开发任务。")

    # 判断最新消息是否为简单消息（短且无复杂关键词）
    latest_content = ""
    if messages:
        last = messages[-1]
        latest_content = last.content if isinstance(last.content, str) else ""
    is_simple_msg = (
        len(latest_content) < 30
        and not any(kw in latest_content for kw in _COMPLEX_MSG_KEYWORDS)
    )

    # SOUL / USER / MEMORY_CORE 始终注入；MEMORY_HISTORY 简单消息时跳过
    for fp, label, skip_if_simple in [
        ("workspace/SOUL.md", "SOUL", False),
        ("workspace/USER.md", "USER", False),
        ("workspace/MEMORY_CORE.md", "MEMORY_CORE", False),
        ("workspace/MEMORY_HISTORY.md", "MEMORY_HISTORY", True),
    ]:
        if skip_if_simple and is_simple_msg:
            continue
        try:
            with open(fp, encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                parts.append(f"\n---\n## Workspace: {label}\n{content}")
        except FileNotFoundError:
            pass

    # 按需注入 Skill 文件（关键词匹配最近 3 条消息）
    recent_text = ""
    if messages:
        for m in messages[-3:]:
            recent_text += (m.content if isinstance(m.content, str) else "") + " "

    skill_files = [
        ("workspace/SKILLS_PROJECT_MGMT.md", "SKILL_PROJECT_MGMT", _PROJECT_MGMT_KEYWORDS),
        ("workspace/SKILLS_FEISHU_BITABLE.md", "SKILL_FEISHU_BITABLE", _BITABLE_KEYWORDS),
    ]
    for fp, label, keywords in skill_files:
        if any(kw in recent_text for kw in keywords):
            try:
                with open(fp, encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    parts.append(f"\n---\n## Workspace: {label}\n{content}")
            except FileNotFoundError:
                pass

    return "\n".join(parts)

_LLM_LOG_PATH = "logs/llm.jsonl"

# 历史工具结果内容限制：非当前轮的 ToolMessage 内容截断至此长度，防止旧任务结果污染新任务上下文
# 注：不再按轮次截断对话历史，完整历史均传给 LLM（SQLite 存储）
HISTORY_TOOL_CONTENT_LIMIT = 300
# 每轮最大工具调用迭代次数（防止死循环）
# 设为 10：复杂开发任务（自迭代 + 上下文分析）通常需要 6-8 次，保留 2 次余量
MAX_TOOL_ITERATIONS = 10

# 需要用户手动交互的信号词（出现则提前终止，避免无效重试）
_USER_INTERACTION_SIGNALS = [
    "EOF when reading a line",
    "PASTE_YOUR_CODE_HERE",
    "请在此处粘贴",
    "请访问以下URL获取code",
    "请粘贴获取到的code",
]


def _trim_tool_content(messages: list) -> list:
    """
    对历史轮次（非当前轮）的 ToolMessage 内容做截断，
    避免旧任务的工具结果（如飞书页面内容、钉钉文档内容）占用大量 token。

    不再按轮次截断对话历史——完整对话历史均传给 LLM，
    仅限制历史 ToolMessage 内容长度至 HISTORY_TOOL_CONTENT_LIMIT 字符。
    """
    human_indices = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    if len(human_indices) <= 1:
        return messages

    current_turn_start = human_indices[-1]
    result = []
    tool_truncated = 0
    for i, m in enumerate(messages):
        if i < current_turn_start and isinstance(m, ToolMessage):
            content = m.content if isinstance(m.content, str) else str(m.content)
            if len(content) > HISTORY_TOOL_CONTENT_LIMIT:
                # 只保留前 HISTORY_TOOL_CONTENT_LIMIT 字符作为人可读摘要，丢弃原始工具数据
                new_content = content[:HISTORY_TOOL_CONTENT_LIMIT] + f"…[工具结果已省略，原长{len(content)}字符]"
                result.append(ToolMessage(content=new_content, tool_call_id=m.tool_call_id))
                tool_truncated += 1
                continue
        result.append(m)

    if tool_truncated:
        logger.info(f"[ContextIsolation] 省略 {tool_truncated} 条历史 ToolMessage 内容（保留前{HISTORY_TOOL_CONTENT_LIMIT}字符），防止跨任务上下文污染")
    return result


# --------------------------------------------------------------------------- #
# 渐进式工具选择
# --------------------------------------------------------------------------- #
def _select_tools(messages: list) -> list:
    """
    根据对话内容动态选择工具集，实现渐进式披露。

    规则：
    1. 始终包含 CORE_TOOLS（7个）
    2. 短消息（<25字符）且无关键词 → 直接返回 CORE_TOOLS，跳过后续扫描
    3. 扫描最近 5 条消息的文本关键词，加载匹配分类
    4. 扫描最近 10 条消息中已实际调用的工具，保持同类工具连续可用（窗口限制避免长对话积累）

    目标：从全量 ~6795 tokens 降至 ~1000-3000 tokens/call。
    """
    selected_categories: set[str] = set()

    # 0. 短消息快速返回：无关键词的简短回复不注入额外工具
    latest_content = ""
    if messages:
        last = messages[-1]
        latest_content = last.content if isinstance(last.content, str) else ""
    if len(latest_content) < 25:
        if not any(
            any(kw in latest_content.lower() for kw in kws)
            for kws in CATEGORY_KEYWORDS.values()
        ):
            return list(CORE_TOOLS)

    # 1. 关键词触发：检查最近 5 条消息
    recent_text = ""
    for m in messages[-5:]:
        content = m.content if isinstance(m.content, str) else ""
        recent_text += content.lower() + " "

    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in recent_text for kw in keywords):
            selected_categories.add(cat)

    # 2. 连续性保持：只扫描最近 10 条消息（避免长对话中工具集无限积累）
    for m in messages[-10:]:
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
# 迭代保护
# --------------------------------------------------------------------------- #
def _count_tool_iterations(messages: list) -> int:
    """统计当前轮（最后一条 HumanMessage 之后）agent 已发起的工具调用次数。"""
    human_indices = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    start = human_indices[-1] + 1 if human_indices else 0
    return sum(
        1 for m in messages[start:]
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
    )


def _check_user_interaction_needed(messages: list) -> str | None:
    """
    检查最近的工具结果是否包含"需要用户手动操作"的信号。
    返回 None 表示正常；返回字符串表示需要终止并告知用户的原因描述。
    """
    # 只检查当前轮（最后一条 HumanMessage 之后）的 ToolMessage
    human_indices = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    start = human_indices[-1] + 1 if human_indices else 0
    current_turn_msgs = messages[start:]

    recent_tool_msgs = [m for m in current_turn_msgs if isinstance(m, ToolMessage)][-3:]

    if not recent_tool_msgs:
        return None

    last_content = recent_tool_msgs[-1].content if isinstance(recent_tool_msgs[-1].content, str) else ""

    # 检测交互式操作信号
    for signal in _USER_INTERACTION_SIGNALS:
        if signal in last_content:
            return f"需要用户手动操作（检测到：{signal}）"

    # 检测重复失败：最近 3 条工具结果高度相似（内容前 100 字符完全相同）
    if len(recent_tool_msgs) >= 3:
        previews = [
            (m.content if isinstance(m.content, str) else "")[:100]
            for m in recent_tool_msgs
        ]
        if previews[0] == previews[1] == previews[2]:
            return "工具连续返回相同结果（可能陷入循环）"

    return None


# --------------------------------------------------------------------------- #
# 节点
# --------------------------------------------------------------------------- #
def agent_node(state: AgentState) -> dict:
    thread_id = f"{state.get('platform', '?')}:{state.get('chat_id', '?')}"

    # ── 迭代保护：超限或检测到需要用户交互，直接终止 ──────────────────────────
    iterations = _count_tool_iterations(state["messages"])
    if iterations >= MAX_TOOL_ITERATIONS:
        logger.warning(f"[IterGuard] 达到最大迭代次数 {MAX_TOOL_ITERATIONS}，强制终止 thread={thread_id}")
        return {"messages": [AIMessage(content=(
            f"⚠️ 已尝试 {iterations} 次工具调用，超过上限（{MAX_TOOL_ITERATIONS} 次），自动终止。\n"
            "可能遇到了无法自动解决的问题，请告诉我您希望如何继续，或者提供更多信息。"
        ))]}

    interaction_reason = _check_user_interaction_needed(state["messages"])
    if interaction_reason:
        logger.warning(f"[IterGuard] 检测到需要用户交互，终止自动重试 thread={thread_id} reason={interaction_reason}")
        return {"messages": [AIMessage(content=(
            f"⚠️ 当前操作需要您手动完成（{interaction_reason}），无法继续自动执行。\n"
            "请按照之前的提示完成手动步骤后，再告诉我结果，我会继续协助。"
        ))]}
    # ─────────────────────────────────────────────────────────────────────────

    # 截断历史 ToolMessage 内容：保留完整对话历史，仅压缩历史轮工具结果体积
    trimmed = _trim_tool_content(state["messages"])
    messages = [SystemMessage(content=_build_system_prompt(trimmed))] + trimmed

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
    from graph.parallel import run_tools_parallel

    thread_id = f"{state['platform']}:{state['chat_id']}"
    send_fn = reply_fn_registry.get(thread_id)
    # 为当前线程设置工具上下文（单工具 / 串行路径使用）
    set_tool_ctx(thread_id, send_fn)

    calls = state["messages"][-1].tool_calls
    tool_messages = run_tools_parallel(calls, thread_id, send_fn, tools_by_name)
    return {"messages": tool_messages}


def should_continue(state: AgentState) -> str:
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "end"
