from datetime import datetime
from typing import List, Optional

from pydantic import Field

from schemas.base import ShanghaiBaseModel, ShanghaiOrmModel


class AssistantMessageCreate(ShanghaiBaseModel):
    """发送给助手的消息"""

    message: str = Field(min_length=1, max_length=4000)
    session_id: Optional[int] = None
    retry_message_id: Optional[int] = None
    include_portfolio_context: bool = True
    portfolio_ids: Optional[List[int]] = None


class AssistantSessionCreate(ShanghaiBaseModel):
    """创建助手会话"""

    title: Optional[str] = Field(default=None, max_length=120)


class AssistantSessionResponse(ShanghaiOrmModel):
    """助手会话响应"""

    id: int
    title: str
    last_message_preview: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class AssistantMessageResponse(ShanghaiOrmModel):
    """助手消息响应"""

    id: int
    role: str
    content: str
    status: str = "done"
    run_id: Optional[str] = None
    created_at: datetime

class AssistantChatResponse(ShanghaiBaseModel):
    """助手聊天响应"""

    session: AssistantSessionResponse
    user_message: AssistantMessageResponse
    assistant_message: AssistantMessageResponse


class AssistantHistoryResponse(ShanghaiBaseModel):
    """助手历史消息"""

    session: AssistantSessionResponse
    messages: List[AssistantMessageResponse]


class AssistantSessionListResponse(ShanghaiBaseModel):
    """助手会话列表"""

    sessions: List[AssistantSessionResponse]
