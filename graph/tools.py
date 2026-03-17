"""
工具函数，注册为 LangGraph tools，供 agent nodes 调用。
"""
import os
import re
import subprocess
import logging
import textwrap
import urllib.parse
import urllib.request
import html
from langchain_core.tools import tool
from integrations.feishu.knowledge import FeishuKnowledge
from integrations.dingtalk.docs import DingTalkDocs
from sync.context_sync import ContextSync

logger = logging.getLogger(__name__)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------- #
# 飞书知识库 — 读
# --------------------------------------------------------------------------- #
@tool
def feishu_read_page(wiki_url_or_token: str) -> str:
    """
    读取飞书知识库页面的纯文本内容。

    参数：
      wiki_url_or_token — 飞书 wiki 页面 URL 或 token。
        支持完整 URL：https://xxx.feishu.cn/wiki/Qo4nwLphWiWZyfkGAHHcoHwQnEf
        也支持裸 token：Qo4nwLphWiWZyfkGAHHcoHwQnEf

    返回页面的纯文本内容。
    """
    try:
        kb = FeishuKnowledge()
        content = kb.read_page(wiki_url_or_token)
        return content or "（页面内容为空）"
    except Exception as e:
        logger.error(f"[feishu_read_page] {e}")
        return f"读取失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书知识库 — 写（追加）
# --------------------------------------------------------------------------- #
@tool
def feishu_append_to_page(wiki_url_or_token: str, content: str) -> str:
    """
    向飞书知识库页面末尾追加文本内容，不影响已有内容。

    参数：
      wiki_url_or_token — 飞书 wiki 页面 URL 或 token
      content           — 要追加的文本（支持多行）

    适用场景：记录新信息、追加日志、在已有文档末尾补充内容。
    """
    try:
        kb = FeishuKnowledge()
        kb.append_to_page(wiki_url_or_token, content)
        return "内容已追加到飞书页面。"
    except Exception as e:
        logger.error(f"[feishu_append_to_page] {e}")
        return f"追加失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书知识库 — 写（覆盖）
# --------------------------------------------------------------------------- #
@tool
def feishu_overwrite_page(wiki_url_or_token: str, content: str) -> str:
    """
    清空飞书知识库页面并写入新内容（覆盖模式）。

    参数：
      wiki_url_or_token — 飞书 wiki 页面 URL 或 token
      content           — 新的完整内容（会替换页面所有原有内容）

    注意：此操作不可撤销，原有内容将被清除。
    适用场景：更新上下文快照、重写文档、定期刷新页面内容。
    """
    try:
        kb = FeishuKnowledge()
        kb.overwrite_page(wiki_url_or_token, content)
        return "飞书页面内容已覆盖更新。"
    except Exception as e:
        logger.error(f"[feishu_overwrite_page] {e}")
        return f"覆盖写入失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书知识库 — 搜索
# --------------------------------------------------------------------------- #
@tool
def feishu_search_wiki(query: str) -> str:
    """
    在飞书知识库（AI上下文页面）中搜索包含关键词的内容。

    参数：
      query — 搜索关键词

    返回匹配的页面内容摘要。若无匹配则返回提示。
    适用场景：查找历史记录、检索已记录的信息。
    """
    try:
        kb = FeishuKnowledge()
        results = kb.search(query)
        if not results:
            return f"知识库中未找到包含「{query}」的内容。"
        return "\n\n---\n\n".join(results[:3])
    except Exception as e:
        logger.error(f"[feishu_search_wiki] {e}")
        return f"搜索失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书知识库 — 上下文快照同步
# --------------------------------------------------------------------------- #
@tool
def sync_context_to_feishu() -> str:
    """
    将本地 SQLite 记忆（LangGraph checkpoints）快照同步到飞书知识库上下文页面。
    自动覆盖更新，保持飞书页面与本地记忆同步。
    """
    try:
        ContextSync().push_to_feishu()
        return "本地上下文已同步至飞书知识库。"
    except Exception as e:
        logger.error(f"[sync_context_to_feishu] {e}")
        return f"同步失败：{e}"


# --------------------------------------------------------------------------- #
# 钉钉文档（会议纪要）
# --------------------------------------------------------------------------- #
@tool
def get_latest_meeting_docs(limit: int = 5) -> str:
    """从钉钉文档空间获取最新会议纪要列表。"""
    try:
        docs = DingTalkDocs()
        items = docs.list_recent_files(limit=limit)
        if not items:
            return "暂无会议文档。"
        lines = [f"- [{d['name']}]({d['url']})  {d['updated_at']}" for d in items]
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[get_latest_meeting_docs] {e}")
        return f"获取失败：{e}"


@tool
def read_meeting_doc(file_id: str) -> str:
    """读取钉钉文档完整文本内容。file_id: 文档 ID。"""
    try:
        docs = DingTalkDocs()
        return docs.read_file_content(file_id)
    except Exception as e:
        logger.error(f"[read_meeting_doc] {e}")
        return f"读取失败：{e}"


# --------------------------------------------------------------------------- #
# 自迭代：异步启动 Claude Code，流式输出实时推送到 IM
# --------------------------------------------------------------------------- #
@tool
def trigger_self_iteration(requirement: str) -> str:
    """
    触发 Claude Code 自迭代开发（异步）。

    启动 claude CLI，以流式 JSON 模式运行，执行过程和结果实时通过 IM 推送给用户。
    用户在 Claude 运行期间发送的消息会被转发给 Claude。

    requirement: 清晰的需求描述，包含目标、约束和验收标准。
    """
    from integrations.claude_code.session import session_manager
    from graph.nodes import get_tool_ctx

    thread_id, send_fn = get_tool_ctx()

    if not thread_id:
        logger.warning("[自迭代] 未获取到 thread_id，降级为同步模式")
        return _trigger_sync(requirement)

    if not send_fn:
        logger.warning(f"[自迭代] thread_id={thread_id} 无 send_fn，降级为同步模式")
        return _trigger_sync(requirement)

    logger.info(f"[自迭代] 异步启动 thread={thread_id}，需求：{requirement[:80]}")
    session_manager.start(thread_id, requirement, send_fn)
    return "✅ Claude Code 已启动，正在执行中...\n执行过程将实时推送，期间你的消息可直接与 Claude 交互。"


def _trigger_sync(requirement: str) -> str:
    """降级同步模式：无 IM 推送，直接返回结果。"""
    prompt = (
        f"你正在开发 /root/ai-assistant 项目（AI 个人助理）。\n"
        f"请根据以下需求进行开发，直到完成为止：\n\n{requirement}\n\n"
        f"完成后输出：1) 修改了哪些文件  2) 做了什么  3) 如何验证"
    )
    try:
        result = subprocess.run(
            ["claude", "--print", "--permission-mode", "acceptEdits", prompt],
            capture_output=True, text=True, cwd=PROJECT_DIR, timeout=600,
            env={**os.environ},
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            return f"Claude Code 执行失败（exit={result.returncode}）：\n{result.stderr.strip()[:500]}"
        return f"Claude Code 完成：\n\n{output[:3000]}"
    except subprocess.TimeoutExpired:
        return "Claude Code 超时（>10分钟）。"
    except FileNotFoundError:
        return "未找到 claude 命令，请确认 Claude Code CLI 已安装。"


# --------------------------------------------------------------------------- #
# 本机 Shell（无限制，个人私有服务器）
# --------------------------------------------------------------------------- #
@tool
def run_command(command: str) -> str:
    """
    在本机执行任意 Shell 命令（个人私有服务器，无限制）。
    支持 git、ls、cat、python、pip、df、ps、find、curl 等所有命令。
    超时 60 秒，输出截断至 3000 字符。
    """
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=60, cwd=PROJECT_DIR,
        )
        output = (result.stdout or result.stderr or "（无输出）").strip()
        return output[:3000]
    except subprocess.TimeoutExpired:
        return "命令执行超时（>60s）"
    except Exception as e:
        return f"命令执行失败：{e}"


# --------------------------------------------------------------------------- #
# Claude Code 会话管理（tmux）
# --------------------------------------------------------------------------- #
@tool
def list_claude_sessions() -> str:
    """
    列出当前所有活跃的 Claude Code tmux 会话。

    返回每个会话的名称、对应的 IM 会话 ID、创建时间。
    用于了解哪些 Claude 任务正在后台运行。
    """
    from integrations.claude_code.tmux_session import list_active_sessions
    sessions = list_active_sessions()
    if not sessions:
        return "当前没有活跃的 Claude Code 会话。"
    lines = ["活跃的 Claude Code 会话："]
    for s in sessions:
        lines.append(f"  • {s['session_name']}  thread={s['thread_id']}  创建于={s['created']}")
    lines.append("\n可用 `tmux attach -t {session_name}` 直接查看会话。")
    return "\n".join(lines)


@tool
def get_claude_session_output(thread_id: str, lines: int = 80) -> str:
    """
    获取指定 Claude Code 会话的最近输出内容。

    参数：
      thread_id — IM 会话 ID（如 feishu:oc_xxx），或 tmux session 名称
      lines     — 获取最近多少行（默认 80）

    适用于查看 Claude Code 当前执行进度或排查问题。
    """
    from integrations.claude_code.tmux_session import _sessions, _safe_name, _tmux
    # 尝试在内存会话中查找
    session = _sessions.get(thread_id)
    if session:
        return session.get_recent_output(lines)
    # 尝试用 tmux 直接查
    name = thread_id if thread_id.startswith("ai-claude-") else _safe_name(thread_id)
    rc, out = _tmux("capture-pane", "-t", name, "-p", f"-{lines}")
    if rc == 0:
        return out.strip() or "（屏幕内容为空）"
    return f"未找到会话 {thread_id}，请先用 list_claude_sessions 确认会话名称。"


@tool
def kill_claude_session(thread_id: str) -> str:
    """
    强制终止指定的 Claude Code tmux 会话。

    参数：
      thread_id — IM 会话 ID 或 tmux session 名称

    适用场景：Claude 陷入循环、任务需要中止、重新下发新需求。
    """
    from integrations.claude_code.tmux_session import _sessions, _sessions_lock, _safe_name, _tmux
    with _sessions_lock:
        session = _sessions.pop(thread_id, None)
    if session:
        session._stop.set()
        _tmux("kill-session", "-t", session.session_name)
        return f"✅ 已终止会话 {session.session_name}。"
    # 尝试直接 kill tmux session
    name = thread_id if thread_id.startswith("ai-claude-") else _safe_name(thread_id)
    rc, out = _tmux("kill-session", "-t", name)
    if rc == 0:
        return f"✅ 已终止 tmux 会话 {name}。"
    return f"未找到会话 {thread_id}。当前活跃会话：{[s['session_name'] for s in __import__('integrations.claude_code.tmux_session', fromlist=['list_active_sessions']).list_active_sessions()]}"


@tool
def send_claude_input(thread_id: str, text: str) -> str:
    """
    向正在运行的 Claude Code 会话发送输入文本。

    参数：
      thread_id — IM 会话 ID 或 tmux session 名称
      text      — 要发送的内容（Claude 的问题回答、追加指令等）

    注意：仅对交互模式有效；stream-json 模式下 Claude 不读 stdin。
    适合在 Claude 询问用户时提供回答。
    """
    from integrations.claude_code.tmux_session import session_manager, _safe_name, _tmux
    ok = session_manager.relay_input(thread_id, text)
    if ok:
        return f"✅ 已向 {thread_id} 发送输入。"
    # 尝试直接 tmux send-keys
    name = thread_id if thread_id.startswith("ai-claude-") else _safe_name(thread_id)
    rc, _ = _tmux("send-keys", "-t", name, text, "Enter")
    if rc == 0:
        return f"✅ 已通过 tmux 向 {name} 发送输入。"
    return f"发送失败：会话 {thread_id} 不存在或未运行。"


# --------------------------------------------------------------------------- #
# Web 工具
# --------------------------------------------------------------------------- #
@tool
def web_search(query: str, num_results: int = 5) -> str:
    """
    在网络上搜索信息，返回摘要结果列表。

    参数：
      query       — 搜索关键词（支持中英文）
      num_results — 返回结果数量（默认 5，最多 10）

    返回搜索结果标题、URL 和摘要。
    """
    num_results = min(int(num_results), 10)
    try:
        # 使用 DuckDuckGo lite（无需 API key）
        encoded = urllib.parse.quote_plus(query)
        url = f"https://duckduckgo.com/lite/?q={encoded}&kl=cn-zh"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Assistant/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")

        # 解析结果：从 HTML 提取标题、链接、摘要
        results = []
        # DuckDuckGo lite 返回 <a class="result-link"> 和 <td class="result-snippet">
        link_pat = re.compile(r'<a[^>]+class="result-link"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', re.I)
        snip_pat = re.compile(r'<td[^>]+class="result-snippet"[^>]*>(.*?)</td>', re.I | re.S)
        links = link_pat.findall(body)
        snips = snip_pat.findall(body)
        for i, (href, title) in enumerate(links[:num_results]):
            snip = snips[i] if i < len(snips) else ""
            snip = re.sub(r"<[^>]+>", "", snip).strip()
            snip = html.unescape(snip)[:200]
            title = html.unescape(title.strip())
            results.append(f"{i+1}. **{title}**\n   {href}\n   {snip}")

        if not results:
            return f"未找到关于「{query}」的搜索结果。"
        return f"搜索「{query}」的结果：\n\n" + "\n\n".join(results)

    except Exception as e:
        logger.warning(f"[web_search] DuckDuckGo 失败: {e}，尝试 curl")
        # fallback: 通过 run_command 调用 curl
        try:
            r = subprocess.run(
                ["curl", "-s", "-L", "--max-time", "10",
                 "-A", "Mozilla/5.0",
                 f"https://duckduckgo.com/lite/?q={urllib.parse.quote_plus(query)}"],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0 and r.stdout:
                # 简单提取文本
                text = re.sub(r"<[^>]+>", " ", r.stdout)
                text = re.sub(r"\s+", " ", text).strip()
                return f"搜索「{query}」（原始文本）：\n\n{text[:2000]}"
        except Exception:
            pass
        return f"搜索失败：{e}"


@tool
def web_fetch(url: str, max_chars: int = 3000) -> str:
    """
    获取指定 URL 的网页内容（提取纯文本，去除 HTML 标签）。

    参数：
      url       — 要访问的网址
      max_chars — 返回的最大字符数（默认 3000）

    适用场景：阅读文档、新闻、技术文章、API 参考等。
    """
    max_chars = min(int(max_chars), 8000)
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Assistant/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        # 去除 script/style/head
        body = re.sub(r"<(script|style|head)[^>]*>.*?</\1>", "", body, flags=re.I | re.S)
        # 去除 HTML 标签
        text = re.sub(r"<[^>]+>", " ", body)
        # 合并空白
        text = re.sub(r"\s+", " ", html.unescape(text)).strip()
        return text[:max_chars] + ("..." if len(text) > max_chars else "")
    except Exception as e:
        logger.error(f"[web_fetch] {url}: {e}")
        return f"获取失败：{e}"


# --------------------------------------------------------------------------- #
# Python 代码执行
# --------------------------------------------------------------------------- #
@tool
def python_execute(code: str) -> str:
    """
    在本机执行 Python 代码片段并返回输出。

    参数：
      code — Python 代码（支持多行，可 import 任何已安装包）

    适用场景：数据处理、计算、调用 Python 库、快速验证逻辑。
    超时 30 秒，stdout+stderr 合并返回，截断至 3000 字符。
    """
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True, text=True,
            timeout=30, cwd=PROJECT_DIR,
        )
        output = (result.stdout + result.stderr).strip()
        return (output or "（无输出）")[:3000]
    except subprocess.TimeoutExpired:
        return "执行超时（>30s）"
    except Exception as e:
        return f"执行失败：{e}"


# --------------------------------------------------------------------------- #
# 系统状态
# --------------------------------------------------------------------------- #
@tool
def get_system_status() -> str:
    """
    获取本机系统状态：CPU、内存、磁盘、运行进程概览。
    用于监控服务器健康状况。
    """
    try:
        r = subprocess.run(
            "echo '=== CPU ===' && top -bn1 | head -5 && "
            "echo '' && echo '=== 内存 ===' && free -h && "
            "echo '' && echo '=== 磁盘 ===' && df -h / /root 2>/dev/null && "
            "echo '' && echo '=== 进程 ===' && ps aux --sort=-%cpu | head -10",
            shell=True, capture_output=True, text=True, timeout=10,
        )
        return (r.stdout + r.stderr).strip()[:3000]
    except Exception as e:
        return f"获取系统状态失败：{e}"


@tool
def get_service_status() -> str:
    """
    检查 AI 助理服务的运行状态：FastAPI 进程、tmux 会话、日志尾部。
    """
    try:
        r = subprocess.run(
            "echo '=== FastAPI 进程 ===' && ps aux | grep 'main.py\\|uvicorn' | grep -v grep && "
            "echo '' && echo '=== 端口监听 ===' && ss -tlnp | grep 8000 && "
            "echo '' && echo '=== Claude tmux 会话 ===' && tmux list-sessions 2>/dev/null | grep ai-claude || echo '无活跃 Claude 会话' && "
            "echo '' && echo '=== 最近日志 ===' && tail -20 logs/app.log 2>/dev/null || echo '日志文件不存在'",
            shell=True, capture_output=True, text=True, timeout=10, cwd=PROJECT_DIR,
        )
        return (r.stdout + r.stderr).strip()[:3000]
    except Exception as e:
        return f"获取服务状态失败：{e}"


# --------------------------------------------------------------------------- #
# 导出所有工具
# --------------------------------------------------------------------------- #
ALL_TOOLS = [
    # 飞书知识库
    feishu_read_page,
    feishu_append_to_page,
    feishu_overwrite_page,
    feishu_search_wiki,
    sync_context_to_feishu,
    # 钉钉文档
    get_latest_meeting_docs,
    read_meeting_doc,
    # Claude Code 管理（tmux）
    trigger_self_iteration,
    list_claude_sessions,
    get_claude_session_output,
    kill_claude_session,
    send_claude_input,
    # Web
    web_search,
    web_fetch,
    # 代码执行
    python_execute,
    # 系统
    run_command,
    get_system_status,
    get_service_status,
]
