"""
会议文档处理记录（SQLite）：避免重复分析同一文档。

表：meeting_docs
  doc_id               TEXT PRIMARY KEY  — DingTalk 文档 ID
  space_id             TEXT              — 所属知识库空间 ID
  doc_name             TEXT              — 文档标题
  analyzed_at          TEXT              — 分析时间（ISO 8601）
  feishu_page          TEXT              — 写入的飞书页面标识（wiki token 或 url）
  project_name         TEXT              — 识别的项目名称
  project_code         TEXT              — 识别的项目代号
  project_folder_token TEXT              — 飞书项目文件夹 wiki token
  raid_written         INTEGER           — 是否已写入 RAID 日志（0/1）
"""
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
_DB = "data/meeting.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB, check_same_thread=False)
    c.execute("""
        CREATE TABLE IF NOT EXISTS meeting_docs (
            doc_id               TEXT PRIMARY KEY,
            space_id             TEXT,
            doc_name             TEXT,
            analyzed_at          TEXT,
            feishu_page          TEXT,
            project_name         TEXT,
            project_code         TEXT,
            project_folder_token TEXT,
            raid_written         INTEGER DEFAULT 0
        )
    """)
    # 幂等迁移：为旧表添加新列
    for col, definition in [
        ("project_name",         "TEXT"),
        ("project_code",         "TEXT"),
        ("project_folder_token", "TEXT"),
        ("raid_written",         "INTEGER DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE meeting_docs ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略
    c.commit()
    return c


def is_processed(doc_id: str) -> bool:
    with _conn() as c:
        row = c.execute("SELECT 1 FROM meeting_docs WHERE doc_id=?", (doc_id,)).fetchone()
        return row is not None


def mark_processed(
    doc_id: str,
    space_id: str,
    doc_name: str,
    feishu_page: str = "",
    project_name: str = "",
    project_code: str = "",
    project_folder_token: str = "",
    raid_written: bool = False,
):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO meeting_docs "
            "(doc_id, space_id, doc_name, analyzed_at, feishu_page, "
            " project_name, project_code, project_folder_token, raid_written)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                doc_id, space_id, doc_name, datetime.now().isoformat(), feishu_page,
                project_name or "", project_code or "", project_folder_token or "",
                1 if raid_written else 0,
            ),
        )
        c.commit()


def list_processed(limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT doc_id, doc_name, analyzed_at, feishu_page, "
            "       project_name, project_code, project_folder_token, raid_written "
            "FROM meeting_docs ORDER BY analyzed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "doc_id": r[0], "doc_name": r[1], "analyzed_at": r[2], "feishu_page": r[3],
            "project_name": r[4], "project_code": r[5],
            "project_folder_token": r[6], "raid_written": bool(r[7]),
        }
        for r in rows
    ]


def unmark(doc_id: str):
    """重置某文档的处理状态（用于强制重新分析）。"""
    with _conn() as c:
        c.execute("DELETE FROM meeting_docs WHERE doc_id=?", (doc_id,))
        c.commit()
