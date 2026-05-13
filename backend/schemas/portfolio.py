import math

from pydantic import field_validator
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from schemas.base import ShanghaiBaseModel, ShanghaiOrmModel


def _finite_float(value, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def _optional_finite_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


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

    @field_validator(
        "current_price",
        "change_pct",
        "market_value",
        "pnl",
        "pnl_pct",
        "today_pnl",
        "today_pnl_pct",
        mode="before",
    )
    @classmethod
    def clean_optional_float(cls, value):
        return _optional_finite_float(value)


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

    @field_validator("total_market_value", "total_cost", "total_pnl", "total_pnl_pct", mode="before")
    @classmethod
    def clean_required_float(cls, value):
        return _finite_float(value)

    @field_validator("today_pnl", "today_pnl_pct", "total_assets", mode="before")
    @classmethod
    def clean_summary_optional_float(cls, value):
        return _optional_finite_float(value)

    @field_validator("category_distribution", mode="before")
    @classmethod
    def clean_category_distribution(cls, value):
        if not isinstance(value, dict):
            return {}
        return {str(key): _finite_float(item) for key, item in value.items()}
