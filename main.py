import os
import time
from fastapi import FastAPI, HTTPException
from schemas import ChatRequest, ChatResponse, HistoryRequest, History
from llm import chat
from storage import Messages
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static",StaticFiles(directory="static"),name="static")
@app.get("/ping")
def read_ping():
    return {"message": "pong"}

@app.post("/history", response_model=History)
def get_chat_history(req: HistoryRequest):
    m = Messages(f"sessions/{req.session}.json")
    m.load_messages()
    return History(
        history=m.messages[1:],
        session=req.session
    )

@app.get("/sessions")
def list_sessions():
    if not os.path.exists("sessions"):
        return {"sessions": []}
    sessions = [f[:-5] for f in os.listdir("sessions") if f.endswith(".json")]
    sessions = sorted(sessions, key=lambda x: os.path.getmtime(f"sessions/{x}.json"), reverse=True)
    return {"sessions": sessions}

@app.post("/chat", response_model=ChatResponse)
def chat_api(req: ChatRequest):
    session_name = req.session
    if session_name is None:
        session_name = f"chat_{int(time.time())}"
    m = Messages(f"sessions/{session_name}.json")
    m.load_messages()
    user_message = req.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    m.messages.append({"role": "user", "content": user_message})
    reply = chat(m.messages)
    if reply is None:
        m.messages.pop()
        raise HTTPException(status_code=502, detail="调用模型失败")

    m.messages.append({"role": "assistant", "content": reply})
    m.save_messages()

    return ChatResponse(
        reply=reply,
        session=session_name,
        message_count=len(m.messages)
    )




