from fastapi import APIRouter, Query, Depends
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from schemas.market import MarketQuote, MarketDailyResponse, KLineItem, EtfSearchResult
from services.market_service import MarketService
from services.portfolio_service import PortfolioService
from routers.auth import get_current_user
from models.user import User

router = APIRouter(
    prefix="/api/market",
    tags=["market"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/quote/{code}", response_model=MarketQuote)
async def get_quote(code: str):
    """获取单个ETF实时行情"""
    quotes = await MarketService.get_quotes_for_codes([code])
    if code not in quotes:
        return {"error": "未找到该ETF"}
    return quotes[code]


@router.post("/refresh/{code}")
async def refresh_quote(code: str):
    """强制刷新单个ETF行情"""
    quote = await MarketService.refresh_quote(code)
    if quote:
        return {"success": True, "quote": quote}
    return {"success": False, "message": f"刷新 {code} 行情失败"}


@router.post("/refresh-all")
async def refresh_all_quotes(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """强制刷新所有持仓ETF行情"""
    # 获取用户持仓的所有ETF代码
    portfolios = await PortfolioService.get_with_market(session, user_id=current_user.id)
    codes = list(set(p.etf_code for p in portfolios))
    
    if not codes:
        return {"success": True, "message": "无持仓数据", "refreshed": 0}
    
    # 强制刷新行情
    quotes = await MarketService.refresh_quotes(codes)
    return {
        "success": True,
        "message": f"已刷新 {len(quotes)} 只ETF行情",
        "refreshed": len(quotes),
        "codes": codes,
    }


@router.get("/history/{code}", response_model=MarketDailyResponse)
async def get_history(
    code: str, 
    days: int = Query(default=60, ge=1, le=365)
):
    """获取历史K线和技术指标"""
    kline_data = await MarketService.get_history_kline(code, days=days)
    quotes = await MarketService.get_quotes_for_codes([code])
    quote = quotes.get(code)
    
    # 计算技术指标
    indicators = MarketService.calculate_technical_indicators(kline_data)
    
    return MarketDailyResponse(
        code=code,
        name=quote.name if quote else "",
        data=kline_data,
        indicators=indicators,
    )


@router.get("/etf/search", response_model=List[EtfSearchResult])
async def search_etf(q: str = Query(default="", min_length=1)):
    """搜索ETF"""
    return await MarketService.search_etf(q)
