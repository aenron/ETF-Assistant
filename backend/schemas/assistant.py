from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AssistantMessageCreate(BaseModel):
    """发送给助手的消息"""

    message: str = Field(min_length=1, max_length=4000)
    session_id: Optional[int] = None


class AssistantSessionCreate(BaseModel):
    """创建助手会话"""

    title: Optional[str] = Field(default=None, max_length=120)


class AssistantSessionResponse(BaseModel):
    """助手会话响应"""

    id: int
    title: str
    last_message_preview: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssistantMessageResponse(BaseModel):
    """助手消息响应"""

    id: int
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssistantChatResponse(BaseModel):
    """助手聊天响应"""

    session: AssistantSessionResponse
    user_message: AssistantMessageResponse
    assistant_message: AssistantMessageResponse


class AssistantHistoryResponse(BaseModel):
    """助手历史消息"""

    session: AssistantSessionResponse
    messages: List[AssistantMessageResponse]


class AssistantSessionListResponse(BaseModel):
    """助手会话列表"""

    sessions: List[AssistantSessionResponse]
