from datetime import date
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Portfolio, EtfInfo
from schemas.portfolio import (
    PortfolioCreate, PortfolioUpdate, PortfolioResponse, 
    PortfolioWithMarket, PortfolioSummary
)
from services.market_service import MarketService


class PortfolioService:
    """持仓管理服务"""

    @staticmethod
    def build_summary_from_portfolios(portfolios: List[PortfolioWithMarket], available_cash: float = 0.0) -> PortfolioSummary:
        """基于已拉取的持仓+行情结果构建汇总，避免重复查询和重复拉行情。"""
        total_market_value = 0.0
        total_cost = 0.0
        today_pnl = 0.0
        category_distribution = {}

        for p in portfolios:
            if p.market_value:
                total_market_value += p.market_value
                cost = float(p.shares) * float(p.cost_price)
                total_cost += cost

                if p.change_pct and p.market_value:
                    yesterday_value = p.market_value / (1 + p.change_pct / 100)
                    today_pnl += p.market_value - yesterday_value

                category = MarketService._guess_category(p.etf_name or "")
                if category not in category_distribution:
                    category_distribution[category] = 0.0
                category_distribution[category] += p.market_value

        total_pnl = total_market_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
        today_pnl_pct = (today_pnl / (total_market_value - today_pnl) * 100) if total_market_value > today_pnl else 0.0
        total_assets = total_market_value + available_cash

        return PortfolioSummary(
            total_market_value=total_market_value,
            total_cost=total_cost,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            today_pnl=today_pnl,
            today_pnl_pct=today_pnl_pct,
            category_distribution=category_distribution,
            total_assets=total_assets,
        )
    
    @staticmethod
    async def get_all(session: AsyncSession, user_id: int) -> List[PortfolioResponse]:
        """获取所有持仓"""
        result = await session.execute(
            select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)
        )
        portfolios = result.scalars().all()
        return [PortfolioResponse.model_validate(p) for p in portfolios]
    
    @staticmethod
    async def get_by_id(
        session: AsyncSession, portfolio_id: int, user_id: int
    ) -> Optional[PortfolioResponse]:
        """获取单个持仓"""
        result = await session.execute(
            select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
        )
        portfolio = result.scalar_one_or_none()
        return PortfolioResponse.model_validate(portfolio) if portfolio else None
    
    @staticmethod
    async def create(
        session: AsyncSession, data: PortfolioCreate, user_id: int
    ) -> PortfolioResponse:
        """创建持仓"""
        portfolio = Portfolio(
            user_id=user_id,
            etf_code=data.etf_code,
            shares=data.shares,
            cost_price=data.cost_price,
            buy_date=data.buy_date,
            note=data.note,
        )
        session.add(portfolio)
        await session.flush()
        await session.refresh(portfolio)
        return PortfolioResponse.model_validate(portfolio)
    
    @staticmethod
    async def update(
        session: AsyncSession, 
        portfolio_id: int, 
        data: PortfolioUpdate,
        user_id: int,
    ) -> Optional[PortfolioResponse]:
        """更新持仓"""
        result = await session.execute(
            select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
        )
        portfolio = result.scalar_one_or_none()
        if not portfolio:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(portfolio, key, value)
        
        await session.flush()
        await session.refresh(portfolio)
        return PortfolioResponse.model_validate(portfolio)
    
    @staticmethod
    async def delete(session: AsyncSession, portfolio_id: int, user_id: int) -> bool:
        """删除持仓"""
        result = await session.execute(
            select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
        )
        portfolio = result.scalar_one_or_none()
        if not portfolio:
            return False
        
        await session.delete(portfolio)
        return True
    
    @staticmethod
    async def get_with_market(
        session: AsyncSession, user_id: int
    ) -> List[PortfolioWithMarket]:
        """获取持仓列表（含实时行情）"""
        result = await session.execute(
            select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)
        )
        portfolios = result.scalars().all()
        
        if not portfolios:
            return []
        
        # 只获取持仓ETF的行情（优先从Redis缓存）
        etf_codes = [p.etf_code for p in portfolios]
        quotes = await MarketService.get_quotes_for_codes(etf_codes)
        
        results = []
        for p in portfolios:
            quote = quotes.get(p.etf_code)
            if quote:
                market_value = float(p.shares) * quote.price
                cost = float(p.shares) * float(p.cost_price)
                pnl = market_value - cost
                pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0
                
                holding_days = None
                if p.buy_date:
                    holding_days = (date.today() - p.buy_date).days
                
                results.append(PortfolioWithMarket(
                    id=p.id,
                    etf_code=p.etf_code,
                    shares=float(p.shares),
                    cost_price=float(p.cost_price),
                    buy_date=p.buy_date,
                    note=p.note,
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                    etf_name=quote.name,
                    current_price=quote.price,
                    change_pct=quote.change_pct,
                    market_refreshed_at=quote.refreshed_at,
                    market_value=market_value,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    holding_days=holding_days,
                ))
            else:
                results.append(PortfolioWithMarket(
                    id=p.id,
                    etf_code=p.etf_code,
                    shares=float(p.shares),
                    cost_price=float(p.cost_price),
                    buy_date=p.buy_date,
                    note=p.note,
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                ))
        
        return results
    
    @staticmethod
    async def get_summary(session: AsyncSession, user_id: int) -> PortfolioSummary:
        """获取持仓汇总"""
        from models.user import User
        
        portfolios = await PortfolioService.get_with_market(session, user_id=user_id)
        # 获取用户可用资金
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        available_cash = float(user.account_balance) if user and user.account_balance else 0.0
        
        return PortfolioService.build_summary_from_portfolios(portfolios, available_cash)
