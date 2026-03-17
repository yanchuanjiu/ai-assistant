# 集成平台说明

## 飞书（国内版）

**应用信息**
- App ID: `cli_a8fec6e8585d100d`
- 开放平台: https://open.feishu.cn/app

**已用 API**

| API | 用途 |
|-----|------|
| `POST /auth/v3/tenant_access_token/internal` | 获取 tenant_access_token |
| `POST /im/v1/messages` | 发送消息 |
| `GET /wiki/v2/spaces` | 列出知识库空间 |
| `GET /wiki/v2/spaces/{space_id}/nodes` | 列出知识库节点 |
| `POST /wiki/v2/spaces/{space_id}/nodes` | 创建知识库页面 |
| `GET /docx/v1/documents/{doc_token}/raw_content` | 读取文档内容 |
| `POST /docx/v1/documents/{doc_token}/blocks/batch_update` | 更新文档内容 |

**Webhook 路径**: `POST /feishu/webhook`

事件类型：`im.message.receive_v1`（仅处理文本消息）

**Token 刷新策略**：tenant_access_token 有效期 2小时，client.py 自动缓存并在到期前60秒刷新。

---

## 钉钉（企业内部应用）

**应用信息**
- Client ID (AppKey): `ding5nridvxbae9dvfh1`
- Agent ID: `4342092316`
- 文档空间 ID: `r9xmyYP7YK1w1mEO`（来自 https://alidocs.dingtalk.com/i/spaces/r9xmyYP7YK1w1mEO/overview）
- 开放平台: https://open.dingtalk.com

**已用 API**

| API | 用途 |
|-----|------|
| `POST /v1.0/oauth2/accessToken` | 获取 access_token |
| `POST /v1.0/robot/oToMessages/batchSend` | 发送单聊消息 |
| `GET /v1.0/doc/spaces/{spaceId}/files` | 列出文档空间文件 |
| `GET /v1.0/documents/{fileId}/content` | 读取文档内容 |

**Webhook 路径**: `POST /dingtalk/webhook`

**会议纪要获取**：会议结束约30分钟后，钉钉文档空间自动更新文字版录音总结。通过 `get_latest_meeting_docs` 工具拉取。

---

## 163 邮箱（IMAP）

**连接参数**
- 服务器: `imap.163.com:993`（SSL）
- 认证: 邮箱地址 + 授权码（非登录密码）

**工作流程**

```
163邮箱 ← 工作邮件转发（Outlook/Teams 会议邀请）
    ↓ 每5分钟 IMAP UNSEEN 查询
提取字段：subject / from / date / body（纯文本）
    ↓ claude-haiku 解析
is_meeting=true → 写飞书知识库 [会议] xxx
```

**注意**：163邮箱需手动开启 IMAP 服务，且每次生成授权码后原授权码失效。

---

## 火山云 Ark（主力 LLM）

- API 兼容 OpenAI 格式
- Base URL: `https://ark.cn-beijing.volces.com/api/v3`
- Endpoint: `ep-20260317143459-qtgqn`
- 控制台: https://console.volcengine.com/ark

**切换模型**：在火山方舟控制台新建推理接入点，将 endpoint ID 更新到 `.env VOLCENGINE_MODEL`。

---

## OpenRouter（备用 LLM）

- API 兼容 OpenAI 格式
- Base URL: `https://openrouter.ai/api/v1`
- 默认模型: `anthropic/claude-sonnet-4-5`
- 控制台: https://openrouter.ai/keys

**切换模型**：修改 `.env OPENROUTER_MODEL`，支持格式：`provider/model-name`

常用选项：
```
anthropic/claude-sonnet-4-5    # 强推理，适合复杂任务
openai/gpt-4o                  # 通用
google/gemini-2.0-flash        # 快速、低成本
```

---

## Claude Code CLI（自迭代）

- 版本: 2.1.77
- 路径: `/root/.local/bin/claude`
- 使用方式: `claude --dangerously-skip-permissions --print "<需求>"`
- 工作目录: `/root/ai-assistant`
- API Key: 通过 `ANTHROPIC_API_KEY` 环境变量传入

**自迭代触发条件**：用户明确表达开发需求，且 Agent 判断需要修改代码时自动触发。
