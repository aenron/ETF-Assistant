from pydantic import BaseModel, ConfigDict
from datetime import date, datetime
from decimal import Decimal
from typing import Optional


class DecimalModel(BaseModel):
    model_config = ConfigDict(
        json_encoders={Decimal: lambda v: float(v)},
    )


class PortfolioBase(BaseModel):
    etf_code: str
    shares: float
    cost_price: float
    buy_date: Optional[date] = None
    note: Optional[str] = None


class PortfolioCreate(PortfolioBase):
    pass


class PortfolioUpdate(BaseModel):
    shares: Optional[float] = None
    cost_price: Optional[float] = None
    buy_date: Optional[date] = None
    note: Optional[str] = None


class PortfolioResponse(PortfolioBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PortfolioWithMarket(PortfolioResponse):
    """持仓信息 + 实时行情"""
    etf_name: Optional[str] = None
    current_price: Optional[float] = None
    change_pct: Optional[float] = None
    market_value: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    holding_days: Optional[int] = None


class PortfolioSummary(BaseModel):
    """持仓汇总"""
    total_market_value: float
    total_cost: float
    total_pnl: float
    total_pnl_pct: float
    today_pnl: Optional[float] = None
    today_pnl_pct: Optional[float] = None
    category_distribution: dict[str, float]
