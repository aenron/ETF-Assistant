from fastapi import APIRouter, Query
from typing import List

from schemas.market import MarketQuote, MarketDailyResponse, KLineItem, EtfSearchResult
from services.market_service import MarketService

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/quote/{code}", response_model=MarketQuote)
async def get_quote(code: str):
    """获取单个ETF实时行情"""
    quotes = await MarketService.get_quotes_for_codes([code])
    if code not in quotes:
        return {"error": "未找到该ETF"}
    return quotes[code]


@router.get("/history/{code}", response_model=MarketDailyResponse)
async def get_history(
    code: str, 
    days: int = Query(default=60, ge=1, le=365)
):
    """获取历史K线"""
    kline_data = MarketService.get_history_kline(code, days=days)
    quotes = await MarketService.get_quotes_for_codes([code])
    quote = quotes.get(code)
    return MarketDailyResponse(
        code=code,
        name=quote.name if quote else "",
        data=kline_data,
    )


@router.get("/etf/search", response_model=List[EtfSearchResult])
async def search_etf(q: str = Query(default="", min_length=1)):
    """搜索ETF"""
    return await MarketService.search_etf(q)
