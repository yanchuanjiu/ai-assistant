"""
工具函数，注册为 LangGraph tools，供 agent nodes 调用。
"""
import os
import subprocess
import logging
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
    # 系统
    trigger_self_iteration,
    run_command,
]
