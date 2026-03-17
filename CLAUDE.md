# AI 个人助理 — Claude Code 项目上下文

> 本文件供 Claude Code 自迭代时读取，也是新成员了解项目的入口。
> 最后更新：2026-03-17

## 项目定位

个人非商用 AI 助理，部署在 Linux 云服务器（`/root/ai-assistant`）。
通过飞书/钉钉机器人对话交互，**无稳定性/性能硬性要求，可用性和可迭代性优先**。

## 当前运行状态

```
✅ 飞书机器人    — 长连接（lark-oapi ws.Client），收发消息正常
✅ 钉钉机器人    — 流模式（dingtalk-stream），连接已建立
✅ 火山云 LLM   — ep-20260317143459-qtgqn，调用正常
✅ SQLite 记忆  — data/memory.db，LangGraph checkpointer
✅ 定时任务      — 邮件5分钟/同步30分钟
✅ 飞书知识库  — 读写正常（docx API via get_node），context page 已配置
⚠️  钉钉文档    — /v1.0/doc/spaces API 404，路径待修复
⚠️  163 IMAP   — Unsafe Login，需重新开启邮箱 IMAP
```

## 技术栈

| 层 | 技术 |
|----|------|
| Web | FastAPI + uvicorn |
| Agent | LangGraph ReAct + SQLite Checkpointer |
| 主力 LLM | 火山云 Ark `ep-20260317143459-qtgqn`（OpenAI-compatible） |
| 备用 LLM | OpenRouter `anthropic/claude-sonnet-4-5`（with_fallbacks 自动切换） |
| 自迭代 | Claude Code CLI（`ANTHROPIC_API_KEY` 仅此处使用） |
| 飞书 | `lark-oapi` SDK，长连接模式（ws.Client） |
| 钉钉 | `dingtalk-stream` SDK，流模式（DingTalkStreamClient） |
| 定时任务 | APScheduler |

## 目录结构

```
graph/           LangGraph：state / agent / nodes / tools
integrations/    第三方集成：feishu / dingtalk / email / storage
sync/            SQLite ↔ 飞书知识库双向同步
prompts/         system.md / meeting_extract.md
tools/           运维辅助脚本（list_feishu_spaces 等）
docs/            架构/部署/开发/集成文档
data/            运行时数据，gitignored
logs/            运行日志，gitignored
```

## 核心设计决策

1. **无公网 Webhook**：飞书用 `lark-oapi ws.Client` 长连接，钉钉用 `dingtalk-stream` 流模式，均为服务器主动出连接，不需要公网 IP
2. **LLM 不用 Claude API**：Agent LLM 链是 火山云 → OpenRouter，Claude API 仅供 `claude` CLI 自迭代
3. **记忆双轨**：SQLite（机器可读，LangGraph checkpointer）+ 飞书知识库（人类可读，定期同步）
4. **工具扩展点**：在 `graph/tools.py` 加 `@tool` 函数并加入 `ALL_TOOLS`，无需改其他文件
5. **消息回复解耦**：`graph/agent.py` 的 `invoke()` 只返回文本，各平台 bot handler 负责发送

## 启动方式

```bash
cd /root/ai-assistant
source .venv/bin/activate
python main.py

# 查看日志
tail -f logs/app.log
```

## 已知问题与待完成

| 问题 | 位置 | 优先级 |
|------|------|--------|
| `FEISHU_WIKI_SPACE_ID` 未配置 | `.env` | 高（知识库功能不可用） |
| 钉钉文档 API 404 | `integrations/dingtalk/docs.py` | 中 |
| 163 IMAP Unsafe Login | `integrations/email/imap_client.py` | 中 |
| 火山云 OSS 未接入 | `integrations/storage/base.py` | 低 |

## 自迭代规则（Claude Code 须知）

1. **先读 `CLAUDE.md` 和相关模块**，理解现有代码再动手
2. **最小改动原则**：只改需求涉及的文件
3. **新增工具**：在 `graph/tools.py` 加 `@tool` 函数，加入 `ALL_TOOLS`
4. **新增平台集成**：在 `integrations/` 新建子目录，在 `main.py` 注册启动线程
5. **完成后输出**：① 修改了哪些文件 ② 做了什么 ③ 如何验证
6. **重启方式**：代码改完后运行 `kill $(lsof -ti:8000); python main.py &`

## 参考文档

- 架构：`docs/architecture.md`
- 部署：`docs/setup.md`
- 开发：`docs/development.md`
- 集成：`docs/integrations.md`
- 版本：`CHANGELOG.md`
