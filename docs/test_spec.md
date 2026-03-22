# AI 个人助理 — 测试用例规范文档

> **版本**：v1.0.18
> **最后更新**：2026-03-23
> **基准文档**：`docs/functional_spec.md` v1.0.18
> **用途**：基于功能规格设计测试用例，覆盖全部 spec 功能点，不依赖代码实现细节

---

## 目录

1. [测试体系概述](#1-测试体系概述)
2. [命名规范](#2-命名规范)
3. [脚本结构规范](#3-脚本结构规范)
4. [TC-PROC — 进程管理层](#4-tc-proc--进程管理层)
5. [TC-AGENT — LangGraph Agent 层](#5-tc-agent--langgraph-agent-层)
6. [TC-TOOL-WIKI — 飞书知识库工具](#6-tc-tool-wiki--飞书知识库工具)
7. [TC-TOOL-ADV — 飞书高级工具](#7-tc-tool-adv--飞书高级工具)
8. [TC-TOOL-CORE — 核心系统工具](#8-tc-tool-core--核心系统工具)
9. [TC-TOOL-CLAUDE — Claude Code 工具](#9-tc-tool-claude--claude-code-工具)
10. [TC-TOOL-MEET — 钉钉会议工具](#10-tc-tool-meet--钉钉会议工具)
11. [TC-FEISHU — 飞书平台集成](#11-tc-feishu--飞书平台集成)
12. [TC-DINGTALK — 钉钉平台集成](#12-tc-dingtalk--钉钉平台集成)
13. [TC-TOPIC — 话题管理](#13-tc-topic--话题管理)
14. [TC-PERSIST — 持久化层](#14-tc-persist--持久化层)
15. [TC-SCHED — 定时任务调度](#15-tc-sched--定时任务调度)
16. [TC-MEETING — 会议纪要自动化](#16-tc-meeting--会议纪要自动化)
17. [TC-CLAUDE-SUB — Claude Code 子 Agent](#17-tc-claude-sub--claude-code-子-agent)
18. [TC-ERR — 错误处理与自修复](#18-tc-err--错误处理与自修复)
19. [TC-CFG — 配置管理](#19-tc-cfg--配置管理)
20. [TC-ADMIN — Admin 管理界面](#20-tc-admin--admin-管理界面)
21. [TC-SYNC — 上下文同步](#21-tc-sync--上下文同步)
22. [TC-CONC — 并发任务框架](#22-tc-conc--并发任务框架)
23. [测试优先级与运行策略](#23-测试优先级与运行策略)
24. [Mock 与真实 API 切换策略](#24-mock-与真实-api-切换策略)
25. [运行方式速查](#25-运行方式速查)
26. [CI/CD 集成](#26-cicd-集成)

---

## 1. 测试体系概述

### 1.1 测试分层

| 层次 | 目录 | 特征 | 运行频率 |
|------|------|------|---------|
| **单元测试** | `tests/unit/` | Mock 外部依赖，纯逻辑验证 | 每次 push |
| **集成测试** | `tests/integration/` | 真实 SQLite，Mock HTTP | 每次 PR |
| **端到端测试** | `tests/e2e/` | 真实服务（需配置密钥） | 每日定时 |
| **回归测试** | `tests/regression/` | 历史 Bug 防回归 | 每次 push |

### 1.2 覆盖目标

| 功能模块 | 规格章节 | 覆盖场景码 |
|---------|---------|----------|
| 进程管理 | §3 | TC-PROC |
| Agent 核心 | §4 | TC-AGENT |
| 飞书知识库工具 | §5.2 | TC-TOOL-WIKI |
| 飞书高级工具 | §5.3 | TC-TOOL-ADV |
| 核心系统工具 | §5.4 | TC-TOOL-CORE |
| Claude Code 工具 | §5.5 | TC-TOOL-CLAUDE |
| 钉钉 Pipeline | §5.6 | TC-TOOL-MEET |
| 飞书平台集成 | §6.1 | TC-FEISHU |
| 钉钉平台集成 | §6.2 | TC-DINGTALK |
| 话题管理 | §6.3 | TC-TOPIC |
| 持久化层 | §7 | TC-PERSIST |
| 定时任务 | §8 | TC-SCHED |
| 会议纪要 | §12 | TC-MEETING |
| Claude Code 子 Agent | §13 | TC-CLAUDE-SUB |
| 错误处理 | §14 | TC-ERR |
| 配置管理 | §15 | TC-CFG |
| Admin UI | §16 | TC-ADMIN |
| 上下文同步 | §17 | TC-SYNC |
| 并发框架 | §18 | TC-CONC |

---

## 2. 命名规范

### 2.1 文件命名

| 类型 | 规则 | 示例 |
|------|------|------|
| 测试文件 | `test_{模块名}.py` | `test_topic_routing.py` |
| 测试类 | `Test{模块}{子功能}` | `TestTopicRoutingCreation` |
| 测试方法 | `test_{动词}_{条件}` | `test_create_topic_with_hash_prefix` |
| Fixture | 名词或名词短语 | `mock_feishu_client`, `sqlite_db` |

### 2.2 用例 ID 规范

```
TC-{场景码}-{序号：两位}
```

| 场景码 | 对应功能 |
|--------|---------|
| `PROC` | 进程管理 |
| `AGENT` | LangGraph Agent |
| `TOOL-WIKI` | 飞书知识库工具 |
| `TOOL-ADV` | 飞书高级工具 |
| `TOOL-CORE` | 核心系统工具 |
| `TOOL-CLAUDE` | Claude Code 工具 |
| `TOOL-MEET` | 钉钉 Pipeline 工具 |
| `FEISHU` | 飞书平台集成 |
| `DINGTALK` | 钉钉平台集成 |
| `TOPIC` | 话题管理 |
| `PERSIST` | 持久化层 |
| `SCHED` | 定时任务调度 |
| `MEETING` | 会议纪要自动化 |
| `CLAUDE-SUB` | Claude Code 子 Agent |
| `ERR` | 错误处理 |
| `CFG` | 配置管理 |
| `ADMIN` | Admin UI |
| `SYNC` | 上下文同步 |
| `CONC` | 并发任务框架 |

---

## 3. 脚本结构规范

每个测试方法必须包含四节 docstring：

```python
def test_功能名称(self, fixture):
    """
    TC-XXX-YY：用例标题
    前置条件：描述运行此测试所需的数据/环境
    执行步骤：描述测试操作流程
    断言逻辑：描述如何判断通过/失败（含量化指标）
    """
    # 1. Arrange — 准备数据和 Mock
    ...
    # 2. Act — 执行被测逻辑
    ...
    # 3. Assert — 断言结果
    assert result == expected, f"期望 {expected}，实际 {result}"
```

---

## 4. TC-PROC — 进程管理层

> 规格依据：functional_spec.md §3

### TC-PROC-01：Supervised Thread 指数退避重启

```
优先级：P0 | 类型：单元测试
前置条件：mock target 函数，第一次抛出 RuntimeError
执行步骤：
  1. 调用 _supervised("test", failing_fn, base_delay=0.01)
  2. 等待 3 次失败
断言逻辑：
  - 延迟依次为 0.01s, 0.02s, 0.04s（指数翻倍）
  - 崩溃事件写入 logs/crash.log（JSONL 格式，含 time/thread/error/traceback）
```

### TC-PROC-02：PID 文件写入与读取

```
优先级：P1 | 类型：单元测试
前置条件：临时目录
执行步骤：启动时写入 logs/service.pid
断言逻辑：
  - 文件存在
  - 内容为当前进程 PID
  - 重启后 PID 更新
```

### TC-PROC-03：_cleanup_previous 幂等性

```
优先级：P1 | 类型：单元测试
前置条件：logs/service.pid 包含不存在的 PID
执行步骤：调用 _cleanup_previous() 两次
断言逻辑：两次调用均不抛出异常（幂等）
```

### TC-PROC-04：SIGTERM 优雅关闭

```
优先级：P1 | 类型：集成测试
前置条件：服务已启动
执行步骤：
  1. kill -TERM $(cat logs/service.pid)
  2. 等待 5 秒
断言逻辑：
  - 进程已退出（不残留）
  - logs/app.log 含 "shutdown" 日志
```

### TC-PROC-05：崩溃日志格式

```
优先级：P1 | 类型：单元测试
前置条件：构造一个抛出异常的 supervised thread
执行步骤：触发崩溃
断言逻辑：
  - crash.log 含 JSONL 记录
  - 记录含 time, thread, error, traceback 字段
```

---

## 5. TC-AGENT — LangGraph Agent 层

> 规格依据：functional_spec.md §4

### TC-AGENT-01：AgentState 字段完整性

```
优先级：P0 | 类型：单元测试
前置条件：构造 AgentState 字典
执行步骤：验证所有必填字段
断言逻辑：messages, platform, user_id, chat_id, thread_id 均存在且类型正确
```

### TC-AGENT-02：图结构 START→END 正常路径

```
优先级：P0 | 类型：集成测试（Mock LLM）
前置条件：Mock LLM 返回无 tool_calls 的 AIMessage
执行步骤：graph.invoke({messages: [HumanMessage("你好")]})
断言逻辑：
  - 返回最终状态
  - messages 末尾为 AIMessage（非 ToolMessage）
```

### TC-AGENT-03：图结构工具调用路径

```
优先级：P0 | 类型：集成测试（Mock LLM + Mock 工具）
前置条件：Mock LLM 第一次返回含 tool_calls，第二次返回纯文本
执行步骤：graph.invoke(...)
断言逻辑：
  - messages 包含 AIMessage（含 tool_calls） → ToolMessage → AIMessage（最终）
  - 路径经过 tools_node
```

### TC-AGENT-04：MAX_TOOL_ITERATIONS=15 强制终止

```
优先级：P0 | 类型：集成测试（Mock LLM）
前置条件：Mock LLM 始终返回含 tool_calls 的 AIMessage
执行步骤：graph.invoke(...)
断言逻辑：
  - 迭代次数达到 15 次后强制终止
  - 最终 AIMessage 含 "超过上限" 提示
  - 不无限循环
```

### TC-AGENT-05：渐进式工具披露 — 短消息只返回 CORE_TOOLS

```
优先级：P1 | 类型：单元测试
前置条件：消息 "你好" (< 25 字符，无关键词)
执行步骤：调用 _select_tools_for_context(messages)
断言逻辑：返回工具集合大小 == 9（CORE_TOOLS 数量）
```

### TC-AGENT-06：渐进式工具披露 — 飞书关键词注入 feishu_wiki

```
优先级：P1 | 类型：单元测试
前置条件：消息含 "飞书知识库"
执行步骤：调用 _select_tools_for_context(messages)
断言逻辑：
  - 返回工具集合包含 feishu_read_page, feishu_wiki_page
  - 大小 > 9
```

### TC-AGENT-07：渐进式工具披露 — 工具连续性保持

```
优先级：P2 | 类型：单元测试
前置条件：最近 10 条消息中曾调用 feishu_bitable_record（无飞书关键词）
执行步骤：当前消息无关键词，调用 _select_tools_for_context(messages)
断言逻辑：返回工具集合包含 feishu_bitable_record（历史连续性）
```

### TC-AGENT-08：system prompt 动态构建 — 始终注入

```
优先级：P1 | 类型：单元测试
前置条件：构造最短有效消息
执行步骤：调用 _build_system_prompt(state)
断言逻辑：返回字符串包含 SOUL.md、USER.md、MEMORY_CORE.md 内容关键字
```

### TC-AGENT-09：system prompt 动态构建 — 条件注入

```
优先级：P1 | 类型：单元测试
前置条件：消息含项目管理关键词
执行步骤：调用 _build_system_prompt(state)
断言逻辑：返回字符串包含 SKILLS_PROJECT_MGMT.md 内容关键字
```

### TC-AGENT-10：LLM 日志写入 llm.jsonl

```
优先级：P1 | 类型：集成测试
前置条件：Mock LLM，临时 logs/ 目录
执行步骤：执行一次 agent_node
断言逻辑：
  - logs/llm.jsonl 含新记录
  - 记录包含 timestamp, model, latency_ms, input_tokens, output_tokens 字段
```

### TC-AGENT-11：Hook 机制 — volcengine 文本格式工具调用解析

```
优先级：P0 | 类型：单元测试
前置条件：无
执行步骤：
  对以下三种变体调用 volcengine_text_tool_call_hook：
  - "<|FunctionCallBegin|>[{\"name\": \"web_search\", \"args\": {}}]<|FunctionCallEnd|>"
  - "<|FunctionCallBeginBegin|>[...]<|FunctionCallEndEnd|>"
  - "[{\"name\": \"web_search\", \"args\": {}}]<|FunctionCallEnd|>"
断言逻辑：三种变体均成功解析为标准 tool_calls 结构
```

### TC-AGENT-12：_check_user_interaction_needed 检测重复工具调用

```
优先级：P1 | 类型：单元测试
前置条件：构造连续 3 次相同工具调用的 messages
执行步骤：调用 _check_user_interaction_needed(messages)
断言逻辑：返回 True（需要用户交互）
```

### TC-AGENT-13：LLM 主备切换（OpenRouter fallback）

```
优先级：P1 | 类型：单元测试（Mock）
前置条件：Mock 主 LLM 抛出连接错误
执行步骤：执行 agent_node
断言逻辑：
  - 调用切换到备用 LLM（OpenRouter）
  - 最终返回有效 AIMessage
```

---

## 6. TC-TOOL-WIKI — 飞书知识库工具

> 规格依据：functional_spec.md §5.2

### TC-TOOL-WIKI-01：feishu_read_page — URL 输入解析

```
优先级：P0 | 类型：单元测试（Mock API）
前置条件：Mock feishu_call 返回 obj_token
执行步骤：feishu_read_page("https://xxx.feishu.cn/wiki/AbCdEfG")
断言逻辑：
  - 成功提取 token "AbCdEfG"
  - 返回页面文本内容（非空）
```

### TC-TOOL-WIKI-02：feishu_read_page — obj_type=sheet 路由

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock wiki_token_to_obj_token 返回 obj_type="sheet"
执行步骤：feishu_read_page("some_token")
断言逻辑：返回字符串包含 "feishu_spreadsheet" 提示
```

### TC-TOOL-WIKI-03：feishu_read_page — obj_type=bitable 路由

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock wiki_token_to_obj_token 返回 obj_type="bitable"
执行步骤：feishu_read_page("some_token")
断言逻辑：返回字符串包含 "feishu_bitable_record" 提示
```

### TC-TOOL-WIKI-04：feishu_append_to_page — 成功追加

```
优先级：P0 | 类型：单元测试（Mock API）
前置条件：Mock API 返回成功
执行步骤：feishu_append_to_page("token", "新内容")
断言逻辑：
  - 返回包含确认信息
  - 返回包含页面链接 URL
```

### TC-TOOL-WIKI-05：feishu_overwrite_page — 成功覆盖

```
优先级：P0 | 类型：单元测试（Mock API）
前置条件：Mock API 返回成功
执行步骤：feishu_overwrite_page("token", "新内容")
断言逻辑：
  - 返回包含确认信息
  - 返回包含页面链接 URL
```

### TC-TOOL-WIKI-06：feishu_search_wiki — 返回结果

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock 搜索 API 返回 2 条结果
执行步骤：feishu_search_wiki("项目进展")
断言逻辑：返回包含 2 条摘要，每条含标题和摘要文本
```

### TC-TOOL-WIKI-07：feishu_search_wiki — 无结果

```
优先级：P2 | 类型：单元测试（Mock API）
前置条件：Mock 搜索 API 返回空列表
执行步骤：feishu_search_wiki("不存在的内容xyz")
断言逻辑：返回"未找到相关内容"提示（不抛出异常）
```

### TC-TOOL-WIKI-08：feishu_wiki_page action=list_children 分页

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock API 第一次返回 has_more=True，第二次返回 has_more=False
执行步骤：feishu_wiki_page("list_children", wiki_token="root_token")
断言逻辑：返回所有分页结果合并后的子页面列表
```

### TC-TOOL-WIKI-09：feishu_wiki_page action=find_or_create — 已存在时不重复创建

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock list_children 返回含目标标题的页面
执行步骤：feishu_wiki_page("find_or_create", parent_token="p", title="已有页面")
断言逻辑：
  - 不调用 create API
  - 返回已存在页面的 token
```

### TC-TOOL-WIKI-10：feishu_wiki_delete — 成功删除

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock DELETE API 返回 200
执行步骤：feishu_wiki_delete("valid_node_token")
断言逻辑：返回成功确认信息
```

### TC-TOOL-WIKI-11：@feishu_tool 装饰器 — WikiPermissionError (131006)

```
优先级：P0 | 类型：单元测试
前置条件：Mock feishu_call 抛出 WikiPermissionError
执行步骤：调用任意被 @feishu_tool 装饰的工具
断言逻辑：
  - 返回包含三种解决方案的提示文字（不抛出异常）
  - 调用了 notify_owner_reauth()（通知用户）
```

### TC-TOOL-WIKI-12：@feishu_tool 装饰器 — UserTokenExpiredError

```
优先级：P0 | 类型：单元测试
前置条件：Mock feishu_call 抛出 UserTokenExpiredError
执行步骤：调用任意被 @feishu_tool 装饰的工具
断言逻辑：
  - 返回包含重新授权提示的字符串（不抛出异常）
  - 调用了 IM 通知函数
```

---

## 7. TC-TOOL-ADV — 飞书高级工具

> 规格依据：functional_spec.md §5.3

### TC-TOOL-ADV-01：feishu_bitable_record action=list — 带过滤条件

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock Bitable list API 返回 3 条记录
执行步骤：feishu_bitable_record("list", app_token="t", table_id="tb", filter="状态 = '进行中'")
断言逻辑：返回 3 条记录，包含字段名和值
```

### TC-TOOL-ADV-02：feishu_bitable_record action=batch_create

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock batch create API
执行步骤：feishu_bitable_record("batch_create", app_token="t", table_id="tb", records=[{...}, {...}])
断言逻辑：返回新创建记录的 ID 列表
```

### TC-TOOL-ADV-03：feishu_bitable_meta — 返回字段列表

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock meta API 返回 5 个字段定义
执行步骤：feishu_bitable_meta(app_token="t", table_id="tb")
断言逻辑：返回包含字段名、类型的结构化信息
```

### TC-TOOL-ADV-04：feishu_spreadsheet action=read_values — A1 记号法

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock spreadsheet read API
执行步骤：feishu_spreadsheet("read_values", spreadsheet_token="t", range_="Sheet1!A1:C5")
断言逻辑：返回 5 行 3 列的二维数据
```

### TC-TOOL-ADV-05：feishu_spreadsheet action=append_values

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock append API
执行步骤：feishu_spreadsheet("append_values", spreadsheet_token="t", range_="Sheet1!A:C", values=[[1,2,3]])
断言逻辑：调用了 append API，返回确认信息
```

### TC-TOOL-ADV-06：feishu_calendar_event action=get_free_busy

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：Mock free_busy API
执行步骤：feishu_calendar_event("get_free_busy", start_time="2026-03-24T09:00", end_time="2026-03-24T18:00")
断言逻辑：返回忙闲时间段列表
```

### TC-TOOL-ADV-07：feishu_chat_info action=list_chats

```
优先级：P2 | 类型：单元测试（Mock API）
前置条件：Mock list chats API 返回 3 个群组
执行步骤：feishu_chat_info("list_chats")
断言逻辑：返回 3 个群组名称和 chat_id
```

### TC-TOOL-ADV-08：excel_import action=parse — 合并单元格处理

```
优先级：P1 | 类型：单元测试
前置条件：提供含合并单元格的 .xlsx 文件
执行步骤：excel_import("parse", file="test.xlsx")
断言逻辑：合并单元格内容正确扩展到各行（不丢失数据）
```

### TC-TOOL-ADV-09：manage_topics action=list

```
优先级：P1 | 类型：集成测试（真实 SQLite）
前置条件：chat_topics 表中预插入 3 条话题记录
执行步骤：manage_topics("list", chat_id="oc_xxx")
断言逻辑：返回 3 条话题，含 topic_name 和 thread_id
```

### TC-TOOL-ADV-10：manage_topics action=delete — 清除三处记录

```
优先级：P0 | 类型：集成测试（真实 SQLite）
前置条件：chat_topics、feishu_anchors、checkpoints 均有该话题记录
执行步骤：manage_topics("delete", chat_id="oc_xxx", topic_name="项目A")
断言逻辑：
  - chat_topics 中该话题记录已删除
  - feishu_anchors 中相关记录已删除
  - checkpoints 中该 thread_id 记录已删除
```

---

## 8. TC-TOOL-CORE — 核心系统工具

> 规格依据：functional_spec.md §5.4

### TC-TOOL-CORE-01：agent_config set/get 优先级

```
优先级：P0 | 类型：集成测试（真实 SQLite）
前置条件：.env 含 TEST_KEY=env_value；SQLite 无该 key
执行步骤：
  1. agent_config("get", "TEST_KEY") → 期望 "env_value"
  2. agent_config("set", "TEST_KEY", "db_value")
  3. agent_config("get", "TEST_KEY") → 期望 "db_value"
断言逻辑：SQLite 值覆盖 .env 值
```

### TC-TOOL-CORE-02：agent_config topics 动作

```
优先级：P1 | 类型：集成测试（真实 SQLite）
前置条件：chat_topics 表有 2 条记录
执行步骤：在 tool_ctx 中设置 chat_id，调用 agent_config("topics")
断言逻辑：返回当前 chat 的话题列表（含 thread_id）
```

### TC-TOOL-CORE-03：agent_config sessions 动作

```
优先级：P1 | 类型：集成测试（真实 SQLite）
前置条件：checkpoints 表有 2 个不同 thread_id 的记录
执行步骤：调用 agent_config("sessions")
断言逻辑：返回活跃会话摘要列表
```

### TC-TOOL-CORE-04：python_execute — 正常执行

```
优先级：P0 | 类型：单元测试
前置条件：无
执行步骤：python_execute("print(1+1)")
断言逻辑：返回包含 "2"
```

### TC-TOOL-CORE-05：python_execute — 超时保护

```
优先级：P1 | 类型：单元测试
前置条件：无
执行步骤：python_execute("import time; time.sleep(60)")
断言逻辑：在 35 秒内返回超时错误信息（不无限挂起）
```

### TC-TOOL-CORE-06：run_command — 正常执行

```
优先级：P0 | 类型：单元测试
前置条件：无
执行步骤：run_command("echo hello")
断言逻辑：返回含 "hello"，退出码 0
```

### TC-TOOL-CORE-07：get_service_status — 结构完整

```
优先级：P1 | 类型：单元测试
前置条件：无
执行步骤：get_service_status()
断言逻辑：返回包含 版本、运行时间、线程数、活跃话题数 字段
```

### TC-TOOL-CORE-08：get_recent_chat_context — 返回最近消息

```
优先级：P1 | 类型：集成测试（真实 SQLite）
前置条件：checkpoints 中有 5 条历史消息
执行步骤：在 tool_ctx 中设置 thread_id，调用 get_recent_chat_context(limit=3)
断言逻辑：返回最近 3 条消息摘要（不超过 limit）
```

### TC-TOOL-CORE-09：query_task_status — 任务监控信息

```
优先级：P2 | 类型：单元测试
前置条件：TaskMonitor 中有 2 个运行中任务
执行步骤：query_task_status(limit=5)
断言逻辑：返回包含运行中任务数量和队列大小信息
```

---

## 9. TC-TOOL-CLAUDE — Claude Code 工具

> 规格依据：functional_spec.md §5.5

### TC-TOOL-CLAUDE-01：trigger_self_iteration — 写入 prompt 文件

```
优先级：P0 | 类型：单元测试（Mock tmux）
前置条件：Mock tmux new-session 命令
执行步骤：trigger_self_iteration("修复消息去重 Bug")
断言逻辑：
  - /tmp/ai-claude-*.prompt 文件存在
  - 文件内容包含需求文字
```

### TC-TOOL-CLAUDE-02：trigger_self_iteration — wrapper script 含 unset

```
优先级：P0 | 类型：单元测试
前置条件：调用 trigger_self_iteration
执行步骤：检查生成的 wrapper script 内容
断言逻辑：脚本包含 "unset ANTHROPIC_API_KEY"
```

### TC-TOOL-CLAUDE-03：list_claude_sessions — 列出活跃会话

```
优先级：P1 | 类型：单元测试（Mock tmux）
前置条件：Mock tmux list-sessions 返回 2 个 ai-claude-* 会话
执行步骤：list_claude_sessions()
断言逻辑：返回 2 个会话信息
```

### TC-TOOL-CLAUDE-04：kill_claude_session — 终止会话

```
优先级：P1 | 类型：单元测试（Mock tmux）
前置条件：Mock tmux kill-session
执行步骤：kill_claude_session("thread_id_abc")
断言逻辑：调用了 tmux kill-session -t ai-claude-thread-id-abc
```

### TC-TOOL-CLAUDE-05：send_claude_input — 中继输入

```
优先级：P1 | 类型：单元测试（Mock tmux）
前置条件：Mock tmux send-keys
执行步骤：send_claude_input("thread_id_abc", "继续执行")
断言逻辑：调用了 tmux send-keys -t ai-claude-thread-id-abc "继续执行" Enter
```

---

## 10. TC-TOOL-MEET — 钉钉会议工具

> 规格依据：functional_spec.md §5.6

### TC-TOOL-MEET-01：get_latest_meeting_docs — MCP 优先降级

```
优先级：P1 | 类型：单元测试（Mock）
前置条件：Mock MCP list_nodes 抛出连接错误，Mock 直接 API 返回 3 个文档
执行步骤：get_latest_meeting_docs(limit=10)
断言逻辑：
  - 降级到直接 API
  - 返回 3 个文档信息
```

### TC-TOOL-MEET-02：analyze_meeting_doc — 非会议文档标记

```
优先级：P1 | 类型：集成测试（Mock LLM）
前置条件：Mock LLM 分析返回 {"is_meeting": false}
执行步骤：analyze_meeting_doc("doc_001")
断言逻辑：
  - data/meeting.db 中 doc_001 状态为 "not_meeting"
  - 不调用飞书写入 API
```

### TC-TOOL-MEET-03：analyze_meeting_doc — 已处理文档跳过

```
优先级：P0 | 类型：集成测试（真实 SQLite）
前置条件：data/meeting.db 中 doc_001 状态为 "processed"
执行步骤：analyze_meeting_doc("doc_001")
断言逻辑：
  - 不调用 LLM（跳过）
  - 返回"已处理"提示
```

### TC-TOOL-MEET-04：analyze_meeting_doc force=True — 强制重新分析

```
优先级：P2 | 类型：集成测试（Mock LLM）
前置条件：data/meeting.db 中 doc_001 状态为 "processed"
执行步骤：analyze_meeting_doc("doc_001", force=True)
断言逻辑：调用了 LLM（强制重新分析）
```

### TC-TOOL-MEET-05：list_processed_meetings — 返回记录

```
优先级：P2 | 类型：集成测试（真实 SQLite）
前置条件：meeting.db 中预插入 5 条记录
执行步骤：list_processed_meetings(limit=3)
断言逻辑：返回最近 3 条记录（按时间倒序）
```

---

## 11. TC-FEISHU — 飞书平台集成

> 规格依据：functional_spec.md §6.1

### TC-FEISHU-01：消息去重 — 同 message_id 2 分钟内不重复处理

```
优先级：P0 | 类型：单元测试
前置条件：初始化 FeishuBotHandler
执行步骤：
  1. 触发消息处理（message_id="msg_001"）
  2. 1 分钟后再次触发相同 message_id
断言逻辑：第二次处理被去重跳过（Agent 未被调用）
```

### TC-FEISHU-02：消息类型解析 — text

```
优先级：P0 | 类型：单元测试
前置条件：构造 feishu 文本消息事件
执行步骤：_parse_feishu_message(event)
断言逻辑：返回 MessageContext.text 为消息内容
```

### TC-FEISHU-03：消息类型解析 — post 富文本

```
优先级：P1 | 类型：单元测试
前置条件：构造 post 类型消息（含多段文本）
执行步骤：_parse_feishu_message(event)
断言逻辑：返回所有 text 标签内容拼接后的字符串
```

### TC-FEISHU-04：消息类型解析 — merge_forward 合并转发

```
优先级：P1 | 类型：单元测试（Mock API）
前置条件：构造 merge_forward 消息，Mock 获取子消息 API
执行步骤：_parse_feishu_message(event)
断言逻辑：返回所有子消息文本合并结果
```

### TC-FEISHU-05：消息类型解析 — image/file 非文本不静默丢弃

```
优先级：P1 | 类型：单元测试
前置条件：构造 image 类型消息
执行步骤：_parse_feishu_message(event)
断言逻辑：返回 "收到图片" 提示文字（不返回空，不抛异常）
```

### TC-FEISHU-06：线程路由 — feishu_anchors 反向映射

```
优先级：P0 | 类型：集成测试（真实 SQLite）
前置条件：feishu_anchors 中注册 msg_001 → thread_id_a
执行步骤：用户在 msg_001 的线程中回复（root_id=msg_001）
断言逻辑：路由到 thread_id_a 对应的话题上下文
```

### TC-FEISHU-07：线程路由 — 未知 root_id 回退主聊天

```
优先级：P1 | 类型：单元测试
前置条件：feishu_anchors 中无该 root_id
执行步骤：消息含未知 root_id
断言逻辑：路由到主聊天 thread_id（不孤立）
```

### TC-FEISHU-08：线程路由 — 启动时重建内存映射

```
优先级：P1 | 类型：集成测试（真实 SQLite）
前置条件：feishu_anchors 表有 3 条记录（7天内）
执行步骤：调用 _rebuild_anchor_map()（模拟重启）
断言逻辑：_thread_anchor 和 _anchor_to_thread 内存映射正确重建
```

### TC-FEISHU-09：Token 续期 — 并发不重复刷新

```
优先级：P0 | 类型：单元测试（Mock API）
前置条件：Mock refresh token API 只能成功一次
执行步骤：5 个线程同时调用 get_user_access_token()
断言逻辑：refresh token API 只被调用一次（threading.Lock 双重检查有效）
```

### TC-FEISHU-10：Token 续期 — 失败不降级 tenant token

```
优先级：P0 | 类型：单元测试（Mock API）
前置条件：Mock refresh token API 返回 20024（refresh token 无效）
执行步骤：调用 get_user_access_token()
断言逻辑：抛出 UserTokenExpiredError，不降级为 tenant token
```

### TC-FEISHU-11：feishu_call 统一入口 — Token 过期自动重试

```
优先级：P0 | 类型：单元测试（Mock API）
前置条件：Mock API 第一次返回 99991677，第二次返回成功
执行步骤：调用 feishu_call(path, as_="user")
断言逻辑：
  - 自动刷新 token 并重试一次
  - 最终返回成功响应
```

### TC-FEISHU-12：每话题串行锁 — 同话题串行不乱序

```
优先级：P0 | 类型：集成测试
前置条件：同一 thread_id 并发 2 条消息
执行步骤：并发触发 2 条消息处理
断言逻辑：第二条消息等待第一条处理完成后才开始（顺序确定）
```

### TC-FEISHU-13：不同话题可并行处理

```
优先级：P1 | 类型：集成测试（Mock LLM）
前置条件：同一 chat_id 的两个不同话题
执行步骤：并发触发两个不同话题的消息
断言逻辑：两条消息同时处理（不互相等待）
```

### TC-FEISHU-14：斜杠命令 /clear 清除上下文

```
优先级：P1 | 类型：集成测试（真实 SQLite）
前置条件：thread_id 有历史消息
执行步骤：发送 "/clear" 消息
断言逻辑：
  - checkpoints 中该 thread_id 记录已清除
  - 返回确认消息
```

### TC-FEISHU-15：斜杠命令 /topics 列出会话

```
优先级：P1 | 类型：集成测试（真实 SQLite）
前置条件：chat_topics 表有 2 条记录
执行步骤：发送 "/topics" 消息
断言逻辑：返回 2 个话题列表（含话题名和最后活跃时间）
```

### TC-FEISHU-16：纯问候快速路径不调用 LLM

```
优先级：P1 | 类型：单元测试（Mock LLM）
前置条件：无
执行步骤：发送 "你好"、"Hi"、"早上好" 等纯问候词
断言逻辑：LLM 未被调用，直接返回问候回复
```

---

## 12. TC-DINGTALK — 钉钉平台集成

> 规格依据：functional_spec.md §6.2

### TC-DINGTALK-01：MarkdownCard 消息格式发送

```
优先级：P0 | 类型：单元测试（Mock API）
前置条件：Mock 钉钉 Card API
执行步骤：dingtalk_bot.send_reply(ctx, "**测试内容**")
断言逻辑：调用 MarkdownCard API（非 Webhook），消息格式为 Markdown
```

### TC-DINGTALK-02：5 秒回调超时优化

```
优先级：P1 | 类型：单元测试（Mock）
前置条件：Mock Agent 执行时间 > 5 秒
执行步骤：触发消息处理
断言逻辑：5 秒内返回初始 MarkdownCard（"处理中"），完成后更新
```

### TC-DINGTALK-03：斜杠命令 /status

```
优先级：P1 | 类型：单元测试（Mock）
前置条件：Mock get_service_status
执行步骤：发送 "/status"
断言逻辑：返回服务状态信息（不调用 Agent）
```

---

## 13. TC-TOPIC — 话题管理

> 规格依据：functional_spec.md §6.3

### TC-TOPIC-01：#话题名 前缀提取

```
优先级：P0 | 类型：单元测试
前置条件：无
执行步骤：extract_topic("#产品规划 帮我看看这个方案")
断言逻辑：返回 topic_name="产品规划"，text="帮我看看这个方案"
```

### TC-TOPIC-02：新话题 前缀提取

```
优先级：P1 | 类型：单元测试
前置条件：无
执行步骤：extract_topic("新话题：竞品分析")
断言逻辑：返回 topic_name="竞品分析"
```

### TC-TOPIC-03：主窗口短标题（< 10 字）视为话题名

```
优先级：P1 | 类型：单元测试
前置条件：无
执行步骤：extract_topic("竞品分析")（7 字，非问候词）
断言逻辑：返回 topic_name="竞品分析"
```

### TC-TOPIC-04：主窗口短标题 — 相近话题检测

```
优先级：P1 | 类型：集成测试（真实 SQLite）
前置条件：chat_topics 中已有 "竞品分析" 话题
执行步骤：主窗口发送 "竞品" (< 10 字)
断言逻辑：
  - find_similar_topics 检测到 "竞品分析" 为相近话题
  - 返回合并确认提示（不直接创建新话题）
```

### TC-TOPIC-05：相近话题字符集重叠 ≥ 60% 判定

```
优先级：P1 | 类型：单元测试
前置条件：无
执行步骤：find_similar_topics("竞品分", existing=["竞品分析", "项目管理"])
断言逻辑：
  - "竞品分析" 被判定为相近（重叠率 > 60%）
  - "项目管理" 不被判定为相近
```

### TC-TOPIC-06：话题持久化 — 重启后不丢失

```
优先级：P0 | 类型：集成测试（真实 SQLite）
前置条件：chat_topics 中已有 "项目A" 话题记录
执行步骤：
  1. 重新加载 topic_manager（模拟重启）
  2. 查询 "项目A" 话题
断言逻辑：话题记录和 thread_id 与重启前一致
```

### TC-TOPIC-07：话题 thread_id 格式

```
优先级：P1 | 类型：单元测试
前置条件：无
执行步骤：make_topic_thread_id("feishu", "oc_abc", "项目A")
断言逻辑：格式符合 "feishu:oc_abc#topic#项目A" 规范（或 URL-safe 编码）
```

### TC-TOPIC-08：单 chat 最多 20 个话题限制

```
优先级：P2 | 类型：集成测试（真实 SQLite）
前置条件：某 chat 已有 20 个话题
执行步骤：尝试创建第 21 个话题
断言逻辑：返回超出上限的提示，不创建新话题
```

---

## 14. TC-PERSIST — 持久化层

> 规格依据：functional_spec.md §7

### TC-PERSIST-01：checkpoints WAL 模式

```
优先级：P1 | 类型：单元测试
前置条件：data/memory.db 已创建
执行步骤：查询 PRAGMA journal_mode
断言逻辑：返回 "wal"
```

### TC-PERSIST-02：checkpoints — 同 thread_id 对话历史隔离

```
优先级：P0 | 类型：集成测试（真实 SQLite）
前置条件：无
执行步骤：
  1. thread_id_a 写入消息 "A对话"
  2. thread_id_b 写入消息 "B对话"
  3. 分别读取两者历史
断言逻辑：各自历史独立，互不干扰
```

### TC-PERSIST-03：feishu_anchors 7 天 TTL 清理

```
优先级：P1 | 类型：单元测试（真实 SQLite）
前置条件：feishu_anchors 中插入 8 天前的记录
执行步骤：调用 TTL 清理逻辑（模拟启动）
断言逻辑：8 天前的记录被删除，7 天内记录保留
```

### TC-PERSIST-04：meeting_docs INSERT OR IGNORE 去重

```
优先级：P0 | 类型：集成测试（真实 SQLite）
前置条件：data/meeting.db 已有 doc_001
执行步骤：INSERT OR IGNORE doc_001 第二次
断言逻辑：无报错，记录数量仍为 1
```

### TC-PERSIST-05：agent_config SQLite 优先级 > .env

```
优先级：P0 | 类型：集成测试（真实 SQLite）
前置条件：.env KEY=env_val，SQLite KEY=db_val
执行步骤：读取 KEY
断言逻辑：返回 "db_val"（SQLite 优先）
```

---

## 15. TC-SCHED — 定时任务调度

> 规格依据：functional_spec.md §8

### TC-SCHED-01：heartbeat 夜间静默（23:00–07:00）

```
优先级：P1 | 类型：单元测试（Mock datetime）
前置条件：Mock 当前时间为 01:30
执行步骤：调用 heartbeat()
断言逻辑：跳过执行（不触发 Agent，不推送消息）
```

### TC-SCHED-02：heartbeat 工作时间 — HEARTBEAT.md 有任务时触发

```
优先级：P1 | 类型：单元测试（Mock Agent）
前置条件：
  - Mock 时间为 10:00
  - HEARTBEAT.md 含待处理任务
执行步骤：调用 heartbeat()
断言逻辑：触发 Agent 处理并调用推送函数
```

### TC-SCHED-03：poll_dingtalk_meetings — 新文档处理

```
优先级：P0 | 类型：集成测试（Mock DingTalk + Mock LLM）
前置条件：Mock 钉钉 API 返回 1 个新文档，Mock LLM 分析返回 is_meeting=true
执行步骤：调用 poll_dingtalk_meetings()
断言逻辑：
  - 调用 LLM 分析
  - 调用飞书写入 API
  - meeting.db 状态为 "processed"
```

### TC-SCHED-04：poll_dingtalk_meetings — 已处理文档跳过

```
优先级：P0 | 类型：集成测试（真实 SQLite + Mock）
前置条件：meeting.db 中文档已标记 "processed"
执行步骤：调用 poll_dingtalk_meetings()（该文档出现在列表中）
断言逻辑：不调用 LLM，不调用飞书 API
```

### TC-SCHED-05：daily_migration — 每日 08:00 触发格式

```
优先级：P2 | 类型：单元测试（Mock APScheduler）
前置条件：APScheduler 已配置
执行步骤：检查 daily_migration job 配置
断言逻辑：trigger 类型为 cron，hour=8，minute=0，时区 Asia/Shanghai
```

### TC-SCHED-06：sync_context — 写入飞书上下文页

```
优先级：P1 | 类型：集成测试（Mock 飞书 API）
前置条件：Mock feishu_overwrite_page
执行步骤：调用 sync_context()
断言逻辑：
  - 调用了 feishu_overwrite_page（覆盖模式）
  - 写入内容包含活跃话题列表
```

---

## 16. TC-MEETING — 会议纪要自动化

> 规格依据：functional_spec.md §12

### TC-MEETING-01：LLM 分析输出结构完整性

```
优先级：P0 | 类型：单元测试（Mock LLM）
前置条件：Mock LLM 返回完整 JSON
执行步骤：analyzer.analyze("会议内容...", "2026-03-23会议")
断言逻辑：
  返回 dict 含 is_meeting, title, date, participants, decisions, action_items, raid
  所有字段类型正确
```

### TC-MEETING-02：分析返回 is_meeting=false 时不写飞书

```
优先级：P0 | 类型：单元测试（Mock LLM + Mock 飞书）
前置条件：Mock LLM 返回 {"is_meeting": false}
执行步骤：完整调用 analyze_meeting_doc
断言逻辑：飞书 API 未被调用
```

### TC-MEETING-03：项目路由 — 关键词匹配识别项目

```
优先级：P1 | 类型：单元测试
前置条件：Mock 项目配置含 "VOC" 项目
执行步骤：project_router.route_meeting({"title": "VOC分析周例会"})
断言逻辑：路由到 VOC 项目文件夹，不是全局汇总页
```

### TC-MEETING-04：RAID 提取 — action_items 写入多维表格

```
优先级：P1 | 类型：单元测试（Mock Bitable）
前置条件：Mock feishu_bitable_record API
执行步骤：analyzer.write_raid_rows(analysis_result)
断言逻辑：调用 feishu_bitable_record("batch_create") 写入 RAID 记录
```

### TC-MEETING-05：内容截断 — 超 6000 字符的文档

```
优先级：P1 | 类型：单元测试
前置条件：构造 8000 字符的文档内容
执行步骤：read_meeting_doc + 传入 analyzer.analyze
断言逻辑：传入 LLM 的内容不超过 6000 字符
```

### TC-MEETING-06：每日迁移 — 格式化输出

```
优先级：P2 | 类型：单元测试（Mock 飞书）
前置条件：meeting.db 有前一天的 3 条 processed 记录
执行步骤：trigger_daily_migration()
断言逻辑：
  - 调用 feishu_append_to_page 向历史页追加内容
  - 追加内容包含 3 条会议标题
```

---

## 17. TC-CLAUDE-SUB — Claude Code 子 Agent

> 规格依据：functional_spec.md §13

### TC-CLAUDE-SUB-01：wrapper script 不含 ANTHROPIC_API_KEY

```
优先级：P0 | 类型：单元测试
前置条件：调用 trigger_self_iteration("测试需求")
执行步骤：读取生成的 wrapper script 文件
断言逻辑：
  - 包含 "unset ANTHROPIC_API_KEY"（必须在行首或命令中）
  - 不包含 ANTHROPIC_API_KEY 的赋值
```

### TC-CLAUDE-SUB-02：tmux 会话名格式

```
优先级：P1 | 类型：单元测试（Mock tmux）
前置条件：thread_id = "feishu:oc_abc/test"
执行步骤：触发 trigger_self_iteration
断言逻辑：
  - tmux new-session 命令中会话名为 "ai-claude-feishu-oc-abc-test"
  - 特殊字符替换为 "-"
```

### TC-CLAUDE-SUB-03：会话存活检测

```
优先级：P1 | 类型：单元测试（Mock tmux）
前置条件：Mock tmux has-session 返回 0（会话存在）
执行步骤：session.is_alive()
断言逻辑：返回 True
```

### TC-CLAUDE-SUB-04：stream-json 输出推送 IM

```
优先级：P1 | 类型：单元测试（Mock send_fn）
前置条件：Mock .jsonl 文件写入 stream-json 格式数据
执行步骤：启动 tail 线程解析
断言逻辑：send_fn 被调用，参数为解析后的文本内容
```

### TC-CLAUDE-SUB-05：用户输入中继

```
优先级：P1 | 类型：单元测试（Mock tmux）
前置条件：活跃 Claude 会话存在
执行步骤：relay_input("继续执行下一步")
断言逻辑：调用 tmux send-keys 命令，参数含输入文字
```

---

## 18. TC-ERR — 错误处理与自修复

> 规格依据：functional_spec.md §14

### TC-ERR-01：飞书 token 过期自动刷新

```
优先级：P0 | 类型：单元测试（Mock）
前置条件：见 TC-FEISHU-11
执行步骤：同 TC-FEISHU-11
断言逻辑：同 TC-FEISHU-11
```

### TC-ERR-02：错误误报过滤 — 分析性语境不触发自修复

```
优先级：P1 | 类型：单元测试
前置条件：无
执行步骤：解析含 "分析错误率" 的 LLM 响应
断言逻辑：不触发自动修复流程
```

### TC-ERR-03：自动修复限制 — 同错误超 3 次停止

```
优先级：P1 | 类型：单元测试（Mock auto_fix_tracker）
前置条件：auto_fix_tracker.json 中某错误 count=3
执行步骤：再次触发该错误
断言逻辑：
  - 不再触发 trigger_self_improvement
  - 通知用户停止自动修复
```

### TC-ERR-04：trigger_self_improvement — 日志分析结构

```
优先级：P1 | 类型：单元测试（Mock logs）
前置条件：构造 20 条 interactions.jsonl 记录（含错误和正常）
执行步骤：trigger_self_improvement("测试分析")
断言逻辑：
  - 返回包含 纠错率、响应延迟、工具分布 的分析报告
```

### TC-ERR-05：死循环防御 — 三层协同

```
优先级：P0 | 类型：集成测试（Mock LLM 持续返回 tool_calls）
前置条件：Mock LLM 持续返回 tool_calls
执行步骤：invoke agent（不注入 system.md 权限规则）
断言逻辑：在 MAX_TOOL_ITERATIONS=15 次后强制终止
```

---

## 19. TC-CFG — 配置管理

> 规格依据：functional_spec.md §15

### TC-CFG-01：运行时配置无需重启生效

```
优先级：P0 | 类型：集成测试（真实 SQLite）
前置条件：服务运行中
执行步骤：
  1. agent_config("set", "OWNER_FEISHU_CHAT_ID", "oc_new")
  2. 等待 1 秒（无重启）
  3. agent_config("get", "OWNER_FEISHU_CHAT_ID")
断言逻辑：返回 "oc_new"（无需重启）
```

### TC-CFG-02：必选环境变量缺失时启动失败

```
优先级：P1 | 类型：单元测试
前置条件：Mock os.environ 缺少 FEISHU_APP_ID
执行步骤：尝试启动
断言逻辑：抛出配置错误，明确提示缺少哪个变量
```

### TC-CFG-03：workspace 文件修改实时生效

```
优先级：P1 | 类型：单元测试
前置条件：SOUL.md 原内容
执行步骤：
  1. 修改 workspace/SOUL.md（追加一行唯一文字）
  2. 下次调用 _build_system_prompt()
断言逻辑：system prompt 包含新追加的文字（无需重启）
```

---

## 20. TC-ADMIN — Admin 管理界面

> 规格依据：functional_spec.md §16

### TC-ADMIN-01：GET /api/config — 列出所有配置

```
优先级：P1 | 类型：集成测试
前置条件：agent_config 表有 3 条记录
执行步骤：HTTP GET http://localhost:8080/api/config
断言逻辑：返回 JSON 列表，包含 3 条配置
```

### TC-ADMIN-02：POST /api/config — 写入配置

```
优先级：P1 | 类型：集成测试
前置条件：Admin 服务已启动
执行步骤：HTTP POST {"key": "TEST_CFG", "value": "hello"}
断言逻辑：
  - 返回 200
  - agent_config("get", "TEST_CFG") == "hello"
```

### TC-ADMIN-03：DELETE /api/config/{key} — 删除配置

```
优先级：P2 | 类型：集成测试
前置条件：agent_config 中存在 TEST_CFG
执行步骤：HTTP DELETE /api/config/TEST_CFG
断言逻辑：
  - 返回 200
  - TEST_CFG 不再存在
```

### TC-ADMIN-04：仅 localhost 可访问

```
优先级：P1 | 类型：单元测试
前置条件：Admin 服务已启动
执行步骤：从外部 IP 访问 :8080
断言逻辑：连接被拒绝（仅 localhost）
```

---

## 21. TC-SYNC — 上下文同步

> 规格依据：functional_spec.md §17

### TC-SYNC-01：context_sync — 生成快照内容

```
优先级：P1 | 类型：集成测试（Mock 飞书 API + 真实 SQLite）
前置条件：checkpoints 有 2 个活跃 thread_id
执行步骤：调用 ContextSync().push_to_feishu()
断言逻辑：
  - 调用 feishu_overwrite_page（覆盖模式）
  - 写入内容包含 2 个 thread_id 的摘要
  - 写入内容包含活跃话题统计
```

### TC-SYNC-02：context_sync — 飞书 API 失败不崩溃

```
优先级：P1 | 类型：单元测试（Mock）
前置条件：Mock feishu_overwrite_page 抛出异常
执行步骤：调用 push_to_feishu()
断言逻辑：不抛出异常，记录错误日志，任务继续运行
```

---

## 22. TC-CONC — 并发任务框架

> 规格依据：functional_spec.md §18

### TC-CONC-01：多工具并行执行顺序保持

```
优先级：P0 | 类型：单元测试（Mock 工具）
前置条件：构造含 3 个 tool_calls 的 AIMessage
执行步骤：run_tools_parallel(tool_calls, tools_map)
断言逻辑：
  - 返回 3 个 ToolMessage
  - 顺序与原 tool_calls 一致（按 tool_call_id 对应）
```

### TC-CONC-02：串行工具 feishu_overwrite_page 不并发执行

```
优先级：P1 | 类型：单元测试（Mock 工具）
前置条件：构造含 2 个 feishu_overwrite_page 调用的 AIMessage
执行步骤：run_tools_parallel(tool_calls, tools_map)
断言逻辑：两次调用串行执行（第二次等待第一次完成）
```

### TC-CONC-03：TaskMonitor 任务状态追踪

```
优先级：P1 | 类型：单元测试
前置条件：无
执行步骤：
  1. 创建任务 "task_001"（pending）
  2. 更新状态为 running
  3. 更新状态为 done
断言逻辑：每步查询均返回正确状态
```

### TC-CONC-04：工具执行线程上下文传播

```
优先级：P1 | 类型：单元测试
前置条件：set_tool_ctx(thread_id="th_001", send_fn=mock_fn)
执行步骤：在工具执行线程中读取 _tool_ctx
断言逻辑：thread_id 和 send_fn 正确传播（thread-local 隔离）
```

---

## 23. 测试优先级与运行策略

### 23.1 优先级定义

| 优先级 | 含义 | 失败处理 |
|-------|------|---------|
| `P0` | 核心路径，阻塞发布 | 必须修复后才能合并 |
| `P1` | 重要场景 | 失败触发告警，48h 内修复 |
| `P2` | 边界/降级场景 | 记录 warning，下版本修复 |

### 23.2 各层运行时机

| 触发条件 | 运行测试集 | 预期时间 |
|---------|----------|---------|
| 每次 git push | P0 单元测试 + 回归测试 | < 5 min |
| Pull Request | P0+P1 单元+集成测试 | < 15 min |
| 每日凌晨 02:00 | 全量测试（含 P2） | < 30 min |
| 手动触发 | 指定场景码 | 按需 |

### 23.3 Pytest Markers

```ini
[pytest]
markers =
    smoke:       冒烟测试，核心路径，每次 push 必跑
    unit:        纯单元测试，无外部依赖
    integration: 需要 SQLite 或 Mock HTTP
    e2e:         需要真实 API 密钥（默认跳过）
    regression:  历史 Bug 防回归
    feishu:      飞书相关测试
    dingtalk:    钉钉相关测试
    topic:       话题管理相关
    agent:       Agent 核心逻辑
    tools:       工具系统
    meeting:     会议纪要流水线
    claude_sub:  Claude Code 子 Agent
```

---

## 24. Mock 与真实 API 切换策略

```python
# 所有外部 HTTP 调用通过 fixture 决定是否 Mock
@pytest.fixture(scope="session")
def use_real_feishu_api():
    """设置 USE_REAL_FEISHU=1 使用真实 API"""
    if os.getenv("USE_REAL_FEISHU") != "1":
        pytest.skip("需要配置 USE_REAL_FEISHU=1 才运行真实 API 测试")

# Mock 示例
@pytest.fixture
def mock_feishu_call(mocker):
    return mocker.patch("integrations.feishu.client.feishu_call")

# 临时 SQLite
@pytest.fixture
def tmp_sqlite(tmp_path):
    db_path = tmp_path / "test_memory.db"
    # 初始化表结构
    ...
    return str(db_path)
```

**Mock 原则**：
- 单元测试必须 Mock 所有 HTTP 调用
- 集成测试使用真实 SQLite（临时目录）
- E2E 测试使用真实 API（CI 中跳过，手动运行）

---

## 25. 运行方式速查

```bash
# 激活 venv
cd /root/ai-assistant
source .venv/bin/activate

# 运行所有 smoke 测试（< 5min）
pytest tests/ -m "smoke" -v

# 运行所有单元测试
pytest tests/unit/ -v

# 运行特定场景码
pytest tests/ -k "TOPIC" -v

# 运行 Agent 相关测试
pytest tests/ -m "agent" -v

# 运行飞书集成测试
pytest tests/ -m "feishu" -v

# 跳过需要真实 API 的测试
pytest tests/ -m "not e2e" -v

# 生成覆盖率报告
pytest tests/ --cov=graph --cov=integrations --cov-report=html

# 运行回归测试
pytest tests/regression/ -v
```

---

## 26. CI/CD 集成

**文件**：`.github/workflows/test.yml`

| Job | 触发条件 | 运行集 | 耗时目标 |
|-----|---------|--------|---------|
| `smoke` | 每次 push | P0 smoke 标签 | < 5 min |
| `integration` | PR + main merge | P0+P1 unit+integration | < 15 min |
| `full-regression` | 每日 02:00 UTC | 全量（含 P2，跳过 e2e） | < 30 min |
| `notify-failure` | 任意 job 失败 | - | < 1 min |

**报告**：
- JUnit XML → GitHub Actions Artifacts
- 覆盖率报告 → Codecov（可选）

---

*本文档基于 functional_spec.md v1.0.18 编写，2026-03-23*
*新增功能后同步更新测试用例，确保 spec 和 test 双向追踪。*
