from pydantic import BaseModel, Field


class HistoryItem(BaseModel):
    id: int
    role: str
    content: str
    segment_id: int | None = None


class History(BaseModel):
    items: list[HistoryItem]
    has_more: bool
    next_before_id: int | None = None


class HistoryRequest(BaseModel):
    before_id: int | None = None
    limit: int = Field(default=30, ge=1, le=100)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)

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