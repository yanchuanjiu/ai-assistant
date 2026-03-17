"""
钉钉文档空间操作：
- 列出最新文件（会议纪要）
- 读取文档文本内容
"""
import logging
from datetime import datetime
from integrations.dingtalk.client import dt_get, dt_post, _settings

logger = logging.getLogger(__name__)


class DingTalkDocs:
    def __init__(self):
        self.space_id = _settings.dingtalk_docs_space_id

    def list_recent_files(self, limit: int = 10) -> list[dict]:
        """列出空间内最近更新的文件，按更新时间倒序。"""
        try:
            resp = dt_get(
                f"/v1.0/drive/spaces/{self.space_id}/files",
                params={"parentId": "0", "maxResults": limit, "orderBy": "modifiedTime", "order": "desc"},
            )
            files = resp.get("files", [])
            return [
                {
                    "id": f.get("fileId") or f.get("id", ""),
                    "name": f.get("fileName") or f.get("name", ""),
                    "url": f.get("url", ""),
                    "updated_at": self._format_ts(f.get("modifiedTime", "")),
                }
                for f in files
            ]
        except Exception as e:
            logger.error(f"列出钉钉文档失败: {e}")
            return []

    def read_file_content(self, file_id: str) -> str:
        """读取钉钉文档的纯文本内容。"""
        try:
            resp = dt_get(f"/v1.0/drive/files/{file_id}/content")
            return resp.get("content", "") or resp.get("text", "")
        except Exception as e:
            logger.error(f"读取钉钉文档 {file_id} 失败: {e}")
            return f"读取失败: {e}"

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
