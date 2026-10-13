import threading
from fastapi import FastAPI, HTTPException
from starlette.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR
from .db import SessionLocal, Session as SessionModel, User
from .schemas import ChatRequest, HistoryRequest, History, RenameResponse, RenameRequest, RegisterRequest, \
    RegisterResponse
from .security import hash_password
from .llm import chat, chat_stream
from .storage import Messages

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/ping")
def read_ping():
    return {"message": "pong"}

@app.post("/register", response_model=RegisterResponse)
def register(req: RegisterRequest):
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


@app.post("/history", response_model=History)
def get_chat_history(req: HistoryRequest):
    m = Messages(session_uuid=req.session_uuid)
    m.load_messages()
    return History(
        # 只返回前端需要的 role/content，剔除内部用的整数 id，避免类型校验失败
        history=[{"role": msg["role"], "content": msg["content"]} for msg in m.messages[1:]],
        session=m.name,
        session_uuid=m.session_uuid
    )


@app.get("/sessions")
def list_sessions():
    with SessionLocal() as db:
        sessions = db.execute(
            select(SessionModel).order_by(SessionModel.created_at.desc())
        ).scalars().all()
        return {
            "sessions": [
                {"uuid": s.uuid, "name": s.name} for s in sessions
            ]
        }


@app.post("/chat", response_model=RenameResponse)
def chat_api(req: RenameRequest):
    """智能重命名会话"""
    m = Messages(session_uuid=req.session_uuid)
    m.load_messages()
    if len(m.messages) <= 1:
        # 还没发过消息，跳过重命名
        return RenameResponse(session=m.name, session_uuid=m.session_uuid)

    system_prompt = [
        {"role": "system", "content": "请根据下面的用户消息生成一个会话名称，只返回会话名称，不要返回其他内容，13字以内，尽量不要跟用户的话一样"},
        m.messages[1]
    ]
    try:
        new_name = chat(system_prompt).strip().strip('"').strip("'")
        if len(new_name) > 20:
            new_name = new_name[:20]
        if new_name:
            m.rename(new_name)
    except Exception as e:
        print(f"重命名失败: {e}")

    return RenameResponse(session=m.name, session_uuid=m.session_uuid)


@app.post("/chat/stream")
def chat_stream_api(req: ChatRequest):
    session_uuid = req.session_uuid  # None 表示新会话

    m = Messages(session_uuid=session_uuid)
    m.load_messages()

    user_message = req.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    m.messages.append({"id": None,"role": "user", "content": user_message})

    # 确保 session 有 uuid
    if not m.session_uuid:
        m._get_or_create_session()

    current_uuid = m.session_uuid

    def gen():
        full = ""
        yield f"data: [START]{current_uuid}\n\n"
        for chunk in chat_stream(m.get_context()):
            yield chunk
            if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                if chunk.startswith("data: [ERROR]"):
                    m.messages.pop()
                    yield chunk
                    return
                content = chunk[6:].rstrip("\n")
                full += content
        if not full:
            m.messages.pop()
            yield "data: [ERROR] 调用模型失败\n\n"
            return
        if full:
            m.messages.append({"id": None,"role": "assistant", "content": full})
            m.save_messages()
            # 回复流已结束，后台无感压缩超限历史，不阻塞本轮响应
            threading.Thread(target=m.maybe_summarize, daemon=True).start()


    return StreamingResponse(gen(), media_type="text/event-stream")