from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models.user import User
from routers.auth import get_current_user
from schemas.strategy import (
    StrategyInfo,
    StrategyRunRequest,
    StrategyRunResponse,
    StrategyScheduleRequest,
    StrategyScheduleResponse,
)
from services.strategy_service import STRATEGY_ID, StrategyService


router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyInfo])
async def list_strategies(current_user: User = Depends(get_current_user)):
    return StrategyService.list_strategies()


@router.post("/run", response_model=StrategyRunResponse)
async def run_strategy(
    request: StrategyRunRequest,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if request.strategy_id == STRATEGY_ID:
        return await StrategyService.run_tfss_v1(db, current_user.id)
    raise HTTPException(status_code=400, detail="Unsupported strategy")


@router.get("/latest", response_model=StrategyRunResponse | None)
async def get_latest_strategy_run(current_user: User = Depends(get_current_user)):
    return StrategyService.get_last_run(current_user.id)


@router.get("/schedule", response_model=StrategyScheduleResponse)
async def get_strategy_schedule(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await StrategyService.get_schedule(db, current_user.id)


@router.post("/schedule", response_model=StrategyScheduleResponse)
async def set_strategy_schedule(
    request: StrategyScheduleRequest,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await StrategyService.set_schedule(
        db,
        current_user.id,
        enabled=request.enabled,
    )
