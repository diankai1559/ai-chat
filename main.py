from fastapi import FastAPI, HTTPException
from schemas import ChatRequest, ChatResponse
from llm import chat
from storage import Messages
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static",StaticFiles(directory="static"),name="static")
@app.get("/ping")
def read_ping():
    return {"message": "pong"}

@app.post("/chat", response_model=ChatResponse)
def chat_api(req: ChatRequest):
    m = Messages(f"sessions/{req.session}.json")
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
        session=req.session,
        message_count=len(m.messages)
    )




