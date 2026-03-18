# 部署配置指南

> 最后更新：2026-03-18（v0.7.4）

## 1. 环境准备

```bash
# Python 3.11+
python3 --version

# Node.js 20+（Claude Code CLI 依赖）
node --version   # 需要 >= 20

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 确认 Claude Code CLI
claude --version   # 应输出 2.x.x
```

## 2. 环境变量（.env）

```bash
cp .env.example .env
```

### 火山云 Ark（主力 LLM）

```
VOLCENGINE_API_KEY=ffbf3d3c-...
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
VOLCENGINE_MODEL=ep-20260317143459-qtgqn   # endpoint ID
```

> 获取 endpoint：火山方舟控制台 → 模型推理 → 我的推理接入点

### OpenRouter（备用 LLM）

```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=anthropic/claude-sonnet-4-5
```

### Anthropic（仅供 Claude Code CLI 自迭代）

```
ANTHROPIC_API_KEY=sk-ant-...
```

> **注意**：此 Key 不用于 Agent LLM，只在 `trigger_self_iteration` 工具调用 `claude` CLI 时传入

### 飞书（国内版）

```
FEISHU_APP_ID=cli_a8fec6e8585d100d
FEISHU_APP_SECRET=...
FEISHU_WIKI_SPACE_ID=         # 见下方获取方式 ⬇️
```

**获取 Wiki Space ID：**
```bash
python -m tools.list_feishu_spaces
# 输出示例：space_id=7xxxxxxxxx  name=我的知识库
```

**飞书控制台配置（必须）：**

1. [飞书开放平台](https://open.feishu.cn) → 你的应用
2. **添加应用能力** → 机器人（开启）
3. **权限管理** → 开通以下权限：
   - `im:message`
   - `im:message:send_as_bot`
   - `wiki:wiki`
   - `docx:document`
4. **事件订阅** → 订阅方式选「**长连接**」→ 添加事件 `im.message.receive_v1`
5. 创建版本并发布

> ⚠️ 事件订阅必须选「长连接」模式，否则消息收不到

### 钉钉（企业内部应用）

```
DINGTALK_CLIENT_ID=ding5nridvxbae9dvfh1
DINGTALK_CLIENT_SECRET=...
DINGTALK_AGENT_ID=4342092316
DINGTALK_DOCS_SPACE_ID=r9xmyYP7YK1w1mEO   # 已废弃，仅供 analyze_meeting_doc 内部兜底用

# MCP Server URLs（钉钉开放平台 → 文档 MCP / AI 表格 MCP）
DINGTALK_MCP_URL=https://mcp-gw.dingtalk.com/server/<your_doc_token>
DINGTALK_MCP_TABLE_URL=https://mcp-gw.dingtalk.com/server/<your_table_token>
```

> **MCP URL 获取**：钉钉开放平台 → 你的应用 → MCP Server → 复制 Streamable-HTTP 地址

**钉钉控制台配置：**

1. [钉钉开放平台](https://open.dingtalk.com) → 应用开发 → 你的应用
2. 机器人 → 消息接收模式 → 选择「**Stream 模式**」
3. 确认已开通消息发送权限

### 邮件（163 IMAP）

```
EMAIL_ADDRESS=xxx@163.com
EMAIL_AUTH_CODE=xxxxx   # 授权码，非登录密码
```

**163邮箱开启 IMAP：**
1. 打开 mail.163.com → 设置 → POP3/SMTP/IMAP
2. 开启「IMAP/SMTP 服务」
3. 生成授权码（注意：每次生成后旧码失效）

> ⚠️ 如收到 `Unsafe Login` 错误，说明授权码已失效或 IMAP 未开启

## 3. 启动服务

```bash
cd /root/ai-assistant
source .venv/bin/activate   # ⚠️ 必须激活 venv

# 前台运行（调试用）
python main.py

# 后台运行（推荐，所有输出合并到 app.log）
nohup python main.py >> logs/app.log 2>&1 &

# 重启（改代码后用 PID 文件 kill）
kill $(cat logs/service.pid 2>/dev/null) 2>/dev/null
source .venv/bin/activate
nohup python main.py >> logs/app.log 2>&1 &

# 查看实时日志
tail -f logs/app.log

# 查看崩溃记录
tail -f logs/crash.log | python -m json.tool
```

> v0.7.3 起已去除 FastAPI/uvicorn，服务不监听任何 TCP 端口。无需健康检查端点。

## 4. 验证连接

### 飞书验证

启动后日志应出现：
```
[INFO] integrations.feishu.bot: [飞书] 长连接启动中...
[INFO] connected to wss://msg-frontier.feishu.cn/ws/v2?...
```

然后从飞书向机器人发一条消息，日志应出现：
```
[INFO] integrations.feishu.bot: [飞书长连接] user=ou_xxx chat=oc_xxx msg=你好
[INFO] httpx: HTTP Request: POST https://ark.cn-beijing.volces.com/... "HTTP/1.1 200 OK"
```

### 钉钉验证

启动后日志应出现：
```
[INFO] integrations.dingtalk.bot: [钉钉] 流模式启动中...
[INFO] dingtalk_stream.client: endpoint is {'endpoint': 'wss://...'}
```

## 5. 常见问题

**Q: 飞书收不到消息**
→ 确认飞书控制台事件订阅已选「长连接」模式，并已添加 `im.message.receive_v1` 事件

**Q: `No module named 'langgraph.checkpoint.sqlite'`**
→ `pip install langgraph-checkpoint-sqlite`

**Q: `Invalid checkpointer` 错误**
→ 不要用 `SqliteSaver.from_conn_string()`，改用：
```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
conn = sqlite3.connect("data/memory.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)
```

**Q: 163 邮件 `Unsafe Login`**
→ 到 mail.163.com 重新生成 IMAP 授权码，更新 `.env EMAIL_AUTH_CODE`

**Q: 钉钉文档相关操作失败**
→ v0.7.4 起文档/表格操作通过 MCP 接入，确认 `DINGTALK_MCP_URL` 和 `DINGTALK_MCP_TABLE_URL` 已正确配置；启动日志中应有 `[tools] 钉钉 MCP 工具已注册: [...]`

**Q: 飞书 WS 断连后不响应消息**
→ v0.7.3 起 supervised thread 会在 5s 内自动重启；查看 `logs/crash.log` 确认重启记录
