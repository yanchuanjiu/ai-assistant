# AI 个人助理 — Claude Code 项目上下文

> 本文件供 Claude Code 自迭代时读取，也是新成员了解项目的入口。

## 项目定位

个人非商用 AI 助理，部署在 Linux 云服务器（`/root/ai-assistant`）。
通过飞书/钉钉机器人对话交互，无稳定性/性能硬性要求。**可用性和可迭代性优先**。

## 技术栈

| 层 | 技术 |
|----|------|
| Web | FastAPI + uvicorn |
| Agent | LangGraph ReAct + SQLite Checkpointer |
| 主力 LLM | 火山云 Ark `ep-20260317143459-qtgqn` |
| 备用 LLM | OpenRouter `anthropic/claude-sonnet-4-5`（with_fallbacks 自动切换） |
| 自迭代 | Claude Code CLI（`ANTHROPIC_API_KEY` 仅此处使用） |
| 定时任务 | APScheduler |
| 飞书集成 | 国内版飞书开放平台 API |
| 钉钉集成 | 企业内部应用 API + 文档空间 API |
| 邮件 | 163 IMAP 轮询 |

## 目录结构

```
graph/           LangGraph：state / agent / nodes / tools
integrations/    第三方集成：feishu / dingtalk / email / storage
sync/            SQLite ↔ 飞书知识库双向同步
prompts/         system.md（主 prompt）/ meeting_extract.md
tools/           运维辅助脚本
docs/            详细文档（架构/部署/开发/集成）
data/            运行时数据，gitignored
```

## 核心设计决策

1. **LLM 不用 Claude API**：Agent LLM 链是 火山云 → OpenRouter，Claude API 仅供此 CLI 工具使用
2. **记忆双轨**：SQLite（机器可读，跨会话持久化）+ 飞书知识库（人类可读，定期同步）
3. **工具扩展点**：新增技能只需在 `graph/tools.py` 加 `@tool` 函数并加入 `ALL_TOOLS`，无需改其他文件
4. **自迭代限制**：Shell 白名单保护，Claude Code 工作目录限定在本项目

## 启动方式

```bash
cd /root/ai-assistant
source .venv/bin/activate   # 或 pip install -r requirements.txt
python main.py
# 健康检查: curl http://localhost:8000/health
```

## 待完成配置

- [ ] `FEISHU_WIKI_SPACE_ID`：运行 `python -m tools.list_feishu_spaces` 获取
- [ ] `FEISHU_VERIFICATION_TOKEN`：飞书开放平台事件订阅页面获取
- [ ] 飞书应用权限：`im:message`、`wiki:wiki`、`docx:document`
- [ ] 钉钉机器人消息接收 URL 配置

## 自迭代规则（Claude Code 须知）

收到开发需求时：
1. **先读 `CLAUDE.md` 和相关模块**，理解现有代码再动手
2. **最小改动原则**：只改需求涉及的文件
3. **新增工具**：在 `graph/tools.py` 加函数，加入 `ALL_TOOLS`
4. **新增集成**：在 `integrations/` 新建子目录，在 `main.py` 注册 router
5. **完成后输出**：① 修改了哪些文件 ② 做了什么 ③ 如何验证

## 当前 MVP 状态

- [x] 飞书机器人 Webhook 收发
- [x] 钉钉企业内部机器人收发
- [x] LangGraph ReAct Agent + SQLite 记忆
- [x] 163 IMAP 邮件轮询 + 会议信息提取（纯文字）
- [x] 飞书知识库读写
- [x] 钉钉文档空间读取（会议纪要）
- [x] SQLite ↔ 飞书知识库定期同步
- [x] Claude Code 自迭代（全自动，--dangerously-skip-permissions）
- [ ] 火山云 OSS 文件存储（接口占位，待接入）
- [ ] 飞书知识库语义搜索（待接入向量检索）

## 参考文档

- 架构详解：`docs/architecture.md`
- 部署配置：`docs/setup.md`
- 开发指南：`docs/development.md`
- 集成说明：`docs/integrations.md`
