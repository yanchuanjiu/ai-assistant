# Changelog

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
