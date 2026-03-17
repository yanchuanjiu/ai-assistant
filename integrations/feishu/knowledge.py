"""
飞书知识库（Wiki）操作：
- 解析 wiki URL/token → obj_token（get_node API）
- 读取 / 追加 / 覆盖页面内容（docx API）

权限说明：
  tenant_access_token 无法调用 wiki spaces list / create nodes API，
  但可以通过 get_node 解析 obj_token 后直接操作 docx。
  前提：在飞书页面的"文档权限"里给应用授予查看/编辑权限。
"""
import re
import logging
from pydantic_settings import BaseSettings
from integrations.feishu.client import feishu_get, feishu_post, feishu_delete

logger = logging.getLogger(__name__)


class KBSettings(BaseSettings):
    feishu_wiki_space_id: str = ""
    feishu_wiki_context_page: str = ""   # 存放 AI 上下文快照的页面 wiki token

    class Config:
        env_file = ".env"
        extra = "ignore"


def parse_wiki_token(url_or_token: str) -> str:
    """
    从飞书 wiki URL 或裸 token 中提取 wiki node token。
    支持格式：
      - https://xxx.feishu.cn/wiki/Qo4nwLphWiWZyfkGAHHcoHwQnEf
      - https://xxx.feishu.cn/wiki/Qo4nwLphWiWZyfkGAHHcoHwQnEf?fromScene=...
      - Qo4nwLphWiWZyfkGAHHcoHwQnEf  （裸 token）
    """
    url_or_token = url_or_token.strip()
    m = re.search(r"/wiki/([A-Za-z0-9]+)", url_or_token)
    if m:
        return m.group(1)
    return url_or_token.split("?")[0]


def wiki_token_to_obj_token(wiki_token: str) -> tuple[str, str]:
    """
    将 wiki node token 转为实际文档 token。
    返回 (obj_token, obj_type)，obj_type 通常是 'docx'。
    """
    resp = feishu_get(
        "/wiki/v2/spaces/get_node",
        params={"token": wiki_token, "obj_type": "wiki"},
    )
    node = resp.get("data", {}).get("node", {})
    return node.get("obj_token", ""), node.get("obj_type", "docx")


class FeishuKnowledge:
    def __init__(self):
        cfg = KBSettings()
        self.space_id = cfg.feishu_wiki_space_id
        self.context_page_wiki_token = cfg.feishu_wiki_context_page

    # ------------------------------------------------------------------ #
    # 读取页面纯文本内容
    # ------------------------------------------------------------------ #
    def read_page(self, wiki_url_or_token: str) -> str:
        """通过 wiki URL 或 token 读取页面纯文本内容。"""
        wiki_token = parse_wiki_token(wiki_url_or_token)
        obj_token, _ = wiki_token_to_obj_token(wiki_token)
        if not obj_token:
            raise ValueError(f"无法解析 wiki token: {wiki_token}")
        resp = feishu_get(f"/docx/v1/documents/{obj_token}/raw_content")
        return resp.get("data", {}).get("content", "")

    # ------------------------------------------------------------------ #
    # 覆盖写入页面（清空后重写）
    # ------------------------------------------------------------------ #
    def overwrite_page(self, wiki_url_or_token: str, content: str):
        """清空页面所有内容，写入新的纯文本。"""
        wiki_token = parse_wiki_token(wiki_url_or_token)
        obj_token, _ = wiki_token_to_obj_token(wiki_token)
        if not obj_token:
            raise ValueError(f"无法解析 wiki token: {wiki_token}")
        self._clear_doc(obj_token)
        self._append_text(obj_token, content)

    # ------------------------------------------------------------------ #
    # 追加内容到页面末尾
    # ------------------------------------------------------------------ #
    def append_to_page(self, wiki_url_or_token: str, content: str):
        """向页面末尾追加文本内容。"""
        wiki_token = parse_wiki_token(wiki_url_or_token)
        obj_token, _ = wiki_token_to_obj_token(wiki_token)
        if not obj_token:
            raise ValueError(f"无法解析 wiki token: {wiki_token}")
        self._append_text(obj_token, content)

    # ------------------------------------------------------------------ #
    # AI 上下文快照专用：覆盖写入 context_page
    # ------------------------------------------------------------------ #
    def create_or_update_page(self, title: str, content: str) -> str:
        """
        写入 AI 上下文快照到预配置的 context page（FEISHU_WIKI_CONTEXT_PAGE）。
        """
        wiki_token = self.context_page_wiki_token
        if not wiki_token:
            raise ValueError(
                "FEISHU_WIKI_CONTEXT_PAGE 未配置，"
                "请在飞书新建一个专用页面并将其 wiki token 填入 .env"
            )
        obj_token, _ = wiki_token_to_obj_token(wiki_token)
        if not obj_token:
            raise ValueError(f"无法解析 context page wiki token: {wiki_token}")
        full_content = f"# {title}\n\n{content}"
        self._clear_doc(obj_token)
        self._append_text(obj_token, full_content)
        return f"https://open.feishu.cn/docx/{obj_token}"

    # ------------------------------------------------------------------ #
    # 搜索（在指定页面列表中检索关键词）
    # ------------------------------------------------------------------ #
    def search(self, query: str, wiki_tokens: list[str] = None) -> list[str]:
        """
        在指定的 wiki token 列表中搜索包含 query 的页面内容。
        wiki_tokens 为空时仅搜索 context_page。
        """
        targets = wiki_tokens or (
            [self.context_page_wiki_token] if self.context_page_wiki_token else []
        )
        results = []
        for wt in targets:
            if not wt:
                continue
            try:
                content = self.read_page(wt)
                if query.lower() in content.lower():
                    results.append(content)
            except Exception as e:
                logger.warning(f"读取页面失败 {wt}: {e}")
        return results

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _clear_doc(self, obj_token: str):
        """删除文档所有子块（清空内容）。"""
        resp = feishu_get(f"/docx/v1/documents/{obj_token}/blocks")
        items = resp.get("data", {}).get("items", [])
        child_count = len(items) - 1   # items[0] 是根块自身
        if child_count <= 0:
            return
        feishu_delete(
            f"/docx/v1/documents/{obj_token}/blocks/{obj_token}/children/batch_delete",
            json={"start_index": 0, "end_index": child_count},
        )

    def _append_text(self, obj_token: str, text: str):
        """向文档末尾追加文本（按换行拆成段落块）。"""
        lines = text.split("\n")
        children = [
            {
                "block_type": 2,
                "text": {
                    "elements": [{"text_run": {"content": line}}],
                    "style": {},
                },
            }
            for line in lines
        ]
        feishu_post(
            f"/docx/v1/documents/{obj_token}/blocks/{obj_token}/children",
            json={"children": children, "index": -1},
        )
