import os
from fastapi import FastAPI, HTTPException
from starlette.responses import StreamingResponse

from schemas import ChatRequest, HistoryRequest, History, RenameResponse, RenameRequest
from llm import chat, chat_stream
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

@app.post("/chat", response_model=RenameResponse)
def chat_api(req: RenameRequest):
    session_name = req.session
    m1 = Messages(f"sessions/{session_name}.json")
    m1.load_messages()
    system_prompt = [
        {"role": "system", "content": "请根据下面的用户消息生成一个会话名称，只返回会话名称，不要返回其他内容，13字以内，尽量不要跟用户的话一样"},
        m1.messages[1]]
    name = chat(system_prompt)
    m1.rename(name)
    m1.save_messages()
    return RenameResponse(
        session=name
    )

@app.post("/chat/stream")
def chat_stream_api(req: ChatRequest):
    session_name = req.session
    if session_name is None:
        session_name = "新会话"
    m = Messages(f"sessions/{session_name}.json")
    m.load_messages()
    user_message = req.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    m.messages.append({"role": "user", "content": user_message})
    def gen():
        full = ""
        yield f"data: [START]{session_name}\n\n"  # 添加会话名标识
        for chunk in chat_stream(m.messages):
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
            m.messages.append({"role": "assistant", "content": full})
            m.save_messages()
    return StreamingResponse(gen(), media_type="text/event-stream")








