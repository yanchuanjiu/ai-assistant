"""
邮件 → 结构化会议信息提取（纯文本，通过 LLM 解析）。
"""
import json
import logging
from anthropic import Anthropic

logger = logging.getLogger(__name__)
client = Anthropic()

EXTRACT_PROMPT = open("prompts/meeting_extract.md", encoding="utf-8").read() if True else ""


def extract_meeting_info(email: dict) -> dict | None:
    """
    输入一封邮件 dict（subject/sender/date/body），
    返回结构化会议信息，或 None（非会议邮件）。
    """
    try:
        _load_prompt()
        text = f"主题：{email['subject']}\n发件人：{email['sender']}\n日期：{email['date']}\n\n{email['body']}"
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=EXTRACT_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("{"):
            data = json.loads(raw)
            if data.get("is_meeting"):
                return data
        return None
    except Exception as e:
        logger.error(f"会议信息提取失败: {e}")
        return None


_prompt_loaded = False


def _load_prompt():
    global EXTRACT_PROMPT, _prompt_loaded
    if not _prompt_loaded:
        try:
            with open("prompts/meeting_extract.md", encoding="utf-8") as f:
                EXTRACT_PROMPT = f.read()
        except FileNotFoundError:
            EXTRACT_PROMPT = "提取邮件中的会议信息，返回 JSON。"
        _prompt_loaded = True
