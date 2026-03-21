"""
工具函数，注册为 LangGraph tools，供 agent nodes 调用。
"""
import json
import os
import re
import time
import subprocess
import logging
import textwrap
import urllib.parse
import httpx
import urllib.request
import html
from langchain_core.tools import tool
from integrations.feishu.knowledge import FeishuKnowledge
from integrations.feishu.client import feishu_get, feishu_post, feishu_delete, _update_env_user_token, FEISHU_BASE, _user_token_cache
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

    ⚠️ token 必须来自用户提供的 URL 或 feishu_wiki_page(list_children) 的返回结果，不能使用记忆中的旧 token。
    返回权限错误时（含 131006/403），停止重试，告知用户配置权限。
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

        # 尝试项目感知路由，降级到全局汇总页
        project_name = (info.get("project_name") or "").strip()
        project_code = (info.get("project_code") or "").strip().upper()
        folder_token = ""
        raid_written = False

        if project_name or project_code:
            try:
                from integrations.meeting.project_router import ProjectRouter
                router = ProjectRouter()
                folder_token = router.get_or_create_project_folder(project_name, project_code)
                routing = router.route_meeting(info, folder_token)
                feishu_page = analyzer.write_to_project_page(
                    info, routing["meeting_notes_token"], doc_url
                )
                raid = info.get("raid_elements") or {}
                has_raid = any(raid.get(k) for k in ("risks", "actions", "issues", "decisions"))
                if has_raid and routing.get("raid_token"):
                    analyzer.write_raid_rows(raid, routing["raid_token"], date=info.get("date") or "")
                    raid_written = True
            except Exception as e:
                logger.warning(f"[analyze_meeting_doc] 项目路由失败，降级: {e}")
                feishu_page = analyzer.write_to_feishu(info, doc_url=doc_url)
        else:
            feishu_page = analyzer.write_to_feishu(info, doc_url=doc_url)

        tracker.mark_processed(
            file_id, docs.space_id, doc_name, feishu_page,
            project_name=project_name, project_code=project_code,
            project_folder_token=folder_token, raid_written=raid_written,
        )

        summary = info.get("summary", "")
        decisions = "\n".join(f"  - {d}" for d in (info.get("decisions") or []))
        actions = "\n".join(
            f"  - {a['task']}（{a.get('owner','?')} / {a.get('deadline','无截止')}）"
            for a in (info.get("action_items") or [])
        )
        proj_hint = f" [{project_code}]" if project_code else ""
        return (
            f"✅ 分析完成{proj_hint}：{doc_name}\n"
            f"摘要：{summary}\n"
            + (f"决策：\n{decisions}\n" if decisions else "")
            + (f"待办：\n{actions}\n" if actions else "")
            + f"已写入飞书：{feishu_page}"
            + (f"\nRAID 日志：已更新" if raid_written else "")
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
# 每日会议迁移：手动触发或查询状态
# --------------------------------------------------------------------------- #
@tool
def trigger_daily_migration() -> str:
    """
    立即触发一次每日会议纪要迁移（富文本格式，保留原始钉钉文档时间）。

    等价于每天 08:00 自动执行的定时任务，可用于手动补跑或测试。
    处理最近 DAILY_MIGRATION_LOOKBACK_DAYS 天（默认7天）内未被本插件迁移过的文档。

    返回迁移摘要（处理/跳过/错误数量）。
    """
    try:
        from integrations.meeting.daily_migration import run_daily_migration
        return run_daily_migration()
    except Exception as e:
        logger.error(f"[trigger_daily_migration] {e}")
        return f"每日迁移失败：{e}"


@tool
def list_daily_migrations(limit: int = 10) -> str:
    """列出每日迁移插件已处理的会议文档（富文本格式，最近 N 条）。"""
    try:
        from integrations.meeting.daily_migration import list_migrated
        items = list_migrated(limit)
        if not items:
            return "每日迁移插件尚未处理任何文档。"
        lines = [f"每日迁移记录（最近 {len(items)} 条）："]
        for r in items:
            orig = f"  原始时间={r['original_time']}" if r.get("original_time") else ""
            lines.append(f"- [{r['doc_name']}]{orig}  → {r['migrated_at']}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[list_daily_migrations] {e}")
        return f"查询失败：{e}"


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
# 自我改进：触发 Claude Code 分析日志并优化 Agent
# --------------------------------------------------------------------------- #
@tool
def trigger_self_improvement(reason: str = "") -> str:
    """
    触发 Claude Code 对 Agent 进行自我分析和改进（异步，流式推送到 IM）。

    Claude Code 将执行：
    1. 分析近期交互日志（logs/interactions.jsonl）：纠正率、工具使用模式、高延迟对话
    2. 分析 LLM 调用日志（logs/llm.jsonl）：工具选择准确性、token 消耗
    3. 检查崩溃日志（logs/crash.log）
    4. 读取当前 workspace 文件（SOUL/USER/MEMORY/HEARTBEAT）和 prompts/system.md
    5. 生成针对性改进：更新 workspace/MEMORY.md、workspace/HEARTBEAT.md，
       必要时调整 prompts/system.md 工具选择规则
    6. 生成改进报告发送给用户
    7. 重启 agent 服务使改进生效

    reason: 触发原因（可选），帮助 Claude Code 聚焦改进方向。
    """
    from integrations.claude_code.session import session_manager
    from graph.nodes import get_tool_ctx

    thread_id, send_fn = get_tool_ctx()
    if not thread_id or not send_fn:
        return "⚠️ 无法获取会话上下文，请在 IM 对话中触发自我改进。"

    reason_section = f"\n\n**触发原因**: {reason}" if reason else ""

    requirement = f"""你是这个 AI Agent 的自我改进系统。请对 /root/ai-assistant 项目进行深度分析和优化。{reason_section}

## 分析任务

### 1. 交互日志分析
读取并分析 `logs/interactions.jsonl`（最近 200 条）：
- 统计 `has_correction=true` 的比例（用户纠正率）
- 列出最常被调用的工具 Top 5
- 找出高延迟对话（latency_ms > 8000）
- 找出 agent_response 包含"失败"、"错误"、"出错"的记录

### 2. LLM 调用日志分析
读取 `logs/llm.jsonl`（最近 200 条）：
- 统计各工具分类的激活频率
- 找出 tools_count=7（只有 CORE_TOOLS）但用户消息应该触发更多工具的情况
- 统计 token 消耗趋势

### 2.5 响应延迟专项分析（持续目标：>15s 的响应需评估优化空间）
从 `logs/interactions.jsonl` 分析延迟分布：
- 统计 latency_ms 的 p50/p95/max
- 列出 latency_ms > 15000 的记录（Top 10），逐条分析：
  - 对应的 user_message（短还是长？有无工具关键词？）
  - 对应的 tools_used（工具调用次数是否过多？）
  - 可能的原因：多轮工具调用链？tokens 过多？
- 对比 slow_response=true 和 slow_response=false 的记录，找出差异规律
- 在报告中输出"⚡ 响应速度分析"节，给出具体优化建议

### 3. 崩溃日志检查
读取 `logs/crash.log`（如存在）：
- 列出最近 5 条崩溃记录
- 识别重复崩溃模式

### 4. 读取当前配置
- `prompts/system.md`
- `workspace/MEMORY.md`
- `workspace/HEARTBEAT.md`
- `workspace/USER.md`

### 5. 重复问题检测（关键）
扫描 interactions.jsonl 所有 user_message，识别**未被解决的重复问题**：
- 提取包含以下关键词的消息：慢、卡、失败、没有、不对、错误、看不到、重试、超时、又、还是
- 按语义主题分组（如"响应慢"、"写飞书失败"、"工具不可用"等）
- 对每个主题，检查 workspace/MEMORY.md 和 workspace/HEARTBEAT.md 中是否已有对应改进记录：
  - 已记录但该主题仍出现 → 标记为"**改进后仍复现，视为未解决**"
  - 未记录 → 标记为"**首次发现**"
- 在报告中输出"🔄 重复出现的问题"节

### 6. 上下文健康监控
从 `logs/llm.jsonl` 分析各 thread 的 token 消耗：
- 统计各 thread_id 的调用次数和平均 input token 数
- 标记单次超过 30K input tokens 的 thread（上下文过重）
- 在报告中输出"📏 上下文健康"节：Top 5 最重 thread + 建议用户执行 /clear

## 改进任务（每项改进必须有数据支撑）

### 必做：更新 workspace/MEMORY.md
基于交互日志，提炼：
- 用户最常请求的任务类型
- 用户的沟通风格偏好
- Agent 已知的坏习惯（高频纠正的场景）

### 必做：更新 workspace/HEARTBEAT.md
根据实际运行情况调整心跳任务的优先级和频率。

### 按需：更新 prompts/system.md
仅在以下情况才改：
- 发现工具选择关键词（CATEGORY_KEYWORDS）有明显缺失
- 有重复出现的工具调用错误需要在 system prompt 层面纠正
改动要最小化，只改需要改的部分。

## 输出改进报告

格式（发给用户）：
```
## 🔍 自我改进报告

**分析周期**: 最近 N 条交互
**用户纠正率**: X%（含重复提及的隐式纠正）

**发现的问题**:
- ...

**🔄 重复出现的问题**:
| 主题 | 出现次数 | 首次 | 末次 | 状态 |
|------|---------|------|------|------|
| 响应慢 | N次 | MM-DD | MM-DD | ⚠️ 改进后仍复现 |

**📏 上下文健康**:
- 高负载 thread（input token >30K）: ...
- 建议对以下对话执行 /clear: ...

**已做的改进**:
- ...

**建议关注**:
- ...
```

## 最后：重启 agent 服务

```bash
cd /root/ai-assistant && kill $(cat logs/service.pid 2>/dev/null) 2>/dev/null; sleep 1; source .venv/bin/activate && nohup python main.py >> logs/app.log 2>&1 &
```

重启后将改进报告通过 IM 发给用户。"""

    logger.info(f"[自我改进] 启动 thread={thread_id}，原因: {reason or '手动触发'}")
    session_manager.start(thread_id, requirement, send_fn)
    return "🔍 自我改进已启动，Claude Code 正在分析日志并生成优化方案，完成后将推送报告..."


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
      list_children   — 列出子页面
                        parent_wiki_token 为空 → 列出知识库空间根节点（第一层文档）
                        parent_wiki_token 有值 → 列出该节点的子页面
                        ✅ 浏览用户文档结构时，先不传 parent_wiki_token 从根节点开始
                        ✅ 读写前不确定 token 时，先调此接口发现有效 token
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
        from integrations.feishu.knowledge import FeishuKnowledge, parse_wiki_token
        kb = FeishuKnowledge()

        # 清理 token（去除 URL 前缀、inline comment 残留、空白）
        if parent_wiki_token:
            parent_wiki_token = parse_wiki_token(parent_wiki_token.split("#")[0].strip())

        if action == "list_children":
            items = kb.list_wiki_children(parent_wiki_token)
            if not items:
                scope = parent_wiki_token or "空间根节点"
                return f"{scope} 下暂无子页面"
            scope = parent_wiki_token or "空间根节点"
            lines = [f"{scope} 共 {len(items)} 个子页面："]
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


@tool
def feishu_project_setup(
    project_name: str,
    project_code: str,
    parent_wiki_token: str = "",
    docs_to_create: str = "all",
) -> str:
    """
    一键在飞书知识库中建立标准项目文件夹结构（含全套文档模板）。

    参数：
      project_name     — 项目中文名称，如"知识库AI项目"
      project_code     — 项目英文代号，如"AIKG"（用于文件夹命名和缓存键）
      parent_wiki_token — 父页面 wiki token（默认在 wiki 根目录创建，与首页齐平）
                          ⚠️ 绝对不能传入 FEISHU_WIKI_CONTEXT_PAGE，那是 AI 助理专用页！
                          如果配置了 FEISHU_WIKI_PORTFOLIO_PAGE 则以它为父页面。
      docs_to_create   — "all" 创建全套7个文档，或逗号分隔的文档名，
                         如 "00_项目章程,02_技术方案"

    创建内容（默认 all，敏捷业务项目结构）：
      项目文件夹（命名：{code} {name} 🔵）
      00_项目章程 / 01_需求清单（用户故事）/ 04_会议纪要（文件夹）
      05_迭代计划（Sprint）/ 06_RAID 日志（含需求验收）/ 07_需求交付记录

    父页面优先级：parent_wiki_token 参数 > FEISHU_WIKI_PORTFOLIO_PAGE > wiki 根目录
    （不使用 FEISHU_WIKI_CONTEXT_PAGE，那是 AI 助理专用页）

    幂等：重复调用安全，已存在文档不覆盖内容。
    创建结果自动缓存到 config_store（FEISHU_PROJECT_{CODE}），后续无需重复查找。
    """
    try:
        from integrations.feishu.knowledge import FeishuKnowledge, _PROJECT_DOCS
        from integrations.storage.config_store import get as cfg_get

        # 确定父页面：优先 FEISHU_WIKI_PORTFOLIO_PAGE，未配置则直接在 wiki 根目录创建
        # 注意：不再回落到 FEISHU_WIKI_CONTEXT_PAGE（那是 AI 助理专用页，不是项目集目录）
        if not parent_wiki_token:
            parent_wiki_token = (
                cfg_get("FEISHU_WIKI_PORTFOLIO_PAGE")
                or os.getenv("FEISHU_WIKI_PORTFOLIO_PAGE", "")
            )
        if not parent_wiki_token:
            # 直接在 wiki 空间根目录创建（与首页齐平）
            from integrations.feishu.knowledge import FeishuKnowledge as _KB
            parent_wiki_token = _KB().space_id
            logger.info("[feishu_project_setup] 未配置 FEISHU_WIKI_PORTFOLIO_PAGE，在 wiki 根目录创建")

        # 清理 token（去除 URL 前缀、inline comment 残留、空白）
        from integrations.feishu.knowledge import parse_wiki_token
        parent_wiki_token = parse_wiki_token(parent_wiki_token.split("#")[0].strip())

        docs = (
            None
            if docs_to_create.strip().lower() == "all"
            else [d.strip() for d in docs_to_create.split(",") if d.strip()]
        )

        kb = FeishuKnowledge()
        result = kb.bootstrap_project(
            project_name=project_name,
            project_code=project_code,
            parent_wiki_token=parent_wiki_token,
            docs_to_create=docs,
        )

        lines = [f"✅ 项目结构创建完成：{project_code} {project_name}"]
        folder_token = result.get("folder", "")
        if folder_token:
            lines.append(f"📁 项目文件夹：https://feishu.cn/wiki/{folder_token}")
        for doc_name, token in result.items():
            if doc_name == "folder":
                continue
            if token:
                lines.append(f"  📄 {doc_name}：https://feishu.cn/wiki/{token}")
            else:
                lines.append(f"  ❌ {doc_name}：创建失败")
        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[feishu_project_setup] {e}")
        return f"❌ 项目结构创建失败：{e}"


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

    ⚠️ app_token 必须从多维表格 URL 提取：https://xxx.feishu.cn/base/{app_token}
    不知道 app_token 时，先询问用户提供多维表格链接，不能使用 placeholder。
    """
    if not app_token or "placeholder" in app_token.lower():
        return "app_token 无效。请从多维表格 URL 提取：https://xxx.feishu.cn/base/{app_token}"
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

    ⚠️ app_token 必须从多维表格 URL 提取：https://xxx.feishu.cn/base/{app_token}
    不知道 app_token 时，先询问用户提供多维表格链接，不能使用 placeholder。
    """
    if not app_token or "placeholder" in app_token.lower():
        return "app_token 无效。请从多维表格 URL 提取：https://xxx.feishu.cn/base/{app_token}"
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
# 飞书日历日程管理
# --------------------------------------------------------------------------- #
@tool
def feishu_calendar_event(
    action: str,
    calendar_id: str = "primary",
    event_id: str = None,
    summary: str = None,
    description: str = None,
    start_time: str = None,
    end_time: str = None,
    attendees: list = None,
    vchat_type: str = None,
    user_open_id: str = None,
    query: str = None,
    start_ts: str = None,
    end_ts: str = None,
    page_size: int = 20,
    page_token: str = None,
) -> str:
    """
    飞书日历日程管理（calendar/v4）。

    action 可选：
      create      — 创建日程（需 summary、start_time、end_time）
                    时间格式：ISO 8601 含时区，如 "2026-03-21T10:00:00+08:00"
                    attendees 格式：[{"type": "user", "id": "ou_xxx"}, ...]
                    vchat_type："vc"（飞书视频会议）/ "no_meeting"（无）
                    user_open_id：当前用户 open_id，日程才会出现在用户日历
      get         — 获取日程详情（需 event_id）
      list        — 列出日程（需 start_ts/end_ts，Unix 秒时间戳字符串）
      update      — 更新日程（需 event_id，可更新 summary/description/start_time/end_time）
      delete      — 删除日程（需 event_id）
      search      — 搜索日程（需 query）
      freebusy    — 忙闲查询（需 user_open_id + start_ts + end_ts）

    calendar_id 默认 "primary"（主日历），通常无需修改。
    需在飞书开放平台开通 calendar:calendar 权限。
    """
    try:
        base = f"/calendar/v4/calendars/{calendar_id}"

        if action == "create":
            if not summary or not start_time or not end_time:
                return "create 需要 summary、start_time、end_time"
            body: dict = {
                "summary": summary,
                "start_time": {"datetime": start_time},
                "end_time": {"datetime": end_time},
            }
            if description:
                body["description"] = description
            if vchat_type:
                body["vchat"] = {"vc_type": vchat_type}
            resp = feishu_post(f"{base}/events", json=body)
            event = resp.get("data", {}).get("event", {})
            ev_id = event.get("event_id", "")
            # 添加参会人（含创建者自己）
            all_attendees = list(attendees or [])
            if user_open_id:
                ids = [a.get("id") for a in all_attendees]
                if user_open_id not in ids:
                    all_attendees.append({"type": "user", "id": user_open_id})
            if all_attendees and ev_id:
                feishu_post(
                    f"{base}/events/{ev_id}/attendees/batch_create",
                    json={"attendees": all_attendees},
                )
            return str(event)

        elif action == "get":
            resp = feishu_get(f"{base}/events/{event_id}")
            return str(resp.get("data", {}).get("event", resp))

        elif action == "list":
            params: dict = {"page_size": page_size}
            if start_ts:
                params["start_time"] = start_ts
            if end_ts:
                params["end_time"] = end_ts
            if page_token:
                params["page_token"] = page_token
            resp = feishu_get(f"{base}/events/instance_view", params=params)
            return str(resp.get("data", resp))

        elif action == "update":
            body = {}
            if summary is not None:
                body["summary"] = summary
            if description is not None:
                body["description"] = description
            if start_time is not None:
                body["start_time"] = {"datetime": start_time}
            if end_time is not None:
                body["end_time"] = {"datetime": end_time}
            from integrations.feishu.client import feishu_post as _post
            resp = _post(f"{base}/events/{event_id}", json=body)
            return str(resp.get("data", resp))

        elif action == "delete":
            from integrations.feishu.client import feishu_delete as _del
            _del(f"{base}/events/{event_id}")
            return f"日程 {event_id} 已删除"

        elif action == "search":
            resp = feishu_post(f"{base}/events/search", json={
                "query": query or "",
                "page_size": page_size,
            })
            items = resp.get("data", {}).get("items", [])
            if not items:
                return f"未找到包含「{query}」的日程"
            lines = [f"搜索「{query}」共 {len(items)} 条："]
            for ev in items:
                lines.append(f"- [{ev.get('summary', '无标题')}] {ev.get('start_time', {}).get('datetime', '')} → {ev.get('end_time', {}).get('datetime', '')}  id={ev.get('event_id', '')}")
            return "\n".join(lines)

        elif action == "freebusy":
            if not user_open_id or not start_ts or not end_ts:
                return "freebusy 需要 user_open_id、start_ts、end_ts"
            resp = feishu_post("/calendar/v4/freebusy/query", json={
                "time_min": start_ts,
                "time_max": end_ts,
                "user_id_list": [user_open_id],
            })
            return str(resp.get("data", resp))

        else:
            return f"未知 action：{action}。可选：create/get/list/update/delete/search/freebusy"
    except Exception as e:
        logger.error(f"[feishu_calendar_event] {e}")
        return f"日历操作失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书电子表格（Sheets）
# --------------------------------------------------------------------------- #
@tool
def feishu_spreadsheet(
    action: str,
    spreadsheet_token: str = None,
    sheet_id: str = None,
    title: str = None,
    range_: str = None,
    values: list = None,
    folder_token: str = None,
    page_size: int = 20,
) -> str:
    """
    飞书电子表格操作（sheets API）。

    action 可选：
      create        — 创建新电子表格（需 title；folder_token 可选，指定存放目录）
      get_meta      — 获取表格元信息（sheet 列表、title 等，需 spreadsheet_token）
      read_values   — 读取单元格数据（需 spreadsheet_token + range_）
                      range_ 格式："{sheet_id}!A1:D10" 或 "{sheet_id}!A:D"
      write_values  — 写入/覆盖单元格（需 spreadsheet_token + range_ + values）
                      values 格式：二维数组，如 [["姓名","分数"],["张三",90]]
      append_values — 追加行数据（需 spreadsheet_token + range_ + values）
                      自动追加到有数据的最后一行之后

    spreadsheet_token 从表格 URL 提取：https://xxx.feishu.cn/sheets/{spreadsheet_token}
    """
    try:
        if action == "create":
            if not title:
                return "create 需要提供 title"
            body: dict = {"title": title}
            if folder_token:
                body["folder_token"] = folder_token
            resp = feishu_post("/sheets/v3/spreadsheets", json=body)
            sheet = resp.get("data", {}).get("spreadsheet", {})
            return str(sheet)

        elif action == "get_meta":
            if not spreadsheet_token:
                return "get_meta 需要提供 spreadsheet_token"
            resp = feishu_get(f"/sheets/v3/spreadsheets/{spreadsheet_token}")
            return str(resp.get("data", resp))

        elif action == "read_values":
            if not spreadsheet_token or not range_:
                return "read_values 需要 spreadsheet_token 和 range_"
            resp = feishu_get(
                f"/sheets/v2/spreadsheets/{spreadsheet_token}/values/{range_}",
                params={"valueRenderOption": "ToString", "dateTimeRenderOption": "FormattedString"},
            )
            return str(resp.get("data", resp))

        elif action == "write_values":
            if not spreadsheet_token or not range_ or values is None:
                return "write_values 需要 spreadsheet_token、range_ 和 values"
            resp = feishu_post(
                f"/sheets/v2/spreadsheets/{spreadsheet_token}/values",
                json={"valueRange": {"range": range_, "values": values}},
            )
            return str(resp.get("data", resp))

        elif action == "append_values":
            if not spreadsheet_token or not range_ or values is None:
                return "append_values 需要 spreadsheet_token、range_ 和 values"
            resp = feishu_post(
                f"/sheets/v2/spreadsheets/{spreadsheet_token}/values_append",
                json={"valueRange": {"range": range_, "values": values}},
            )
            return str(resp.get("data", resp))

        else:
            return f"未知 action：{action}。可选：create/get_meta/read_values/write_values/append_values"
    except Exception as e:
        logger.error(f"[feishu_spreadsheet] {e}")
        return f"电子表格操作失败：{e}"


# --------------------------------------------------------------------------- #
# 飞书群聊信息查询
# --------------------------------------------------------------------------- #
@tool
def feishu_chat_info(
    action: str,
    chat_id: str = None,
    page_size: int = 20,
    page_token: str = None,
    user_id: str = None,
    user_id_type: str = "open_id",
) -> str:
    """
    飞书群聊和用户信息查询。

    action 可选：
      list_chats   — 列出机器人所在的所有群聊（返回 chat_id/name/type）
      get_chat     — 获取指定群信息（需 chat_id）
      list_members — 列出群成员（需 chat_id）
      get_user     — 查询用户信息（需 user_id；user_id_type: open_id/user_id/union_id）

    使用场景：
      - 想知道"帮我发给xxx群"时先用 list_chats 找到群 chat_id
      - 需要群成员信息时用 list_members
      - 看到 open_id 想知道是谁用 get_user
    """
    try:
        if action == "list_chats":
            params: dict = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            resp = feishu_get("/im/v1/chats", params=params)
            data = resp.get("data", {})
            items = data.get("items", [])
            if not items:
                return "机器人当前不在任何群聊中"
            lines = [f"机器人所在群聊（共 {len(items)} 个）："]
            for c in items:
                lines.append(f"- {c.get('name', '(无名)')}  [{c.get('chat_type', '')}]  chat_id={c.get('chat_id', '')}")
            if data.get("has_more"):
                lines.append(f"\n（还有更多，page_token={data.get('page_token')}）")
            return "\n".join(lines)

        elif action == "get_chat":
            if not chat_id:
                return "get_chat 需要提供 chat_id"
            resp = feishu_get(f"/im/v1/chats/{chat_id}")
            return str(resp.get("data", resp))

        elif action == "list_members":
            if not chat_id:
                return "list_members 需要提供 chat_id"
            params = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            resp = feishu_get(f"/im/v1/chats/{chat_id}/members", params=params)
            data = resp.get("data", {})
            items = data.get("items", [])
            if not items:
                return "群成员列表为空"
            lines = [f"群成员（共 {len(items)} 人）："]
            for m in items:
                lines.append(f"- {m.get('name', '?')}  open_id={m.get('member_id', '')}")
            if data.get("has_more"):
                lines.append(f"\n（还有更多，page_token={data.get('page_token')}）")
            return "\n".join(lines)

        elif action == "get_user":
            if not user_id:
                return "get_user 需要提供 user_id"
            resp = feishu_get(
                f"/contact/v3/users/{user_id}",
                params={"user_id_type": user_id_type},
            )
            user = resp.get("data", {}).get("user", resp)
            name = user.get("name", "?") if isinstance(user, dict) else str(user)
            return str(user)

        else:
            return f"未知 action：{action}。可选：list_chats/get_chat/list_members/get_user"
    except Exception as e:
        logger.error(f"[feishu_chat_info] {e}")
        return f"查询失败：{e}"


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
# 对话历史获取（CORE 工具，按需历史）
# --------------------------------------------------------------------------- #
@tool
def get_recent_chat_context(limit: int = 3) -> str:
    """
    获取当前对话的最近 N 条历史消息（默认 3 条）。
    当用户消息含有引用词（上次/刚才/之前/那个/你说的）时主动调用，
    无需用户指定 chat_id，自动从当前会话上下文中获取。
    limit: 要获取的消息条数，建议 3。
    """
    from graph.nodes import get_tool_ctx
    thread_id, _ = get_tool_ctx()
    if not thread_id:
        return "无法获取当前会话 ID。"

    parts = thread_id.split(":", 1)
    if len(parts) != 2:
        return f"无法解析会话 ID: {thread_id}"
    platform, chat_id = parts[0], parts[1]

    try:
        if platform == "feishu":
            resp = feishu_get(f"/im/v1/messages?container_id_type=chat&container_id={chat_id}&page_size={limit}&sort_type=ByCreateTimeDesc")
            items = (resp.get("data") or {}).get("items") or []
            lines = []
            for item in items[:limit]:
                body = item.get("body") or {}
                content = body.get("content", "")
                try:
                    content = json.loads(content).get("text", content)
                except Exception:
                    pass
                sender = (item.get("sender") or {}).get("id", "?")
                lines.append(f"[{sender}]: {content[:200]}")
            return "\n".join(reversed(lines)) if lines else "暂无历史消息。"
        else:
            return "钉钉平台暂不支持获取历史消息。"
    except Exception as e:
        logger.error(f"[get_recent_chat_context] {e}")
        return f"获取历史消息失败：{e}"


# --------------------------------------------------------------------------- #
# 并发任务状态查询
# --------------------------------------------------------------------------- #
@tool
def query_task_status(limit: int = 10) -> str:
    """
    查询当前并发任务执行状态，包括正在运行的任务、等待队列大小和近期任务历史。

    Args:
        limit: 返回的近期任务条数，默认 10 条（最大 20 条）

    返回 JSON 格式，包含：
    - running: 当前正在执行的任务列表
    - queue_size: 等待队列中的任务数量
    - summary: 各状态任务数统计（pending/running/done/failed）
    - recent: 最近 N 条任务记录（包含状态、优先级、耗时等）
    """
    import json
    from graph.agent import get_concurrent_status
    status = get_concurrent_status()
    status["recent"] = status.get("recent", [])[:min(limit, 20)]

    # 为 recent 列表计算可读耗时
    for t in status["recent"]:
        if t.get("started_at") and t.get("finished_at"):
            t["elapsed_ms"] = round((t["finished_at"] - t["started_at"]) * 1000)
        elif t.get("started_at"):
            t["elapsed_ms"] = round((time.time() - t["started_at"]) * 1000)

    return json.dumps(status, ensure_ascii=False, indent=2, default=str)


# --------------------------------------------------------------------------- #
# 飞书 OAuth 授权配置工具
# --------------------------------------------------------------------------- #

_FEISHU_OAUTH_REDIRECT_URI = "https://open.feishu.cn/document/server-docs/"


@tool
def feishu_oauth_setup(action: str, code: str = "") -> str:
    """飞书 OAuth 授权工具：获取/更新 user_access_token + refresh_token，修复 wiki 空间 131006 权限问题。

    action 取值：
      - "check_status"  : ⚠️ 必须首先调用！检查当前 token 状态，过期则自动用 refresh_token 续期
      - "get_auth_url"  : 返回飞书登录授权链接，发给用户在浏览器中打开（仅 check_status 确认需要时才调用）
      - "exchange_code" : 用授权 code 换取 access_token + refresh_token，自动写入 .env

    ⚠️ 重要规则：遇到 token 相关错误时，必须先调用 check_status，不得直接调用 get_auth_url。
    - check_status 返回"有效"或"已自动续期" → token 正常，不需要重新授权，不得再触发 OAuth 流程
    - check_status 返回"需要重新授权" → 才可调用 get_auth_url 让用户登录

    使用流程（check_status 确认需要授权后）：
    1. feishu_oauth_setup(action="get_auth_url")  → 将链接发给用户
    2. 用户在浏览器打开链接，登录飞书后页面跳转，从地址栏复制 code=xxx 参数值，
    3. feishu_oauth_setup(action="exchange_code", code="xxx")
    4. .env 自动写入 FEISHU_USER_ACCESS_TOKEN / FEISHU_USER_REFRESH_TOKEN，立即生效
    """
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")

    if action == "check_status":
        token = os.getenv("FEISHU_USER_ACCESS_TOKEN", "")
        refresh_token = os.getenv("FEISHU_USER_REFRESH_TOKEN", "")
        expires_at = float(os.getenv("FEISHU_USER_TOKEN_EXPIRES_AT", "0"))
        now = time.time()

        if not token:
            return (
                "⚠️ token 状态：未配置\n"
                "FEISHU_USER_ACCESS_TOKEN 未设置，需要重新授权。\n"
                'feishu_oauth_setup(action="get_auth_url") 开始授权流程。'
            )

        # 手动配置 token 但未设置过期时间，视为有效（与 get_user_access_token 逻辑一致）
        if token and expires_at == 0:
            return (
                "✅ token 状态：有效（手动配置，未设置过期时间，视为有效）\n"
                "用户已登录，无需重新授权。token 可正常使用。"
            )

        # token 在缓存中且未过期
        if expires_at > 0 and now < expires_at - 60:
            remaining = int((expires_at - now) / 60)
            return (
                f"✅ token 状态：有效（剩余约 {remaining} 分钟）\n"
                "用户已登录，无需重新授权。token 可正常使用。"
            )

        # token 已过期，尝试用 refresh_token 续期
        if refresh_token:
            try:
                app_resp = httpx.post(
                    f"{FEISHU_BASE}/auth/v3/app_access_token/internal",
                    json={"app_id": app_id, "app_secret": app_secret},
                    timeout=10,
                )
                app_resp.raise_for_status()
                app_token = app_resp.json()["app_access_token"]

                resp = httpx.post(
                    f"{FEISHU_BASE}/authen/v1/refresh_access_token",
                    headers={"Authorization": f"Bearer {app_token}"},
                    json={"grant_type": "refresh_token", "refresh_token": refresh_token},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json().get("data", resp.json())
                new_token = data.get("access_token", "")
                new_refresh = data.get("refresh_token", refresh_token)
                new_expires_in = data.get("expires_in", 7200)
                new_expires_at = now + new_expires_in

                if new_token:
                    os.environ["FEISHU_USER_ACCESS_TOKEN"] = new_token
                    os.environ["FEISHU_USER_REFRESH_TOKEN"] = new_refresh
                    os.environ["FEISHU_USER_TOKEN_EXPIRES_AT"] = str(int(new_expires_at))
                    _user_token_cache["token"] = new_token
                    _user_token_cache["expires_at"] = new_expires_at
                    _update_env_user_token(new_token, new_refresh, new_expires_at)
                    return (
                        f"✅ token 状态：已自动续期（新有效期约 {new_expires_in // 60} 分钟）\n"
                        "用户已登录，无需重新授权。续期后可立即使用。"
                    )
            except Exception as e:
                return (
                    f"⚠️ token 已过期，自动续期失败：{e}\n"
                    "需要重新授权，请调用 feishu_oauth_setup(action=\"get_auth_url\")。"
                )

        return (
            "⚠️ token 状态：已过期且无 refresh_token\n"
            "需要重新授权，请调用 feishu_oauth_setup(action=\"get_auth_url\")。"
        )

    if action == "get_auth_url":
        scope = "wiki:wiki docx:document bitable:app im:message:send_as_bot"
        url = (
            f"https://open.feishu.cn/open-apis/authen/v1/authorize"
            f"?app_id={urllib.parse.quote(app_id)}"
            f"&redirect_uri={urllib.parse.quote(_FEISHU_OAUTH_REDIRECT_URI)}"
            f"&scope={urllib.parse.quote(scope)}"
            f"&state=setup"
        )
        return (
            f"请在浏览器中打开以下链接，用飞书账号登录授权：\n\n{url}\n\n"
            f"登录后会跳转到飞书文档页面，请从浏览器地址栏复制 URL 中的 code=xxx 参数值，"
            f"然后调用：feishu_oauth_setup(action=\"exchange_code\", code=\"<从地址栏复制的code>\")"
        )

    if action == "exchange_code":
        if not code:
            return "❌ 请提供 code 参数，示例：feishu_oauth_setup(action=\"exchange_code\", code=\"xxx\")"
        try:
            # 先获取 app_access_token
            app_resp = httpx.post(
                f"{FEISHU_BASE}/auth/v3/app_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
                timeout=10,
            )
            app_resp.raise_for_status()
            app_token = app_resp.json()["app_access_token"]

            resp = httpx.post(
                f"{FEISHU_BASE}/authen/v1/access_token",
                headers={"Authorization": f"Bearer {app_token}"},
                json={"grant_type": "authorization_code", "code": code},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("data", resp.json())
            new_token = data.get("access_token", "")
            new_refresh = data.get("refresh_token", "")
            expires_in = data.get("expires_in", 7200)
            if not new_token:
                return f"❌ 换取 token 失败，飞书返回：{resp.json()}"

            new_expires_at = time.time() + expires_in
            os.environ["FEISHU_USER_ACCESS_TOKEN"] = new_token
            os.environ["FEISHU_USER_REFRESH_TOKEN"] = new_refresh
            os.environ["FEISHU_USER_TOKEN_EXPIRES_AT"] = str(int(new_expires_at))
            _user_token_cache["token"] = new_token
            _user_token_cache["expires_at"] = new_expires_at
            _update_env_user_token(new_token, new_refresh, new_expires_at)

            has_refresh = "✅ refresh_token 已写入，后续自动续期" if new_refresh else "⚠️ 未获得 refresh_token"
            return (
                f"✅ OAuth 授权成功！\n"
                f"- access_token 已写入 .env（有效期约 {expires_in // 60} 分钟）\n"
                f"- {has_refresh}\n"
                f"- wiki 空间权限（131006）应已修复，可立即调用 feishu_wiki_page 验证"
            )
        except Exception as e:
            return f"❌ 换取 token 失败：{e}"

    return f"❌ 未知 action：{action}，支持 check_status / get_auth_url / exchange_code"


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
    get_recent_chat_context,
    query_task_status,
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
        feishu_project_setup,
        feishu_oauth_setup,
    ],
    # 飞书高级工具（Bitable / Task / 搜索 / IM / 日历 / 电子表格 / 群聊）——schema 较重，按需加载
    "feishu_advanced": [
        feishu_bitable_record,
        feishu_bitable_meta,
        feishu_task_task,
        feishu_task_tasklist,
        feishu_search_doc_wiki,
        feishu_im_get_messages,
        feishu_calendar_event,
        feishu_spreadsheet,
        feishu_chat_info,
    ],
    # Claude Code 自迭代 + 自我改进
    "claude": [
        trigger_self_iteration,
        trigger_self_improvement,
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
        "会议", "纪要", "meeting", "会议纪要", "整理会议", "写入飞书", "汇总",
        "项目", "章程", "周报", "里程碑", "需求文档", "技术方案", "风险", "raid",
        "复盘", "项目集", "portfolio", "上线", "验收", "立项",
        "新建项目", "项目初始化", "建立项目", "创建项目", "项目结构",
        "oauth", "授权", "token", "权限", "131006",
    ],
    "feishu_advanced": [
        "多维表格", "bitable", "表格", "任务", "task",
        "全文搜索", "群聊", "消息记录", "im消息",
        "表格记录", "待办", "清单",
        "日历", "日程", "calendar", "会议", "约会", "忙闲", "freebusy",
        "电子表格", "sheet", "spreadsheet",
        "群成员", "chat_id", "用户信息",
    ],
    "claude": [
        "迭代", "开发", "修复", "实现", "编写代码", "重构",
        "claude", "session", "会话", "调试", "自迭代",
        "自我改进", "优化自己", "分析日志", "self-improve", "改进自己",
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
    trigger_daily_migration,
    list_daily_migrations,
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
