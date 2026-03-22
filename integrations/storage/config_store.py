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


def get_active_topics(chat_id: str = None) -> list[dict]:
    """查询活跃话题，返回 [{chat_id, topic_name, thread_id, last_active}]。

    Args:
        chat_id: 可选，只查询指定聊天窗口的话题；不填返回所有话题。
    """
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_topics (
                chat_id     TEXT NOT NULL,
                topic_name  TEXT NOT NULL,
                thread_id   TEXT NOT NULL,
                last_active TEXT,
                PRIMARY KEY (chat_id, topic_name)
            )
        """)
        if chat_id:
            rows = conn.execute(
                "SELECT chat_id, topic_name, thread_id, last_active FROM chat_topics "
                "WHERE chat_id=? ORDER BY last_active DESC",
                (chat_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT chat_id, topic_name, thread_id, last_active FROM chat_topics "
                "ORDER BY last_active DESC LIMIT 50"
            ).fetchall()
        conn.close()
        return [
            {"chat_id": r[0], "topic_name": r[1], "thread_id": r[2], "last_active": r[3]}
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"[config_store] get_active_topics() failed: {e}")
        return []


def get_recent_sessions(limit: int = 20) -> list[dict]:
    """查询最近活跃的会话（从 LangGraph checkpoints 元数据）。

    Returns: [{thread_id, last_active, msg_count}]
    """
    try:
        conn = sqlite3.connect(_DB_PATH)
        # LangGraph SQLite checkpointer 使用 checkpoints 表
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "checkpoints" not in tables:
            conn.close()
            return []
        rows = conn.execute(
            "SELECT thread_id, MAX(ts) as last_ts, COUNT(*) as cnt "
            "FROM checkpoints GROUP BY thread_id ORDER BY last_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [{"thread_id": r[0], "last_active": r[1], "msg_count": r[2]} for r in rows]
    except Exception as e:
        logger.warning(f"[config_store] get_recent_sessions() failed: {e}")
        return []
