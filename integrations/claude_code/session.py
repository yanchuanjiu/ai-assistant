"""
Claude Code 交互会话管理器。

auto 模式（默认）：
  claude --print --dangerously-skip-permissions --output-format stream-json
  全自动执行，stream-json 流式输出实时推送到 IM。

交互模式（预留）：
  stdin 注入接口供用户通过 IM 回复 Claude。

reply_fn_registry：
  bot handler 在调用 agent 前注册 {thread_id: send_fn}，
  trigger_self_iteration 工具读取以获得 IM 回复能力。
"""
import json
import logging
import os
import subprocess
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ------------------------------------------------------------------ #
# 全局：thread_id → send_fn（由 bot handler 注册）
# ------------------------------------------------------------------ #
reply_fn_registry: dict[str, Callable[[str], None]] = {}

# ------------------------------------------------------------------ #
# 活跃会话表
# ------------------------------------------------------------------ #
_sessions: dict[str, "ClaudeCodeSession"] = {}
_sessions_lock = threading.Lock()


class ClaudeCodeSession:
    """管理一个 claude 子进程的 I/O。"""

    def __init__(self, thread_id: str, send_fn: Callable[[str], None]):
        self.thread_id = thread_id
        self.send_fn = send_fn
        self.proc: subprocess.Popen | None = None
        self._done = threading.Event()

    # ---------------------------------------------------------------- #
    # 启动：auto 流式模式
    # ---------------------------------------------------------------- #
    def start_streaming(self, requirement: str):
        """
        以 --print --dangerously-skip-permissions --output-format stream-json
        启动 Claude Code，后台线程解析 JSON 流并实时推送给 IM。
        """
        full_prompt = (
            f"你正在开发 /root/ai-assistant 项目（AI 个人助理）。\n"
            f"请根据以下需求进行开发，直到完成为止：\n\n"
            f"{requirement}\n\n"
            f"完成后输出：1) 修改了哪些文件  2) 做了什么  3) 如何验证"
        )
        self.proc = subprocess.Popen(
            [
                "claude",
                "--print",
                "--permission-mode", "acceptEdits",
                "--output-format", "stream-json",
                "--verbose",
                full_prompt,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=PROJECT_DIR,
            # 排除 ANTHROPIC_API_KEY，让 Claude Code 使用自身的 OAuth session token
            env={k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"},
        )
        threading.Thread(target=self._read_stream_json, daemon=True).start()
        threading.Thread(target=self._wait_done, daemon=True).start()
        logger.info(f"[ClaudeSession] {self.thread_id} started, pid={self.proc.pid}")

    # ---------------------------------------------------------------- #
    # 交互：stdin 注入（预留，供用户通过 IM 回复）
    # ---------------------------------------------------------------- #
    def relay_input(self, text: str):
        if self.proc and self.proc.stdin and not self.proc.stdin.closed:
            try:
                self.proc.stdin.write(text + "\n")
                self.proc.stdin.flush()
            except Exception as e:
                logger.warning(f"[ClaudeSession] relay_input 失败: {e}")

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def wait(self, timeout: float = None):
        self._done.wait(timeout)

    # ---------------------------------------------------------------- #
    # 内部：解析 stream-json 推送到 IM
    # ---------------------------------------------------------------- #
    def _read_stream_json(self):
        buf: list[str] = []
        last_flush = time.time()

        def flush():
            if buf:
                self.send_fn("\n\n".join(buf))
                buf.clear()

        try:
            for raw_line in self.proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    # 非 JSON 行直接透传（错误输出等）
                    if line:
                        buf.append(line)
                    continue

                event_type = obj.get("type", "")

                if event_type == "assistant":
                    for block in obj.get("message", {}).get("content", []):
                        if block.get("type") == "text":
                            text = block["text"].strip()
                            if text:
                                buf.append(text)

                elif event_type == "result":
                    flush()
                    result_text = obj.get("result", "")
                    duration_s = obj.get("duration_ms", 0) / 1000
                    cost = obj.get("total_cost_usd", 0)
                    summary = f"✅ 执行完成（{duration_s:.1f}s，${cost:.4f}）"
                    if result_text:
                        # 只取最后 500 字，避免刷屏
                        summary += f"\n\n{result_text[-500:]}"
                    self.send_fn(summary)
                    continue

                # 每 3 条或每 5 秒批量推送，减少消息轰炸
                if len(buf) >= 3 or (buf and time.time() - last_flush > 5):
                    flush()
                    last_flush = time.time()

        except Exception as e:
            logger.error(f"[ClaudeSession] 读取流失败: {e}")
        finally:
            flush()

    def _wait_done(self):
        if self.proc:
            self.proc.wait()
        self._done.set()
        with _sessions_lock:
            _sessions.pop(self.thread_id, None)
        logger.info(f"[ClaudeSession] {self.thread_id} 会话结束")


# ------------------------------------------------------------------ #
# SessionManager 单例
# ------------------------------------------------------------------ #
class SessionManager:
    def start(
        self,
        thread_id: str,
        requirement: str,
        send_fn: Callable[[str], None],
    ) -> ClaudeCodeSession:
        with _sessions_lock:
            old = _sessions.get(thread_id)
            if old and old.is_running():
                try:
                    old.proc.terminate()
                except Exception:
                    pass
            session = ClaudeCodeSession(thread_id, send_fn)
            _sessions[thread_id] = session
        session.start_streaming(requirement)
        return session

    def get(self, thread_id: str) -> ClaudeCodeSession | None:
        with _sessions_lock:
            s = _sessions.get(thread_id)
            return s if (s and s.is_running()) else None

    def relay_input(self, thread_id: str, text: str) -> bool:
        s = self.get(thread_id)
        if s:
            s.relay_input(text)
            return True
        return False


session_manager = SessionManager()
