"""
项目路由器：根据会议分析结果识别项目，在飞书中定位或创建对应项目文件夹和子页面。
"""
import logging
import os

logger = logging.getLogger(__name__)

# 子页面标准名称（与 SKILLS_PROJECT_MGMT.md 保持一致）
PAGE_MEETING_NOTES = "04_会议纪要"
PAGE_WEEKLY_REPORT = "05_状态周报"
PAGE_RAID_LOG      = "06_RAID 日志"


class ProjectRouter:
    """
    根据会议 info dict 将内容路由到飞书对应项目子页面。

    使用前提：
      - 环境变量 FEISHU_WIKI_PORTFOLIO_PAGE 或 FEISHU_WIKI_CONTEXT_PAGE 已配置
        （作为项目集根节点，项目文件夹建在其下）
    """

    def __init__(self):
        from integrations.feishu.knowledge import FeishuKnowledge
        from integrations.storage.config_store import get as cfg_get, set as cfg_set
        self._kb = FeishuKnowledge()
        self._cfg_get = cfg_get
        self._cfg_set = cfg_set

    def _portfolio_root(self) -> str:
        """返回项目集根页面 token（优先 FEISHU_WIKI_PORTFOLIO_PAGE，降级 FEISHU_WIKI_CONTEXT_PAGE）。"""
        root = (
            self._cfg_get("FEISHU_WIKI_PORTFOLIO_PAGE")
            or os.getenv("FEISHU_WIKI_PORTFOLIO_PAGE", "")
            or self._cfg_get("FEISHU_WIKI_CONTEXT_PAGE")
            or os.getenv("FEISHU_WIKI_CONTEXT_PAGE", "")
        )
        if not root:
            raise RuntimeError(
                "未配置项目集根页面，请通过 agent_config 设置 FEISHU_WIKI_PORTFOLIO_PAGE"
            )
        return root

    def identify_project(self, info: dict) -> tuple[str, str]:
        """
        从 info 提取 (project_name, project_code)。
        优先使用 LLM 已提取的字段，均为空时返回 ("", "")。
        """
        name = (info.get("project_name") or "").strip()
        code = (info.get("project_code") or "").strip().upper()
        return name, code

    def get_or_create_project_folder(self, project_name: str, project_code: str) -> str:
        """
        在项目集根页面下查找或创建项目文件夹，返回 wiki node_token。

        查找顺序：
          1. config_store 缓存 FEISHU_PROJECT_{CODE}（有 code 时）
          2. list_wiki_children 按名称前缀模糊匹配
          3. 以上均无则 find_or_create_child_page 新建
        文件夹命名："{code} {name} 🔵"（code 为空时省略 code 前缀）
        """
        root = self._portfolio_root()
        cache_key = f"FEISHU_PROJECT_{project_code}" if project_code else ""

        # 1. 缓存
        if cache_key:
            cached = self._cfg_get(cache_key)
            if cached:
                logger.debug(f"[ProjectRouter] 命中缓存 {cache_key}={cached}")
                return cached

        # 2. 模糊匹配子节点（含 code 或 name 的标题）
        children = self._kb.list_wiki_children(root)
        for child in children:
            title = child.get("title", "")
            if (project_code and project_code in title) or (project_name and project_name in title):
                token = child["node_token"]
                if cache_key:
                    self._cfg_set(cache_key, token)
                logger.info(f"[ProjectRouter] 找到已有项目文件夹: {title!r} → {token}")
                return token

        # 3. 新建
        if project_code:
            folder_title = f"{project_code} {project_name} 🔵" if project_name else f"{project_code} 🔵"
        else:
            folder_title = f"{project_name} 🔵" if project_name else "未命名项目 🔵"

        token = self._kb.find_or_create_child_page(
            title=folder_title,
            parent_wiki_token=root,
            cache_key=cache_key,
        )
        logger.info(f"[ProjectRouter] 创建项目文件夹: {folder_title!r} → {token}")
        return token

    def _get_project_subpage(self, project_folder_token: str, page_title: str, cache_key: str) -> str:
        """查找或创建项目文件夹下的指定子页面，返回 wiki node_token。"""
        return self._kb.find_or_create_child_page(
            title=page_title,
            parent_wiki_token=project_folder_token,
            cache_key=cache_key,
        )

    def route_meeting(self, info: dict, project_folder_token: str) -> dict:
        """
        根据 info 内容确定需要写入哪些子页面，返回路由结果 dict。

        返回值：
        {
          "meeting_notes_token": str,           # 04_会议纪要（总是存在）
          "raid_token": str | None,             # 06_RAID 日志（有 raid_elements 时）
          "weekly_report_token": str | None,    # 05_状态周报（有 weekly_report_hint 时）
        }
        """
        code = (info.get("project_code") or "UNKNOWN").upper()

        # 04_会议纪要（总是创建/查找）
        meeting_token = self._get_project_subpage(
            project_folder_token,
            PAGE_MEETING_NOTES,
            f"FEISHU_PROJECT_{code}_MEETING_NOTES",
        )

        # 06_RAID 日志（有任何 raid_elements 非空时）
        raid_token = None
        raid = info.get("raid_elements") or {}
        has_raid = any(raid.get(k) for k in ("risks", "actions", "issues", "decisions"))
        if has_raid:
            raid_token = self._get_project_subpage(
                project_folder_token,
                PAGE_RAID_LOG,
                f"FEISHU_PROJECT_{code}_RAID",
            )

        # 05_状态周报（有 weekly_report_hint 时）
        weekly_token = None
        if info.get("weekly_report_hint"):
            weekly_token = self._get_project_subpage(
                project_folder_token,
                PAGE_WEEKLY_REPORT,
                f"FEISHU_PROJECT_{code}_WEEKLY",
            )

        return {
            "meeting_notes_token": meeting_token,
            "raid_token": raid_token,
            "weekly_report_token": weekly_token,
        }
