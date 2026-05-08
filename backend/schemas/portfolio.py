from pydantic import Field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from schemas.base import ShanghaiBaseModel, ShanghaiOrmModel


class DecimalModel(ShanghaiBaseModel):
    pass


class PortfolioBase(ShanghaiBaseModel):
    etf_code: str
    shares: float
    cost_price: float
    buy_date: Optional[date] = None
    note: Optional[str] = None


class PortfolioCreate(PortfolioBase):
    pass


class PortfolioUpdate(ShanghaiBaseModel):
    shares: Optional[float] = None
    cost_price: Optional[float] = None
    buy_date: Optional[date] = None
    note: Optional[str] = None


class PortfolioResponse(PortfolioBase, ShanghaiOrmModel):
    id: int
    created_at: datetime
    updated_at: datetime

class PortfolioWithMarket(PortfolioResponse):
    """持仓信息 + 实时行情"""
    etf_name: Optional[str] = None
    current_price: Optional[float] = None
    change_pct: Optional[float] = None
    market_refreshed_at: Optional[datetime] = None
    market_value: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    today_pnl: Optional[float] = None
    today_pnl_pct: Optional[float] = None
    holding_days: Optional[int] = None


class PortfolioSummary(ShanghaiBaseModel):
    """持仓汇总"""
    total_market_value: float
    total_cost: float
    total_pnl: float
    total_pnl_pct: float
    today_pnl: Optional[float] = None
    today_pnl_pct: Optional[float] = None
    category_distribution: dict[str, float]
    total_assets: Optional[float] = None  # 总金额 = 持仓市值 + 可用资金
