# AI 个人助理 — Claude Code 项目上下文

> 本文件是 Claude Code 自迭代的首要参考，进入项目目录后**先读此文件**再动手。
> 最后更新：2026-03-20（v0.8.11）

---

## 项目定位

个人非商用 AI 助理，部署在 Linux 云服务器（`/root/ai-assistant`）。
通过飞书/钉钉机器人对话交互，**无稳定性/性能硬性要求，可用性和可迭代性优先**。

**代码管理原则**：每次确认变更后立即 `git add + commit + push`，确保远程仓库始终是最新版本。

---

## 当前运行状态（v0.8.1）

```
✅ 飞书机器人      — 长连接（lark-oapi ws.Client），收发消息正常
✅ 钉钉机器人      — 流模式（dingtalk-stream），连接已建立
✅ 火山云 LLM     — ep-20260317143459-qtgqn，调用正常
✅ SQLite 记忆    — data/memory.db（LangGraph checkpointer）
                    data/meeting.db（会议文档处理记录）
✅ 定时任务        — 钉钉会议30分钟/邮件60分钟/上下文同步30分钟/心跳30分钟
✅ 飞书知识库      — 读写正常（docx API via get_node）
                    context page: FalZwGDOkiqpbQkeAjGc8jaznMd
✅ 会议纪要闭环    — 钉钉知识库轮询 → LLM 分析 → 飞书写入（自动 + 按需）
✅ LLM 调用日志   — logs/llm.jsonl（JSONL，含 latency/model/usage/tool_calls）
✅ Claude Code迭代 — tmux 会话（持久化），stream-json 实时推送 IM，用户可交互
✅ Claude 会话管理 — list/get_output/kill/send_input（4个工具）
✅ 无限制 CLI      — run_command（无白名单）+ python_execute
✅ Web 工具        — web_search（DuckDuckGo）+ web_fetch
✅ 系统监控        — get_system_status / get_service_status
✅ 飞书扩展工具    — Bitable CRUD / 任务管理 / 文档搜索 / IM 消息读取
✅ 钉钉文档 MCP   — 12个文档工具（搜索/读取/创建/块编辑），关键词"钉钉"触发
✅ 钉钉AI表格 MCP — 21个表格工具（Base/Table/Field/Record CRUD），关键词"钉钉"触发

✅ 运行时配置     — agent_config 工具，对话中动态读写，无需重启（data/memory.db）
✅ 进程管理       — supervised thread + 指数退避自动重启，崩溃写 logs/crash.log
✅ Admin 配置界面  — http://localhost:8080（Web 管理配置，实时生效，无需重启）

✅ 飞书子页面创建  — find_or_create_child_page (tenant token，无需 user OAuth)
✅ 会议页面自发现  — FEISHU_WIKI_MEETING_PAGE 不再需要手动配置，自动在 context page 下创建
✅ 回归测试套件   — tests/regression/（飞书知识库/钉钉MCP/端到端流水线，共33用例）

✅ Workspace 自我体系 — workspace/{SOUL/USER/MEMORY/HEARTBEAT}.md，动态注入 system prompt
✅ 交互日志增强   — logs/interactions.jsonl（含工具使用、延迟、用户纠正信号）
✅ 自我改进工具   — trigger_self_improvement，Claude Code 分析日志 → 优化 → 推送报告
✅ Heartbeat 心跳 — 每30分钟 Agent 主动决策，OWNER_FEISHU_CHAT_ID 通过 agent_config 设置
✅ IM 配置引导   — system.md 内置无需重启的配置项引导规则，用户说"帮我配"即可完成

⚠️  163 IMAP     — 需在 163 网页版重新开启 IMAP 并更新 EMAIL_AUTH_CODE
```

---

## 版本变更历史

### v0.8.9（2026-03-20）— 自我改进：workspace 记忆初始化 + admin 端口修复

**修改文件**：
- `workspace/MEMORY.md` — 首次基于 31 条交互日志完整填充：用户行为模式、3个核心项目信息、已知坑点（延迟/parent_wiki_token/admin端口）
- `workspace/USER.md` — 补充用户工作背景（美妆护肤行业、AI落地项目负责人）和操作注意事项
- `workspace/HEARTBEAT.md` — 新增"优先级 4：项目进展跟踪（每周一次）"；admin-http 崩溃标注为已知问题（同天只提醒一次）
- `admin/server.py` — `start_admin_server()` 设置 `HTTPServer.allow_reuse_address = True` + `SO_REUSEADDR`，解决重启时端口 8080 占用导致的持续 crash

**数据发现**：
- 31 条交互，用户纠正率 6.5%（2/31，低于 15% 阈值）
- 所有交互延迟均 >70 秒，平均约 2-3 分钟，平均 token 消耗 ~110K
- 5 条错误响应均与 `parent_wiki_token` 传入 space_id 有关（v0.8.8 已修复）
- admin-http 线程在每次服务重启时因端口已占用持续写入 crash.log

### v0.8.11（2026-03-20）— 主动错误检测 + 自动修复 + GitHub Issue 上报

**修改文件**：
- `integrations/logging/error_tracker.py` — **新建**：错误关键词检测、出现次数追踪（`data/auto_fix_tracker.json`）、GitHub Issue 创建（`gh` CLI）
- `graph/agent.py` — `invoke()` 在返回前启动后台线程 `_maybe_auto_fix()`；新增 `_maybe_auto_fix()` 和 `_build_auto_fix_requirement()` 函数

**能力变化**：
- Agent 回复含错误/异常关键词时（如"错误"、"失败"、"Exception"等），自动在后台触发 Claude Code 修复
- 同一错误模式第 1-2 次：静默修复（启动 Claude Code 会话，修复后推送报告）
- 第 3 次及以上：停止自动修复，通知用户一起排查，并自动创建 GitHub Issue
- 错误追踪数据持久化到 `data/auto_fix_tracker.json`

### v0.8.10（2026-03-20）— 上下文截断 + Token 优化 + 自我改进增强

**修改文件**：
- `graph/nodes.py` — 新增 `_trim_to_user_turns()`（MAX_USER_TURNS=5，只传最近5轮用户消息给 LLM）；`_select_tools()` 新增短消息快速返回（<25字符无关键词→直接返回 CORE_TOOLS）、连续性扫描从全量历史改为最近 10 条；`agent_node()` 使用截断后的消息
- `graph/tools.py` — `trigger_self_improvement` prompt 新增步骤5（重复问题检测：相同话题≥2次→标为"改进后仍复现"）、步骤6（上下文健康：input token>30K 的 thread 标记）；报告格式新增"🔄 重复出现的问题"和"📏 上下文健康"节
- `prompts/system.md` — 新增"对话重置"节：说明5轮截断机制、引导用户用 `/clear`、Agent 主动提示时机
- `workspace/HEARTBEAT.md` — 优先级2"记忆维护"拆分为短期（当日）+ 长期（每周压缩）+ 上下文健康检查三项
- `workspace/MEMORY.md` — 更新改进历史

**能力变化**：
- LLM 每次调用只接收最近 5 轮用户消息，长对话不再膨胀 token
- 短消息（"好的"、"谢谢"等）不再触发工具加载，直接返回 CORE_TOOLS
- 连续性工具保持窗口从全量→最近10条，防止工具集无限积累
- 自我改进报告可识别"改进后仍复现"的问题（超越 has_correction 关键词限制）
- 心跳每日更新短期记忆，每周压缩长期记忆，检查上下文过重的 thread

### v0.8.8（2026-03-20）— 修复飞书 wiki 子页面创建 400 Bad Request

**修改文件**：
- `integrations/feishu/knowledge.py` — 新增 `_is_space_level_token()` 方法；`list_wiki_children()` 检测到 space 级标识时自动降级为列出根节点；`create_wiki_child_page()` 增加方案A（直接调用 `POST /wiki/v2/spaces/{space_id}/nodes`），方案B（move_docs_to_wiki）保留为降级兜底；对 space 级 token 直接抛 ValueError 提示
- `graph/tools.py` — `feishu_wiki_page` 和 `feishu_project_setup` 在调用 KB 方法前先用 `parse_wiki_token()` 清理 `parent_wiki_token`（去除 URL 前缀、inline comment、空白）

**根因**：LLM 有时将 space_id（纯数字如 `7618158120166034630`）或 `space_XXX` 格式传作 `parent_wiki_token`，导致 Feishu API 返回 400；同时原有创建路径只有 `move_docs_to_wiki` 一种，新增直接节点创建 API 作为首选。

**能力变化**：
- 传入 space 级标识时自动处理而非崩溃
- 新建子页面首选直接 wiki 节点创建 API，失败时自动降级到原有 docx→move 方案

### v0.8.7（2026-03-20）— 钉钉会议纪要 → 飞书项目文档自动更新

**修改文件**：
- `prompts/meeting_analysis.md` — 新增提取字段：project_name/code、raid_elements（Risk/Action/Issue/Decision）、milestone_impact、weekly_report_hint
- `integrations/meeting/analyzer.py` — 新增 4 个方法：`format_for_project_page`、`format_raid_rows`、`write_to_project_page`、`write_raid_rows`；原有方法不变（向后兼容）
- `integrations/meeting/tracker.py` — 新增列：project_name/code/folder_token/raid_written；幂等 ALTER TABLE 迁移
- `integrations/meeting/project_router.py` — **新建**：`ProjectRouter` 类，识别项目并路由到飞书 04/05/06 子页面
- `integrations/feishu/knowledge.py` — 新增 `_PROJECT_DOCS`/`_PROJECT_TEMPLATES` 常量 + `bootstrap_project()` 方法（一键创建7个项目文档）
- `graph/tools.py` — 新增 `feishu_project_setup` 工具；`analyze_meeting_doc` 接入项目路由；更新 TOOL_CATEGORIES + CATEGORY_KEYWORDS
- `scheduler.py` — 新增 `_route_and_write_meeting()` 辅助函数；`poll_dingtalk_meetings()` 接入项目感知路由
- `prompts/system.md` — 新增 `feishu_project_setup` 工具说明 + 新建项目流程

**能力变化**：
- 会议纪要自动识别所属项目 → 写入项目 `04_会议纪要` 子页（而非全局汇总页）
- RAID 元素（风险/行动项/问题/决策）自动提取 → 写入项目 `06_RAID 日志`
- `feishu_project_setup` 工具：一句话创建完整 7 文档项目结构（含标准模板）
- 无法识别项目时自动降级到全局「📋 会议纪要汇总」页

### v0.8.6（2026-03-20）— IM 长回复压缩 + 详情写飞书

**修改文件**：
- `prompts/system.md` — 新增"IM 回复规范"节：IM ≤800字符，超出时写"📝 AI 回复详情"页并发摘要+链接，明确触发场景和摘要格式
- `integrations/feishu/bot.py` — `send_text` 新增兜底逻辑：超 800 字符时调用 `_save_to_feishu_wiki()` 存飞书，IM 发前 300 字摘要 + wiki 链接；飞书写入失败时降级为原有分段发送；新增 `_save_to_feishu_wiki()` 方法（`find_or_create_child_page` + `append_to_page`）

**能力变化**：
- LLM 层（主动）：system prompt 指导 LLM 在回复超长时主动写飞书再发摘要
- Bot 层（兜底）：LLM 未遵守时 bot 自动截断并存飞书，IM 始终保持简洁
- 飞书"📝 AI 回复详情"页自动创建并按时间戳追加，token 缓存在 config_store

### v0.8.5（2026-03-19）— 项目管理 Skill 集成 + 多任务并行处理

**修改文件**：
- `workspace/SKILLS_PROJECT_MGMT.md` — 新增：IT 项目集管理 Skill，含页面结构规范、五种文档模板（章程/技术方案/周报/RAID/会议纪要）、写入前治理检查规则
- `graph/nodes.py` — `_build_system_prompt()` 加入 `SKILLS_PROJECT_MGMT.md` 注入，每次 LLM 调用动态加载
- `prompts/system.md` — 新增"写入前治理检查"规则（项目文档写入前先确认归属/类型/模板）；新增"多任务识别与并行处理"节（并行工具调用 + 分主题汇报）
- `graph/tools.py` — `CATEGORY_KEYWORDS["feishu_wiki"]` 新增项目管理触发词（项目/章程/周报/里程碑/需求文档/技术方案/风险/raid/复盘/项目集/portfolio/上线/验收/立项）

**能力变化**：
- 用户提到项目相关关键词 → 自动注入飞书知识库工具 + SKILL_PROJECT_MGMT 指导
- 写入项目文档前 → Agent 先执行治理检查（归属/模板），新项目自动引导建章程
- 收到多任务消息 → Agent 并行发起工具调用，分主题汇报结果

### v0.8.2（2026-03-19）— 修复会议纪要写入目标：钉钉→飞书

**修改文件**：
- `graph/tools.py` — `CATEGORY_KEYWORDS["feishu_wiki"]` 新增会议/纪要/meeting 等关键词，确保会议纪要场景下飞书写入工具被注入
- `prompts/system.md` — 明确数据流"钉钉（只读来源）→ 飞书（写入目标）"；新增手动写入和迁移步骤；工具使用原则新增禁止写回钉钉的强制规则

**根因**：关键词"会议/纪要"只触发 `dingtalk_mcp` 分类，未触发 `feishu_wiki`，LLM 只有钉钉写入工具可用，因此写回钉钉。

### v0.8.1（2026-03-19）— 配置引导完善：IM 对话直接完成配置，无需重启

**修改文件**：
- `scheduler.py` — `heartbeat()` 读取 `OWNER_FEISHU_CHAT_ID` 时优先查 config_store，fallback .env；无需重启即可激活心跳推送
- `prompts/system.md` — 新增「运行时配置引导」节：明确所有无需重启的配置 key 及其触发场景；Agent 在用户提到心跳/通知/会议/钉钉空间等关键词时主动引导并代为完成配置

**设计动机**：用户提到相关功能时，Agent 应主动带出配置方法并通过 `agent_config` 在 IM 中一次性完成，不要让用户手动改文件或重启服务。

### v0.8.0（2026-03-19）— 自我学习三件套：Workspace + 自我改进 + Heartbeat

**新增文件**：
- `workspace/SOUL.md` — Agent 行为原则与价值观
- `workspace/USER.md` — 用户画像（持续积累）
- `workspace/MEMORY.md` — 长期记忆（心跳提炼，初始为空模板）
- `workspace/HEARTBEAT.md` — 主动任务清单（可自行调整优先级）
- `integrations/logging/__init__.py`
- `integrations/logging/interaction_logger.py` — 交互日志记录（logs/interactions.jsonl）

**修改文件**：
- `graph/nodes.py` — `_build_system_prompt()` 替换原静态 `SYSTEM_PROMPT`，每次 LLM 调用动态读取 workspace 文件，Claude Code 改完即生效
- `graph/agent.py` — `invoke()` 调用后自动记录交互日志（工具列表、延迟、纠正信号），跳过内部 heartbeat/scheduler 调用
- `graph/tools.py` — 新增 `trigger_self_improvement` 工具（claude 分类）；Claude Code 接收全量日志分析后更新 workspace 文件并重启服务；新增触发关键词「自我改进」等
- `scheduler.py` — 新增 `heartbeat()` 定时任务（30分钟），深夜自动静默，每次独立 thread_id 避免上下文堆积；Agent 回 HEARTBEAT_OK 则静默，有实质内容推送给 owner

### v0.7.7（2026-03-18）— 会议纪要流水线并入钉钉分类 + 清理待办项

**修改文件**：
- `graph/tools.py` — 删除 `"meeting"` 分类；将 4 个 pipeline 工具（`get_latest_meeting_docs` / `read_meeting_doc` / `analyze_meeting_doc` / `list_processed_meetings`）并入 `dingtalk_mcp`；无论 MCP 是否连接，pipeline 工具始终注册；`CATEGORY_KEYWORDS["dingtalk_mcp"]` 新增会议/纪要/meeting 等触发词
- `prompts/system.md` — 删除独立"## 会议纪要流水线"节；改写为"### 会议纪要处理（知识库同步 Skill）"嵌入钉钉文档节末尾
- `README.md` — 删除独立"会议纪要流水线"工具子表；在钉钉 MCP 节末尾补充一行说明；删除 3 个不在计划内的待办项（163 IMAP / action items / OSS）
- `CLAUDE.md` — 工具表分类更新；待办项清理；新增本版本历史
- `docs/architecture.md` — TOOL_CATEGORIES 说明更新

**设计动机**：会议纪要处理是钉钉知识库的使用场景，而非独立分类。合并后：
- 用户说"会议"/"纪要" → 触发 `dingtalk_mcp`（含 MCP 工具 + pipeline 工具）
- 避免"会议"关键词触发孤立的 `meeting` 分类而缺失 MCP 工具的情况
- pipeline 工具不依赖 MCP 连接状态，始终可用

### v0.7.9（2026-03-18）— Admin Web 配置管理界面

**新增文件**：
- `admin/__init__.py`
- `admin/server.py` — 基于 Python stdlib `http.server` 的轻量 Web 管理服务（无新依赖）

**修改文件**：
- `main.py` — 新增 `_start_admin()` + `_supervised("admin-http", ...)` 线程

**功能**：
- 访问 `http://localhost:8080` 即可查看/添加/编辑/删除 agent_config 配置项
- REST API：`GET /api/config`、`POST /api/config`、`DELETE /api/config/{key}`
- 前端纯原生 JS，内嵌于 Python 字符串，无构建步骤
- 预定义常用 key（FEISHU_WIKI_MEETING_PAGE 等）快速选择 + 说明提示
- 配置写入 SQLite（同 `agent_config` 工具），实时生效，无需重启
- 端口可通过环境变量 `ADMIN_PORT` 覆盖（默认 8080）

**设计动机**：`agent_config` 工具只能通过 IM 对话管理配置，非技术用户不友好。Web 界面允许直接在浏览器中配置知识库 ID 等参数，且与现有存储层（config_store）完全复用。

### v0.7.8（2026-03-18）— 邮件会议提取改由主 Agent 处理，移除 Haiku 独立调用

**删除文件**：
- `integrations/email/parser.py` — 原 Anthropic Haiku 调用入口，已移除
- `prompts/meeting_extract.md` — 邮件提取 prompt，已移除（prompt 内联到 scheduler）

**修改文件**：
- `scheduler.py` — 重写 `poll_email()`：删除 `extract_meeting_info`/`FeishuKnowledge` 导入，改为构造 prompt 后调用 `graph.agent.invoke()`；删除 `_format_email_meeting()`；新增 `_build_email_prompt()`
- `requirements.txt` — 删除 `anthropic>=0.40.0` 和 `langchain-anthropic>=0.3.0`

**设计动机**：主 Agent（火山云 Ark）应是唯一处理此类判断任务的 LLM，独立 Haiku 调用与整体 LLM 分工设计不一致。改造后：
- 定时任务拉取邮件 → 构造 prompt → 主 Agent 判断是否为会议邮件 → 自主决定是否写飞书
- prompt 包含"会议"/"飞书"/"追加"等关键词，触发 `feishu_wiki` + `dingtalk_mcp` 分类工具

### v0.7.6（2026-03-18）— 飞书子页面创建 + 会议页面自发现 + 回归测试套件

**新增文件**：
- `tests/regression/test_feishu_wiki.py` — 飞书知识库回归测试（14用例：读取/追加/子页面/工具）
- `tests/regression/test_dingtalk_mcp.py` — 钉钉 MCP 工具回归测试（8用例：搜索/列节点/内容读取）
- `tests/regression/test_e2e_pipeline.py` — 端到端流水线回归测试（11用例：分析/写飞书/去重）
- `tests/regression/run_all.py` — 回归测试 CLI 入口（支持按套件运行）
- `tests/__init__.py` / `tests/regression/__init__.py` / `tests/regression/conftest.py`

**修改文件**：
- `integrations/feishu/knowledge.py` — 新增 `list_wiki_children` / `create_wiki_child_page` / `find_or_create_child_page`；`_append_text` 分批写入（每批40行），修复超50块限制导致的400错误
- `integrations/meeting/analyzer.py` — 新增 `_get_or_create_meeting_page()`；`write_to_feishu` 自动在 context page 下创建"📋 会议纪要汇总"子页面，不再依赖手动配置
- `graph/tools.py` — 新增 `feishu_wiki_page` 工具（list_children / find_or_create）；加入 feishu_wiki 分类

**测试结果**：
```
tests/regression/test_feishu_wiki.py   — 14 passed
tests/regression/test_dingtalk_mcp.py  — 8 passed
tests/regression/test_e2e_pipeline.py  — 8 passed, 3 skipped（LLM超时，外部依赖）
```

**跳过用例说明**：`TestAnalyze` 中 3 个用例因 LLM 超时跳过（`pytest.skip`），属预期行为。LLM 超时是外部依赖问题，不是代码 bug。

### v0.7.5（2026-03-18）— 修复钉钉文档访问问题

**修改文件**：
- `integrations/dingtalk/docs.py` — 新增 `extract_node_id_from_url()`；`_list_wiki_nodes` 扩充响应格式（`result.*` / `nodeList` / 列表）+升级日志；`_normalize_node` 新增 `object_id`；`read_file_content` 支持 URL + 更完整内容字段解析
- `graph/tools.py` — `read_meeting_doc` 支持 URL 输入 + 失败时提示改用 MCP；`TOOL_CATEGORIES["meeting"]` 恢复 `get_latest_meeting_docs` / `read_meeting_doc` 作为 MCP 降级备选
- `prompts/system.md` — 新增原则：alidocs URL 必须提取 nodeId 调用 `get_document_content`，禁止 `web_fetch`/`feishu_read_page`

**解决问题**：
- 用户发 alidocs URL → agent 正确调用 MCP `get_document_content` 而非 web_fetch（需登录）
- `_list_wiki_nodes` 失败时打印完整响应，方便排查权限/格式问题
- `read_meeting_doc` 支持 alidocs URL 直接传入（自动提取 nodeId）

### v0.7.4（2026-03-18）— MCP 接管钉钉文档能力 + 系统提示词更新

**修改文件**：
- `prompts/system.md` — 替换"会议与文档"节为"钉钉文档（MCP）"+"钉钉AI表格（MCP）"+"会议纪要流水线"
- `graph/tools.py` — `TOOL_CATEGORIES["meeting"]` 移除旧工具（`get_latest_meeting_docs` / `read_meeting_doc`）；扩充 `dingtalk_mcp` 关键词（加入"钉钉"/"dingtalk"）；从 `meeting` 关键词中移除"钉钉"/"dingtalk"，避免路由冲突；更新 `analyze_meeting_doc` docstring（file_id 来源改为 MCP）

**效果**：
- 用户说"钉钉"/"搜索钉钉文档" → 触发 `dingtalk_mcp`，调用 MCP 工具
- "会议分析" → 触发 `meeting`，调用 `analyze_meeting_doc` / `list_processed_meetings`
- LLM 通过 system prompt 知晓完整 MCP 工具能力

### v0.7.3（2026-03-18）— 去除 FastAPI/uvicorn，supervised thread 进程管理

**修改文件**：
- `main.py` — 重写：去除 FastAPI/uvicorn，改用 `_supervised()` 线程管理（指数退避重启）+ signal 优雅关闭 + PID 写入 `logs/service.pid`
- `requirements.txt` — 删除 fastapi、uvicorn[standard]、python-multipart
- `graph/tools.py` — `get_service_status` 新增读 `logs/crash.log` 最近 5 条崩溃记录

**崩溃日志格式**（JSONL，`logs/crash.log`）：
```json
{"time": "2026-03-18T10:06:20", "thread": "feishu-ws", "error": "...", "traceback": "..."}
```

**启动命令变更**：
```bash
# 旧（需要 kill port 8000）
kill $(lsof -ti:8000) 2>/dev/null
nohup python main.py >> logs/app.log 2>> logs/server.log &

# 新（用 PID 文件，所有输出合并到 app.log）
kill $(cat logs/service.pid 2>/dev/null) 2>/dev/null
nohup python main.py >> logs/app.log 2>&1 &
```

### v0.7.2（2026-03-18）— 运行时配置存储（无需重启）

**新增文件**：
- `integrations/storage/config_store.py` — SQLite key-value 配置存储（data/memory.db）

**修改文件**：
- `graph/tools.py` — 新增 `agent_config` 工具（get/set/delete/list），加入 CORE_TOOLS
- `integrations/meeting/analyzer.py` — `write_to_feishu` 先查 config_store，再 fallback .env
- `integrations/dingtalk/docs.py` — `__init__` 先查 config_store 的 DINGTALK_DOCS_SPACE_ID；
  `read_file_content` 自动探测有效 API 路径并写入 DINGTALK_WIKI_API_PATH（后续直接使用）

**解决问题**：
- `FEISHU_WIKI_MEETING_PAGE` 不再需要改 .env 重启，直接 `agent_config(set, ...)` 即可
- 钉钉文档 API 路径首次调用后自动记忆，不再每次重试两条路径

### v0.7.1（2026-03-18）— 渐进式工具披露 + DingTalk API 修复

**修改文件**：
- `graph/tools.py` — 拆分为 `CORE_TOOLS` + `TOOL_CATEGORIES`（渐进式披露，87% token 节省）
- `graph/nodes.py` — `agent_node` 按消息关键词动态注入工具分类
- `integrations/dingtalk/client.py` — `get_current_user_unionid` API 路径 `/v1.0/contact/users/me` → `/v2.0/users/me`

**渐进式工具架构**：
```
CORE_TOOLS（6个，每次必带）：web_search / web_fetch / python_execute / run_command / get_system_status / get_service_status

TOOL_CATEGORIES（按需注入，关键词匹配）：
  feishu_wiki    — 飞书知识库关键词 → 5 个工具
  feishu_advanced— 多维表格/任务/搜索关键词 → 6 个工具
  meeting        — 会议/钉钉关键词 → 4 个工具
  claude         — 迭代/开发/Claude关键词 → 5 个工具
```

### v0.7.0（2026-03-18）— 会议纪要闭环 + LLM 日志

**新增文件**：
- `integrations/meeting/__init__.py`
- `integrations/meeting/analyzer.py` — 火山云 LLM 分析会议纪要，结果写飞书
- `integrations/meeting/tracker.py` — SQLite 记录已处理文档（data/meeting.db）
- `prompts/meeting_analysis.md` — 会议纪要结构化提取 prompt

**修改文件**：
- `scheduler.py` — 新增 `poll_dingtalk_meetings()`（每30min），调整任务 id
- `graph/tools.py` — 新增 `analyze_meeting_doc` / `list_processed_meetings` 工具；
  将之前 Claude Code 迭代新增的 6 个飞书工具加入 ALL_TOOLS（之前遗漏）
- `graph/nodes.py` — 每次 LLM 调用后写入 `logs/llm.jsonl`（含 latency/usage/tool_calls）

**会议闭环流程**：
```
APScheduler（每30min）
  → poll_dingtalk_meetings()
    → DingTalkDocs.list_recent_files(limit=50)
    → tracker.is_processed(doc_id) → 跳过已处理
    → docs.read_file_content(doc_id) → 读内容
    → analyzer.analyze(content) → 火山云 LLM → 结构化 JSON
    → analyzer.write_to_feishu(info) → 追加到 FEISHU_WIKI_MEETING_PAGE
    → tracker.mark_processed(doc_id)

用户也可直接触发：
  → analyze_meeting_doc(file_id) — 按需分析单篇（支持 force=true 重新分析）
  → list_processed_meetings()    — 查看已处理记录
```

### v0.6.1（2026-03-18）— 飞书工具扩展（Claude Code 自动迭代）

Claude Code tmux 会话自动完成，内容：
- `integrations/feishu/client.py`：user_access_token 流程（含 refresh_token 自动续期 + .env 写回）；新增 `feishu_get_user` / `feishu_post_user`
- `integrations/dingtalk/docs.py`：先试 `/v1.0/wiki/spaces/{id}/nodes`，fallback drive；支持 keyword 过滤和动态 space_id
- `graph/tools.py`：新增 6 个飞书工具（Bitable/Task/Search/IM）、改进 `get_latest_meeting_docs` 签名

**新增工具（6个）**：
| 工具 | 分类 | 描述 |
|------|------|------|
| `feishu_bitable_record` | 飞书Bitable | 多维表格记录 CRUD（7种操作） |
| `feishu_bitable_meta` | 飞书Bitable | 列出数据表/字段/视图 |
| `feishu_task_task` | 飞书任务 | 任务 CRUD + 子任务 |
| `feishu_task_tasklist` | 飞书任务 | 任务清单管理 |
| `feishu_search_doc_wiki` | 飞书搜索 | 全文搜索（需 user token） |
| `feishu_im_get_messages` | 飞书IM | 读取群聊/单聊消息 |

### v0.6.0（2026-03-17）— tmux 化 + 通用能力扩展

- `integrations/claude_code/tmux_session.py` — 基于 tmux 的 Claude Code 会话管理器
- `graph/tools.py` — 新增 9 个工具（Claude 管理/Web/代码执行/系统监控）
- `prompts/system.md` — 更新为全量能力描述

### v0.5.0（2026-03-17）— 流式推送 + 无限制 CLI

- Claude Code 流式推送到 IM（stream-json 解析）
- 用户可通过 IM 消息与运行中的 Claude 交互（stdin relay）
- `run_command` 无白名单限制
- 飞书知识库读写工具

### v0.4.0 及之前

- 初始 LangGraph ReAct 架构；飞书/钉钉双平台接入；SQLite 记忆持久化；会议纪要邮件提取

---

## 技术栈

| 层 | 技术 | 备注 |
|----|------|------|
| Web | FastAPI + uvicorn | port 8000 |
| Agent | LangGraph ReAct + SQLite Checkpointer | thread_id = platform:chat_id |
| 主力 LLM | 火山云 Ark `ep-20260317143459-qtgqn` | OpenAI-compatible |
| 备用 LLM | OpenRouter `anthropic/claude-sonnet-4-5` | with_fallbacks 自动切换 |
| 自迭代 | Claude Code CLI（`--permission-mode acceptEdits`） | OAuth session，tmux 会话 |
| 飞书 | `lark-oapi` SDK，ws.Client 长连接 | 无需公网 |
| 钉钉 | `dingtalk-stream` SDK，流模式 | 无需公网 |
| 定时任务 | APScheduler | 钉钉会议30min，邮件60min，同步30min |
| 进程管理 | tmux 3.4 | Claude Code 会话持久化 |

---

## 目录结构

```
admin/
  ├── __init__.py
  └── server.py          Admin 配置管理 Web 服务（端口 8080，stdlib http.server）

graph/
  ├── agent.py           图定义 + SQLite checkpointer + invoke() 入口
  ├── nodes.py           agent_node（含 LLM 日志） / tools_node / should_continue
  ├── state.py           AgentState TypedDict
  └── tools.py           26 个工具，CORE_TOOLS + TOOL_CATEGORIES（渐进式披露）+ ALL_TOOLS

integrations/
  ├── feishu/
  │   ├── bot.py         长连接消息处理，注册 reply_fn_registry，Claude 会话拦截
  │   ├── client.py      tenant_access_token + user_access_token + feishu_get/post/delete
  │   └── knowledge.py   wiki 读写（parse_wiki_token → get_node → docx API）
  ├── dingtalk/
  │   ├── bot.py         流模式消息处理，同上 Claude 会话拦截
  │   ├── client.py      DingTalk OAuth token；get_current_user_unionid（/v2.0/users/me）
  │   └── docs.py        wiki/drive API 双路径 fallback，支持 keyword 过滤
  ├── email/
  │   ├── imap_client.py 163 IMAP 轮询
  │   └── (parser.py 已删除，v0.7.8 改由主 Agent 处理)
  ├── meeting/
  │   ├── __init__.py
  │   ├── analyzer.py    火山云 LLM 分析会议纪要 → 结构化 JSON → 飞书写入
  │   └── tracker.py     SQLite（data/meeting.db）记录已处理文档，避免重复
  ├── claude_code/
  │   ├── session.py     向后兼容重新导出（→ tmux_session.py）
  │   └── tmux_session.py  TmuxClaudeSession + SessionManager（tmux 实现）
  └── storage/
      ├── config_store.py  运行时 key-value 配置（SQLite，agent_config 工具后端）
      └── base.py          LocalStorage / 待接火山云 OSS

sync/context_sync.py     SQLite checkpoints → 飞书知识库页面
prompts/
  ├── system.md          Agent system prompt（工具能力描述）
  ├── meeting_extract.md 会议信息提取 prompt（邮件场景）
  └── meeting_analysis.md 会议纪要深度分析 prompt（钉钉文档场景）
scheduler.py             APScheduler（钉钉会议30min / 邮件60min / 同步30min）
main.py                  FastAPI lifespan + 两个平台线程
logs/
  ├── app.log            应用日志
  ├── server.log         uvicorn 输出
  └── llm.jsonl          LLM 调用日志（JSONL，每次调用一行）
data/
  ├── memory.db          LangGraph SQLite checkpointer
  └── meeting.db         会议文档处理记录

larksuite-openclaw-lark-2026.3.15.tgz  OpenClaw 飞书集成参考包（技能/工具参考）
```

---

## 核心设计决策（含坑点）

### 1. 无公网 Webhook
飞书用 `lark-oapi ws.Client` 长连接，钉钉用 `dingtalk-stream` 流模式，均为服务器主动出连接。

### 2. LLM 分离：Agent ≠ Claude CLI
- **Agent LLM**：火山云 Ark → OpenRouter（OpenAI-compatible，`VOLCENGINE_API_KEY`）
- **自迭代 CLI**：`claude` 命令，使用 OAuth session token（**不传 `ANTHROPIC_API_KEY`**）
- ⚠️ 关键：wrapper script 中 `unset ANTHROPIC_API_KEY`，否则会覆盖 OAuth session 导致 401

### 3. 飞书知识库权限绕过
`/wiki/v2/spaces` 系列 API **不支持 tenant_access_token**（需要用户 OAuth）。
绕过方案：
1. `GET /wiki/v2/spaces/get_node?token=WIKI_TOKEN` → 获取 `obj_token`（tenant token 可用）
2. `/docx/v1/documents/{obj_token}/...` → docx API 直接读写（tenant token 可用）
3. 前提：飞书页面「文档权限 → 可管理应用」添加该应用

### 4. Claude Code 子进程权限
运行环境是 root，`--dangerously-skip-permissions` 被禁止。
使用 `--permission-mode acceptEdits --output-format stream-json --verbose`。

### 5. Claude Code tmux 会话架构

```
bot._on_message()
  → 注册 reply_fn_registry[thread_id] = bot.send_text
  → session_manager.get(thread_id) → 有活跃 tmux 会话则 relay_input，skip agent
  → 否则 invoke(agent)
      → tools_node: set_tool_ctx(thread_id, send_fn)
          → trigger_self_iteration 调用 session_manager.start()
              → TmuxClaudeSession.start_streaming(requirement)
                  ① 写 prompt 到 /tmp/ai-claude-*.prompt
                  ② 清空 /tmp/ai-claude-*.jsonl
                  ③ 写 wrapper script /tmp/ai-claude-*.sh（含 unset ANTHROPIC_API_KEY）
                  ④ tmux new-session -d -s {name} {script}
                  ⑤ 后台线程 tail .jsonl，解析 stream-json → send_fn → IM

tmux session 名称：ai-claude-{safe_thread_id}
日志文件：        /tmp/ai-claude-{safe_thread_id}.jsonl
直接查看：        tmux attach -t ai-claude-{safe_thread_id}
```

### 6. 消息回复解耦
`graph/agent.py` 的 `invoke()` 只返回文本，各平台 bot handler 负责发送。

### 7. 火山云文本格式工具调用
火山云 Ark 有时以文本形式返回工具调用，格式为 `<|FunctionCallBeginBegin|>[...]`。
`graph/nodes.py` 的 `_extract_text_tool_calls()` 负责解析，转换为标准 LangChain tool_calls。

### 8. 进程重启后恢复方案
⚠️ **重启必须激活 venv**：`source .venv/bin/activate && python main.py`
- 直接 `python main.py` 会因缺少包导致 crash（`ModuleNotFoundError: No module named 'dotenv'`）
- 推荐使用 `nohup python main.py >> logs/app.log 2>> logs/server.log &`，**在激活 venv 后**执行

### 9. 渐进式工具披露（Progressive Tool Disclosure）
LLM 每次调用时携带全量 26 个工具会消耗大量 token（schema 很重）。
解决方案：`graph/nodes.py` 的 `agent_node` 根据用户消息关键词动态决定注入哪些分类：
- `CORE_TOOLS`（6个）每次必带
- 其余 20 个工具按 `CATEGORY_KEYWORDS` 匹配后追加
- 无关键词匹配时只传 6 个 → 节省约 87% token

新增工具时：在 `TOOL_CATEGORIES` 的对应分类中添加，并在 `CATEGORY_KEYWORDS` 中维护触发词。

### 10. 会议纪要 SQLite 去重
`data/meeting.db` 中 `meeting_docs` 表以 `doc_id` 为主键。
每次轮询 `is_processed(doc_id)` 检查，避免重复分析。
非会议文档也会标记为 `not_meeting`，避免每次都调用 LLM。

---

## 工具列表（28个）

| 工具 | 分类 | 描述 |
|------|------|------|
| `agent_config` | 配置 | 运行时配置读写（get/set/delete/list），持久化到 SQLite，无需重启 |
| `feishu_read_page` | 飞书知识库 | 读取飞书 wiki 页面（URL 或 token） |
| `feishu_append_to_page` | 飞书知识库 | 向页面末尾追加内容 |
| `feishu_overwrite_page` | 飞书知识库 | 清空并覆盖写入页面 |
| `feishu_search_wiki` | 飞书知识库 | 在上下文页面中搜索关键词 |
| `feishu_wiki_page` | 飞书知识库 | 子页面管理：list_children / find_or_create（tenant token，无需 user OAuth） |
| `feishu_project_setup` | 飞书知识库 | 一键创建完整项目文件夹结构（7个标准文档+模板），幂等，结果缓存到 config_store |
| `sync_context_to_feishu` | 飞书知识库 | SQLite 记忆 → 飞书知识库 |
| `feishu_bitable_record` | 飞书Bitable | 多维表格记录 CRUD（create/list/update/delete 等7种） |
| `feishu_bitable_meta` | 飞书Bitable | 列出数据表/字段/视图 |
| `feishu_task_task` | 飞书任务 | 任务创建/查询/更新/子任务 |
| `feishu_task_tasklist` | 飞书任务 | 任务清单管理 |
| `feishu_search_doc_wiki` | 飞书搜索 | 全文搜索文档/Wiki（需 user_access_token） |
| `feishu_im_get_messages` | 飞书IM | 读取群聊或单聊历史消息 |
| ~~`get_latest_meeting_docs`~~ | ~~钉钉~~ | ~~已停用，由 MCP `search_documents` 替代~~ |
| ~~`read_meeting_doc`~~ | ~~钉钉~~ | ~~已停用，由 MCP `get_document_content` 替代~~ |
| `analyze_meeting_doc` | 钉钉/会议Skill | 立即 LLM 分析指定文档并写飞书（file_id 来自 MCP） |
| `list_processed_meetings` | 钉钉/会议Skill | 查看已分析的会议文档列表 |
| `trigger_self_iteration` | Claude | 异步启动 Claude Code tmux 会话，流式推送到 IM |
| `list_claude_sessions` | Claude | 列出所有活跃的 tmux Claude 会话 |
| `get_claude_session_output` | Claude | 获取指定会话的最近输出 |
| `kill_claude_session` | Claude | 强制终止 Claude tmux 会话 |
| `send_claude_input` | Claude | 向会话发送追加输入 |
| `web_search` | Web | DuckDuckGo 搜索，无需 API key |
| `web_fetch` | Web | 获取任意 URL 纯文本内容 |
| `python_execute` | 代码 | 执行 Python 代码片段 |
| `run_command` | 系统 | 执行任意 shell 命令（无白名单） |
| `get_system_status` | 系统 | CPU/内存/磁盘状态 |
| `get_service_status` | 系统 | FastAPI 进程、端口、Claude 会话状态 |

---

## 待完成事项（优先级排序）

| 优先级 | 问题 | 位置 | 行动 |
|--------|------|------|------|
| 高 | FEISHU_WIKI_MEETING_PAGE 未配置 | agent 对话 | 在飞书新建「会议纪要汇总」页面，然后 `agent_config(set, FEISHU_WIKI_MEETING_PAGE, <token>)` |
| 中 | 钉钉文档内容读取 | 自动 | 首次调用 `read_meeting_doc` 时自动探测并写入 DINGTALK_WIKI_API_PATH |
| 低 | 飞书知识库语义搜索 | `integrations/feishu/knowledge.py` | 当前为关键词匹配 |

---

## 启动 / 重启

```bash
cd /root/ai-assistant
source .venv/bin/activate   # ⚠️ 必须激活 venv，否则缺包崩溃

# 后台运行（推荐，所有输出合并到 app.log）
nohup python main.py >> logs/app.log 2>&1 &

# 查看日志
tail -f logs/app.log

# 重启（改完代码后，用 PID 文件 kill）
kill $(cat logs/service.pid 2>/dev/null) 2>/dev/null
source .venv/bin/activate
nohup python main.py >> logs/app.log 2>&1 &

# 查看崩溃日志
tail -f logs/crash.log | python -m json.tool

# 查看 LLM 调用日志
tail -f logs/llm.jsonl | python -m json.tool

# 查看 Claude tmux 会话
tmux list-sessions | grep ai-claude
tmux attach -t ai-claude-{session_name}
```

---

## 自迭代规则（Claude Code 须知）

1. **先读此文件**，理解现有架构再动手
2. **最小改动原则**：只改需求涉及的文件
3. **新增工具**：在 `graph/tools.py` 加 `@tool` 函数，加入 `TOOL_CATEGORIES` 对应分类（同时更新 `CATEGORY_KEYWORDS`），更新本文件工具表
4. **新增平台集成**：在 `integrations/` 新建子目录，在 `main.py` 注册启动线程
5. **Claude Code 子进程**：必须 `unset ANTHROPIC_API_KEY`（wrapper script 中），使用 `--permission-mode acceptEdits`
6. **完成后必做（缺一不可）**：
   - ① 确认修改了哪些文件（用 `git diff --stat` 核查）
   - ② 做了什么、为什么（写入 commit message）
   - ③ 如何验证（运行测试或冒烟脚本）
   - ④ **更新文档**（涉及哪类变更就更新哪类文档）：
     - `CLAUDE.md` — **每次必更新**：状态表、版本变更历史（含修改文件列表）、工具表
     - `README.md` — **每次必更新**：功能列表、工具概览、启动步骤
     - `docs/architecture.md` — 新增/删除模块、改变数据流时更新架构图/说明
     - `docs/user_manual.md` — 新增/修改用户可见功能时更新操作指引（不存在则新建）
     - 文档更新不允许省略，即使改动很小
   - ⑤ **提交并推送**：`git add -A && git commit -m "feat/fix: 描述 (vX.Y.Z)" && git push`
     - commit message 格式：`类型: 一句话描述 (版本号)`
     - 类型：`feat`（新功能）/ `fix`（修复）/ `docs`（仅文档）/ `refactor`（重构）
     - **push 是强制步骤**，不允许只 commit 不 push
7. **重启方式**：`kill $(cat logs/service.pid 2>/dev/null) 2>/dev/null; source .venv/bin/activate && nohup python main.py >> logs/app.log 2>&1 &`

### 问题分类方法论

遇到 bug 或行为不符合预期时，先判断属于哪类再修复：

| 类别 | 判断标准 | 修复位置 |
|------|---------|---------|
| **代码问题** | API 调用失败、参数错误、Python 异常、超时、数据格式不对 | `integrations/`、`graph/tools.py`、`graph/nodes.py` |
| **提示词/技能问题** | LLM 理解错误、选错工具、参数填错、格式不符预期、行为歧义 | `prompts/system.md`、工具 docstring、`CATEGORY_KEYWORDS` |

- **代码问题**：加日志、修参数、做兼容处理、写回归测试
- **提示词问题**：更新 `prompts/system.md` 或工具描述，添加正例/反例，调整关键词路由
- **两类问题各有专属测试**：代码问题→单元/集成测试（`tests/regression/`）；提示词问题→手动场景测试 + 更新 system.md 后验证

---

## 关键配置（.env）

```
FEISHU_APP_ID=cli_a8fec6e8585d100d
FEISHU_WIKI_SPACE_ID=7618158120166034630
FEISHU_WIKI_CONTEXT_PAGE=FalZwGDOkiqpbQkeAjGc8jaznMd  # AI助理上下文快照页
FEISHU_WIKI_MEETING_PAGE=<待配置>                       # 会议纪要汇总页面 wiki token

VOLCENGINE_MODEL=ep-20260317143459-qtgqn
OPENROUTER_MODEL=anthropic/claude-sonnet-4-5

DINGTALK_DOCS_SPACE_ID=r9xmyYP7YK1w1mEO  # 钉钉知识库空间 ID

# FEISHU_USER_ACCESS_TOKEN / FEISHU_USER_REFRESH_TOKEN — 飞书用户 OAuth（可选，用于全文搜索）
# ANTHROPIC_API_KEY — 仅供 Claude Code CLI 在 Claude Code 界面内使用
# 不会传入 trigger_self_iteration 启动的子进程（子进程用 OAuth session）
```

---

## OpenClaw 参考资料

`larksuite-openclaw-lark-2026.3.15.tgz` 是飞书 OpenClaw 集成包，包含以下可参考的飞书 API 工具和技能：

| 模块 | 对应飞书 API | 扩展优先级 |
|------|------------|---------|
| `tools/oapi/bitable/` | 多维表格 CRUD（27 种字段类型） | 已接入 |
| `tools/oapi/calendar/` | 日历事件、日程、空闲查询 | 低 |
| `tools/oapi/task/` | 任务、子任务、任务列表 | 已接入 |
| `tools/oapi/chat/` | 群组管理 | 低 |
| `tools/oapi/drive/` | 云文档（非 wiki）读写 | 低 |
| `tools/oapi/search/` | 飞书全文搜索 | 已接入 |
| `skills/feishu-bitable/` | Bitable 使用技能 | 低 |
| `skills/feishu-calendar/` | 日历操作技能 | 低 |
| `skills/feishu-task/` | 任务管理技能 | 低 |

如需扩展飞书能力，从 tgz 中提取对应模块并适配为 Python `@tool` 函数。
