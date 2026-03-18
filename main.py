"""
AI 个人助理主入口。

启动内容：
1. 飞书长连接（WebSocket，lark-oapi SDK）
2. 钉钉流模式（dingtalk-stream SDK）
3. APScheduler 定时任务

无 HTTP 层，使用 supervised thread + 指数退避自动重启。
崩溃写入 logs/crash.log（JSONL）。
"""
import json
import logging
import os
import signal
import threading
import time
import traceback
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("main")

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_CRASH_LOG = os.path.join(_PROJECT_DIR, "logs", "crash.log")
_PID_FILE = os.path.join(_PROJECT_DIR, "logs", "service.pid")


def _write_crash_log(thread_name: str, exc: Exception) -> None:
    entry = {
        "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "thread": thread_name,
        "error": str(exc),
        "traceback": traceback.format_exc(),
    }
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as log_err:
        logger.error(f"写 crash.log 失败: {log_err}")


def _supervised(name: str, target, base_delay: int = 5, max_delay: int = 300):
    """返回一个 daemon thread，循环运行 target()，崩溃后指数退避重启。"""
    def _run():
        delay = base_delay
        while True:
            try:
                logger.info(f"[{name}] 启动")
                target()
                logger.warning(f"[{name}] 正常退出，{delay}s 后重启")
            except Exception as e:
                _write_crash_log(name, e)
                logger.error(f"[{name}] 崩溃: {e}，{delay}s 后重启", exc_info=True)
            time.sleep(delay)
            delay = min(delay * 2, max_delay)
    return threading.Thread(target=_run, daemon=True, name=name)


def _start_feishu():
    from integrations.feishu.bot import start_feishu_longconn
    start_feishu_longconn()


def _start_dingtalk():
    from integrations.dingtalk.bot import start_dingtalk_stream
    start_dingtalk_stream()


def _start_admin():
    from admin.server import start_admin_server
    start_admin_server()


def main():
    import scheduler as sched

    # 写 PID 文件
    try:
        os.makedirs(os.path.dirname(_PID_FILE), exist_ok=True)
        with open(_PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        logger.info(f"PID {os.getpid()} 写入 {_PID_FILE}")
    except Exception as e:
        logger.warning(f"写 PID 文件失败: {e}")

    threads = [
        _supervised("feishu-ws", _start_feishu),
        _supervised("dingtalk-stream", _start_dingtalk),
        _supervised("admin-http", _start_admin),
    ]
    for t in threads:
        t.start()

    sched.start()
    logger.info("AI 助理启动完成（无 HTTP 层）")

    # 优雅关闭
    _stop = threading.Event()

    def _shutdown(signum, frame):
        logger.info(f"收到信号 {signum}，准备关闭…")
        sched.stop()
        _stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    _stop.wait()
    logger.info("AI 助理已退出")


if __name__ == "__main__":
    main()
