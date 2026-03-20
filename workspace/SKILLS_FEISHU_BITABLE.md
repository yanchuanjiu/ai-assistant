# SKILL: 飞书多维表格 & 任务管理

> 触发时机：用户提到多维表格、Bitable、任务、待办、清单时注入。

---

## 快速索引：意图 → 工具 → 必填参数

| 用户意图 | 工具 | 必填参数 |
|----------|------|----------|
| 查看表格有哪些字段/视图 | `feishu_bitable_meta` | `action="list_fields"`, `app_token`, `table_id` |
| 查询/筛选记录 | `feishu_bitable_record` | `action="list"`, `app_token`, `table_id` |
| 新增记录 | `feishu_bitable_record` | `action="create"`, `app_token`, `table_id`, `fields` |
| 更新记录 | `feishu_bitable_record` | `action="update"`, `app_token`, `table_id`, `record_id`, `fields` |
| 删除记录 | `feishu_bitable_record` | `action="delete"`, `app_token`, `table_id`, `record_id` |
| 创建任务 | `feishu_task_task` | `action="create"`, `summary`（标题） |
| 查询任务 | `feishu_task_task` | `action="list"` 或 `action="get"`, `task_id` |
| 创建任务清单 | `feishu_task_tasklist` | `action="create"`, `name` |

---

## 核心约束（Schema 未透露的知识）

**app_token 获取**：从多维表格 URL 提取，格式 `https://xxx.feishu.cn/base/{app_token}`，不是 wiki token。

**table_id 获取**：先调 `feishu_bitable_meta(action="list_tables", app_token=...)` 获取，不要猜测。

**fields 格式**：字段值类型取决于字段类型：
- 文本字段：`{"字段名": "文本内容"}`
- 数字字段：`{"字段名": 123}`
- 单选字段：`{"字段名": "选项名"}`（选项名必须已存在，否则报错）
- 多选字段：`{"字段名": ["选项A", "选项B"]}`
- 人员字段：`{"字段名": [{"id": "open_id"}]}`
- 日期字段：`{"字段名": 1711900800000}`（毫秒时间戳）

**权限要求**：多维表格需要应用有 `bitable:app` 权限，且页面已添加应用为协作者。

**任务 open_id**：创建任务时负责人/关注人需要传 `open_id`，可通过 `feishu_im_get_messages` 中的 sender 字段获取。

---

## 常见错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| 400 invalid field value | 单选/多选传了不存在的选项 | 先 `list_fields` 查看可用选项 |
| 403 forbidden | 应用未被添加为表格协作者 | 告知用户在表格设置中添加应用 |
| record_id not found | record_id 已被删除或传错 | 重新 `list` 获取最新 record_id |
