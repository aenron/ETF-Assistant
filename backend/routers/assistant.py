from fastapi.responses import StreamingResponse
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models.user import User
from routers.auth import get_current_user
from schemas.assistant import (
    AssistantChatResponse,
    AssistantHistoryResponse,
    AssistantMessageCreate,
    AssistantSessionCreate,
    AssistantSessionListResponse,
    AssistantSessionResponse,
)
from services.assistant_service import AssistantService


router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.get("/sessions", response_model=AssistantSessionListResponse)
async def list_assistant_sessions(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await AssistantService.list_sessions(db, user_id=current_user.id)


@router.post("/sessions", response_model=AssistantSessionResponse)
async def create_assistant_session(
    data: AssistantSessionCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await AssistantService.create_session(db, user_id=current_user.id, title=data.title)


@router.get("/history", response_model=AssistantHistoryResponse)
async def get_assistant_history(
    session_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取助手对话历史"""
    return await AssistantService.get_history(db, user_id=current_user.id, session_id=session_id)


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(
    data: AssistantMessageCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """发送消息给智能体助手"""
    return await AssistantService.chat(db, user_id=current_user.id, session_id=data.session_id, message=data.message)


@router.post("/chat/stream")
async def stream_chat_with_assistant(
    data: AssistantMessageCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """流式发送消息给智能体助手"""
    _, stream = await AssistantService.chat_stream(db, user_id=current_user.id, session_id=data.session_id, message=data.message)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/sessions/{session_id}")
async def delete_assistant_session(
    session_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """删除助手会话"""
    deleted = await AssistantService.delete_session(db, user_id=current_user.id, session_id=session_id)
    return {"success": True, "deleted": deleted}
