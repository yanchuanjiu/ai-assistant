"""
并发任务框架：优先级队列 + 并行工具执行 + 任务状态监控。

核心组件：
- TaskMonitor     : 线程安全的任务生命周期追踪（pending → running → done/failed）
- AgentTaskQueue  : 优先级任务队列，URGENT(0) > HIGH(1) > NORMAL(2) > LOW(3)
- run_tools_parallel : 并行执行同一轮 LLM 工具调用，含副作用工具串行保护
"""
import time
import uuid
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import IntEnum
from queue import PriorityQueue, Empty
from typing import Callable, Any

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# 优先级常量
# ------------------------------------------------------------------ #
class Priority(IntEnum):
    URGENT = 0   # 用户实时消息（飞书 / 钉钉）
    HIGH   = 1   # 高优先级后台任务
    NORMAL = 2   # 定时轮询（会议纪要、邮件）
    LOW    = 3   # 维护任务（心跳、同步、自改进）


# ------------------------------------------------------------------ #
# 任务状态监控
# ------------------------------------------------------------------ #
class _S:
    PENDING = "pending"
    RUNNING = "running"
    DONE    = "done"
    FAILED  = "failed"


class TaskMonitor:
    """线程安全的任务状态追踪器。

    支持 register / mark_running / mark_done，并提供 get_running / summary 查询。
    自动淘汰超出 max_history 的已完成条目。
    """

    def __init__(self, max_history: int = 200):
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}
        self._max_history = max_history

    # ---- 写操作 ----

    def register(self, task_id: str, description: str, priority: int) -> None:
        with self._lock:
            self._tasks[task_id] = {
                "id":          task_id,
                "desc":        description[:80],
                "priority":    priority,
                "status":      _S.PENDING,
                "created_at":  time.time(),
                "started_at":  None,
                "finished_at": None,
                "error":       None,
            }
            self._evict()

    def _evict(self) -> None:
        """内部：移除多余已完成条目（调用方须持锁）。"""
        if len(self._tasks) <= self._max_history:
            return
        done = sorted(
            [k for k, v in self._tasks.items()
             if v["status"] in (_S.DONE, _S.FAILED)],
            key=lambda k: self._tasks[k]["created_at"],
        )
        for k in done[: max(1, len(done) // 2)]:
            del self._tasks[k]

    def mark_running(self, task_id: str) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].update(
                    status=_S.RUNNING,
                    started_at=time.time(),
                )

    def mark_done(self, task_id: str, error: str | None = None) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].update(
                    status=_S.FAILED if error else _S.DONE,
                    finished_at=time.time(),
                    error=error,
                )

    # ---- 读操作 ----

    def get_running(self) -> list[dict]:
        with self._lock:
            return [
                t.copy() for t in self._tasks.values()
                if t["status"] == _S.RUNNING
            ]

    def get_recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            tasks = sorted(
                self._tasks.values(),
                key=lambda t: t["created_at"],
                reverse=True,
            )
            return [t.copy() for t in tasks[:limit]]

    def summary(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {}
            for t in self._tasks.values():
                counts[t["status"]] = counts.get(t["status"], 0) + 1
            return counts


# 全局实例（供整个进程共享）
task_monitor = TaskMonitor()


# ------------------------------------------------------------------ #
# 优先级任务队列
# ------------------------------------------------------------------ #
_seq_counter = 0
_seq_lock = threading.Lock()


def _next_seq() -> int:
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


@dataclass(order=True)
class _QueueItem:
    priority:  int
    seq:       int               # 同优先级内保持 FIFO
    task_id:   str  = field(compare=False)
    fn:        Any  = field(compare=False)
    args:      tuple = field(compare=False)
    kwargs:    dict  = field(compare=False)


class AgentTaskQueue:
    """
    优先级任务队列。

    - URGENT(0)：用户消息，立即抢占空闲 worker
    - NORMAL(2) / LOW(3)：定时任务，不抢占 URGENT 的 worker 位置

    使用方式：
        task_id = get_task_queue().submit(fn, arg1, arg2,
                                          priority=Priority.NORMAL,
                                          description="邮件轮询")
    """

    def __init__(self, max_workers: int = 4):
        self._queue: PriorityQueue[_QueueItem] = PriorityQueue()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="agent-worker",
        )
        self._running = True
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop,
            daemon=True,
            name="task-dispatcher",
        )
        self._dispatcher.start()
        logger.info(f"[TaskQueue] 已启动，max_workers={max_workers}")

    # ---- 提交 ----

    def submit(
        self,
        fn: Callable,
        *args,
        priority: int = Priority.NORMAL,
        description: str = "",
        **kwargs,
    ) -> str:
        """提交任务，立即返回 task_id（非阻塞）。"""
        task_id = uuid.uuid4().hex[:8]
        desc = description or getattr(fn, "__name__", "task")
        task_monitor.register(task_id, desc, priority)
        item = _QueueItem(
            priority=priority,
            seq=_next_seq(),
            task_id=task_id,
            fn=fn,
            args=args,
            kwargs=kwargs,
        )
        self._queue.put(item)
        logger.debug(f"[TaskQueue] 入队 {task_id} p={priority} {desc[:40]}")
        return task_id

    # ---- 内部调度 ----

    def _dispatch_loop(self) -> None:
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
                self._executor.submit(self._run, item)
            except Empty:
                pass
            except Exception as e:
                logger.error(f"[TaskQueue] dispatch 异常: {e}")

    def _run(self, item: _QueueItem) -> None:
        task_monitor.mark_running(item.task_id)
        fn_name = getattr(item.fn, "__name__", str(item.fn))
        logger.info(f"[TaskQueue] 开始执行 {item.task_id} p={item.priority} fn={fn_name}")
        try:
            item.fn(*item.args, **item.kwargs)
            task_monitor.mark_done(item.task_id)
            logger.debug(f"[TaskQueue] 完成 {item.task_id}")
        except Exception as e:
            task_monitor.mark_done(item.task_id, error=str(e)[:200])
            logger.error(f"[TaskQueue] {item.task_id} 执行失败: {e}", exc_info=True)

    # ---- 状态查询 ----

    def status(self) -> dict:
        return {
            "queue_size": self._queue.qsize(),
            "running":    task_monitor.get_running(),
            "summary":    task_monitor.summary(),
        }

    def shutdown(self) -> None:
        self._running = False
        self._executor.shutdown(wait=False)


# 延迟初始化的全局队列实例
_agent_task_queue: AgentTaskQueue | None = None
_queue_init_lock = threading.Lock()


def get_task_queue() -> AgentTaskQueue:
    """获取全局优先级任务队列（单例，线程安全初始化）。"""
    global _agent_task_queue
    if _agent_task_queue is None:
        with _queue_init_lock:
            if _agent_task_queue is None:
                _agent_task_queue = AgentTaskQueue(max_workers=4)
    return _agent_task_queue


# ------------------------------------------------------------------ #
# 并行工具执行
# ------------------------------------------------------------------ #

# 含有写副作用或顺序依赖的工具 → 整批串行执行（保守策略）
_SERIAL_TOOLS: frozenset[str] = frozenset({
    "trigger_self_iteration",
    "trigger_self_improvement",
    "trigger_daily_migration",
    "sync_context_to_feishu",
    "run_command",
    "feishu_overwrite_page",
    "feishu_append_to_page",
})

# 工具并行执行线程池（限制并发数，避免 API 限流）
_TOOL_EXECUTOR = ThreadPoolExecutor(
    max_workers=6,
    thread_name_prefix="tool-parallel",
)


def run_tools_parallel(
    calls: list[dict],
    thread_id: str,
    send_fn,
    tools_by_name: dict,
) -> list:
    """
    并行执行同一轮 LLM 下发的多个工具调用，保持原始顺序返回 ToolMessage 列表。

    策略：
    - 单个工具调用：同步执行，无额外线程开销
    - 含副作用工具（_SERIAL_TOOLS）：整批串行执行
    - 其余多工具：ThreadPoolExecutor 并行，as_completed 收集结果
    """
    from langchain_core.messages import ToolMessage

    if not calls:
        return []

    # 单工具快速路径
    if len(calls) == 1:
        _set_ctx(thread_id, send_fn)
        result = _invoke_tool(calls[0], tools_by_name)
        return [ToolMessage(content=str(result), tool_call_id=calls[0]["id"])]

    # 含副作用工具 → 串行
    if any(c.get("name") in _SERIAL_TOOLS for c in calls):
        logger.debug(f"[ToolSerial] 含副作用工具，串行执行 {[c['name'] for c in calls]}")
        _set_ctx(thread_id, send_fn)
        messages = []
        for call in calls:
            result = _invoke_tool(call, tools_by_name)
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
        return messages

    # 多工具并行
    logger.info(f"[ToolParallel] 并行执行 {len(calls)} 个工具: {[c['name'] for c in calls]}")
    t0 = time.monotonic()

    results: dict[str, str] = {}
    futures = {
        _TOOL_EXECUTOR.submit(_invoke_tool_in_thread, call, thread_id, send_fn, tools_by_name): call
        for call in calls
    }
    for future in as_completed(futures):
        call = futures[future]
        try:
            results[call["id"]] = str(future.result())
        except Exception as e:
            results[call["id"]] = f"工具执行出错：{e}"
            logger.error(f"[ToolParallel] {call['name']} 并行失败: {e}", exc_info=True)

    elapsed_ms = (time.monotonic() - t0) * 1000
    logger.info(f"[ToolParallel] {len(calls)} 个工具完成，耗时 {elapsed_ms:.0f}ms")

    # 按原始顺序返回
    return [
        ToolMessage(content=results[call["id"]], tool_call_id=call["id"])
        for call in calls
    ]


def _set_ctx(thread_id: str, send_fn) -> None:
    """设置当前线程的工具上下文（避免循环导入，局部 import）。"""
    from graph.nodes import set_tool_ctx
    set_tool_ctx(thread_id, send_fn)


def _invoke_tool_in_thread(call: dict, thread_id: str, send_fn, tools_by_name: dict) -> str:
    """在并行线程内设置工具上下文并执行工具。"""
    _set_ctx(thread_id, send_fn)
    return _invoke_tool(call, tools_by_name)


def _invoke_tool(call: dict, tools_by_name: dict) -> str:
    """执行单个工具调用，返回字符串结果。"""
    tool = tools_by_name.get(call["name"])
    if tool is None:
        return f"未找到工具：{call['name']}"
    try:
        return str(tool.invoke(call["args"]))
    except Exception as e:
        logger.error(f"[Tool] {call['name']} 执行失败: {e}", exc_info=True)
        return f"工具执行出错：{e}"
