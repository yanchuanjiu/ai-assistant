"""
运行时配置存储：基于 SQLite（data/memory.db），支持 Agent 对话中动态读写配置。
优先级：config_store > .env

常用 key：
  FEISHU_WIKI_MEETING_PAGE  — 飞书会议纪要汇总页面 wiki token
  DINGTALK_DOCS_SPACE_ID    — 钉钉知识库空间 ID
  DINGTALK_WIKI_API_PATH    — 钉钉文档内容读取 API（verified 后写入，如 wiki 或 drive）
"""
import os
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "memory.db"
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_config (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def get(key: str, default: str = "") -> str:
    """读取配置值，不存在时返回 default。"""
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT value FROM agent_config WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else default
    except Exception as e:
        logger.warning(f"[config_store] get({key!r}) failed: {e}")
        return default


def set(key: str, value: str) -> None:
    """写入或更新配置值。"""
    try:
        with _conn() as conn:
            conn.execute(
                """INSERT INTO agent_config (key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, value, datetime.now().isoformat()),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"[config_store] set({key!r}) failed: {e}")


def delete(key: str) -> bool:
    """删除配置项，返回是否存在过。"""
    try:
        with _conn() as conn:
            cur = conn.execute("DELETE FROM agent_config WHERE key = ?", (key,))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"[config_store] delete({key!r}) failed: {e}")
        return False


def list_all() -> dict[str, dict]:
    """列出所有配置项，返回 {key: {value, updated_at}}。"""
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT key, value, updated_at FROM agent_config ORDER BY key"
            ).fetchall()
            return {row[0]: {"value": row[1], "updated_at": row[2]} for row in rows}
    except Exception as e:
        logger.error(f"[config_store] list_all() failed: {e}")
        return {}
