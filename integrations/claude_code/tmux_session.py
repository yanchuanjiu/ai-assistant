"""
基于 tmux 的 Claude Code 会话管理器。

相比原 subprocess.Popen 方案的优势：
  - 会话持久化：Python 进程重启后 Claude 任务继续执行
  - 可随时 attach：`tmux attach -t {session_name}` 直接查看
  - 更可靠的输入注入：tmux send-keys
  - 并行多会话：每个 thread_id 对应独立 tmux session
  - 可被 list/kill/output 工具管理

命名规则：tmux session = "ai-claude-{safe_thread_id}"
日志文件：/tmp/ai-claude-{safe_thread_id}.jsonl
"""
import json
import logging
import os
import re
import subprocess
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SESSION_PREFIX = "ai-claude-"

# ------------------------------------------------------------------ #
# 全局：thread_id → send_fn（由 bot handler 注册）
# ------------------------------------------------------------------ #
reply_fn_registry: dict[str, Callable[[str], None]] = {}

# ------------------------------------------------------------------ #
# 活跃会话表
# ------------------------------------------------------------------ #
_sessions: dict[str, "TmuxClaudeSession"] = {}
_sessions_lock = threading.Lock()


def _safe_name(thread_id: str) -> str:
    """将 thread_id 转为 tmux 安全的 session 名称（最长 50 字符）。"""
    return SESSION_PREFIX + re.sub(r"[^a-zA-Z0-9_-]", "-", thread_id)[:40]


def _tmux(*args) -> tuple[int, str]:
    """运行 tmux 命令，返回 (returncode, stdout+stderr)。"""
    r = subprocess.run(["tmux"] + list(args), capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def list_active_sessions() -> list[dict]:
    """列出所有活跃的 ai-claude-* tmux 会话。"""
    rc, out = _tmux("list-sessions", "-F", "#{session_name}|#{session_created_string}")
    if rc != 0:
        return []
    sessions = []
    for line in out.splitlines():
        if not line.startswith(SESSION_PREFIX):
            continue
        parts = line.split("|", 1)
        name = parts[0]
        created = parts[1] if len(parts) > 1 else "?"
        # 还原 thread_id（第一个 - 替换回 :）
        raw = name[len(SESSION_PREFIX):]
        thread_id = raw.replace("-", ":", 1)
        # 查 Python 内存中是否有对应会话
        in_memory = thread_id in _sessions or raw in _sessions
        sessions.append({
            "session_name": name,
            "thread_id": thread_id,
            "created": created,
            "in_memory": in_memory,
        })
    return sessions


# ------------------------------------------------------------------ #
# TmuxClaudeSession
# ------------------------------------------------------------------ #
class TmuxClaudeSession:
    """管理一个 tmux + Claude Code 会话的完整生命周期。"""

    def __init__(self, thread_id: str, send_fn: Callable[[str], None]):
        self.thread_id = thread_id
        self.session_name = _safe_name(thread_id)
        self.send_fn = send_fn
        self.log_file = f"/tmp/{self.session_name}.jsonl"
        self.prompt_file = f"/tmp/{self.session_name}.prompt"
        self.script_file = f"/tmp/{self.session_name}.sh"
        self._stop = threading.Event()

    # ---------------------------------------------------------------- #
    # 启动：创建 tmux session，以 stream-json 模式运行 Claude Code
    # ---------------------------------------------------------------- #
    def start_streaming(self, requirement: str):
        full_prompt = (
            f"你正在开发 /root/ai-assistant 项目（AI 个人助理）。\n"
            f"请根据以下需求进行开发，直到完成为止：\n\n"
            f"{requirement}\n\n"
            f"完成后输出：1) 修改了哪些文件  2) 做了什么  3) 如何验证"
        )
        # 写 prompt 文件（避免 shell 转义问题）
        with open(self.prompt_file, "w", encoding="utf-8") as f:
            f.write(full_prompt)
        # 清空 log 文件
        open(self.log_file, "w").close()

        # 构建 wrapper script
        script = f"""#!/bin/bash
unset ANTHROPIC_API_KEY
PROMPT=$(cat '{self.prompt_file}')
claude --print \\
  --permission-mode acceptEdits \\
  --output-format stream-json \\
  --verbose \\
  "$PROMPT" >> '{self.log_file}' 2>&1
EXIT_CODE=$?
echo '{{"type":"_tmux_done","exit_code":'$EXIT_CODE'}}' >> '{self.log_file}'
"""
        with open(self.script_file, "w") as f:
            f.write(script)
        os.chmod(self.script_file, 0o755)

        # 关闭已有同名 session（忽略错误）
        _tmux("kill-session", "-t", self.session_name)
        time.sleep(0.2)

        # 创建新 detached tmux session
        rc, out = _tmux(
            "new-session", "-d",
            "-s", self.session_name,
            "-c", PROJECT_DIR,
            self.script_file,
        )
        if rc != 0:
            logger.error(f"[TmuxSession] 创建失败: {out}")
            self.send_fn(f"⚠️ tmux 会话创建失败: {out}")
            return

        logger.info(f"[TmuxSession] {self.session_name} 已启动")
        threading.Thread(target=self._tail_log, daemon=True).start()

    # ---------------------------------------------------------------- #
    # 输入注入（交互模式）
    # ---------------------------------------------------------------- #
    def relay_input(self, text: str):
        """向 tmux 会话发送按键输入。"""
        _tmux("send-keys", "-t", self.session_name, text, "Enter")

    # ---------------------------------------------------------------- #
    # 状态查询
    # ---------------------------------------------------------------- #
    def is_running(self) -> bool:
        rc, _ = _tmux("has-session", "-t", self.session_name)
        return rc == 0

    def get_recent_output(self, lines: int = 80) -> str:
        """获取 tmux 会话的最近屏幕内容（或 log 文件尾部）。"""
        rc, out = _tmux("capture-pane", "-t", self.session_name, "-p", f"-{lines}")
        if rc == 0 and out.strip():
            return out.strip()
        # fallback：读 log 文件
        try:
            with open(self.log_file, encoding="utf-8") as f:
                content = f.read().strip()
            return content[-3000:] if content else "（无输出）"
        except Exception:
            return "（会话已结束，无输出）"

    def kill(self):
        """强制终止会话。"""
        self._stop.set()
        _tmux("kill-session", "-t", self.session_name)
        with _sessions_lock:
            _sessions.pop(self.thread_id, None)

    # ---------------------------------------------------------------- #
    # 内部：tail log 文件，解析 stream-json，推送到 IM
    # ---------------------------------------------------------------- #
    def _tail_log(self):
        buf: list[str] = []
        last_flush = time.time()

        def flush():
            if buf:
                self.send_fn("\n\n".join(buf))
                buf.clear()

        # 等待 log 文件出现并有内容（最多 15 秒）
        for _ in range(30):
            if os.path.exists(self.log_file) and os.path.getsize(self.log_file) > 0:
                break
            time.sleep(0.5)

        try:
            with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                while not self._stop.is_set():
                    raw = f.readline()
                    if not raw:
                        time.sleep(0.3)
                        if not self.is_running():
                            flush()
                            break
                        continue
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
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
                            summary += f"\n\n{result_text[-500:]}"
                        self.send_fn(summary)

                    elif event_type == "_tmux_done":
                        exit_code = obj.get("exit_code", "?")
                        flush()
                        if exit_code != 0:
                            self.send_fn(f"⚠️ Claude Code 退出码：{exit_code}，可用 `get_claude_session_output` 查看详情")
                        break

                    # 每 3 条或 5 秒批量推送，减少消息刷屏
                    if len(buf) >= 3 or (buf and time.time() - last_flush > 5):
                        flush()
                        last_flush = time.time()

        except Exception as e:
            logger.error(f"[TmuxSession] tail_log 异常: {e}")
        finally:
            flush()
            with _sessions_lock:
                _sessions.pop(self.thread_id, None)
            logger.info(f"[TmuxSession] {self.session_name} 监控结束")


# ------------------------------------------------------------------ #
# SessionManager 单例
# ------------------------------------------------------------------ #
class SessionManager:
    def start(
        self,
        thread_id: str,
        requirement: str,
        send_fn: Callable[[str], None],
    ) -> TmuxClaudeSession:
        with _sessions_lock:
            old = _sessions.get(thread_id)
            if old and old.is_running():
                old._stop.set()
                _tmux("kill-session", "-t", old.session_name)
            session = TmuxClaudeSession(thread_id, send_fn)
            _sessions[thread_id] = session
        session.start_streaming(requirement)
        return session

    def get(self, thread_id: str) -> TmuxClaudeSession | None:
        with _sessions_lock:
            s = _sessions.get(thread_id)
        if s and s.is_running():
            return s
        return None

    def relay_input(self, thread_id: str, text: str) -> bool:
        s = self.get(thread_id)
        if s:
            s.relay_input(text)
            return True
        return False


session_manager = SessionManager()
