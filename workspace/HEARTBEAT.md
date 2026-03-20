# HEARTBEAT.md — 心跳任务清单

每次心跳时，检查以下事项。如果没有需要处理的，回复 `HEARTBEAT_OK`，不要发消息给用户。

状态记录在 `workspace/heartbeat_state.json`，用于判断哪些检查到期了。

## 优先级 1：异常主动提醒

- 如果 `logs/crash.log` 存在且有新内容（上次心跳后），提醒用户
- 如果服务进程不在（`logs/service.pid` 对应进程已死），提醒用户
- **已知稳定崩溃**：`admin-http` 线程因端口 8080 已占用会持续崩溃，这是已知问题，不需要每次都提醒（同一天内只提醒一次）

## 优先级 1.5：代码生效检查（每次心跳）

- 比较 `logs/service.pid` 对应进程的启动时间与最新 git commit 时间
  - 命令：`ps -p $(cat logs/service.pid) -o lstart=` vs `git log -1 --format="%ai"`
  - 若服务启动时间**早于**最新 commit，立即重启服务并通知用户
  - 重启命令：`kill $(cat logs/service.pid 2>/dev/null) 2>/dev/null; source /root/ai-assistant/.venv/bin/activate && nohup python /root/ai-assistant/main.py >> /root/ai-assistant/logs/app.log 2>&1 &`
- 这是高优先级检查：commit 后不重启等于修复无效，会导致用户重复遭遇已修复的 bug

## 优先级 2：记忆维护（每天一次）

**短期记忆（当日提炼）**：
- 回顾 `logs/interactions.jsonl` 最近 50 条
- 提炼当日用户行为模式、偏好变化、新任务背景，更新 `workspace/MEMORY.md` 的"用户行为模式"和"常用工作流"节
- 如果某个重复问题在最近 5 条记录中仍然出现，在 MEMORY.md "已知注意事项"中标注"⚠️ 未解决"

**长期记忆（每周压缩）**：
- 每 7 天对 MEMORY.md 做一次压缩：合并重复条目、删除超过 30 天无引用的内容、保留用户三大项目的核心背景
- 压缩后在"改进历史"节追加一条记录

**上下文健康检查**：
- 从 `logs/llm.jsonl` 检查最近 10 次调用的 input token 数
- 若有调用超过 30K tokens，说明该 thread 上下文过重，在心跳消息中提醒用户可发 `/clear` 重置
- v0.8.20 起历史 ToolMessage 截断至 300 字符，检查时若 avg input_tokens 仍 >50K，考虑进一步降低 HISTORY_TOOL_CONTENT_LIMIT

## 优先级 3：自我改进检查（每3天一次）

- 统计近期用户纠正次数（`has_correction=true` 的比例）
- 如果纠正率 > 15%，或连续出现工具调用失败，触发 `trigger_self_improvement`

## 优先级 4：项目进展跟踪（每周一次）

- 用户有三个核心项目，会议纪要会持续产生。每周检查一次是否有新的未处理钉钉会议文档（`list_processed_meetings`）
- 若发现 >3 篇未处理，主动告知用户并询问是否批量处理

## 规则

- 深夜（23:00—07:00）不主动发消息给用户，除非是服务崩溃
- 同一件事不要在同一天内重复提醒
- 心跳本身的执行不需要告知用户，只在有实质内容时才发消息
