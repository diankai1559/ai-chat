from pydantic import BaseModel, Field


class User(BaseModel):
    name:str
    age:int = 18


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    session: str = Field(default="default", min_length=1, max_length=50)

class ChatResponse(BaseModel):
    reply: str
    session: str
    message_count: int



