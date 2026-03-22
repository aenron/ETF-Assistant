from fastapi.responses import StreamingResponse
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models.user import User
from routers.auth import get_current_user
from schemas.assistant import AssistantChatResponse, AssistantHistoryResponse, AssistantMessageCreate
from services.assistant_service import AssistantService


router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.get("/history", response_model=AssistantHistoryResponse)
async def get_assistant_history(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取助手对话历史"""
    return await AssistantService.get_history(db, user_id=current_user.id)


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(
    data: AssistantMessageCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """发送消息给智能体助手"""
    return await AssistantService.chat(db, user_id=current_user.id, message=data.message)


@router.post("/chat/stream")
async def stream_chat_with_assistant(
    data: AssistantMessageCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """流式发送消息给智能体助手"""
    _, stream = await AssistantService.chat_stream(db, user_id=current_user.id, message=data.message)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/history")
async def clear_assistant_history(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """清空助手记忆"""
    deleted = await AssistantService.clear_history(db, user_id=current_user.id)
    return {"success": True, "deleted": deleted}
