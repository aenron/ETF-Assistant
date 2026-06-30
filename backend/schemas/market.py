import math

from pydantic import field_validator
from datetime import date, datetime
from typing import Optional, List

from schemas.base import ShanghaiBaseModel


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


def _optional_finite_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return int(parsed)


class MarketQuote(ShanghaiBaseModel):
    """实时行情"""
    code: str
    name: str
    price: float
    change_pct: float
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[float] = None
    iopv: Optional[float] = None
    premium_rate: Optional[float] = None
    refreshed_at: Optional[datetime] = None

    @field_validator("price", "change_pct", mode="before")
    @classmethod
    def clean_required_float(cls, value):
        return _finite_float(value)

    @field_validator("open_price", "high_price", "low_price", "amount", "iopv", "premium_rate", mode="before")
    @classmethod
    def clean_optional_float(cls, value):
        return _optional_finite_float(value)

    @field_validator("volume", mode="before")
    @classmethod
    def clean_optional_int(cls, value):
        return _optional_finite_int(value)


class KLineItem(ShanghaiBaseModel):
    """K线数据项"""
    trade_date: date
    trade_time: Optional[datetime] = None
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: int
    amount: Optional[float] = None
    change_pct: float

    @field_validator("open_price", "close_price", "high_price", "low_price", "change_pct", mode="before")
    @classmethod
    def clean_kline_float(cls, value):
        return _finite_float(value)

    @field_validator("amount", mode="before")
    @classmethod
    def clean_kline_amount(cls, value):
        return _optional_finite_float(value)

    @field_validator("volume", mode="before")
    @classmethod
    def clean_kline_volume(cls, value):
        return _optional_finite_int(value) or 0


class TechnicalIndicators(ShanghaiBaseModel):
    """技术指标"""
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    rsi14: Optional[float] = None
    macd_dif: Optional[float] = None
    macd_dea: Optional[float] = None
    macd_histogram: Optional[float] = None

    @field_validator("ma5", "ma10", "ma20", "rsi14", "macd_dif", "macd_dea", "macd_histogram", mode="before")
    @classmethod
    def clean_indicator_float(cls, value):
        return _optional_finite_float(value)


class MarketDailyResponse(ShanghaiBaseModel):
    """历史行情响应"""
    code: str
    name: str
    data: List[KLineItem]
    indicators: Optional[TechnicalIndicators] = None


class EtfSearchResult(ShanghaiBaseModel):
    """ETF搜索结果"""
    code: str
    name: str
    category: Optional[str] = None
    exchange: Optional[str] = None


class EtfClassificationResponse(ShanghaiBaseModel):
    """ETF 标签分类结果"""
    code: str
    name: str
    asset_bucket: str
    region: str
    style: str
    risk_tags: list[str]
    macro_weights: dict[str, float]
    max_position_hint: float
    reason: str
