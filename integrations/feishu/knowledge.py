"""
飞书知识库（Wiki）操作：
- 解析 wiki URL/token → obj_token（get_node API）
- 读取 / 追加 / 覆盖页面内容（docx API）
- 列出/创建子页面（全程 tenant_access_token，无需 user OAuth）

权限说明：
  tenant_access_token 无法直接 create wiki nodes，
  但可以：① docx API 创建文档  ② move_docs_to_wiki 移入 wiki 作为子页面
  前提：在飞书页面的"文档权限"里给应用授予查看/编辑权限。
"""
import re
import time
import logging
from pydantic_settings import BaseSettings
from integrations.feishu.client import feishu_get, feishu_post, feishu_delete

logger = logging.getLogger(__name__)


class KBSettings(BaseSettings):
    feishu_wiki_space_id: str = ""
    feishu_wiki_context_page: str = ""   # 存放 AI 上下文快照的页面 wiki token

    class Config:
        env_file = ".env"
        extra = "ignore"


def parse_wiki_token(url_or_token: str) -> str:
    """
    从飞书 wiki URL 或裸 token 中提取 wiki node token。
    支持格式：
      - https://xxx.feishu.cn/wiki/Qo4nwLphWiWZyfkGAHHcoHwQnEf
      - https://xxx.feishu.cn/wiki/Qo4nwLphWiWZyfkGAHHcoHwQnEf?fromScene=...
      - Qo4nwLphWiWZyfkGAHHcoHwQnEf  （裸 token）
    """
    url_or_token = url_or_token.strip()
    m = re.search(r"/wiki/([A-Za-z0-9]+)", url_or_token)
    if m:
        return m.group(1)
    return url_or_token.split("?")[0]


def wiki_token_to_obj_token(wiki_token: str) -> tuple[str, str]:
    """
    将 wiki node token 转为实际文档 token。
    返回 (obj_token, obj_type)，obj_type 通常是 'docx'。
    """
    resp = feishu_get(
        "/wiki/v2/spaces/get_node",
        params={"token": wiki_token, "obj_type": "wiki"},
    )
    node = resp.get("data", {}).get("node", {})
    return node.get("obj_token", ""), node.get("obj_type", "docx")


# 标准项目文档列表（顺序即创建顺序）
_PROJECT_DOCS = [
    "00_项目章程",
    "01_需求与范围",
    "02_技术方案",
    "03_项目计划",
    "04_会议纪要",
    "05_状态周报",
    "06_RAID 日志",
]

# 各文档初始模板（仅对空页面写入）
_PROJECT_TEMPLATES: dict[str, str] = {
    "00_项目章程": """\
# {project_name} — 项目章程

**版本**：v1.0  **日期**：{date}  **状态**：草稿

## 1. 项目背景
[业务背景与发起原因]

## 2. 项目目标与成功标准
| 目标 | 衡量指标 (KPI) | 目标值 | 截止日期 |
|------|----------------|--------|----------|
|      |                |        |          |

## 3. 项目范围
**纳入范围 (In Scope)**：
-

**排除范围 (Out of Scope)**：
-

## 4. 干系人与 RACI
| 姓名/角色 | 部门 | R(执行) | A(负责) | C(咨询) | I(知情) |
|-----------|------|---------|---------|---------|---------|
|           |      |         |         |         |         |

## 5. 里程碑计划
| 里程碑 | 计划日期 | 实际日期 | 状态 |
|--------|----------|----------|------|
| 立项批准 |         |          | 🔵 规划 |
| 需求冻结 |         |          | 🔵 规划 |
| 技术方案确认 |     |          | 🔵 规划 |
| 开发完成 |         |          | 🔵 规划 |
| UAT 通过 |         |          | 🔵 规划 |
| 正式上线 |         |          | 🔵 规划 |

## 6. 初始风险识别
| 风险描述 | 概率(H/M/L) | 影响(H/M/L) | 应对策略 |
|----------|-------------|-------------|----------|
|          |             |             |          |

## 7. 资源与预算
[人力配置、外部资源、预算估算]

## 8. 项目批准
| 角色 | 姓名 | 确认日期 |
|------|------|----------|
| 项目发起人 |  |  |
| 项目负责人 |  |  |
""",
    "01_需求与范围": """\
# {project_name} — 需求与范围

**版本**：v1.0  **日期**：{date}

## 功能需求
| 需求ID | 需求描述 | 优先级 | 状态 |
|--------|----------|--------|------|
|        |          | H/M/L  | 待确认 |

## 非功能需求
- 性能：
- 安全：
- 可用性：

## 验收标准
-
""",
    "02_技术方案": """\
# {project_name} — 技术方案

**版本**：v1.0  **日期**：{date}  **评审状态**：草稿

## 1. 系统架构概览
[架构图 / 文字描述]

## 2. 系统交互清单
| 源系统 | 目标系统 | 接口方式 | 数据内容 | 频率 | 负责方 |
|--------|----------|----------|----------|------|--------|
|        |          |          |          |      |        |

## 3. 数据流与关键字段
[数据流向描述]

## 4. 安全与权限
- 数据分级：
- 访问控制：

## 5. 部署方案
- 环境：开发 / 测试 / 预发 / 生产
- 发布策略：

## 6. 技术风险与应对
| 风险 | 应对措施 |
|------|----------|
|      |          |
""",
    "03_项目计划": """\
# {project_name} — 项目计划

**版本**：v1.0  **日期**：{date}

## 整体进度
| 阶段 | 开始 | 结束 | 负责人 | 状态 |
|------|------|------|--------|------|
| 需求分析 | | | | 🔵 |
| 技术设计 | | | | 🔵 |
| 开发实现 | | | | 🔵 |
| 测试验证 | | | | 🔵 |
| 上线部署 | | | | 🔵 |
""",
    "04_会议纪要": """\
# {project_name} — 会议纪要

> 每次会议追加一条记录，最新在最下方。

""",
    "05_状态周报": """\
# {project_name} — 状态周报

> 每周追加一条，最新在最上方。

""",
    "06_RAID 日志": """\
# {project_name} — RAID 日志

> 持续维护：风险(Risks)、行动项(Actions)、问题(Issues)、决策(Decisions)

## 风险 (Risks)
| ID | 描述 | 概率 | 影响 | 优先级 | 应对措施 | 负责人 | 更新日期 | 状态 |
|----|------|------|------|--------|----------|--------|----------|------|

## 行动项 (Actions)
| ID | 描述 | 负责人 | 截止日期 | 优先级 | 状态 |
|----|------|--------|----------|--------|------|

## 问题 (Issues)
| ID | 描述 | 影响 | 解决方案 | 负责人 | 截止日期 | 状态 |
|----|------|------|----------|--------|----------|------|

## 决策 (Decisions)
| ID | 决策内容 | 背景与依据 | 决策人 | 日期 | 影响范围 |
|----|----------|-----------|--------|------|----------|
""",
}


class FeishuKnowledge:
    def __init__(self):
        cfg = KBSettings()
        self.space_id = cfg.feishu_wiki_space_id
        self.context_page_wiki_token = cfg.feishu_wiki_context_page

    # ------------------------------------------------------------------ #
    # 读取页面纯文本内容
    # ------------------------------------------------------------------ #
    def read_page(self, wiki_url_or_token: str) -> str:
        """通过 wiki URL 或 token 读取页面纯文本内容。"""
        wiki_token = parse_wiki_token(wiki_url_or_token)
        obj_token, _ = wiki_token_to_obj_token(wiki_token)
        if not obj_token:
            raise ValueError(f"无法解析 wiki token: {wiki_token}")
        resp = feishu_get(f"/docx/v1/documents/{obj_token}/raw_content")
        return resp.get("data", {}).get("content", "")

    # ------------------------------------------------------------------ #
    # 覆盖写入页面（清空后重写）
    # ------------------------------------------------------------------ #
    def overwrite_page(self, wiki_url_or_token: str, content: str):
        """清空页面所有内容，写入新的纯文本。"""
        wiki_token = parse_wiki_token(wiki_url_or_token)
        obj_token, _ = wiki_token_to_obj_token(wiki_token)
        if not obj_token:
            raise ValueError(f"无法解析 wiki token: {wiki_token}")
        self._clear_doc(obj_token)
        self._append_text(obj_token, content)

    # ------------------------------------------------------------------ #
    # 追加内容到页面末尾
    # ------------------------------------------------------------------ #
    def append_to_page(self, wiki_url_or_token: str, content: str):
        """向页面末尾追加文本内容。"""
        wiki_token = parse_wiki_token(wiki_url_or_token)
        obj_token, _ = wiki_token_to_obj_token(wiki_token)
        if not obj_token:
            raise ValueError(f"无法解析 wiki token: {wiki_token}")
        self._append_text(obj_token, content)

    # ------------------------------------------------------------------ #
    # AI 上下文快照专用：覆盖写入 context_page
    # ------------------------------------------------------------------ #
    def create_or_update_page(self, title: str, content: str) -> str:
        """
        写入 AI 上下文快照到预配置的 context page（FEISHU_WIKI_CONTEXT_PAGE）。
        """
        wiki_token = self.context_page_wiki_token
        if not wiki_token:
            raise ValueError(
                "FEISHU_WIKI_CONTEXT_PAGE 未配置，"
                "请在飞书新建一个专用页面并将其 wiki token 填入 .env"
            )
        obj_token, _ = wiki_token_to_obj_token(wiki_token)
        if not obj_token:
            raise ValueError(f"无法解析 context page wiki token: {wiki_token}")
        full_content = f"# {title}\n\n{content}"
        self._clear_doc(obj_token)
        self._append_text(obj_token, full_content)
        return f"https://open.feishu.cn/docx/{obj_token}"

    # ------------------------------------------------------------------ #
    # 子页面：列出 / 查找 / 创建
    # ------------------------------------------------------------------ #
    def _is_space_level_token(self, token: str) -> bool:
        """判断 token 是否是 space 级别的标识（space_id 数字串 或 space_XXX 格式），
        这类 token 不能作为 parent_node_token 传给 wiki nodes API。"""
        if not token:
            return False
        # 纯数字 = space_id（如 7618158120166034630）
        if token.isdigit():
            return True
        # space_ 前缀（如 space_7618158120166034630）
        if token.startswith("space_"):
            return True
        return False

    def list_wiki_children(self, parent_wiki_token: str) -> list[dict]:
        """列出指定 wiki 节点的直属子页面。返回节点列表（含 title / node_token / has_child）。

        parent_wiki_token 必须是 wiki node token（如 FalZwGDOkiqpbQkeAjGc8jaznMd），
        不能是 space_id 数字或 space_XXX 格式。如果传入 space 级标识，
        将改为列出 wiki 空间根节点（不带 parent_node_token 参数）。
        """
        if self._is_space_level_token(parent_wiki_token):
            logger.warning(
                f"[FeishuKnowledge] list_wiki_children: 收到 space 级标识 {parent_wiki_token!r}，"
                f"改为列出空间根节点（parent_node_token 留空）"
            )
            resp = feishu_get(
                f"/wiki/v2/spaces/{self.space_id}/nodes",
                params={"page_size": 50},
            )
        else:
            resp = feishu_get(
                f"/wiki/v2/spaces/{self.space_id}/nodes",
                params={"parent_node_token": parent_wiki_token, "page_size": 50},
            )
        return resp.get("data", {}).get("items", [])

    def create_wiki_child_page(self, title: str, parent_wiki_token: str) -> str:
        """
        在指定 wiki 节点下创建子页面，返回新页面的 wiki node_token。

        方案 A（首选）：POST /wiki/v2/spaces/{space_id}/nodes 直接创建 wiki 节点
        方案 B（备选）：POST /docx/v1/documents → move_docs_to_wiki → 轮询任务

        全程 tenant_access_token，无需 user OAuth。
        """
        if self._is_space_level_token(parent_wiki_token):
            raise ValueError(
                f"create_wiki_child_page: parent_wiki_token {parent_wiki_token!r} 是 space 级标识，"
                f"请传入有效的 wiki node token（如 FalZwGDOkiqpbQkeAjGc8jaznMd）"
            )

        # 方案 A：直接创建 wiki 节点（无需 docx 中转）
        try:
            resp = feishu_post(
                f"/wiki/v2/spaces/{self.space_id}/nodes",
                json={
                    "obj_type": "wiki",
                    "parent_node_token": parent_wiki_token,
                    "node_type": "origin",
                    "title": title,
                },
            )
            node = resp.get("data", {}).get("node", {})
            node_token = node.get("node_token", "")
            if node_token:
                logger.info(f"[FeishuKnowledge] 方案A 创建子页面成功: {title!r} → {node_token}")
                return node_token
            logger.warning(f"[FeishuKnowledge] 方案A 响应未含 node_token: {resp}")
        except Exception as e:
            logger.warning(f"[FeishuKnowledge] 方案A 失败，降级到方案B: {e}")

        # 方案 B（降级）：创建 docx 后 move_docs_to_wiki
        # ① 创建 docx
        doc_resp = feishu_post("/docx/v1/documents", json={"title": title})
        doc_id = doc_resp["data"]["document"]["document_id"]

        # ② 移入 wiki
        move_resp = feishu_post(
            f"/wiki/v2/spaces/{self.space_id}/nodes/move_docs_to_wiki",
            json={
                "parent_wiki_token": parent_wiki_token,
                "obj_type": "docx",
                "obj_token": doc_id,
            },
        )
        task_id = move_resp["data"]["task_id"]

        # ③ 轮询任务（最多等 10 秒）
        for _ in range(10):
            time.sleep(1)
            task_resp = feishu_get(f"/wiki/v2/tasks/{task_id}", params={"task_type": "move"})
            results = task_resp.get("data", {}).get("task", {}).get("move_result", [])
            if results and results[0].get("status") == 0:
                node_token = results[0]["node"]["node_token"]
                logger.info(f"[FeishuKnowledge] 方案B 创建子页面成功: {title!r} → {node_token}")
                return node_token
        raise RuntimeError(f"创建子页面超时（task_id={task_id}）")

    def find_or_create_child_page(
        self, title: str, parent_wiki_token: str, cache_key: str = ""
    ) -> str:
        """
        在指定 wiki 节点下查找或创建命名子页面，返回 wiki node_token。

        查找顺序：
          1. config_store 缓存（cache_key 非空时）
          2. list_children 按 title 精确匹配
          3. 以上均无则调用 create_wiki_child_page 新建

        结果自动写入 config_store（cache_key 非空时）以供后续复用。
        """
        from integrations.storage.config_store import get as cfg_get, set as cfg_set

        # 1. 缓存
        if cache_key:
            cached = cfg_get(cache_key)
            if cached:
                logger.debug(f"[FeishuKnowledge] 命中缓存 {cache_key}={cached}")
                return cached

        # 2. 列子节点查找同名
        children = self.list_wiki_children(parent_wiki_token)
        for child in children:
            if child.get("title") == title:
                token = child["node_token"]
                logger.info(f"[FeishuKnowledge] 找到已有子页面: {title!r} → {token}")
                if cache_key:
                    cfg_set(cache_key, token)
                return token

        # 3. 新建
        logger.info(f"[FeishuKnowledge] 子页面不存在，新建: {title!r}")
        token = self.create_wiki_child_page(title, parent_wiki_token)
        if cache_key:
            cfg_set(cache_key, token)
        return token

    # ------------------------------------------------------------------ #
    # 搜索（在指定页面列表中检索关键词）
    # ------------------------------------------------------------------ #
    def search(self, query: str, wiki_tokens: list[str] = None) -> list[str]:
        """
        在指定的 wiki token 列表中搜索包含 query 的页面内容。
        wiki_tokens 为空时仅搜索 context_page。
        """
        targets = wiki_tokens or (
            [self.context_page_wiki_token] if self.context_page_wiki_token else []
        )
        results = []
        for wt in targets:
            if not wt:
                continue
            try:
                content = self.read_page(wt)
                if query.lower() in content.lower():
                    results.append(content)
            except Exception as e:
                logger.warning(f"读取页面失败 {wt}: {e}")
        return results

    # ------------------------------------------------------------------ #
    # 项目文件夹批量初始化
    # ------------------------------------------------------------------ #
    def bootstrap_project(
        self,
        project_name: str,
        project_code: str,
        parent_wiki_token: str,
        docs_to_create: list[str] | None = None,
    ) -> dict[str, str]:
        """
        在 parent_wiki_token 下创建完整项目文件夹结构，返回 {doc_type: wiki_token} 映射。

        幂等：重复调用安全（find_or_create），已存在文档不覆盖内容。
        """
        from datetime import date as _date
        from integrations.storage.config_store import set as cfg_set

        docs = docs_to_create if docs_to_create is not None else _PROJECT_DOCS
        today = _date.today().isoformat()

        # 创建/查找项目文件夹
        if project_code:
            folder_title = f"{project_code} {project_name} 🔵" if project_name else f"{project_code} 🔵"
        else:
            folder_title = f"{project_name} 🔵" if project_name else "未命名项目 🔵"

        cache_key = f"FEISHU_PROJECT_{project_code.upper()}" if project_code else ""
        folder_token = self.find_or_create_child_page(
            title=folder_title,
            parent_wiki_token=parent_wiki_token,
            cache_key=cache_key,
        )
        logger.info(f"[FeishuBootstrap] 项目文件夹: {folder_title!r} → {folder_token}")

        result: dict[str, str] = {"folder": folder_token}

        for doc_name in docs:
            try:
                doc_cache_key = (
                    f"FEISHU_PROJECT_{project_code.upper()}_{doc_name}" if project_code else ""
                )
                doc_token = self.find_or_create_child_page(
                    title=doc_name,
                    parent_wiki_token=folder_token,
                    cache_key=doc_cache_key,
                )
                result[doc_name] = doc_token

                # 仅对空页面写入模板
                template = _PROJECT_TEMPLATES.get(doc_name, "")
                if template:
                    try:
                        existing = self.read_page(doc_token)
                        if len(existing.strip()) < 10:
                            content = template.format(
                                project_name=project_name or "项目", date=today
                            )
                            self.append_to_page(doc_token, content)
                            logger.info(f"[FeishuBootstrap] 写入模板: {doc_name!r}")
                    except Exception as e:
                        logger.warning(f"[FeishuBootstrap] 模板写入失败 {doc_name!r}: {e}")

            except Exception as e:
                logger.error(f"[FeishuBootstrap] 创建子文档失败 {doc_name!r}: {e}")
                result[doc_name] = ""

        return result

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _clear_doc(self, obj_token: str):
        """删除文档所有子块（清空内容）。"""
        resp = feishu_get(f"/docx/v1/documents/{obj_token}/blocks")
        items = resp.get("data", {}).get("items", [])
        child_count = len(items) - 1   # items[0] 是根块自身
        if child_count <= 0:
            return
        feishu_delete(
            f"/docx/v1/documents/{obj_token}/blocks/{obj_token}/children/batch_delete",
            json={"start_index": 0, "end_index": child_count},
        )

    def _append_text(self, obj_token: str, text: str, chunk_size: int = 40):
        """向文档末尾追加文本（按换行拆成段落块，分批提交避免超限）。"""
        import time
        lines = text.split("\n")
        for i in range(0, len(lines), chunk_size):
            batch = lines[i : i + chunk_size]
            children = [
                {
                    "block_type": 2,
                    "text": {
                        "elements": [{"text_run": {"content": line}}],
                        "style": {},
                    },
                }
                for line in batch
            ]
            feishu_post(
                f"/docx/v1/documents/{obj_token}/blocks/{obj_token}/children",
                json={"children": children, "index": -1},
            )
            if i + chunk_size < len(lines):
                time.sleep(0.3)  # 防止限速
