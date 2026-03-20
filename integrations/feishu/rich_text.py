"""
Markdown → 飞书 docx 富文本块转换器。

将 Markdown 文本转换为飞书 docx API 的块（block）结构列表，
用于 append_blocks_to_page() 写入飞书知识库页面。

支持：
  - 标题（H1-H6 → heading1-heading6）
  - 加粗、斜体、行内代码、删除线
  - 无序列表（- / * / +）+ 复选框（[ ] / [x]）
  - 有序列表（1. 2. ...）
  - 代码块（```lang ... ```）
  - 分割线（---）
  - 普通段落（含内联样式）
  - 引用块（> text → 缩进段落）
"""

import re
from typing import List, Dict, Any

Block = Dict[str, Any]
Element = Dict[str, Any]


# --------------------------------------------------------------------------- #
# 内联元素构造
# --------------------------------------------------------------------------- #

def _text_run(
    text: str,
    bold: bool = False,
    italic: bool = False,
    inline_code: bool = False,
    strikethrough: bool = False,
) -> Element:
    """构造单个 text_run 元素。"""
    style: Dict[str, Any] = {}
    if bold:
        style["bold"] = True
    if italic:
        style["italic"] = True
    if inline_code:
        style["inline_code"] = True
    if strikethrough:
        style["strikethrough"] = True
    run: Dict[str, Any] = {"content": text}
    if style:
        run["text_element_style"] = style
    return {"text_run": run}


# 正则：依次识别 ***bold+italic*** / **bold** / *italic* / `code` / ~~strike~~ / [link](url) / plain
_INLINE_RE = re.compile(
    r"\*\*\*(.+?)\*\*\*"   # bold+italic
    r"|\*\*(.+?)\*\*"       # bold
    r"|__(.+?)__"           # bold (alt)
    r"|\*(.+?)\*"           # italic
    r"|_(.+?)_"             # italic (alt)
    r"|`(.+?)`"             # inline code
    r"|~~(.+?)~~"           # strikethrough
    r"|\[([^\]]+)\]\([^)]+\)"  # link → display text only
    r"|([^*_`~\[]+)",       # plain text
    re.DOTALL,
)


def parse_inline(text: str) -> List[Element]:
    """解析行内 Markdown 样式，返回 text_elements 列表。"""
    elements: List[Element] = []
    for m in _INLINE_RE.finditer(text):
        g = m.groups()
        if g[0]:    # ***bold+italic***
            elements.append(_text_run(g[0], bold=True, italic=True))
        elif g[1]:  # **bold**
            elements.append(_text_run(g[1], bold=True))
        elif g[2]:  # __bold__
            elements.append(_text_run(g[2], bold=True))
        elif g[3]:  # *italic*
            elements.append(_text_run(g[3], italic=True))
        elif g[4]:  # _italic_
            elements.append(_text_run(g[4], italic=True))
        elif g[5]:  # `code`
            elements.append(_text_run(g[5], inline_code=True))
        elif g[6]:  # ~~strike~~
            elements.append(_text_run(g[6], strikethrough=True))
        elif g[7]:  # [link](url) → show link text
            elements.append(_text_run(g[7]))
        elif g[8]:  # plain text
            elements.append(_text_run(g[8]))
    if not elements:
        elements.append(_text_run(text))
    return elements


# --------------------------------------------------------------------------- #
# 块构造辅助
# --------------------------------------------------------------------------- #

def _block(block_type: int, key: str, elements: List[Element], style: dict = None) -> Block:
    return {
        "block_type": block_type,
        key: {
            "elements": elements,
            "style": style or {},
        },
    }


def _text_block(elements: List[Element]) -> Block:
    return _block(2, "text", elements)


def _heading_block(level: int, text: str) -> Block:
    """level: 1-6，飞书 block_type 3-8 对应 heading1-heading6。"""
    level = max(1, min(level, 6))
    return _block(2 + level, f"heading{level}", parse_inline(text))


def _bullet_block(elements: List[Element]) -> Block:
    return _block(13, "bullet", elements)


def _ordered_block(elements: List[Element]) -> Block:
    return _block(12, "ordered", elements)


def _code_block(code: str, lang: str = "") -> Block:
    """代码块。lang 为空或不认识时降级为 PlainText(1)。"""
    _LANG_MAP = {
        "python": 49, "py": 49,
        "javascript": 20, "js": 20,
        "typescript": 47, "ts": 47,
        "java": 21, "go": 22, "rust": 23,
        "c": 24, "cpp": 25, "c++": 25,
        "shell": 4, "bash": 4, "sh": 4,
        "sql": 26, "json": 14,
        "yaml": 27, "yml": 27,
        "xml": 28, "html": 29,
        "markdown": 1, "md": 1, "": 1,
    }
    lang_code = _LANG_MAP.get(lang.lower().strip(), 1)
    return {
        "block_type": 14,
        "code": {
            "elements": [{"text_run": {"content": code}}],
            "style": {"language": lang_code, "wrap": True},
        },
    }


def _divider_block() -> Block:
    return {"block_type": 24, "divider": {}}


# --------------------------------------------------------------------------- #
# 主转换函数
# --------------------------------------------------------------------------- #

def md_to_feishu_blocks(markdown: str) -> List[Block]:
    """
    将 Markdown 字符串转换为飞书 docx API 块列表。

    返回的每个元素可直接作为 children 传给
    POST /docx/v1/documents/{doc_id}/blocks/{block_id}/children。
    """
    if not markdown:
        return []

    blocks: List[Block] = []
    lines = markdown.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 空行 → 空段落（保持视觉间距）
        if not stripped:
            blocks.append(_text_block([_text_run("")]))
            i += 1
            continue

        # 分割线：--- / *** / ___ / ===
        if re.match(r"^[-*_=]{3,}$", stripped) and len(set(stripped)) == 1:
            blocks.append(_divider_block())
            i += 1
            continue

        # 标题 H1-H6：# ~ ######
        h = re.match(r"^(#{1,6})\s+(.+)", line)
        if h:
            level = len(h.group(1))
            blocks.append(_heading_block(level, h.group(2).strip()))
            i += 1
            continue

        # 代码块（围栏式）
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            code_lines: List[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # 跳过结尾 ```
            blocks.append(_code_block("\n".join(code_lines), lang))
            continue

        # 引用块 > text → 斜体段落
        if stripped.startswith("> "):
            quote_text = stripped[2:]
            blocks.append(_text_block(parse_inline(f"「{quote_text}」")))
            i += 1
            continue

        # 无序列表（- / * / +）含复选框
        ul = re.match(r"^(\s*)[*\-+]\s+(.*)", line)
        if ul:
            text = ul.group(2)
            if text.startswith("[ ] "):
                text = "☐ " + text[4:]
            elif re.match(r"^\[x\] ", text, re.IGNORECASE):
                text = "☑ " + text[4:]
            blocks.append(_bullet_block(parse_inline(text)))
            i += 1
            continue

        # 有序列表 1. / 2. ...
        ol = re.match(r"^\s*\d+\.\s+(.*)", line)
        if ol:
            blocks.append(_ordered_block(parse_inline(ol.group(1))))
            i += 1
            continue

        # 普通段落（含内联样式）
        blocks.append(_text_block(parse_inline(line)))
        i += 1

    return blocks
