# AI 个人助理

> 运行在私有 Linux 服务器上的个人 AI 助理。通过飞书/钉钉机器人对话交互，自动处理会议纪要、管理飞书知识库，并支持通过自然语言驱动 Claude Code 完成自迭代开发。

## 功能概览

| 模块 | 功能 |
|------|------|
| 飞书机器人 | 接收消息、调用 Agent、回复结果 |
| 钉钉机器人 | 同上，支持企业内部应用接入 |
| 会议处理 | 163 邮箱轮询 → LLM 提取会议信息 → 写入飞书知识库 |
| 钉钉文档 | 读取钉钉文档空间的会议纪要（含文字版录音总结） |
| 项目管理 | 通过对话读写飞书知识库，维护项目上下文 |
| 自迭代开发 | Agent 向本机 Claude Code CLI 下发需求，自动完成开发并回收结果 |
| 上下文同步 | 本地 SQLite 记忆 ↔ 飞书知识库定期双向同步 |
| 本机操作 | 白名单内执行 git/ls/python 等 shell 命令 |

## 系统架构

```
飞书 Webhook ──┐
               ├──► FastAPI ──► LangGraph Agent ──► 工具层
钉钉 Webhook ──┘                    │
                              SQLite 记忆          │
                           (LangGraph Checkpointer) │
                                                    ├── 飞书知识库 (读/写)
APScheduler ──► 邮件轮询                            ├── 钉钉文档 (读)
             └► 上下文同步                          ├── Claude Code CLI (自迭代)
                                                    └── Shell 命令 (白名单)

LLM 链：火山云 Ark ──(失败)──► OpenRouter (Claude/GPT-4o)
Claude API：仅供 Claude Code CLI 使用
```

## 快速开始

### 环境要求

- Python 3.11+
- Claude Code CLI（已安装：`claude --version`）
- 可访问公网的 Linux 服务器（用于飞书/钉钉 Webhook 回调）

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
# 按照 docs/setup.md 逐项填写 .env
```

### 获取飞书知识库 Space ID

```bash
python -m tools.list_feishu_spaces
# 将输出的 space_id 填入 .env: FEISHU_WIKI_SPACE_ID=
```

### 启动

```bash
python main.py
# 服务默认监听 0.0.0.0:8000
# 健康检查：curl http://localhost:8000/health
```

## 配置说明

详见 [docs/setup.md](docs/setup.md)，关键配置项：

| 变量 | 说明 |
|------|------|
| `VOLCENGINE_MODEL` | 火山云 endpoint ID（`ep-xxx`）或模型名 |
| `OPENROUTER_MODEL` | 复杂任务备用模型，默认 `anthropic/claude-sonnet-4-5` |
| `FEISHU_WIKI_SPACE_ID` | 知识库空间 ID，运行 `list_feishu_spaces` 获取 |
| `FEISHU_VERIFICATION_TOKEN` | 飞书事件订阅验证 Token |
| `ANTHROPIC_API_KEY` | 仅供 Claude Code CLI 使用 |

## 项目结构

```
ai-assistant/
├── main.py                  # FastAPI 启动入口
├── scheduler.py             # 定时任务（邮件轮询 / 上下文同步）
├── requirements.txt
├── .env.example             # 配置模板
├── CLAUDE.md                # Claude Code 项目上下文（自迭代用）
│
├── graph/                   # LangGraph Agent
│   ├── agent.py             # 图定义 + SQLite checkpointer
│   ├── nodes.py             # 节点（LLM调用 / 工具执行 / 消息回复）
│   ├── state.py             # AgentState 定义
│   └── tools.py             # 工具函数注册
│
├── integrations/
│   ├── feishu/              # 飞书：机器人 Webhook + 知识库
│   ├── dingtalk/            # 钉钉：机器人 + 文档空间
│   ├── email/               # 163 IMAP 轮询 + 会议信息提取
│   └── storage/             # 文件存储抽象（LocalStorage / 待接 OSS）
│
├── sync/                    # SQLite ↔ 飞书知识库同步
├── prompts/                 # System prompt + 会议提取 prompt
├── tools/                   # 运维辅助脚本
└── docs/                    # 详细文档
    ├── setup.md             # 部署配置指南
    ├── architecture.md      # 架构设计说明
    ├── integrations.md      # 各平台集成说明
    └── development.md       # 开发指南
```

## 自迭代开发

向机器人发消息即可触发开发迭代，例如：

> "帮我新增一个工具，每天早上9点自动从钉钉文档拉取昨天的会议纪要汇总发给我"

Agent 会调用 `trigger_self_iteration` 工具，启动本机 `claude --dangerously-skip-permissions`，自动完成代码修改后汇报结果。

详见 [docs/development.md](docs/development.md)。

## Roadmap

- [ ] 火山云 OSS 文件存储接入
- [ ] 飞书知识库向量检索（语义搜索）
- [ ] 钉钉机器人双向对话完整支持
- [ ] 定时任务 Web 管理界面
- [ ] 多用户权限隔离

## 许可

个人非商用项目，MIT License。
