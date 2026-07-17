import asyncio
from fastapi import APIRouter, Query, Depends
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from schemas.market import MarketQuote, MarketDailyResponse, KLineItem, EtfSearchResult, EtfClassificationResponse
from services.market_service import MarketService
from services.etf_classification_service import EtfClassificationService
from services.portfolio_service import PortfolioService
from services.scheduler import update_user_dca_signals
from routers.auth import get_current_user
from models.portfolio import Portfolio
from models.user import User

router = APIRouter(
    prefix="/api/market",
    tags=["market"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/quote/{code}", response_model=MarketQuote)
async def get_quote(code: str):
    """获取单个证券/基金行情。默认只读缓存，避免普通页面查询阻塞。"""
    quote = await MarketService.get_quote_from_cache(code)
    if quote:
        return MarketQuote.model_validate(quote)

    asyncio.create_task(MarketService.refresh_quote(code))
    return MarketQuote(code=code, name="", price=0, change_pct=0)


@router.post("/refresh/{code}")
async def refresh_quote(
    code: str,
    current_user: User = Depends(get_current_user),
):
    """强制刷新单个证券/基金行情，并更新当前用户红绿灯信号。"""
    quote = await MarketService.refresh_quote(code)
    if quote:
        clean_quote = MarketQuote.model_validate(quote).model_dump(mode="json")
        dca_events = await update_user_dca_signals(current_user.id, etf_codes=[code])
        return {"success": True, "quote": clean_quote, "dca_events": len(dca_events)}
    return {"success": False, "message": f"刷新 {code} 行情失败"}


@router.post("/refresh-all")
async def refresh_all_quotes(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """强制刷新所有持仓品种行情"""
    result = await session.execute(
        select(Portfolio.etf_code)
        .where(Portfolio.user_id == current_user.id)
        .distinct()
    )
    codes = sorted({code for code in result.scalars().all() if code})
    
    if not codes:
        return {"success": True, "message": "无持仓数据", "refreshed": 0}
    
    quotes = await MarketService.refresh_quotes(codes)
    dca_events = await update_user_dca_signals(current_user.id)
    return {
        "success": True,
        "message": f"已刷新 {len(quotes)} 个品种行情，并更新红绿灯信号",
        "refreshed": len(quotes),
        "dca_events": len(dca_events),
        "codes": codes,
    }


@router.get("/history/{code}", response_model=MarketDailyResponse)
async def get_history(
    code: str, 
    days: int = Query(default=60, ge=1, le=365)
):
    """获取历史K线和技术指标。

    详情页首次打开需要直接拿到图表数据；这里使用 get_history_kline 的缓存/数据库/外部源
    降级链路，而不是只读 Redis 后异步预热。
    """
    confirmed_kline_data = await MarketService.get_history_kline(code, days=days)
    indicators = MarketService.calculate_technical_indicators(confirmed_kline_data)
    kline_data = await MarketService.append_realtime_daily_point(code, confirmed_kline_data)

    quote = await MarketService.get_quote_from_cache(code)

    latest_trade_date = MarketService._latest_kline_trade_date(kline_data)
    has_provisional = any(item.provisional for item in kline_data)
    
    return MarketDailyResponse(
        code=code,
        name=quote.name if quote else "",
        data=kline_data,
        indicators=indicators,
        latest_trade_date=latest_trade_date,
        source="history+realtime_quote" if has_provisional else "history",
        has_provisional=has_provisional,
    )


@router.get("/intraday/{code}", response_model=MarketDailyResponse)
async def get_intraday(
    code: str,
    period: str = Query(default="1m", pattern="^(1m|5m|15m|30m|60m)$"),
    limit: int = Query(default=240, ge=20, le=480),
):
    """获取当日分钟K线，用于详情页实时趋势图。"""
    kline_data, source = await MarketService.get_intraday_kline_with_source(code, period=period, limit=limit)
    quote = await MarketService.get_quote_from_cache(code)
    indicators = MarketService.calculate_technical_indicators(kline_data)
    has_provisional = any(item.provisional for item in kline_data)
    return MarketDailyResponse(
        code=code,
        name=quote.name if quote else "",
        data=kline_data,
        indicators=indicators,
        latest_trade_date=MarketService._latest_kline_trade_date(kline_data),
        source=source,
        has_provisional=has_provisional,
    )


@router.get("/etf/search", response_model=List[EtfSearchResult])
async def search_etf(q: str = Query(default="", min_length=1)):
    """搜索ETF"""
    return await MarketService.search_etf(q)


@router.get("/etf/{code}/classification", response_model=EtfClassificationResponse)
async def get_etf_classification(
    code: str,
    name: str | None = Query(default=None),
):
    """获取 ETF 资产桶、地域、风格、风险标签和宏观权重。"""
    display_name = name
    if not display_name:
        quote = await MarketService.get_quote_from_cache(code)
        display_name = quote.name if quote and quote.name else ""
    return EtfClassificationService.classify(code, display_name)


@router.get("/etf/{code}/profile")
async def get_etf_profile(
    code: str,
    year: int | None = Query(default=None, ge=2000, le=2100),
    force_refresh: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
):
    """获取ETF/基金资料、资产配置、持仓明细和公告提醒"""
    return await MarketService.get_etf_profile(
        code,
        year=year,
        session=session,
        force_refresh=force_refresh,
    )
