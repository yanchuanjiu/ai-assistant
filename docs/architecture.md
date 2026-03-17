# 系统架构说明

## 整体架构

```
                    ┌─────────────────────────────────────────────┐
                    │              外部输入                         │
                    │  飞书机器人消息  │  钉钉机器人消息  │  定时任务  │
                    └──────┬──────────────────┬──────────┬────────┘
                           │                  │          │
                    ┌──────▼──────────────────▼──────────▼────────┐
                    │              FastAPI 入口层                   │
                    │   /feishu/webhook   /dingtalk/webhook         │
                    │   /health                                     │
                    └──────────────────────┬──────────────────────┘
                                           │
                    ┌──────────────────────▼──────────────────────┐
                    │           LangGraph ReAct Agent              │
                    │                                             │
                    │   AgentState                                 │
                    │   ┌──────────────────────────────────────┐  │
                    │   │ messages / platform / user_id /      │  │
                    │   │ chat_id / intent / skill_result      │  │
                    │   └──────────────────────────────────────┘  │
                    │                                             │
                    │   节点流：agent → tools → agent → respond    │
                    └──────┬──────────────────────┬──────────────┘
                           │                      │
              ┌────────────▼──────┐    ┌──────────▼────────────┐
              │    LLM 调用层      │    │      工具执行层         │
              │                   │    │                        │
              │  1. 火山云 Ark     │    │  飞书知识库 读/写       │
              │     (主力)         │    │  钉钉文档 读取          │
              │  2. OpenRouter     │    │  Claude Code CLI       │
              │     (备用)         │    │  Shell 命令(白名单)     │
              │                   │    │  上下文同步             │
              └───────────────────┘    └────────────────────────┘
                           │
              ┌────────────▼──────────────────────────────────────┐
              │                  持久化层                          │
              │                                                   │
              │  SQLite (data/memory.db)       飞书知识库          │
              │  LangGraph Checkpointer     人类可读上下文镜像      │
              │  短期记忆：当前对话历史       定期同步（每30分钟）   │
              │  长期记忆：跨会话 thread                           │
              └────────────────────────────────────────────────────┘
```

## 核心组件

### 1. LangGraph Agent（`graph/`）

使用 **ReAct**（Reasoning + Acting）模式：

```
用户消息
   ↓
[agent_node]  ── LLM 推理，决定是否调用工具
   ↓
[should_continue]  ── 路由：有 tool_calls → tools，否则 → respond
   ↓
[tools_node]  ── 并行执行所有 tool calls，收集结果
   ↓
[agent_node]  ← 将工具结果作为上下文，继续推理（可多轮）
   ↓
[respond_node]  ── 最终回复，推送到飞书/钉钉
```

**持久化**：每个 `thread_id`（= `platform:chat_id`）独立保存对话历史到 SQLite，实现跨会话记忆。

### 2. LLM 链（`graph/nodes.py`）

```python
火山云 Ark (ep-xxx)
    └─ with_fallbacks([OpenRouter])
         └─ bind_tools(ALL_TOOLS)
```

- 主力：火山云 doubao-pro，低延迟、低成本
- 备用：OpenRouter，可路由到 Claude / GPT-4o / Gemini 等
- Claude API：**仅** 通过环境变量传给 `claude` CLI，不在 agent 链中使用

### 3. 工具层（`graph/tools.py`）

| 工具 | 描述 |
|------|------|
| `write_meeting_note` | 写会议纪要到飞书知识库 |
| `read_feishu_knowledge` | 检索飞书知识库 |
| `write_feishu_knowledge` | 写任意内容到飞书知识库 |
| `get_latest_meeting_docs` | 列出钉钉文档最新文件 |
| `read_meeting_doc` | 读取钉钉文档内容 |
| `trigger_self_iteration` | 启动 Claude Code 自迭代 |
| `sync_context_to_feishu` | 同步本地记忆到飞书 |
| `run_shell_command` | 执行白名单 Shell 命令 |

### 4. 自迭代流程（`trigger_self_iteration`）

```
用户 → "帮我加个XX功能"
  ↓
Agent 调用 trigger_self_iteration(requirement=...)
  ↓
subprocess: claude --dangerously-skip-permissions --print "<需求+上下文>"
  工作目录: /root/ai-assistant
  超时: 10分钟
  环境变量: ANTHROPIC_API_KEY 透传
  ↓
Claude Code 自动：读代码 → 修改文件 → 验证
  ↓
返回：修改了哪些文件 + 验证结果
  ↓
Agent 汇报给用户
```

### 5. 定时任务（`scheduler.py`）

| 任务 | 频率 | 说明 |
|------|------|------|
| `poll_email` | 每5分钟 | 拉取163邮箱未读邮件，提取会议信息写飞书 |
| `sync_context` | 每30分钟 | SQLite 记忆快照写入飞书知识库 |

## 数据流：会议信息处理

```
工作邮件转发至 163邮箱
    ↓ (每5分钟)
IMAPPoller.fetch_unread()
    ↓
extract_meeting_info(email)   ← claude-haiku 解析
    ↓ is_meeting=true
FeishuKnowledge.create_or_update_page(
    title="[会议] xxx",
    content=Markdown格式纪要
)
    ↓
飞书知识库页面（人类可读）
```

## 记忆架构

```
短期记忆：LangGraph message history
  - 按 thread_id (platform:chat_id) 隔离
  - SQLite checkpoints 持久化
  - 自动附加到每次 LLM 调用

长期记忆：飞书知识库（人类可读）
  - 每30分钟同步一次
  - 包含：对话线程列表、会议纪要、项目上下文
  - 支持手动查阅和编辑
```

## 安全设计

- **Shell 白名单**：只允许 `git/ls/cat/pwd/echo/python/pip/df/du/ps/which/find` 前缀
- **Claude Code 隔离**：工作目录限定在 `/root/ai-assistant`，通过子进程调用
- **凭据管理**：所有 Key 通过 `.env` 注入，不硬编码，`.env` 在 `.gitignore` 中
- **Webhook 验证**：飞书使用 Verification Token 验证请求来源
