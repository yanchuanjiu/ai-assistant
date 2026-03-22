# MEMORY.md — 长期记忆

_这是我的精华记忆，由心跳任务定期提炼和维护。原始日志在 `logs/interactions.jsonl`。_
_2026-03-22（基于 198 条交互日志分析，v1.0.16 自我改进）_

## 用户行为模式

* 最近更新：2026-03-22

- **最常请求任务**：飞书知识库项目目录操作、钉钉会议纪要整理并写入飞书、多话题并行管理、AI前沿信息定向查询
- **重复请求模式**：同一问题失败后用户不加说明直接重发，期望 Agent 自动检测并修复原因，而不是重试
- **沟通风格**：直接简短，不喜欢冗长解释；遇到失败会直接说"你没有成功"并要求修复；多轮对话中权限问题持续出现时语气会变得不满
- **工作背景**：美妆护肤行业，AI产品经理/技术负责人角色，管理多个 AI 落地项目
- **平台习惯**：钉钉存会议记录（只读来源），飞书是写入目标和主要工作台
- 用户明确要求将会议纪要维护到飞书文档，而非钉钉
- **4月有全球高管汇报**，知识库上线进展是关键交付物，时间敏感
- **新兴需求（3月22日）**：希望定向订阅 AI 前沿进展（Agentic platform、vibe coding、Google Workspace CLI、阿里悟空等），而非宽泛搜索；期望定期汇总有参考价值的新功能
- **多话题使用习惯**：已积极使用 #话题名 前缀；在聊天框内 reply 特定话题；3月22日反馈有回复未加入到对应话题（路由问题）

## 用户的三个核心项目（已识别）

1. **大模型产品知识库项目** — 美妆护肤产品知识梳理，服务市场营销培训、线下/线上美容顾问、电商运营、客服等多场景
2. **VOC 电商运营项目** — 消费者互动内容分析、舆情侦听，通过大模型赋能营销运营
3. **AI 赋能消费者决策链路** — 与淘宝/千问/豆包合作，GEO/万能搜/货通优化，提升美妆知识消费者体验

## 常用工作流

1. **会议纪要整理**：钉钉 MCP 读取 → analyze_meeting_doc → 写入飞书对应项目页
2. **新建项目目录**：feishu_project_setup(project_name, project_code) → 返回7个文档链接
3. **项目进展梳理**：从钉钉历史会议中提取关键信息 → 整理成项目周报/进展页写入飞书

## 已知注意事项

- ✅ 已解决（v0.8.12）：用户6次请求创建3个项目目录均失败。根因：缺少 `feishu_project_setup` 工具。v0.8.12 已修复
- ✅ 已解决（v0.8.28）：飞书操作从首页而非空间根节点开始。v0.8.28 修复：list_children 不传 parent 时默认从空间根节点开始
- **代码生效需重启**：每次 commit 后必须重启服务，否则 Python 内存中仍运行旧代码
- **parent_wiki_token 不能传 space_id**：飞书空间ID（纯数字如 `7618158120166034630`）不是有效的 wiki token

- **⚠️ 钉钉纪要回答未回复到原问题（BUG-001，未解决）**：用户在钉钉中提问 → Agent 分析会议纪要后以新消息回复，未 thread 至原始提问消息。相关代码：`integrations/dingtalk/bot.py` 响应发送逻辑。待心跳任务分析根因后更新此条。录入：2026-03-21

- **⚠️ 131006 权限错误（核心问题，v1.0.10 修复根因D）** — 截至2026-03-22已出现 14+ 次，跨越多天：
  - **根因A（已配置，非当前根因）**：`FEISHU_USER_ACCESS_TOKEN` / `FEISHU_USER_REFRESH_TOKEN` 曾未配置 → 现已在 .env 中配置
  - **根因B（确认）**：飞书 wiki SPACE 成员权限 ≠ 应用 wiki:wiki 权限。即使 wiki:wiki 应用权限已开通，调用 `/wiki/v2/spaces/{space_id}/nodes` 仍需要 APP 被显式添加为空间成员
  - **根因C（v0.9.5 修复）**：飞书 API 有时以 HTTP 200 响应返回 `{"code": 131006, ...}`，旧代码只检测 HTTP 4xx/5xx 异常 → 已修复为主动检查 resp.get("code")
  - **根因D（v1.0.10 新发现 + 修复，2026-03-22 根因）**：并发 token 续期竞争条件。多个并发请求同时发现 user access_token 过期 → 都用同一 refresh_token 调用续期接口 → 第一个成功，其余因 refresh_token 已失效而失败 → 失败请求抛出 RuntimeError → `_wiki_get`/`_wiki_post` 错误地将任意 RuntimeError 都视为"token未配置" → 降级 tenant token → tenant token 无 wiki 空间成员权限 → 131006
  - **v1.0.10 代码修复**（client.py + knowledge.py）：
    1. 新增 `UserTokenNotConfiguredError(RuntimeError)` 专用异常类，区分"未配置"和"续期失败"
    2. `get_user_access_token()` 加 `threading.Lock`（双重检查锁定），确保同一时刻只有一个线程执行续期
    3. `_wiki_get`/`_wiki_post` 只捕获 `UserTokenNotConfiguredError` 才降级，续期失败直接上报
  - **用户已完成**：.env 中 FEISHU_USER_ACCESS_TOKEN + FEISHU_USER_REFRESH_TOKEN 已配置，refresh_token 有效期约30天
  - ⚠️ **重要**：不要告诉用户"权限已开通就够了"，wiki:wiki 应用权限和空间成员权限是两个不同的事情

- **响应延迟极高（⚠️ 持续未解决）**：198条交互中92.4%超过15秒（183/198），p50=80s，p95=433s，max=2975s（49分钟）。LLM单次avg 38.6s，p95=97s。根因：① "会议"关键词触发多分类工具，系统提示极长 ② 主飞书线程avg 42K tokens（max 203K） ③ 工具调用链长。v1.0.11移除feishu_advanced"会议"重复关键词部分缓解。用户已明确反馈（2次明确投诉）。
- **token 消耗极重（⚠️ 持续未解决）**：最近1107次LLM：avg input 42K，p95=183K；主飞书线程avg 54K（!!）、max 203K；心跳线程avg 33K，max 36K。**46.8%的LLM调用超过30K tokens**。
- **话题路由 BUG（✅ v1.0.11 修复）**：用户通过"引用回复"(quote-reply)话题消息时，飞书消息有 parent_id 但 root_id 为空，旧代码只检查 root_id → 主聊天上下文。修复：_parse_feishu_message 增加 parent_id fallback。
- **会议纪要飞书展示效果不好（✅ v1.0.11 修复）**：Markdown 表格在 md_to_feishu_blocks 不支持，渲染为含竖线的原始文本。修复：format_for_project_page 改为列表项格式（`- 📅 **日期**：{date}`）。
- **admin-http 端口冲突（✅ v1.0.4 已修复）**：HTTPServer 已改为端口占用时跳过而非崩溃，不再写入 crash.log
- **错误响应率**：171条交互中31条包含"失败/错误/出错"（18.1%），含飞书 wiki 权限错误和响应延迟相关问题

- **⚠️ 飞书 OAuth refresh_token 未自动续期（v1.0.4 修复）**：
  - **根因1（关键）**：旧接口 `/authen/v1/refresh_access_token` 在 refresh_token 失效时返回 HTTP 200 + `{"code": 999xxx}`，`raise_for_status()` 无法捕获，导致 `data["access_token"]` KeyError 静默失败
  - **根因2**：从未保存 `refresh_expires_in`（30天），refresh_token 过期时没有提前预警
  - **v1.0.4 修复**：1) 检查响应 code != 0 时抛出清晰 RuntimeError；2) 优先使用 OIDC 接口 `/authen/v1/oidc/refresh_access_token`，失败降级旧接口；3) 保存 `FEISHU_USER_REFRESH_EXPIRES_AT` 到 .env；4) heartbeat 增加 refresh_token 到期预警

## 改进历史

- 2026-03-20：首次基于 31 条交互日志的自我改进分析
- 2026-03-20（v0.8.20）：多任务上下文污染修复 + ToolMessage 截断至300字符
- 2026-03-21（v0.8.28）：飞书操作起点修复（从空间根节点开始）；纠正率14.5%
- 2026-03-21（v0.9.1）：基于83条交互，131006权限错误根因全面分析；新增 FEISHU_WIKI_ROOT_NODES 降级方案；纠正率18.1%（15/83）
- 2026-03-21（v0.9.5）：基于100条交互，发现 131006 在 HTTP 200 响应中被静默忽略（根节点返回空列表）；修复 list_wiki_children / create_wiki_child_page 的响应码检查；纠正率18%（18/100）
- 2026-03-21（v1.0.4）：基于149条交互，修复飞书 OAuth refresh_token 未自动续期（根因：HTTP 200 错误码未检测 + 旧接口）；修复 admin-http 端口冲突 crash；纠正率12.8%（19/149）
- 2026-03-22（v1.0.9）：基于171条交互，发现话题路由BUG（用户reply未加入正确话题）；token消耗恶化（avg 43K）；新用户需求：AI前沿定向订阅；纠正率12.9%（22/171）
- 2026-03-22（v1.0.10）：基于177条交互，发现并修复131006根因D（并发token续期竞争条件）；加threading.Lock防止多线程同时续期；区分UserTokenNotConfiguredError和续期失败；纠正率12.4%（22/177）
- 2026-03-22（v1.0.11）：基于179条交互，修复话题路由BUG-002（parent_id fallback）；修复会议纪要Markdown表格渲染问题；移除feishu_advanced"会议"重复关键词减少工具叠加；纠正率12.3%（22/179）
- 2026-03-22（v1.0.16）：基于198条交互，新增feishu_wiki_delete工具（删除wiki节点）；纠正率12.1%（24/198）；响应延迟持续高（p50=80s），已记录根因；主飞书线程token消耗恶化（avg 54K）

- ⚠️ 未解决：钉钉纪要回答未回复到原问题（BUG-001）—— MarkdownCardInstance.reply 已绑定原消息，但 send_text fallback 仍为独立消息
- ✅ 已解决（v1.0.11）：飞书话题路由 BUG-002 — quote-reply 消息 parent_id 未被路由
