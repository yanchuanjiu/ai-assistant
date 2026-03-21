# Changelog

## v0.9.9 - 2026-03-21

### Added
- **飞书 / 钉钉 同话题回复线程化**：同一 `thread_id` 下的后续回复自动使用「回复原文」方式，利用 IM 线程实现上下文视觉隔离
  - **飞书**：新增 `_thread_anchor` 注册表（thread_id → 首条 message_id），调用 `ReplyMessageRequest` 的 `reply_in_thread=True` API；超长消息降级为普通发送
  - **钉钉**：新增 `_thread_anchor` 注册表（thread_id → 首条 incoming 对象），通过 `session_webhook` 回复到原消息线程；webhook 过期后自动清除并降级为 `send_text`
  - 对话首条消息仍正常发送，后续回复自动附线程；话题切换时（`#话题名`）单独维护话题维度的锚点

## v0.9.8 - 2026-03-21

### Added
- **多话题并行对话**：同一 IM 聊天窗口支持 `#话题名` 前缀隔离对话上下文，不同话题并行处理
  - 新增 `integrations/topic_manager.py`：话题注册、thread_id 生成、列表格式化、欢迎消息
  - 话题 thread_id 格式：`{platform}:{chat_id}#topic#{safe_name}`，通过 SQLite checkpointer 自然隔离历史
  - 锁机制从 **per-chat** 改为 **per-thread**：同一聊天不同话题可真正并行执行 Agent
  - 新增 `/topics` 斜杠命令：飞书和钉钉均支持，列出活跃话题（7天TTL）
  - 话题切换（`#话题名` 无消息体）：提示已切换并展示话题列表，不触发 Agent
  - 问候快速路径更新：在欢迎消息中说明多话题用法
- **性能优化**：锁粒度降低后，多话题场景下不同话题的响应互不阻塞
- **工具兼容**：`get_recent_chat_context` 正确处理话题 thread_id（提取真实 chat_id）
- **`AgentState` 扩展**：新增 `thread_id` 字段，供 `agent_node` 和 `tools_node` 使用，避免从 platform:chat_id 重建导致话题信息丢失

## v0.9.7 - 2026-03-21

### Changed
- **移除上下文轮次截断，保留工具内容限制**
  - 根因：`MAX_USER_TURNS=2` 导致 LLM 只能看到最近 2 轮对话历史，无法理解跨轮次的任务背景和用户意图
  - 修改：删除 `MAX_USER_TURNS` 常量及按轮截断逻辑，完整对话历史均传给 LLM
  - 保留：`HISTORY_TOOL_CONTENT_LIMIT=300` 对历史 ToolMessage 内容截断，防止旧工具结果（飞书页面内容等）占用大量 token
  - 重命名：`_trim_to_user_turns()` → `_trim_tool_content()`，函数职责更清晰
  - 调用处注释更新，反映新的截断语义
  - Token 分析（基于 logs/llm.jsonl 近 50 条）：平均 prompt 22,660 tokens，最低 5,945，最高 36,649；火山云 doubao-pro-32k 上下文 32K tokens，完整历史策略在正常对话长度下有充足空间

---

## v0.9.6 - 2026-03-21

### Fixed
- **飞书 OAuth：已登录状态下仍触发重新授权流程**
  - 根因：`feishu_oauth_setup` 工具无状态检查入口，LLM 遇到 token 相关错误（99991668/131006）时直接调用 `get_auth_url` 要求用户重新授权，即使 token 实际仍有效
  - 修复：新增 `action="check_status"` —— 先检查 token 是否有效/已过期；过期且有 refresh_token 时自动续期（复用 client.py 刷新逻辑）；只有确认无法续期时才返回"需要重新授权"
  - 修复：工具 docstring 增加强制规则：遇到 token 错误时**必须先调用 check_status**，check_status 返回"有效"或"已自动续期"则不得再触发 OAuth 流程
  - 修复：`expires_at == 0` 的手动配置 token 在 check_status 中正确识别为有效（与 get_user_access_token 逻辑一致）

## v0.9.5 - 2026-03-21

### Fixed
- **飞书 wiki 根节点查询返回空列表（131006 被静默忽略）**
  - 根因：飞书 API 有时以 HTTP 200 响应返回 `{"code": 131006, ...}`，旧代码只检测 HTTP 4xx/5xx 异常，131006 未被捕获 → `items=[]` 静默返回
  - 修复：`FeishuKnowledge.list_wiki_children` 和 `create_wiki_child_page` 在每次 `_wiki_get`/`_wiki_post` 后主动检查 `resp.get("code", 0)`，非 0 时抛出 RuntimeError，确保 131006 正确触发 fallback 流程
  - 影响：之前空间根节点遍历返回空列表 → 现在正确报错并走 `FEISHU_WIKI_ROOT_NODES` 降级或提示用户配置

## v0.9.4 - 2026-03-21

### Fixed
- **飞书 user_access_token 配置，修复 131006 权限错误**
  - `.env` 写入 `FEISHU_USER_ACCESS_TOKEN` / `FEISHU_USER_TOKEN_EXPIRES_AT` / `FEISHU_APP_SECRET`
  - `integrations/feishu/client.py`：`get_user_access_token()` 新增兼容逻辑，当 `FEISHU_USER_TOKEN_EXPIRES_AT=0` 但 token 存在时，视为新鲜 token（避免无 expires_at 配置时强制走刷新路径）

### Added
- **`feishu_oauth_setup` 工具**（`graph/tools.py`）：飞书 OAuth 授权全流程工具
  - `action="get_auth_url"`：生成授权链接，发给用户在浏览器打开
  - `action="exchange_code"`：接收用户从地址栏复制的 code，换取 access_token + refresh_token，写入 .env，立即生效
  - 注册到 `feishu_wiki` 分类，关键词 "oauth/授权/token/权限/131006" 触发
  - 从此 user token 可通过 refresh_token 自动续期，无需人工干预

## v0.9.3 - 2026-03-21

### Refactor
- **提示词系统深度精简（减法优先，Opus 分析）**
  - `prompts/system.md`：262行→62行（-76%），移除所有工具能力列表、API错误处理表、重复说明、多任务并发步骤等冗余内容
  - 死循环根本修复：新增一句「权限不足/配置缺失/需人工操作：告知用户后停止，不要自主修复系统配置」
  - `workspace/SOUL.md`：「先尝试解决」后加限定「但遇到权限不足或需要人工操作的障碍时，直接告知主人」
  - `workspace/MEMORY_CORE.md`：移除「OAuth 是绕过方案」暗示，改为明确说明需管理员配置
  - `graph/tools.py`：`feishu_read_page` docstring 移除「失败时先用 list_children 重新发现」重试指令

### Root cause analysis
- 死循环由5条指令合力触发：SOUL.md「先尝试」无停止条件 + system.md「不能声称未集成」+ system.md「主动组合工具」+ system.md「失败给备选方案」+ MEMORY_CORE.md「OAuth是绕过方案」
- 修复策略：减法+最小加法，代码层 MAX_TOOL_ITERATIONS=5 作为兜底

## v0.9.2 - 2026-03-21

### Fixed
- **Agent 死循环防护（`graph/nodes.py`）**
  - 新增 `MAX_TOOL_ITERATIONS = 5`：每轮对话最多 5 次工具调用迭代，超限直接终止并告知用户
  - 新增 `_count_tool_iterations()`：统计当前轮（最后一条 HumanMessage 之后）已发起的 AIMessage tool_calls 次数
  - 新增 `_check_user_interaction_needed()`：检测工具结果中的"需要用户手动操作"信号（如 OAuth URL、EOF 交互错误、连续3次相同失败）→ 提前终止并提示用户手动处理
  - 根因：17:38–18:01 的 23 分钟死循环源于 OAuth user_access_token 获取流程需要浏览器交互，agent 无法获取 code 却不断重试（20+ 次 LLM 调用）

## v0.9.1 - 2026-03-21

### Fixed
- **131006 权限错误根因分析与降级修复（`integrations/feishu/knowledge.py`）**
  - 根因确认：`wiki:wiki` 应用权限 ≠ wiki 空间成员权限；`FEISHU_USER_ACCESS_TOKEN` 从未写入 .env
  - 新增 `_list_wiki_root_nodes_fallback()`：当 list_wiki_children 遇到 131006 时，读取 `FEISHU_WIKI_ROOT_NODES` 配置（逗号分隔的已知根节点 wiki token），通过 `get_node` API（tenant token 可用）返回节点信息
  - 优化 131006 错误信息：改为三选一的具体行动指南（FEISHU_WIKI_ROOT_NODES / user token / 空间成员）
  - 修复 `import os` 缺失（原文件未 import os）

### Docs
- **`CLAUDE.md`**：明确 wiki:wiki 权限 vs 空间成员权限的区别，新增 FEISHU_WIKI_ROOT_NODES 配置说明
- **`workspace/MEMORY.md`**：更新 131006 根因分析和三选一解决方案，更新至 83 条交互统计
- **`workspace/HEARTBEAT.md`**：新增飞书权限配置检查（每天一次，检测 .env 缺少 user token / root nodes 配置）

## v0.9.0 - 2026-03-21

### Added
- **`integrations/feishu/bot.py`**：全面升级飞书消息处理能力
  - **消息去重**：基于 message_id 的 2min TTL 去重，防止 WebSocket 断线重连时重放触发双响应
  - **每 chat 串行锁**：同一 chat 同时只处理一条消息，防止快速连发导致乱序回复
  - **非文本消息支持**：文本/富文本(post)/合并转发/图片/文件/音视频/卡片均有处理，不再静默丢弃
  - **合并转发展开**：调用 IM API 获取子消息列表，将内容展开传给 AI
  - **post 富文本发送**：改用 `msg_type=post` + `tag=md`，Markdown 在飞书客户端正确渲染（加粗/代码块/标题等）；post 失败自动降级纯文本
- **`graph/tools.py`**：新增三类飞书工具
  - **`feishu_calendar_event`**：日历日程 CRUD（create/get/list/update/delete/search/freebusy），需 `calendar:calendar` 权限
  - **`feishu_spreadsheet`**：电子表格操作（create/get_meta/read_values/write_values/append_values）
  - **`feishu_chat_info`**：群聊和用户信息（list_chats/get_chat/list_members/get_user）
  - 更新 `CATEGORY_KEYWORDS["feishu_advanced"]`：新增日历/电子表格/群聊相关触发词

### Fixed
- 修复非文本消息（图片、文件、合并转发等）发送给机器人后完全沉默的问题
- 修复 AI 回复中的 Markdown 格式（`##`、`**` 等）在飞书 IM 显示为原始符号的问题

---

## v0.8.30 - 2026-03-21

### Fixed
- **`integrations/feishu/knowledge.py`**：`list_wiki_children` 根节点分支和子节点分支遇到 error 131006 时，原来静默返回空列表导致 `find_or_create_child_page` 继续尝试创建页面（同样 131006），造成级联失败。现在改为遇到 131006 立即抛出明确权限错误，终止后续无意义的创建操作，直接向用户呈现可操作的修复建议。

---

## v0.8.29 - 2026-03-21

### Fixed
- **`integrations/feishu/knowledge.py`**：修复飞书 wiki space API 400 错误（error 131006：应用缺少空间编辑权限）
  - 新增 `_wiki_get` / `_wiki_post` 辅助方法：user_access_token 优先，未配置/401/403 自动降级 tenant_access_token
  - `list_wiki_children` 改用 `_wiki_get`（支持有 user token 时正常列出根节点和子节点）
  - `create_wiki_child_page` 方案A/B 改用 `_wiki_post`；检测到 131006 时跳过方案B直接抛出明确错误信息，避免创建孤立 docx
  - 方案B `move_docs_to_wiki` 也捕获 131006 并附带 doc_id 提示已创建的独立文档
- **`integrations/feishu/client.py`**：新增 `_raise_with_body` 辅助函数；`feishu_get` / `feishu_post` / `feishu_delete` / `feishu_get_user` / `feishu_post_user` 统一在错误响应中包含 body（原先 `move_docs_to_wiki` 400 错误无法看到具体错误码）

### Root Cause
飞书 wiki space 级 API（`POST/GET /wiki/v2/spaces/{id}/nodes`、`move_docs_to_wiki`）要求 tenant 应用在 wiki 空间有编辑权限（error 131006）。
原代码方案A失败后无条件降级方案B，但方案B的 `move_docs_to_wiki` 同样需要空间权限，导致循环失败；
且 400 响应体无法被看到。

### 解决路径（运行时）
1. **有 user_access_token**（`.env` 配置 `FEISHU_USER_ACCESS_TOKEN` 或 `FEISHU_USER_REFRESH_TOKEN`）→ 自动使用 user token，无需额外授权
2. **无 user token**：需 wiki 空间管理员在「空间设置 → 成员管理」添加应用并授予「编辑」权限

---

## v0.8.28 - 2026-03-21

### Fixed
- **`integrations/feishu/knowledge.py`** `list_wiki_children`：修复空间根节点无法列举的问题 — 原代码对 space 级标识直接返回空列表，导致 LLM 无法浏览知识库第一层文档；现在不传或传 space 级标识时，调用 Feishu API 不带 `parent_node_token` 来列出根节点
- **`graph/tools.py`** `feishu_wiki_page`：`list_children` 不再要求必须传 parent_wiki_token；不传时默认从空间根节点开始，方便 LLM 探索用户文档结构
- **`prompts/system.md`**：新增"飞书知识库浏览起点"章节，明确规定从空间根节点（不传 parent）开始浏览用户文档，禁止从 `FEISHU_WIKI_CONTEXT_PAGE`（AI 专用页）开始

### 根因分析
用户反馈飞书操作从"首页"而非"空间根节点"开始，导致错误创建页面。根因：`feishu_wiki_page(list_children)` 要求必须传 parent_wiki_token，LLM 找不到合适入口时默认用 FEISHU_WIKI_CONTEXT_PAGE 作起点，该页面只是 AI 助理自己的快照页，看不到用户的项目目录。

---

## v0.8.27 - 2026-03-21

### Added
- **`graph/parallel.py`**（新文件）：并发任务框架
  - `TaskMonitor`：线程安全任务状态追踪（pending → running → done/failed），支持近期任务查询和统计摘要
  - `AgentTaskQueue`：优先级任务队列（URGENT=0 用户消息 / HIGH=1 / NORMAL=2 调度任务 / LOW=3 维护任务），内置 4 worker ThreadPoolExecutor + 独立 dispatcher 线程
  - `run_tools_parallel()`：并行执行同一轮 LLM 下发的多个工具调用；含副作用工具（`_SERIAL_TOOLS`）自动降级为串行，保持原始顺序返回

### Changed
- **`graph/nodes.py`** `tools_node`：改用 `run_tools_parallel()` 替代串行循环，多工具调用并发执行（最多 6 worker），单工具调用保持同步快速路径
- **`graph/agent.py`** `invoke()`：接入 `task_monitor` 追踪每次调用生命周期；按平台自动设置优先级（用户消息=URGENT，scheduler=NORMAL）；新增 `get_concurrent_status()` 函数供工具/Admin查询实时状态
- **`graph/tools.py`**：新增 `query_task_status` 工具（加入 CORE_TOOLS），支持按需查询正在执行的任务、队列大小、近期任务历史
- **`scheduler.py`** `poll_email` / `heartbeat`：调度任务改为通过 `AgentTaskQueue` 提交（NORMAL / LOW 优先级），不再阻塞 APScheduler 线程，且不与用户实时消息竞争

---

## [0.8.26] - 2026-03-21

### Fixed
- **`graph/nodes.py`**：修复火山云 Ark 缺少 `<|FunctionCallBegin|>` 标记时工具调用解析失败问题 — 新增 `_FUNC_CALL_NO_BEGIN_RE` 正则作为 fallback，兼容 `[{...}]<|FunctionCallEnd|>` 格式，避免用户收到"工具调用格式异常"错误

---

## [0.8.25] - 2026-03-21

### Added
- **`tests/regression/test_volcengine_parser.py`**（18用例）：火山云文本格式工具调用解析器 `_extract_text_tool_calls` 全场景覆盖 — 单/多工具调用、双Begin变体、格式损坏安全降级、parameters/arguments字段兼容
- **`tests/regression/test_error_tracker.py`**（25用例）：error_tracker 全路径 — `detect_error_in_response` 关键词检测与误报过滤、`record_error` 计数递增、`get_fix_status` 状态读取、GitHub Issue 创建（mock subprocess）、自我改进报告不触发误报、并发安全
- **`tests/regression/test_tool_invocation.py`**（31用例）：核心工具调用路径（mock API）— `agent_config` get/set/delete/list（临时 SQLite）、`get_service_status` crash.log解析、`run_command`/`python_execute` 执行与超时、`list/kill_claude_sessions` tmux mock、Bitable placeholder guard、`get_recent_chat_context` thread_id 解析
- **`tests/regression/test_concurrency.py`**（6用例）：并发安全 — SQLite meeting.db 并发 INSERT 唯一性、config_store 并发读写一致性、error_tracker 并发记录无竞态
- **`tests/regression/test_context_management.py`** 追加 CTX-4x（5用例）：跨轮上下文连续性 — 飞书/bitable/claude 工具连续性保持、指代消解场景、多轮 trim 正确性
- **`tests/regression/run_all.py`**：新增 volcengine / tracker / tools / concurrency 四个可选 suite

---

## [0.8.24] - 2026-03-21

### Changed
- **文档重组**：`CLAUDE.md` 精简为纯"机器指令"文件（删除工具表、目录结构、技术栈表、版本历史），减少每次提交需要同步的文件数
- **`CHANGELOG.md`** 成为唯一版本历史，补入 v0.8.6~v0.8.23 所有记录
- **自迭代规则更新**：每次提交只强制维护 `CLAUDE.md`（状态/坑点）+ `CHANGELOG.md`（变更记录），`README.md` 和 `docs/` 仅大变化时更新

---

## [0.8.23] - 2026-03-21

### Fixed
- **飞书 wiki token 使用规则**（`prompts/system.md`）：新增专节，禁止 LLM 使用记忆/猜测 token，明确获取有效 token 的唯一正确方式，含 400 错误恢复流程
- **`feishu_bitable_meta` / `feishu_bitable_record`**（`graph/tools.py`）：函数体开头加 placeholder 校验，传入无效 app_token 直接返回错误提示而非发起 400 调用
- **`wiki_token_to_obj_token`**（`integrations/feishu/knowledge.py`）：空 obj_token 从静默失败改为 WARNING 日志并输出完整 API 响应

### Changed
- **`feishu_read_page` / `feishu_wiki_page` / `feishu_bitable_meta` / `feishu_bitable_record`** docstring 追加 token 使用警告和获取方式说明

---

## [0.8.22] - 2026-03-21

### Changed
- **`graph/nodes.py`**：`MAX_USER_TURNS=2`（原5）；历史 ToolMessage 截断至前 100 字符（原300）
- **`graph/tools.py`**：新增 `get_recent_chat_context` 工具（飞书 IM 读取最近 N 条消息），加入 CORE_TOOLS
- **`prompts/system.md`**：新增"问候与按需历史"节——纯问候直接回复；含引用词时先调 `get_recent_chat_context`
- **`integrations/feishu/bot.py` / `integrations/dingtalk/bot.py`**：问候快速路径，精确匹配纯问候词直接回复，不走 LLM
- **`workspace/SKILLS_PROJECT_MGMT.md`**：重写为摘要版（~1KB）
- **`workspace/SKILLS_PROJECT_MGMT_TEMPLATES.md`**（新建）：完整文档模板，按需读取

---

## [0.8.21] - 2026-03-20

### Changed
- **`graph/nodes.py`**：`_build_system_prompt()` 按需加载——`SKILLS_PROJECT_MGMT.md` 仅含项目管理关键词时注入；`MEMORY.md` 简单消息（<30字）时跳过
- **`integrations/logging/interaction_logger.py`**：新增 `slow_response` 字段（latency_ms > 15000）
- **`workspace/HEARTBEAT.md`**：新增响应速度监控任务（>15s 比例超 30% 时汇报）
- **`graph/tools.py`**：`trigger_self_improvement` 新增响应延迟专项分析节

---

## [0.8.20] - 2026-03-20

### Fixed
- **上下文污染**（`graph/nodes.py`）：`_trim_to_user_turns()` 对非当前轮 ToolMessage 截断至 300 字符，防止旧任务工具结果污染新任务上下文

### Changed
- **`prompts/system.md`**：新增"跨任务上下文隔离"节，LLM 以当前消息为准忽略历史工具结果噪声
- **`workspace/MEMORY.md` / `workspace/HEARTBEAT.md`**：更新 token 监控基准

---

## [0.8.19] - 2026-03-20

### Changed
- **`integrations/meeting/analyzer.py`**：`write_to_feishu` / `write_to_project_page` 升级为调用 `append_blocks_to_page + md_to_feishu_blocks`，纯文本保留为降级兜底
- **`integrations/feishu/knowledge.py`**：新增 `append_blocks_to_page()`

### Added
- **`integrations/feishu/rich_text.py`**（新建）：Markdown → 飞书 docx 块转换器（标题/加粗/斜体/列表/代码块/分割线）
- **`tests/regression/test_meeting_format.py`**（新建）：29 个格式化单元测试

---

## [0.8.13] - 2026-03-20

### Added
- **`integrations/meeting/daily_migration.py`**（新建）：`DailyMigrationPlugin`，每天 08:00 自动检查钉钉新会议纪要并以富文本迁移到飞书，保留原始文档时间
- **`trigger_daily_migration` / `list_daily_migrations`** 工具（`graph/tools.py`）

### Changed
- **`scheduler.py`**：新增 `daily_meeting_migration()` + cron job（每天 08:00）
- **`integrations/dingtalk/docs.py`**：`_normalize_node()` 新增 `created_at` 字段

---

## [0.8.11] - 2026-03-20

### Added
- **`integrations/logging/error_tracker.py`**（新建）：错误关键词检测、出现次数追踪、GitHub Issue 创建
- **自动修复机制**（`graph/agent.py`）：回复含错误关键词时后台触发 Claude Code 修复；同一错误第3次停止自动修复并创建 GitHub Issue

---

## [0.8.10] - 2026-03-20

### Changed
- **`graph/nodes.py`**：`_trim_to_user_turns()`（MAX_USER_TURNS=5）；短消息快速返回 CORE_TOOLS（<25字符）
- **`graph/tools.py`**：`trigger_self_improvement` 新增重复问题检测（相同话题≥2次）和上下文健康检查节
- **`prompts/system.md`**：新增"对话重置"节（5轮截断机制说明）

---

## [0.8.9] - 2026-03-20

### Fixed
- **`admin/server.py`**：`HTTPServer.allow_reuse_address = True` + `SO_REUSEADDR`，解决重启时端口 8080 持续占用

### Changed
- **`workspace/MEMORY.md` / `workspace/USER.md` / `workspace/HEARTBEAT.md`**：基于31条交互日志完整填充

---

## [0.8.8] - 2026-03-20

### Fixed
- **飞书 wiki 根目录 400 Bad Request**（`integrations/feishu/knowledge.py`）：
  - `list_wiki_children`：收到 space 级标识时跳过 `GET nodes`，直接返回空列表走创建分支
  - `create_wiki_child_page`：`obj_type` 从 `"wiki"` 改为 `"docx"`
- **`graph/tools.py`**：`feishu_wiki_page` / `feishu_project_setup` 调用前用 `parse_wiki_token()` 清理 parent_wiki_token

---

## [0.8.7] - 2026-03-20

### Added
- **`integrations/meeting/project_router.py`**（新建）：`ProjectRouter` 类，识别项目并路由到飞书子页面
- **`feishu_project_setup` 工具**（`graph/tools.py`）：一键创建敏捷项目文件夹（6文档）
- **会议纪要自动路由**：`analyze_meeting_doc` 接入项目路由，写入 `04_会议纪要` 子页；RAID 元素写入 `06_RAID 日志`

### Changed
- **`prompts/meeting_analysis.md`**：新增提取字段（project_name/code/raid_elements/milestone_impact）
- **`integrations/feishu/knowledge.py`**：新增 `_PROJECT_DOCS` / `_PROJECT_TEMPLATES` 常量 + `bootstrap_project()`

---

## [0.8.6] - 2026-03-20

### Added
- **IM 长回复自动压缩**（`integrations/feishu/bot.py`）：超 800 字符时调用 `_save_to_feishu_wiki()` 存飞书，IM 发前 300 字摘要 + wiki 链接；API 失败时降级分段发送

### Changed
- **`prompts/system.md`**：新增"IM 回复规范"节（IM ≤800字符，超出写飞书页面发摘要+链接）

---

## [0.8.5] - 2026-03-19

### Added
- **`workspace/SKILLS_PROJECT_MGMT.md`**：IT 项目集管理 Skill
  - 知识库页面结构规范（项目文件夹 → 章程/技术方案/周报/RAID/会议纪要五种子页面）
  - 五种文档的完整 Markdown 模板（含字段说明）
  - 写入前治理检查规则（文档归属 / 类型匹配 / 模板选择）
  - 新建项目时自动引导创建章程页面

### Changed
- **`graph/nodes.py`**：`_build_system_prompt()` 新增注入 `SKILLS_PROJECT_MGMT.md`（label: `SKILL_PROJECT_MGMT`），动态加载，无需重启
- **`prompts/system.md`**：
  - 新增"写入前治理检查（项目类文档）"节：写入章程/技术方案/周报/RAID 等文档前执行归属确认 + 模板匹配
  - 新增"多任务识别与并行处理"节：识别独立子任务 → 并行工具调用 → 分主题汇报；长任务支持多 Claude Code 会话并行启动
- **`graph/tools.py`**：`CATEGORY_KEYWORDS["feishu_wiki"]` 新增 14 个项目管理触发词（项目/章程/周报/里程碑/需求文档/技术方案/风险/raid/复盘/项目集/portfolio/上线/验收/立项）

---

## [0.8.4] - 2026-03-19

### Changed
- **`prompts/system.md`** + **`workspace/SOUL.md`**：整体重写，明确"飞书知识库主动维护者"定位
  - Agent 首要职责：主动保持飞书知识库内容完整和及时，而非被动问答
  - 工具诚实性原则：工具列表里有什么能力就有什么，不能声称未集成
  - 简洁行动原则：先做再说，不解释计划，完成后一句话告知

---

## [0.8.3] - 2026-03-19

### Fixed
- **`graph/nodes.py`**：修复火山云文本格式工具调用泄漏（`_extract_text_tool_calls` 解析后残留文本混入最终回复）

### Changed
- **`graph/agent.py`**：消息层解耦——`invoke()` 只返回文本，bot handler 负责发送，消除跨层依赖
- 新增斜杠命令支持（`/status`、`/sessions` 等快捷指令路由）

---

## [0.7.6] - 2026-03-18

### Added
- **回归测试套件**（`tests/regression/`）：
  - `test_feishu_wiki.py`：14 用例（读取/追加/子页面/工具端到端），全部通过
  - `test_dingtalk_mcp.py`：8 用例（MCP工具加载/搜索/节点列表/参数验证），全部通过
  - `test_e2e_pipeline.py`：11 用例（LLM分析/写飞书/去重），8通过3跳过（LLM超时外部依赖）
  - `run_all.py`：CLI 入口，支持 `python tests/regression/run_all.py [feishu|dingtalk|e2e]`
- **飞书子页面创建**（`integrations/feishu/knowledge.py`）：
  - `list_wiki_children(parent_wiki_token)` — 列出子页面（`/wiki/v2/spaces/{id}/nodes`）
  - `create_wiki_child_page(title, parent_wiki_token)` — 两步创建：`POST /docx/v1/documents` → `move_docs_to_wiki` 异步任务轮询 → 返回 `node_token`（全程 tenant token，无需 user OAuth）
  - `find_or_create_child_page(title, parent, cache_key)` — 三级缓存：config_store → list_children 精确匹配 → create
- **`feishu_wiki_page` 工具**（`graph/tools.py`）：子页面管理（`list_children` / `find_or_create`），加入 `feishu_wiki` 分类
- **`_get_or_create_meeting_page()`**（`integrations/meeting/analyzer.py`）：`write_to_feishu` 自动在 context page 下创建"📋 会议纪要汇总"子页面

### Fixed
- **`_append_text` 超 50 块限制**（`integrations/feishu/knowledge.py`）：分批写入（每批40行，批间 sleep 0.3s），修复大段内容追加时的 400 错误

---

## [0.7.5] - 2026-03-18

### Fixed
- **钉钉文档 URL 访问**（`integrations/dingtalk/docs.py`）：
  - 新增 `extract_node_id_from_url()`，支持直接传入 alidocs URL
  - `_list_wiki_nodes` 扩充响应格式（`result.*` / `nodeList` / 列表），升级日志输出
  - `_normalize_node` 新增 `object_id` 字段
  - `read_file_content` 支持 URL 输入 + 更完整内容字段解析
- **`read_meeting_doc` 工具**（`graph/tools.py`）：支持 URL 输入，失败时提示改用 MCP `get_document_content`

### Changed
- **`prompts/system.md`**：新增原则——收到 alidocs URL 时直接提取 nodeId 调用 `get_document_content`，禁止 `web_fetch`/`feishu_read_page`（需登录的内容无法通过 HTTP 抓取）

---

## [0.7.4] - 2026-03-18

### Changed
- **`prompts/system.md`**：替换"会议与文档"节，新增"钉钉文档（MCP）"+"钉钉AI表格（MCP）"+"会议纪要流水线"三节，LLM 可感知 MCP 工具全量能力
- **`graph/tools.py`**：
  - `TOOL_CATEGORIES["meeting"]` 移除旧工具 `get_latest_meeting_docs` / `read_meeting_doc`（钉钉文档读取由 MCP 承担）
  - `CATEGORY_KEYWORDS["dingtalk_mcp"]` 加入 `"钉钉"` / `"dingtalk"`，扩充触发词
  - `CATEGORY_KEYWORDS["meeting"]` 移除 `"钉钉"` / `"dingtalk"`，避免路由冲突
  - `analyze_meeting_doc` docstring：file_id 来源从 `get_latest_meeting_docs` 改为 MCP 工具
- **`CLAUDE.md` / `README.md`**：同步状态表、版本历史、工具表至 v0.7.4

---

## [0.7.3] - 2026-03-18

### Changed
- **`main.py`**：完全重写，去除 FastAPI/uvicorn HTTP 层
  - `_supervised(name, target, base_delay=5, max_delay=300)`：每个 bot 线程独立 supervised，崩溃后指数退避自动重启（5s→10s→…→5min）
  - 写 `logs/service.pid`（主进程 PID，方便 kill 重启）
  - `signal.signal(SIGTERM/SIGINT)` 优雅关闭（sched.stop + Event.set）
  - 崩溃信息写入 `logs/crash.log`（JSONL：time/thread/error/traceback）
- **`requirements.txt`**：删除 `fastapi>=0.115.0`、`uvicorn[standard]>=0.32.0`、`python-multipart>=0.0.20`
- **`graph/tools.py`**：`get_service_status` 末尾追加读取 `logs/crash.log` 最近 5 条

### Migration
```bash
# 旧（kill by port）
kill $(lsof -ti:8000) 2>/dev/null
nohup python main.py >> logs/app.log 2>> logs/server.log &

# 新（kill by PID file）
kill $(cat logs/service.pid 2>/dev/null) 2>/dev/null
nohup python main.py >> logs/app.log 2>&1 &
```

---

## [0.7.2] - 2026-03-18

### Added
- **`integrations/storage/config_store.py`**：SQLite key-value 配置存储（复用 `data/memory.db`）
  - `get(key)` / `set(key, value)` / `delete(key)` / `list_all()`
- **`agent_config` tool**（`graph/tools.py`）：对话中直接读写运行时配置，无需重启
  - 加入 `CORE_TOOLS`（每次必带）

### Changed
- **`integrations/meeting/analyzer.py`**：`write_to_feishu` 优先读 config_store 的 `FEISHU_WIKI_MEETING_PAGE`，fallback `.env`
- **`integrations/dingtalk/docs.py`**：
  - `__init__` 优先读 config_store 的 `DINGTALK_DOCS_SPACE_ID`
  - `read_file_content` 自动探测有效 API 路径并写入 `DINGTALK_WIKI_API_PATH`，后续直接使用

---

## [0.7.1] - 2026-03-18

### Added
- **渐进式工具披露**（Progressive Tool Disclosure）：87% token 节省
  - `CORE_TOOLS`（7个）：每次必带（web_search/web_fetch/python_execute/run_command/get_system_status/get_service_status/agent_config）
  - `TOOL_CATEGORIES`：按消息关键词动态注入（feishu_wiki/feishu_advanced/meeting/claude 四类）
  - `CATEGORY_KEYWORDS`：关键词 → 分类映射，`agent_node` 每次根据用户消息匹配后追加

### Fixed
- **`integrations/dingtalk/client.py`**：`get_current_user_unionid` API 路径 `/v1.0/contact/users/me` → `/v2.0/users/me`

---

## [0.7.0] - 2026-03-18

### Added
- **会议纪要闭环**（`integrations/meeting/`）：
  - `analyzer.py`：调用火山云 LLM 分析会议纪要 → 结构化 JSON → 追加写飞书知识库页面
  - `tracker.py`：SQLite（`data/meeting.db`）记录已处理 `doc_id`，避免重复分析；非会议文档标记 `not_meeting`
  - `prompts/meeting_analysis.md`：会议纪要深度分析 prompt（钉钉文档场景）
- **`analyze_meeting_doc` tool**：按需触发单篇文档分析，支持 `force=true` 重新分析
- **`list_processed_meetings` tool**：查看已分析文档列表
- **LLM 调用日志**（`logs/llm.jsonl`）：每次 LLM 调用记录一行 JSONL（model/latency/usage/tool_calls）

### Changed
- **`scheduler.py`**：新增 `poll_dingtalk_meetings()`（每30分钟轮询）
- **`graph/nodes.py`**：每次 LLM 调用后写入 `logs/llm.jsonl`

---

## [0.6.1] - 2026-03-18

### Added（Claude Code 自动迭代完成）
- **6 个新飞书工具**（`graph/tools.py`，加入 `feishu_advanced` 分类）：

| 工具 | 描述 |
|------|------|
| `feishu_bitable_record` | 多维表格记录 CRUD（7种操作，含批量） |
| `feishu_bitable_meta` | 列出数据表/字段/视图 |
| `feishu_task_task` | 任务创建/查询/更新/子任务 |
| `feishu_task_tasklist` | 任务清单管理 |
| `feishu_search_doc_wiki` | 全文搜索文档/Wiki（需 user_access_token） |
| `feishu_im_get_messages` | 读取群聊或单聊历史消息 |

### Changed
- **`integrations/feishu/client.py`**：user_access_token OAuth 流程（含 refresh_token 自动续期 + `.env` 写回）；新增 `feishu_get_user` / `feishu_post_user`
- **`integrations/dingtalk/docs.py`**：先试 `/v1.0/wiki/spaces/{id}/nodes`，fallback drive；支持 keyword 过滤和动态 space_id

---

## [0.6.0] - 2026-03-17

### Added
- **`integrations/claude_code/tmux_session.py`**：基于 tmux 的 Claude Code 会话管理器
  - `TmuxClaudeSession.start_streaming(requirement)`：
    1. 写 prompt 到 `/tmp/ai-claude-*.prompt`
    2. 写 wrapper script `/tmp/ai-claude-*.sh`（含 `unset ANTHROPIC_API_KEY`）
    3. `tmux new-session -d -s ai-claude-{thread_id} {script}`
    4. 后台线程 `tail .jsonl`，解析 stream-json → `send_fn` → IM
  - `SessionManager`：管理活跃 tmux 会话，支持多 thread 并发
- **4 个 Claude 会话管理工具**（`graph/tools.py`）：
  - `list_claude_sessions`：列出活跃 tmux 会话
  - `get_claude_session_output`：获取会话最近输出
  - `kill_claude_session`：强制终止会话
  - `send_claude_input`：向会话发送追加输入
- **Web 工具**：`web_search`（DuckDuckGo，无需 key）、`web_fetch`（任意 URL 纯文本）
- **`python_execute` tool**：直接执行 Python 代码片段（30s 超时）
- **系统工具**：`get_system_status`（CPU/内存/磁盘）、`get_service_status`（进程/端口/日志）

### Changed
- **`integrations/claude_code/session.py`**：向后兼容重新导出，指向 `tmux_session.py`
- **`trigger_self_iteration`**：改为启动 tmux 会话，`--dangerously-skip-permissions` → `--permission-mode acceptEdits`；wrapper script 中 `unset ANTHROPIC_API_KEY`（使用 OAuth session）
- **`run_command`**：无白名单限制（个人私有 root 服务器）
- **`prompts/system.md`**：更新为全量工具能力描述

---

## [0.5.0] - 2026-03-17

### Added
- **`integrations/claude_code/session.py`**：Claude Code 会话管理器
  - `ClaudeCodeSession.start_streaming()` — 以 `--permission-mode acceptEdits --output-format stream-json --verbose` 启动 Claude，stream-json 实时解析并推送到 IM
  - `SessionManager` 单例：管理活跃会话，支持多 thread 并发
  - `reply_fn_registry`：全局 `{thread_id: send_fn}` 注册表，bot handler 注册，tool 读取
- **`run_command` tool**：无白名单限制，执行任意 shell 命令（个人私有服务器）
- **IM 交互会话**：用户在 Claude Code 执行期间发送的消息会被 relay_input 转发给 Claude stdin

### Changed
- **`trigger_self_iteration`**：改为异步流式模式，立即返回确认，执行进度实时推送 IM；降级同步模式作为兜底
- **`run_shell_command`**（白名单版本）：已移除，替换为无限制的 `run_command`
- **`graph/nodes.py`**：`tools_node` 执行前注入 `thread_id` 和 `send_fn` 到线程局部变量
- **`integrations/feishu/bot.py`**：注册 `reply_fn_registry`；检测活跃 Claude 会话并拦截消息
- **`integrations/dingtalk/bot.py`**：同上
- **`integrations/email/imap_client.py`**：区分认证失败和连接失败，输出详细排查提示
- **`scheduler.py`**：邮件轮询间隔从 5 分钟改为 60 分钟
- **`prompts/system.md`**：更新工具描述，说明异步迭代和无限制 CLI 能力

---

## [0.4.0] - 2026-03-17

### Added
- **飞书知识库工具**（`graph/tools.py`）：新增 4 个独立 LangGraph tools
  - `feishu_read_page`：读取任意 wiki 页面（支持 URL 或裸 token）
  - `feishu_append_to_page`：向页面末尾追加内容
  - `feishu_overwrite_page`：清空并覆盖写入整个页面
  - `feishu_search_wiki`：在上下文页面中搜索关键词
- **`.env` 新增配置项**：`FEISHU_WIKI_CONTEXT_PAGE`（AI上下文快照专用页面 token）

### Fixed
- **飞书知识库权限问题**：Wiki Space list/create nodes API 不支持 tenant_access_token；改用 `GET /wiki/v2/spaces/get_node` 解析 wiki token → `obj_token`，再通过 docx API 直接读写，完全避开 space-level 权限限制
- **`FEISHU_WIKI_SPACE_ID`**：修正为正确值 `7618158120166034630`
- **`feishu_delete`**（`integrations/feishu/client.py`）：支持传递 JSON body（batch_delete 接口需要）
- **`knowledge.py`**：重写，新增 `parse_wiki_token`、`_clear_doc`、`_append_text`

### Changed
- `graph/tools.py`：移除旧的 `write_meeting_note`、`read_feishu_knowledge`、`write_feishu_knowledge`

---

## [0.3.0] - 2026-03-17

### Fixed
- **飞书消息接收**：Webhook → 长连接 SDK（`lark-oapi ws.Client`），无需公网
- **钉钉消息接收**：Webhook → 流模式 SDK（`dingtalk-stream`），无需公网
- **LangGraph Checkpointer**：`SqliteSaver.from_conn_string()` → `sqlite3.connect() + SqliteSaver(conn)`
- **LangGraph 模块路径**：单独安装 `langgraph-checkpoint-sqlite`（原 `langgraph.checkpoint.sqlite` 已拆包）
- **飞书发消息**：改用 `lark_oapi` SDK 的 `CreateMessageRequest` builder

### Changed
- `graph/agent.py`：移除 `respond_node`，`invoke()` 直接返回文本，bot handler 负责发送
- `graph/nodes.py`：路由终点改为 `END`
- `main.py`：两个平台连接器以 daemon thread 启动

---

## [0.2.0] - 2026-03-17

### Added
- `docs/architecture.md`、`docs/setup.md`、`docs/development.md`、`docs/integrations.md`
- `README.md`：项目概览、快速启动、结构说明

---

## [0.1.0] - 2026-03-17

### Added
- 项目骨架初始化
- LangGraph ReAct Agent + SQLite 记忆
- 火山云 Ark 主力 LLM + OpenRouter fallback 链
- 飞书 / 钉钉 / 163 IMAP 接入
- APScheduler 定时任务（邮件5min、上下文同步30min）
- Claude Code CLI 自迭代工具（`--dangerously-skip-permissions`）
- Shell 命令白名单执行工具
- 实现多任务并行执行框架
- 支持非阻塞工具调用
- 引入任务优先级队列
- 优化线程安全机制
- 增加实时进度监控
