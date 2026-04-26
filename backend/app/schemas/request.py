from typing import Optional

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    user_id: Optional[str] = None
    session_id: Optional[str] = Field(description="Session ID", default=None)


class ChatMessageRequest(BaseModel):
    query: str
    context: UserContext
    flag: bool = True


class UserSessionsRequest(BaseModel):
    user_id: Optional[str] = Field(default=None, description="Deprecated, ignored by server")
