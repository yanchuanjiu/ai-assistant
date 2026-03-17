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
# 飞书知识库
# --------------------------------------------------------------------------- #
@tool
def write_meeting_note(title: str, content: str) -> str:
    """将会议纪要写入飞书知识库。title: 会议标题，content: Markdown 格式正文。"""
    kb = FeishuKnowledge()
    url = kb.create_or_update_page(title=f"[会议] {title}", content=content)
    return f"已写入飞书知识库：{url}"


@tool
def read_feishu_knowledge(query: str) -> str:
    """从飞书知识库检索相关内容。query: 搜索关键词。"""
    kb = FeishuKnowledge()
    results = kb.search(query)
    if not results:
        return "知识库中未找到相关内容。"
    return "\n\n---\n\n".join(results[:3])


@tool
def write_feishu_knowledge(title: str, content: str) -> str:
    """在飞书知识库新建或更新页面。"""
    kb = FeishuKnowledge()
    url = kb.create_or_update_page(title=title, content=content)
    return f"已保存至飞书知识库：{url}"


# --------------------------------------------------------------------------- #
# 钉钉文档（会议纪要）
# --------------------------------------------------------------------------- #
@tool
def get_latest_meeting_docs(limit: int = 5) -> str:
    """从钉钉文档空间获取最新会议纪要列表。"""
    docs = DingTalkDocs()
    items = docs.list_recent_files(limit=limit)
    if not items:
        return "暂无会议文档。"
    lines = [f"- [{d['name']}]({d['url']})  {d['updated_at']}" for d in items]
    return "\n".join(lines)


@tool
def read_meeting_doc(file_id: str) -> str:
    """读取钉钉文档完整文本内容。file_id: 文档 ID。"""
    docs = DingTalkDocs()
    return docs.read_file_content(file_id)


# --------------------------------------------------------------------------- #
# 自迭代：启动本机 Claude Code，全自动执行，回收结果
# --------------------------------------------------------------------------- #
@tool
def trigger_self_iteration(requirement: str) -> str:
    """
    触发 Claude Code 自迭代开发。

    将需求描述传给本机 claude CLI，使用 --dangerously-skip-permissions 跳过
    所有交互确认，自动完成文件编辑、命令执行等操作，返回执行摘要。

    requirement: 清晰的需求描述，包含目标、约束和验收标准。
    """
    logger.info(f"[自迭代] 启动 Claude Code，需求：{requirement[:100]}")

    # 构造完整 prompt，含项目上下文
    prompt = f"""你正在开发 /root/ai-assistant 项目（AI 个人助理）。
请根据以下需求进行开发，直到完成为止：

{requirement}

完成后输出：1) 修改了哪些文件  2) 做了什么  3) 如何验证"""

    cmd = [
        "claude",
        "--dangerously-skip-permissions",  # 自动同意所有操作
        "--print",                          # 非交互模式，输出后退出
        prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
            timeout=600,  # 最长等待 10 分钟
            env={**os.environ, "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", "")},
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            err = result.stderr.strip()[:500]
            logger.error(f"[自迭代] Claude Code 退出码={result.returncode}: {err}")
            return f"Claude Code 执行失败（exit={result.returncode}）：\n{err}"

        logger.info(f"[自迭代] 完成，输出长度={len(output)}")
        return f"Claude Code 自迭代完成：\n\n{output[:3000]}"

    except subprocess.TimeoutExpired:
        return "Claude Code 超时（>10分钟），请检查需求是否过于复杂。"
    except FileNotFoundError:
        return "未找到 claude 命令，请确认 Claude Code CLI 已安装（npm install -g @anthropic-ai/claude-code）。"


# --------------------------------------------------------------------------- #
# 上下文同步
# --------------------------------------------------------------------------- #
@tool
def sync_context_to_feishu() -> str:
    """将本地 SQLite 记忆快照同步到飞书知识库。"""
    ContextSync().push_to_feishu()
    return "本地上下文已同步至飞书知识库。"


# --------------------------------------------------------------------------- #
# 本机 Shell（白名单）
# --------------------------------------------------------------------------- #
SHELL_WHITELIST = (
    "git ", "ls ", "cat ", "pwd", "echo ", "python ",
    "pip ", "df ", "du ", "ps ", "which ", "find ",
)


@tool
def run_shell_command(command: str) -> str:
    """
    在本机执行白名单内的 Shell 命令。
    允许前缀：git / ls / cat / pwd / echo / python / pip / df / du / ps / which / find
    """
    stripped = command.strip()
    if not any(stripped.startswith(p) for p in SHELL_WHITELIST):
        return f"命令被拒绝：'{stripped}'\n允许的前缀：{', '.join(SHELL_WHITELIST)}"
    try:
        result = subprocess.run(
            stripped, shell=True, capture_output=True, text=True,
            timeout=30, cwd=PROJECT_DIR,
        )
        output = (result.stdout or result.stderr or "（无输出）").strip()
        return output[:2000]
    except subprocess.TimeoutExpired:
        return "命令执行超时（>30s）"


ALL_TOOLS = [
    write_meeting_note,
    read_feishu_knowledge,
    write_feishu_knowledge,
    get_latest_meeting_docs,
    read_meeting_doc,
    trigger_self_iteration,
    sync_context_to_feishu,
    run_shell_command,
]
