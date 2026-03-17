"""
AI 个人助理主入口。
FastAPI 应用，挂载飞书 & 钉钉 Webhook，启动定时任务。
"""
import logging
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from integrations.feishu.bot import router as feishu_router
from integrations.dingtalk.bot import router as dingtalk_router
import scheduler as sched


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched.start()
    yield
    sched.stop()


app = FastAPI(title="AI Personal Assistant", lifespan=lifespan)
app.include_router(feishu_router)
app.include_router(dingtalk_router)


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
