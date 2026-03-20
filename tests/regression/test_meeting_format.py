"""
单元测试：会议纪要格式化函数样式输出
  T1  format_for_feishu — 基础字段渲染
  T2  format_for_feishu — 可选字段（摘要/决策/待办/跟进）
  T3  format_for_feishu — 空数据兜底
  T4  format_for_project_page — 项目信息 & 里程碑
  T5  format_for_project_page — RAID 元素渲染
  T6  格式兼容性：md_to_feishu_blocks 能解析输出（不抛异常）
"""
import pytest
from integrations.meeting.analyzer import format_for_feishu, format_for_project_page


# ── 测试数据 ────────────────────────────────────────────────────────────────────

BASIC_INFO = {
    "is_meeting": True,
    "title": "产品评审会议",
    "date": "2026-03-20",
    "participants": ["张三", "李四", "王五"],
    "summary": "本次评审确认了 v2.0 功能范围，推迟了支付模块上线计划。",
    "decisions": ["v2.0 功能范围冻结", "支付模块延期至 Q2"],
    "action_items": [
        {"task": "更新需求文档", "owner": "张三", "deadline": "2026-03-25"},
        {"task": "通知研发团队", "owner": "李四", "deadline": ""},
    ],
    "next_steps": "下周五前完成文档更新，安排研发 kickoff。",
}

PROJECT_INFO = {
    **BASIC_INFO,
    "project_name": "AI 助理平台",
    "project_code": "AIP",
    "milestone_impact": {
        "milestone": "v2.0 发布",
        "status": "at_risk",
    },
    "weekly_report_hint": "支付模块存在延期风险，已升级至 PMO。",
    "raid_elements": {
        "risks": [
            {
                "description": "第三方支付 API 接口变更",
                "probability": "高",
                "impact": "高",
                "mitigation": "联系供应商确认变更时间表",
            }
        ],
        "decisions": [
            {
                "decision": "支付模块延期至 Q2",
                "rationale": "技术风险过高",
                "impact_scope": "全部支付相关功能",
            }
        ],
        "actions": [],
        "issues": [],
    },
}

MINIMAL_INFO = {
    "is_meeting": True,
    "title": "",
    "date": "",
    "participants": [],
    "summary": "",
    "decisions": [],
    "action_items": [],
    "next_steps": "",
}


# ── T1 format_for_feishu 基础字段 ──────────────────────────────────────────────

class TestFormatForFeishu:
    def test_contains_title(self):
        out = format_for_feishu(BASIC_INFO)
        assert "产品评审会议" in out

    def test_contains_date(self):
        out = format_for_feishu(BASIC_INFO)
        assert "2026-03-20" in out

    def test_contains_participants(self):
        out = format_for_feishu(BASIC_INFO)
        assert "张三" in out
        assert "李四" in out

    def test_divider_present(self):
        out = format_for_feishu(BASIC_INFO)
        assert "---" in out

    def test_heading_level2(self):
        out = format_for_feishu(BASIC_INFO)
        assert "## 📋 产品评审会议" in out

    def test_info_table_format(self):
        out = format_for_feishu(BASIC_INFO)
        # 表格行存在
        assert "| 📅 **会议日期**" in out
        assert "| 👥 **参与人**" in out

    def test_doc_url_in_table(self):
        out = format_for_feishu(BASIC_INFO, doc_url="https://example.com/doc/123")
        assert "🔗 **原始文档**" in out
        assert "https://example.com/doc/123" in out

    def test_no_doc_url(self):
        out = format_for_feishu(BASIC_INFO)
        assert "🔗" not in out


# ── T2 可选字段 ────────────────────────────────────────────────────────────────

class TestFormatForFeishuOptional:
    def test_summary_as_blockquote(self):
        out = format_for_feishu(BASIC_INFO)
        # 摘要使用引用块格式
        assert "> " in out
        assert "v2.0 功能范围" in out

    def test_decisions_section(self):
        out = format_for_feishu(BASIC_INFO)
        assert "### ✅ 决策与结论" in out
        assert "v2.0 功能范围冻结" in out
        assert "支付模块延期至 Q2" in out

    def test_action_items_with_owner_bold(self):
        out = format_for_feishu(BASIC_INFO)
        assert "### 📌 待办事项" in out
        assert "**（张三）**" in out
        assert "- [ ] 更新需求文档" in out

    def test_action_item_deadline_code(self):
        out = format_for_feishu(BASIC_INFO)
        assert "`2026-03-25`" in out

    def test_action_item_no_deadline(self):
        """没有 deadline 时不应有 ⏰"""
        out = format_for_feishu(BASIC_INFO)
        lines = out.split("\n")
        notify_line = next((l for l in lines if "通知研发团队" in l), "")
        assert "⏰" not in notify_line

    def test_next_steps_section(self):
        out = format_for_feishu(BASIC_INFO)
        assert "### 🔄 后续跟进" in out
        assert "下周五前完成文档更新" in out

    def test_no_decisions_section_absent(self):
        info = {**BASIC_INFO, "decisions": []}
        out = format_for_feishu(info)
        assert "决策与结论" not in out

    def test_no_action_items_section_absent(self):
        info = {**BASIC_INFO, "action_items": []}
        out = format_for_feishu(info)
        assert "待办事项" not in out


# ── T3 空数据兜底 ────────────────────────────────────────────────────────────────

class TestFormatForFeishuMinimal:
    def test_minimal_no_crash(self):
        out = format_for_feishu(MINIMAL_INFO)
        assert isinstance(out, str)
        assert "未命名会议" in out
        assert "未记录" in out

    def test_minimal_no_optional_sections(self):
        out = format_for_feishu(MINIMAL_INFO)
        assert "决策" not in out
        assert "待办" not in out
        assert "后续跟进" not in out


# ── T4 format_for_project_page 项目信息 ────────────────────────────────────────

class TestFormatForProjectPage:
    def test_project_code_in_table(self):
        out = format_for_project_page(PROJECT_INFO)
        assert "AIP" in out
        assert "AI 助理平台" in out
        assert "📁 **项目**" in out

    def test_milestone_section(self):
        out = format_for_project_page(PROJECT_INFO)
        assert "### 🏁 里程碑影响" in out
        assert "v2.0 发布" in out
        assert "🟡 有风险" in out

    def test_milestone_status_on_track(self):
        info = {**PROJECT_INFO, "milestone_impact": {"milestone": "M1 上线", "status": "on_track"}}
        out = format_for_project_page(info)
        assert "🟢 正常" in out

    def test_milestone_status_delayed(self):
        info = {**PROJECT_INFO, "milestone_impact": {"milestone": "M1 上线", "status": "delayed"}}
        out = format_for_project_page(info)
        assert "🔴 延迟" in out

    def test_weekly_hint_section(self):
        out = format_for_project_page(PROJECT_INFO)
        assert "### 📊 本周状态" in out
        assert "支付模块存在延期风险" in out

    def test_doc_time_in_table(self):
        out = format_for_project_page(PROJECT_INFO, doc_time="2026-03-20 14:30")
        assert "2026-03-20 14:30" in out

    def test_no_project_info(self):
        """无项目信息时不应输出项目行"""
        info = {**BASIC_INFO, "project_name": "", "project_code": ""}
        out = format_for_project_page(info)
        assert "📁 **项目**" not in out


# ── T5 RAID 元素渲染 ────────────────────────────────────────────────────────────

class TestFormatForProjectPageRaid:
    def test_raid_risks_section(self):
        out = format_for_project_page(PROJECT_INFO)
        assert "### ⚠️ 识别风险" in out
        assert "第三方支付 API 接口变更" in out
        assert "`[高/高]`" in out
        assert "联系供应商确认变更时间表" in out

    def test_raid_decisions_section(self):
        out = format_for_project_page(PROJECT_INFO)
        assert "### 📜 本次决策（详细）" in out
        assert "支付模块延期至 Q2" in out
        assert "技术风险过高" in out
        assert "全部支付相关功能" in out

    def test_no_raid_elements(self):
        info = {**BASIC_INFO, "raid_elements": {}}
        out = format_for_project_page(info)
        assert "识别风险" not in out
        assert "本次决策（详细）" not in out


# ── T6 富文本兼容性 ────────────────────────────────────────────────────────────

class TestRichTextCompatibility:
    """验证 format 输出可被 md_to_feishu_blocks 解析，不抛异常。"""

    def test_feishu_blocks_basic(self):
        from integrations.feishu.rich_text import md_to_feishu_blocks
        out = format_for_feishu(BASIC_INFO)
        blocks = md_to_feishu_blocks(out)
        assert isinstance(blocks, list)
        assert len(blocks) > 0

    def test_feishu_blocks_project(self):
        from integrations.feishu.rich_text import md_to_feishu_blocks
        out = format_for_project_page(PROJECT_INFO)
        blocks = md_to_feishu_blocks(out)
        assert isinstance(blocks, list)
        assert len(blocks) > 0

    def test_feishu_blocks_minimal(self):
        from integrations.feishu.rich_text import md_to_feishu_blocks
        out = format_for_feishu(MINIMAL_INFO)
        blocks = md_to_feishu_blocks(out)
        assert isinstance(blocks, list)

    def test_feishu_blocks_contains_heading(self):
        """输出块中应包含 heading 类型块（block_type 3-8）。"""
        from integrations.feishu.rich_text import md_to_feishu_blocks
        out = format_for_feishu(BASIC_INFO)
        blocks = md_to_feishu_blocks(out)
        heading_blocks = [b for b in blocks if b.get("block_type") in range(3, 9)]
        assert len(heading_blocks) >= 1, "应至少包含一个标题块"

    def test_feishu_blocks_contains_divider(self):
        """输出块中应包含分隔线块（block_type 24）。"""
        from integrations.feishu.rich_text import md_to_feishu_blocks
        out = format_for_feishu(BASIC_INFO)
        blocks = md_to_feishu_blocks(out)
        dividers = [b for b in blocks if b.get("block_type") == 24]
        assert len(dividers) >= 1, "应至少包含一个分隔线块"

    def test_feishu_blocks_contains_bullet(self):
        """待办/决策列表应生成 bullet 块（block_type 13）。"""
        from integrations.feishu.rich_text import md_to_feishu_blocks
        out = format_for_feishu(BASIC_INFO)
        blocks = md_to_feishu_blocks(out)
        bullets = [b for b in blocks if b.get("block_type") == 13]
        assert len(bullets) >= 1, "应至少包含一个列表块"
