# 集成平台说明

## 飞书（国内版）

**应用信息**
- App ID: `cli_a8fec6e8585d100d`
- 开放平台: https://open.feishu.cn/app

**已用 API**

| API | 用途 | Token 类型 |
|-----|------|-----------|
| `POST /auth/v3/tenant_access_token/internal` | 获取 tenant_access_token | — |
| `POST /im/v1/messages` | 发送消息 | tenant |
| `GET /wiki/v2/spaces/get_node` | wiki token → obj_token | tenant |
| `GET /wiki/v2/spaces/{id}/nodes` | 列出子页面 | tenant |
| `POST /docx/v1/documents` | 创建裸文档（子页面创建第一步） | tenant |
| `POST /wiki/v2/spaces/{id}/nodes/move_docs_to_wiki` | 移入知识库（子页面创建第二步） | tenant |
| `GET /wiki/v2/tasks/{task_id}` | 轮询移动任务状态 | tenant |
| `GET /docx/v1/documents/{obj_token}/raw_content` | 读取文档内容 | tenant |
| `POST /docx/v1/documents/{obj_token}/blocks/{id}/children` | 追加文档内容块 | tenant |
| `POST /docx/v1/documents/{obj_token}/blocks/batch_update` | 更新文档内容 | tenant |

> ⚠️ `POST /wiki/v2/spaces/{id}/nodes`（直接创建 wiki 节点）不支持 tenant token，只能用 user OAuth。子页面创建须走 "create docx → move" 两步。

**连接方式**: 长连接（lark-oapi ws.Client），无需公网 Webhook

事件类型：`im.message.receive_v1`（仅处理文本消息）

**Token 刷新策略**：tenant_access_token 有效期 2小时，client.py 自动缓存并在到期前60秒刷新。

---

## 钉钉（企业内部应用）

**应用信息**
- Client ID (AppKey): `ding5nridvxbae9dvfh1`
- Agent ID: `4342092316`
- 文档空间 ID: `r9xmyYP7YK1w1mEO`（来自 https://alidocs.dingtalk.com/i/spaces/r9xmyYP7YK1w1mEO/overview）
- 开放平台: https://open.dingtalk.com

**已用 API（机器人消息）**

| API | 用途 |
|-----|------|
| `POST /v1.0/oauth2/accessToken` | 获取 access_token |
| `POST /v1.0/robot/oToMessages/batchSend` | 发送单聊消息 |
| `GET /v2.0/users/me` | 获取当前用户 unionid |

**MCP 方式访问钉钉文档 / AI 表格**

v0.7.4 起，文档和表格操作通过 **Streamable-HTTP MCP Server** 接入，不再直接调用 REST API：

| 配置项 | 说明 |
|--------|------|
| `DINGTALK_MCP_URL` | 钉钉文档 MCP Server URL（来自钉钉开放平台 MCP 配置） |
| `DINGTALK_MCP_TABLE_URL` | 钉钉 AI 表格 MCP Server URL |

**文档 MCP 工具（12个）**：
- 搜索：`search_documents` / `list_nodes`
- 读取：`get_document_content` / `get_document_info`
- 创建/编辑：`create_document` / `update_document` / `create_folder`
- 块操作：`list_document_blocks` / `insert_document_block` / `update_document_block` / `delete_document_block` / `get_document_block`

**AI 表格 MCP 工具（21个）**：
- Base：`list_bases` / `search_bases` / `create_base` / `delete_base`
- Table/Field：`get_tables` / `create_table` / `create_fields` / `get_fields`
- Record CRUD：`create_records` / `query_records` / `update_records` / `delete_records`
- 其他：`export_data` 等

**会议纪要获取**：会议结束约30分钟后，钉钉文档空间自动更新录音总结。通过 MCP `search_documents` 搜索后，用 `get_document_content` 读取内容。

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

- 路径: `/root/.local/bin/claude`
- 使用方式: `claude --permission-mode acceptEdits --output-format stream-json --verbose`
- 工作目录: `/root/ai-assistant`
- 凭据: OAuth session token（**必须 `unset ANTHROPIC_API_KEY`**，否则 API Key 覆盖 OAuth 导致 401）

**自迭代触发条件**：用户明确表达开发需求，且 Agent 判断需要修改代码时，调用 `trigger_self_iteration` 启动 tmux 会话，stream-json 实时推送到 IM。
