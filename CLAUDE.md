# AI 个人助理 - Claude Code 项目上下文

## 项目定位
个人非商用 AI 助理，运行在 Linux 云服务器，通过飞书/钉钉机器人交互。
无稳定性、性能要求。优先可用性和可迭代性。

## 技术栈
- **主力模型**: 火山云 Ark（doubao-pro，OpenAI-compatible API）
- **备用模型**: OpenRouter（`anthropic/claude-sonnet-4-5`，火山云失败时自动切换）
- **Claude API**: 仅供本机 Claude Code CLI 自迭代使用，不作为 agent LLM
- **核心框架**: LangGraph + LangChain（with_fallbacks 自动降级）
- **Web 框架**: FastAPI + uvicorn
- **记忆持久化**: LangGraph SQLiteCheckpointer (`data/memory.db`)
- **定时任务**: APScheduler
- **飞书集成**: 国内版飞书开放平台 API
- **钉钉集成**: 钉钉企业内部应用 API
- **邮件**: 163 IMAP 轮询

## 项目结构
```
graph/          LangGraph Agent 图（state/agent/nodes/tools）
integrations/   第三方平台集成（feishu/dingtalk/email/storage）
sync/           SQLite ↔ 飞书知识库双向同步
prompts/        System prompt 和提取 prompt
tools/          辅助运维脚本
data/           运行时数据（memory.db，gitignored）
```

## 启动方式
```bash
cd /root/ai-assistant
pip install -r requirements.txt
python main.py
```

## 关键配置（.env）
- `FEISHU_WIKI_SPACE_ID`: 运行 `python -m tools.list_feishu_spaces` 获取
- `FEISHU_VERIFICATION_TOKEN`: 在飞书开放平台事件订阅页面获取
- `ANTHROPIC_API_KEY`: 已配置

## 自迭代规则
1. 通过飞书/钉钉向机器人描述新需求
2. Agent 调用 `trigger_self_iteration` 工具，将需求传给 `claude` CLI
3. Claude Code 在 `/root/ai-assistant` 目录下执行修改
4. 修改完成后 agent 汇报结果

## 当前 MVP 范围
- [x] 飞书机器人 Webhook 收发
- [x] 钉钉企业内部机器人收发
- [x] LangGraph ReAct Agent + SQLite 记忆
- [x] 163 IMAP 邮件轮询 + 会议信息提取
- [x] 飞书知识库读写
- [x] 钉钉文档空间读取（会议纪要）
- [x] SQLite ↔ 飞书知识库定期同步
- [x] Claude Code 自迭代触发
- [ ] 火山云 OSS（待接入）
- [ ] 飞书知识库搜索优化（待接入向量检索）

## 待完成的配置步骤
1. 飞书开放平台 → 事件订阅 → 填写 Webhook URL + 获取 Verification Token
2. 飞书开放平台 → 权限管理 → 开通 wiki/im/docx 相关权限
3. 运行 `python -m tools.list_feishu_spaces` 获取 Wiki Space ID
4. 钉钉开放平台 → 机器人消息接收 → 填写 Webhook URL
