# AI 个人助理

> 运行在私有 Linux 服务器上的个人 AI 助理。通过飞书/钉钉机器人对话交互（长连接，无需公网），自动处理会议纪要、读写飞书知识库，并支持通过自然语言驱动 Claude Code 完成自迭代开发。

## 当前状态（v0.5.0）

| 组件 | 状态 | 说明 |
|------|------|------|
| 飞书机器人（长连接） | ✅ 运行中 | 收发消息正常，火山云 LLM 响应 |
| 钉钉机器人（流模式） | ✅ 连接中 | Stream 连接已建立 |
| 火山云 Ark LLM | ✅ 正常 | `ep-20260317143459-qtgqn` |
| OpenRouter fallback | ✅ 就绪 | 火山云失败时自动切换 |
| SQLite 记忆 | ✅ 正常 | `data/memory.db`，LangGraph checkpointer |
| APScheduler 定时任务 | ✅ 运行中 | 邮件轮询60分钟/同步30分钟 |
| 飞书知识库 | ✅ 正常 | 读写均可，docx API via `get_node` |
| Claude Code 流式迭代 | ✅ 正常 | 异步执行，进度实时推送 IM，用户可交互 |
| 无限制 CLI | ✅ 正常 | `run_command`，个人服务器无白名单 |
| 钉钉文档读取 | ⚠️ 待修复 | API 路径需确认 |
| 163 IMAP 邮件 | ⚠️ 待配置 | 需在 163 开启 IMAP 并更新授权码 |

## 功能概览

| 模块 | 功能 |
|------|------|
| 飞书机器人 | 长连接收消息 → Agent 推理 → 回复，无需公网 IP |
| 钉钉机器人 | 流模式收消息 → Agent 推理 → 回复，无需公网 IP |
| 飞书知识库 | 读取/追加/覆盖任意 wiki 页面，搜索关键词 |
| 上下文同步 | 本地 SQLite 记忆定期推送至飞书知识库页面 |
| 会议处理 | 163邮箱轮询 → LLM 提取会议信息 → 写入飞书知识库 |
| 钉钉文档 | 读取钉钉文档空间的会议纪要 |
| 自迭代开发 | Agent 向本机 Claude Code CLI 下发需求，流式进度推送到 IM，支持 IM 消息实时交互 |
| 本机操作 | 执行任意 shell 命令（`run_command`，无白名单） |

## 系统架构

```
飞书（长连接 WS）──┐
                   ├──► LangGraph ReAct Agent ──► 工具层
钉钉（流模式 WS）──┘         │
                        SQLite 记忆            │
                    (LangGraph Checkpointer)   ├── 飞书知识库（读/追加/覆盖/搜索）
                                              ├── 钉钉文档
APScheduler ──► 邮件轮询60min                  ├── Claude Code CLI（自迭代，流式推送）
             └► 上下文同步30min ─────────────► └── Shell 命令（无限制）

LLM 链：火山云 Ark ──(失败)──► OpenRouter (anthropic/claude-sonnet-4-5)
Claude API：仅供 Claude Code CLI 自身使用（OAuth session token）
```

### Claude Code 流式迭代架构

```
用户发消息给 IM
  ↓
bot._on_message()
  → 注册 reply_fn_registry[thread_id] = bot.send_text
  → 检查是否有活跃 Claude 会话 → 有则 relay_input(stdin) 并返回
  → 否则 invoke(agent)
      → tools_node: set_tool_ctx(thread_id, send_fn)
          → trigger_self_iteration: 读取 get_tool_ctx()
              → session_manager.start(thread_id, requirement, send_fn)
                  → ClaudeCodeSession.start_streaming()
                      → 后台线程解析 stream-json → send_fn → IM 推送
```

## 飞书知识库权限说明

飞书 Wiki Space API 不支持 `tenant_access_token`（需要用户 OAuth），但**单个文档的 docx API 可以通过 tenant token 直接读写**，只需：

1. 在飞书页面的「文档权限 → 可管理应用」里添加该应用
2. 通过 `GET /wiki/v2/spaces/get_node?token=WIKI_TOKEN` 将 wiki token 转为 `obj_token`
3. 用 docx API 对 `obj_token` 进行读写

配置：在 `.env` 中填写 `FEISHU_WIKI_CONTEXT_PAGE`（wiki URL 末尾的 token）。

## 快速启动

### 环境要求

- Python 3.11+
- Node.js 20+（用于 Claude Code CLI）
- Claude Code CLI（`claude --version` 确认已安装，已登录 OAuth session）

### 安装

```bash
git clone https://github.com/yanchuanjiu/ai-assistant.git
cd ai-assistant

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
# 按照 docs/setup.md 填写各项配置
```

**飞书知识库关键配置：**

```bash
FEISHU_WIKI_SPACE_ID=7618158120166034630
FEISHU_WIKI_CONTEXT_PAGE=FalZwGDOkiqpbQkeAjGc8jaznMd  # AI助理上下文快照页
```

### 启动

```bash
source .venv/bin/activate
python main.py

# 后台运行
nohup python main.py > logs/app.log 2>&1 &

# 健康检查
curl http://localhost:8000/health

# 重启（改完代码后）
kill $(lsof -ti:8000) 2>/dev/null; python main.py &
```

## 项目结构

```
ai-assistant/
├── main.py                  # FastAPI 入口 + 启动两个平台连接器
├── scheduler.py             # 定时任务（邮件轮询60min / 上下文同步30min）
├── requirements.txt
├── .env                     # 凭据（私有仓库，不公开）
├── .env.example             # 配置模板
├── CLAUDE.md                # Claude Code 自迭代上下文（首要参考）
├── CHANGELOG.md             # 版本迭代记录
│
├── graph/                   # LangGraph Agent
│   ├── agent.py             # 图定义 + SQLite checkpointer
│   ├── nodes.py             # 节点（LLM调用 / 工具执行 + tool context 注入）
│   ├── state.py             # AgentState 定义
│   └── tools.py             # 工具函数注册（9个工具）
│
├── integrations/
│   ├── feishu/              # 飞书：长连接机器人 + 知识库读写
│   │   ├── bot.py           # 长连接消息处理 + reply_fn 注册 + 会话拦截
│   │   ├── client.py        # tenant_access_token + HTTP 封装
│   │   └── knowledge.py     # wiki 读写（docx API via get_node）
│   ├── dingtalk/            # 钉钉：流模式机器人 + 文档空间
│   │   ├── bot.py           # 流模式消息处理 + 会话拦截
│   │   ├── client.py        # DingTalk OAuth token
│   │   └── docs.py          # 文档空间读取（API 路径待修复）
│   ├── claude_code/         # Claude Code 会话管理
│   │   └── session.py       # ClaudeCodeSession + SessionManager + reply_fn_registry
│   ├── email/               # 163 IMAP 轮询 + 会议信息提取
│   └── storage/             # 文件存储抽象（LocalStorage / 待接 OSS）
│
├── sync/                    # SQLite ↔ 飞书知识库同步
├── prompts/                 # System prompt + 会议提取 prompt
├── tools/                   # 运维辅助脚本
├── logs/                    # 运行日志（gitignored）
└── docs/                    # 详细文档
    ├── setup.md             # 部署配置指南
    ├── architecture.md      # 架构设计说明
    ├── integrations.md      # 各平台集成说明
    └── development.md       # 开发指南
```

## Agent 工具列表（9个）

| 工具 | 描述 |
|------|------|
| `feishu_read_page` | 读取飞书 wiki 页面内容（传 URL 或 token） |
| `feishu_append_to_page` | 向飞书页面末尾追加内容 |
| `feishu_overwrite_page` | 清空并覆盖写入飞书页面 |
| `feishu_search_wiki` | 在上下文页面中搜索关键词 |
| `sync_context_to_feishu` | 将本地 SQLite 记忆同步至飞书 |
| `get_latest_meeting_docs` | 获取最新钉钉会议纪要列表 |
| `read_meeting_doc` | 读取钉钉文档完整内容 |
| `trigger_self_iteration` | 触发 Claude Code 异步迭代，进度实时推送 IM，支持 IM 交互 |
| `run_command` | 执行任意 Shell 命令（无白名单，个人服务器） |

## LLM 策略

```
用户消息 → 火山云 Ark（ep-20260317143459-qtgqn）
                ↓ 失败/超时（30s）
           OpenRouter（anthropic/claude-sonnet-4-5）

Claude Code CLI → 独立使用 OAuth session token（不依赖 ANTHROPIC_API_KEY）
```

## 自迭代开发

向飞书/钉钉机器人发消息即可触发开发：

> "帮我新增一个工具，每天早上9点自动从钉钉拉取昨天的会议纪要发给我"

Agent 调用 `trigger_self_iteration`，在本机启动 Claude Code（`--permission-mode acceptEdits`），执行进度实时推送到 IM。在 Claude 运行期间，用户发送的消息会被转发给 Claude stdin，实现移动端远程交互。

**重要**：Claude Code 子进程必须排除 `ANTHROPIC_API_KEY`，否则会覆盖 OAuth session 导致 401 认证失败。

## 待完成事项

- [ ] 修复钉钉文档 API 路径（`/v1.0/doc/spaces` 404 待查）
- [ ] 163 邮箱重新开启 IMAP 并更新授权码（`.env EMAIL_AUTH_CODE`）
- [ ] 火山云 OSS 文件存储接入
- [ ] 飞书知识库语义搜索（当前为关键词匹配）

## 文档

- [部署配置指南](docs/setup.md)
- [架构设计说明](docs/architecture.md)
- [开发指南](docs/development.md)
- [集成平台说明](docs/integrations.md)
- [版本记录](CHANGELOG.md)
- [自迭代上下文](CLAUDE.md)

## License

个人非商用，MIT License。
