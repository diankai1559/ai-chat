from pydantic import BaseModel, Field


class User(BaseModel):
    name:str
    age:int = 18

class History(BaseModel):
    history: list[dict[str, str]]
    session: str

class HistoryRequest(BaseModel):
    session: str = Field(..., min_length=1, max_length=50)

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    session: str | None = Field(default=None, min_length=1, max_length=50)

class RenameRequest(BaseModel):
    session: str = Field(..., min_length=1, max_length=50)

class RenameResponse(BaseModel):
    session: str = Field(..., min_length=1, max_length=50)




