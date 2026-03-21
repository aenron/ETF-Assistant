import asyncio
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict

from database import get_session
from schemas.advice import (
    AdviceGenerateRequest,
    AdviceResponse,
    AdviceLogResponse,
    AccountAnalysisResponse,
)
from services.advisor_service import AdvisorService
from models.advice_log import AdviceLog
from routers.auth import get_current_user
from models.user import User

router = APIRouter(prefix="/api/advice", tags=["advice"])


@router.post("/generate", response_model=List[AdviceResponse])
async def generate_advice(
    request: AdviceGenerateRequest,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """生成投资建议（可指定ETF代码列表）"""
    return await AdvisorService.generate_advice(db, request.etf_codes, user_id=current_user.id)


@router.post("/account-analysis", response_model=AccountAnalysisResponse)
async def generate_account_analysis(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """生成账户级投资建议"""
    return await AdvisorService.generate_account_analysis(
        db,
        user_id=current_user.id,
        account_balance=current_user.account_balance,
    )


@router.get("/account-analysis/latest", response_model=Optional[AccountAnalysisResponse])
async def get_latest_account_analysis(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取最近一次账户级投资建议"""
    return await AdvisorService.get_latest_account_analysis(db, user_id=current_user.id)


@router.get("/generate/{portfolio_id}", response_model=AdviceResponse)
async def generate_advice_for_portfolio(
    portfolio_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """生成单个持仓的投资建议"""
    advice = await AdvisorService.generate_advice_for_portfolio(
        db, portfolio_id, user_id=current_user.id
    )
    if not advice:
        return {"error": "未找到该持仓"}
    return advice


@router.get("/history", response_model=List[AdviceLogResponse])
async def get_advice_history(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取历史建议记录"""
    return await AdvisorService.get_history(db, limit, user_id=current_user.id)


@router.get("/latest", response_model=Dict[str, AdviceLogResponse])
async def get_latest_advices(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取每个ETF的最新建议"""
    from sqlalchemy import func
    # 子查询：每个etf_code的最大id
    subquery = (
        select(func.max(AdviceLog.id).label("max_id"))
        .where(
            AdviceLog.user_id == current_user.id,
            AdviceLog.etf_code != AdvisorService.ACCOUNT_ANALYSIS_CODE,
        )
        .group_by(AdviceLog.etf_code)
        .subquery()
    )
    query = select(AdviceLog).where(AdviceLog.id == subquery.c.max_id)
    result = await db.execute(query)
    logs = result.scalars().all()
    return {
        log.etf_code: AdviceLogResponse.model_validate(log) for log in logs
    }


@router.post("/analyze-all")
async def analyze_all_portfolios(
    current_user: User = Depends(get_current_user),
):
    """手动触发分析当前用户的所有持仓"""
    from services.scheduler import analyze_user_portfolios
    # 异步执行分析任务
    asyncio.create_task(analyze_user_portfolios(current_user.id))
    return {
        "message": f"用户 {current_user.id} 的分析任务已启动",
        "status": "running",
        "user_id": current_user.id,
    }
