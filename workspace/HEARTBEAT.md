# HEARTBEAT.md — 心跳任务清单

每次心跳时，检查以下事项。如果没有需要处理的，回复 `HEARTBEAT_OK`，不要发消息给用户。

状态记录在 `workspace/heartbeat_state.json`，用于判断哪些检查到期了。

## 优先级 1：异常主动提醒

- 如果 `logs/crash.log` 存在且有新内容（上次心跳后），提醒用户
- 如果服务进程不在（`logs/service.pid` 对应进程已死），提醒用户

## 优先级 2：记忆维护（每天一次）

- 回顾 `logs/interactions.jsonl` 最近50条
- 提炼用户行为模式、偏好变化，更新 `workspace/MEMORY.md`
- 删除 MEMORY.md 中已过时的内容

## 优先级 3：自我改进检查（每3天一次）

- 统计近期用户纠正次数（`has_correction=true` 的比例）
- 如果纠正率 > 15%，或连续出现工具调用失败，触发 `trigger_self_improvement`

## 规则

- 深夜（23:00—07:00）不主动发消息给用户，除非是服务崩溃
- 同一件事不要在同一天内重复提醒
- 心跳本身的执行不需要告知用户，只在有实质内容时才发消息
