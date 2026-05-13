from datetime import date, datetime, time
from decimal import Decimal
import math
from typing import Optional, List
from zoneinfo import ZoneInfo
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

    SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

    @classmethod
    def _shanghai_now(cls) -> datetime:
        return datetime.now(cls.SHANGHAI_TZ)

    @classmethod
    def _quote_refresh_date(cls, refreshed_at) -> Optional[date]:
        if not refreshed_at:
            return None
        if refreshed_at.tzinfo is None:
            return refreshed_at.date()
        return refreshed_at.astimezone(cls.SHANGHAI_TZ).date()

    @classmethod
    def _is_today_market_quote(cls, refreshed_at) -> bool:
        """Treat quote change_pct as today's move once the A-share call auction starts."""
        now = cls._shanghai_now()
        if now.weekday() >= 5:
            return False
        if now.time() < time(9, 15):
            return False
        return cls._quote_refresh_date(refreshed_at) == now.date()

    @staticmethod
    def _finite_float(value, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if math.isnan(parsed) or math.isinf(parsed):
            return default
        return parsed

    @staticmethod
    def _optional_finite_float(value) -> Optional[float]:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed

    @staticmethod
    def build_summary_from_portfolios(portfolios: List[PortfolioWithMarket], available_cash: float = 0.0) -> PortfolioSummary:
        """基于已拉取的持仓+行情结果构建汇总，避免重复查询和重复拉行情。"""
        total_market_value = 0.0
        total_cost = 0.0
        today_pnl = 0.0
        today_previous_value = 0.0
        has_today_pnl = False
        category_distribution = {}

        for p in portfolios:
            market_value = PortfolioService._optional_finite_float(p.market_value)
            if market_value is not None and market_value > 0:
                total_market_value += market_value
                cost = PortfolioService._finite_float(p.shares) * PortfolioService._finite_float(p.cost_price)
                total_cost += cost

                item_today_pnl = PortfolioService._optional_finite_float(p.today_pnl)
                if item_today_pnl is not None:
                    today_pnl += item_today_pnl
                    today_previous_value += market_value - item_today_pnl
                    has_today_pnl = True

                category = MarketService._guess_category(p.etf_name or "")
                if category not in category_distribution:
                    category_distribution[category] = 0.0
                category_distribution[category] += market_value

        total_pnl = total_market_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
        today_pnl_value = today_pnl if has_today_pnl else None
        today_pnl_pct = (today_pnl / today_previous_value * 100) if has_today_pnl and today_previous_value > 0 else None
        total_assets = total_market_value + PortfolioService._finite_float(available_cash)

        return PortfolioSummary(
            total_market_value=PortfolioService._finite_float(total_market_value),
            total_cost=PortfolioService._finite_float(total_cost),
            total_pnl=PortfolioService._finite_float(total_pnl),
            total_pnl_pct=PortfolioService._finite_float(total_pnl_pct),
            today_pnl=PortfolioService._optional_finite_float(today_pnl_value),
            today_pnl_pct=PortfolioService._optional_finite_float(today_pnl_pct),
            category_distribution={
                category: PortfolioService._finite_float(value)
                for category, value in category_distribution.items()
            },
            total_assets=PortfolioService._finite_float(total_assets),
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
    
    @classmethod
    async def get_with_market(
        cls, session: AsyncSession, user_id: int
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
            price = cls._optional_finite_float(quote.price) if quote else None
            if quote and price is not None and price > 0:
                shares = cls._finite_float(p.shares)
                cost_price = cls._finite_float(p.cost_price)
                change_pct = cls._optional_finite_float(quote.change_pct)
                market_value = shares * price
                cost = shares * cost_price
                pnl = market_value - cost
                pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0
                today_pnl = None
                today_pnl_pct = None
                today = cls._shanghai_now().date()
                if cls._is_today_market_quote(quote.refreshed_at):
                    if p.buy_date == today:
                        today_pnl = pnl
                        today_pnl_pct = pnl_pct
                    elif change_pct is not None:
                        previous_value = market_value / (1 + change_pct / 100) if change_pct != -100 else 0.0
                        today_pnl = market_value - previous_value
                        today_pnl_pct = change_pct
                
                holding_days = None
                if p.buy_date:
                    holding_days = (today - p.buy_date).days
                
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
                    current_price=price,
                    change_pct=change_pct,
                    market_refreshed_at=quote.refreshed_at,
                    market_value=cls._finite_float(market_value),
                    pnl=cls._finite_float(pnl),
                    pnl_pct=cls._finite_float(pnl_pct),
                    today_pnl=cls._optional_finite_float(today_pnl),
                    today_pnl_pct=cls._optional_finite_float(today_pnl_pct),
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
