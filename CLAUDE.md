# AI 个人助理 — Claude Code 项目上下文

> 本文件是 Claude Code 自迭代的首要参考，进入项目目录后**先读此文件**再动手。
> 最后更新：2026-03-21（v0.8.29）

---

## 项目定位

个人非商用 AI 助理，部署在 Linux 云服务器（`/root/ai-assistant`）。
通过飞书/钉钉机器人对话交互，**无稳定性/性能硬性要求，可用性和可迭代性优先**。

---

## 当前运行状态

```
✅ 飞书机器人      — 长连接（lark-oapi ws.Client）
✅ 钉钉机器人      — 流模式（dingtalk-stream）
✅ 火山云 LLM     — ep-20260317143459-qtgqn，OpenAI-compatible
✅ SQLite 记忆    — data/memory.db（LangGraph checkpointer）/ data/meeting.db
✅ 定时任务        — 钉钉会议30min / 邮件60min / 上下文同步30min / 心跳30min / 每日迁移08:00
✅ 飞书知识库      — docx API via get_node（context page: FalZwGDOkiqpbQkeAjGc8jaznMd）
✅ 会议纪要闭环    — 钉钉轮询 → LLM 分析 → 飞书写入（自动 + 按需 + 每日富文本迁移）
✅ Claude Code    — tmux 会话（持久化），stream-json 实时推送 IM
✅ 进程管理        — supervised thread + 指数退避自动重启，崩溃写 logs/crash.log
✅ Admin 界面      — http://localhost:8080（Web 配置管理，无需重启）
✅ 渐进式工具披露  — CORE_TOOLS（9个）+ 按关键词动态注入，节省 ~87% token
✅ 并发任务框架    — graph/parallel.py：工具并行执行 + 优先级队列（URGENT/NORMAL/LOW）+ TaskMonitor
✅ Workspace 体系 — workspace/{SOUL/USER/MEMORY/HEARTBEAT/SKILLS_*}.md 动态注入 system prompt
✅ 自我改进        — trigger_self_improvement，分析日志 → 优化 → 推送报告
✅ 单轮上下文      — MAX_USER_TURNS=2，历史 ToolMessage 截断至 100 字符
✅ 问候快速路径    — 纯问候词直接回复，不走 LLM
✅ 钉钉 MCP       — 文档12个 + AI 表格21个工具，关键词"钉钉"触发

⚠️  163 IMAP     — 需在 163 网页版重新开启 IMAP 并更新 EMAIL_AUTH_CODE
```

---

## 核心设计决策（含坑点）

### 1. 无公网 Webhook
飞书用 `lark-oapi ws.Client` 长连接，钉钉用 `dingtalk-stream` 流模式，均为服务器主动出连接。

### 2. LLM 分离：Agent ≠ Claude CLI
- **Agent LLM**：火山云 Ark → OpenRouter fallback（`VOLCENGINE_API_KEY`）
- **自迭代 CLI**：`claude` 命令，使用 OAuth session token
- ⚠️ **关键**：wrapper script 中必须 `unset ANTHROPIC_API_KEY`，否则覆盖 OAuth session 导致 401

### 3. 飞书知识库权限说明
读写已有页面（tenant_access_token 可用）：
1. `GET /wiki/v2/spaces/get_node?token=WIKI_TOKEN` → 获取 `obj_token`
2. `/docx/v1/documents/{obj_token}/...` → docx API 直接读写
3. 前提：飞书页面「文档权限 → 可管理应用」添加该应用

创建新 wiki 节点需要 wiki 空间编辑权限（error 131006 = 无权限）：
- ⚠️ **tenant_access_token 创建节点需 wiki 空间管理员授予应用编辑权限**
- 首选：配置 `FEISHU_USER_ACCESS_TOKEN` / `FEISHU_USER_REFRESH_TOKEN`（user token 优先）
- `knowledge.py` 的 `_wiki_get` / `_wiki_post` 自动 user token 优先、tenant token 降级

### 4. Claude Code 子进程权限
运行环境是 root，`--dangerously-skip-permissions` 被禁止。
使用 `--permission-mode acceptEdits --output-format stream-json --verbose`。

### 5. Claude Code tmux 会话流程
```
bot._on_message()
  → session_manager.get(thread_id)？→ YES: relay_input → tmux send-keys
  → NO: invoke(agent) → trigger_self_iteration → TmuxClaudeSession.start_streaming()
      ① 写 prompt /tmp/ai-claude-*.prompt
      ② 写 wrapper script（含 unset ANTHROPIC_API_KEY）
      ③ tmux new-session -d -s ai-claude-{thread_id}
      ④ 后台线程 tail .jsonl → stream-json → IM

tmux session: ai-claude-{safe_thread_id}
直接查看:     tmux attach -t ai-claude-{safe_thread_id}
```

### 6. 火山云文本格式工具调用
火山云 Ark 有时以文本形式返回工具调用，格式 `<|FunctionCallBeginBegin|>[...]`。
`graph/nodes.py` 的 `_extract_text_tool_calls()` 负责解析转换为标准 LangChain tool_calls。

### 7. 重启必须激活 venv
⚠️ 直接 `python main.py` 会 crash（`ModuleNotFoundError: No module named 'dotenv'`）。
必须：`source .venv/bin/activate && python main.py`

### 8. 渐进式工具披露
`graph/nodes.py` 的 `agent_node` 按消息关键词动态注入工具分类。
新增工具时：在 `TOOL_CATEGORIES` 对应分类添加，在 `CATEGORY_KEYWORDS` 维护触发词。

### 9. 会议纪要 SQLite 去重
`data/meeting.db` 中 `meeting_docs` 表以 `doc_id` 为主键。
非会议文档标记为 `not_meeting`，避免每次都调用 LLM。

### 10. 飞书 wiki token 只能从实时 API 获取
历史对话中的 token 可能已失效。
- 正确方式：用户提供 URL → 从 URL 提取；需要找页面 → `feishu_wiki_page(list_children)`
- 绝对禁止：凭记忆/猜测 token、使用任何 placeholder 字符串、把 space_id 当 node token

---

## 关键配置（.env）

```
FEISHU_APP_ID=cli_a8fec6e8585d100d
FEISHU_WIKI_SPACE_ID=7618158120166034630
FEISHU_WIKI_CONTEXT_PAGE=FalZwGDOkiqpbQkeAjGc8jaznMd  # AI助理上下文快照页

VOLCENGINE_MODEL=ep-20260317143459-qtgqn
OPENROUTER_MODEL=anthropic/claude-sonnet-4-5
DINGTALK_DOCS_SPACE_ID=r9xmyYP7YK1w1mEO

# ANTHROPIC_API_KEY — 仅 Claude Code 界面内使用，不传给子进程（子进程用 OAuth session）
```

运行时可配置项（通过 `agent_config` 工具，无需重启）：
- `OWNER_FEISHU_CHAT_ID` — 心跳推送目标
- `FEISHU_WIKI_MEETING_PAGE` — 会议纪要汇总页 wiki token
- `DINGTALK_WIKI_API_PATH` — 自动探测写入，一般无需手动设置

---

## 启动 / 重启

```bash
cd /root/ai-assistant
source .venv/bin/activate   # ⚠️ 必须激活 venv

# 后台运行
nohup python main.py >> logs/app.log 2>&1 &

# 重启
kill $(cat logs/service.pid 2>/dev/null) 2>/dev/null
source .venv/bin/activate && nohup python main.py >> logs/app.log 2>&1 &

# 日志
tail -f logs/app.log
tail -f logs/crash.log | python -m json.tool
tail -f logs/llm.jsonl | python -m json.tool
tmux list-sessions | grep ai-claude
```

---

## 自迭代规则

1. **先读此文件**，理解现有架构再动手
2. **最小改动原则**：只改需求涉及的文件
3. **新增工具**：在 `graph/tools.py` 加 `@tool`，加入 `TOOL_CATEGORIES` 对应分类，更新 `CATEGORY_KEYWORDS`
4. **新增平台集成**：在 `integrations/` 新建子目录，在 `main.py` 注册启动线程
5. **Claude Code 子进程**：必须 `unset ANTHROPIC_API_KEY`，使用 `--permission-mode acceptEdits`
6. **完成后必做（缺一不可）**：
   - ① `git diff --stat` 确认修改文件
   - ② **更新 `CLAUDE.md`**：仅更新"当前运行状态"和坑点（不维护工具表和版本历史）
   - ③ **追加 `CHANGELOG.md`**：本次变更记录（唯一的版本历史，格式见现有条目）
   - ④ `README.md` 和 `docs/` 仅在功能大变化时更新，小迭代跳过
   - ⑤ **提交并推送**：`git add -A && git commit -m "类型: 描述 (vX.Y.Z)" && git push`
     - 类型：`feat` / `fix` / `docs` / `refactor`
     - **push 是强制步骤**

### 问题分类方法论

| 类别 | 判断标准 | 修复位置 |
|------|---------|---------|
| **代码问题** | API 调用失败、参数错误、Python 异常、超时 | `integrations/`、`graph/tools.py`、`graph/nodes.py` |
| **提示词/行为问题** | LLM 选错工具、参数填错、格式不符预期 | `prompts/system.md`、工具 docstring、`CATEGORY_KEYWORDS` |

---

## OpenClaw 参考

`larksuite-openclaw-lark-2026.3.15.tgz` — 飞书 API 工具和技能参考包（bitable/calendar/task/chat/drive/search）。
扩展飞书能力时从 tgz 提取对应模块并适配为 Python `@tool` 函数。
