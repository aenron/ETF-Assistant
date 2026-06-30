"""管理员路由"""
from datetime import timezone
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models.user import User
from models.dca_index_mapping import DcaIndexMapping
from models.dca_signal_config import DcaSignalConfig
from models.macro_cycle_state import MacroCycleState
from routers.auth import get_current_admin
from schemas.user import AdminUserUpdate, UserResponse
from schemas.portfolio import DcaIndexMappingCreate, DcaIndexMappingResponse, DcaIndexMappingUpdate, DcaSignalConfigResponse, DcaSignalConfigUpdate
from schemas.macro import MacroCycleStateCreate, MacroCycleStateResponse, MacroRefreshResponse
from utils.timezone import now_in_utc_naive
from services.industry_fundamental_service import IndustryFundamentalService
from services.macro_service import MacroDataService
from services.portfolio_service import PortfolioService
from services.scheduler import (
    get_scheduler_job,
    list_scheduler_jobs,
    pause_scheduler_job,
    resume_scheduler_job,
    set_scheduler_job_enabled,
    trigger_scheduler_job_now,
)


router = APIRouter(
    prefix="/api/admin",
    tags=["管理员"],
    dependencies=[Depends(get_current_admin)],
)


@router.post("/portfolio/migrate-otc-funds")
async def migrate_legacy_otc_funds(
    dry_run: bool = True,
    user_id: int | None = None,
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
):
    """保守识别旧持仓里的场外基金。dry_run=true 只预览，false 才更新。"""
    result = await PortfolioService.migrate_legacy_otc_fund_holdings(
        session,
        dry_run=dry_run,
        user_id=user_id,
        limit=limit,
    )
    if not dry_run:
        await session.commit()
    return result


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    session: AsyncSession = Depends(get_session),
):
    """列出全部账号"""
    result = await session.execute(select(User).order_by(User.created_at.asc(), User.id.asc()))
    return result.scalars().all()


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: AdminUserUpdate,
    session: AsyncSession = Depends(get_session),
    current_admin: User = Depends(get_current_admin),
):
    """更新账号状态、管理员角色或账户金额"""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if user.id == current_admin.id:
        if data.is_active is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能禁用当前登录的管理员账号")
        if data.is_admin is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能移除当前登录账号的管理员权限")

    if data.is_active is not None:
        user.is_active = data.is_active
    if data.is_admin is not None:
        user.is_admin = data.is_admin
    if data.account_balance is not None:
        user.account_balance = Decimal(str(data.account_balance))

    await session.commit()
    await session.refresh(user)
    return user


def _to_utc_naive(value):
    if value is None:
        return now_in_utc_naive()
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _default_macro_dca_impact(cycle_phase: str) -> str:
    impact = {
        "recovery": "复苏环境下权益风险预算可适度提高，绿灯可按常规或增强倍率执行，黄灯维持基础定投。",
        "overheating": "过热环境下避免追高，绿灯仍可执行但建议降低增强倍率上限，红灯严格暂停新增。",
        "stagflation": "滞涨环境下权益风险预算应下调，黄灯偏观察，只有质量较高的深绿/绿灯才考虑小额执行。",
        "recession": "衰退环境下控制总仓位，优先现金、债券和防御资产，红绿灯只作为低位分批观察信号。",
    }
    return impact.get(cycle_phase, "宏观阶段不明确，红绿灯策略维持默认倍率并控制总仓位。")


@router.post("/macro/state", response_model=MacroCycleStateResponse)
async def create_macro_state(data: MacroCycleStateCreate, session: AsyncSession = Depends(get_session)):
    """手动维护当前宏观美林时钟状态。"""
    state = MacroCycleState(
        region=data.region,
        cycle_phase=data.cycle_phase,
        growth_score=Decimal(str(data.growth_score)),
        inflation_score=Decimal(str(data.inflation_score)),
        growth_trend=data.growth_trend,
        inflation_trend=data.inflation_trend,
        confidence=Decimal(str(data.confidence)),
        summary=data.summary.strip() if data.summary else None,
        dca_impact=(data.dca_impact.strip() if data.dca_impact else _default_macro_dca_impact(data.cycle_phase)),
        source_note=data.source_note.strip() if data.source_note else "手动维护",
        source_type="manual",
        override_until=_to_utc_naive(data.override_until) if data.override_until else None,
        observed_at=_to_utc_naive(data.observed_at),
    )
    session.add(state)
    await session.commit()
    await session.refresh(state)
    return state


@router.get("/industry/fundamentals")
async def list_industry_fundamentals():
    """列出行业基本面缓存、样本股、核心指标和采集错误。"""
    return {"items": await IndustryFundamentalService.list_snapshots()}


@router.post("/industry/fundamentals/refresh")
async def refresh_industry_fundamentals(key: str | None = None):
    """手动刷新行业基本面缓存。"""
    keys = [key] if key else None
    result = await IndustryFundamentalService.refresh_all(keys)
    return {
        "success": True,
        "refreshed": len(result),
        "keys": list(result.keys()),
        "items": await IndustryFundamentalService.list_snapshots(),
    }


@router.post("/macro/refresh", response_model=MacroRefreshResponse)
async def refresh_macro_data(region: str | None = None, session: AsyncSession = Depends(get_session)):
    """手动采集宏观指标并生成自动美林时钟状态。"""
    state, indicators, errors = await MacroDataService.refresh(session, region=region)
    if not indicators:
        await session.rollback()
        return MacroRefreshResponse(success=False, message=f"{region or '全量'} 宏观指标采集失败", indicators_saved=0, state=None, errors=errors)
    await session.commit()
    if state:
        await session.refresh(state)
    return MacroRefreshResponse(
        success=True,
        message=f"{region or '全量'} 宏观指标已刷新，保存 {len(indicators)} 个指标",
        indicators_saved=len(indicators),
        state=state,
        errors=errors,
    )


def _require_scheduler_job(job_id: str):
    job = get_scheduler_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="定时任务不存在")
    return job


@router.get("/scheduler/jobs")
async def list_scheduler_job_status(
    session: AsyncSession = Depends(get_session),
):
    """列出后台定时任务状态"""
    from services.scheduler import ensure_scheduler_job_configs

    await ensure_scheduler_job_configs(session)
    await session.commit()
    return list_scheduler_jobs()


@router.post("/scheduler/jobs/{job_id}/run")
async def run_scheduler_job(job_id: str):
    """立即手动执行一个定时任务"""
    _require_scheduler_job(job_id)
    job = trigger_scheduler_job_now(job_id)
    return {
        "success": True,
        "message": f"任务 {job.name} 已开始手动执行",
        "job_id": job.id,
    }


@router.post("/scheduler/jobs/{job_id}/pause")
async def pause_scheduler_job_status(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """暂停一个定时任务"""
    _require_scheduler_job(job_id)
    job = pause_scheduler_job(job_id)
    await set_scheduler_job_enabled(session, job_id, False)
    await session.commit()
    return {
        "success": True,
        "message": f"任务 {job.name} 已暂停",
        "jobs": list_scheduler_jobs()["jobs"],
    }


@router.post("/scheduler/jobs/{job_id}/resume")
async def resume_scheduler_job_status(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """恢复一个定时任务"""
    _require_scheduler_job(job_id)
    job = resume_scheduler_job(job_id)
    await set_scheduler_job_enabled(session, job_id, True)
    await session.commit()
    return {
        "success": True,
        "message": f"任务 {job.name} 已恢复",
        "jobs": list_scheduler_jobs()["jobs"],
    }


async def _get_or_create_dca_signal_config(session: AsyncSession) -> DcaSignalConfig:
    config = await session.get(DcaSignalConfig, 1)
    if config:
        return config
    config = DcaSignalConfig(id=1)
    session.add(config)
    await session.flush()
    await session.refresh(config)
    return config


def _validate_dca_signal_config(config: DcaSignalConfig) -> None:
    deep = float(config.valuation_deep_green_percentile)
    green = float(config.valuation_green_percentile)
    red = float(config.valuation_red_percentile)
    if not (0 < deep < green < red < 100):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="估值分位必须满足 0 < 深绿 < 绿灯 < 红灯 < 100")
    if config.valuation_min_sample_size < 30:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="估值样本阈值不能小于30")
    if not (5 <= config.trend_short_ma_days < config.trend_medium_ma_days < config.trend_long_ma_days):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="均线周期必须满足 短期 < 中期 < 长期，且短期至少5日")
    if config.trend_history_days < config.trend_long_ma_days + config.trend_slope_shift_days:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="历史K线天数必须覆盖长期均线和斜率窗口")
    if config.trend_volume_confirm_ratio <= 0 or config.trend_volume_expand_ratio < config.trend_volume_confirm_ratio:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="量能阈值必须为正，且放量阈值不能低于确认阈值")
    if not (0 < float(config.trend_atr_base_multiplier) <= float(config.trend_atr_mid_multiplier) <= float(config.trend_atr_high_multiplier)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ATR倍数必须递增且大于0")
    if not (0 < float(config.trend_atr_mid_volatility_pct) <= float(config.trend_atr_high_volatility_pct)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ATR波动率阈值必须递增且大于0")
    if config.light_confirm_count < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="灯色确认次数不能小于1")


@router.get("/dca/signal-config", response_model=DcaSignalConfigResponse)
async def get_dca_signal_config(session: AsyncSession = Depends(get_session)):
    """获取定投红绿灯全局参数配置。"""
    config = await _get_or_create_dca_signal_config(session)
    await session.commit()
    return config


@router.put("/dca/signal-config", response_model=DcaSignalConfigResponse)
async def update_dca_signal_config(data: DcaSignalConfigUpdate, session: AsyncSession = Depends(get_session)):
    """更新定投红绿灯全局参数配置。"""
    config = await _get_or_create_dca_signal_config(session)
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        setattr(config, key, Decimal(str(value)) if isinstance(value, float) else value)
    _validate_dca_signal_config(config)
    await session.commit()
    await session.refresh(config)
    return config


@router.get("/dca/index-mappings", response_model=List[DcaIndexMappingResponse])
async def list_dca_index_mappings(
    session: AsyncSession = Depends(get_session),
):
    """列出定投红绿灯宽基 ETF 到指数估值代码的映射。"""
    result = await session.execute(select(DcaIndexMapping).order_by(DcaIndexMapping.enabled.desc(), DcaIndexMapping.etf_code.asc(), DcaIndexMapping.keyword.asc()))
    return result.scalars().all()


@router.post("/dca/index-mappings", response_model=DcaIndexMappingResponse)
async def create_dca_index_mapping(
    data: DcaIndexMappingCreate,
    session: AsyncSession = Depends(get_session),
):
    """新增宽基估值映射。etf_code 和 keyword 至少填写一个。"""
    if not (data.etf_code or data.keyword):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ETF代码和名称关键词至少填写一个")
    mapping = DcaIndexMapping(
        etf_code=data.etf_code.strip() if data.etf_code else None,
        keyword=data.keyword.strip() if data.keyword else None,
        index_symbol=data.index_symbol.strip(),
        index_name=data.index_name.strip() if data.index_name else None,
        enabled=data.enabled,
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return mapping


@router.put("/dca/index-mappings/{mapping_id}", response_model=DcaIndexMappingResponse)
async def update_dca_index_mapping(
    mapping_id: int,
    data: DcaIndexMappingUpdate,
    session: AsyncSession = Depends(get_session),
):
    """更新宽基估值映射。"""
    mapping = await session.get(DcaIndexMapping, mapping_id)
    if not mapping:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="映射不存在")
    if data.etf_code is not None:
        mapping.etf_code = data.etf_code.strip() or None
    if data.keyword is not None:
        mapping.keyword = data.keyword.strip() or None
    if not (mapping.etf_code or mapping.keyword):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ETF代码和名称关键词至少填写一个")
    if data.index_symbol is not None:
        mapping.index_symbol = data.index_symbol.strip()
    if data.index_name is not None:
        mapping.index_name = data.index_name.strip() or None
    if data.enabled is not None:
        mapping.enabled = data.enabled
    await session.commit()
    await session.refresh(mapping)
    return mapping


@router.delete("/dca/index-mappings/{mapping_id}")
async def delete_dca_index_mapping(
    mapping_id: int,
    session: AsyncSession = Depends(get_session),
):
    """删除宽基估值映射。"""
    mapping = await session.get(DcaIndexMapping, mapping_id)
    if not mapping:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="映射不存在")
    await session.delete(mapping)
    await session.commit()
    return {"message": "删除成功"}
