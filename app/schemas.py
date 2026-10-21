from pydantic import BaseModel, Field


class History(BaseModel):
    history: list[dict[str, str]]
    session: str      # 会话显示名
    session_uuid: str  # 会话唯一标识


class HistoryRequest(BaseModel):
    session_uuid: str = Field(..., min_length=1, max_length=50)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    session_uuid: str | None = Field(default=None)


class RenameRequest(BaseModel):
    session_uuid: str = Field(..., min_length=1, max_length=50)


class RenameResponse(BaseModel):
    session: str       # 新的会话显示名
    session_uuid: str   # 不变的唯一标识

class RegisterRequest(BaseModel):
    username: str = Field(...,min_length=3,max_length=50)
    password: str = Field(...,min_length=6,max_length=100)

class RegisterResponse(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    username: str = Field(...,min_length=1,max_length=50)
    password: str = Field(...,min_length=1,max_length=100)

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str

class ApiKeyTestResponse(BaseModel):
    ok: bool
    message: str