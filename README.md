# AI 个人助理

> 运行在私有 Linux 服务器上的个人 AI 助理。通过飞书机器人对话交互（长连接，无需公网），自动处理会议纪要、管理飞书知识库，并支持通过自然语言驱动 Claude Code 完成自迭代开发。

## 当前状态

| 组件 | 状态 | 说明 |
|------|------|------|
| 飞书机器人（长连接） | ✅ 运行中 | 收发消息正常，火山云 LLM 响应 |
| 钉钉机器人（流模式） | ✅ 连接中 | Stream 连接已建立 |
| 火山云 Ark LLM | ✅ 正常 | `ep-20260317143459-qtgqn` |
| OpenRouter fallback | ✅ 就绪 | 火山云失败时自动切换 |
| SQLite 记忆 | ✅ 正常 | `data/memory.db` |
| APScheduler 定时任务 | ✅ 运行中 | 邮件轮询5分钟/同步30分钟 |
| 飞书知识库 | ⚠️ 待配置 | `FEISHU_WIKI_SPACE_ID` 未填 |
| 钉钉文档读取 | ⚠️ 待修复 | API 路径需确认 |
| 163 IMAP 邮件 | ⚠️ 待修复 | 需在邮箱重新开启 IMAP |

## 功能概览

| 模块 | 功能 |
|------|------|
| 飞书机器人 | 长连接收消息 → Agent 推理 → 回复，无需公网 IP |
| 钉钉机器人 | 流模式收消息 → Agent 推理 → 回复，无需公网 IP |
| 会议处理 | 163邮箱轮询 → LLM 提取会议信息 → 写入飞书知识库 |
| 钉钉文档 | 读取钉钉文档空间的会议纪要（含文字版录音总结） |
| 项目管理 | 对话式读写飞书知识库，维护项目上下文 |
| 自迭代开发 | Agent 向本机 Claude Code CLI 下发需求，自动完成开发并回收结果 |
| 上下文同步 | 本地 SQLite 记忆 ↔ 飞书知识库定期同步 |
| 本机操作 | 白名单内执行 git/ls/python 等 shell 命令 |

## 系统架构

```
飞书（长连接 WS）──┐
                   ├──► LangGraph ReAct Agent ──► 工具层
钉钉（流模式 WS）──┘         │
                        SQLite 记忆            │
                    (LangGraph Checkpointer)   ├── 飞书知识库
                                              ├── 钉钉文档
APScheduler ──► 邮件轮询                       ├── Claude Code CLI（自迭代）
             └► 上下文同步                     └── Shell 命令（白名单）

LLM 链：火山云 Ark ──(失败)──► OpenRouter (Claude/GPT-4o)
Claude API：仅供 Claude Code CLI，不作为 agent LLM
```

## 快速启动

### 环境要求

- Python 3.11+
- Node.js 20+（用于 Claude Code CLI）
- Claude Code CLI（`claude --version` 确认已安装）

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

**最关键的几项：**

```bash
# 获取飞书 Wiki Space ID
python -m tools.list_feishu_spaces

# 填入 .env
FEISHU_WIKI_SPACE_ID=xxxxx
```

### 启动

```bash
source .venv/bin/activate
python main.py

# 后台运行
nohup python main.py > logs/app.log 2>&1 &

# 健康检查
curl http://localhost:8000/health
```

## 项目结构

```
ai-assistant/
├── main.py                  # FastAPI 入口 + 启动两个平台连接器
├── scheduler.py             # 定时任务（邮件轮询 / 上下文同步）
├── requirements.txt
├── .env.example             # 配置模板（勿将 .env 提交）
├── CLAUDE.md                # Claude Code 自迭代上下文
├── CHANGELOG.md             # 版本迭代记录
│
├── graph/                   # LangGraph Agent
│   ├── agent.py             # 图定义 + SQLite checkpointer
│   ├── nodes.py             # 节点（LLM调用 / 工具执行）
│   ├── state.py             # AgentState 定义
│   └── tools.py             # 工具函数注册（8个工具）
│
├── integrations/
│   ├── feishu/              # 飞书：长连接机器人 + 知识库
│   ├── dingtalk/            # 钉钉：流模式机器人 + 文档空间
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

## LLM 策略

```
用户消息 → 火山云 Ark（ep-20260317143459-qtgqn）
                ↓ 失败/超时（30s）
           OpenRouter（anthropic/claude-sonnet-4-5）

Claude API → 仅 claude CLI 自迭代，env: ANTHROPIC_API_KEY
```

## 自迭代开发

向飞书/钉钉机器人发消息即可触发开发：

> "帮我新增一个工具，每天早上9点自动从钉钉拉取昨天的会议纪要发给我"

Agent 调用 `trigger_self_iteration`，在本机启动 `claude --dangerously-skip-permissions`，自动完成代码修改后汇报结果。

## 待完成事项

- [ ] 配置 `FEISHU_WIKI_SPACE_ID`（运行 `python -m tools.list_feishu_spaces`）
- [ ] 修复钉钉文档 API 路径（`/v1.0/doc/spaces` 404 待查）
- [ ] 163 邮箱重新开启 IMAP 并更新授权码
- [ ] 火山云 OSS 文件存储接入
- [ ] 飞书知识库语义搜索

## 文档

- [部署配置指南](docs/setup.md)
- [架构设计说明](docs/architecture.md)
- [开发指南](docs/development.md)
- [集成平台说明](docs/integrations.md)
- [版本记录](CHANGELOG.md)

## License

个人非商用，MIT License。
