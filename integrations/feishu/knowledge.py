"""
飞书知识库（Wiki）操作：
- 列出空间节点
- 创建/更新页面
- 搜索页面内容
"""
import logging
from pydantic_settings import BaseSettings
from integrations.feishu.client import feishu_get, feishu_post

logger = logging.getLogger(__name__)


class KBSettings(BaseSettings):
    feishu_wiki_space_id: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


class FeishuKnowledge:
    def __init__(self):
        self.space_id = KBSettings().feishu_wiki_space_id

    # ------------------------------------------------------------------ #
    # 列出空间顶层节点
    # ------------------------------------------------------------------ #
    def list_nodes(self) -> list[dict]:
        resp = feishu_get(f"/wiki/v2/spaces/{self.space_id}/nodes")
        items = resp.get("data", {}).get("items", [])
        return [{"title": i["title"], "node_token": i["node_token"]} for i in items]

    # ------------------------------------------------------------------ #
    # 创建或更新 Wiki 页面
    # 若同名页面已存在则更新其文档内容，否则新建。
    # ------------------------------------------------------------------ #
    def create_or_update_page(self, title: str, content: str) -> str:
        existing = self._find_node_by_title(title)
        if existing:
            doc_token = existing.get("obj_token", "")
            self._update_doc(doc_token, content)
            return f"https://open.feishu.cn/docx/{doc_token}"

        # 新建 Wiki 节点（类型 doc）
        resp = feishu_post(
            f"/wiki/v2/spaces/{self.space_id}/nodes",
            json={"obj_type": "doc", "title": title},
        )
        node = resp.get("data", {}).get("node", {})
        doc_token = node.get("obj_token", "")
        if doc_token:
            self._update_doc(doc_token, content)
        return f"https://open.feishu.cn/docx/{doc_token}"

    # ------------------------------------------------------------------ #
    # 搜索（简单：列出所有节点标题匹配）
    # ------------------------------------------------------------------ #
    def search(self, query: str) -> list[str]:
        nodes = self.list_nodes()
        results = []
        for n in nodes:
            if query.lower() in n["title"].lower():
                try:
                    content = self._read_doc(n["node_token"])
                    results.append(f"## {n['title']}\n{content}")
                except Exception as e:
                    logger.warning(f"读取文档失败 {n['node_token']}: {e}")
        return results

    # ------------------------------------------------------------------ #
    # 内部：读取 Doc 原始内容
    # ------------------------------------------------------------------ #
    def _read_doc(self, node_token: str) -> str:
        resp = feishu_get(f"/docx/v1/documents/{node_token}/raw_content")
        return resp.get("data", {}).get("content", "")

    def _update_doc(self, doc_token: str, markdown: str):
        """用批量更新 API 将 Markdown 写入文档（简化：整体替换为纯文本块）。"""
        blocks = [
            {
                "block_type": 2,  # 段落
                "paragraph": {
                    "elements": [{"type": 0, "text_run": {"content": markdown}}]
                },
            }
        ]
        feishu_post(
            f"/docx/v1/documents/{doc_token}/blocks/batch_update",
            json={"requests": [{"replace_children": {"blocks": blocks}}]},
        )

    def _find_node_by_title(self, title: str) -> dict | None:
        nodes_resp = feishu_get(f"/wiki/v2/spaces/{self.space_id}/nodes")
        for item in nodes_resp.get("data", {}).get("items", []):
            if item["title"] == title:
                return item
        return None
