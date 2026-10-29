"""对话路由：流式回复与历史分页。

流式接口只负责「把生成中的文字按 SSE 推回去」，
上下文怎么装配、什么时候切段，全部交给 application/chat_service.py。
"""

import threading

from fastapi import APIRouter, Depends, Header, HTTPException
from starlette.responses import StreamingResponse

from ..deps import get_current_user
from ..schemas import ChatRequest, HistoryResponse, HistoryRequest
from ...application.chat_service import Messages, update_state_after_reply
from ...config import CHAT_TEMPERATURE, DAILY_MESSAGE_LIMIT
from ...infrastructure.cache import check_rate_limit
from ...infrastructure.db import User
from ...infrastructure.llm import chat_stream

router = APIRouter()


@router.post("/history", response_model=HistoryResponse)
def get_chat_history(req: HistoryRequest, user: User = Depends(get_current_user)):
    """按 id 游标分页拉历史；不传 before_id 就是最新一页。"""
    m = Messages(user_id=user.id)
    return HistoryResponse(**m.history(before_id=req.before_id, limit=req.limit))


@router.post("/chat/stream")
def chat_stream_api(
    req: ChatRequest,
    api_key: str | None = Header(default=None, alias="X-API-Key"),
    user: User = Depends(get_current_user),
):
    """流式回复一条消息。

    先按当前这句话检索往事并装配 system，再把用户消息追加进上下文，
    然后边生成边推送；模型失败时把这条用户消息撤回，避免下一轮重复。
    """
    # 免费公网服务：单用户每天的消息额度，防止服务端 Key 被刷。
    # 用户自带的 Key 消耗的是自己的额度，所以不占用这里的限额。
    if not api_key and not check_rate_limit(f"user:{user.id}:daily", limit=DAILY_MESSAGE_LIMIT, window=86400):
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
                full += chunk[6:].rstrip("\n")

        if not full:
            m.messages.pop()
            yield "data: [ERROR] 调用模型失败\n\n"
            return

        m.messages.append({"id": None, "role": "assistant", "content": full})
        m.save_messages()
        # 回复流已结束，后台更新情绪状态，不阻塞本轮响应
        threading.Thread(
            target=update_state_after_reply,
            args=(user.id, user_message, full, api_key),
            daemon=True,
        ).start()

    return StreamingResponse(gen(), media_type="text/event-stream")
