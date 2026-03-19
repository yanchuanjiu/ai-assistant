# Changelog

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
