from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models.user import User
from routers.auth import get_current_user
from schemas.multi_agent import (
    MultiAgentRunCreate,
    MultiAgentRunDetailResponse,
    MultiAgentRunListResponse,
    MultiAgentRunResponse,
    MultiAgentRunUpdate,
)
from services.multi_agent_service import MultiAgentService

router = APIRouter(prefix="/api/multi-agent", tags=["multi-agent"])


@router.post("/runs", response_model=MultiAgentRunResponse)
async def create_run(
    request: MultiAgentRunCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await MultiAgentService.create_run(db, current_user.id, request)


@router.post("/runs/stream")
async def stream_run(
    request: MultiAgentRunCreate,
    current_user: User = Depends(get_current_user),
):
    stream = MultiAgentService.create_run_stream_with_managed_session(current_user.id, request)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs", response_model=MultiAgentRunListResponse)
async def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await MultiAgentService.list_runs(db, current_user.id, limit)


@router.get("/runs/{run_id}", response_model=MultiAgentRunDetailResponse)
async def get_run(
    run_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    run = await MultiAgentService.get_run(db, current_user.id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="未找到该多智能体研判记录")
    return run


@router.patch("/runs/{run_id}", response_model=MultiAgentRunResponse)
async def update_run(
    run_id: int,
    request: MultiAgentRunUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    run = await MultiAgentService.update_run(db, current_user.id, run_id, request)
    if run is None:
        raise HTTPException(status_code=404, detail="未找到该多智能体研判记录")
    return run


@router.delete("/runs/{run_id}")
async def delete_run(
    run_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    deleted = await MultiAgentService.delete_run(db, current_user.id, run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到该多智能体研判记录")
    return {"success": True}
