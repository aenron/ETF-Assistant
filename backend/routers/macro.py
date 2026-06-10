from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models.macro_cycle_state import MacroCycleState
from models.macro_indicator import MacroIndicator
from routers.auth import get_current_user
from schemas.macro import MacroCycleStateResponse, MacroIndicatorResponse
from utils.timezone import now_in_shanghai, now_in_utc_naive


router = APIRouter(prefix="/api/macro", tags=["宏观时钟"], dependencies=[Depends(get_current_user)])


def _default_dca_impact(cycle_phase: str) -> str:
    impact = {
        "recovery": "复苏环境下权益风险预算可适度提高，绿灯可按常规或增强倍率执行，黄灯维持基础定投。",
        "overheating": "过热环境下避免追高，绿灯仍可执行但建议降低增强倍率上限，红灯严格暂停新增。",
        "stagflation": "滞涨环境下权益风险预算应下调，黄灯偏观察，只有质量较高的深绿/绿灯才考虑小额执行。",
        "recession": "衰退环境下控制总仓位，优先现金、债券和防御资产，红绿灯只作为低位分批观察信号。",
    }
    return impact.get(cycle_phase, "宏观阶段不明确，红绿灯策略维持默认倍率并控制总仓位。")


def _default_macro_state(region: str = "cn") -> MacroCycleStateResponse:
    now = now_in_shanghai()
    return MacroCycleStateResponse(
        id=0,
        region=region,
        cycle_phase="recovery",
        growth_score=50,
        inflation_score=50,
        growth_trend="unclear",
        inflation_trend="unclear",
        confidence=0,
        summary="尚未维护宏观状态。管理员可在宏观时钟页面录入当前美林时钟阶段。",
        dca_impact="暂无宏观约束，定投红绿灯按默认参数执行。",
        source_note="手动维护",
        source_type="manual",
        override_until=None,
        observed_at=now,
        created_at=now,
        updated_at=now,
    )


@router.get("/current", response_model=MacroCycleStateResponse)
async def get_current_macro_state(region: str = "cn", session: AsyncSession = Depends(get_session)):
    now = now_in_utc_naive()
    manual_result = await session.execute(
        select(MacroCycleState)
        .where(
            MacroCycleState.region == region,
            MacroCycleState.source_type == "manual",
            or_(MacroCycleState.override_until.is_(None), MacroCycleState.override_until > now),
        )
        .order_by(MacroCycleState.observed_at.desc(), MacroCycleState.id.desc())
        .limit(1)
    )
    state = manual_result.scalar_one_or_none()
    if not state:
        result = await session.execute(
            select(MacroCycleState)
            .where(MacroCycleState.region == region)
            .order_by(MacroCycleState.observed_at.desc(), MacroCycleState.id.desc())
            .limit(1)
        )
        state = result.scalar_one_or_none()
    if not state:
        return _default_macro_state(region)
    if not state.dca_impact:
        state.dca_impact = _default_dca_impact(state.cycle_phase)
    return state


@router.get("/history", response_model=List[MacroCycleStateResponse])
async def list_macro_history(region: str | None = None, limit: int = 12, session: AsyncSession = Depends(get_session)):
    limit = max(1, min(limit, 60))
    stmt = select(MacroCycleState)
    if region:
        stmt = stmt.where(MacroCycleState.region == region)
    result = await session.execute(
        stmt.order_by(MacroCycleState.observed_at.desc(), MacroCycleState.id.desc()).limit(limit)
    )
    return result.scalars().all()


@router.get("/indicators", response_model=List[MacroIndicatorResponse])
async def list_macro_indicators(region: str | None = None, limit: int = 20, session: AsyncSession = Depends(get_session)):
    limit = max(1, min(limit, 100))
    stmt = select(MacroIndicator)
    if region:
        stmt = stmt.where(MacroIndicator.region == region)
    result = await session.execute(
        stmt.order_by(MacroIndicator.fetched_at.desc(), MacroIndicator.id.desc()).limit(limit)
    )
    items = result.scalars().all()
    latest_by_code = {}
    for item in items:
        latest_by_code.setdefault(f"{item.region}:{item.indicator_code}", item)
    return list(latest_by_code.values())
