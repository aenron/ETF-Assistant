import logging

logger = logging.getLogger("uvicorn.error.szse_service")

from services.market.http_client import market_http_client
"""Public SZSE website feeds. Prices in yuan, volumes normalized to shares."""

import asyncio
import html
import math
import re
import time
from datetime import date, datetime, time as daytime
from typing import Any

import httpx

from config import settings
from schemas.market import EtfSearchResult, KLineItem, MarketQuote
from utils.timezone import SHANGHAI_TZ, now_in_shanghai


class SzseService:
    BASE_URL = "https://www.szse.cn/api"
    REFERER = "https://fund.szse.cn/marketdata/trade/index.html"
    _cache: dict[tuple, tuple[float, Any]] = {}
    _locks: dict[tuple, asyncio.Lock] = {}
    _cooldown_until = 0.0

    @staticmethod
    def supports(code: str) -> bool:
        # Only route Shenzhen listed funds, never OTC funds or Shanghai codes.
        return bool(re.fullmatch(r"15\d{4}", str(code)))

    @staticmethod
    def number(value: Any) -> float | None:
        try:
            result = float(str(value).replace(",", ""))
            return result if math.isfinite(result) else None
        except (ValueError, TypeError):
            return None

    @classmethod
    async def _get(cls, path: str, params: dict, ttl: int) -> Any:
        if not settings.szse_enabled or time.monotonic() < cls._cooldown_until:
            return None
        key = (path, tuple(sorted(params.items())))
        cached = cls._cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        # Reuse locks for concurrent refreshes, but bound memory for searches.
        if key not in cls._locks and len(cls._locks) >= 256:
            for old_key, lock in list(cls._locks.items()):
                if not lock.locked():
                    cls._locks.pop(old_key)
                    break
        async with cls._locks.setdefault(key, asyncio.Lock()):
            cached = cls._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            if time.monotonic() < cls._cooldown_until:
                return None
            try:
                async with market_http_client(timeout=8.0) as client:
                    response = await client.get(
                        cls.BASE_URL + path, params=params,
                        headers={"User-Agent": "Mozilla/5.0", "Referer": cls.REFERER},
                    )
                    response.raise_for_status()
                    payload = response.json()
                if isinstance(payload, dict) and str(payload.get("code")) != "0":
                    raise ValueError("SZSE response status")
                if not isinstance(payload, (dict, list)):
                    raise ValueError("SZSE response shape")
                if len(cls._cache) >= 256:
                    cls._cache.pop(next(iter(cls._cache)))
                cls._cache[key] = (time.monotonic() + ttl, payload)
                return payload
            except Exception as exc:
                cls._cooldown_until = time.monotonic() + 60
                logger.info(f"[SzseService] 公开数据请求失败: {type(exc).__name__}")
                return None

    @classmethod
    def _data(cls, code: str, payload: Any) -> dict:
        if not isinstance(payload, dict) or str(payload.get("code")) != "0":
            return {}
        data = payload.get("data")
        if not isinstance(data, dict) or str(data.get("code")) != code:
            return {}
        return data

    @classmethod
    def parse_quote(cls, code: str, payload: Any) -> MarketQuote | None:
        data = cls._data(code, payload)
        if not data or data.get("isPurposeful") is True:
            return None
        values = [cls.number(data.get(k)) for k in ("now", "open", "high", "low")]
        if any(v is None or v <= 0 for v in values):
            return None
        price, opening, high, low = values
        if not low <= min(price, opening) <= max(price, opening) <= high:
            return None
        try:
            stamp = datetime.fromisoformat(data.get("marketTime") or payload["datetime"]).replace(tzinfo=SHANGHAI_TZ)
        except (ValueError, TypeError, KeyError):
            return None
        age = (now_in_shanghai() - stamp).total_seconds()
        if age < -60 or age > 10 * 86400:
            return None
        prev = cls.number(data.get("close"))
        change = cls.number(data.get("deltaPercent"))
        if change is None and prev and prev > 0:
            change = (price / prev - 1) * 100
        if change is None:
            return None
        volume, amount = cls.number(data.get("volume")), cls.number(data.get("amount"))
        # netValue is not guaranteed to be intraday IOPV. Use only dated piciopv
        # observations during the trading session, never post-close zero padding.
        iopv = None
        points = data.get("piciopv")
        if isinstance(points, list):
            for row in points:
                if not isinstance(row, list) or len(row) < 2:
                    continue
                try:
                    point_time = daytime.fromisoformat(row[0])
                except (ValueError, TypeError):
                    continue
                value = cls.number(row[1])
                if daytime(9, 30) <= point_time <= min(stamp.time(), daytime(15)) and value and value > 0:
                    iopv = value
        return MarketQuote(
            code=code, name=str(data.get("name") or ""), price=price, change_pct=change,
            open_price=opening, high_price=high, low_price=low,
            volume=int(volume * 100) if volume is not None and volume >= 0 else None,
            amount=amount if amount is not None and amount >= 0 else None,
            iopv=iopv, premium_rate=(price / iopv - 1) * 100 if iopv else None,
            refreshed_at=stamp,
        )

    @classmethod
    async def fetch_quotes(cls, codes: list[str]) -> dict[str, MarketQuote]:
        result = {}
        # Keep official website requests sequential rather than fan out per symbol.
        for code in dict.fromkeys(codes):
            if not cls.supports(code):
                continue
            payload = await cls._get("/market/ssjjhq/getTimeData", {"marketId": 1, "code": code}, 20)
            quote = cls.parse_quote(code, payload)
            if quote:
                result[code] = quote
        return result

    @classmethod
    def parse_history(cls, code: str, payload: Any, days: int) -> list[KLineItem]:
        data = cls._data(code, payload)
        rows = data.get("picupdata")
        if not isinstance(rows, list):
            return []
        current = now_in_shanghai()
        items = {}
        for row in rows:
            if not isinstance(row, list) or len(row) < 9:
                continue
            try:
                trade_date = date.fromisoformat(row[0])
            except (TypeError, ValueError):
                continue
            if trade_date > current.date() or (trade_date == current.date() and current.time() < daytime(15, 10)):
                continue
            # Website order: date, open, close, low, high, delta, delta%, lots, yuan.
            opening, close, low, high, change, volume, amount = [cls.number(row[i]) for i in (1, 2, 3, 4, 6, 7, 8)]
            if any(v is None for v in (opening, close, low, high, change, volume, amount)):
                continue
            if low <= 0 or not low <= min(opening, close) <= max(opening, close) <= high or volume < 0 or amount < 0:
                continue
            items[trade_date] = KLineItem(
                trade_date=trade_date, open_price=opening, close_price=close,
                low_price=low, high_price=high, change_pct=change,
                volume=int(volume * 100), amount=amount,
            )
        result = [items[key] for key in sorted(items)]
        # The public feed is a fixed ~200-bar window. Let deeper providers satisfy
        # requests for 250 bars rather than caching a shortened history as complete.
        if len(result) < days or not result or (current.date() - result[-1].trade_date).days > 10:
            return []
        return result[-days:]

    @classmethod
    async def fetch_history(cls, code: str, days: int = 60) -> list[KLineItem]:
        if not cls.supports(code) or days <= 0:
            return []
        payload = await cls._get("/market/ssjjhq/getHistoryData", {"marketId": 1, "code": code, "cycleType": 32}, 300)
        return cls.parse_history(code, payload, days)

    @staticmethod
    def _plain(value: Any) -> str:
        return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()

    @classmethod
    async def search(cls, query: str, limit: int = 20) -> list[EtfSearchResult]:
        if limit <= 0:
            return []
        params = {"CATALOGID": "fund_etf", "TABKEY": "tab1", "PAGENO": 1, "txtQueryKeyAndJC": query}
        results = {}
        for page in range(1, 1 + min(20, (limit + 9) // 10)):
            params["PAGENO"] = page
            payload = await cls._get("/report/ShowReport/data", params, 900)
            if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
                break
            table = payload[0]
            rows = table.get("data")
            if not isinstance(rows, list):
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code, name = cls._plain(row.get("sys_key")), cls._plain(row.get("kzjcurl"))
                if cls.supports(code) and name and (query.casefold() in code.casefold() or query.casefold() in name.casefold()):
                    results[code] = EtfSearchResult(code=code, name=name, exchange="SZ")
            metadata = table.get("metadata")
            pagecount = cls.number(metadata.get("pagecount")) if isinstance(metadata, dict) else None
            if len(results) >= limit or page >= (pagecount or 1):
                break
        return list(results.values())[:limit]
