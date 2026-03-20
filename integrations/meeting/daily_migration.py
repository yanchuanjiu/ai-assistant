"""
每日会议纪要迁移插件（DailyMigrationPlugin）。

功能：
  1. 每天自动执行一次（由 scheduler.py 注册 daily job）
  2. 提取钉钉文档原始创建/修改时间，写入飞书时显示原始时间而非迁移时间
  3. 将 Markdown 格式转换为飞书富文本块（heading / bullet / code / divider 等）
  4. 按项目自动路由到 04_会议纪要 子页面
  5. 独立状态跟踪（data/daily_migration.db），不影响 30 分钟轮询的 tracker

可配置项（通过 agent_config 工具在 IM 中设置，无需重启）：
  DAILY_MIGRATION_LOOKBACK_DAYS  — 回溯天数（默认 7）
  DAILY_MIGRATION_PROJECT_MAP    — JSON 字典 {"关键词": "项目代码"}，用于手动指定映射
  DAILY_MIGRATION_RUN_HOUR       — 每天几点执行（默认 8，即 08:00），scheduler 注册时读取
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = "data/daily_migration.db"


# --------------------------------------------------------------------------- #
# 状态持久化（独立 SQLite 表，与 meeting tracker 互不干扰）
# --------------------------------------------------------------------------- #

def _get_conn() -> sqlite3.Connection:
    Path("data").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS migrated_docs (
            doc_id       TEXT PRIMARY KEY,
            doc_name     TEXT,
            original_time TEXT,
            feishu_page  TEXT,
            migrated_at  TEXT
        )
    """)
    conn.commit()
    return conn


def is_migrated(doc_id: str) -> bool:
    """检查文档是否已被本插件处理过（富文本格式写入）。"""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM migrated_docs WHERE doc_id=?", (doc_id,)
        ).fetchone()
        return row is not None


def mark_migrated(doc_id: str, doc_name: str, original_time: str, feishu_page: str):
    """记录已迁移文档。"""
    with _get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO migrated_docs
               (doc_id, doc_name, original_time, feishu_page, migrated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                doc_id,
                doc_name,
                original_time,
                feishu_page,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )


def list_migrated(limit: int = 20) -> list[dict]:
    """列出最近已迁移的文档记录。"""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT doc_id, doc_name, original_time, feishu_page, migrated_at "
            "FROM migrated_docs ORDER BY migrated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "doc_id": r[0],
                "doc_name": r[1],
                "original_time": r[2],
                "feishu_page": r[3],
                "migrated_at": r[4],
            }
            for r in rows
        ]


# --------------------------------------------------------------------------- #
# 插件主类
# --------------------------------------------------------------------------- #

class DailyMigrationPlugin:
    """
    每日会议纪要迁移插件。

    调用 run() 执行单次迁移（供 scheduler 和手动触发工具调用）。
    """

    def __init__(self):
        from integrations.storage.config_store import get as cfg_get

        # 回溯天数
        try:
            self.lookback_days = int(cfg_get("DAILY_MIGRATION_LOOKBACK_DAYS") or "7")
        except ValueError:
            self.lookback_days = 7

        # 手动项目映射 {"关键词": "项目代码"}
        raw_map = cfg_get("DAILY_MIGRATION_PROJECT_MAP") or "{}"
        try:
            self.project_map: dict[str, str] = json.loads(raw_map)
        except Exception:
            self.project_map = {}

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #

    def run(self) -> str:
        """
        执行每日迁移。返回执行摘要字符串。
        """
        from integrations.dingtalk.docs import DingTalkDocs
        from integrations.meeting import analyzer

        logger.info("[DailyMigration] 开始每日会议纪要迁移...")

        try:
            docs = DingTalkDocs()
            items = docs.list_recent_files(limit=100)
        except Exception as e:
            logger.error(f"[DailyMigration] 获取钉钉文档列表失败: {e}")
            return f"每日迁移失败（获取文档列表）：{e}"

        cutoff = datetime.now() - timedelta(days=self.lookback_days)
        processed = skipped = errors = 0

        for item in items:
            doc_id = item.get("id", "")
            doc_name = item.get("name", "")
            # 优先用创建时间，其次用修改时间作为"原始时间"
            original_time = item.get("created_at") or item.get("updated_at") or ""

            if not doc_id:
                continue

            # 已被本插件处理
            if is_migrated(doc_id):
                skipped += 1
                continue

            # 时间过滤：跳过回溯窗口之外的文档
            if original_time:
                try:
                    doc_dt = datetime.strptime(original_time[:10], "%Y-%m-%d")
                    if doc_dt < cutoff:
                        skipped += 1
                        continue
                except Exception:
                    pass  # 无法解析时间则不过滤

            logger.info(f"[DailyMigration] 处理: {doc_name!r}  原始时间={original_time!r}")
            try:
                content = docs.read_file_content(doc_id)
                if not content:
                    skipped += 1
                    continue

                info = analyzer.analyze(content, doc_name=doc_name)
                if info is None:
                    skipped += 1
                    continue

                # 注入原始时间（让格式化函数显示原始时间）
                if original_time and not info.get("date"):
                    info["date"] = original_time[:10]

                # 手动项目映射覆盖（若 LLM 未识别出项目）
                if not info.get("project_code") and self.project_map:
                    for keyword, code in self.project_map.items():
                        if keyword.lower() in doc_name.lower():
                            info["project_code"] = code
                            break

                doc_url = item.get("url", "")
                feishu_page = self._write_rich_text(info, doc_url, original_time)
                mark_migrated(doc_id, doc_name, original_time, feishu_page or "")
                processed += 1
                proj = f" [{info.get('project_code', '')}]" if info.get("project_code") else ""
                logger.info(f"[DailyMigration] 已迁移{proj}: {doc_name!r} → {feishu_page}")

            except Exception as e:
                logger.error(f"[DailyMigration] 处理失败 ({doc_name}): {e}", exc_info=True)
                errors += 1

        summary = (
            f"每日会议迁移完成：新增 {processed} 篇，"
            f"跳过 {skipped} 篇，错误 {errors} 篇"
        )
        logger.info(f"[DailyMigration] {summary}")
        return summary

    # ------------------------------------------------------------------ #
    # 富文本写入
    # ------------------------------------------------------------------ #

    def _write_rich_text(self, info: dict, doc_url: str, original_time: str) -> str:
        """
        将会议 info 以飞书富文本块格式写入对应页面，返回 feishu_page token。

        写入顺序：
          1. 项目路由 → 04_会议纪要
          2. 降级 → 全局「📋 会议纪要汇总」页
        """
        from integrations.feishu.knowledge import FeishuKnowledge
        from integrations.feishu.rich_text import md_to_feishu_blocks
        from integrations.meeting import analyzer

        # 生成 Markdown，传入原始时间
        md_content = analyzer.format_for_project_page(
            info, doc_url=doc_url, doc_time=original_time
        )
        blocks = md_to_feishu_blocks(md_content)

        project_name = (info.get("project_name") or "").strip()
        project_code = (info.get("project_code") or "").strip().upper()

        if project_name or project_code:
            try:
                from integrations.meeting.project_router import ProjectRouter
                router = ProjectRouter()
                folder_token = router.get_or_create_project_folder(project_name, project_code)
                routing = router.route_meeting(info, folder_token)
                meeting_page = routing["meeting_notes_token"]

                kb = FeishuKnowledge()
                kb.append_blocks_to_page(meeting_page, blocks)
                return meeting_page
            except Exception as e:
                logger.warning(f"[DailyMigration] 项目路由失败，降级到全局汇总: {e}")

        # 降级：全局汇总页
        from integrations.meeting.analyzer import _get_or_create_meeting_page
        meeting_page = _get_or_create_meeting_page()
        kb = FeishuKnowledge()
        kb.append_blocks_to_page(meeting_page, blocks)
        return meeting_page


# --------------------------------------------------------------------------- #
# 全局入口（供 scheduler 和工具调用）
# --------------------------------------------------------------------------- #

def run_daily_migration() -> str:
    """执行每日会议纪要迁移，返回摘要。"""
    return DailyMigrationPlugin().run()
