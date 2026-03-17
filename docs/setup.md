# 部署配置指南

## 1. 环境准备

```bash
# Python 3.11+
python3 --version

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 确认 Claude Code CLI
claude --version   # 应输出 2.x.x
```

## 2. 环境变量（.env）

复制模板：
```bash
cp .env.example .env
```

逐项说明：

### 火山云 Ark（主力 LLM）

```
VOLCENGINE_API_KEY=ffbf3d3c-...      # 火山方舟 API Key
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
VOLCENGINE_MODEL=ep-20260317143459-qtgqn   # 模型接入点 ID
```

获取 endpoint ID：
> 火山方舟控制台 → 模型推理 → 我的推理接入点 → 复制接入点 ID

### OpenRouter（备用 LLM）

```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=anthropic/claude-sonnet-4-5
```

可选模型：`openai/gpt-4o`、`anthropic/claude-opus-4`、`google/gemini-pro` 等。

### Anthropic Claude API（仅供 Claude Code CLI）

```
ANTHROPIC_API_KEY=sk-ant-...
```

> **重要**：此 Key 不用于 Agent LLM，仅在 `trigger_self_iteration` 工具调用 `claude` CLI 时通过环境变量传递。

### 飞书

```
FEISHU_APP_ID=cli_...
FEISHU_APP_SECRET=...
FEISHU_VERIFICATION_TOKEN=...     # 见下方「飞书配置」
FEISHU_WIKI_SPACE_ID=...          # 见下方获取方式
```

获取 Wiki Space ID：
```bash
python -m tools.list_feishu_spaces
```

### 钉钉

```
DINGTALK_CLIENT_ID=ding...        # AppKey
DINGTALK_CLIENT_SECRET=...        # AppSecret
DINGTALK_AGENT_ID=...             # 企业内部应用 AgentId
DINGTALK_DOCS_SPACE_ID=...        # 文档空间 ID（URL 中的路径段）
```

### 邮件（163 IMAP）

```
EMAIL_ADDRESS=xxx@163.com
EMAIL_AUTH_CODE=...               # 163邮箱授权码（非登录密码）
```

获取授权码：163邮箱网页版 → 设置 → POP3/SMTP/IMAP → 开启 IMAP → 生成授权码

---

## 3. 飞书开放平台配置

### 3.1 开通权限

进入飞书开放平台 → 你的应用 → 权限管理，开通：

| 权限 | 用途 |
|------|------|
| `im:message` | 接收和发送消息 |
| `im:message:send_as_bot` | 机器人发消息 |
| `wiki:wiki` | 知识库读写 |
| `docx:document` | 文档读写 |
| `drive:drive` | 云盘访问 |

### 3.2 配置事件订阅

飞书开放平台 → 事件订阅 → 请求网址：

```
http://<你的服务器公网IP>:8000/feishu/webhook
```

订阅事件：`im.message.receive_v1`（接收消息）

配置完成后，将页面上的 **Verification Token** 填入 `.env`：
```
FEISHU_VERIFICATION_TOKEN=xxx
```

### 3.3 发布应用

权限和事件配置完后，点击「创建版本」→「申请发布」。

---

## 4. 钉钉开放平台配置

### 4.1 机器人消息接收

钉钉开放平台 → 你的应用 → 机器人 → 消息接收地址：

```
http://<你的服务器公网IP>:8000/dingtalk/webhook
```

### 4.2 确认权限

确保应用有「发送消息」和「通讯录」相关权限。

---

## 5. 启动服务

```bash
cd /root/ai-assistant
source .venv/bin/activate
python main.py
```

后台运行（推荐用 systemd 或 screen）：

```bash
# screen 方式
screen -S ai-assistant
python main.py
# Ctrl+A D 挂起

# 或 nohup 方式
nohup python main.py > logs/app.log 2>&1 &
```

健康检查：
```bash
curl http://localhost:8000/health
# 返回 {"status":"ok"}
```

---

## 6. 常见问题

**Q: 飞书 Webhook 验证失败**
检查 `FEISHU_VERIFICATION_TOKEN` 是否正确，服务器 8000 端口是否对外开放。

**Q: 火山云调用失败自动切到 OpenRouter**
正常，这是 fallback 机制。检查火山云 endpoint 是否已部署、配额是否充足。

**Q: 邮件轮询没有触发**
163邮箱需要手动开启 IMAP 服务，并使用授权码（非账号密码）。

**Q: Claude Code 自迭代没有反应**
确认 `claude --version` 可以正常执行，且 `ANTHROPIC_API_KEY` 已配置。
