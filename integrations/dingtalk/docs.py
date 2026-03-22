"""
钉钉知识库（Wiki Workspace）操作：
- 列出知识库工作空间内的文档节点（/v2.0/wiki/workspaces + /v2.0/wiki/nodes）
- 读取文档文本内容（支持 nodeId 或 docs.dingtalk.com URL）
"""
import logging
import os
import re
from datetime import datetime
from integrations.dingtalk.client import dt_get, dt_post, _settings

logger = logging.getLogger(__name__)


def _get_operator_id() -> str:
    """返回操作人 unionId（v2.0 wiki API 必填）。
    优先读取 DINGTALK_OPERATOR_ID，其次 DINGTALK_UNION_ID。
    """
    uid = (
        os.getenv("DINGTALK_OPERATOR_ID", "").strip()
        or os.getenv("DINGTALK_UNION_ID", "").strip()
    )
    return uid


class DingTalkDocs:
    def __init__(self, space_id: str = None):
        from integrations.storage.config_store import get as cfg_get
        self.workspace_id = (
            space_id
            or cfg_get("DINGTALK_DOCS_SPACE_ID")
            or _settings.dingtalk_docs_space_id
        )

    # ------------------------------------------------------------------ #
    # 公开接口
    # ------------------------------------------------------------------ #
    def list_recent_files(self, limit: int = 20, keyword: str = None) -> list[dict]:
        """列出知识库工作空间顶层文档节点。

        正确流程（v2.0 wiki API）：
          1. GET /v2.0/wiki/workspaces/{workspaceId}?operatorId=xxx → 取 rootNodeId
          2. GET /v2.0/wiki/nodes?parentNodeId={rootNodeId}&operatorId=xxx → 列节点

        operatorId 需在 .env 中配置 DINGTALK_OPERATOR_ID（用户 unionId）。
        """
        nodes = self._list_wiki_nodes_v2(limit=limit)
        if nodes is None:
            return []
        if keyword:
            kw = keyword.lower()
            nodes = [n for n in nodes if kw in n.get("name", "").lower()]
        return nodes[:limit]

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    def _list_wiki_nodes_v2(self, limit: int = 50) -> list[dict] | None:
        """使用 /v2.0/wiki API 两步列出知识库节点。"""
        operator_id = _get_operator_id()
        if not operator_id:
            logger.warning(
                "[wiki/v2] DINGTALK_OPERATOR_ID 未配置，无法调用 v2.0 wiki API。"
                "请在 .env 中添加 DINGTALK_OPERATOR_ID=<你的 unionId>。"
                "获取方法：钉钉 → 个人主页 → 更多 → 复制 unionId，或联系管理员从开发者后台查询。"
            )
            return None

        # Step 1: 获取 workspace，拿 rootNodeId
        root_node_id = self._get_root_node_id(operator_id)
        if not root_node_id:
            return None

        # Step 2: 列出 rootNodeId 下的子节点
        return self._fetch_nodes(root_node_id, operator_id, limit=limit)

    def _get_root_node_id(self, operator_id: str) -> str | None:
        """从 workspace 详情中获取 rootNodeId。"""
        try:
            resp = dt_get(
                f"/v2.0/wiki/workspaces/{self.workspace_id}",
                params={"operatorId": operator_id, "withPermissionRole": "false"},
            )
            logger.info(f"[wiki/workspace] resp preview={str(resp)[:300]}")
            root = (
                resp.get("rootNodeId")
                or (resp.get("result") or {}).get("rootNodeId")
                or (resp.get("data") or {}).get("rootNodeId")
            )
            if root:
                logger.info(f"[wiki/workspace] rootNodeId={root}")
                return root
            logger.warning(f"[wiki/workspace] 未找到 rootNodeId，完整响应: {resp}")
            return None
        except Exception as e:
            logger.warning(f"[wiki/workspace] 获取 workspace 失败: {e}")
            return None

    def _fetch_nodes(
        self, parent_node_id: str, operator_id: str, limit: int = 50
    ) -> list[dict] | None:
        """列出指定 parentNodeId 下的子节点。"""
        try:
            params = {
                "parentNodeId": parent_node_id,
                "operatorId": operator_id,
                "maxResults": min(limit, 50),
                "orderBy": "MODIFIED_TIME_DESC",
            }
            resp = dt_get("/v2.0/wiki/nodes", params=params)
            logger.info(f"[wiki/nodes] resp preview={str(resp)[:400]}")
            nodes_raw = (
                resp.get("nodes")
                or resp.get("items")
                or (resp.get("result") or {}).get("nodes")
                or (resp.get("data") or {}).get("nodes")
            )
            if nodes_raw is None and isinstance(resp, list):
                nodes_raw = resp
            if not nodes_raw:
                logger.warning(f"[wiki/nodes] 未解析到节点，完整响应: {resp}")
                return []
            return [self._normalize_node(n) for n in nodes_raw]
        except Exception as e:
            logger.warning(f"[wiki/nodes] 获取节点列表失败: {e}")
            return None

    def list_children(self, parent_node_id: str, limit: int = 50) -> list[dict] | None:
        """列出任意节点的子节点（可用于递归浏览知识库目录结构）。"""
        operator_id = _get_operator_id()
        if not operator_id:
            logger.warning("[wiki/v2] DINGTALK_OPERATOR_ID 未配置")
            return None
        return self._fetch_nodes(parent_node_id, operator_id, limit=limit)

    def _normalize_node(self, n: dict) -> dict:
        """统一节点字段格式。"""
        node_id = n.get("nodeId") or n.get("fileId") or n.get("id", "")
        # docs.dingtalk.com URL
        url = n.get("url", "")
        if not url and node_id:
            url = f"https://docs.dingtalk.com/i/nodes/{node_id}"
        return {
            "id": node_id,
            "object_id": n.get("objectId") or n.get("docId") or n.get("objId") or "",
            "name": n.get("title") or n.get("name") or n.get("fileName", ""),
            "url": url,
            "type": n.get("type") or n.get("nodeType", ""),
            "has_child": bool(n.get("hasChild") or n.get("subNodeCount", 0)),
            "created_at": self._format_ts(
                n.get("createTime") or n.get("createdTime") or n.get("createAt", "")
            ),
            "updated_at": self._format_ts(
                n.get("modifiedTime") or n.get("updateTime", "")
            ),
        }

    # ------------------------------------------------------------------ #
    # 读取文档内容
    # ------------------------------------------------------------------ #
    @staticmethod
    def extract_node_id_from_url(url_or_id: str) -> str:
        """从钉钉文档 URL 提取节点 ID，或直接返回 ID。

        支持格式：
          https://docs.dingtalk.com/i/nodes/{nodeId}
          https://alidocs.dingtalk.com/i/nodes/{nodeId}?...
          直接传 nodeId 字符串
        """
        # docs.dingtalk.com 新版 URL
        m = re.search(r'docs\.dingtalk\.com/i/nodes/([A-Za-z0-9_\-]+)', url_or_id)
        if m:
            return m.group(1)
        # alidocs 旧版 URL
        m = re.search(r'alidocs\.dingtalk\.com/[^/]+/nodes/([A-Za-z0-9_\-]+)', url_or_id)
        if m:
            return m.group(1)
        return url_or_id.strip()

    def read_file_content(self, file_id: str) -> str:
        """读取钉钉文档的纯文本内容（v2.0 wiki nodes content API）。

        支持传入文档 nodeId 或 docs.dingtalk.com / alidocs URL。
        """
        node_id = self.extract_node_id_from_url(file_id)
        if node_id != file_id:
            logger.info(f"[DingTalkDocs] 从 URL 提取 nodeId: {node_id}")

        operator_id = _get_operator_id()
        params = {"operatorId": operator_id} if operator_id else {}

        # v2.0 wiki 节点内容接口
        content_paths = [
            f"/v2.0/wiki/nodes/{node_id}/documentContent",
            f"/v2.0/wiki/nodes/{node_id}/content",
            f"/v1.0/doc/nodes/{node_id}/content",
        ]

        last_err = None
        for path in content_paths:
            try:
                resp = dt_get(path, params=params)
                logger.info(f"[read_content] path={path} preview={str(resp)[:300]}")
                content = (
                    resp.get("content")
                    or resp.get("text")
                    or resp.get("documentContent")
                    or (resp.get("data") or {}).get("content")
                    or (resp.get("data") or {}).get("text")
                    or (resp.get("result") or {}).get("content")
                    or ""
                )
                if content:
                    return content
                logger.debug(f"[read_content] {path} 响应无内容字段: {resp}")
            except Exception as e:
                logger.debug(f"[read_content] {path} 失败: {e}")
                last_err = e

        logger.error(f"读取钉钉文档 {node_id} 失败: {last_err}")
        return (
            f"读取失败（nodeId={node_id}）: {last_err}\n"
            f"提示：可改用 MCP 工具 get_document_content(docId='{node_id}') 读取。"
        )

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
