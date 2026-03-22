"""火山云 Ark 文本格式工具调用转换 Hook。

火山云 Ark 有时以文本形式返回工具调用，格式为：
  <|FunctionCallBegin|>[...] 或 <|FunctionCallBeginBegin|>[...]（双 Begin 变体）
  也可能缺少 Begin 标记：[...]<|FunctionCallEnd|>

本 hook 将其转换为标准 LangChain AIMessage.tool_calls 格式。
注册方式：在 graph/nodes.py 模块级别 register_llm_hook(volcengine_text_tool_call_hook)
"""
import re
import json
import logging
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

_FUNC_CALL_RE = re.compile(
    r"<\|FunctionCallBegin(?:Begin)?\|>(.*?)(?:<\|FunctionCallEnd(?:End)?\|>|$)",
    re.DOTALL,
)
_FUNC_CALL_NO_BEGIN_RE = re.compile(
    r"(\[.*?\])\s*<\|FunctionCallEnd(?:End)?\|>",
    re.DOTALL,
)


def _parse_func_call_json(content: str) -> list[dict] | None:
    match = _FUNC_CALL_RE.search(content)
    if not match:
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


def volcengine_text_tool_call_hook(response: AIMessage) -> AIMessage:
    """将火山云 <|FunctionCallBegin|> 文本格式转换为标准 tool_calls。"""
    if not (
        isinstance(response.content, str)
        and "<|FunctionCall" in response.content
        and not getattr(response, "tool_calls", None)
    ):
        return response

    tool_calls = _parse_func_call_json(response.content)
    if tool_calls:
        logger.debug(f"[VolcEngine Hook] 解析文本格式工具调用: {[c['name'] for c in tool_calls]}")
        return AIMessage(content="", tool_calls=tool_calls)
    logger.warning(f"[VolcEngine Hook] 解析失败，原始内容: {response.content[:300]}")
    return AIMessage(content="（工具调用格式异常，请重试）")
