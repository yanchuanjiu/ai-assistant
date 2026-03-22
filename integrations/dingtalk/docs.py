"""
钉钉知识库（Wiki Workspace）操作 — v2.0 wiki API。

关键概念：
- URL 里的 spaceId（如 r9xmyYP7YK1w1mEO）是展示用 ID，不是 API workspaceId
- API 用 workspaceId（如 Ao01nS92A9VB4B8J）+ rootNodeId 访问节点
- operatorId 必须是用户 unionId（不是 staffId/钉钉号）
"""
import logging
import os
import re
from datetime import datetime
from integrations.dingtalk.client import dt_get, dt_post, _settings

logger = logging.getLogger(__name__)


def _get_operator_id() -> str:
    """返回操作人 unionId（v2.0 wiki API 必填）。"""
    return (
        _settings.dingtalk_operator_id
        or os.getenv("DINGTALK_OPERATOR_ID", "").strip()
    )


class DingTalkDocs:
    def __init__(self, space_id: str = None):
        from integrations.storage.config_store import get as cfg_get
        # space_id 参数保留兼容性，实际用 workspaceId
        self.url_space_id = (
            space_id
            or cfg_get("DINGTALK_DOCS_SPACE_ID")
            or _settings.dingtalk_docs_space_id
        )
        # 优先从 env 读已知 workspaceId，否则运行时发现
        self.workspace_id = (
            os.getenv("DINGTALK_WORKSPACE_ID", "").strip()
            or _settings.dingtalk_workspace_id
            or cfg_get("DINGTALK_WORKSPACE_ID")
            or ""
        )
        self.root_node_id = cfg_get("DINGTALK_ROOT_NODE_ID") or ""

    # ------------------------------------------------------------------ #
    # 公开接口
    # ------------------------------------------------------------------ #
    def list_recent_files(self, limit: int = 20, keyword: str = None) -> list[dict]:
        """列出知识库顶层文档节点（v2.0 wiki nodes API）。"""
        nodes = self._list_wiki_nodes_v2(limit=limit)
        if nodes is None:
            return []
        if keyword:
            kw = keyword.lower()
            nodes = [n for n in nodes if kw in n.get("name", "").lower()]
        return nodes[:limit]

    def list_children(self, parent_node_id: str, limit: int = 50) -> list[dict] | None:
        """列出任意节点的子节点（递归浏览目录结构用）。"""
        operator_id = _get_operator_id()
        if not operator_id:
            logger.warning("[wiki/v2] DINGTALK_OPERATOR_ID 未配置")
            return None
        return self._fetch_nodes(parent_node_id, operator_id, limit=limit)

    # ------------------------------------------------------------------ #
    # 内部：两步流程
    # ------------------------------------------------------------------ #
    def _list_wiki_nodes_v2(self, limit: int = 50) -> list[dict] | None:
        operator_id = _get_operator_id()
        if not operator_id:
            logger.warning(
                "[wiki/v2] DINGTALK_OPERATOR_ID 未配置。"
                "请在 .env 添加 DINGTALK_OPERATOR_ID=<unionId>（当前 unionId: 0DyEwX7Zw3HfhffedWPiSJAiEiE）"
            )
            return None

        # 确保有 rootNodeId
        root = self._ensure_root_node_id(operator_id)
        if not root:
            return None

        return self._fetch_nodes(root, operator_id, limit=limit)

    def _ensure_root_node_id(self, operator_id: str) -> str | None:
        """确保 workspace_id 和 root_node_id 已初始化（懒加载 + 缓存）。"""
        from integrations.storage.config_store import set as cfg_set

        if self.root_node_id:
            return self.root_node_id

        # 如果没有 workspaceId，先列出所有 workspaces 找匹配的
        if not self.workspace_id:
            self.workspace_id = self._discover_workspace_id(operator_id)
            if self.workspace_id:
                cfg_set("DINGTALK_WORKSPACE_ID", self.workspace_id)
                os.environ["DINGTALK_WORKSPACE_ID"] = self.workspace_id

        if not self.workspace_id:
            logger.warning("[wiki/v2] 无法确定 workspaceId")
            return None

        root = self._get_root_node_id(operator_id, self.workspace_id)
        if root:
            self.root_node_id = root
            cfg_set("DINGTALK_ROOT_NODE_ID", root)
        return root

    def _discover_workspace_id(self, operator_id: str) -> str | None:
        """列出所有 workspaces，找到 URL 匹配 url_space_id 的那个。"""
        try:
            resp = dt_get(
                "/v2.0/wiki/workspaces",
                params={"operatorId": operator_id, "maxResults": 50},
            )
            workspaces = resp.get("workspaces") or []
            for ws in workspaces:
                url = ws.get("url", "")
                wid = ws.get("workspaceId", "")
                # 匹配 URL 中的 spaceId 片段
                if self.url_space_id and self.url_space_id in url:
                    logger.info(f"[wiki/v2] 发现 workspaceId={wid}（URL 匹配 {self.url_space_id}）")
                    return wid
            # 只有一个时直接用
            if len(workspaces) == 1:
                wid = workspaces[0].get("workspaceId", "")
                logger.info(f"[wiki/v2] 唯一 workspace，使用 workspaceId={wid}")
                return wid
            logger.warning(f"[wiki/v2] 未找到匹配 {self.url_space_id} 的 workspace，共 {len(workspaces)} 个")
            return None
        except Exception as e:
            logger.warning(f"[wiki/v2] 列举 workspaces 失败: {e}")
            return None

    def _get_root_node_id(self, operator_id: str, workspace_id: str) -> str | None:
        """从 workspace 详情中获取 rootNodeId。"""
        try:
            resp = dt_get(
                f"/v2.0/wiki/workspaces/{workspace_id}",
                params={"operatorId": operator_id},
            )
            # 响应可能嵌套在 workspace / result / data key 下
            ws_obj = resp.get("workspace") or resp.get("result") or resp.get("data") or resp
            root = ws_obj.get("rootNodeId") if isinstance(ws_obj, dict) else None
            if root:
                logger.info(f"[wiki/v2] rootNodeId={root}")
            else:
                logger.warning(f"[wiki/v2] workspace 响应无 rootNodeId: {resp}")
            return root
        except Exception as e:
            logger.warning(f"[wiki/v2] 获取 workspace 详情失败: {e}")
            return None

    def _fetch_nodes(self, parent_node_id: str, operator_id: str, limit: int = 50) -> list[dict] | None:
        """列出指定节点下的子节点。"""
        try:
            resp = dt_get(
                "/v2.0/wiki/nodes",
                params={
                    "parentNodeId": parent_node_id,
                    "operatorId": operator_id,
                    "maxResults": min(limit, 50),
                    "orderBy": "MODIFIED_TIME_DESC",
                },
            )
            nodes_raw = (
                resp.get("nodes")
                or resp.get("items")
                or (resp.get("result") or {}).get("nodes")
                or (resp.get("data") or {}).get("nodes")
            )
            if nodes_raw is None and isinstance(resp, list):
                nodes_raw = resp
            if not nodes_raw:
                logger.info(f"[wiki/v2] parentNodeId={parent_node_id} 下无子节点")
                return []
            logger.info(f"[wiki/v2] parentNodeId={parent_node_id} 返回 {len(nodes_raw)} 个节点")
            return [self._normalize_node(n) for n in nodes_raw]
        except Exception as e:
            logger.warning(f"[wiki/v2] 获取节点列表失败: {e}")
            return None

    def _normalize_node(self, n: dict) -> dict:
        node_id = n.get("nodeId") or n.get("id", "")
        url = n.get("url", "")
        if not url and node_id:
            url = f"https://alidocs.dingtalk.com/i/nodes/{node_id}"
        return {
            "id": node_id,
            "object_id": n.get("objectId") or n.get("docId") or "",
            "name": n.get("name") or n.get("title", ""),
            "url": url,
            "type": n.get("type") or n.get("nodeType", ""),
            "has_child": bool(n.get("hasChildren") or n.get("hasChild")),
            "created_at": self._format_ts(n.get("createTime") or n.get("createdTime", "")),
            "updated_at": self._format_ts(n.get("modifiedTime") or n.get("updateTime", "")),
        }

    # ------------------------------------------------------------------ #
    # 读取文档内容
    # ------------------------------------------------------------------ #
    @staticmethod
    def extract_node_id_from_url(url_or_id: str) -> str:
        """从钉钉文档 URL 提取 nodeId，或直接返回 ID。

        支持格式：
          https://alidocs.dingtalk.com/i/nodes/{nodeId}
          https://docs.dingtalk.com/i/nodes/{nodeId}
        """
        m = re.search(r'dingtalk\.com/[^/]+/nodes/([A-Za-z0-9_\-]+)', url_or_id)
        if m:
            return m.group(1)
        return url_or_id.strip()

    def read_file_content(self, file_id: str) -> str:
        """读取钉钉文档的纯文本内容。支持 nodeId 或文档 URL。"""
        node_id = self.extract_node_id_from_url(file_id)
        if node_id != file_id:
            logger.info(f"[DingTalkDocs] 从 URL 提取 nodeId: {node_id}")

        operator_id = _get_operator_id()
        params = {"operatorId": operator_id} if operator_id else {}

        paths = [
            f"/v2.0/wiki/nodes/{node_id}/documentContent",
            f"/v2.0/wiki/nodes/{node_id}/content",
        ]
        for path in paths:
            try:
                resp = dt_get(path, params=params)
                content = (
                    resp.get("content")
                    or resp.get("documentContent")
                    or resp.get("text")
                    or (resp.get("data") or {}).get("content")
                    or ""
                )
                if content:
                    return content
            except Exception as e:
                logger.debug(f"[read_content] {path} 失败: {e}")

        return (
            f"读取失败（nodeId={node_id}）\n"
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
