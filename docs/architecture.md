# 系统架构说明

> 最后更新：2026-03-18（v0.7.3）

## 整体架构

```
                    ┌─────────────────────────────────────────────┐
                    │              外部输入                         │
                    │  飞书机器人消息  │  钉钉机器人消息  │  定时任务  │
                    └──────┬──────────────────┬──────────┬────────┘
                           │                  │          │
                    ┌──────▼──────────────────▼──────────▼────────┐
                    │         进程管理层（main.py）                  │
                    │                                              │
                    │  supervised thread × 2（指数退避自动重启）     │
                    │  ├── feishu-ws（lark-oapi ws.Client）        │
                    │  └── dingtalk-stream（dingtalk-stream SDK）  │
                    │  APScheduler（定时任务）                       │
                    │  SIGTERM/SIGINT 优雅关闭                      │
                    │  崩溃写 logs/crash.log（JSONL）               │
                    └──────────────────────┬──────────────────────┘
                                           │
                    ┌──────────────────────▼──────────────────────┐
                    │           LangGraph ReAct Agent              │
                    │                                              │
                    │   AgentState                                 │
                    │   ┌──────────────────────────────────────┐  │
                    │   │ messages / platform / user_id /      │  │
                    │   │ chat_id / intent / skill_result      │  │
                    │   └──────────────────────────────────────┘  │
                    │                                              │
                    │   节点流：agent_node → tools_node → …→ END  │
                    └──────┬──────────────────────┬──────────────┘
                           │                      │
              ┌────────────▼──────┐    ┌──────────▼────────────┐
              │    LLM 调用层      │    │      工具执行层（27个）  │
              │                   │    │                        │
              │  1. 火山云 Ark     │    │  飞书知识库 读/写       │
              │     (主力)         │    │  飞书 Bitable/任务/搜索 │
              │  2. OpenRouter     │    │  钉钉文档 读取          │
              │     (备用)         │    │  会议纪要 分析/写入      │
              │                   │    │  Claude Code 子 Agent  │
              │                   │    │  Shell/Python 执行      │
              │                   │    │  Web 搜索/抓取          │
              └───────────────────┘    └────────────────────────┘
                           │
              ┌────────────▼──────────────────────────────────────┐
              │                  持久化层                          │
              │                                                   │
              │  data/memory.db（LangGraph Checkpointer）         │
              │    ├── 对话历史（按 thread_id 隔离）                │
              │    └── 运行时配置（agent_config key-value）        │
              │  data/meeting.db（会议文档处理记录）                │
              │  飞书知识库（人类可读上下文镜像，每30分钟同步）       │
              └────────────────────────────────────────────────────┘
```

## 核心组件

### 1. 进程管理（`main.py`）

无 HTTP 层，纯 Python 进程管理：

```python
_supervised(name, target, base_delay=5, max_delay=300)
# → 循环运行 target()
# → 正常退出或崩溃后 sleep(delay)，delay = min(delay*2, 300)
# → 崩溃写 logs/crash.log（JSONL）
```

- **PID 文件**：`logs/service.pid`，方便外部 `kill $(cat logs/service.pid)`
- **优雅关闭**：SIGTERM/SIGINT → `sched.stop()` + `Event.set()`
- **无端口监听**：不绑定任何 TCP 端口，消除攻击面

### 2. LangGraph Agent（`graph/`）

使用 **ReAct**（Reasoning + Acting）模式：

```
用户消息
   ↓
[agent_node]  ── 渐进式工具注入（按关键词匹配分类）→ LLM 推理
   ↓
[should_continue]  ── 有 tool_calls → tools_node，否则 → END
   ↓
[tools_node]  ── 并行执行所有 tool calls，收集结果
   ↓
[agent_node]  ← 将工具结果作为上下文，继续推理（可多轮）
```

**持久化**：每个 `thread_id`（= `platform:chat_id`）独立保存对话历史到 SQLite，实现跨会话记忆。

### 3. 渐进式工具披露（`graph/nodes.py` + `graph/tools.py`）

全量 27 个工具的 schema 传给 LLM 会消耗大量 token。解决方案：

```
CORE_TOOLS（7个，每次必带）
  agent_config / web_search / web_fetch / python_execute
  run_command / get_system_status / get_service_status

TOOL_CATEGORIES（按关键词动态注入）
  feishu_wiki    → 关键词：飞书/wiki/知识库    → 5 个工具
  feishu_advanced→ 关键词：多维表格/任务/bitable→ 6 个工具
  meeting        → 关键词：会议/纪要/钉钉      → 4 个工具
  claude         → 关键词：迭代/开发/claude    → 5 个工具
```

无关键词时只传 7 个 → 节省约 87% token。

### 4. LLM 链（`graph/nodes.py`）

```python
火山云 Ark (ep-xxx)
    └─ with_fallbacks([OpenRouter])
         └─ bind_tools(tools)   # 按消息动态决定 tools 集合
```

每次调用后记录到 `logs/llm.jsonl`（model/latency/input_tokens/output_tokens/tool_calls）。

### 5. Claude Code 子 Agent（`integrations/claude_code/tmux_session.py`）

```
trigger_self_iteration(requirement)
       ↓
TmuxClaudeSession.start_streaming()
  ① 写 prompt → /tmp/ai-claude-*.prompt
  ② 写 wrapper script /tmp/ai-claude-*.sh
     （含 unset ANTHROPIC_API_KEY，使用 OAuth session）
  ③ tmux new-session -d -s ai-claude-{thread_id} {script}
  ④ 后台线程 tail .jsonl → 解析 stream-json → send_fn → IM 推送
       ↓
用户后续消息 → bot 检测活跃 Claude 会话 → relay_input() → tmux send-keys
```

⚠️ **关键**：必须 `unset ANTHROPIC_API_KEY`，否则 OAuth session 被 API Key 覆盖导致 401。

### 6. 会议纪要闭环（`integrations/meeting/`）

```
APScheduler（每30min）
  → poll_dingtalk_meetings()
    → DingTalkDocs.list_recent_files(limit=50)
    → tracker.is_processed(doc_id) → 已处理则跳过
    → docs.read_file_content(doc_id)
    → analyzer.analyze(content)    → 火山云 LLM → 结构化 JSON
    → analyzer.write_to_feishu()   → 追加到会议纪要汇总页
    → tracker.mark_processed(doc_id)
```

### 7. 定时任务（`scheduler.py`）

| 任务 | 频率 | 说明 |
|------|------|------|
| `poll_dingtalk_meetings` | 每30分钟 | 钉钉知识库 → LLM 分析 → 飞书写入 |
| `poll_email` | 每60分钟 | 163 IMAP → Claude Haiku 提取 → 飞书写入 |
| `sync_context` | 每30分钟 | SQLite checkpoints 快照 → 覆盖飞书上下文页面 |

## 飞书知识库权限绕过

`/wiki/v2/spaces` 系列 API 不支持 tenant_access_token。绕过方案：

```
GET /wiki/v2/spaces/get_node?token=WIKI_TOKEN
  → 返回 obj_token（tenant token 可用）
GET/POST /docx/v1/documents/{obj_token}/...
  → docx API 直接读写（tenant token 可用）
前提：飞书页面「文档权限 → 可管理应用」添加该应用
```

## 安全设计

- **无端口监听**：去除 HTTP 层，不暴露任何 TCP 端口
- **无 API Key 传递**：Claude Code 子进程 `unset ANTHROPIC_API_KEY`，使用 OAuth session
- **凭据管理**：所有 Key 通过 `.env` 注入，不硬编码，`.env` 在 `.gitignore` 中
- **个人私有服务器**：`run_command` 无白名单限制（root 用户，受控环境）

## 日志文件

| 文件 | 内容 |
|------|------|
| `logs/app.log` | 所有应用日志（INFO/ERROR） |
| `logs/llm.jsonl` | LLM 调用记录（JSONL，每次一行） |
| `logs/crash.log` | 线程崩溃记录（JSONL，time/thread/error/traceback） |
| `logs/service.pid` | 主进程 PID |
