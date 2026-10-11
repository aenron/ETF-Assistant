import logging

logger = logging.getLogger("uvicorn.error.market_service")

import asyncio
import akshare as ak
import pandas as pd
from datetime import date, datetime, timedelta, time as datetime_time
from typing import Optional, List, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import time



from models import MarketDaily
from schemas.market import MarketQuote, KLineItem, EtfSearchResult
from config import settings
from database import async_session_maker
from services.redis_service import RedisService
from services.miaoxiang_service import MiaoxiangService
from services.szse_service import SzseService
from utils.timezone import SHANGHAI_TZ, now_in_shanghai


from services.market.providers import MarketProviderMixin
from services.market.profiles import FundProfileMixin
from services.market.indicators import TechnicalIndicatorMixin


class MarketService(MarketProviderMixin, FundProfileMixin, TechnicalIndicatorMixin):
    """Market source orchestration, cache policy and historical storage."""

    # Redis缓存key
    REDIS_KEY_QUOTE_PREFIX = "etf:quote:v2:"
    REDIS_KEY_KLINE_PREFIX = "etf:kline:v2:"
    REDIS_KEY_PROFILE_PREFIX = "etf:profile:"
    REDIS_KEY_OTC_FUND_DAILY_SNAPSHOT = "fund:otc:daily_snapshot"
    REDIS_KEY_ALL_QUOTES = "etf:all_quotes"
    CACHE_EXPIRE_SECONDS = 604800  # 7天缓存 (7 * 24 * 60 * 60)
    KLINE_CACHE_EXPIRE_SECONDS = 7200  # 2小时缓存
    PROFILE_CACHE_EXPIRE_SECONDS = 86400  # ETF资料1天缓存，后台定时刷新
    OTC_FUND_DAILY_CACHE_EXPIRE_SECONDS = 21600  # 开放式基金净值列表6小时缓存
    KLINE_CACHE_CANDIDATE_DAYS = (60, 90, 120, 140, 180, 250)
    _THS_INDUSTRY_NAME_MAP: Dict[str, str] | None = None
    _TUSHARE_PRO = None
    _KLINE_WARMING_KEYS: set[str] = set()
    _QUOTE_REFRESH_TASKS: Dict[tuple, asyncio.Task] = {}
    _EASTMONEY_INTRADAY_FAILURES: Dict[str, int] = {}
    _EASTMONEY_INTRADAY_BREAKER_UNTIL: Dict[str, float] = {}
    EASTMONEY_INTRADAY_FAILURE_THRESHOLD = 2
    EASTMONEY_INTRADAY_BREAKER_SECONDS = 180
    _ETF_SEARCH_CACHE: Optional[pd.DataFrame] = None
    _ETF_SEARCH_EXPIRES_AT = 0.0
    _ETF_SEARCH_LOCK = asyncio.Lock()
    SSE_ETF_CATALOG_CACHE_TTL = 900
    _SSE_ETF_CATALOG_CACHE: Dict[str, str] = {}
    _SSE_ETF_CATALOG_EXPIRES_AT = 0.0
    SSE_MARKET_DATA_BASE_URL = "https://yunhq.sse.com.cn:32042/v1/sh1"
    SSE_MARKET_DATA_REFERER = "https://www.sse.com.cn/assortment/fund/etf/price/"

    @staticmethod
    def _with_refresh_time(
        quote: MarketQuote,
        refreshed_at: Optional[datetime] = None,
    ) -> MarketQuote:
        """为行情附加刷新时间"""
        return quote.model_copy(update={"refreshed_at": refreshed_at or now_in_shanghai()})

    @classmethod
    async def get_quote_from_cache(cls, code: str) -> Optional[MarketQuote]:
        """从Redis缓存获取单个ETF行情"""
        if not settings.redis_enabled:
            return None
        cached = await RedisService.get(f"{cls.REDIS_KEY_QUOTE_PREFIX}{code}")
        if cached and "data" in cached:
            data = dict(cached["data"])
            data["refreshed_at"] = data.get("refreshed_at")
            quote = MarketQuote(**data)
            quote = quote.model_copy(update={"stale": not cls._quote_is_fresh(quote)})
            cls._log_quote_source(code, "redis_cache", quote)
            return quote
        return None

    @staticmethod
    def _quote_is_fresh(quote: MarketQuote, now: Optional[datetime] = None) -> bool:
        current = now or now_in_shanghai()
        stamp = quote.refreshed_at
        if stamp is None or quote.price <= 0:
            return False
        stamp = stamp.astimezone(SHANGHAI_TZ) if stamp.tzinfo else stamp.replace(tzinfo=SHANGHAI_TZ)
        age = (current - stamp).total_seconds()
        if age < -60 or age > 10 * 86400:
            return False
        if quote.quote_type in {"nav", "estimate"}:
            return age <= 4 * 86400
        trading = current.weekday() < 5 and (
            datetime_time(9, 15) <= current.time() <= datetime_time(11, 35)
            or datetime_time(13) <= current.time() <= datetime_time(15, 5)
        )
        if trading:
            return quote.quote_type == "realtime" and age <= 180
        expected = current.date()
        if current.time() < datetime_time(9, 15):
            expected -= timedelta(days=1)
        while expected.weekday() >= 5:
            expected -= timedelta(days=1)
        # Lunch break: morning close is current-session data.
        return stamp.date() >= expected

    @classmethod
    def _prepare_kline(cls, data: List[KLineItem], source: str) -> List[KLineItem]:
        return cls._normalize_kline_amounts([item.model_copy(update={"source": source}) for item in data])

    @classmethod
    def _kline_cache_key(cls, code: str, days: int) -> str:
        return f"{cls.REDIS_KEY_KLINE_PREFIX}{code}:{days}"

    @staticmethod
    def _last_weekday_before(value: date) -> date:
        candidate = value - timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate

    @classmethod
    def _expected_kline_min_date(cls, now: Optional[datetime] = None) -> date:
        """Return the minimum acceptable daily K-line date for cache reuse.

        During the trading session most public daily-K sources do not publish the
        current day yet, so yesterday's trading day is acceptable. After 15:10 we
        try to refresh toward today's final daily bar.
        """
        current = now or now_in_shanghai()
        today = current.date()
        if today.weekday() >= 5:
            candidate = today
            while candidate.weekday() >= 5:
                candidate -= timedelta(days=1)
            return candidate
        if current.time() >= datetime_time(15, 10):
            return today
        return cls._last_weekday_before(today)

    @classmethod
    def _is_kline_recent(cls, data: List[KLineItem], max_lag_days: int = 4) -> bool:
        """Return whether cached daily K-line data is recent enough to reuse."""
        if not data:
            return False
        latest_dates = [item.trade_date for item in data if item.trade_date]
        if not latest_dates:
            return False
        latest_date = max(latest_dates)
        expected_date = cls._expected_kline_min_date()
        if latest_date >= expected_date:
            return True
        return False

    @classmethod
    def _latest_kline_trade_date(cls, data: List[KLineItem]) -> Optional[date]:
        dates = [item.trade_date for item in data if item.trade_date]
        return max(dates) if dates else None

    @classmethod
    async def append_realtime_daily_point(cls, code: str, data: List[KLineItem]) -> List[KLineItem]:
        """Append a non-persistent intraday daily bar when quote is newer than daily K-line."""
        if not data:
            return data
        quote = await cls.get_quote_from_cache(code)
        if not quote or not quote.refreshed_at or quote.price <= 0:
            return data

        refreshed_at = quote.refreshed_at.astimezone(SHANGHAI_TZ) if quote.refreshed_at.tzinfo else quote.refreshed_at.replace(tzinfo=SHANGHAI_TZ)
        quote_date = refreshed_at.date()
        if quote_date.weekday() >= 5:
            return data
        latest_date = cls._latest_kline_trade_date(data)
        if latest_date is None or latest_date >= quote_date:
            return data

        previous_close = data[-1].close_price if data[-1].close_price > 0 else quote.price
        open_price = quote.open_price if quote.open_price and quote.open_price > 0 else previous_close
        high_price = max(quote.high_price or quote.price, quote.price, open_price)
        low_price = min(quote.low_price or quote.price, quote.price, open_price)
        change_pct = quote.change_pct
        if (change_pct is None or change_pct == 0) and previous_close > 0:
            change_pct = (quote.price - previous_close) / previous_close * 100

        provisional = KLineItem(
            trade_date=quote_date,
            trade_time=refreshed_at,
            provisional=True,
            source=quote.source,
            open_price=open_price,
            close_price=quote.price,
            high_price=high_price,
            low_price=low_price,
            volume=quote.volume or 0,
            amount=quote.amount,
            change_pct=round(change_pct or 0.0, 2),
        )
        return [*data, provisional]

    @staticmethod
    def _has_kline_amount(data: List[KLineItem]) -> bool:
        """Return whether the K-line series carries usable historical turnover amount."""
        if not data:
            return False
        recent = data[-min(len(data), 6):]
        return any(item.amount is not None and item.amount > 0 for item in recent)

    @classmethod
    def _log_quote_source(cls, code: str, source: str, quote: Optional[MarketQuote]) -> None:
        if not quote:
            return
        amount_text = f"{quote.amount:.2f}" if quote.amount is not None else "None"
        volume_text = str(quote.volume) if quote.volume is not None else "None"
        logger.info(
            f"[MarketService] 数据来源 quote code={code} source={source} "
            f"price={quote.price:.4f} change_pct={quote.change_pct:.4f} "
            f"amount={amount_text} volume={volume_text}"
        )

    @classmethod
    def _log_kline_source(cls, code: str, source: str, data: List[KLineItem]) -> None:
        if not data:
            return
        latest = data[-1]
        total_rows = len(data)
        missing_amount = sum(1 for item in data if item.amount is None or item.amount <= 0)
        amount_rate = ((total_rows - missing_amount) / total_rows * 100) if total_rows else 0.0
        latest_amount = latest.amount if latest.amount is not None else 0.0
        logger.info(
            f"[MarketService] 数据来源 kline code={code} source={source} rows={total_rows} "
            f"latest={latest.trade_date} close={latest.close_price:.4f} "
            f"amount={latest_amount:.2f} amount_rate={amount_rate:.1f}% "
            f"estimated_rows={sum(item.amount_estimated for item in data)}"
        )

    @classmethod
    def _normalize_kline_amounts(cls, data: List[KLineItem]) -> List[KLineItem]:
        """Fill missing turnover amount with a price-volume estimate when the source lacks it."""
        normalized: List[KLineItem] = []
        for item in data:
            amount = item.amount
            if (amount is None or amount <= 0) and item.volume and item.volume > 0:
                avg_price = (item.open_price + item.close_price + item.high_price + item.low_price) / 4
                if avg_price > 0:
                    amount = float(item.volume) * avg_price
            if amount != item.amount:
                item = item.model_copy(update={"amount": amount, "amount_estimated": True})
            normalized.append(item)
        return normalized


    @classmethod
    async def get_kline_from_cache(cls, code: str, days: int) -> Optional[List[KLineItem]]:
        """从 Redis 读取历史 K 线缓存"""
        if not settings.redis_enabled:
            return None

        cached = await RedisService.get(cls._kline_cache_key(code, days))
        if not cached or "data" not in cached:
            return None

        try:
            return [KLineItem(**item) for item in cached["data"]]
        except Exception as e:
            logger.info(f"[MarketService] K线缓存反序列化失败: {code}, {e}")
            return None

    @classmethod
    async def cache_kline(cls, code: str, days: int, data: List[KLineItem]) -> None:
        """缓存历史 K 线到 Redis"""
        if not settings.redis_enabled or not data:
            return

        payload = {
            "data": [item.model_dump(mode="json") for item in data],
            "cached_at": now_in_shanghai().isoformat(),
        }
        await RedisService.set(
            cls._kline_cache_key(code, days),
            payload,
            expire=cls.KLINE_CACHE_EXPIRE_SECONDS,
        )

    @classmethod
    async def get_kline_from_longer_cache(cls, code: str, days: int) -> Optional[List[KLineItem]]:
        """从更长周期 Redis 缓存裁剪历史 K 线，减少精确天数 miss 后的外部请求。"""
        if not settings.redis_enabled:
            return None

        candidate_days = sorted({*cls.KLINE_CACHE_CANDIDATE_DAYS, days * 2})
        for candidate in candidate_days:
            if candidate <= days:
                continue
            cached = await cls.get_kline_from_cache(code, candidate)
            if cached and len(cached) >= days:
                result = cached[-days:]
                await cls.cache_kline(code, days, result)
                logger.info(f"[MarketService] 使用较长K线缓存: {code}, {candidate}->{days}")
                return result
        return None

    @classmethod
    async def get_kline_from_db(cls, code: str, days: int) -> Optional[List[KLineItem]]:
        """从 market_daily 读取历史 K 线，作为手动策略执行的持久缓存。"""
        try:
            async with async_session_maker() as session:
                result = await session.execute(
                    select(MarketDaily)
                    .where(MarketDaily.etf_code == code, MarketDaily.source.is_not(None), MarketDaily.adjustment == "none")
                    .order_by(MarketDaily.trade_date.desc())
                    .limit(days)
                )
                rows = list(result.scalars().all())
        except Exception as e:
            logger.info(f"[MarketService] 数据库K线读取失败: {code}, {e}")
            return None

        min_rows = days
        if len(rows) < min_rows:
            logger.info(f"[MarketService] 数据库K线缓存不足: {code}, {len(rows)}/{min_rows} 条")
            return None

        rows.reverse()
        items = [
            KLineItem(
                trade_date=row.trade_date,
                open_price=float(row.open_price) if row.open_price is not None else 0.0,
                close_price=float(row.close_price) if row.close_price is not None else 0.0,
                high_price=float(row.high_price) if row.high_price is not None else 0.0,
                low_price=float(row.low_price) if row.low_price is not None else 0.0,
                volume=int(row.volume or 0),
                amount=float(row.amount) if getattr(row, "amount", None) is not None else None,
                change_pct=float(row.change_pct) if row.change_pct is not None else 0.0,
                source=row.source, adjustment=row.adjustment, amount_estimated=row.amount_estimated,
            )
            for row in rows
        ]
        items = cls._normalize_kline_amounts(items)
        await cls.cache_kline(code, days, items)
        logger.info(f"[MarketService] 使用数据库K线缓存: {code}, {len(items)} 条")
        return items

    @classmethod
    async def _cache_and_store_kline(cls, code: str, days: int, data: List[KLineItem]) -> None:
        """外部数据源成功后同步写入短期 Redis 和持久行情表。"""
        data = cls._normalize_kline_amounts(data)
        await cls.cache_kline(code, days, data)
        try:
            async with async_session_maker() as session:
                await cls.save_market_daily(session, code, data)
                await session.commit()
        except Exception as e:
            logger.info(f"[MarketService] 数据库K线保存失败: {code}, {e}")

    @classmethod
    async def warm_history_kline_cache(cls, code: str, days: int = 60) -> None:
        """后台预热 K 线缓存；同一标的同一周期去重，失败只记录日志。"""
        key = cls._kline_cache_key(code, days)
        if key in cls._KLINE_WARMING_KEYS:
            return
        cls._KLINE_WARMING_KEYS.add(key)
        try:
            await cls.get_history_kline(code, days=days, prefer_cache=False)
        except Exception as e:
            logger.info(f"[MarketService] 后台预热历史K线失败: {code}, {e}")
        finally:
            cls._KLINE_WARMING_KEYS.discard(key)

    @classmethod
    async def cache_quote(cls, code: str, quote: MarketQuote) -> MarketQuote:
        """缓存单个ETF行情到Redis（带时间戳）"""
        # 不缓存空数据或价格为0的数据
        if quote.price <= 0:
            logger.info(f"[MarketService] 跳过缓存空数据: {code}")
            return quote

        if not quote.name:
            cached_quote = await cls.get_quote_from_cache(code)
            if cached_quote and cached_quote.name:
                quote = quote.model_copy(update={"name": cached_quote.name})

        quote_with_time = quote if quote.source else cls._with_refresh_time(quote, quote.refreshed_at)
        quote_with_time = quote_with_time.model_copy(update={"fetched_at": now_in_shanghai(), "stale": not cls._quote_is_fresh(quote_with_time)})
        if settings.redis_enabled:
            cache_data = {
                "data": quote_with_time.model_dump(mode="json"),
                "cached_at": quote_with_time.refreshed_at.isoformat() if quote_with_time.refreshed_at else now_in_shanghai().isoformat(),
                "cache_date": now_in_shanghai().date().isoformat(),
            }
            await RedisService.set(
                f"{cls.REDIS_KEY_QUOTE_PREFIX}{code}",
                cache_data,
                expire=cls.CACHE_EXPIRE_SECONDS
            )
        return quote_with_time

    @classmethod
    async def get_quotes_for_codes(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """获取指定ETF代码的行情（优先从Redis缓存，失败时使用旧缓存）"""
        result: Dict[str, MarketQuote] = {}
        stale: Dict[str, MarketQuote] = {}
        for code in dict.fromkeys(codes):
            quote = await cls.get_quote_from_cache(code)
            if quote and cls._quote_is_fresh(quote):
                result[code] = quote
            elif quote:
                stale[code] = quote.model_copy(update={"stale": True})
        missing = [code for code in dict.fromkeys(codes) if code not in result]
        if missing:
            try:
                refreshed = await cls.refresh_quotes(missing)
                result.update({code: quote for code, quote in refreshed.items() if quote.price > 0})
            except Exception as exc:
                logger.warning("Quote refresh failed: %s", type(exc).__name__)
            for code in missing:
                if code not in result and code in stale:
                    result[code] = stale[code]
        return result

    @classmethod
    async def get_cached_quotes_for_codes(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """只读取行情缓存，不触发外部数据源请求。用于持仓列表快速返回。"""
        result: Dict[str, MarketQuote] = {}
        for code in codes:
            cached = await cls.get_quote_from_cache(code)
            if cached:
                result[code] = cached
        return result

    @classmethod
    async def refresh_quote(cls, code: str) -> Optional[MarketQuote]:
        """强制刷新单个ETF行情（跳过缓存）"""
        quotes = await cls.refresh_quotes([code])
        return quotes.get(code)

    @classmethod
    async def refresh_quotes(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        key = tuple(sorted(set(codes)))
        if not key:
            return {}
        task = cls._QUOTE_REFRESH_TASKS.get(key)
        if task is None:
            task = asyncio.create_task(cls._refresh_quotes(list(key)))
            cls._QUOTE_REFRESH_TASKS[key] = task
            def completed(done):
                if cls._QUOTE_REFRESH_TASKS.get(key) is done:
                    cls._QUOTE_REFRESH_TASKS.pop(key, None)
                if not done.cancelled():
                    done.exception()  # consume errors if every waiter was cancelled
            task.add_done_callback(completed)
        return await asyncio.shield(task)

    @classmethod
    async def _refresh_quotes(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """强制刷新多个ETF行情（跳过缓存）"""
        if not codes:
            return {}

        result: Dict[str, MarketQuote] = {}
        try:
            zhitu_quotes = await cls._fetch_quotes_from_zhitu(codes)
            for code, quote in zhitu_quotes.items():
                cls._log_quote_source(code, "zhitu_fund_real", quote)
            result.update(zhitu_quotes)
        except Exception as e:
            logger.info(f"[MarketService] 智兔批量刷新行情失败: {e}")

        remaining = [code for code in codes if code not in result]
        if remaining:
            try:
                quotes = await cls._fetch_quotes_from_akshare(remaining)
                for code, quote in quotes.items():
                    cls._log_quote_source(code, "fallback_market_sources", quote)
                result.update(quotes)
            except Exception as e:
                logger.info(f"[MarketService] 批量刷新行情失败: {e}")
        return result

    @classmethod
    def _normalize_intraday_items(cls, items: List[KLineItem], limit: int) -> List[KLineItem]:
        ordered = sorted(
            [item for item in items if item.trade_time is not None],
            key=lambda item: item.trade_time,
        )[-limit:]
        result: List[KLineItem] = []
        for item in ordered:
            previous_close = result[-1].close_price if result else item.open_price
            change_pct = (item.close_price - previous_close) / previous_close * 100 if previous_close > 0 else 0.0
            result.append(item.model_copy(update={"change_pct": round(change_pct, 3)}))
        return result

    @classmethod
    async def _realtime_intraday_fallback(cls, code: str) -> List[KLineItem]:
        quote = await cls.get_quote_from_cache(code)
        if not quote or not quote.refreshed_at or quote.price <= 0 or quote.quote_type != "realtime":
            return []
        refreshed_at = quote.refreshed_at.astimezone(SHANGHAI_TZ) if quote.refreshed_at.tzinfo else quote.refreshed_at.replace(tzinfo=SHANGHAI_TZ)
        now = now_in_shanghai()
        if refreshed_at.date() != now.date() or refreshed_at > now + timedelta(minutes=1):
            return []
        if refreshed_at.time() < datetime_time(9, 15) or refreshed_at.time() > datetime_time(15, 5):
            return []
        open_price = quote.open_price if quote.open_price and quote.open_price > 0 else quote.price
        return [KLineItem(
            trade_date=refreshed_at.date(),
            trade_time=refreshed_at,
            provisional=True,
            source=quote.source,
            open_price=open_price,
            close_price=quote.price,
            high_price=max(quote.high_price or quote.price, quote.price, open_price),
            low_price=min(quote.low_price or quote.price, quote.price, open_price),
            volume=quote.volume or 0,
            amount=quote.amount,
            change_pct=round(quote.change_pct or 0.0, 2),
        )]

    @classmethod
    def _intraday_period_candidates(cls, period: str) -> List[str]:
        supported = ["1m", "5m", "15m", "30m", "60m"]
        safe_period = period if period in supported else "1m"
        if safe_period == "1m":
            return ["1m", "5m", "15m"]
        if safe_period == "5m":
            return ["5m", "15m"]
        return [safe_period]

    @classmethod
    async def get_intraday_kline_with_source(cls, code: str, period: str = "1m", limit: int = 240) -> tuple[List[KLineItem], str]:
        safe_limit = max(20, min(limit, 480))
        for candidate_period in cls._intraday_period_candidates(period):
            for fetcher in (
                cls._fetch_intraday_kline_sse,
                cls._fetch_intraday_kline_eastmoney,
            ):
                result = await fetcher(code, candidate_period, safe_limit)
                if not result:
                    continue
                today_items = cls._filter_today_intraday_items(result)
                if today_items:
                    if candidate_period != period:
                        logger.info(f"[MarketService] 今日分钟线周期降级成功: {code}, requested={period}, used={candidate_period}")
                    return cls._normalize_intraday_items(today_items, safe_limit), f"intraday_{candidate_period}"
                latest_time = result[-1].trade_time if result else None
                logger.info(f"[MarketService] 分钟K无今日有效数据，忽略非今日或未来数据: {code}, period={candidate_period}, latest={latest_time}")
        fallback = await cls._realtime_intraday_fallback(code)
        if fallback:
            logger.info(f"[MarketService] 使用实时快照兜底今日分钟线: {code}, latest={fallback[-1].trade_time}")
            return fallback, "intraday_realtime_quote"
        return [], "intraday_empty"

    @classmethod
    async def get_intraday_kline(cls, code: str, period: str = "1m", limit: int = 240) -> List[KLineItem]:
        data, _source = await cls.get_intraday_kline_with_source(code, period=period, limit=limit)
        return data

    @classmethod
    async def get_history_kline(cls, code: str, days: int = 60, prefer_cache: bool = True) -> List[KLineItem]:
        """获取历史K线数据（ETF/股票/指数板块/场外基金多源降级）"""
        if prefer_cache:
            cached = await cls.get_kline_from_cache(code, days)
            if cached and cls._is_kline_recent(cached) and cls._has_kline_amount(cached):
                cls._log_kline_source(code, "redis_cache", cached)
                return cached
            if cached:
                reason = "缺少成交额" if cls._is_kline_recent(cached) and not cls._has_kline_amount(cached) else f"最新日期: {cached[-1].trade_date}"
                logger.info(f"[MarketService] K线缓存需刷新: {code}, {reason}")

            cached = await cls.get_kline_from_longer_cache(code, days)
            if cached and cls._is_kline_recent(cached) and cls._has_kline_amount(cached):
                cls._log_kline_source(code, "redis_longer_cache", cached)
                return cached
            if cached:
                reason = "缺少成交额" if cls._is_kline_recent(cached) and not cls._has_kline_amount(cached) else f"最新日期: {cached[-1].trade_date}"
                logger.info(f"[MarketService] 较长K线缓存需刷新: {code}, {reason}")

            cached = await cls.get_kline_from_db(code, days)
            if cached and cls._is_kline_recent(cached) and cls._has_kline_amount(cached):
                cls._log_kline_source(code, "database_cache", cached)
                return cached
            if cached:
                reason = "缺少成交额" if cls._is_kline_recent(cached) and not cls._has_kline_amount(cached) else f"最新日期: {cached[-1].trade_date}"
                logger.info(f"[MarketService] 数据库K线缓存需刷新: {code}, {reason}")

        logger.info(f"[MarketService] 开始获取历史K线: {code}, 天数: {days}")

        # 智兔指数历史行情：用于沪深300、中证A500等基准指数，ETF历史K线实测无数据。
        try:
            result = await cls._fetch_history_kline_zhitu_index(code, days)
            if result:
                result = cls._prepare_kline(result, "zhitu_index_history")
                cls._log_kline_source(code, "zhitu_index_history", result)
                await cls._cache_and_store_kline(code, days, result)
                return result
        except Exception as e:
            logger.info(f"[MarketService] 智兔指数历史K线异常: {e}")

        # 同花顺 88xxxx 行业代码，必须优先于东方财富板块代码体系。
        try:
            result = await asyncio.to_thread(cls._fetch_history_kline_ths_industry, code, days)
            if result:
                result = cls._prepare_kline(result, "ths_industry_history")
                cls._log_kline_source(code, "ths_industry_history", result)
                await cls._cache_and_store_kline(code, days, result)
                return result
        except Exception as e:
            logger.info(f"[MarketService] 同花顺行业指数K线异常: {e}")

        if not prefer_cache:
            cached = await cls.get_kline_from_cache(code, days)
            if cached and cls._is_kline_recent(cached) and cls._has_kline_amount(cached):
                cls._log_kline_source(code, "redis_cache_after_force", cached)
                return cached

        # Exchange public feeds cover their respective listed securities.
        try:
            result = await cls._fetch_history_kline_sse(code, days)
            if result:
                result = cls._prepare_kline(result, "sse_history")
                cls._log_kline_source(code, "sse_history", result)
                await cls._cache_and_store_kline(code, days, result)
                return result
        except Exception as e:
            logger.info(f"[MarketService] 上交所历史K线异常: {code}, {type(e).__name__}")

        try:
            result = await SzseService.fetch_history(code, days)
            if result:
                result = cls._prepare_kline(result, "szse_history")
                cls._log_kline_source(code, "szse_history", result)
                await cls._cache_and_store_kline(code, days, result)
                return result
        except Exception as e:
            logger.info(f"[MarketService] 深交所历史K线异常: {code}, {type(e).__name__}")

        # Tushare is a configured-provider fallback for daily bars; check it before
        # public sources only when credentials are available.
        if settings.tushare_token.strip():
            try:
                result = await cls._fetch_history_kline_tushare(code, days)
                if result:
                    result = cls._prepare_kline(result, "tushare_history")
                    cls._log_kline_source(code, "tushare_history", result)
                    await cls._cache_and_store_kline(code, days, result)
                    return result
            except Exception as e:
                logger.info(f"[MarketService] Tushare历史K线异常: {e}")

        # 妙想已验证能返回真实 OHLCV 和成交额，优先于新浪估算成交额。
        try:
            result = await MiaoxiangService.fetch_history(code, days)
            if result:
                result = cls._prepare_kline(result, "miaoxiang_history")
                cls._log_kline_source(code, "miaoxiang_history", result)
                await cls._cache_and_store_kline(code, days, result)
                return result
        except Exception as e:
            logger.info(f"[MarketService] 妙想历史K线异常: {code}, {type(e).__name__}")

        # Sina returned current 60-day histories in the observed refreshes. Its
        # turnover is estimated, so prefer exchange feeds/Tushare/Miaoxiang first and record the
        # estimate in the source label.
        try:
            result = await cls._fetch_history_kline_sina(code, days)
            if result:
                result = cls._prepare_kline(result, "sina_history_estimated_amount")
                cls._log_kline_source(code, "sina_history_estimated_amount", result)
                await cls._cache_and_store_kline(code, days, result)
                return result
        except Exception as e:
            logger.info(f"[MarketService] 新浪API获取K线异常: {e}")

        # AkShare/Eastmoney have recently failed more often, but remain fallbacks
        # in case Sina does not return this symbol.
        try:
            result = await asyncio.to_thread(cls._fetch_history_kline_akshare, code, days)
            if result:
                result = cls._prepare_kline(result, "akshare_etf_history")
                cls._log_kline_source(code, "akshare_etf_history", result)
                await cls._cache_and_store_kline(code, days, result)
                return result
        except Exception as e:
            logger.info(f"[MarketService] akshare获取K线异常: {e}")

        # A股股票
        try:
            result = await asyncio.to_thread(cls._fetch_history_kline_akshare_stock, code, days)
            if result:
                result = cls._prepare_kline(result, "akshare_stock_history")
                cls._log_kline_source(code, "akshare_stock_history", result)
                await cls._cache_and_store_kline(code, days, result)
                return result
        except Exception as e:
            logger.info(f"[MarketService] akshare股票K线异常: {e}")

        # 备用：东方财富通用K线API，覆盖股票、场内基金、指数和部分板块。
        try:
            result = await cls._fetch_history_kline_eastmoney(code, days)
            if result:
                result = cls._prepare_kline(result, "eastmoney_history")
                cls._log_kline_source(code, "eastmoney_history", result)
                await cls._cache_and_store_kline(code, days, result)
                return result
        except Exception as e:
            logger.info(f"[MarketService] 东方财富API获取K线异常: {e}")

        # 场外基金净值走势。只作为最后兜底；该数据源没有真实开高低收。
        try:
            result = await asyncio.to_thread(cls._fetch_history_kline_akshare_otc_fund, code, days)
            if result:
                result = cls._prepare_kline(result, "akshare_otc_fund_history")
                cls._log_kline_source(code, "akshare_otc_fund_history", result)
                await cls._cache_and_store_kline(code, days, result)
                return result
        except Exception as e:
            logger.info(f"[MarketService] akshare场外基金净值异常: {e}")

        logger.info(f"[MarketService] ✗ 历史K线获取失败: {code}")
        return []


    @classmethod
    async def _fetch_quotes_from_akshare(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """从数据源获取指定证券/基金行情"""
        if not codes:
            return {}

        logger.info(f"[MarketService] 开始获取 {len(codes)} 个品种行情: {codes}")
        result: Dict[str, MarketQuote] = {}

        def merge_quotes(incoming: Dict[str, MarketQuote], source: str, quote_type: str = "realtime") -> None:
            for code, quote in incoming.items():
                quote = quote.model_copy(update={"source": source, "quote_type": quote_type})
                result[code] = cls._merge_quote(result[code], quote) if code in result else quote

        def core_missing() -> List[str]:
            return [code for code in codes if cls._quote_needs_enrichment(result.get(code))]

        missing_codes = core_missing()
        if missing_codes:
            logger.info(f"[MarketService] >>> 尝试上交所实时行情: {missing_codes}")
            sse_result = await cls._fetch_from_sse_api(missing_codes)
            merge_quotes(sse_result, "sse_quote", "realtime")

        missing_codes = core_missing()
        if missing_codes:
            szse_result = await SzseService.fetch_quotes(missing_codes)
            for code, quote in szse_result.items():
                cls._log_quote_source(code, "szse_quote", quote)
            merge_quotes(szse_result, "szse_quote", "realtime")

        # THS only has a matching catalog for 88xxxx industry indices.
        missing_codes = [code for code in core_missing() if str(code).startswith("88")]
        if missing_codes:
            logger.info(f"[MarketService] >>> 尝试同花顺行业指数数据源: {missing_codes}")
            ths_result = await cls._fetch_from_ths_industry_api(missing_codes)
            if ths_result:
                logger.info(f"[MarketService] ✓ 同花顺行业指数成功: {len(ths_result)} 个")
                merge_quotes(ths_result, "ths_daily_quote", "daily")

        # Sina was consistently available in the observed refreshes. Use it before
        # Tencent (whose volume is normalized in its parser) and the flaky batch APIs.
        missing_codes = core_missing()
        if missing_codes:
            logger.info(f"[MarketService] >>> 尝试新浪财经API: {missing_codes}")
            sina_result = await cls._fetch_from_sina_api(missing_codes)
            if sina_result:
                logger.info(f"[MarketService] ✓ 新浪API成功: {len(sina_result)} 个")
                merge_quotes(sina_result, "sina_quote", "realtime")

        missing_codes = core_missing()
        if missing_codes:
            logger.info(f"[MarketService] >>> 新浪未覆盖，尝试腾讯财经API: {missing_codes}")
            tencent_result = await cls._fetch_from_tencent_api(missing_codes)
            if tencent_result:
                logger.info(f"[MarketService] ✓ 腾讯财经API成功: {len(tencent_result)} 个")
                merge_quotes(tencent_result, "tencent_quote", "realtime")

        # 妙想提供最近完成交易日的场内报价；仅在实时源未覆盖时兜底。
        missing_codes = [code for code in core_missing() if cls._looks_like_listed_security_code(code)]
        if missing_codes and MiaoxiangService.enabled():
            try:
                mx_result = await MiaoxiangService.fetch_quotes(missing_codes)
                for code, quote in mx_result.items():
                    cls._log_quote_source(code, "miaoxiang_daily_quote", quote)
                merge_quotes(mx_result, "miaoxiang_daily_quote", "daily")
            except Exception as e:
                logger.info(f"[MarketService] 妙想报价异常: {type(e).__name__}")

        # ETF spot is retained for quote fallback and IOPV/premium enrichment. Its
        # failure must not keep stock and OTC codes cascading through price sources.
        etf_codes = [
            code for code in codes
            if cls._looks_like_listed_fund_code(code)
            and (
                cls._quote_needs_enrichment(result.get(code))
                or cls._quote_needs_iopv_enrichment(result.get(code))
            )
        ]
        if etf_codes:
            logger.info(f"[MarketService] >>> 尝试 AkShare ETF列表补价/IOPV: {etf_codes}")
            akshare_etf_result = await cls._fetch_from_akshare_etf_spot(etf_codes)
            if akshare_etf_result:
                logger.info(f"[MarketService] ✓ AkShare ETF实时列表成功: {len(akshare_etf_result)} 个")
                merge_quotes(akshare_etf_result, "eastmoney_etf_spot", "realtime")

        missing_codes = [
            code for code in core_missing()
            if cls._looks_like_listed_fund_code(code)
        ]
        if missing_codes:
            etf_result = await cls._fetch_from_eastmoney_api(missing_codes)
            if etf_result:
                logger.info(f"[MarketService] ✓ 东方财富ETF批量API成功: {len(etf_result)} 个")
                merge_quotes(etf_result, "eastmoney_etf_quote", "realtime")

        missing_codes = core_missing()
        if missing_codes:
            logger.info(f"[MarketService] >>> 尝试东方财富通用证券API: {missing_codes}")
            broad_result = await cls._fetch_from_eastmoney_quote_api(missing_codes)
            if broad_result:
                logger.info(f"[MarketService] ✓ 东方财富通用证券API成功: {len(broad_result)} 个")
                merge_quotes(broad_result, "eastmoney_quote", "realtime")

        missing_codes = core_missing()
        if missing_codes and settings.tushare_token.strip():
            logger.info(f"[MarketService] >>> 尝试 Tushare 数据源: {missing_codes}")
            tushare_result = await cls._fetch_from_tushare_api(missing_codes)
            if tushare_result:
                logger.info(f"[MarketService] ✓ Tushare成功: {len(tushare_result)} 个")
                merge_quotes(tushare_result, "tushare_daily_quote", "daily")

        missing_codes = cls._otc_fund_candidate_codes(codes, result)
        if missing_codes:
            logger.info(f"[MarketService] >>> 尝试场外基金每日净值数据源: {missing_codes}")
            fund_result = await cls._fetch_from_otc_fund_daily_api(missing_codes)
            if fund_result:
                logger.info(f"[MarketService] ✓ 场外基金每日净值API成功: {len(fund_result)} 个")
                merge_quotes(fund_result, "eastmoney_fund_nav", "nav")

        # This endpoint is only an optional intraday estimate now. The disclosed
        # NAV snapshot above remains the source of truth for OTC fund names/prices.
        missing_codes = cls._otc_fund_candidate_codes(codes, result)
        if missing_codes:
            logger.info(f"[MarketService] >>> 尝试场外基金估值备用源: {missing_codes}")
            fund_result = await cls._fetch_from_otc_fund_api(missing_codes)
            if fund_result:
                logger.info(f"[MarketService] ✓ 场外基金估值备用源成功: {len(fund_result)} 个")
                merge_quotes(fund_result, "eastmoney_fund_estimate", "estimate")

        if result:
            for code, quote in list(result.items()):
                result[code] = await cls.cache_quote(code, quote)

        missing_codes = [code for code in codes if code not in result]
        if missing_codes:
            logger.info(f"[MarketService] ✗ 部分品种所有数据源均失败，返回空数据: {missing_codes}")
            result.update(cls._get_empty_quotes(missing_codes))
        return result


    @classmethod
    def _parse_quotes_from_df(cls, codes: List[str], df: pd.DataFrame) -> Dict[str, MarketQuote]:
        """从DataFrame解析行情数据"""
        result = {}

        # 兼容不同数据源的列名
        code_col = "代码" if "代码" in df.columns else "code" if "code" in df.columns else df.columns[0]
        name_col = "名称" if "名称" in df.columns else "name" if "name" in df.columns else df.columns[1]
        price_col = "最新价" if "最新价" in df.columns else "收盘" if "收盘" in df.columns else df.columns[2]
        change_col = "涨跌幅" if "涨跌幅" in df.columns else df.columns[3] if len(df.columns) > 3 else None
        open_col = "今开" if "今开" in df.columns else None
        high_col = "最高" if "最高" in df.columns else None
        low_col = "最低" if "最低" in df.columns else None
        volume_col = "成交量" if "成交量" in df.columns else None
        amount_col = "成交额" if "成交额" in df.columns else None
        iopv_col = "IOPV实时估值" if "IOPV实时估值" in df.columns else "iopv" if "iopv" in df.columns else None
        discount_col = "基金折价率" if "基金折价率" in df.columns else None
        premium_col = "溢价率" if "溢价率" in df.columns else "premium_rate" if "premium_rate" in df.columns else None

        for code in codes:
            row = df[df[code_col] == code]
            if not row.empty:
                row = row.iloc[0]
                result[code] = MarketQuote(
                    code=code,
                    name=str(row.get(name_col, "")),
                    price=float(row.get(price_col, 0) or 0),
                    change_pct=float(row.get(change_col, 0) or 0) if change_col else 0.0,
                    open_price=float(row.get(open_col, 0)) if open_col and row.get(open_col) else None,
                    high_price=float(row.get(high_col, 0)) if high_col and row.get(high_col) else None,
                    low_price=float(row.get(low_col, 0)) if low_col and row.get(low_col) else None,
                    volume=cls._to_int(row.get(volume_col)) if volume_col else None,
                    amount=cls._to_float(row.get(amount_col)) if amount_col else None,
                    iopv=cls._to_float(row.get(iopv_col)) if iopv_col else None,
                    premium_rate=(cls._to_float(row.get(premium_col)) if premium_col else (-cls._to_float(row.get(discount_col)) if discount_col and cls._to_float(row.get(discount_col)) is not None else None)),
                )
        return result

    @classmethod
    def _get_empty_quotes(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """返回空行情数据（无数据时使用）"""
        result = {}
        for code in codes:
            result[code] = MarketQuote(
                code=code,
                name="",
                price=0.0,
                change_pct=0.0,
                open_price=None,
                high_price=None,
                low_price=None,
                volume=None,
                amount=None,
            )
        logger.info(f"[MarketService] 返回空数据 {len(result)} 只ETF")
        return result

    @classmethod
    async def search_etf(cls, query: str, limit: int = 20) -> List[EtfSearchResult]:
        """搜索ETF，AkShare 无结果时补充沪深交易所公开 ETF 列表。"""
        try:
            # akshare 仍是同步库，放到线程池里避免阻塞事件循环
            async with cls._ETF_SEARCH_LOCK:
                if cls._ETF_SEARCH_CACHE is None or time.monotonic() >= cls._ETF_SEARCH_EXPIRES_AT:
                    df = await asyncio.to_thread(ak.fund_etf_spot_em)
                    if df is not None and not df.empty:
                        cls._ETF_SEARCH_CACHE = df
                        cls._ETF_SEARCH_EXPIRES_AT = time.monotonic() + 900
                else:
                    df = cls._ETF_SEARCH_CACHE
            if df is not None and not df.empty:
                # 按代码或名称搜索
                mask = df["代码"].astype(str).str.contains(query, case=False, na=False, regex=False) | \
                       df["名称"].astype(str).str.contains(query, case=False, na=False, regex=False)
                result_df = df[mask].head(limit)

                results = []
                for _, row in result_df.iterrows():
                    code = str(row["代码"])
                    results.append(EtfSearchResult(
                        code=code,
                        name=str(row["名称"]),
                        category=cls._guess_category(str(row["名称"])),
                        exchange="SH" if code.startswith("5") else "SZ",
                    ))
                if results:
                    return results
        except Exception as e:
            logger.info(f"[MarketService] AkShare ETF搜索失败: {type(e).__name__}")

        results = await cls._search_sse_etf_catalog(query, limit)
        if len(results) < limit:
            szse_results = await SzseService.search(query, limit)
            seen = {item.code for item in results}
            results.extend(
                item.model_copy(update={"category": cls._guess_category(item.name)})
                for item in szse_results if item.code not in seen
            )
        return results[:limit]

    @staticmethod
    def _guess_category(name: str) -> str:
        """根据名称猜测ETF类别"""
        if any(k in name for k in ["货币", "现金", "短融", "同业存单"]):
            return "现金管理"
        elif any(k in name for k in ["国债", "地方债", "政金债", "信用债", "可转债", "债券"]):
            return "债券"
        elif any(k in name for k in ["沪深300", "中证500", "中证1000", "上证50", "创业板指", "深证100", "A50", "全指", "科创宽基"]):
            return "宽基指数"
        elif any(k in name for k in ["红利", "股息", "高股息", "央企红利"]):
            return "红利策略"
        elif any(k in name for k in ["恒生", "纳指", "纳斯达克", "标普", "日经", "德国", "法国", "海外", "全球", "美国", "港股"]):
            return "海外市场"
        elif any(k in name for k in ["医药", "医疗", "生物", "创新药", "疫苗", "中药"]):
            return "医药医疗"
        elif any(k in name for k in ["芯片", "半导体", "集成电路"]):
            return "半导体芯片"
        elif any(k in name for k in ["人工智能", "AI", "机器人", "算力", "通信", "5G", "软件", "云计算", "信息技术", "计算机", "科技"]):
            return "TMT/人工智能"
        elif any(k in name for k in ["消费", "食品", "饮料", "白酒", "家电", "养殖", "农业消费"]):
            return "消费"
        elif any(k in name for k in ["新能源", "光伏", "锂电", "电池", "储能", "风电", "电车", "新能源汽车"]):
            return "新能源"
        elif any(k in name for k in ["银行", "证券", "券商", "保险", "金融", "地产", "房地产"]):
            return "金融地产"
        elif any(k in name for k in ["军工", "国防", "航空航天"]):
            return "军工国防"
        elif any(k in name for k in ["黄金", "白银", "贵金属"]):
            return "贵金属"
        elif any(k in name for k in ["原油", "煤炭", "油气", "能源", "化工"]):
            return "能源化工"
        elif any(k in name for k in ["豆粕", "农产品", "农业", "饲料"]):
            return "农产品"
        elif any(k in name for k in ["REIT", "reits", "不动产"]):
            return "REITs"
        else:
            return "未分类"


    @staticmethod
    async def save_market_daily(session: AsyncSession, code: str, data: List[KLineItem]):
        """保存历史行情到数据库"""
        if not data:
            return
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        dialect = session.get_bind().dialect.name
        if dialect not in {"postgresql", "sqlite"}:
            raise ValueError(f"Unsupported market storage dialect: {dialect}")
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        # Deduplicate dates before PostgreSQL ON CONFLICT (one update per row).
        rows = {item.trade_date: {
            "etf_code": code, "trade_date": item.trade_date,
            "open_price": item.open_price, "close_price": item.close_price,
            "high_price": item.high_price, "low_price": item.low_price,
            "volume": item.volume, "amount": item.amount, "change_pct": item.change_pct,
            "source": item.source, "adjustment": item.adjustment, "amount_estimated": item.amount_estimated,
        } for item in data}
        values = list(rows.values())
        # Bound SQLite parameters; a 250-day history normally needs 4 statements.
        for offset in range(0, len(values), 64):
            statement = insert(MarketDaily).values(values[offset:offset + 64])
            statement = statement.on_conflict_do_update(
                index_elements=["etf_code", "trade_date"],
                set_={field: getattr(statement.excluded, field) for field in (
                    "open_price", "close_price", "high_price", "low_price", "volume", "amount", "change_pct", "source", "adjustment", "amount_estimated",
                )},
            )
            await session.execute(statement)

    @classmethod
    def _filter_today_intraday_items(cls, items: List[KLineItem]) -> List[KLineItem]:
        now = now_in_shanghai()
        today = now.date()
        market_start = datetime_time(9, 15)
        market_end = datetime_time(15, 0)
        filtered: List[KLineItem] = []
        for item in items:
            if item.trade_time is None:
                continue
            trade_time = item.trade_time.astimezone(SHANGHAI_TZ) if item.trade_time.tzinfo else item.trade_time.replace(tzinfo=SHANGHAI_TZ)
            if trade_time.date() != today:
                continue
            if trade_time > now:
                continue
            if not (market_start <= trade_time.time() <= market_end):
                continue
            filtered.append(item.model_copy(update={"trade_date": today, "trade_time": trade_time}))
        return filtered
