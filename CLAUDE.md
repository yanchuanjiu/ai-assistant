# AI 个人助理 — Claude Code 项目上下文

> 本文件是 Claude Code 自迭代的首要参考，进入项目目录后**先读此文件**再动手。
> 最后更新：2026-03-17（v0.6.0）

---

## 项目定位

个人非商用 AI 助理，部署在 Linux 云服务器（`/root/ai-assistant`）。
通过飞书/钉钉机器人对话交互，**无稳定性/性能硬性要求，可用性和可迭代性优先**。

**代码管理原则**：每次确认变更后立即 `git add + commit + push`，确保远程仓库始终是最新版本。

---

## 当前运行状态（v0.6.0）

```
✅ 飞书机器人      — 长连接（lark-oapi ws.Client），收发消息正常
✅ 钉钉机器人      — 流模式（dingtalk-stream），连接已建立
✅ 火山云 LLM     — ep-20260317143459-qtgqn，调用正常
✅ SQLite 记忆    — data/memory.db，LangGraph checkpointer
✅ 定时任务        — 邮件60分钟/上下文同步30分钟
✅ 飞书知识库      — 读写正常（docx API via get_node）
                    context page: FalZwGDOkiqpbQkeAjGc8jaznMd
✅ Claude Code迭代 — tmux 会话（持久化），stream-json 实时推送 IM，用户可交互
✅ Claude 会话管理 — list/get_output/kill/send_input（4个工具）
✅ 无限制 CLI      — run_command（无白名单）+ python_execute
✅ Web 工具        — web_search（DuckDuckGo）+ web_fetch
✅ 系统监控        — get_system_status / get_service_status

⚠️  钉钉文档      — /v1.0/doc/spaces API 404，路径待修复
⚠️  163 IMAP     — 需在 163 网页版重新开启 IMAP 并更新 EMAIL_AUTH_CODE
```

---

## 版本变更历史

### v0.6.0（2026-03-17）— tmux 化 + 通用能力扩展

**变更原因**：
- 原 `subprocess.Popen` 方案在 Python 进程重启后 Claude 任务丢失，无法持久化
- 缺少通用能力（web 搜索、代码执行）和 Claude 会话管理工具
- 参考 OpenClaw（`larksuite-openclaw-lark-2026.3.15.tgz`）的工具体系扩充能力

**新增文件**：
- `integrations/claude_code/tmux_session.py` — 基于 tmux 的 Claude Code 会话管理器

**修改文件**：
- `integrations/claude_code/session.py` — 改为从 `tmux_session.py` 重新导出（向后兼容）
- `graph/tools.py` — 新增 9 个工具（共 18 个），新增 imports
- `prompts/system.md` — 更新为全量能力描述

**新增工具（9个）**：
| 工具 | 分类 | 描述 |
|------|------|------|
| `list_claude_sessions` | Claude 管理 | 列出所有活跃的 tmux Claude 会话 |
| `get_claude_session_output` | Claude 管理 | 获取会话最近输出 |
| `kill_claude_session` | Claude 管理 | 强制终止会话 |
| `send_claude_input` | Claude 管理 | 向会话发送追加输入 |
| `web_search` | Web | DuckDuckGo 搜索，无需 API key |
| `web_fetch` | Web | 获取任意 URL 纯文本内容 |
| `python_execute` | 代码执行 | 执行 Python 代码片段 |
| `get_system_status` | 系统 | CPU/内存/磁盘状态 |
| `get_service_status` | 系统 | FastAPI 进程、端口、Claude 会话状态 |

**tmux 架构要点**：
- Session 命名：`ai-claude-{safe_thread_id}`（safe = 非字母数字替换为 `-`）
- Prompt 写入 `/tmp/ai-claude-*.prompt`，输出写入 `/tmp/ai-claude-*.jsonl`
- Wrapper script `/tmp/ai-claude-*.sh` 排除 `ANTHROPIC_API_KEY`，防止覆盖 OAuth
- Python 进程后台线程 tail `.jsonl` 文件，解析 stream-json 推送到 IM
- Session 在 Python 进程重启后仍然存活（持久化）
- 可用 `tmux attach -t {name}` 直接查看

### v0.5.0（2026-03-17）— 流式推送 + 无限制 CLI

- Claude Code 流式推送到 IM（stream-json 解析）
- 用户可通过 IM 消息与运行中的 Claude 交互（stdin relay）
- `run_command` 无白名单限制
- 飞书知识库读写工具（read/append/overwrite/search）

### v0.4.0 及之前

- 初始 LangGraph ReAct 架构
- 飞书/钉钉双平台接入
- SQLite 记忆持久化
- 会议纪要邮件提取

---

## 技术栈

| 层 | 技术 | 备注 |
|----|------|------|
| Web | FastAPI + uvicorn | port 8000 |
| Agent | LangGraph ReAct + SQLite Checkpointer | thread_id = platform:chat_id |
| 主力 LLM | 火山云 Ark `ep-20260317143459-qtgqn` | OpenAI-compatible |
| 备用 LLM | OpenRouter `anthropic/claude-sonnet-4-5` | with_fallbacks 自动切换 |
| 自迭代 | Claude Code CLI（`--permission-mode acceptEdits`） | OAuth session，tmux 会话 |
| 飞书 | `lark-oapi` SDK，ws.Client 长连接 | 无需公网 |
| 钉钉 | `dingtalk-stream` SDK，流模式 | 无需公网 |
| 定时任务 | APScheduler | 邮件60min，同步30min |
| 进程管理 | tmux 3.4 | Claude Code 会话持久化 |

---

## 目录结构

```
graph/
  ├── agent.py           图定义 + SQLite checkpointer + invoke() 入口
  ├── nodes.py           agent_node / tools_node（含 tool context 注入）
  ├── state.py           AgentState TypedDict
  └── tools.py           18 个工具，ALL_TOOLS 导出

integrations/
  ├── feishu/
  │   ├── bot.py         长连接消息处理，注册 reply_fn_registry，Claude 会话拦截
  │   ├── client.py      tenant_access_token + feishu_get/post/delete
  │   └── knowledge.py   wiki 读写（parse_wiki_token → get_node → docx API）
  ├── dingtalk/
  │   ├── bot.py         流模式消息处理，同上 Claude 会话拦截
  │   ├── client.py      DingTalk OAuth token
  │   └── docs.py        文档空间读取（API 路径待修复）
  ├── email/
  │   ├── imap_client.py 163 IMAP 轮询
  │   └── parser.py      Claude Haiku 提取会议信息
  ├── claude_code/
  │   ├── session.py     向后兼容重新导出（→ tmux_session.py）
  │   └── tmux_session.py  TmuxClaudeSession + SessionManager（tmux 实现）
  └── storage/           LocalStorage / 待接火山云 OSS

sync/context_sync.py     SQLite checkpoints → 飞书知识库页面
prompts/
  ├── system.md          Agent system prompt（18 个工具的完整能力描述）
  └── meeting_extract.md 会议信息提取 prompt
scheduler.py             APScheduler（邮件60min / 同步30min）
main.py                  FastAPI lifespan + 两个平台线程

larksuite-openclaw-lark-2026.3.15.tgz  OpenClaw 飞书集成参考包（技能/工具参考）
```

---

## 核心设计决策（含坑点）

### 1. 无公网 Webhook
飞书用 `lark-oapi ws.Client` 长连接，钉钉用 `dingtalk-stream` 流模式，均为服务器主动出连接。

### 2. LLM 分离：Agent ≠ Claude CLI
- **Agent LLM**：火山云 Ark → OpenRouter（OpenAI-compatible，`VOLCENGINE_API_KEY`）
- **自迭代 CLI**：`claude` 命令，使用 OAuth session token（**不传 `ANTHROPIC_API_KEY`**）
- ⚠️ 关键：wrapper script 中 `unset ANTHROPIC_API_KEY`，否则会覆盖 OAuth session 导致 401

### 3. 飞书知识库权限绕过
`/wiki/v2/spaces` 系列 API **不支持 tenant_access_token**（需要用户 OAuth）。
绕过方案：
1. `GET /wiki/v2/spaces/get_node?token=WIKI_TOKEN` → 获取 `obj_token`（tenant token 可用）
2. `/docx/v1/documents/{obj_token}/...` → docx API 直接读写（tenant token 可用）
3. 前提：飞书页面「文档权限 → 可管理应用」添加该应用

### 4. Claude Code 子进程权限
运行环境是 root，`--dangerously-skip-permissions` 被禁止。
使用 `--permission-mode acceptEdits --output-format stream-json --verbose`。

### 5. Claude Code tmux 会话架构

```
bot._on_message()
  → 注册 reply_fn_registry[thread_id] = bot.send_text
  → session_manager.get(thread_id) → 有活跃 tmux 会话则 relay_input，skip agent
  → 否则 invoke(agent)
      → tools_node: set_tool_ctx(thread_id, send_fn)
          → trigger_self_iteration 调用 session_manager.start()
              → TmuxClaudeSession.start_streaming(requirement)
                  ① 写 prompt 到 /tmp/ai-claude-*.prompt
                  ② 清空 /tmp/ai-claude-*.jsonl
                  ③ 写 wrapper script /tmp/ai-claude-*.sh（含 unset ANTHROPIC_API_KEY）
                  ④ tmux new-session -d -s {name} {script}
                  ⑤ 后台线程 tail .jsonl，解析 stream-json → send_fn → IM

tmux session 名称：ai-claude-{safe_thread_id}
日志文件：        /tmp/ai-claude-{safe_thread_id}.jsonl
直接查看：        tmux attach -t ai-claude-{safe_thread_id}
```

### 6. 消息回复解耦
`graph/agent.py` 的 `invoke()` 只返回文本，各平台 bot handler 负责发送。

### 7. 火山云文本格式工具调用
火山云 Ark 有时以文本形式返回工具调用，格式为 `<|FunctionCallBeginBegin|>[...]`。
`graph/nodes.py` 的 `_extract_text_tool_calls()` 负责解析，转换为标准 LangChain tool_calls。

---

## 工具列表（18个）

| 工具 | 分类 | 描述 |
|------|------|------|
| `feishu_read_page` | 飞书 | 读取飞书 wiki 页面（URL 或 token） |
| `feishu_append_to_page` | 飞书 | 向页面末尾追加内容 |
| `feishu_overwrite_page` | 飞书 | 清空并覆盖写入页面 |
| `feishu_search_wiki` | 飞书 | 在上下文页面中搜索关键词 |
| `sync_context_to_feishu` | 飞书 | SQLite 记忆 → 飞书知识库 |
| `get_latest_meeting_docs` | 钉钉 | 获取最新钉钉会议纪要列表 |
| `read_meeting_doc` | 钉钉 | 读取钉钉文档完整内容 |
| `trigger_self_iteration` | Claude | 异步启动 Claude Code tmux 会话，流式推送到 IM |
| `list_claude_sessions` | Claude | 列出所有活跃的 tmux Claude 会话 |
| `get_claude_session_output` | Claude | 获取指定会话的最近输出 |
| `kill_claude_session` | Claude | 强制终止 Claude tmux 会话 |
| `send_claude_input` | Claude | 向会话发送追加输入 |
| `web_search` | Web | DuckDuckGo 搜索，无需 API key |
| `web_fetch` | Web | 获取任意 URL 纯文本内容 |
| `python_execute` | 代码 | 执行 Python 代码片段 |
| `run_command` | 系统 | 执行任意 shell 命令（无白名单） |
| `get_system_status` | 系统 | CPU/内存/磁盘状态 |
| `get_service_status` | 系统 | FastAPI 进程、端口、Claude 会话状态 |

---

## 待完成事项（优先级排序）

| 优先级 | 问题 | 位置 | 行动 |
|--------|------|------|------|
| 中 | 163 IMAP 认证失败 | `.env EMAIL_AUTH_CODE` | 163 网页版重新开启 IMAP，生成新授权码 |
| 中 | 钉钉文档 API 404 | `integrations/dingtalk/docs.py` | 确认正确 API 路径 |
| 低 | 火山云 OSS 未接入 | `integrations/storage/` | 按需接入 |
| 低 | 飞书知识库语义搜索 | `integrations/feishu/knowledge.py` | 当前为关键词匹配 |
| 低 | OpenClaw 飞书工具扩展 | `integrations/feishu/` | 参考 `larksuite-openclaw-lark-2026.3.15.tgz` 中的 bitable/calendar/task/chat 工具 |

---

## 启动 / 重启

```bash
cd /root/ai-assistant
source .venv/bin/activate
python main.py

# 后台运行
nohup python main.py > logs/app.log 2>&1 &

# 查看日志
tail -f logs/app.log

# 重启（改完代码后）
kill $(lsof -ti:8000) 2>/dev/null; python main.py &

# 查看 Claude tmux 会话
tmux list-sessions | grep ai-claude
tmux attach -t ai-claude-{session_name}
```

---

## 自迭代规则（Claude Code 须知）

1. **先读此文件**，理解现有架构再动手
2. **最小改动原则**：只改需求涉及的文件
3. **新增工具**：在 `graph/tools.py` 加 `@tool` 函数，加入 `ALL_TOOLS`，更新本文件工具表
4. **新增平台集成**：在 `integrations/` 新建子目录，在 `main.py` 注册启动线程
5. **Claude Code 子进程**：必须 `unset ANTHROPIC_API_KEY`（wrapper script 中），使用 `--permission-mode acceptEdits`
6. **完成后必做**：
   - ① 修改了哪些文件
   - ② 做了什么、为什么
   - ③ 如何验证
   - ④ 更新本文件（CLAUDE.md）：状态表 + 变更历史 + 工具表
   - ⑤ **提交并推送**：`git add -A && git commit -m "..." && git push`
7. **重启方式**：`kill $(lsof -ti:8000) 2>/dev/null; python main.py &`

---

## 关键配置（.env）

```
FEISHU_APP_ID=cli_a8fec6e8585d100d
FEISHU_WIKI_SPACE_ID=7618158120166034630
FEISHU_WIKI_CONTEXT_PAGE=FalZwGDOkiqpbQkeAjGc8jaznMd  # AI助理上下文快照页

VOLCENGINE_MODEL=ep-20260317143459-qtgqn
OPENROUTER_MODEL=anthropic/claude-sonnet-4-5

# ANTHROPIC_API_KEY — 仅供 Claude Code CLI 在 Claude Code 界面内使用
# 不会传入 trigger_self_iteration 启动的子进程（子进程用 OAuth session）
```

---

## OpenClaw 参考资料

`larksuite-openclaw-lark-2026.3.15.tgz` 是飞书 OpenClaw 集成包，包含以下可参考的飞书 API 工具和技能：

| 模块 | 对应飞书 API | 扩展优先级 |
|------|------------|---------|
| `tools/oapi/bitable/` | 多维表格 CRUD（27 种字段类型） | 低 |
| `tools/oapi/calendar/` | 日历事件、日程、空闲查询 | 低 |
| `tools/oapi/task/` | 任务、子任务、任务列表 | 低 |
| `tools/oapi/chat/` | 群组管理 | 低 |
| `tools/oapi/drive/` | 云文档（非 wiki）读写 | 低 |
| `tools/oapi/search/` | 飞书全文搜索 | 低 |
| `skills/feishu-bitable/` | Bitable 使用技能 | 低 |
| `skills/feishu-calendar/` | 日历操作技能 | 低 |
| `skills/feishu-task/` | 任务管理技能 | 低 |

如需扩展飞书能力，从 tgz 中提取对应模块并适配为 Python `@tool` 函数。
