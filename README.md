# AI 个人助理（v0.8.24）

> 运行在私有 Linux 服务器上的个人 AI 助理。通过飞书 / 钉钉机器人对话，自动处理会议纪要、读写飞书知识库、搜索网络，并通过自然语言驱动 Claude Code 完成代码开发自迭代与自我学习改进。

---

## 整体定位

| 维度 | 说明 |
|------|------|
| **是什么** | 个人专属 AI 助理，部署在私有 Linux 服务器，通过 IM 机器人交互 |
| **解决什么** | 用一个对话入口统一管理：会议、知识库、开发任务、系统运维、网络信息 |
| **不是什么** | 不是 SaaS 产品，无多租户/稳定性硬要求，可用性和可迭代性优先 |
| **用户是谁** | 仅供服务器拥有者本人使用（私有 root 服务器，无限制执行权限） |

---

## Agent 编排：谁做什么

本系统共有 **2 类 Agent**，分工如下：

```
用户（飞书/钉钉）
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  Agent①  主 Agent（LangGraph ReAct）                    │
│                                                         │
│  角色：通用决策中枢                                      │
│  触发：所有用户消息默认进入此 Agent                       │
│  LLM ：火山云 Ark → OpenRouter（自动 fallback）           │
│  记忆：SQLite（data/memory.db），按 thread_id 持久化      │
│  自我：workspace/{SOUL/USER/MEMORY/HEARTBEAT/            │
│        SKILLS_PROJECT_MGMT}.md                           │
│                                                         │
│  处理：会议管理 / 知识库读写 / 网络搜索 /                  │
│        系统运维 / 代码执行 / 开发需求路由                  │
│                                                         │
│  工具：7核心 + 按需注入（含 33个 MCP），渐进式披露         │
└───────────────────┬─────────────────────────────────────┘
                    │ 当任务=开发/代码改动时
                    │ 调用 trigger_self_iteration
                    ├──────────────────────────────────────►
                    │                                      ▼
                    │ 当任务=自我学习分析时          ┌─────────────────┐
                    │ 调用 trigger_self_improvement  │ Agent②  Claude  │
                    └──────────────────────────────► │ Code 子 Agent   │
                                                     │ (tmux 会话)     │
                                                     │                 │
                                                     │ · 开发迭代      │
                                                     │ · 分析日志      │
                                                     │ · 优化自身      │
                                                     └─────────────────┘
```

### 两个 Agent 的对比

| | 主 Agent | Claude Code 子 Agent |
|---|---|---|
| 触发时机 | 所有用户消息 | 开发需求 / 自我学习分析 |
| LLM | 火山云 Ark / OpenRouter | Claude CLI（OAuth） |
| 运行模式 | 同步（请求-响应） | 异步（tmux 后台执行） |
| 生命周期 | 每次消息一个 invoke | 一个任务可持续数分钟 |
| 记忆 | SQLite 持久化跨会话 | 单次任务，无持久化 |
| 输出方式 | 直接回复 | stream-json 分片推送到 IM |
| 用户交互 | 正常对话 | IM 消息自动 relay 给 Claude |

---

## 主 Agent 工具表

主 Agent 通过 LangGraph 的 ReAct 模式调用以下工具。采用**渐进式披露**：7 个核心工具每次必带，其余按消息关键词动态注入（节省约 87% token）。共 **29 个工具**（含 6 个飞书知识库、6 个飞书高级、2 个会议、6 个 Claude 管理，另有 33 个 MCP 工具按需注入）。

### 核心工具（7 个，每次必带）

| 工具 | 用途 |
|------|------|
| `agent_config` | 运行时配置读写（get/set/delete/list），对话中直接配置，无需重启 |
| `web_search` | DuckDuckGo 搜索（无需 API key） |
| `web_fetch` | 获取任意 URL 的纯文本内容 |
| `python_execute` | 直接执行 Python 代码片段（30s 超时） |
| `run_command` | 执行任意 shell 命令（无白名单） |
| `get_system_status` | CPU / 内存 / 磁盘状态 |
| `get_service_status` | 主进程、Claude tmux 会话概览、最近崩溃记录 |

### 飞书知识库（6 个，关键词：飞书/wiki/知识库/会议/纪要/项目/章程/周报等）

| 工具 | 用途 | 典型场景 |
|------|------|---------|
| `feishu_read_page` | 读取 wiki 页面全文 | 查阅历史记录、读取文档 |
| `feishu_append_to_page` | 向页面末尾追加内容 | 记录新信息、追加日志 |
| `feishu_overwrite_page` | 清空并重写页面 | 更新上下文快照 |
| `feishu_search_wiki` | 在上下文页面中搜索 | 检索已记录内容 |
| `feishu_wiki_page` | 子页面管理（list_children / find_or_create） | 自动创建/查找子页面 |
| `sync_context_to_feishu` | SQLite 记忆快照 → 飞书 | 手动触发同步 |

### 飞书高级工具（6 个，关键词：多维表格/任务/bitable）

| 工具 | 用途 |
|------|------|
| `feishu_bitable_record` | 多维表格记录 CRUD（create/list/update/delete 等7种） |
| `feishu_bitable_meta` | 列出数据表/字段/视图 |
| `feishu_task_task` | 任务创建/查询/更新/子任务 |
| `feishu_task_tasklist` | 任务清单管理 |
| `feishu_search_doc_wiki` | 全文搜索文档/Wiki（需 user_access_token） |
| `feishu_im_get_messages` | 读取群聊或单聊历史消息 |

### 钉钉文档 MCP（33 个，关键词：钉钉/dingtalk）

通过钉钉 MCP Server 直接调用，主要工具：

| 工具 | 用途 |
|------|------|
| `search_documents` | 按关键词搜索文档 |
| `get_document_content` | 读取文档 Markdown 内容 |
| `create_document` / `update_document` | 创建/覆盖写入文档 |
| `list_document_blocks` / `insert_document_block` / `update_document_block` / `delete_document_block` | 块级精确编辑 |
| `list_bases` / `query_records` / `create_records` / `update_records` | AI 表格 CRUD |
| *(共 33 个，含文档 12 个 + AI 表格 21 个)* | |
| `analyze_meeting_doc` / `list_processed_meetings` | 会议纪要 Skill：LLM 分析并写飞书 / 查看历史记录 |

### Claude Code 管理（6 个，关键词：迭代/开发/claude/自我改进）

> 主 Agent 用这组工具全权管理 Claude Code 子 Agent 的生命周期。

| 工具 | 用途 | 典型场景 |
|------|------|---------|
| `trigger_self_iteration` | **启动** Claude Code 开发任务（异步） | "帮我加一个 XX 功能" |
| `trigger_self_improvement` | **启动** Claude Code 自我学习分析（异步） | "分析日志优化自己" |
| `list_claude_sessions` | 列出所有活跃 tmux 会话 | "现在 Claude 在跑什么？" |
| `get_claude_session_output` | 获取会话最近输出 | 查看进度 / 排查问题 |
| `kill_claude_session` | 强制终止会话 | 任务跑偏、需要重来 |
| `send_claude_input` | 向会话发送追加指令 | 补充需求、回答 Claude 的问题 |

---

## 运行时配置（无需重启）

以下配置项可通过 `agent_config` 工具在 IM 对话中直接设置，立即生效：

| 功能场景 | 配置 key | 说明 |
|----------|----------|------|
| 心跳主动通知 | `OWNER_FEISHU_CHAT_ID` | 飞书群/单聊的 chat_id，心跳有内容时推送到此 |
| 会议纪要汇总页 | `FEISHU_WIKI_MEETING_PAGE` | 飞书 wiki token，会议纪要写入目标页面 |
| 钉钉知识库空间 | `DINGTALK_DOCS_SPACE_ID` | 钉钉知识库空间 ID |
| 钉钉文档 API 路径 | `DINGTALK_WIKI_API_PATH` | 首次自动探测写入，一般无需手动设置 |

在 IM 中直接说"帮我配置心跳通知"，Agent 会主动引导并完成配置，无需手动改文件或重启。

---

## Skills 是什么

本项目的 **Skills** 是写在 `prompts/system.md` 中的**能力模块声明**，告诉主 Agent 在哪些场景下应该怎么做、优先用哪些工具组合。Skills 不是代码，而是 Agent 的行为规范。

当前 system.md 中定义的 Skills：

| Skill | 触发条件 | 典型工具组合 |
|-------|---------|------------|
| **会议管理** | "帮我整理会议纪要" / 接到钉钉文档 | `get_document_content`(MCP) → `analyze_meeting_doc` → `feishu_append_to_page` |
| **项目集管理** | "新建项目" / "写章程" / "更新周报" / "项目里程碑" | `feishu_wiki_page`(find_or_create) → 按 SKILLS_PROJECT_MGMT 模板 → `feishu_append_to_page` |
| **知识库管理** | "记录一下…" / "查一下…" | `feishu_search_wiki` → `feishu_append_to_page` |
| **开发迭代** | "帮我加个功能" / "修复这个 bug" | `trigger_self_iteration` → `list_claude_sessions` |
| **自我学习** | "分析日志" / "优化自己" | `trigger_self_improvement` → `list_claude_sessions` |
| **网络信息** | "搜一下…" / "查最新…" | `web_search` → `web_fetch` |
| **系统运维** | "服务怎么了" / "查一下日志" | `get_service_status` → `run_command` |
| **数据处理** | "帮我算…" / "统计一下…" | `python_execute` |
| **多任务并行** | "同时帮我：① … ② … ③ …" | 并行工具调用 → 分主题汇报结果 |

---

## 完整消息流

```
用户在飞书/钉钉发消息
         │
         ▼
  bot._on_message()
         │
         ├─── 是否有活跃 Claude Code 会话？
         │         YES → relay_input() → tmux send-keys → Claude Code
         │
         └─── NO → invoke(主 Agent)
                        │
                   agent_node (LLM 推理，动态读取 workspace/ 自我文件)
                        │
                   有 tool_calls？
                   YES ↓        NO → respond_node → IM 回复
                        │
                   tools_node (并行执行工具)
                        │
                   返回 tool 结果 → 继续推理（可多轮）
                        │
                   最终回复文本 → IM
                        │
                   log_interaction() → logs/interactions.jsonl

  若工具 = trigger_self_iteration / trigger_self_improvement：
         │
         ▼
    TmuxClaudeSession.start_streaming()
         ├── 写 prompt 到 /tmp/ai-claude-*.prompt
         ├── 创建 tmux session（ai-claude-{thread_id}）
         ├── 运行 wrapper script（含 unset ANTHROPIC_API_KEY）
         └── 后台线程 tail .jsonl → 解析 stream-json → IM 推送
```

---

## 定时任务（独立于 Agent）

| 任务 | 频率 | 做什么 |
|------|------|--------|
| `poll_dingtalk_meetings` | 每 30 分钟 | 轮询钉钉知识库 → LLM 分析新会议纪要 → 写飞书知识库 |
| `poll_email` | 每 60 分钟 | 拉取 163 邮件 → 主 Agent 判断会议邮件 → 写飞书知识库 |
| `sync_context` | 每 30 分钟 | SQLite checkpoints 快照 → 覆盖飞书上下文页面 |
| `heartbeat` | 每 30 分钟 | Agent 主动读取 HEARTBEAT.md 决策，深夜静默（23:00–07:00），有内容推送给 Owner |

---

## LLM 分工

| LLM | 用途 | 凭据 |
|-----|------|------|
| 火山云 Ark `ep-20260317143459-qtgqn` | 主 Agent（主力） | `VOLCENGINE_API_KEY` |
| OpenRouter `anthropic/claude-sonnet-4-5` | 主 Agent（fallback） | `OPENROUTER_API_KEY` |
| Claude Code CLI | 代码开发 / 自我学习子 Agent | OAuth session token（**排除 `ANTHROPIC_API_KEY`**） |

⚠️ **关键**：子 Agent（Claude Code CLI）启动时必须 `unset ANTHROPIC_API_KEY`，否则 OAuth session 被覆盖导致 401 失败。

---

## 当前运行状态（v0.8.24）

```
✅ 飞书机器人      — 长连接（lark-oapi ws.Client）
✅ 钉钉机器人      — 流模式（dingtalk-stream）
✅ 火山云 LLM     — ep-20260317143459-qtgqn
✅ SQLite 记忆    — data/memory.db / data/meeting.db
✅ 运行时配置      — agent_config 工具，对话中动态配置，无需重启
✅ 进程管理        — supervised thread + 指数退避自动重启，崩溃写 logs/crash.log
✅ 定时任务        — 钉钉会议30min / 邮件60min / 上下文同步30min / 心跳30min
✅ 飞书知识库      — docx API via get_node（context page: FalZwGDOkiqpbQkeAjGc8jaznMd）
✅ 飞书子页面      — find_or_create_child_page（tenant token，无需 user OAuth）
✅ 会议纪要闭环    — 钉钉知识库轮询 → LLM 分析 → 飞书写入（自动 + 按需）
✅ 会议页面自发现  — "📋 会议纪要汇总"页面自动在 context page 下创建，无需手动配置
✅ LLM 调用日志   — logs/llm.jsonl（JSONL）
✅ 交互日志        — logs/interactions.jsonl（含工具使用、延迟、用户纠正信号）
✅ Claude Code    — tmux 会话（持久化），stream-json 推送 IM
✅ Claude 会话管理 — list / get_output / kill / send_input
✅ Web 工具        — web_search + web_fetch
✅ 代码执行        — python_execute + run_command（无白名单）
✅ 系统监控        — get_system_status / get_service_status
✅ 飞书扩展工具    — Bitable CRUD / 任务管理 / 文档搜索 / IM 消息读取
✅ 钉钉文档 MCP   — 12个文档工具（搜索/读取/创建/块编辑），关键词"钉钉"触发
✅ 钉钉AI表格 MCP — 21个表格工具（Base/Table/Field/Record CRUD），关键词"钉钉"触发
✅ 渐进式工具披露  — 7 核心工具 + 按需动态注入（~87% token 节省）
✅ 回归测试套件    — tests/regression/（飞书/钉钉MCP/端到端，共33用例）
✅ Admin Web 界面  — http://localhost:8080（配置管理，无需重启）
✅ Workspace 自我  — workspace/{SOUL/USER/MEMORY/HEARTBEAT/SKILLS_PROJECT_MGMT}.md，动态注入 system prompt
✅ 项目集管理Skill — workspace/SKILLS_PROJECT_MGMT.md，写入项目文档时执行治理检查 + 模板匹配
✅ 多任务并行处理  — 复杂消息自动拆分子任务并行处理，分主题汇报结果
✅ 自我改进工具    — trigger_self_improvement，Claude Code 分析日志 → 优化 → 推送报告
✅ 心跳主动决策    — 每30分钟 Agent 自主判断是否行动；OWNER_FEISHU_CHAT_ID 通过 agent_config 配置
✅ IM 配置引导    — 用户提到相关场景时，Agent 主动引导并在对话中完成配置

⚠️  163 IMAP     — 需重新开启 IMAP 并更新 EMAIL_AUTH_CODE
```

---

## 项目结构

```
ai-assistant/
├── main.py                      # 主入口：supervised thread 进程管理 + signal 优雅关闭
├── scheduler.py                 # APScheduler 定时任务（含心跳）
├── requirements.txt
├── .env                         # 所有凭据（私有仓库）
├── CLAUDE.md                    # Claude Code 自迭代首要参考（含变更历史）
├── CHANGELOG.md                 # 版本记录
├── larksuite-openclaw-lark-*.tgz  # 飞书 OpenClaw Skills 参考包
│
├── workspace/                   # Agent 自我（Workspace 文件体系）
│   ├── SOUL.md                  # Agent 行为原则与价值观
│   ├── USER.md                  # 用户画像（持续积累）
│   ├── MEMORY.md                # 长期记忆（心跳提炼）
│   ├── HEARTBEAT.md             # 主动任务清单（心跳任务配置）
│   └── SKILLS_PROJECT_MGMT.md  # IT 项目集管理 Skill（模板 + 治理规则）
│
├── graph/                       # 主 Agent（LangGraph）
│   ├── agent.py                 # 图定义 + SQLite checkpointer + invoke() 入口（含交互日志）
│   ├── nodes.py                 # agent_node（动态 system prompt + 渐进式工具注入）/ tools_node
│   ├── state.py                 # AgentState TypedDict
│   └── tools.py                 # 29个工具，CORE_TOOLS + TOOL_CATEGORIES（渐进式披露）
│
├── integrations/
│   ├── feishu/
│   │   ├── bot.py               # 长连接消息处理，Claude 会话拦截，reply_fn 注册
│   │   ├── client.py            # tenant/user_access_token + HTTP 封装
│   │   └── knowledge.py         # wiki 读写 + 子页面创建（get_node → docx → move_docs_to_wiki）
│   ├── dingtalk/
│   │   ├── bot.py               # 流模式消息处理，Claude 会话拦截
│   │   ├── client.py            # DingTalk OAuth token；get_current_user_unionid（/v2.0/users/me）
│   │   └── docs.py              # wiki/drive 双路径 fallback，keyword 过滤
│   ├── meeting/
│   │   ├── analyzer.py          # 火山云 LLM 分析会议纪要 → 结构化 JSON → 飞书写入
│   │   └── tracker.py           # SQLite（data/meeting.db）记录已处理文档，避免重复
│   ├── claude_code/
│   │   ├── tmux_session.py      # TmuxClaudeSession + SessionManager（核心实现）
│   │   └── session.py           # 向后兼容重新导出
│   ├── email/
│   │   └── imap_client.py       # 163 IMAP 轮询
│   ├── logging/
│   │   └── interaction_logger.py  # 交互日志（logs/interactions.jsonl），含纠正信号检测
│   ├── mcp/
│   │   └── client.py            # MCP Streamable-HTTP 客户端（load_mcp_tools）
│   └── storage/                 # 文件存储抽象
│       └── config_store.py      # 运行时 key-value 配置（SQLite，无需重启）
│
├── admin/
│   └── server.py                # Web 配置管理界面（端口 8080，stdlib http.server）
│
├── sync/context_sync.py         # SQLite checkpoints → 飞书知识库
├── prompts/
│   ├── system.md                # 主 Agent system prompt（Skills 声明 + 配置引导规则）
│   └── meeting_analysis.md      # 会议纪要深度分析 prompt（钉钉文档场景）
├── tests/
│   └── regression/              # 回归测试套件
│       ├── conftest.py          # pytest 配置（加载 .env，设置 sys.path）
│       ├── run_all.py           # CLI 入口（python tests/regression/run_all.py）
│       ├── test_feishu_wiki.py  # 飞书知识库（14用例）
│       ├── test_dingtalk_mcp.py # 钉钉 MCP 工具（8用例）
│       └── test_e2e_pipeline.py # 端到端流水线（11用例）
└── docs/                        # 详细文档
```

---

## 快速启动

```bash
git clone https://github.com/yanchuanjiu/ai-assistant.git
cd ai-assistant
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填写 docs/setup.md 中的配置项

# 启动（前台）
python main.py

# 后台运行（必须在激活 venv 后执行，所有输出合并到 app.log）
nohup python main.py >> logs/app.log 2>&1 &

# 重启（用 PID 文件 kill）
kill $(cat logs/service.pid 2>/dev/null) 2>/dev/null
source .venv/bin/activate
nohup python main.py >> logs/app.log 2>&1 &

# 查看 Claude Code 后台会话
tmux list-sessions | grep ai-claude
tmux attach -t ai-claude-{session_name}
```

**环境要求**：Python 3.11+，tmux，Claude Code CLI（已完成 OAuth 登录）

---

## 回归测试

每次迭代后运行，确保已有功能不被破坏：

```bash
source .venv/bin/activate

# 运行全部（需真实 .env 凭据）
python tests/regression/run_all.py

# 按套件单独运行
python tests/regression/run_all.py feishu    # 飞书知识库（14用例）
python tests/regression/run_all.py dingtalk  # 钉钉 MCP（8用例）
python tests/regression/run_all.py e2e       # 端到端流水线（11用例）
```

> LLM 调用类测试（`TestAnalyze`）因外部依赖超时会自动 skip，属正常现象。

---

## 待完成事项

- [ ] 飞书知识库语义搜索（当前为关键词匹配）

---

## 相关文档

| 文档 | 内容 |
|------|------|
| [CLAUDE.md](CLAUDE.md) | Claude Code 自迭代上下文，架构坑点，自迭代规则 |
| [docs/setup.md](docs/setup.md) | 详细部署和配置指南 |
| [docs/architecture.md](docs/architecture.md) | 架构设计 |
| [CHANGELOG.md](CHANGELOG.md) | 版本迭代记录 |

MIT License · 个人非商用
## v0.8.23 - 2026-03-21
- 优化并发处理能力，支持多任务并行执行
- 实现非阻塞工具调用
- 引入任务优先级队列
- 增强线程安全机制
- 添加实时进度监控
