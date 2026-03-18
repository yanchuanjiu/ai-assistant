"""
会议纪要分析器：
  1. 用火山云 LLM 分析文档内容，提取结构化信息
  2. 将结果格式化后写入飞书 wiki 专用页面
  3. 可选：为 action items 创建飞书任务
"""
import os
import json
import logging
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)

_PROMPT_PATH = "prompts/meeting_analysis.md"
_prompt_cache: str | None = None


def _get_prompt() -> str:
    global _prompt_cache
    if _prompt_cache is None:
        try:
            with open(_PROMPT_PATH, encoding="utf-8") as f:
                _prompt_cache = f.read()
        except FileNotFoundError:
            _prompt_cache = "分析会议纪要，提取结构化信息，返回 JSON。"
    return _prompt_cache


def analyze(content: str, doc_name: str = "") -> dict | None:
    """
    调用火山云 LLM 分析会议纪要内容。
    返回结构化 dict，或 None（不是会议 / 分析失败）。
    """
    if not content or len(content.strip()) < 50:
        logger.info(f"[MeetingAnalyzer] 文档内容过短，跳过: {doc_name!r}")
        return None

    api_key = os.getenv("VOLCENGINE_API_KEY", "")
    base_url = os.getenv("VOLCENGINE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    model = os.getenv("VOLCENGINE_MODEL", "ep-20260317143459-qtgqn")

    if not api_key:
        logger.error("[MeetingAnalyzer] VOLCENGINE_API_KEY 未配置")
        return None

    text = content[:6000]  # 避免超长
    try:
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "max_tokens": 2048,
                "messages": [
                    {"role": "system", "content": _get_prompt()},
                    {"role": "user", "content": f"文档名称：{doc_name}\n\n{text}"},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # 去掉可能的 markdown 代码块
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        if not data.get("is_meeting"):
            logger.info(f"[MeetingAnalyzer] 非会议文档: {doc_name!r}")
            return None
        return data
    except json.JSONDecodeError as e:
        logger.warning(f"[MeetingAnalyzer] JSON 解析失败 ({doc_name}): {e}")
        return None
    except Exception as e:
        logger.error(f"[MeetingAnalyzer] 分析失败 ({doc_name}): {e}")
        return None


def format_for_feishu(info: dict, doc_url: str = "") -> str:
    """将结构化 meeting info 格式化为飞书 wiki 追加内容。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = info.get("title") or "未命名会议"
    date = info.get("date") or "日期不明"
    participants = "、".join(info.get("participants") or []) or "未记录"
    summary = info.get("summary") or ""
    decisions = info.get("decisions") or []
    action_items = info.get("action_items") or []
    next_steps = info.get("next_steps") or ""

    lines = [
        f"",
        f"---",
        f"## 📋 {title}",
        f"**会议日期**: {date}　　**分析时间**: {now}",
        f"**参与人**: {participants}",
    ]
    if doc_url:
        lines.append(f"**原始文档**: {doc_url}")
    if summary:
        lines += ["", f"**摘要**: {summary}"]
    if decisions:
        lines += ["", "**决策/结论**:"]
        for d in decisions:
            lines.append(f"- {d}")
    if action_items:
        lines += ["", "**待办事项**:"]
        for item in action_items:
            owner = f"（{item['owner']}）" if item.get("owner") else ""
            ddl = f"  截止：{item['deadline']}" if item.get("deadline") else ""
            lines.append(f"- [ ] {item['task']}{owner}{ddl}")
    if next_steps:
        lines += ["", f"**后续跟进**: {next_steps}"]

    return "\n".join(lines)


def write_to_feishu(info: dict, doc_url: str = "") -> str:
    """将分析结果追加到飞书会议纪要页面，返回写入结果描述。"""
    from integrations.storage.config_store import get as cfg_get
    meeting_page = cfg_get("FEISHU_WIKI_MEETING_PAGE") or os.getenv("FEISHU_WIKI_MEETING_PAGE", "")
    if not meeting_page:
        logger.warning("[MeetingAnalyzer] FEISHU_WIKI_MEETING_PAGE 未配置，跳过飞书写入")
        return "FEISHU_WIKI_MEETING_PAGE 未配置，请通过 agent_config 工具设置"

    from integrations.feishu.knowledge import FeishuKnowledge
    content = format_for_feishu(info, doc_url)
    kb = FeishuKnowledge()
    kb.append_to_page(meeting_page, content)
    return meeting_page
