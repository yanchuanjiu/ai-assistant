"""
钉钉知识库（知识库/Wiki）空间操作：
- 列出空间内所有文档节点（支持关键词过滤）
- 读取文档文本内容
"""
import logging
from datetime import datetime
from integrations.dingtalk.client import dt_get, dt_post, _settings, get_current_user_unionid

logger = logging.getLogger(__name__)


class DingTalkDocs:
    def __init__(self, space_id: str = None):
        from integrations.storage.config_store import get as cfg_get
        self.space_id = space_id or cfg_get("DINGTALK_DOCS_SPACE_ID") or _settings.dingtalk_docs_space_id

    def list_recent_files(self, limit: int = 20, keyword: str = None) -> list[dict]:
        """
        列出知识库空间内的文档节点。
        优先使用 /v1.0/wiki/spaces/{spaceId}/nodes 接口。
        keyword: 可选标题关键词过滤（不区分大小写）。
        """
        nodes = self._list_wiki_nodes(limit=limit)
        if nodes is None:
            # fallback: 尝试旧路径
            nodes = self._list_drive_files(limit=limit)
        if nodes is None:
            return []
        if keyword:
            kw = keyword.lower()
            nodes = [n for n in nodes if kw in n.get("name", "").lower()]
        return nodes[:limit]

    def _list_wiki_nodes(self, limit: int = 50) -> list[dict] | None:
        """调用钉钉知识库节点列表 API。"""
        try:
            union_id = get_current_user_unionid()
            params: dict = {"maxResults": limit, "orderBy": "modifiedTime", "order": "desc"}
            if union_id:
                params["unionId"] = union_id
            resp = dt_get(
                f"/v1.0/wiki/spaces/{self.space_id}/nodes",
                params=params,
            )
            logger.debug(f"[wiki/nodes] resp keys={list(resp.keys())}")
            # 可能的字段名：nodes / items / files / data
            nodes_raw = (
                resp.get("nodes")
                or resp.get("items")
                or resp.get("files")
                or resp.get("data", {}).get("nodes")
                or resp.get("data", {}).get("items")
                or []
            )
            return [self._normalize_node(n) for n in nodes_raw]
        except Exception as e:
            logger.warning(f"[wiki/nodes] 失败: {e}")
            return None

    def _list_drive_files(self, limit: int = 50) -> list[dict] | None:
        """Fallback：尝试旧版 drive/spaces 接口。"""
        try:
            union_id = get_current_user_unionid()
            params: dict = {"parentId": "0", "maxResults": limit, "orderBy": "modifiedTime", "order": "desc"}
            if union_id:
                params["unionId"] = union_id
            resp = dt_get(
                f"/v1.0/drive/spaces/{self.space_id}/files",
                params=params,
            )
            files = resp.get("files", [])
            return [self._normalize_node(f) for f in files]
        except Exception as e:
            logger.warning(f"[drive/files] 失败: {e}")
            return None

    def _normalize_node(self, n: dict) -> dict:
        """统一节点字段格式。"""
        return {
            "id": n.get("nodeId") or n.get("fileId") or n.get("id", ""),
            "name": n.get("title") or n.get("fileName") or n.get("name", ""),
            "url": n.get("url", ""),
            "type": n.get("type", ""),
            "updated_at": self._format_ts(n.get("modifiedTime") or n.get("updateTime", "")),
        }

    def read_file_content(self, file_id: str) -> str:
        """读取钉钉文档的纯文本内容。

        优先使用 config_store 中已验证的 DINGTALK_WIKI_API_PATH（wiki 或 drive）。
        若未配置，自动尝试两条路径，成功后将有效路径写入 config_store。
        """
        from integrations.storage.config_store import get as cfg_get, set as cfg_set

        verified = cfg_get("DINGTALK_WIKI_API_PATH")  # "wiki" | "drive" | ""

        paths = [
            ("wiki", f"/v1.0/wiki/nodes/{file_id}/content"),
            ("drive", f"/v1.0/drive/files/{file_id}/content"),
        ]
        # 已验证的路径排在最前
        if verified == "drive":
            paths = [paths[1], paths[0]]

        last_err = None
        for path_key, path in paths:
            try:
                resp = dt_get(path)
                content = resp.get("content", "") or resp.get("text", "")
                # 记录有效路径，避免下次重试
                if verified != path_key:
                    cfg_set("DINGTALK_WIKI_API_PATH", path_key)
                    logger.info(f"[DingTalkDocs] 记录有效 API 路径: {path_key}")
                return content
            except Exception as e:
                logger.warning(f"[{path}] 失败: {e}")
                last_err = e

        logger.error(f"读取钉钉文档 {file_id} 失败: {last_err}")
        return f"读取失败: {last_err}"

    @staticmethod
    def _format_ts(ts) -> str:
        if not ts:
            return ""
        try:
            if isinstance(ts, (int, float)):
                return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
            return str(ts)
        except Exception:
            return str(ts)
