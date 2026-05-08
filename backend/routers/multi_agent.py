from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models.user import User
from routers.auth import get_current_user
from schemas.multi_agent import MultiAgentRunCreate, MultiAgentRunDetailResponse, MultiAgentRunListResponse, MultiAgentRunResponse
from services.multi_agent_service import MultiAgentService

router = APIRouter(prefix="/api/multi-agent", tags=["multi-agent"])


@router.post("/runs", response_model=MultiAgentRunResponse)
async def create_run(
    request: MultiAgentRunCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await MultiAgentService.create_run(db, current_user.id, request)


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
