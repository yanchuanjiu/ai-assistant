"""
LangGraph 主图：ReAct agent with SQLite checkpointing。

流程：START → agent → [tool_calls?] → tools → agent → ... → END
消息发送由各平台 bot 模块负责，图本身只负责推理和工具调用。
"""
import os
import sqlite3
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from graph.state import AgentState
from graph.nodes import agent_node, tools_node, should_continue
from graph.parallel import task_monitor, Priority

os.makedirs("data", exist_ok=True)

# 直接用 sqlite3 连接初始化，避免 from_conn_string 返回 context manager
_conn = sqlite3.connect("data/memory.db", check_same_thread=False)
checkpointer = SqliteSaver(_conn)


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)

    g.set_entry_point("agent")

    g.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end": END},
    )
    g.add_edge("tools", "agent")

    return g.compile(checkpointer=checkpointer)


graph = build_graph()


def clear_history(thread_id: str) -> bool:
    """清除指定 thread_id 的对话历史（删除 SQLite checkpoint）。"""
    try:
        _conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        _conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        _conn.commit()
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[clear_history] {e}")
        return False


def invoke(message: str, platform: str, user_id: str, chat_id: str,
           thread_id: str | None = None) -> str:
    """
    外部调用入口：传入用户消息，返回 AI 回复文本。
    消息发送由调用方（bot handler）负责。

    thread_id：可选，覆盖默认的 platform:chat_id。
                多话题场景传入话题专属 thread_id（含 #topic# 分隔符）以隔离对话历史。
    """
    import time
    import threading
    from integrations.logging.interaction_logger import log_interaction

    if thread_id is None:
        thread_id = f"{platform}:{chat_id}"

    # 按来源确定优先级（用户实时消息 > 定时调度任务）
    priority = (
        Priority.URGENT if platform not in ("heartbeat", "scheduler")
        else Priority.NORMAL
    )

    # 向任务监控注册本次调用
    task_id = f"{thread_id[:20]}@{int(time.time())}"
    task_monitor.register(task_id, f"invoke {platform}:{chat_id} — {message[:40]}", priority)
    task_monitor.mark_running(task_id)

    config = {"configurable": {"thread_id": thread_id}}
    state = {
        "messages": [HumanMessage(content=message)],
        "platform": platform,
        "user_id": user_id,
        "chat_id": chat_id,
        "thread_id": thread_id,
        "intent": None,
        "skill_result": None,
        "error": None,
    }

    t0 = time.monotonic()
    try:
        result = graph.invoke(state, config=config)
    except Exception as e:
        task_monitor.mark_done(task_id, error=str(e)[:200])
        raise
    latency_ms = (time.monotonic() - t0) * 1000

    last = result["messages"][-1]
    response_text = last.content if isinstance(last.content, str) else str(last.content)

    task_monitor.mark_done(task_id)

    # 收集本次调用的工具列表（去重保序）
    tools_used = []
    for msg in result["messages"]:
        for tc in getattr(msg, "tool_calls", None) or []:
            name = tc.get("name", "")
            if name and name not in tools_used:
                tools_used.append(name)

    log_interaction(
        platform=platform,
        user_id=user_id,
        chat_id=chat_id,
        user_message=message,
        agent_response=response_text,
        tools_used=tools_used,
        latency_ms=latency_ms,
    )

    # 回复含错误/异常关键词时，后台触发自动修复
    threading.Thread(
        target=_maybe_auto_fix,
        args=(response_text, thread_id, platform, chat_id, message),
        daemon=True,
    ).start()

    return response_text


def get_concurrent_status() -> dict:
    """
    返回当前并发任务状态快照，供工具 / Admin 界面查询。

    示例输出：
    {
        "running": [{"id": "abc123", "desc": "invoke feishu:oc_xxx — 帮我查...", ...}],
        "summary": {"running": 1, "done": 5, "failed": 0, "pending": 2},
        "recent": [...]
    }
    """
    from graph.parallel import get_task_queue
    queue_status = get_task_queue().status()
    return {
        "queue_size": queue_status["queue_size"],
        "running":    queue_status["running"],
        "summary":    queue_status["summary"],
        "recent":     task_monitor.get_recent(limit=10),
    }


def _maybe_auto_fix(response_text: str, thread_id: str, platform: str, chat_id: str, user_message: str):
    """
    检测回复中的错误关键词，按次数决定是自动修复还是通知用户并创建 GitHub issue。
    在后台线程中运行，不阻塞主流程。
    """
    try:
        import logging
        from integrations.logging.error_tracker import (
            detect_error_in_response, record_error, get_fix_status,
            create_github_issue, record_github_issue, MAX_AUTO_FIX_ATTEMPTS,
        )
        from integrations.claude_code.session import session_manager, reply_fn_registry

        logger_fix = logging.getLogger("auto_fix")

        pattern = detect_error_in_response(response_text)
        if not pattern:
            return

        # 跳过心跳/scheduler 平台
        if platform in ("heartbeat", "scheduler"):
            return

        count = record_error(pattern, response_text[:300], platform, chat_id)
        logger_fix.info(f"[AutoFix] 检测到错误模式（第{count}次）: {pattern[:60]}")

        send_fn = reply_fn_registry.get(thread_id)

        if count < MAX_AUTO_FIX_ATTEMPTS:
            # 触发 Claude Code 自动修复
            reason = (
                f"Agent 回复中出现错误（第{count}次，触发自动修复）。\n"
                f"用户问题: {user_message[:200]}\n"
                f"错误片段: {response_text[:300]}\n"
                f"错误模式: {pattern}"
            )
            requirement = _build_auto_fix_requirement(reason, pattern, response_text)
            logger_fix.info(f"[AutoFix] 启动第{count}次自动修复 thread={thread_id}")
            session_manager.start(thread_id + "-autofix", requirement, send_fn)
        else:
            # 达到上限：通知用户 + 创建 GitHub issue + 不再自动修复
            status = get_fix_status(pattern)
            issue_url = status.get("github_issue")

            if not issue_url:
                issue_url = create_github_issue(pattern, count, response_text[:300])
                if issue_url:
                    record_github_issue(pattern, issue_url)

            msg_parts = [
                f"⚠️ 检测到一个反复出现的错误（已自动修复 {MAX_AUTO_FIX_ATTEMPTS} 次，但问题仍存在）：\n",
                f"**错误模式**：{pattern[:100]}\n",
                f"**出现次数**：{count} 次\n",
                "需要您一起排查。请告诉我您看到的具体现象，我们一起分析。\n",
            ]
            if issue_url:
                msg_parts.append(f"📌 已创建 GitHub Issue 记录此问题：{issue_url}")

            if send_fn:
                send_fn("".join(msg_parts))
            else:
                logger_fix.warning(f"[AutoFix] 无法通知用户（send_fn 未找到），issue: {issue_url}")

    except Exception as e:
        import logging
        logging.getLogger("auto_fix").warning(f"[AutoFix] 执行出错: {e}", exc_info=True)


def _build_auto_fix_requirement(reason: str, pattern: str, response_snippet: str) -> str:
    """构建自动修复的 Claude Code 任务描述。"""
    return f"""你是这个 AI Agent 的自动修复系统。Agent 在回复用户时出现了错误，请立即分析并修复。

## 触发原因
{reason}

## 分析任务

### 1. 定位根因
- 查看 `logs/app.log` 最近50行，找与错误相关的 stack trace 或 warning
- 查看 `logs/crash.log`（如存在），识别崩溃模式
- 查看 `logs/interactions.jsonl` 中包含 "{pattern[:40]}" 的记录（最近5条）

### 2. 检查相关代码
- 根据错误内容，定位到可能出问题的 integrations/ 或 graph/ 文件
- 重点检查：API 调用参数、异常处理、网络超时配置

### 3. 修复
- 最小化改动，只修复确认有问题的代码
- 不要臆测，只改有证据支持的部分

### 4. 验证
- 如有回归测试，运行相关测试套件：`cd /root/ai-assistant && source .venv/bin/activate && python -m pytest tests/ -x -q 2>&1 | tail -20`
- 确认修复不引入新问题

### 5. 提交并重启
```bash
cd /root/ai-assistant
git add -A
git commit -m "fix: 自动修复 - {pattern[:40]}"
git push
kill $(cat logs/service.pid 2>/dev/null) 2>/dev/null; sleep 1
source .venv/bin/activate && nohup python main.py >> logs/app.log 2>&1 &
```

### 6. 报告
修复完成后，通过 IM 发送简短报告：修复了什么、改了哪个文件、如何验证。
如果分析后发现无法通过代码修复（如外部服务问题、配置缺失），请说明原因并给出建议。
"""
