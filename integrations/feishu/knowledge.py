"""
飞书知识库（Wiki）操作：
- 解析 wiki URL/token → obj_token（get_node API）
- 读取 / 追加 / 覆盖页面内容（docx API）
- 列出/创建子页面

权限说明：
  wiki space API（/wiki/v2/spaces/{space_id}/nodes）需要 tenant 有空间编辑权限（error 131006）。
  解决方案优先级：
    1. user_access_token（若 FEISHU_USER_ACCESS_TOKEN / FEISHU_USER_REFRESH_TOKEN 已配置）
    2. tenant_access_token + wiki 空间管理员手动授权应用编辑权限

  docx API（/docx/v1/documents/...）只需文档级权限，tenant_access_token 可用。
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
        params={"token": wiki_token},
    )
    node = resp.get("data", {}).get("node", {})
    obj_token = node.get("obj_token", "")
    if not obj_token:
        logger.warning(
            f"[wiki_token_to_obj_token] token={wiki_token!r} 未返回 obj_token，"
            f"页面可能已删除/移动。完整响应: {resp}"
        )
    return obj_token, node.get("obj_type", "docx")


# 标准项目文档列表（敏捷业务项目，顺序即创建顺序）
_PROJECT_DOCS = [
    "00_项目章程",
    "01_需求清单",
    "04_会议纪要",
    "05_迭代计划",
    "06_RAID 日志",
    "07_需求交付记录",
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
| 首个迭代交付 |     |          | 🔵 规划 |
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
    "01_需求清单": """\
# {project_name} — 需求清单

**版本**：v1.0  **日期**：{date}

> 使用用户故事格式：作为 [角色]，我希望 [功能]，以便 [价值]

## Epic 列表
| Epic ID | Epic 名称 | 业务价值 | 优先级 | 状态 |
|---------|-----------|----------|--------|------|
| E001    |           |          | H/M/L  | 待排期 |

## 用户故事
| Story ID | Epic | 用户故事 | 验收标准 | 优先级 | 估算(点) | 迭代 | 状态 |
|----------|------|----------|----------|--------|----------|------|------|
| US001    | E001 | 作为…我希望…以便… | - Given…When…Then… | H | - | - | 待排期 |

## 非功能需求
- 性能：
- 安全：
- 可用性：
""",
    "04_会议纪要": """\
# {project_name} — 会议纪要

> 每次会议创建独立子页面，命名格式：YYYY-MM-DD 会议主题

""",
    "05_迭代计划": """\
# {project_name} — 迭代计划

**日期**：{date}

> 每个 Sprint 追加一条，最新在最下方。

## Sprint 模板
### Sprint N（YYYY-MM-DD 至 YYYY-MM-DD）

**Sprint 目标**：[本迭代要达成的业务目标]

**计划故事**：
| Story ID | 描述 | 负责人 | 估算(点) | 状态 |
|----------|------|--------|----------|------|
|          |      |        |          | 待开始 |

**Sprint 回顾**：
- 做得好：
- 待改进：
- 下次行动：
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

## 需求验收 (Acceptance)
| Story ID | 需求描述 | 验收标准 | 验收人 | 验收日期 | 结果 | 备注 |
|----------|----------|----------|--------|----------|------|------|
""",
    "07_需求交付记录": """\
# {project_name} — 需求交付记录

**日期**：{date}

> 记录每个需求从开发完成到业务验收的全过程，作为项目交付存档。

## 交付记录
| Story ID | 需求描述 | 迭代 | 开发完成日 | UAT 开始日 | 业务验收日 | 验收人 | 上线日期 | 结果 |
|----------|----------|------|------------|------------|------------|--------|----------|------|
|          |          |      |            |            |            |        |          | ✅ 通过 |

## 遗留问题跟踪
| 问题编号 | 描述 | 关联需求 | 严重程度 | 解决日期 | 状态 |
|----------|------|----------|----------|----------|------|
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
    # wiki space API 专用：user token 优先，tenant token 降级
    # ------------------------------------------------------------------ #
    def _wiki_get(self, path: str, params: dict = None) -> dict:
        """GET wiki space API：先用 user_access_token，失败/未配置则用 tenant_access_token。"""
        from integrations.feishu.client import feishu_get_user, feishu_get
        try:
            return feishu_get_user(path, params)
        except RuntimeError:
            # user token 未配置
            return feishu_get(path, params)
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (401, 403):
                logger.warning(f"[wiki] user token GET 失败({status})，降级 tenant token: {e}")
                return feishu_get(path, params)
            raise

    def _wiki_post(self, path: str, json: dict = None) -> dict:
        """POST wiki space API：先用 user_access_token，失败/未配置则用 tenant_access_token。"""
        from integrations.feishu.client import feishu_post_user, feishu_post
        try:
            return feishu_post_user(path, json)
        except RuntimeError:
            # user token 未配置
            return feishu_post(path, json)
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (401, 403):
                logger.warning(f"[wiki] user token POST 失败({status})，降级 tenant token: {e}")
                return feishu_post(path, json)
            raise

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

    def list_wiki_children(self, parent_wiki_token: str = "") -> list[dict]:
        """列出指定 wiki 节点的直属子页面。返回节点列表（含 title / node_token / has_child）。

        parent_wiki_token 为空或 space 级标识时，列出知识库空间根节点（第一层文档）。
        parent_wiki_token 为 wiki node token 时，列出该节点的子页面。
        """
        if not parent_wiki_token or self._is_space_level_token(parent_wiki_token):
            # 列出知识库空间根节点：不传 parent_node_token
            logger.info(
                f"[FeishuKnowledge] list_wiki_children: 列出空间根节点（space_id={self.space_id}）"
            )
            try:
                resp = self._wiki_get(
                    f"/wiki/v2/spaces/{self.space_id}/nodes",
                    params={"page_size": 50},
                )
                items = resp.get("data", {}).get("items", [])
                logger.info(f"[FeishuKnowledge] 空间根节点数量: {len(items)}")
                return items
            except Exception as e:
                detail = str(e)
                if "131006" in detail:
                    raise RuntimeError(
                        f"wiki 空间权限不足（error 131006）：应用需要被 wiki 空间管理员授予「读取」权限，"
                        f"或在 .env 中配置 FEISHU_USER_ACCESS_TOKEN / FEISHU_USER_REFRESH_TOKEN。"
                        f"原始错误: {e}"
                    ) from e
                logger.warning(f"[FeishuKnowledge] 列出根节点失败: {e}，返回空列表")
                return []
        else:
            try:
                resp = self._wiki_get(
                    f"/wiki/v2/spaces/{self.space_id}/nodes",
                    params={"parent_node_token": parent_wiki_token, "page_size": 50},
                )
            except Exception as e:
                detail = str(e)
                if "131006" in detail:
                    raise RuntimeError(
                        f"wiki 空间权限不足（error 131006）：应用需要被 wiki 空间管理员授予「读取」权限，"
                        f"或在 .env 中配置 FEISHU_USER_ACCESS_TOKEN / FEISHU_USER_REFRESH_TOKEN。"
                        f"原始错误: {e}"
                    ) from e
                if "400" in detail:
                    logger.warning(
                        f"[FeishuKnowledge] list_wiki_children 400（页面可能已删除/移动/不在本空间）: "
                        f"{parent_wiki_token!r}，返回空列表"
                    )
                    return []
                raise
        return resp.get("data", {}).get("items", [])

    def create_wiki_child_page(self, title: str, parent_wiki_token: str) -> str:
        """
        在指定 wiki 节点下创建子页面，返回新页面的 wiki node_token。

        方案 A（首选）：POST /wiki/v2/spaces/{space_id}/nodes 直接创建 wiki 节点
        方案 B（备选）：POST /docx/v1/documents → move_docs_to_wiki → 轮询任务

        优先使用 user_access_token（若已配置），否则使用 tenant_access_token。
        tenant_access_token 需要 wiki 空间管理员授予应用编辑权限（error 131006）。
        """
        if self._is_space_level_token(parent_wiki_token):
            logger.info(
                f"[FeishuKnowledge] create_wiki_child_page: 收到 space 级标识 {parent_wiki_token!r}，"
                f"将在 wiki 空间根目录创建（不指定 parent_node_token）"
            )

        # 方案 A：直接创建 wiki 节点（无需 docx 中转）
        # 注意：obj_type 必须是 "docx" 等文档类型，"wiki" 不是有效枚举值
        try:
            payload: dict = {
                "obj_type": "docx",
                "node_type": "origin",
                "title": title,
            }
            # space 级标识 → 创建在 wiki 空间根目录，不传 parent_node_token
            if not self._is_space_level_token(parent_wiki_token):
                payload["parent_node_token"] = parent_wiki_token
            resp = self._wiki_post(
                f"/wiki/v2/spaces/{self.space_id}/nodes",
                json=payload,
            )
            node = resp.get("data", {}).get("node", {})
            node_token = node.get("node_token", "")
            if node_token:
                logger.info(f"[FeishuKnowledge] 方案A 创建子页面成功: {title!r} → {node_token}")
                return node_token
            logger.warning(f"[FeishuKnowledge] 方案A 响应未含 node_token: {resp}")
        except Exception as e:
            detail = str(e)
            # 检测 131006（wiki 空间权限不足）→ 直接报错，无需降级到方案B（方案B同样需要空间权限）
            if "131006" in detail:
                raise RuntimeError(
                    f"wiki 空间权限不足（error 131006）：应用需要被 wiki 空间管理员授予「编辑」权限，"
                    f"或在 .env 中配置 FEISHU_USER_ACCESS_TOKEN / FEISHU_USER_REFRESH_TOKEN。"
                    f"原始错误: {detail}"
                ) from e
            logger.warning(f"[FeishuKnowledge] 方案A 失败，降级到方案B: {detail}")

        # 方案 B（降级）：创建 docx 后 move_docs_to_wiki
        # ① 创建 docx
        doc_resp = feishu_post("/docx/v1/documents", json={"title": title})
        doc_id = doc_resp["data"]["document"]["document_id"]

        # ② 移入 wiki（space 级标识时不传 parent_wiki_token → 移到根节点）
        move_payload: dict = {"obj_type": "docx", "obj_token": doc_id}
        if not self._is_space_level_token(parent_wiki_token):
            move_payload["parent_wiki_token"] = parent_wiki_token
        try:
            move_resp = self._wiki_post(
                f"/wiki/v2/spaces/{self.space_id}/nodes/move_docs_to_wiki",
                json=move_payload,
            )
        except Exception as e:
            detail = str(e)
            if "131006" in detail:
                raise RuntimeError(
                    f"wiki 空间权限不足（error 131006）：move_docs_to_wiki 需要应用有空间编辑权限，"
                    f"或配置 FEISHU_USER_ACCESS_TOKEN / FEISHU_USER_REFRESH_TOKEN。"
                    f"已创建的独立文档 doc_id={doc_id} 可通过 /docx/{doc_id} 访问，"
                    f"但未移入 wiki 空间。"
                ) from e
            raise
        move_data = move_resp.get("data", {})
        logger.info(f"[FeishuKnowledge] 方案B move_docs_to_wiki 响应: {move_data}")

        # 飞书 API 有两种返回：同步完成返回 wiki_token，异步返回 task_id
        # ③-a 同步完成：直接返回 wiki_token
        wiki_token = move_data.get("wiki_token", "")
        if wiki_token:
            logger.info(f"[FeishuKnowledge] 方案B 同步完成: {title!r} → {wiki_token}")
            return wiki_token

        # ③-b 异步模式：轮询 task_id
        task_id = move_data.get("task_id", "")
        if not task_id:
            raise RuntimeError(
                f"move_docs_to_wiki 响应缺少 task_id 和 wiki_token，完整响应: {move_resp}"
            )

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
    # 追加富文本块到页面末尾
    # ------------------------------------------------------------------ #
    def append_blocks_to_page(self, wiki_url_or_token: str, blocks: list, chunk_size: int = 40):
        """
        向页面末尾追加飞书 docx 块列表（富文本格式）。

        blocks 是由 integrations.feishu.rich_text.md_to_feishu_blocks() 生成的块列表。
        每批最多 chunk_size 个块，批次间休眠 0.3s 防限速。
        """
        import time
        wiki_token = parse_wiki_token(wiki_url_or_token)
        obj_token, _ = wiki_token_to_obj_token(wiki_token)
        if not obj_token:
            raise ValueError(f"无法解析 wiki token: {wiki_token}")
        for i in range(0, len(blocks), chunk_size):
            batch = blocks[i : i + chunk_size]
            feishu_post(
                f"/docx/v1/documents/{obj_token}/blocks/{obj_token}/children",
                json={"children": batch, "index": -1},
            )
            if i + chunk_size < len(blocks):
                time.sleep(0.3)

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
