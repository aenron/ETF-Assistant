from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class AssistantMessageCreate(BaseModel):
    """发送给助手的消息"""

    message: str = Field(min_length=1, max_length=4000)


class AssistantMessageResponse(BaseModel):
    """助手消息响应"""

    id: int
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssistantChatResponse(BaseModel):
    """助手聊天响应"""

    user_message: AssistantMessageResponse
    assistant_message: AssistantMessageResponse


class AssistantHistoryResponse(BaseModel):
    """助手历史消息"""

    messages: List[AssistantMessageResponse]
