"""
工具函数，注册为 LangGraph tools，供 agent nodes 调用。
"""
import json
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
from integrations.feishu.client import feishu_get, feishu_post, feishu_delete
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
def get_latest_meeting_docs(limit: int = 20, keyword: str = None, space_id: str = None) -> str:
    """
    从钉钉知识库空间获取文档列表（不限于会议纪要类型）。

    参数：
      limit    — 返回最多多少条（默认 20）
      keyword  — 按标题关键词过滤（可选，不区分大小写）
      space_id — 知识库空间 ID（默认使用 .env 中的 DINGTALK_DOCS_SPACE_ID=r9xmyYP7YK1w1mEO）

    返回文档列表（名称、URL、更新时间）。
    """
    try:
        docs = DingTalkDocs(space_id=space_id)
        items = docs.list_recent_files(limit=limit, keyword=keyword)
        if not items:
            kw_hint = f"（关键词：{keyword}）" if keyword else ""
            return f"知识库空间 {docs.space_id} 中暂未找到文档{kw_hint}。"
        lines = [f"共 {len(items)} 条文档："]
        for d in items:
            name = d['name'] or '（无标题）'
            url_part = f"  {d['url']}" if d['url'] else ""
            time_part = f"  {d['updated_at']}" if d['updated_at'] else ""
            lines.append(f"- [{name}]{url_part}{time_part}  id={d['id']}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[get_latest_meeting_docs] {e}")
        return f"获取失败：{e}"


@tool
def read_meeting_doc(file_id: str) -> str:
    """读取钉钉文档完整文本内容（通过钉钉 API）。

    参数：
      file_id — 钉钉文档 nodeId，或 alidocs 链接（https://alidocs.dingtalk.com/i/nodes/...）

    注意：优先使用 MCP 工具 `get_document_content` 读取文档，本工具作为降级备选。
    """
    try:
        docs = DingTalkDocs()
        node_id = DingTalkDocs.extract_node_id_from_url(file_id)
        content = docs.read_file_content(node_id)
        if not content or content.startswith("读取失败"):
            return (
                f"通过 API 读取失败（nodeId={node_id}）。\n"
                f"建议改用 MCP 工具 get_document_content(docId='{node_id}') 读取。\n"
                f"原始错误: {content}"
            )
        return content
    except Exception as e:
        logger.error(f"[read_meeting_doc] {e}")
        return f"读取失败：{e}"


@tool
def analyze_meeting_doc(file_id: str, force: bool = False) -> str:
    """
    立即分析指定钉钉文档并写入飞书会议纪要页面。

    参数：
      file_id — 钉钉文档 ID（从 MCP 工具 search_documents / list_nodes 获取）
      force   — 是否强制重新分析已处理过的文档（默认 False）

    流程：读取内容 → LLM 分析 → 写入飞书 → 返回摘要。
    需要在 .env 中配置 FEISHU_WIKI_MEETING_PAGE（飞书会议纪要汇总页面 wiki token）。
    """
    from integrations.meeting import analyzer, tracker
    try:
        docs = DingTalkDocs()
        # 查找文档元信息
        items = docs.list_recent_files(limit=50)
        item = next((i for i in items if i.get("id") == file_id), {"id": file_id, "name": file_id, "url": ""})
        doc_name = item.get("name", file_id)

        if not force and tracker.is_processed(file_id):
            rec = next((r for r in tracker.list_processed(50) if r["doc_id"] == file_id), {})
            return f"文档已于 {rec.get('analyzed_at', '?')} 处理过。传 force=true 可强制重新分析。"

        if force:
            tracker.unmark(file_id)

        content = docs.read_file_content(file_id)
        if not content:
            return "文档内容为空，无法分析。"

        info = analyzer.analyze(content, doc_name=doc_name)
        if info is None:
            tracker.mark_processed(file_id, docs.space_id, doc_name, "not_meeting")
            return "该文档不像是会议纪要，未写入飞书。"

        doc_url = item.get("url", "")
        feishu_page = analyzer.write_to_feishu(info, doc_url=doc_url)
        tracker.mark_processed(file_id, docs.space_id, doc_name, feishu_page)

        summary = info.get("summary", "")
        decisions = "\n".join(f"  - {d}" for d in (info.get("decisions") or []))
        actions = "\n".join(
            f"  - {a['task']}（{a.get('owner','?')} / {a.get('deadline','无截止')}）"
            for a in (info.get("action_items") or [])
        )
        return (
            f"✅ 分析完成：{doc_name}\n"
            f"摘要：{summary}\n"
            + (f"决策：\n{decisions}\n" if decisions else "")
            + (f"待办：\n{actions}\n" if actions else "")
            + f"已写入飞书：{feishu_page}"
        )
    except Exception as e:
        logger.error(f"[analyze_meeting_doc] {e}")
        return f"分析失败：{e}"


@tool
def list_processed_meetings(limit: int = 10) -> str:
    """列出已分析过的钉钉会议文档（最近 N 条）。"""
    from integrations.meeting.tracker import list_processed
    items = list_processed(limit)
    if not items:
        return "尚未分析过任何会议文档。"
    lines = [f"最近 {len(items)} 条已处理会议："]
    for r in items:
        lines.append(f"- [{r['doc_name']}] {r['analyzed_at']}  → {r['feishu_page']}")
    return "\n".join(lines)


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
    检查 AI 助理服务的运行状态：主进程、tmux 会话、日志尾部、最近崩溃记录。
    """
    try:
        r = subprocess.run(
            "echo '=== 主进程 ===' && ps aux | grep 'main.py' | grep -v grep && "
            "echo '' && echo '=== Claude tmux 会话 ===' && (tmux list-sessions 2>/dev/null | grep ai-claude || echo '无活跃 Claude 会话') && "
            "echo '' && echo '=== 最近日志 ===' && tail -20 logs/app.log 2>/dev/null || echo '日志文件不存在'",
            shell=True, capture_output=True, text=True, timeout=10, cwd=PROJECT_DIR,
        )
        output = (r.stdout + r.stderr).strip()

        # 读 crash.log 最近 5 条
        crash_log = os.path.join(PROJECT_DIR, "logs", "crash.log")
        crash_section = "\n\n=== 最近崩溃记录 ==="
        if os.path.exists(crash_log):
            try:
                with open(crash_log, encoding="utf-8") as f:
                    lines = f.readlines()
                recent = lines[-5:]
                if recent:
                    for line in recent:
                        try:
                            entry = json.loads(line)
                            crash_section += f"\n[{entry.get('time','')}] {entry.get('thread','')} — {entry.get('error','')}"
                        except Exception:
                            crash_section += f"\n{line.rstrip()}"
                else:
                    crash_section += "\n无崩溃记录"
            except Exception as e:
                crash_section += f"\n读取失败: {e}"
        else:
            crash_section += "\n无崩溃记录"

        return (output + crash_section)[:4000]
    except Exception as e:
        return f"获取服务状态失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书知识库子页面管理（list / find_or_create）
# --------------------------------------------------------------------------- #
@tool
def feishu_wiki_page(
    action: str,
    title: str = "",
    parent_wiki_token: str = "",
    cache_key: str = "",
) -> str:
    """
    飞书知识库子页面管理（全程 tenant_access_token，无需 user OAuth）。

    action 可选：
      list_children   — 列出 parent_wiki_token 下的子页面
                        （需 parent_wiki_token）
      find_or_create  — 查找或创建命名子页面，返回 wiki node_token
                        （需 title + parent_wiki_token；cache_key 可选，用于加速后续查找）

    find_or_create 查找顺序：
      1. config_store 缓存（cache_key 非空时）
      2. 列出子页面按 title 精确匹配
      3. 以上均无则新建（创建 docx → move_docs_to_wiki）

    示例：
      feishu_wiki_page(action="find_or_create",
                       title="📋 会议纪要汇总",
                       parent_wiki_token="FalZwGDOkiqpbQkeAjGc8jaznMd",
                       cache_key="WIKI_PAGE_MEETING_NOTES")
    """
    try:
        from integrations.feishu.knowledge import FeishuKnowledge
        kb = FeishuKnowledge()

        if action == "list_children":
            if not parent_wiki_token:
                return "list_children 需要提供 parent_wiki_token"
            items = kb.list_wiki_children(parent_wiki_token)
            if not items:
                return f"{parent_wiki_token} 下暂无子页面"
            lines = [f"共 {len(items)} 个子页面："]
            for it in items:
                child_hint = "（有子页）" if it.get("has_child") else ""
                lines.append(f"  - {it['title']}{child_hint}  token={it['node_token']}")
            return "\n".join(lines)

        elif action == "find_or_create":
            if not title or not parent_wiki_token:
                return "find_or_create 需要提供 title 和 parent_wiki_token"
            token = kb.find_or_create_child_page(title, parent_wiki_token, cache_key)
            url = f"https://pw46ob73t1c.feishu.cn/wiki/{token}"
            return f"✅ 页面 token={token}\n链接：{url}"

        else:
            return f"未知 action: {action!r}，可选：list_children / find_or_create"

    except Exception as e:
        logger.error(f"[feishu_wiki_page] {e}")
        return f"操作失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书多维表格（Bitable）— 记录 CRUD
# --------------------------------------------------------------------------- #
@tool
def feishu_bitable_record(
    action: str,
    app_token: str,
    table_id: str,
    record_id: str = None,
    fields: dict = None,
    records: list = None,
    record_ids: list = None,
    filter: dict = None,
    sort: list = None,
    field_names: list = None,
    page_size: int = 20,
    page_token: str = None,
) -> str:
    """
    飞书多维表格记录 CRUD 操作。

    action 可选：
      create        — 创建单条记录（需 fields）
      batch_create  — 批量创建记录（需 records，列表每项含 fields，上限 500）
      list          — 查询记录（可选 filter/sort/field_names）
      update        — 更新单条记录（需 record_id + fields）
      batch_update  — 批量更新记录（需 records，列表每项含 record_id + fields）
      delete        — 删除单条记录（需 record_id）
      batch_delete  — 批量删除记录（需 record_ids，上限 500）

    字段值类型严格：
      人员字段 = [{"id": "ou_xxx"}]
      日期字段 = 毫秒时间戳整数（如 1674206443000）
      单选字段 = 字符串（如 "选项名"）
      多选字段 = 字符串列表（如 ["选项1", "选项2"]）
      复选框   = 布尔值（True/False）
    """
    try:
        base = f"/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        if action == "create":
            resp = feishu_post(base, json={"fields": fields or {}})
            return str(resp.get("data", resp))
        elif action == "batch_create":
            resp = feishu_post(f"{base}/batch_create", json={"records": records or []})
            return str(resp.get("data", resp))
        elif action == "list":
            body = {"page_size": page_size}
            if filter:
                body["filter"] = filter
            if sort:
                body["sort"] = sort
            if field_names:
                body["field_names"] = field_names
            if page_token:
                body["page_token"] = page_token
            resp = feishu_post(f"{base}/search", json=body)
            return str(resp.get("data", resp))
        elif action == "update":
            resp = feishu_post(f"{base}/{record_id}", json={"fields": fields or {}})
            return str(resp.get("data", resp))
        elif action == "batch_update":
            resp = feishu_post(f"{base}/batch_update", json={"records": records or []})
            return str(resp.get("data", resp))
        elif action == "delete":
            resp = feishu_delete(f"{base}/{record_id}")
            return str(resp.get("data", resp))
        elif action == "batch_delete":
            resp = feishu_post(f"{base}/batch_delete", json={"records": record_ids or []})
            return str(resp.get("data", resp))
        else:
            return f"未知 action：{action}。可选：create/batch_create/list/update/batch_update/delete/batch_delete"
    except Exception as e:
        logger.error(f"[feishu_bitable_record] {e}")
        return f"操作失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书多维表格（Bitable）— 元数据查询
# --------------------------------------------------------------------------- #
@tool
def feishu_bitable_meta(
    action: str,
    app_token: str,
    table_id: str = None,
    view_id: str = None,
    page_size: int = 50,
    page_token: str = None,
) -> str:
    """
    飞书多维表格元数据查询。

    action 可选：
      list_tables — 列出 App 下所有数据表（需 app_token）
      list_fields — 列出数据表的所有字段（需 app_token + table_id）
      list_views  — 列出数据表的所有视图（需 app_token + table_id）

    返回字段/视图/数据表列表，包含 id、name、type 等信息。
    写记录前建议先调用 list_fields 确认字段类型。
    """
    try:
        if action == "list_tables":
            resp = feishu_get(f"/bitable/v1/apps/{app_token}/tables", params={"page_size": page_size, "page_token": page_token})
            return str(resp.get("data", resp))
        elif action == "list_fields":
            params = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            resp = feishu_get(f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields", params=params)
            return str(resp.get("data", resp))
        elif action == "list_views":
            params = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            resp = feishu_get(f"/bitable/v1/apps/{app_token}/tables/{table_id}/views", params=params)
            return str(resp.get("data", resp))
        else:
            return f"未知 action：{action}。可选：list_tables/list_fields/list_views"
    except Exception as e:
        logger.error(f"[feishu_bitable_meta] {e}")
        return f"查询失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书任务管理 — 任务 CRUD
# --------------------------------------------------------------------------- #
@tool
def feishu_task_task(
    action: str,
    task_guid: str = None,
    summary: str = None,
    description: str = None,
    due: dict = None,
    members: list = None,
    completed_at: str = None,
    tasklists: list = None,
    repeat_rule: str = None,
    current_user_id: str = None,
    completed: bool = None,
    page_size: int = 20,
    page_token: str = None,
    parent_task_guid: str = None,
) -> str:
    """
    飞书任务管理（task/v2）。

    action 可选：
      create         — 创建任务（需 summary；建议传 current_user_id 自动加为 follower）
      get            — 获取任务详情（需 task_guid）
      list           — 列出我的任务（可选 completed=true/false 过滤）
      patch          — 更新任务（需 task_guid；可更新 summary/description/due/completed_at）
      subtask_create — 创建子任务（需 parent_task_guid + summary）
      subtask_list   — 列出子任务（需 parent_task_guid）

    时间格式：ISO 8601 带时区，如 "2026-02-28T17:00:00+08:00"
    完成任务：completed_at = "2026-02-26 15:00:00"（北京时间字符串）
    反完成：completed_at = "0"
    成员角色：role 可选 "assignee"（负责人）或 "follower"（关注人）
    """
    try:
        base = "/task/v2/tasks"

        if action == "create":
            body: dict = {"summary": summary or ""}
            if description:
                body["description"] = description
            if due:
                body["due"] = due
            if tasklists:
                body["tasklists"] = tasklists
            if repeat_rule:
                body["repeat_rule"] = repeat_rule
            members_list = list(members or [])
            if current_user_id:
                ids = [m.get("id") for m in members_list]
                if current_user_id not in ids:
                    members_list.append({"id": current_user_id, "role": "follower"})
            if members_list:
                body["members"] = members_list
            resp = feishu_post(base, json={"task": body})
            return str(resp.get("data", resp))

        elif action == "get":
            resp = feishu_get(f"{base}/{task_guid}")
            return str(resp.get("data", resp))

        elif action == "list":
            params: dict = {"page_size": page_size}
            if completed is not None:
                params["completed"] = str(completed).lower()
            if page_token:
                params["page_token"] = page_token
            resp = feishu_get(base, params=params)
            return str(resp.get("data", resp))

        elif action == "patch":
            body = {}
            update_fields = []
            if summary is not None:
                body["summary"] = summary
                update_fields.append("summary")
            if description is not None:
                body["description"] = description
                update_fields.append("description")
            if due is not None:
                body["due"] = due
                update_fields.append("due")
            if completed_at is not None:
                body["completed_at"] = completed_at
                update_fields.append("completed_at")
            if members is not None:
                body["members"] = members
                update_fields.append("members")
            from integrations.feishu.client import feishu_post as _post
            resp = _post(
                f"{base}/{task_guid}",
                json={"task": body, "update_fields": update_fields},
            )
            return str(resp.get("data", resp))

        elif action == "subtask_create":
            body = {"summary": summary or ""}
            if description:
                body["description"] = description
            if due:
                body["due"] = due
            if members:
                body["members"] = members
            resp = feishu_post(f"{base}/{parent_task_guid}/subtasks", json={"task": body})
            return str(resp.get("data", resp))

        elif action == "subtask_list":
            resp = feishu_get(f"{base}/{parent_task_guid}/subtasks", params={"page_size": page_size})
            return str(resp.get("data", resp))

        else:
            return f"未知 action：{action}。可选：create/get/list/patch/subtask_create/subtask_list"
    except Exception as e:
        logger.error(f"[feishu_task_task] {e}")
        return f"操作失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书任务管理 — 清单
# --------------------------------------------------------------------------- #
@tool
def feishu_task_tasklist(
    action: str,
    tasklist_guid: str = None,
    name: str = None,
    members: list = None,
    completed: bool = None,
    page_size: int = 20,
    page_token: str = None,
) -> str:
    """
    飞书任务清单管理（task/v2）。

    action 可选：
      list        — 列出我的所有任务清单
      create      — 创建清单（需 name；创建者自动成为 owner，勿在 members 中包含创建者）
      tasks       — 查看清单内的任务（需 tasklist_guid；可选 completed=true/false）
      add_members — 向清单添加成员（需 tasklist_guid + members）

    成员角色：owner（所有者）/ editor（编辑）/ viewer（只读）/ chat（群组）
    """
    try:
        base = "/task/v2/tasklists"

        if action == "list":
            params = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            resp = feishu_get(base, params=params)
            return str(resp.get("data", resp))

        elif action == "create":
            body: dict = {"name": name or "新清单"}
            if members:
                body["members"] = members
            resp = feishu_post(base, json={"tasklist": body})
            return str(resp.get("data", resp))

        elif action == "tasks":
            params: dict = {"page_size": page_size}
            if completed is not None:
                params["completed"] = str(completed).lower()
            if page_token:
                params["page_token"] = page_token
            resp = feishu_get(f"{base}/{tasklist_guid}/tasks", params=params)
            return str(resp.get("data", resp))

        elif action == "add_members":
            resp = feishu_post(f"{base}/{tasklist_guid}/add_members", json={"members": members or []})
            return str(resp.get("data", resp))

        else:
            return f"未知 action：{action}。可选：list/create/tasks/add_members"
    except Exception as e:
        logger.error(f"[feishu_task_tasklist] {e}")
        return f"操作失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书全文搜索（需要 user_access_token）
# --------------------------------------------------------------------------- #
@tool
def feishu_search_doc_wiki(
    query: str,
    search_type: str = "all",
    page_size: int = 10,
    page_token: str = None,
) -> str:
    """
    跨飞书文档/Wiki 全文搜索（需要 user_access_token）。

    参数：
      query       — 搜索关键词
      search_type — 搜索范围：all（默认）/ doc / wiki / sheet / mindnote / slides
      page_size   — 每页结果数（默认 10，最大 50）
      page_token  — 分页 token（首次不传）

    需要在 .env 中配置 FEISHU_USER_ACCESS_TOKEN（+ FEISHU_USER_REFRESH_TOKEN 用于续期）。
    返回匹配的文档列表（标题、URL、类型、更新时间）。
    """
    try:
        from integrations.feishu.client import feishu_post_user
        body: dict = {"query": query, "page_size": page_size}
        if search_type and search_type != "all":
            body["search_type"] = search_type
        if page_token:
            body["page_token"] = page_token
        resp = feishu_post_user("/search/v2/doc_wiki/search", json=body)
        data = resp.get("data", resp)
        items = data.get("items", [])
        if not items:
            return f"未找到包含「{query}」的飞书文档/Wiki。"
        lines = [f"搜索「{query}」共 {len(items)} 条结果："]
        for it in items:
            title = it.get("title", "无标题")
            url = it.get("url", "")
            doc_type = it.get("type", "")
            lines.append(f"- [{title}]({url})  [{doc_type}]")
        if data.get("has_more"):
            lines.append(f"\n（还有更多，page_token={data.get('page_token')}）")
        return "\n".join(lines)
    except RuntimeError as e:
        return f"搜索失败（user token 未配置）：{e}"
    except Exception as e:
        logger.error(f"[feishu_search_doc_wiki] {e}")
        return f"搜索失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书 IM 消息读取（tenant_access_token）
# --------------------------------------------------------------------------- #
@tool
def feishu_im_get_messages(
    chat_id: str = None,
    container_id_type: str = "chat",
    start_time: str = None,
    end_time: str = None,
    sort_type: str = "ByCreateTimeAsc",
    page_size: int = 20,
    page_token: str = None,
) -> str:
    """
    读取飞书 IM 消息列表（使用 tenant_access_token，可读 bot 所在群）。

    参数：
      chat_id           — 会话 ID（oc_xxx 格式），必填
      container_id_type — 容器类型：chat（群聊/单聊，默认）或 thread（话题）
      start_time        — 起始时间（Unix 秒时间戳字符串，如 "1700000000"）
      end_time          — 结束时间（Unix 秒时间戳字符串）
      sort_type         — 排序：ByCreateTimeAsc（升序，默认）或 ByCreateTimeDesc（降序）
      page_size         — 每页消息数（默认 20，最大 50）
      page_token        — 分页 token

    返回消息列表（发送者、消息类型、文本内容、时间、message_id）。
    """
    try:
        if not chat_id:
            return "chat_id 为必填参数（oc_xxx 格式）"
        params: dict = {
            "container_id_type": container_id_type,
            "container_id": chat_id,
            "sort_type": sort_type,
            "page_size": page_size,
        }
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        if page_token:
            params["page_token"] = page_token
        resp = feishu_get("/im/v1/messages", params=params)
        data = resp.get("data", resp)
        items = data.get("items", [])
        if not items:
            return "该会话暂无消息记录。"
        lines = [f"共 {len(items)} 条消息："]
        for msg in items:
            sender = msg.get("sender", {})
            sender_id = sender.get("id", "?")
            msg_type = msg.get("msg_type", "?")
            create_time = msg.get("create_time", "")
            msg_id = msg.get("message_id", "")
            body = msg.get("body", {})
            content = body.get("content", "")
            # 截断长消息
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"[{create_time}] {sender_id} ({msg_type}): {content}  [id={msg_id}]")
        if data.get("has_more"):
            lines.append(f"\n（还有更多，page_token={data.get('page_token')}）")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[feishu_im_get_messages] {e}")
        return f"获取消息失败：{e}"


# --------------------------------------------------------------------------- #
# 运行时配置管理（长期记忆存储，无需重启）
# --------------------------------------------------------------------------- #
@tool
def agent_config(action: str, key: str = "", value: str = "") -> str:
    """
    管理 Agent 运行时配置（持久化到 SQLite，优先级高于 .env，无需重启生效）。

    action 可选：
      get    — 读取指定 key 的值（key 必填）
      set    — 写入 key=value（key、value 必填）
      delete — 删除指定 key（key 必填）
      list   — 列出所有配置项（key 可省略）

    常用 key：
      FEISHU_WIKI_MEETING_PAGE  — 飞书会议纪要汇总页面 wiki token（如 Qo4nwXxx）
      DINGTALK_DOCS_SPACE_ID    — 钉钉知识库空间 ID
      DINGTALK_WIKI_API_PATH    — 钉钉文档内容 API 路径（自动探测后写入：wiki 或 drive）

    示例：
      agent_config(action="set", key="FEISHU_WIKI_MEETING_PAGE", value="Qo4nwXxx")
      agent_config(action="get", key="FEISHU_WIKI_MEETING_PAGE")
      agent_config(action="list")
    """
    from integrations.storage.config_store import get as cfg_get, set as cfg_set, delete as cfg_del, list_all as cfg_list
    import json

    if action == "get":
        if not key:
            return "get 操作需要提供 key"
        val = cfg_get(key)
        return f"{key} = {val!r}" if val else f"{key} 未配置"
    elif action == "set":
        if not key or value == "":
            return "set 操作需要提供 key 和 value"
        cfg_set(key, value)
        return f"已设置 {key} = {value!r}"
    elif action == "delete":
        if not key:
            return "delete 操作需要提供 key"
        existed = cfg_del(key)
        return f"已删除 {key}" if existed else f"{key} 不存在"
    elif action == "list":
        data = cfg_list()
        if not data:
            return "暂无配置项"
        lines = [f"共 {len(data)} 项："]
        for k, v in data.items():
            lines.append(f"  {k} = {v['value']!r}  （更新于 {v['updated_at'][:16]}）")
        return "\n".join(lines)
    else:
        return f"未知 action: {action!r}，可选：get / set / delete / list"


# --------------------------------------------------------------------------- #
# 工具分类（渐进式披露）
# --------------------------------------------------------------------------- #

# 每次调用都会携带的最小工具集
CORE_TOOLS = [
    web_search,
    web_fetch,
    python_execute,
    run_command,
    get_system_status,
    get_service_status,
    agent_config,
]

# 按需加载的分类工具
TOOL_CATEGORIES: dict[str, list] = {
    # 飞书基础知识库读写（高频）
    "feishu_wiki": [
        feishu_read_page,
        feishu_append_to_page,
        feishu_overwrite_page,
        feishu_search_wiki,
        sync_context_to_feishu,
        feishu_wiki_page,
    ],
    # 飞书高级工具（Bitable / Task / 搜索 / IM）——schema 较重，按需加载
    "feishu_advanced": [
        feishu_bitable_record,
        feishu_bitable_meta,
        feishu_task_task,
        feishu_task_tasklist,
        feishu_search_doc_wiki,
        feishu_im_get_messages,
    ],
    # Claude Code 自迭代
    "claude": [
        trigger_self_iteration,
        list_claude_sessions,
        get_claude_session_output,
        kill_claude_session,
        send_claude_input,
    ],
}

# 触发各分类的关键词（中英文，小写匹配）
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "feishu_wiki": [
        "飞书", "feishu", "知识库", "wiki", "页面", "同步上下文",
        "读取文档", "追加", "覆盖",
    ],
    "feishu_advanced": [
        "多维表格", "bitable", "表格", "任务", "task", "日程",
        "全文搜索", "群聊", "消息记录", "im消息",
    ],
    "claude": [
        "迭代", "开发", "修复", "实现", "编写代码", "重构",
        "claude", "session", "会话", "调试", "自迭代",
    ],
}

# --------------------------------------------------------------------------- #
# 钉钉文档 MCP 工具（Streamable-HTTP MCP Server，按需加载）
# --------------------------------------------------------------------------- #
def _load_dingtalk_mcp() -> list:
    from integrations.mcp.client import load_mcp_tools
    tools = []

    doc_url = os.getenv("DINGTALK_MCP_URL", "")
    if doc_url:
        tools.extend(load_mcp_tools(doc_url, server_name="dingtalk_docs"))

    table_url = os.getenv("DINGTALK_MCP_TABLE_URL", "")
    if table_url:
        tools.extend(load_mcp_tools(table_url, server_name="dingtalk_table"))

    return tools


_dingtalk_mcp_tools = _load_dingtalk_mcp()

# 会议纪要流水线工具（无论 MCP 是否连接，始终挂在 dingtalk_mcp 分类下）
_pipeline_tools = [
    get_latest_meeting_docs,
    read_meeting_doc,
    analyze_meeting_doc,
    list_processed_meetings,
]

TOOL_CATEGORIES["dingtalk_mcp"] = _dingtalk_mcp_tools + _pipeline_tools
CATEGORY_KEYWORDS["dingtalk_mcp"] = [
    "钉钉", "dingtalk", "alidoc", "钉钉文档",
    "创建文档", "编辑文档", "搜索文档", "文档块", "block",
    "文件夹", "知识库文档", "文档内容",
    "ai表格", "钉钉表格", "智能表格",
    "会议", "纪要", "meeting", "会议室", "分析文档", "处理记录",
]
if _dingtalk_mcp_tools:
    logger.info(f"[tools] 钉钉 MCP 工具已注册: {[t.name for t in _dingtalk_mcp_tools]}")
logger.info(f"[tools] 会议纪要流水线工具已注册到 dingtalk_mcp 分类")

# 全量工具列表（供执行层 tools_by_name 使用，不直接传给 LLM）
ALL_TOOLS = CORE_TOOLS + [
    t for tools in TOOL_CATEGORIES.values() for t in tools
]
