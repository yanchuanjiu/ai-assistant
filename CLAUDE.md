# AI 个人助理 — Claude Code 项目上下文

> 本文件是 Claude Code 自迭代的首要参考，进入项目目录后**先读此文件**再动手。
> 最后更新：2026-03-17（v0.5.0）

---

## 项目定位

个人非商用 AI 助理，部署在 Linux 云服务器（`/root/ai-assistant`）。
通过飞书/钉钉机器人对话交互，**无稳定性/性能硬性要求，可用性和可迭代性优先**。

---

## 当前运行状态（v0.5.0）

```
✅ 飞书机器人      — 长连接（lark-oapi ws.Client），收发消息正常
✅ 钉钉机器人      — 流模式（dingtalk-stream），连接已建立
✅ 火山云 LLM     — ep-20260317143459-qtgqn，调用正常
✅ SQLite 记忆    — data/memory.db，LangGraph checkpointer
✅ 定时任务        — 邮件60分钟/上下文同步30分钟
✅ 飞书知识库      — 读写正常（docx API via get_node）
                    context page: FalZwGDOkiqpbQkeAjGc8jaznMd
✅ Claude Code迭代 — session_manager，stream-json 实时推送 IM，用户可交互
✅ 无限制 CLI      — run_command（无白名单）

⚠️  钉钉文档      — /v1.0/doc/spaces API 404，路径待修复
⚠️  163 IMAP     — 需在 163 网页版重新开启 IMAP 并更新 EMAIL_AUTH_CODE
```

---

## 技术栈

| 层 | 技术 | 备注 |
|----|------|------|
| Web | FastAPI + uvicorn | port 8000 |
| Agent | LangGraph ReAct + SQLite Checkpointer | thread_id = platform:chat_id |
| 主力 LLM | 火山云 Ark `ep-20260317143459-qtgqn` | OpenAI-compatible |
| 备用 LLM | OpenRouter `anthropic/claude-sonnet-4-5` | with_fallbacks 自动切换 |
| 自迭代 | Claude Code CLI（`--permission-mode acceptEdits`） | OAuth session，不用 API Key |
| 飞书 | `lark-oapi` SDK，ws.Client 长连接 | 无需公网 |
| 钉钉 | `dingtalk-stream` SDK，流模式 | 无需公网 |
| 定时任务 | APScheduler | 邮件60min，同步30min |

---

## 目录结构

```
graph/                   LangGraph：state / agent / nodes / tools
  ├── agent.py           图定义 + SQLite checkpointer + invoke() 入口
  ├── nodes.py           agent_node / tools_node（含 tool context 注入）
  ├── state.py           AgentState TypedDict
  └── tools.py           9 个工具，ALL_TOOLS 导出

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
  │   ├── imap_client.py 163 IMAP 轮询（认证失败有详细提示）
  │   └── parser.py      Claude Haiku 提取会议信息
  ├── claude_code/
  │   └── session.py     ClaudeCodeSession + SessionManager + reply_fn_registry
  └── storage/           LocalStorage / 待接火山云 OSS

sync/context_sync.py     SQLite checkpoints → 飞书知识库页面
prompts/
  ├── system.md          Agent system prompt（含工具使用规则）
  └── meeting_extract.md 会议信息提取 prompt
scheduler.py             APScheduler（邮件60min / 同步30min）
main.py                  FastAPI lifespan + 两个平台线程
```

---

## 核心设计决策（含坑点）

### 1. 无公网 Webhook
飞书用 `lark-oapi ws.Client` 长连接，钉钉用 `dingtalk-stream` 流模式，均为服务器主动出连接。

### 2. LLM 分离：Agent ≠ Claude CLI
- **Agent LLM**：火山云 Ark → OpenRouter（OpenAI-compatible，`VOLCENGINE_API_KEY`）
- **自迭代 CLI**：`claude` 命令，使用 OAuth session token（**不传 `ANTHROPIC_API_KEY`**）
- ⚠️ 关键：在 session.py 中启动子进程时必须从 env 排除 `ANTHROPIC_API_KEY`，否则会覆盖 OAuth session 导致 401

### 3. 飞书知识库权限绕过
`/wiki/v2/spaces` 系列 API **不支持 tenant_access_token**（需要用户 OAuth）。
绕过方案：
1. `GET /wiki/v2/spaces/get_node?token=WIKI_TOKEN` → 获取 `obj_token`（tenant token 可用）
2. `/docx/v1/documents/{obj_token}/...` → docx API 直接读写（tenant token 可用）
3. 前提：在飞书页面「文档权限 → 可管理应用」添加该应用

### 4. Claude Code 子进程权限
运行环境是 root，`--dangerously-skip-permissions` 被禁止。
使用 `--permission-mode acceptEdits --output-format stream-json --verbose`。

### 5. Claude Code 流式推送架构
```
bot._on_message()
  → 注册 reply_fn_registry[thread_id] = bot.send_text
  → session_manager.get(thread_id) → 有活跃会话则 relay_input，skip agent
  → 否则 invoke(agent)
      → tools_node: set_tool_ctx(thread_id, send_fn)
          → trigger_self_iteration: 读取 get_tool_ctx()
              → session_manager.start(thread_id, requirement, send_fn)
                  → ClaudeCodeSession.start_streaming()
                      → 后台线程解析 stream-json → send_fn → IM
```

### 6. 消息回复解耦
`graph/agent.py` 的 `invoke()` 只返回文本，各平台 bot handler 负责发送。

---

## 工具列表（9个）

| 工具 | 描述 |
|------|------|
| `feishu_read_page` | 读取飞书 wiki 页面（URL 或 token） |
| `feishu_append_to_page` | 向页面末尾追加内容 |
| `feishu_overwrite_page` | 清空并覆盖写入页面 |
| `feishu_search_wiki` | 在上下文页面中搜索关键词 |
| `sync_context_to_feishu` | SQLite 记忆 → 飞书知识库 |
| `get_latest_meeting_docs` | 获取最新钉钉会议纪要列表 |
| `read_meeting_doc` | 读取钉钉文档完整内容 |
| `trigger_self_iteration` | 异步启动 Claude Code，流式推送到 IM |
| `run_command` | 执行任意 shell 命令（无白名单） |

---

## 待完成事项（优先级排序）

| 优先级 | 问题 | 位置 | 行动 |
|--------|------|------|------|
| 中 | 163 IMAP 认证失败 | `.env EMAIL_AUTH_CODE` | 163 网页版重新开启 IMAP，生成新授权码 |
| 中 | 钉钉文档 API 404 | `integrations/dingtalk/docs.py` | 确认正确 API 路径 |
| 低 | 火山云 OSS 未接入 | `integrations/storage/` | 按需接入 |
| 低 | 飞书知识库语义搜索 | `integrations/feishu/knowledge.py` | 当前为关键词匹配 |

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
```

---

## 自迭代规则（Claude Code 须知）

1. **先读此文件**，理解现有架构再动手
2. **最小改动原则**：只改需求涉及的文件
3. **新增工具**：在 `graph/tools.py` 加 `@tool` 函数，加入 `ALL_TOOLS`
4. **新增平台集成**：在 `integrations/` 新建子目录，在 `main.py` 注册启动线程
5. **Claude Code 子进程**：必须排除 `ANTHROPIC_API_KEY`，使用 `--permission-mode acceptEdits`
6. **完成后**：① 修改了哪些文件 ② 做了什么 ③ 如何验证 ④ 更新 CLAUDE.md 状态表
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
