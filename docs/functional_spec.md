# AI 个人助理 — 完整功能规格文档

> **版本**：v1.0.18
> **最后更新**：2026-03-23
> **用途**：用于核对实际代码工作与设计问题，以及基于文档（而非代码）设计测试用例的基准文档

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [进程管理层](#3-进程管理层)
4. [LangGraph Agent 层](#4-langgraph-agent-层)
5. [工具系统（Tool System）](#5-工具系统)
6. [平台集成](#6-平台集成)
7. [持久化层](#7-持久化层)
8. [定时任务调度](#8-定时任务调度)
9. [Workspace 体系](#9-workspace-体系)
10. [系统提示词架构](#10-系统提示词架构)
11. [消息流与线程路由](#11-消息流与线程路由)
12. [会议纪要自动化](#12-会议纪要自动化)
13. [Claude Code 子 Agent](#13-claude-code-子-agent)
14. [错误处理与自修复](#14-错误处理与自修复)
15. [配置管理](#15-配置管理)
16. [Admin 管理界面](#16-admin-管理界面)
17. [上下文同步](#17-上下文同步)
18. [并发任务框架](#18-并发任务框架)
19. [数据模型](#19-数据模型)
20. [安全设计](#20-安全设计)
21. [部署与启动](#21-部署与启动)
22. [依赖项](#22-依赖项)
23. [已知限制与约束](#23-已知限制与约束)
24. [测试基础设施](#24-测试基础设施)

---

## 1. 项目概述

### 1.1 定位

个人非商用 AI 助理，部署在 Linux 云服务器（`/root/ai-assistant`）。通过飞书（Feishu）和钉钉（DingTalk）机器人接收用户消息，调用 LLM 和各类工具完成任务，并将结果写入飞书知识库归档。

**核心特点**：
- 无公网 HTTP Webhook，全部采用客户端主动连接（WebSocket/流模式）
- 个人专用，无稳定性/高并发硬性要求，可用性和可迭代性优先
- 支持多话题并行处理，各话题上下文完全隔离
- 具备自我改进能力（通过 Claude Code 子进程执行代码迭代）

### 1.2 版本与目录结构

**当前版本**：v1.0.18（`VERSION` 文件）

```
/root/ai-assistant/
├── main.py                    # 入口：进程管理 + 优雅关闭
├── scheduler.py               # APScheduler 定时任务
├── requirements.txt           # Python 依赖
├── VERSION                    # 当前版本号
├── CHANGELOG.md               # 完整变更历史
├── CLAUDE.md                  # 自迭代首要参考文档
├── README.md                  # 简要说明
├── graph/                     # LangGraph Agent 逻辑
│   ├── agent.py               # Graph 构建 + 编译
│   ├── nodes.py               # Agent 节点 + 工具节点 + Prompt 构建
│   ├── tools.py               # 40+ 工具定义（@tool 装饰器）
│   ├── state.py               # AgentState TypedDict
│   ├── parallel.py            # 并发任务框架
│   └── hooks/
│       └── volcengine.py      # 火山云文本格式工具调用解析 Hook
├── integrations/              # 平台集成层
│   ├── base_bot.py            # 平台无关 Bot 模板基类
│   ├── feishu/                # 飞书 WebSocket 长连接
│   │   ├── bot.py             # FeishuBotHandler（继承 BaseBotHandler）
│   │   ├── client.py          # API 客户端 + Token 管理
│   │   ├── knowledge.py       # Wiki 页面操作
│   │   ├── middleware.py      # @feishu_tool 装饰器（错误中间层）
│   │   └── rich_text.py       # Markdown ↔ Feishu Block 转换
│   ├── dingtalk/              # 钉钉流模式
│   │   └── bot.py             # DingTalkBotHandler（继承 BaseBotHandler）
│   ├── claude_code/           # Claude Code tmux 会话管理
│   ├── meeting/               # 会议纪要自动化
│   ├── email/                 # 163 邮件 IMAP 轮询
│   ├── mcp/                   # MCP 协议适配器
│   ├── storage/               # SQLite 运行时配置
│   ├── excel/                 # Excel 导入解析
│   ├── logging/               # 错误追踪 + 交互日志
│   └── topic_manager.py       # 多话题上下文隔离
├── prompts/                   # 系统提示词
│   ├── system.md              # Agent 系统提示词（62行，高度精简）
│   └── meeting_analysis.md    # 会议分析结构化提示词
├── workspace/                 # 持久化记忆文件
│   ├── SOUL.md                # Agent 性格与行动哲学
│   ├── USER.md                # 用户画像
│   ├── MEMORY_CORE.md         # 核心记忆（坑点+项目）
│   ├── MEMORY_HISTORY.md      # 长期记忆（非简单消息时注入）
│   ├── MEMORY.md              # 自动更新记忆快照
│   ├── HEARTBEAT.md           # 主动任务清单
│   ├── SKILLS_PROJECT_MGMT.md # 项目管理 SOP
│   └── SKILLS_FEISHU_BITABLE.md # Bitable 操作指南
├── admin/
│   └── server.py              # HTTP 配置管理 UI（端口 8080）
├── sync/
│   └── context_sync.py        # SQLite ↔ 飞书知识库双向同步
├── data/
│   ├── memory.db              # SQLite 主数据库
│   └── meeting.db             # 会议文档处理记录
├── logs/                      # 运行日志目录
└── tests/                     # 测试套件
```

---

## 2. 系统架构

### 2.1 整体架构图

```
                    ┌──────────────────────────────────────────────┐
                    │              外部输入                          │
                    │  飞书消息（WebSocket）│ 钉钉消息（Stream）│ 定时任务│
                    └──────┬────────────────────┬──────────┬──────┘
                           │                    │          │
                    ┌──────▼────────────────────▼──────────▼──────┐
                    │         进程管理层（main.py）                  │
                    │  supervised thread（指数退避自动重启）          │
                    │  ├── feishu-ws                                │
                    │  ├── dingtalk-stream                          │
                    │  └── admin-http（:8080）                      │
                    │  APScheduler（5个定时任务）                    │
                    │  SIGTERM/SIGINT 优雅关闭                      │
                    └──────────────────────┬───────────────────────┘
                                           │
                    ┌──────────────────────▼───────────────────────┐
                    │           LangGraph ReAct Agent               │
                    │  AgentState {messages, platform, user_id,     │
                    │              chat_id, thread_id, intent}      │
                    │  节点流：agent_node → tools_node → … → END   │
                    └──────┬─────────────────────────┬─────────────┘
                           │                         │
              ┌────────────▼────────┐   ┌────────────▼────────────┐
              │     LLM 调用层       │   │     工具执行层（28+个）   │
              │  1. 火山云 Ark（主）  │   │  飞书知识库（读/写/搜）  │
              │  2. OpenRouter（备）  │   │  飞书 Bitable/任务/日历 │
              │  动态 bind_tools     │   │  钉钉文档/表格（MCP）   │
              │  文本格式工具调用解析  │   │  Claude Code 子 Agent  │
              └─────────────────────┘   │  Shell/Python 执行       │
                                        │  Web 搜索/抓取            │
                                        └────────────────────────-─┘
                           │
              ┌────────────▼────────────────────────────────────────┐
              │                    持久化层                           │
              │  data/memory.db  — LangGraph checkpoints            │
              │                  — agent_config key-value           │
              │                  — feishu_anchors（线程路由）         │
              │                  — chat_topics（话题注册）            │
              │  data/meeting.db — 会议文档处理记录                   │
              │  飞书知识库       — 人类可读上下文镜像（每30min同步）  │
              └─────────────────────────────────────────────────────┘
```

### 2.2 关键设计决策

| 决策 | 原因 |
|------|------|
| 无公网 Webhook | 不暴露公网 IP/域名，客户端主动出连接 |
| Agent LLM ≠ Claude CLI | 防止 ANTHROPIC_API_KEY 覆盖 OAuth Session |
| SQLite 作为唯一存储 | 无外部依赖，单机可靠，个人场景足够 |
| 渐进式工具披露 | 减少约 87% token，仅按关键词注入相关工具 |
| Per-thread 锁（非 per-chat） | 同一聊天窗口不同话题可并行处理 |
| 飞书 User Token 优先 | User Token 可写 wiki 空间，Tenant Token 只读 |

---

## 3. 进程管理层

**文件**：`main.py`

### 3.1 Supervised Thread 模型

```python
_supervised(name, target, base_delay=5, max_delay=300)
```

- 循环运行 `target()` 函数
- 正常退出或异常后 `sleep(delay)`，delay 指数翻倍（5→10→20→…→300秒）
- 崩溃事件写入 `logs/crash.log`（JSONL，含 time/thread/error/traceback）
- 返回 daemon 线程，主线程退出时自动终止

**三个主线程**：
1. `feishu-ws`：飞书 WebSocket 长连接
2. `dingtalk-stream`：钉钉流模式
3. `admin-http`：HTTP 配置管理界面（端口 8080）

### 3.2 PID 文件

- 路径：`logs/service.pid`
- 写入时机：主进程启动时
- 用途：外部进程管理（`kill $(cat logs/service.pid)`）

### 3.3 启动清理（`_cleanup_previous()`）

- 读取旧 PID 文件，若进程仍存活则 `kill`
- 释放被占用的端口（`fuser`）
- 幂等操作，可重入

### 3.4 优雅关闭

- 监听 `SIGTERM` / `SIGINT` 信号
- 触发 `APScheduler.stop()`
- 设置 `Event`，等待各线程完成当前任务

### 3.5 APScheduler 集成

- 同一进程内启动 `scheduler.py` 中定义的定时任务
- 时区：`Asia/Shanghai`
- 5 个定时任务（详见[第 8 节](#8-定时任务调度)）

---

## 4. LangGraph Agent 层

### 4.1 AgentState

**文件**：`graph/state.py`

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # 完整对话历史（不截断轮次）
    platform: str          # "feishu" | "dingtalk"
    user_id: str           # 用户 ID（飞书 open_id / 钉钉 unionId）
    chat_id: str           # 聊天窗口 ID
    thread_id: str         # 话题级别隔离 ID（= platform:chat_id[:topic]）
    intent: str            # 意图标签（预留）
    skill_result: str      # Skill 执行结果（预留）
```

### 4.2 图结构

**文件**：`graph/agent.py`

```
START → agent_node → should_continue → tools_node → agent_node → …
                   ↘ END（无工具调用时）
```

**持久化**：`SqliteSaver`（`data/memory.db`），每个 `thread_id` 独立保存对话历史。

### 4.3 Agent 节点（`agent_node`）

**文件**：`graph/nodes.py`

**执行流程**：

1. 读取 `AgentState.messages`（完整历史，不截断 ToolMessage 内容）
2. 调用 `_build_system_prompt()` 动态组装 system prompt
3. 调用 `_select_tools_for_context()` 按消息关键词选择工具集合
4. `llm.bind_tools(selected_tools).invoke(messages)`
5. 记录到 `logs/llm.jsonl`（model/latency/tokens/tool_calls）
6. 通过 `_apply_llm_hooks()` 运行注册的 LLM 响应后处理 Hook（含火山云文本格式工具调用解析）
7. 检查最大迭代次数（`MAX_TOOL_ITERATIONS=15`），超限强制终止
8. 检查 `_check_user_interaction_needed()`，如需用户交互则提前终止

**LLM Hook 机制**（`graph/hooks/`）：

- `register_llm_hook(fn)` — 注册 Hook 函数，在每次 LLM 响应后执行
- `_apply_llm_hooks(response)` — 依次执行所有注册 Hook
- 内置 Hook：`volcengine_text_tool_call_hook`（`graph/hooks/volcengine.py`）
  - 正则表达式兼容以下变体：
  - `<|FunctionCallBegin|>[...]<|FunctionCallEnd|>`
  - `<|FunctionCallBeginBegin|>[...]<|FunctionCallEndEnd|>`
  - `[...]<|FunctionCallEnd|>`（缺少 Begin 标记）

### 4.4 工具节点（`tools_node`）

- 接收 `AIMessage` 中的 `tool_calls`
- 调用 `run_tools_parallel()` 并行执行（详见[第 18 节](#18-并发任务框架)）
- 收集所有 `ToolMessage` 结果，追加到 `messages`

### 4.5 LLM 链

```python
# 主力：火山云 Ark
ark = ChatOpenAI(model=VOLCENGINE_MODEL, api_key=VOLCENGINE_API_KEY,
                 base_url="https://ark.cn-beijing.volces.com/api/v3", timeout=120)

# 备用：OpenRouter
router = ChatOpenAI(model=OPENROUTER_MODEL, api_key=OPENROUTER_API_KEY,
                    base_url="https://openrouter.ai/api/v1", timeout=120)

llm = ark.with_fallbacks([router])
```

每次调用动态 `bind_tools(selected_tools)`，不预先绑定。

### 4.6 渐进式工具披露

**常驻工具（CORE_TOOLS，9 个，每次必带）**：
- `web_search`
- `web_fetch`
- `python_execute`
- `run_command`
- `get_system_status`
- `get_service_status`
- `agent_config`
- `get_recent_chat_context`（含引用词时主动调用）
- `query_task_status`（查询并发任务状态）

**动态注入（TOOL_CATEGORIES + CATEGORY_KEYWORDS）**：

| 分类 | 触发关键词（部分） | 工具数量 |
|------|------------------|---------|
| `feishu_wiki` | 飞书、wiki、知识库、项目、章程、周报、里程碑 | 9 |
| `feishu_advanced` | 多维表格、bitable、任务、日历、表格、excel | 11 |
| `claude` | 迭代、开发、claude、代码、编写 | 6 |
| `dingtalk_mcp` | 钉钉、dingtalk、会议、纪要 | 33+ MCP + 6 pipeline |

**Token 节省**：无相关关键词时只传 9 个工具 schema，节省约 87% token。

### 4.7 系统提示词动态构建（`_build_system_prompt()`）

**始终注入**：
- `prompts/system.md`
- `workspace/SOUL.md`
- `workspace/USER.md`
- `workspace/MEMORY_CORE.md`

**条件注入**（消息非纯问候且含特定关键词时）：
- `workspace/MEMORY_HISTORY.md`（消息长度 > 30 且非简单问候）
- `workspace/SKILLS_PROJECT_MGMT.md`（含项目管理关键词）
- `workspace/SKILLS_FEISHU_BITABLE.md`（含 bitable 关键词）

**修改无需重启**：workspace 文件每次 LLM 调用时实时读取。

---

## 5. 工具系统

**文件**：`graph/tools.py`（工具定义），`integrations/feishu/middleware.py`（错误中间层）

### 5.1 飞书工具统一错误处理（`@feishu_tool` 装饰器）

**位置**：`integrations/feishu/middleware.py`

所有飞书工具使用 `@feishu_tool` 装饰器统一处理以下异常：

| 异常类型 | 处理行为 |
|---------|---------|
| `UserTokenExpiredError` | 推送飞书 IM 通知用户重新授权，返回说明文字 |
| `WikiPermissionError` | 推送飞书 IM 通知 131006 权限问题，返回三种解决方案 |
| `AppScopeError` | 返回需管理员操作的说明 |
| `UserTokenNotConfiguredError` | 返回需授权的说明 |
| 其他异常 | `logger.error` + 返回 `"操作失败：{msg}"` |

**装饰器顺序**：`@tool` 在外，`@feishu_tool` 在内（`@tool` 包装 `@feishu_tool` 包装函数）。

### 5.2 飞书知识库工具（9 个）

#### `feishu_read_page(wiki_url_or_token)`
- 读取飞书 wiki 页面纯文本内容
- 支持 URL 或裸 token 输入
- obj_type 路由：sheet → 提示用 feishu_spreadsheet；bitable → 提示用 feishu_bitable_record；非 docx/doc → 不支持
- API：`GET /docx/v1/documents/{obj_token}/raw_content`（tenant token）
- **约束**：token 必须来自 `feishu_wiki_page` 返回结果或用户提供 URL，不能猜测

#### `feishu_append_to_page(wiki_url_or_token, content)`
- 向 wiki 页面末尾追加文本，不影响已有内容
- 返回确认消息 + 页面链接
- **适用场景**：记录新信息、追加日志、补充内容

#### `feishu_overwrite_page(wiki_url_or_token, content)`
- 清空页面并写入新内容（不可撤销）
- 返回确认消息 + 页面链接
- **适用场景**：更新上下文快照、重写文档、定期刷新

#### `feishu_search_wiki(query)`
- 在 `FEISHU_WIKI_CONTEXT_PAGE` 中搜索关键词
- 仅搜索上下文页面，非全空间搜索
- 返回最多 3 条匹配摘要

#### `sync_context_to_feishu()`
- 将本地 SQLite checkpoints 快照推送到飞书上下文页（覆盖模式）
- 手动触发版本（定时任务亦可触发）

#### `feishu_wiki_page(action, ...)`
- `list_children(wiki_token)` — 列出子页面（完整分页）
- `create(parent_token, title, content)` — 创建新页面（create docx → move 两步）
- `find_or_create(parent_token, title, content)` — 查找或创建（先搜索后创建）
- `update(wiki_token, content)` — 更新页面内容
- `delete(node_token)` — 删除页面（不可逆，需用户确认）
- **约束**：创建新 wiki 节点需 user token 或 FEISHU_WIKI_ROOT_NODES 配置

#### `feishu_wiki_delete(node_token)`
- 删除 wiki 节点（独立工具，与 feishu_wiki_page action="delete" 等效）
- API：`DELETE /wiki/v2/nodes/{node_token}`（user token）
- **风险**：不可撤销，删除文件夹会递归删除所有子页面

#### `feishu_project_setup(project_name, project_code)`
- 初始化标准项目结构（章程、04_会议纪要、06_RAID日志等）
- 在 wiki 中创建层级页面

#### `feishu_oauth_setup(action, code)`
- OAuth 授权管理
- `get_auth_url` — 获取授权 URL
- `exchange_code` — 用授权码换 token
- `refresh_token` — 手动刷新
- `check_status` — 检查 token 状态

### 5.3 飞书高级工具（11 个）

#### `feishu_spreadsheet(action, spreadsheet_token, range_)`
支持操作：
- `create` — 创建新电子表格
- `read_values` — 读取单元格值（range 格式：`Sheet1!A1:C10`）
- `update_values` — 写入单元格值
- `append_values` — 在表格末尾追加行

#### `feishu_bitable_record(action, app_token, table_id, ...)`
支持操作：
- `list` — 列出记录（支持过滤条件和分页）
- `get` — 获取单条记录
- `create` — 创建记录
- `update` — 更新记录
- `delete` — 删除记录
- `batch_create` — 批量创建

#### `feishu_bitable_meta(app_token, table_id)`
- 获取多维表格或指定表的元信息（字段列表、类型等）
- 用于了解表结构再操作记录

#### `feishu_task_task(action, task_id, ...)`
支持操作：`create`, `get`, `list`, `update`, `delete`, `list_members`

#### `feishu_task_tasklist(action, tasklist_id, ...)`
- 任务清单管理，支持创建/读取/更新/删除清单

#### `feishu_search_doc_wiki(query)`
- 全文搜索飞书知识库（全空间搜索，非仅上下文页面）

#### `feishu_im_get_messages(chat_id, limit=50)`
- 读取飞书聊天消息历史（支持分页）
- 用于回溯对话记录

#### `feishu_calendar_event(action, ...)`
支持操作：
- `list` — 列出日历事件
- `get` — 获取单个事件
- `create` — 创建事件
- `update` — 更新事件
- `delete` — 删除事件
- `get_free_busy` — 查询忙闲状态
- **权限要求**：`calendar:calendar`

#### `feishu_chat_info(action, ...)`
支持操作：
- `list_chats` — 列出机器人所在群组
- `get_chat` — 获取群组详情
- `list_members` — 列出群组成员
- `get_user` — 获取用户信息

#### `excel_import(action, file, sheet_index, ...)`
支持操作：
- `search` — 搜索用户上传的 Excel 文件
- `parse` — 解析 Excel 结构（支持合并单元格）
- `preview` — 预览表格内容
- `import_to_sheet` — 导入到飞书电子表格
- `import_to_bitable` — 导入到飞书多维表格

#### `manage_topics(action, chat_id, topic_name)`
支持操作：
- `list` — 列出 chat 的所有话题（含 thread_id）
- `delete` — 删除指定话题（清除 SQLite + checkpoint + feishu_anchors）
- `delete_all` — 删除该 chat 所有话题
- **注意**：delete 时同时清除 LangGraph checkpoint 和飞书线程锚点，不可恢复

### 5.4 核心系统工具（9 个）

#### `agent_config(action, key, value)`
- `get` — 读取配置值（SQLite 优先，.env 降级）
- `set` — 写入运行时配置（存入 SQLite，下次启动自动加载）
- `list` — 列出所有运行时配置
- `delete` — 删除配置项
- `topics` — 列出当前 chat 所有话题和 thread_id（持久化层 LLM 接入）
- `sessions` — 列出当前活跃 LangGraph 会话摘要（持久化层 LLM 接入）

#### `web_search(query, max_results=5)`
- 调用搜索引擎（默认 DuckDuckGo）
- 返回标题、URL、摘要列表

#### `web_fetch(url, max_length=5000)`
- 抓取网页并转为纯文本（去除 HTML 标签）
- 支持 max_length 截断

#### `python_execute(code)`
- 在隔离 subprocess 中执行 Python 代码
- 超时 30 秒
- 返回 stdout/stderr

#### `run_command(command, timeout=30)`
- 执行 shell 命令
- 返回 stdout/stderr + 退出码
- **注意**：root 权限，受控环境，无白名单限制

#### `get_system_status()`
- 返回系统信息：CPU、内存、磁盘、进程列表

#### `get_service_status()`
- 返回助理自身状态：版本、运行时间、线程数、活跃话题数、近期 LLM 调用统计

### 5.5 Claude Code 工具（6 个）

#### `trigger_self_iteration(requirement)`
- 启动新的 Claude Code tmux 会话
- 写入需求到 `/tmp/ai-claude-{thread_id}.prompt`
- 启动 wrapper script（`unset ANTHROPIC_API_KEY`）
- 后台线程实时推送进度到 IM
- 返回会话 ID

#### `trigger_self_improvement(reason)`
- 分析近 50 条 `logs/interactions.jsonl`
- 计算纠错率、响应延迟、工具使用分布
- 生成分析报告推送到飞书
- 更新 `workspace/MEMORY.md`

#### `list_claude_sessions()`
- 列出所有活跃 Claude Code tmux 会话

#### `get_claude_session_output(thread_id, lines=80)`
- 获取指定 Claude Code 会话的输出（tail 最后 N 行）

#### `kill_claude_session(thread_id)`
- 强制终止 Claude Code tmux 会话（`tmux kill-session`）

#### `send_claude_input(thread_id, text)`
- 向活跃 Claude Code 会话发送文字输入（`tmux send-keys`）

### 5.6 钉钉 Pipeline 工具（6 个）

#### `get_latest_meeting_docs(limit, keyword, space_id)`
- 从钉钉知识库获取文档列表
- 优先通过 MCP `list_nodes` 获取，失败降级直接 API
- 支持关键词过滤

#### `read_meeting_doc(file_id)`
- 读取钉钉文档完整文本
- 优先使用 MCP `get_document_content`，降级直接 API
- 支持 alidocs URL 或 nodeId

#### `analyze_meeting_doc(file_id, force=False)`
- 完整会议纪要处理 pipeline：读取 → LLM 分析 → 写入飞书
- `force=True` 可重新分析已处理的文档

#### `list_processed_meetings(limit=10)`
- 查看已处理的会议文档记录（来自 data/meeting.db）

#### `trigger_daily_migration()`
- 手动触发每日迁移（富文本转文本写入飞书历史页）

#### `list_daily_migrations(limit=10)`
- 查看每日迁移历史记录

### 5.7 MCP 工具（钉钉，33+ 个）

**触发条件**：消息含"钉钉"/"dingtalk"/"会议"/"纪要"关键词时动态注入

**工具来源**：
- `DINGTALK_MCP_URL` — 文档类 MCP server（12 个工具）
- `DINGTALK_MCP_TABLE_URL` — AI 表格类 MCP server（21 个工具）

**加载机制**：启动时通过 `_load_dingtalk_mcp()` 异步连接，失败时日志警告（不影响启动）

**主要工具类别**：
- 文档操作：`list_nodes`, `get_document_content`, `create_document`, `search_documents`
- 表格操作：`list_tables`, `get_table_data`, `insert_rows`, `update_rows`
- AI 表格：`create_ai_table`, `query_ai_table`

---

## 6. 平台集成

### 6.0 Bot 框架统一（`integrations/base_bot.py`）

**类**：`BaseBotHandler`（模板方法模式）

**公共流程** `handle(raw_message)`：
1. `parse_message()` — 子类实现，返回 `MessageContext`
2. `_is_duplicate()` — 2 分钟 TTL 去重
3. `_on_pre_handle()` — 注册 `reply_fn` 等子类钩子
4. `_handle_slash()` — 斜杠命令路由（`/status`, `/clear`, `/stop`, `/topics`）
5. `_handle_greeting()` — 纯问候词快速路径（不调用 LLM）
6. `_relay_claude()` — 检测活跃 Claude 会话 → 中继输入
7. `_invoke_agent()` — 后台线程调用 Agent

**子类**：
- `FeishuBotHandler`（`integrations/feishu/bot.py`）
- `DingTalkBotHandler`（`integrations/dingtalk/bot.py`）

**子类必须实现**：`parse_message()`, `send_reply()`

### 6.1 飞书集成（`integrations/feishu/`）

#### 连接方式

WebSocket 长连接，通过 `lark-oapi` SDK 的 `ws.Client`。无需公网 IP 或 Webhook。

#### 消息类型支持

| 消息类型 | 处理方式 |
|---------|---------|
| 文本（text） | 直接解析 text 字段 |
| 富文本（post） | 提取所有 text 内容拼接 |
| 合并转发（merge_forward） | 遍历所有子消息 |
| 图片（image） | 提示"收到图片" + 文件名 |
| 文件（file） | 提示"收到文件" + 文件名 |
| 卡片（interactive） | 提取 text 内容 |

**非文本消息不再静默丢弃**（v1.0.11 改进）

#### 消息去重

- 基于 `message_id` 的 2 分钟 TTL 去重集合
- 防止 WebSocket 重连后重复处理同一消息

#### 消息发送格式

- **post 富文本**（tag=md，Markdown 正常渲染）
- 超过 400 字符 → 写入飞书知识库 + 返回链接
- 所有话题回复均 `reply_in_thread`（含首条）

#### 线程路由（thread_anchor）

- `feishu_anchors` SQLite 表：`message_id → thread_id` 反向映射
- 7 天 TTL
- 用户在话题线程回复 → 机器人回复至同一线程
- 未知 root_id 时回退主聊天上下文（非孤立会话）
- 启动时重建 `_thread_anchor` 内存映射（从 SQLite 加载）

#### Token 管理（`integrations/feishu/client.py`）

**Token 类型**：
- `tenant_access_token`：应用权限，读现有 wiki 页面、发送消息等
- `user_access_token`：用户 OAuth 授权，wiki 空间创建/删除等高权限操作

**Token 优先级**：user token > tenant token

**User Token 续期**：
- 接口：`POST /authen/v2/oauth/token`（v2 端点）
- 使用 `threading.Lock` 防并发竞争（v1.0.10 修复）
- 双重检查锁定模式（获取锁后再次检查是否已被其他线程更新）
- `FEISHU_USER_REFRESH_EXPIRES_AT` 跟踪 30 天到期时间

**错误码分类**：

| 错误码 | 含义 | 处理 |
|--------|------|------|
| 99991668, 99991677 | Token 过期，可重试 | 自动刷新后重试一次 |
| 20024, 20037, 20064, 20074 | Refresh Token 不可恢复 | 抛出 UserTokenExpiredError |
| 99991672, 99991679 | 应用权限缺失 | 抛出 AppScopeError |
| 131006 | Wiki 空间权限缺失 | 抛出 WikiPermissionError |

**`feishu_call()` 统一入口**：
- 支持 `as_="tenant"` 或 `as_="user"` 指定 token 类型
- Token 过期自动刷新后重试一次
- 所有 API 调用通过此入口

#### 知识库操作（`integrations/feishu/knowledge.py`）

**Wiki Token 解析流程**：
1. `parse_wiki_token(url_or_token)` — 从 URL 提取 token
2. `wiki_token_to_obj_token(wiki_token)` — 获取 (obj_token, obj_type)
   - API：`GET /wiki/v2/spaces/get_node?token={wiki_token}`

**创建新 Wiki 节点（两步法）**：
```
POST /docx/v1/documents          → 创建裸文档（tenant token）
POST /wiki/v2/spaces/{id}/nodes/move_docs_to_wiki → 移入知识库（user token）
  payload: {parent_wiki_token, obj_type: "docx", obj_token}
GET  /wiki/v2/tasks/{task_id}    → 轮询直到完成（最多10次，每次1秒）
```

**权限降级策略**：
- 有 user token → 优先使用
- user token 未配置（`UserTokenNotConfiguredError`）→ 降级 tenant token
- user token 续期失败 → 不降级（防止 131006 复现）
- 无 user token 且需写 wiki → 使用 `FEISHU_WIKI_ROOT_NODES` 已知节点

#### Rich Text 转换（`integrations/feishu/rich_text.py`）

**Markdown → Feishu Docx Block**：
- 支持块类型：标题(H1-H6)、列表(有序/无序)、引用、代码块、分割线、段落
- 支持内联样式：加粗、斜体、行内代码、删除线、链接
- 输出格式：Feishu 文档块结构（用于 `insert_doc_block` API）

### 6.2 钉钉集成（`integrations/dingtalk/`）

#### 连接方式

流模式，通过 `dingtalk-stream` SDK。无需公网 Webhook。

#### 消息回复格式

- **MarkdownCard**（非 Webhook 模式，无过期问题）
- DingTalk 端渲染 Markdown 格式

#### 斜杠命令

| 命令 | 功能 |
|------|------|
| `/status` | 显示服务状态 |
| `/clear` | 清除当前话题上下文 |
| `/stop` | 停止当前 Claude Code 会话 |
| `/topics` | 列出所有历史会话（含线程） |

#### 文档操作（`integrations/dingtalk/docs.py`）

- v2.0 wiki API 兼容
- 动态发现 `workspaceId`（自动探测并缓存到 `agent_config`）
- 文件列表：`list_recent_files(limit, keyword)`
- 文档读取：`read_file_content(node_id)`
- 从 URL 提取 `node_id`：`extract_node_id_from_url(url)`
- **v2 API 要求**：操作方需配置 `operator_id`（unionId）

### 6.3 话题管理（`integrations/topic_manager.py`）

#### 话题识别方式

| 方式 | 格式 | 示例 |
|------|------|------|
| 话题前缀 | `#话题名` | `#产品规划 帮我看看这个方案` |
| 新话题 | `新话题：xxx` | `新话题：竞品分析` |
| 主窗口短标题 | 纯文本 < 10 字 | `竞品分析` |

#### 主窗口短标题智能路由（v1.0.16）

- 消息长度 < 10 字且无问候词 → 视为话题名
- 检查相近话题（编辑距离 / 包含关系）
- 如存在相近话题 → 询问是否合并
- 用户确认合并 → 复用原 thread_id

#### 话题持久化

- SQLite `chat_topics` 表（UPSERT 操作）
- 字段：`chat_id, topic_name → thread_id, last_active`
- 重启后命名话题不丢失

#### 每话题串行锁

- `_topic_locks` 字典，每个 `thread_id` 一把锁
- 同一话题内消息**串行**处理（防乱序和重复响应）
- **不同话题可并行处理**（锁粒度是 thread_id，非 chat_id）
- `_get_topic_lock(thread_id)` — 线程安全地获取或创建锁

---

## 7. 持久化层

### 7.1 主数据库（`data/memory.db`）

**WAL 模式**：启用 WAL（`data/memory.db-wal`, `data/memory.db-shm`）

#### checkpoints 表（LangGraph 内部）

| 字段 | 类型 | 说明 |
|------|------|------|
| thread_id | TEXT | 话题 ID（`platform:chat_id[:topic]`） |
| checkpoint_id | TEXT | 检查点 ID |
| ts | TEXT | 时间戳 |
| channel | TEXT | 消息通道 |
| values | BLOB | 序列化的 AgentState |

**TTL**：7 天（每次启动清理过期记录）

#### agent_config 表

| 字段 | 类型 | 说明 |
|------|------|------|
| key | TEXT PK | 配置键 |
| value | TEXT | 配置值 |
| updated_at | TEXT | 更新时间 |

**优先级**：SQLite > `.env`（运行时可覆盖）

#### feishu_anchors 表

| 字段 | 类型 | 说明 |
|------|------|------|
| message_id | TEXT PK | 飞书消息 ID |
| thread_id | TEXT | 对应话题 ID |
| created_at | TEXT | 创建时间 |

**用途**：`message_id → thread_id` 反向映射，支持 reply_in_thread 路由

**TTL**：7 天

#### chat_topics 表

| 字段 | 类型 | 说明 |
|------|------|------|
| chat_id | TEXT | 聊天窗口 ID |
| topic_name | TEXT | 话题名称 |
| thread_id | TEXT | 对应 thread_id |
| last_active | TEXT | 最后活跃时间 |
| PRIMARY KEY | (chat_id, topic_name) | 联合主键 |

### 7.2 会议数据库（`data/meeting.db`）

#### meeting_docs 表

| 字段 | 类型 | 说明 |
|------|------|------|
| doc_id | TEXT PK | 钉钉文档 ID |
| url_space_id | TEXT | 知识库空间 ID |
| doc_name | TEXT | 文档名称 |
| status | TEXT | analyzed/processed/not_meeting/error |
| feishu_page | TEXT | 写入的飞书页面链接 |
| project_name | TEXT | 关联项目名称 |
| project_code | TEXT | 项目代码 |
| raid_written | BOOLEAN | RAID 是否已写入 |
| created_at | TEXT | 创建时间 |

**去重机制**：`doc_id` 为主键，`INSERT OR IGNORE`

### 7.3 自修复追踪（`data/auto_fix_tracker.json`）

```json
{
  "patterns": {
    "{error_hash}": {
      "count": 2,
      "first_seen": "2026-03-22T10:00:00",
      "last_seen": "2026-03-22T11:30:00",
      "error_summary": "..."
    }
  }
}
```

**限制**：同一错误模式最多自动修复 3 次，超限通知用户并停止

---

## 8. 定时任务调度

**文件**：`scheduler.py`
**引擎**：APScheduler（BlockingScheduler，`Asia/Shanghai` 时区）

| 任务名 | 触发方式 | 功能描述 |
|--------|---------|---------|
| `poll_dingtalk_meetings` | 每 30 分钟（interval） | 从钉钉获取新文档 → LLM 分析 → 写入飞书知识库 |
| `poll_email` | 每 60 分钟（interval） | 163 IMAP 轮询 → 会议相关邮件推送 IM |
| `sync_context` | 每 30 分钟（interval） | SQLite checkpoint 快照 → 覆盖飞书上下文页面 |
| `heartbeat` | 每 30 分钟（interval） | 读取 HEARTBEAT.md → Agent 决策执行，深夜(23-7点)静默 |
| `daily_migration` | 每天 08:00（cron） | 格式化前一天会议纪要摘要 |

**心跳任务特殊逻辑**：
- 23:00–07:00 跳过（夜间静默）
- HEARTBEAT.md 有待处理任务 → 触发 Agent 处理并推送结果到飞书

---

## 9. Workspace 体系

**目录**：`workspace/`

所有文件在 LLM 每次调用时实时读取，修改无需重启。

### 9.1 文件职责分工

| 文件 | Label | 职责 | 不该包含 |
|------|-------|------|---------|
| `SOUL.md` | `SOUL` | Agent 性格、行动哲学、主动/被动边界 | 工具用法、平台细节 |
| `USER.md` | `USER` | 用户画像、偏好、核心项目 | 临时状态 |
| `MEMORY_CORE.md` | `MEMORY_CORE` | 已知坑点结论性描述、API 注意事项 | Agent 可绕过的方案 |
| `MEMORY_HISTORY.md` | `MEMORY_HISTORY` | 长期记忆快照 | 当前会话上下文 |
| `MEMORY.md` | `MEMORY` | 自动更新的记忆快照（心跳提炼） | - |
| `HEARTBEAT.md` | - | 主动任务清单（心跳执行） | 已完成任务 |
| `SKILLS_PROJECT_MGMT.md` | `SKILL_PROJECT_MGMT` | 项目管理 SOP、步骤级指导 | 通用原则 |
| `SKILLS_FEISHU_BITABLE.md` | - | Bitable 操作指南 | - |

### 9.2 USER.md 用户画像（关键信息）

- **角色**：AI 产品经理（美妆行业）
- **沟通风格**：直接高效，不要废话
- **平台偏好**：飞书（主要），钉钉（次要）
- **核心项目**：LLM 产品知识库、VOC 电商分析、AI 消费决策链
- **工作习惯**：失败自修复，给链接证明，简短回复

### 9.3 SOUL.md 行为原则（关键约束）

- **主动操作**：知识库读写、信息整理（无需确认）
- **先确认后执行**：删除数据、批量修改、外部发消息
- **直接停止**：权限不足 → 告知用户，不循环重试
- **IM 长度限制**：> 400 字 → 写飞书 + 返回链接

---

## 10. 系统提示词架构

**文件**：`prompts/system.md`（62 行，高度精简）

### 10.1 设计原则（减法原则）

在增加任何 system.md 内容前，先问：
1. 模型天然会这样做吗？ → 是则不写
2. 工具 schema 已经说清楚了吗？ → 是则不写
3. 这是工具层该处理的吗？ → 是则改 docstring
4. 只在某个 Skill 场景才需要吗？ → 是则写进 SKILLS_*.md
5. SOUL.md 已经覆盖了吗？ → 是则不重复

### 10.2 system.md 包含的关键规则

- 飞书 wiki token 导航方式（只能从实时 API 获取）
- token 类型区分（node_token vs space_id）
- 数据流方向（钉钉 → 飞书，单向）
- IM 消息长度限制（400 字）
- 权限错误处理（告知用户，停止重试）
- 破坏性操作确认要求

### 10.3 死循环防御（三层）

| 层级 | 机制 | 位置 |
|------|------|------|
| 提示词层（最优先） | 权限/配置错误 → 告知用户，停止 | `prompts/system.md` |
| 性格层 | 权限不足是人工介入信号，不是「卡住」 | `workspace/SOUL.md` |
| 代码兜底 | `MAX_TOOL_ITERATIONS=10` + `_check_user_interaction_needed()` | `graph/nodes.py` |

---

## 11. 消息流与线程路由

### 11.1 飞书消息处理流程

```
WebSocket 事件
  ↓
feishu_bot._on_message()
  ├─ 消息去重（2分钟 TTL message_id 集合）
  ├─ 消息解析（_parse_feishu_message）
  │   ├─ 类型识别（text/image/file/card/post）
  │   ├─ root_id 查找（feishu_anchors）
  │   └─ thread_id 解析
  ├─ 话题提取（extract_topic）
  ├─ 主窗口短标题检测（< 10 字 → 智能路由）
  ├─ 快速路径（纯问候词 → 直接回复，不走 LLM）
  ├─ 斜杠命令路由（/status, /clear 等）
  ├─ 活跃 Claude 会话检测 → relay_input() → tmux send-keys
  └─ graph.invoke() → LangGraph Agent 执行
      ├─ set_tool_ctx(thread_id, send_fn)
      ├─ Agent 执行（含工具调用）
      └─ _send_reply() 路由（按 thread_id 选择线程）
```

### 11.2 钉钉消息处理流程

```
Stream 事件
  ↓
dingtalk_bot._BotHandler.process()
  ├─ 消息解析
  ├─ 话题提取
  ├─ 斜杠命令路由
  ├─ 活跃 Claude 会话检测
  └─ graph.invoke() → 发送 MarkdownCard
```

### 11.3 Thread ID 设计

| 场景 | thread_id 格式 |
|------|---------------|
| 飞书主聊天 | `feishu:{chat_id}` |
| 飞书命名话题 | `feishu:{chat_id}:{topic_name}` |
| 钉钉主聊天 | `dingtalk:{conversation_id}` |
| 钉钉命名话题 | `dingtalk:{conversation_id}:{topic_name}` |

### 11.4 Per-Topic 串行锁

```python
_topic_locks: dict[str, threading.Lock]  # thread_id → Lock
```

- 同一 `thread_id`（话题）的消息串行处理（等待前一条处理完毕）
- 防止乱序处理和重复响应
- 同一聊天窗口的**不同话题**可并行处理（锁粒度是 thread_id，非 chat_id）

---

## 12. 会议纪要自动化

**目录**：`integrations/meeting/`

### 12.1 完整 Pipeline

```
APScheduler（每 30 分钟）
  ↓
poll_dingtalk_meetings()
  ├─ DingTalkDocs.list_recent_files(limit=50)     # 获取文档列表
  ├─ 遍历每个文档：
  │   ├─ tracker.is_processed(doc_id)？→ 跳过
  │   ├─ docs.read_file_content(doc_id)            # 读取内容（max 6000 字符）
  │   ├─ analyzer.analyze(content)                 # LLM 分析（30秒超时）
  │   │   → 结构化 JSON {title, date, participants, decisions, action_items, raid}
  │   ├─ analyzer.write_to_feishu(analysis)        # 追加到飞书知识库
  │   └─ tracker.mark_processed(doc_id)            # 标记已处理
  └─ 推送摘要到 IM（若有新记录）
```

### 12.2 会议分析提示词（`prompts/meeting_analysis.md`）

输出结构：
```json
{
  "is_meeting": true/false,
  "title": "会议标题",
  "date": "2026-03-22",
  "participants": ["姓名1", "姓名2"],
  "decisions": ["决定1", "决定2"],
  "action_items": [
    {"owner": "姓名", "task": "任务描述", "due_date": "2026-03-28"}
  ],
  "raid": {
    "risks": [...], "assumptions": [...], "issues": [...], "dependencies": [...]
  }
}
```

### 12.3 去重机制

- `data/meeting.db` 的 `meeting_docs.doc_id` 主键
- `status=not_meeting` 标记非会议文档（避免重复 LLM 调用）
- `INSERT OR IGNORE` 防重复写入

### 12.4 每日迁移（`daily_migration.py`）

- 触发时间：每天 08:00
- 功能：格式化前一天所有已处理会议纪要为富文本格式
- 输出：写入飞书 `FEISHU_WIKI_MEETING_PAGE` 对应的每日摘要页

### 12.5 项目路由（`project_router.py`）

- 根据会议内容自动识别关联项目
- 将分析结果路由至对应项目文件夹的知识库页面
- 路由规则：关键词匹配 + 历史项目映射

---

## 13. Claude Code 子 Agent

**文件**：`integrations/claude_code/tmux_session.py`

### 13.1 会话启动流程

```
trigger_self_iteration(requirement)
  ↓
TmuxClaudeSession.start_streaming()
  ① 写入需求：/tmp/ai-claude-{safe_thread_id}.prompt
  ② 创建 wrapper script：/tmp/ai-claude-{safe_thread_id}.sh
     内容：
     #!/bin/bash
     unset ANTHROPIC_API_KEY           # 必须！防止覆盖 OAuth session
     cd /root/ai-assistant
     source .venv/bin/activate
     claude --permission-mode acceptEdits --output-format stream-json --verbose \
            < /tmp/ai-claude-{thread_id}.prompt \
            > /tmp/ai-claude-{thread_id}.jsonl 2>&1
  ③ tmux new-session -d -s ai-claude-{safe_thread_id} {script}
  ④ 后台线程：tail -f {jsonl} → 解析 stream-json → send_fn(text) → IM 推送
```

### 13.2 会话名称规范

- 格式：`ai-claude-{safe_thread_id}`
- `safe_thread_id`：`thread_id` 中的非字母数字字符替换为 `-`
- 最大长度限制（tmux session name）

### 13.3 用户输入中继

```python
relay_input(text)
  → tmux send-keys -t ai-claude-{session_id} "{text}" Enter
```

### 13.4 会话状态检测

- `is_alive()` → `tmux has-session -t {session_id}`
- `get_output(n_lines)` → tail log file

### 13.5 关键约束

- **必须 `unset ANTHROPIC_API_KEY`**：否则 OAuth session 被 API Key 覆盖 → 401
- **使用 `--permission-mode acceptEdits`**：root 环境下禁止 `--dangerously-skip-permissions`
- **stream-json 格式**：实时解析输出推送 IM

---

## 14. 错误处理与自修复

**文件**：`integrations/logging/error_tracker.py`

### 14.1 错误检测

监控 LLM 响应中的错误关键词：
- "错误"、"异常"、"失败"
- "Exception"、"Error"、"Failed"
- "超时"、"timeout"

**误报过滤**：
- "分析错误率"、"错误日志" 等分析性语境不触发

### 14.2 自动修复流程

```
检测到错误响应
  ↓
计算 error_hash（错误类型 + 位置）
  ↓
查询 auto_fix_tracker.json
  ├─ count < 3 → 触发 trigger_self_improvement() → 分析日志 → 尝试修复
  └─ count >= 3 → 停止自动修复 + 通知用户 + 创建 GitHub Issue
```

### 14.3 自改进分析（`trigger_self_improvement`）

分析内容：
- 近 50 条 `logs/interactions.jsonl` 记录
- 计算：纠错率、响应延迟（p50/p90）、工具使用分布
- 生成分析报告（Markdown 格式）
- 写入飞书知识库 + 推送 IM 通知
- 更新 `workspace/MEMORY.md`

### 14.4 LLM 调用日志（`logs/llm.jsonl`）

每次 LLM 调用记录：
```json
{
  "timestamp": "2026-03-22T10:00:00",
  "model": "ep-xxx",
  "latency_ms": 3200,
  "input_tokens": 12000,
  "output_tokens": 450,
  "tool_calls": ["feishu_read_page", "web_search"],
  "thread_id": "feishu:oc_xxx"
}
```

### 14.5 交互日志（`logs/interactions.jsonl`）

记录每次用户交互的完整信息（去重后）。

---

## 15. 配置管理

### 15.1 环境变量（`.env`）

**必选配置**：

```bash
# 飞书
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxx
FEISHU_WIKI_SPACE_ID=7618158120166034630
FEISHU_WIKI_CONTEXT_PAGE=FalZwGDOkiqpbQkeAjGc8jaznMd

# 钉钉
DINGTALK_CLIENT_ID=xxxxxxxxxx
DINGTALK_CLIENT_SECRET=xxxxxxxxxx
DINGTALK_AGENT_ID=xxxxxxxxxx

# 主力 LLM（火山云）
VOLCENGINE_API_KEY=xxxxxxxxxx
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
VOLCENGINE_MODEL=ep-20260317143459-qtgqn

# 备用 LLM（OpenRouter）
OPENROUTER_API_KEY=xxxxxxxxxx
OPENROUTER_MODEL=anthropic/claude-sonnet-4-5

# Claude Code（仅 CLI，不传给子进程）
ANTHROPIC_API_KEY=sk-ant-xxxx
```

**可选配置**：

```bash
# 邮件（163）
EMAIL_ADDRESS=xxx@163.com
EMAIL_AUTH_CODE=xxxxxxxxxx
IMAP_HOST=imap.163.com
IMAP_PORT=993

# 钉钉 MCP
DINGTALK_MCP_URL=https://xxx
DINGTALK_MCP_TABLE_URL=https://xxx

# 飞书 OAuth（高权限 wiki 操作）
FEISHU_USER_ACCESS_TOKEN=u-xxxxxxxxxx
FEISHU_USER_REFRESH_TOKEN=xxxxxxxxxx
FEISHU_USER_REFRESH_EXPIRES_AT=1748000000

# 已知 wiki 节点（无 user token 时用于创建子页面）
FEISHU_WIKI_ROOT_NODES=token1,token2

# 日志
LOG_LEVEL=INFO
```

### 15.2 运行时配置（SQLite `agent_config` 表）

可通过 `agent_config` 工具或 Admin UI 修改，**无需重启**：

| 键 | 说明 | 来源 |
|------|------|------|
| `OWNER_FEISHU_CHAT_ID` | 心跳推送目标 chat_id | 手动配置 |
| `FEISHU_WIKI_MEETING_PAGE` | 会议纪要汇总页 wiki token | 手动配置 |
| `DINGTALK_DOCS_SPACE_ID` | 钉钉文档空间 ID | 自动探测 |
| `DINGTALK_WIKI_API_PATH` | 钉钉 API 路径 | 自动探测并缓存 |
| `FEISHU_WIKI_ROOT_NODES` | 已知 wiki 根节点（逗号分隔） | 手动配置 |

**优先级**：SQLite > `.env`（SQLite 可覆盖 `.env` 中同名配置）

---

## 16. Admin 管理界面

**文件**：`admin/server.py`
**URL**：`http://localhost:8080`
**用途**：运行时配置管理，无需重启

### 16.1 功能

- **查看配置**：列出所有 `agent_config` 键值对
- **修改配置**：设置 key-value（AJAX 表单提交）
- **删除配置**：删除指定 key
- **状态查看**：系统运行状态概览

### 16.2 安全

- 仅绑定 `localhost`，不暴露外网
- 无认证（个人使用，受信环境）

---

## 17. 上下文同步

**文件**：`sync/context_sync.py`

### 17.1 功能

将本地 SQLite LangGraph checkpoints 摘要同步到飞书知识库上下文页面。

### 17.2 触发方式

- 定时：每 30 分钟自动执行（`scheduler.py`）
- 手动：调用 `sync_context_to_feishu()` 工具

### 17.3 同步内容

- 近期活跃 thread_id 列表
- 每个 thread_id 的最后几条消息摘要
- 活跃话题统计
- 写入 `FEISHU_WIKI_CONTEXT_PAGE`（覆盖模式）

---

## 18. 并发任务框架

**文件**：`graph/parallel.py`

### 18.1 工具并行执行（`run_tools_parallel()`）

- 单个工具调用 → 同步执行
- 多个工具调用 → `ThreadPoolExecutor(max_workers=6)` 并行
- 结果顺序：按原始 tool_calls 顺序保存（`Future` 映射）

**串行工具（`_SERIAL_TOOLS`）**：
- `feishu_overwrite_page`（写操作，防并发覆盖）
- `sync_context_to_feishu`（写操作）
- 其他有副作用的写工具

### 18.2 优先级任务队列

```python
class PriorityQueue:
    URGENT = 0
    NORMAL = 1
    LOW = 2
```

- 支持三级优先级
- 高优先级任务先执行

### 18.3 TaskMonitor

- 追踪长时间运行的任务
- 超时检测
- 任务状态查询接口

### 18.4 线程上下文（`_tool_ctx`）

```python
# 线程局部变量，供工具函数读取当前会话信息
_tool_ctx = threading.local()
_tool_ctx.thread_id  # 当前话题 ID
_tool_ctx.send_fn    # 向 IM 发送消息的函数
```

**用途**：工具函数可直接向用户发送中间进度消息（不通过返回值）。

---

## 19. 数据模型

### 19.1 AgentState 字段语义

| 字段 | 类型 | 语义 | 说明 |
|------|------|------|------|
| `messages` | `list[BaseMessage]` | 完整对话历史 | 含 System/Human/AI/Tool 消息，不按轮次截断 |
| `platform` | `str` | 来源平台 | `"feishu"` / `"dingtalk"` |
| `user_id` | `str` | 用户标识 | 飞书 `open_id` / 钉钉 `unionId` |
| `chat_id` | `str` | 聊天窗口 | 飞书 `chat_id` / 钉钉 `conversationId` |
| `thread_id` | `str` | 话题隔离键 | 用于 LangGraph checkpoint 分组 |
| `intent` | `str` | 意图（预留） | 尚未实际使用 |

### 19.2 LLM Message 类型

| 类型 | 来源 | 说明 |
|------|------|------|
| `SystemMessage` | `_build_system_prompt()` | 系统角色设定（每次动态构建） |
| `HumanMessage` | 用户输入 | 来自飞书/钉钉的用户消息 |
| `AIMessage` | LLM 输出 | 可含 `tool_calls` 字段 |
| `ToolMessage` | 工具执行结果 | 完整保留（不截断），确保 LLM 获得完整工具结果 |

### 19.3 飞书 API 数据类型

| 概念 | 字段名 | 说明 |
|------|--------|------|
| Wiki 节点 token | `node_token` / `wiki_token` | 知识库页面唯一标识 |
| 文档 token | `obj_token` | 底层 docx/sheet/bitable 对象 ID |
| 文档类型 | `obj_type` | `docx` / `sheet` / `bitable` |
| 空间 ID | `space_id` | 知识库空间（非节点 token！） |
| 聊天 ID | `chat_id` | 飞书聊天窗口（群组或单聊） |
| 用户 ID | `open_id` | 飞书用户在应用维度的 ID |

**⚠️ 关键区分**：`space_id` ≠ `node_token`，不可互换使用。

---

## 20. 安全设计

### 20.1 无端口暴露

- 无 HTTP 服务器（除 localhost:8080 Admin UI）
- 客户端主动建立长连接，无需公网 IP/域名

### 20.2 API Key 隔离

- `ANTHROPIC_API_KEY` 仅用于 Claude Code CLI（当前进程）
- Claude Code 子进程执行 `unset ANTHROPIC_API_KEY`，使用 OAuth session token
- 防止子进程泄漏 API key

### 20.3 凭据管理

- 所有密钥通过 `.env` 注入，不硬编码
- `.env` 在 `.gitignore` 中，不入版本控制
- 运行时配置存 SQLite，不写 `.env`

### 20.4 Wiki Token 安全

- 绝对禁止凭记忆/猜测 wiki token
- 绝对禁止使用 placeholder 字符串（如 `YOUR_WIKI_TOKEN`）
- Token 必须通过实时 API 获取（`feishu_wiki_page` 或用户 URL）

---

## 21. 部署与启动

### 21.1 环境要求

- Linux（云服务器）
- Python 3.10+（venv）
- tmux（Claude Code 会话管理）

### 21.2 启动命令

```bash
cd /root/ai-assistant
source .venv/bin/activate     # ⚠️ 必须激活 venv
python main.py                 # 前台运行

# 后台运行
nohup python main.py >> logs/app.log 2>&1 &
```

### 21.3 重启命令

```bash
kill $(cat logs/service.pid 2>/dev/null) 2>/dev/null
source .venv/bin/activate && nohup python main.py >> logs/app.log 2>&1 &
```

**⚠️ 直接 `python main.py`（不激活 venv）会报 `ModuleNotFoundError: No module named 'dotenv'`**

### 21.4 日志查看

```bash
tail -f logs/app.log                          # 主应用日志
tail -f logs/crash.log | python -m json.tool  # 崩溃日志
tail -f logs/llm.jsonl | python -m json.tool  # LLM 调用日志
tmux list-sessions | grep ai-claude           # Claude 会话列表
```

### 21.5 Claude Code 会话直连

```bash
tmux attach -t ai-claude-{safe_thread_id}
# Ctrl+b d 退出（不终止会话）
```

---

## 22. 依赖项

**文件**：`requirements.txt`

| 包 | 版本要求 | 用途 |
|----|---------|------|
| `langgraph` | >=0.2.50 | ReAct Agent 图结构 |
| `langchain-openai` | >=0.3.0 | OpenAI 兼容 LLM 客户端 |
| `langchain-core` | >=0.3.0 | 核心抽象（Message、Tool） |
| `langgraph-checkpoint-sqlite` | >=3.0.0 | SQLite Checkpointer |
| `langchain-mcp-adapters` | >=0.2.0 | MCP 协议适配器 |
| `apscheduler` | >=3.10.0 | 定时任务调度 |
| `python-dotenv` | >=1.0.0 | `.env` 文件加载 |
| `lark-oapi` | >=1.5.0 | 飞书 WebSocket SDK |
| `dingtalk-stream` | >=0.24.0 | 钉钉流模式 SDK |
| `httpx` | >=0.28.0 | 异步 HTTP 客户端 |
| `imapclient` | >=3.0.1 | IMAP 邮件客户端 |
| `pydantic` | >=2.10.0 | 配置验证 |
| `openpyxl` | >=3.1.0 | Excel 文件解析 |

---

## 23. 已知限制与约束

### 23.1 工具迭代上限

- `MAX_TOOL_ITERATIONS=15`（`graph/nodes.py`）
- 超限时强制终止并通知用户
- 防止 LLM 陷入无限工具调用循环（复杂任务如 web_search 并行 + 自迭代通常需 8-12 次）

### 23.2 IM 消息长度

- **限制**：400 字符
- **超限行为**：写入飞书知识库页面 + 返回页面链接

### 23.3 会议文档处理

- 内容截断：6000 字符（减少 LLM token 消耗）
- LLM 超时：30 秒
- 仅处理文本型文档（不支持图片、附件型）

### 23.4 邮件功能

- 仅支持 163 邮箱 IMAP
- 需配置"授权码"（非账号密码）
- 当前因 IMAP 授权码问题暂不可用（⚠️ 需重新配置）

### 23.5 飞书 wiki 权限

- `POST /wiki/v2/spaces/{id}/nodes` 需要 wiki 空间成员权限（131006）
- 解决方案（三选一）：
  1. 将应用添加为 wiki 空间成员
  2. 配置 `FEISHU_WIKI_ROOT_NODES`
  3. 配置 `FEISHU_USER_ACCESS_TOKEN`/`FEISHU_USER_REFRESH_TOKEN`
- **注意**：开通 `wiki:wiki` 应用权限 ≠ wiki 空间成员权限（两者完全独立）

### 23.6 钉钉 MCP

- 依赖远程 MCP Server 可用性
- 启动时连接失败 → 降级使用直接 API（部分功能缺失）

---

## 24. 测试基础设施

**目录**：`tests/`

### 24.1 AI 场景测试（`tests/ai_scenarios/`）

| 文件 | 场景 | 场景码 |
|------|------|--------|
| `test_color_value.py` | 染发色值还原偏差 | `COL` |
| `test_live_stream.py` | 直播数字人抖音适配 | `LIVE` |
| `test_cross_platform.py` | 跨平台兼容性 + 模型监控 | `PLAT` |

**测试 ID 格式**：`TC-{场景码}-{两位序号}`（如 `TC-COL-01`）

### 24.2 回归测试（`tests/regression/`）

覆盖以下场景：
- 工具调用模式（正确参数、错误参数）
- Bot 行为边界（问候快速路径、斜杠命令）
- 飞书 wiki 操作（读、写、搜索、权限错误）
- 话题路由（主窗口短标题、相近话题合并）
- 会议格式（分析输出格式验证）
- 上下文管理（话题隔离、checkpoint 持久化）
- 错误场景（token 过期、网络超时、131006）
- 钉钉 MCP 集成（工具可用性、降级行为）
- 火山云文本格式工具调用（多种变体解析）

### 24.3 CI/CD

**文件**：`.github/workflows/ai_scenarios_ci.yml`

- GitHub Actions 触发
- 运行 AI 场景测试
- 测试报告输出到 `reports/ai_scenarios/`

---

## 附录 A：错误码速查

| 错误码 | 来源 | 含义 | 处理 |
|--------|------|------|------|
| 131006 | 飞书 wiki | 空间权限缺失 | 添加应用为空间成员 / 配置 user token |
| 99991668 | 飞书 | tenant token 过期 | 自动刷新，无需干预 |
| 99991677 | 飞书 | user token 过期，可刷新 | 自动刷新，无需干预 |
| 20024/20037 | 飞书 | refresh token 无效 | 用户重新 OAuth 授权 |
| 99991672/99991679 | 飞书 | 应用 API 权限缺失 | 管理员在开放平台开通权限 |

---

## 附录 B：工具触发关键词速查

| 工具分类 | 触发关键词 |
|---------|-----------|
| `feishu_wiki` | 飞书、wiki、知识库、项目、章程、周报、里程碑、文档、页面、写入、记录 |
| `feishu_advanced` | 多维表格、bitable、任务、日历、表格、电子表格 |
| `claude` | 迭代、开发、claude、代码、编写、修复、功能、bug、feature |
| `dingtalk_mcp` | 钉钉、dingtalk、会议、纪要、alidocs |

---

## 附录 C：飞书 Wiki 操作决策树

```
需要操作飞书知识库？
  │
  ├─ 读取已有页面内容
  │   → feishu_read_page(wiki_url_or_token)
  │
  ├─ 向已有页面追加内容
  │   → feishu_append_to_page(wiki_url_or_token, content)
  │
  ├─ 替换已有页面全部内容
  │   → feishu_overwrite_page(wiki_url_or_token, content)
  │
  ├─ 搜索上下文页面内容
  │   → feishu_search_wiki(query)
  │
  ├─ 列出子页面
  │   → feishu_wiki_page(action="list_children", wiki_token=...)
  │
  ├─ 创建新页面
  │   → feishu_wiki_page(action="create_page", parent_token=..., title=..., content=...)
  │   ⚠️ 需要 user token 或 FEISHU_WIKI_ROOT_NODES
  │
  └─ 删除页面（不可撤销）
      → feishu_wiki_delete(node_token=...)
      ⚠️ 需要用户确认
```

---

*本文档根据 v1.0.18 代码自动分析生成，最后更新：2026-03-23*
*如发现文档与代码不一致，请以代码实现为准，并更新本文档。*
