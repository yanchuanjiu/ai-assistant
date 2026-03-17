"""
上下文双向同步：本地 SQLite（LangGraph checkpoints）↔ 飞书知识库。
同步策略：本地为主，飞书为人类可读镜像，每30分钟推送一次。
"""
import sqlite3
import logging
from datetime import datetime
from integrations.feishu.knowledge import FeishuKnowledge

logger = logging.getLogger(__name__)
DB_PATH = "data/memory.db"


class ContextSync:
    def __init__(self):
        self.kb = FeishuKnowledge()

    def push_to_feishu(self):
        """读取本地记忆摘要，写入飞书知识库。"""
        summary = self._build_summary()
        title = f"AI助理上下文快照 {datetime.now().strftime('%Y-%m-%d')}"
        try:
            url = self.kb.create_or_update_page(title=title, content=summary)
            logger.info(f"上下文已同步至飞书: {url}")
        except Exception as e:
            logger.error(f"同步飞书失败: {e}")

    def _build_summary(self) -> str:
        """从 SQLite 拼装可读摘要（最近100条 checkpoint 元数据）。"""
        lines = [f"# AI 助理上下文快照\n生成时间：{datetime.now().isoformat()}\n"]
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            # LangGraph checkpoints 表
            cur.execute(
                "SELECT thread_id, checkpoint_id, ts FROM checkpoints ORDER BY ts DESC LIMIT 50"
            )
            rows = cur.fetchall()
            if rows:
                lines.append("## 最近对话线程\n")
                for thread_id, ckpt_id, ts in rows:
                    lines.append(f"- `{thread_id}` at {ts}")
            con.close()
        except Exception as e:
            lines.append(f"（读取记忆库失败: {e}）")
        return "\n".join(lines)
