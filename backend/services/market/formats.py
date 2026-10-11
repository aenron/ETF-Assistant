import logging

logger = logging.getLogger("uvicorn.error.formats")

import pandas as pd
import math
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import select
import os


# 设置环境变量模拟浏览器
os.environ.setdefault('HTTP_USER_AGENT', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

from models import EtfInfo
from schemas.market import MarketQuote, KLineItem
from database import async_session_maker
from utils.timezone import SHANGHAI_TZ


class MarketFormatMixin:
    """formats market parsing and retrieval."""

    @classmethod
    def _build_default_headers(cls, referer: str) -> Dict[str, str]:
        return {
            "User-Agent": os.environ["HTTP_USER_AGENT"],
            "Referer": referer,
        }


    @staticmethod
    def _to_float(value: Any, divisor: float = 1.0) -> Optional[float]:
        try:
            if value in (None, "", "-", "--"):
                return None
            parsed = float(value)
            if math.isnan(parsed) or math.isinf(parsed):
                return None
            result = parsed / divisor
            if math.isnan(result) or math.isinf(result):
                return None
            return result
        except (TypeError, ValueError):
            return None


    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        try:
            if value in (None, "", "-", "--"):
                return None
            parsed = float(value)
            if math.isnan(parsed) or math.isinf(parsed):
                return None
            return int(parsed)
        except (TypeError, ValueError):
            return None


    @classmethod
    async def _resolve_quote_name(cls, code: str) -> str:
        cached = await cls.get_quote_from_cache(code)
        if cached and cached.name and cached.name != code:
            return cached.name
        try:
            async with async_session_maker() as session:
                result = await session.execute(select(EtfInfo).where(EtfInfo.code == code))
                info = result.scalar_one_or_none()
                if info and info.name:
                    return info.name
        except Exception as e:
            logger.info(f"[MarketService] 解析ETF名称失败: {code}, {e}")
        return ""


    @staticmethod
    def _merge_quote(existing: MarketQuote, incoming: MarketQuote) -> MarketQuote:
        return existing.model_copy(
            update={
                "name": existing.name or incoming.name,
                "price": existing.price if existing.price > 0 else incoming.price,
                "change_pct": existing.change_pct if existing.change_pct is not None else incoming.change_pct,
                "open_price": existing.open_price if existing.open_price is not None else incoming.open_price,
                "high_price": existing.high_price if existing.high_price is not None else incoming.high_price,
                "low_price": existing.low_price if existing.low_price is not None else incoming.low_price,
                "volume": existing.volume if existing.volume is not None else incoming.volume,
                "amount": existing.amount if existing.amount is not None else incoming.amount,
                "iopv": existing.iopv if existing.iopv is not None else incoming.iopv,
                "premium_rate": existing.premium_rate if existing.premium_rate is not None else incoming.premium_rate,
                "refreshed_at": existing.refreshed_at if existing.price > 0 else incoming.refreshed_at,
                "source": existing.source if existing.price > 0 else incoming.source,
                "quote_type": existing.quote_type if existing.price > 0 else incoming.quote_type,
            }
        )


    @staticmethod
    def _quote_needs_enrichment(quote: MarketQuote | None) -> bool:
        """Whether the core quote (name and a valid price) needs a fallback."""
        return quote is None or not quote.name or quote.price <= 0


    @staticmethod
    def _quote_needs_iopv_enrichment(quote: MarketQuote | None) -> bool:
        """IOPV is optional and applies only to listed funds, not stocks or OTC funds."""
        return quote is not None and quote.iopv is None and quote.premium_rate is None


    @staticmethod
    def _looks_like_listed_security_code(code: str) -> bool:
        clean = str(code or "").strip().upper()
        if not clean.isdigit() or len(clean) != 6:
            return clean.startswith(("BK", "GN"))
        return clean.startswith((
            "5", "15", "16", "18",
            "000", "002", "003", "300", "301",
            "600", "601", "603", "605", "688",
            "399", "88",
        ))


    @staticmethod
    def _looks_like_listed_fund_code(code: str) -> bool:
        clean = str(code or "").strip()
        return (
            len(clean) == 6
            and clean.isdigit()
            and clean.startswith(("50", "51", "52", "56", "58", "59", "15", "16", "18"))
        )


    @classmethod
    def _items_from_ohlcv_df(cls, df: pd.DataFrame, days: int = 60) -> List[KLineItem]:
        if df is None or df.empty:
            return []
        df = df.tail(days)
        result = []
        date_col = "日期" if "日期" in df.columns else "date" if "date" in df.columns else df.columns[0]
        open_col = "开盘" if "开盘" in df.columns else "open" if "open" in df.columns else None
        close_col = "收盘" if "收盘" in df.columns else "close" if "close" in df.columns else None
        high_col = "最高" if "最高" in df.columns else "high" if "high" in df.columns else None
        low_col = "最低" if "最低" in df.columns else "low" if "low" in df.columns else None
        volume_col = "成交量" if "成交量" in df.columns else "volume" if "volume" in df.columns else None
        amount_col = "成交额" if "成交额" in df.columns else "amount" if "amount" in df.columns else None
        change_col = "涨跌幅" if "涨跌幅" in df.columns else None
        if not all([open_col, close_col, high_col, low_col]):
            return []

        for _, row in df.iterrows():
            close = float(row[close_col])
            if change_col and row.get(change_col) not in (None, ""):
                change_pct = float(row[change_col])
            elif result and result[-1].close_price > 0:
                change_pct = (close - result[-1].close_price) / result[-1].close_price * 100
            else:
                change_pct = 0.0

            result.append(KLineItem(
                trade_date=row[date_col] if isinstance(row[date_col], date) else date.fromisoformat(str(row[date_col]).split(" ")[0]),
                open_price=float(row[open_col]),
                close_price=close,
                high_price=float(row[high_col]),
                low_price=float(row[low_col]),
                volume=cls._to_int(row.get(volume_col)) or 0 if volume_col else 0,
                amount=cls._to_float(row.get(amount_col)) if amount_col else None,
                change_pct=round(change_pct, 2),
            ))
        return result


    @staticmethod
    def _timestamp_to_datetime(value: Any) -> Optional[datetime]:
        if value in (None, "", "-"):
            return None
        text = str(value).strip()
        try:
            if text.isdigit():
                if text.startswith(("19", "20")) and len(text) >= 14:
                    parsed = datetime.strptime(text[:14], "%Y%m%d%H%M%S")
                    return parsed.replace(tzinfo=SHANGHAI_TZ)
                if text.startswith(("19", "20")) and len(text) >= 12:
                    parsed = datetime.strptime(text[:12], "%Y%m%d%H%M")
                    return parsed.replace(tzinfo=SHANGHAI_TZ)
                if text.startswith(("19", "20")) and len(text) >= 8:
                    parsed = datetime.strptime(text[:8], "%Y%m%d")
                    return parsed.replace(tzinfo=SHANGHAI_TZ)
                if len(text) >= 13:
                    return datetime.fromtimestamp(int(text[:13]) / 1000, tz=SHANGHAI_TZ)
                if len(text) >= 10:
                    return datetime.fromtimestamp(int(text[:10]), tz=SHANGHAI_TZ)
            normalized = text.replace("T", " ")
            parsed = datetime.fromisoformat(normalized)
            return parsed.astimezone(SHANGHAI_TZ) if parsed.tzinfo else parsed.replace(tzinfo=SHANGHAI_TZ)
        except Exception:
            return None
