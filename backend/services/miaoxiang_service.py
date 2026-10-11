import logging

logger = logging.getLogger("uvicorn.error.miaoxiang_service")

from services.market.http_client import market_http_client
"""Read-only adapter for the official mx-data API, without the skill's file exports."""

import asyncio
import hashlib
import math
import re
import time
from datetime import date, datetime, timedelta, time as datetime_time
from typing import Any

import httpx

from config import settings
from schemas.market import KLineItem, MarketQuote
from utils.timezone import SHANGHAI_TZ, now_in_shanghai


class MiaoxiangService:
    URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
    _lock = asyncio.Lock()
    _last_request = 0.0
    _blocked_until = 0.0
    _cache: dict[str, tuple[float, dict]] = {}
    _sources = {
        "OPEN": "open_price", "HIGH": "high_price", "LOW": "low_price",
        "CLOSE": "close_price", "PRE_CLOSE": "prev_close",
        "VOLUME": "volume", "AMOUNT": "amount",
        "f2": "close_price", "f17": "open_price", "f15": "high_price",
        "f16": "low_price", "f18": "prev_close", "f5": "volume", "f6": "amount",
    }
    _labels = {
        "开盘价": "open_price", "今开": "open_price",
        "最高价": "high_price", "最低价": "low_price",
        "收盘价": "close_price", "最新价": "close_price",
        "前收盘价": "prev_close", "昨收": "prev_close",
        "成交量": "volume", "成交额": "amount",
    }

    @staticmethod
    def enabled() -> bool:
        return settings.mx_enabled and bool(settings.mx_apikey.get_secret_value().strip())

    @staticmethod
    def symbol(code: str) -> str | None:
        text = str(code).strip().upper()
        if re.fullmatch(r"\d{6}\.(SH|SZ)", text):
            return text
        if re.fullmatch(r"(SH|SZ)\d{6}", text):
            return f"{text[2:]}.{text[:2]}"
        if re.fullmatch(r"\d{6}", text):
            if text.startswith(("5", "6", "9")):
                return f"{text}.SH"
            if text.startswith(("0", "1", "2", "3")):
                return f"{text}.SZ"
        return None

    @classmethod
    def _business_error(cls, payload: dict) -> int | None:
        current = payload
        for _ in range(6):
            if not isinstance(current, dict):
                break
            if current.get("success") is False or current.get("status", 0) not in (0, "0", None):
                try:
                    return int(current.get("code", -1))
                except (ValueError, TypeError):
                    return -1
            if "code" in current and str(current["code"]) not in ("0", "100", "200", "None"):
                try:
                    return int(current["code"])
                except (ValueError, TypeError):
                    return -1
            current = current.get("data")
        return None

    @classmethod
    async def _query(cls, query: str, ttl: int) -> dict:
        if not cls.enabled():
            return {}
        key = hashlib.sha256((settings.mx_apikey.get_secret_value() + query).encode()).hexdigest()
        async with cls._lock:
            now = time.monotonic()
            cached = cls._cache.get(key)
            if cached and cached[0] > now:
                return cached[1]
            if now < cls._blocked_until:
                return {}
            wait = settings.mx_min_interval_seconds - (now - cls._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                cls._last_request = time.monotonic()
                async with market_http_client(timeout=settings.mx_timeout_seconds) as client:
                    response = await client.post(
                        cls.URL,
                        headers={"apikey": settings.mx_apikey.get_secret_value()},
                        json={"toolQuery": query},
                    )
                    response.raise_for_status()
                    payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Invalid response")
                error = cls._business_error(payload)
                if error is not None:
                    cls._blocked_until = time.monotonic() + (3600 if error in (113, 114, 401, 403) else 60)
                    logger.info(f"[Miaoxiang] 查询失败，进入冷却: code={error}")
                    return {}
            except Exception as exc:
                cls._blocked_until = time.monotonic() + 60
                # Never log headers, the request, the key, or provider error text.
                logger.info(f"[Miaoxiang] 请求失败，进入冷却: {type(exc).__name__}")
                return {}
            now = time.monotonic()
            cls._cache = {k: v for k, v in cls._cache.items() if v[0] > now}
            if len(cls._cache) >= 128:
                cls._cache.pop(next(iter(cls._cache)))
            cls._cache[key] = (now + ttl, payload)
            return payload

    @classmethod
    def _tables(cls, payload: Any, depth: int = 0) -> list[dict]:
        if depth > 6 or not isinstance(payload, dict):
            return []
        if isinstance(payload.get("dataTableDTOList"), list):
            return [x for x in payload["dataTableDTOList"] if isinstance(x, dict)]
        for key in ("data", "searchDataResultDTO"):
            found = cls._tables(payload.get(key), depth + 1)
            if found:
                return found
        return []

    @staticmethod
    def _date(value: Any) -> date | None:
        text = str(value or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:\(日\))?", text):
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None

    @staticmethod
    def _number(value: Any, unit: str = "") -> float | None:
        if isinstance(value, bool):
            return None
        text = str(value).strip().replace(",", "")
        match = re.fullmatch(r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(亿|万|千)?\s*(元|股|手)?", text)
        if not match:
            return None
        result = float(match[1])
        suffix = (match[2] or "") + (match[3] or "") or unit
        if "亿" in suffix:
            result *= 1e8
        elif "万" in suffix:
            result *= 1e4
        elif "千" in suffix:
            result *= 1e3
        if "手" in suffix:
            result *= 100
        return result if math.isfinite(result) else None

    @classmethod
    def _rows(cls, payload: dict, symbol: str) -> tuple[str, dict[date, dict[str, float]]]:
        if cls._business_error(payload) is not None:
            return "", {}
        rows: dict[date, dict[str, float]] = {}
        name = ""
        for dto in cls._tables(payload):
            # Full symbol matching prevents returning another security's data.
            if str(dto.get("code", "")).upper() != symbol:
                continue
            tag = dto.get("entityTagDTO") or {}
            if not isinstance(tag, dict):
                tag = {}
            name = name or tag.get("shortName") or dto.get("entityName") or symbol
            table = dto.get("rawTable") or dto.get("table") or {}
            if not isinstance(table, dict) or not isinstance(table.get("headName"), list):
                continue
            field_set = dto.get("fieldSet") or []
            metadata = {str(f.get("returnCode")): f for f in field_set if isinstance(f, dict)} if isinstance(field_set, list) else {}
            if isinstance(dto.get("field"), dict):
                field = dto["field"]
                metadata.setdefault(str(field.get("returnCode")), field)
            names = dto.get("nameMap") or {}
            if not isinstance(names, dict):
                names = {}
            for key, values in table.items():
                if key == "headName" or not isinstance(values, list):
                    continue
                field = metadata.get(str(key), {})
                label = str(names.get(key) or field.get("returnName") or "")
                if any(word in label for word in ("净值", "复权", "区间", "基准")):
                    continue
                target = cls._sources.get(field.get("returnSourceCode")) or cls._labels.get(label)
                if not target:
                    continue
                unit = str(field.get("unitName") or "")
                for when, value in zip(table["headName"], values):
                    day = cls._date(when)
                    number = cls._number(value, unit)
                    if day is not None and number is not None and number >= 0:
                        rows.setdefault(day, {}).setdefault(target, number)
        return str(name), rows

    @staticmethod
    def _completed_date() -> date:
        now = now_in_shanghai()
        day = now.date()
        if now.time() < datetime_time(15, 10):
            day -= timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        return day

    @classmethod
    def parse_quote(cls, code: str, payload: dict) -> MarketQuote | None:
        symbol = cls.symbol(code)
        if not symbol:
            return None
        name, rows = cls._rows(payload, symbol)
        completed = cls._completed_date()
        dates = sorted(day for day in rows if day <= completed and rows[day].get("close_price", 0) > 0)
        if not dates or dates[-1] < completed - timedelta(days=10):
            return None
        day = dates[-1]
        row = rows[day]
        previous = row.get("prev_close") or (rows[dates[-2]]["close_price"] if len(dates) > 1 else None)
        if not previous or previous <= 0:
            return None
        change_pct = (row["close_price"] / previous - 1) * 100
        if not math.isfinite(change_pct):
            return None
        return MarketQuote(
            code=code, name=name, price=row["close_price"],
            change_pct=round(change_pct, 4),
            open_price=row.get("open_price"), high_price=row.get("high_price"), low_price=row.get("low_price"),
            volume=int(row["volume"]) if "volume" in row else None, amount=row.get("amount"),
            # These are completed daily bars, never fabricate a live quote timestamp.
            refreshed_at=datetime.combine(day, datetime_time(15), tzinfo=SHANGHAI_TZ),
        )

    @classmethod
    def parse_history(cls, code: str, payload: dict, days: int) -> list[KLineItem]:
        symbol = cls.symbol(code)
        if not symbol or days <= 0:
            return []
        _, rows = cls._rows(payload, symbol)
        result = []
        for day, row in sorted(rows.items()):
            if day > cls._completed_date() or not all(k in row for k in ("open_price", "high_price", "low_price", "close_price", "volume", "amount")):
                continue
            if not (0 < row["low_price"] <= min(row["open_price"], row["close_price"]) <= max(row["open_price"], row["close_price"]) <= row["high_price"]):
                continue
            previous = row.get("prev_close") or (result[-1].close_price if result else row["open_price"])
            result.append(KLineItem(
                trade_date=day, open_price=row["open_price"], high_price=row["high_price"],
                low_price=row["low_price"], close_price=row["close_price"], volume=int(row["volume"]),
                amount=row["amount"], change_pct=round((row["close_price"] / previous - 1) * 100, 4),
            ))
        if len(result) < days or not result or result[-1].trade_date < cls._completed_date() - timedelta(days=10):
            return []
        return result[-days:]

    @classmethod
    async def fetch_quotes(cls, codes: list[str]) -> dict[str, MarketQuote]:
        if not cls.enabled():
            return {}
        candidates = list(dict.fromkeys(code for code in codes if cls.symbol(code)))
        result = {}
        for start in range(0, len(candidates), 5):
            batch = candidates[start:start + 5]
            symbols = "、".join(cls.symbol(code) for code in batch)
            query = f"{symbols} 场内证券最近两个交易日的收盘价、前收盘价、开盘价、最高价、最低价、成交量、成交额（不复权）"
            payload = await cls._query(query, settings.mx_quote_cache_seconds)
            for code in batch:
                quote = cls.parse_quote(code, payload)
                if quote:
                    result[code] = quote
        return result

    @classmethod
    async def fetch_history(cls, code: str, days: int = 60) -> list[KLineItem]:
        symbol = cls.symbol(code)
        if not cls.enabled() or not symbol or not 1 <= days <= 250:
            return []
        query = f"{symbol} 最近{days + 1}个交易日的每日收盘价、开盘价、最高价、最低价、成交量、成交额、不复权"
        payload = await cls._query(query, settings.mx_history_cache_seconds)
        return cls.parse_history(code, payload, days)
