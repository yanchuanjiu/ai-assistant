# Changelog

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

### Verified Working (2026-03-17)
- ✅ `trigger_self_iteration` 异步启动，stream-json 流式推送到 IM mock
- ✅ `run_command` 无限制执行（echo/git/python 等）
- ✅ 所有 9 个工具正常导入
- ✅ 邮件轮询间隔 60min
- ✅ IMAP 错误日志详细化

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
- **`FEISHU_WIKI_SPACE_ID`**：修正为正确值 `7618158120166034630`（原值 `7360567394534637571` 错误）
- **`feishu_delete`**（`integrations/feishu/client.py`）：支持传递 JSON body（batch_delete 接口需要）
- **`knowledge.py`**：重写，新增 `parse_wiki_token`（从 URL 提取 token）、`_clear_doc`（正确的 start/end_index）、`_append_text`

### Changed
- `graph/tools.py`：移除旧的 `write_meeting_note`、`read_feishu_knowledge`、`write_feishu_knowledge`，替换为更细粒度的新工具；所有工具加入异常捕获

### Verified Working (2026-03-17)
- ✅ 飞书知识库读取（`feishu_read_page`）
- ✅ 飞书知识库追加（`feishu_append_to_page`）
- ✅ 飞书知识库覆盖（`feishu_overwrite_page`）
- ✅ 飞书知识库搜索（`feishu_search_wiki`）

---

## [0.3.0] - 2026-03-17

### Fixed
- **飞书消息接收**：将 Webhook 模式改为**长连接 SDK**（`lark-oapi ws.Client`），无需公网 IP 或域名配置
- **钉钉消息接收**：将 Webhook 模式改为**流模式 SDK**（`dingtalk-stream DingTalkStreamClient`），同样无需公网
- **LangGraph Checkpointer**：`SqliteSaver.from_conn_string()` 在新版 `langgraph-checkpoint-sqlite>=3.0` 返回 context manager 而非实例，改用 `sqlite3.connect() + SqliteSaver(conn)` 直接初始化
- **LangGraph 模块路径**：新版需单独安装 `langgraph-checkpoint-sqlite` 包（原 `langgraph.checkpoint.sqlite` 已拆包）
- **飞书发消息**：使用 `lark_oapi` SDK 的 `CreateMessageRequest` builder，自动处理 `receive_id_type`

### Changed
- `graph/agent.py`：移除 `respond_node`，`invoke()` 直接返回文本，由各 bot handler 负责平台回复
- `graph/nodes.py`：路由终点改为 `END` 而非 `respond`
- `main.py`：两个平台连接器以 daemon thread 启动，不阻塞 FastAPI

### Verified Working (2026-03-17)
- ✅ 飞书长连接收发消息（火山云 LLM 响应）
- ✅ 钉钉流模式连接建立
- ✅ 火山云 Ark `ep-20260317143459-qtgqn` 正常调用
- ✅ OpenRouter fallback 链路配置完成

### Known Issues
- ⚠️ 钉钉文档 API 返回 404（`/v1.0/doc/spaces/{id}/files` 路径待确认）
- ⚠️ 飞书 Wiki Space ID 未配置（`.env FEISHU_WIKI_SPACE_ID` 为空，运行 `python -m tools.list_feishu_spaces` 获取）
- ⚠️ 163 IMAP 登录失败（`Unsafe Login`，需在 163 网页版开启 IMAP 并重新生成授权码）

---

## [0.2.0] - 2026-03-17

### Added
- `docs/architecture.md`：系统架构详解、数据流图
- `docs/setup.md`：逐步部署指南，覆盖所有平台配置
- `docs/development.md`：如何新增工具/集成/使用自迭代
- `docs/integrations.md`：各平台 API 细节（飞书/钉钉/163/火山云/OpenRouter）
- `README.md`：项目概览、快速启动、结构说明

### Changed
- `CLAUDE.md`：补充完整项目上下文供自迭代使用

---

## [0.1.0] - 2026-03-17

### Added
- 项目骨架初始化
- LangGraph ReAct Agent + SQLite 记忆（短/长期）
- 火山云 Ark 主力 LLM + OpenRouter fallback 链
- 飞书集成：Bot、知识库读写
- 钉钉集成：Bot、文档空间读取
- 163 IMAP 邮件轮询 + Claude Haiku 会议信息提取
- APScheduler 定时任务：邮件轮询（5分钟）、上下文同步（30分钟）
- SQLite ↔ 飞书知识库双向同步
- Claude Code CLI 自迭代工具（`--dangerously-skip-permissions`）
- Shell 命令白名单执行工具
- `.env` 凭据管理，`.gitignore` 保护
