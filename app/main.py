import threading
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from starlette.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .cache import check_rate_limit
from .config import STATIC_DIR, CHAT_TEMPERATURE, DAILY_MESSAGE_LIMIT
from .db import SessionLocal, User
from .schemas import ChatRequest, HistoryRequest, History, RegisterRequest, \
    RegisterResponse, LoginRequest, LoginResponse, ApiKeyTestResponse
from .security import hash_password,verify_password,create_access_token, get_current_user
from .llm import chat_stream, test_api_key
from .state import advance, load_state, save_state
from .storage import Messages

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _after_reply(user_id: int, user_message: str, reply: str, api_key=None):
    """回复结束后台更新情绪状态，不阻塞本轮响应。"""
    try:
        state = advance(load_state(user_id), user_message, reply, api_key=api_key)
        save_state(user_id, state)
    except Exception as e:
        print(f"后台状态更新失败: {e}")


def _warm_up(user_id: int):
    """登录后预热：最近消息与记忆向量写入 Redis，降低首轮延迟。"""
    try:
        Messages(user_id=user_id).warm_up()
    except Exception as e:
        print(f"预热失败: {e}")


def _client_ip(request: Request) -> str:
    """反向代理后取真实 IP；直连时回落到 socket 地址。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/ping")
def read_ping():
    return {"message": "pong"}


@app.get("/", include_in_schema=False)
def index_page():
    """根路径直接返回页面，访问域名即可，不用带 /static/index.html。"""
    return FileResponse(STATIC_DIR / "index.html")

@app.post("/register", response_model=RegisterResponse)
def register(req: RegisterRequest, request: Request):
    if not check_rate_limit(f"register:{_client_ip(request)}", limit=10, window=3600):
        raise HTTPException(status_code=429, detail="注册太频繁，请稍后再试")
    with SessionLocal() as db:
        result = db.execute(
            select(User).where(User.username == req.username)
        ).scalar_one_or_none()
        if result is not None:
            raise HTTPException(status_code=400, detail="用户名已存在")
        try:
            user = User(username=req.username, password_hash=hash_password(req.password))
            db.add(user)
            db.commit()
            db.refresh(user)
        except IntegrityError:
            raise HTTPException(status_code=400, detail="用户名已存在")
    return RegisterResponse(
        id=user.id,
        username=user.username
    )


@app.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request):
    if not check_rate_limit(f"login:{_client_ip(request)}", limit=30, window=60):
        raise HTTPException(status_code=429, detail="登录尝试太频繁，请稍后再试")
    with SessionLocal() as db:
        result = db.execute(
            select(User).where(User.username == req.username)
        ).scalar_one_or_none()
        if result is None:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not verify_password(req.password, result.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
            
        result_username = result.username

        access_token = create_access_token(result.id)

    threading.Thread(target=_warm_up, args=(result.id,), daemon=True).start()
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        username=result_username
    )


@app.post("/api-key/test", response_model=ApiKeyTestResponse)
def test_api_key_endpoint(
    api_key: str | None = Header(default=None, alias="X-API-Key"),
    user: User = Depends(get_current_user),
):
    """用传入的 API Key 打一个极小请求，校验 Key 是否可用。"""
    ok, message = test_api_key(api_key)
    return ApiKeyTestResponse(ok=ok, message=message)


@app.post("/history", response_model=History)
def get_chat_history(req: HistoryRequest, user: User = Depends(get_current_user)):
    """按 id 游标分页拉历史；不传 before_id 就是最新一页。"""
    m = Messages(user_id=user.id)
    return History(**m.history(before_id=req.before_id, limit=req.limit))


@app.post("/chat/stream")
def chat_stream_api(req: ChatRequest, api_key: str | None = Header(default=None, alias="X-API-Key"), user: User = Depends(get_current_user)):
    # 免费公网服务：单用户每天的消息额度，防止服务端 Key 被刷
    if not check_rate_limit(f"user:{user.id}:daily", limit=DAILY_MESSAGE_LIMIT, window=86400):
        raise HTTPException(status_code=429, detail="今天的消息额度用完了，明天再来找我吧")
    m = Messages(user_id=user.id)
    m.load_messages()

    user_message = req.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    m.messages.append({"id": None, "role": "user", "content": user_message})
    # 用当前这句话做检索 query，记忆槽每轮现场装配
    m.ensure_system(query=user_message)

    def gen():
        full = ""
        yield "data: [START]\n\n"
        for chunk in chat_stream(m.get_context(), api_key=api_key, temperature=CHAT_TEMPERATURE):
            yield chunk
            if chunk.startswith("data: [ERROR]"):
                m.messages.pop()
                return
            if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                content = chunk[6:].rstrip("\n")
                full += content
        if not full:
            m.messages.pop()
            yield "data: [ERROR] 调用模型失败\n\n"
            return
        if full:
            m.messages.append({"id": None,"role": "assistant", "content": full})
            m.save_messages()
            # 回复流已结束，后台更新情绪状态，不阻塞本轮响应
            threading.Thread(
                target=_after_reply,
                args=(user.id, user_message, full, api_key),
                daemon=True,
            ).start()


    return StreamingResponse(gen(), media_type="text/event-stream")