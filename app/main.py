"""应用入口：只做组装。

挂静态资源、挂路由，其余都在 api/ 与 application/ 里。
`uvicorn app.main:app` 的启动路径保持不变，Dockerfile 与 Compose 无需改动。
"""

import anyio 
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import auth, chat, memory
from .config import STATIC_DIR

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 在这里设置，此时事件循环已在运行
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = 200          # 临时调大，仅用于诊断
    yield
    # 这里可以放关闭时的清理逻辑
app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(memory.router)


@app.get("/ping")
def read_ping():
    """健康检查：Docker HEALTHCHECK 每 30 秒打一次这个地址。"""
    return {"message": "pong"}


@app.get("/", include_in_schema=False)
def index_page():
    """根路径直接返回页面，访问域名即可，不用带 /static/index.html。"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/brain", include_in_schema=False)
def brain_page():
    """记忆大脑页：把长期记忆片段画成可点击的 3D 网络。"""
    return FileResponse(STATIC_DIR / "brain.html")
