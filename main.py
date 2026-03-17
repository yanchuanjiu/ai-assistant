"""
AI 个人助理主入口。

启动内容：
1. 飞书长连接（WebSocket，lark-oapi SDK）
2. 钉钉流模式（dingtalk-stream SDK）
3. FastAPI（健康检查 + 未来扩展用）
4. APScheduler 定时任务
"""
import logging
import os
import threading
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from fastapi import FastAPI
import scheduler as sched


def _start_feishu():
    from integrations.feishu.bot import start_feishu_longconn
    try:
        start_feishu_longconn()
    except Exception as e:
        logging.getLogger("feishu").error(f"飞书长连接异常退出: {e}")


def _start_dingtalk():
    from integrations.dingtalk.bot import start_dingtalk_stream
    try:
        start_dingtalk_stream()
    except Exception as e:
        logging.getLogger("dingtalk").error(f"钉钉流模式异常退出: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 飞书长连接
    threading.Thread(target=_start_feishu, daemon=True, name="feishu-ws").start()
    # 钉钉流模式
    threading.Thread(target=_start_dingtalk, daemon=True, name="dingtalk-stream").start()
    # 定时任务
    sched.start()

    yield

    sched.stop()


app = FastAPI(title="AI Personal Assistant", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=False,
    )
