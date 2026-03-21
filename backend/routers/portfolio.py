from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from database import get_session
from schemas.portfolio import (
    PortfolioCreate, PortfolioUpdate, PortfolioResponse, PortfolioWithMarket, PortfolioSummary
)
from services.portfolio_service import PortfolioService
from routers.auth import get_current_user
from models.user import User

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=List[PortfolioWithMarket])
async def get_portfolio_list(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取持仓列表（含实时行情）"""
    return await PortfolioService.get_with_market(db, user_id=current_user.id)


@router.get("/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取持仓汇总"""
    return await PortfolioService.get_summary(db, user_id=current_user.id)


@router.get("/{portfolio_id}", response_model=PortfolioResponse)
async def get_portfolio(
    portfolio_id: int, 
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取单个持仓"""
    result = await PortfolioService.get_by_id(db, portfolio_id, user_id=current_user.id)
    if not result:
        raise HTTPException(status_code=404, detail="持仓不存在")
    return result


@router.post("", response_model=PortfolioResponse)
async def create_portfolio(
    data: PortfolioCreate, 
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """创建持仓"""
    return await PortfolioService.create(db, data, user_id=current_user.id)


@router.put("/{portfolio_id}", response_model=PortfolioResponse)
async def update_portfolio(
    portfolio_id: int, 
    data: PortfolioUpdate, 
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """更新持仓"""
    result = await PortfolioService.update(db, portfolio_id, data, user_id=current_user.id)
    if not result:
        raise HTTPException(status_code=404, detail="持仓不存在")
    return result


@router.delete("/{portfolio_id}")
async def delete_portfolio(
    portfolio_id: int, 
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """删除持仓"""
    success = await PortfolioService.delete(db, portfolio_id, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="持仓不存在")
    return {"message": "删除成功"}
