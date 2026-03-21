from pydantic import BaseModel, ConfigDict
from datetime import date
from decimal import Decimal
from typing import Optional, List


class MarketQuote(BaseModel):
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


class KLineItem(BaseModel):
    """K线数据项"""
    trade_date: date
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: int
    change_pct: float


class MarketDailyResponse(BaseModel):
    """历史行情响应"""
    code: str
    name: str
    data: List[KLineItem]


class EtfSearchResult(BaseModel):
    """ETF搜索结果"""
    code: str
    name: str
    category: Optional[str] = None
    exchange: Optional[str] = None
