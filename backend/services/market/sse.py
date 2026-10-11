import logging

logger = logging.getLogger("uvicorn.error.sse")

from services.market.http_client import market_http_client
import asyncio
from datetime import date, datetime, timedelta, time as datetime_time
from typing import Optional, List, Dict, Any
from sqlalchemy import select
import time
import json


# 设置环境变量模拟浏览器

from schemas.market import MarketQuote, KLineItem, EtfSearchResult
from utils.timezone import SHANGHAI_TZ, now_in_shanghai


from services.market.formats import MarketFormatMixin

class SseProviderMixin(MarketFormatMixin):
    """sse market parsing and retrieval."""

    @staticmethod
    def _sse_code_supported(code: str) -> bool:
        """The SSE sh1 web feed covers Shanghai-listed security codes only."""
        clean = str(code or "").strip()
        return len(clean) == 6 and clean.isdigit() and clean.startswith(("5", "6", "9"))


    @staticmethod
    def _parse_sse_jsonp(text: str) -> Any:
        """Decode the JSON/JSONP bodies used by SSE's public web pages."""
        body = str(text or "").strip()
        if not body:
            return None
        if body.endswith(";"):
            body = body[:-1].rstrip()
        if not body.startswith(("{", "[")):
            open_paren = body.find("(")
            close_paren = body.rfind(")")
            if open_paren < 0 or close_paren <= open_paren:
                return None
            body = body[open_paren + 1:close_paren].strip()
        try:
            return json.loads(body)
        except (TypeError, ValueError):
            return None


    @staticmethod
    def _sse_timestamp_to_datetime(value: Any) -> Optional[datetime]:
        if value in (None, "", "-", "--"):
            return None
        if isinstance(value, datetime):
            return value.astimezone(SHANGHAI_TZ) if value.tzinfo else value.replace(tzinfo=SHANGHAI_TZ)
        text = str(value).strip()
        if text.endswith(".0"):
            text = text[:-2]
        digits = text.replace("-", "").replace(":", "").replace(" ", "")
        try:
            if digits.isdigit() and len(digits) >= 14:
                return datetime.strptime(digits[:14], "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI_TZ)
            if digits.isdigit() and len(digits) >= 12:
                return datetime.strptime(digits[:12], "%Y%m%d%H%M").replace(tzinfo=SHANGHAI_TZ)
            if digits.isdigit() and len(digits) == 8:
                return datetime.strptime(digits, "%Y%m%d").replace(tzinfo=SHANGHAI_TZ)
            return MarketFormatMixin._timestamp_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return MarketFormatMixin._timestamp_to_datetime(value)


    @classmethod
    def _sse_row_parts(cls, row: Any) -> List[Any]:
        if isinstance(row, str):
            return row.split(",")
        if isinstance(row, (list, tuple)):
            return list(row)
        if isinstance(row, dict):
            return [
                row.get("date") or row.get("time"),
                row.get("open"),
                row.get("high"),
                row.get("low"),
                row.get("close"),
                row.get("volume"),
                row.get("amount"),
            ]
        return []


    @classmethod
    def _parse_sse_snapshot(cls, code: str, payload: Any) -> Optional[MarketQuote]:
        if not isinstance(payload, dict):
            return None
        snap = payload.get("snap")
        if isinstance(snap, dict):
            name = str(snap.get("name") or "").strip()
            price = cls._to_float(snap.get("last") or snap.get("price"))
            prev_close = cls._to_float(snap.get("prevclose") or snap.get("prev_close"))
            change_pct = cls._to_float(snap.get("changepercent") or snap.get("change_pct"))
            change = cls._to_float(snap.get("change"))
            open_price = cls._to_float(snap.get("open"))
            high = cls._to_float(snap.get("high"))
            low = cls._to_float(snap.get("low"))
            volume = cls._to_int(snap.get("volume"))
            amount = cls._to_float(snap.get("amount"))
        elif isinstance(snap, (list, tuple)) and len(snap) >= 8:
            name = str(snap[0] or "").strip()
            price = cls._to_float(snap[1])
            change_pct = cls._to_float(snap[2])
            change = cls._to_float(snap[3])
            amount = cls._to_float(snap[4])
            volume = cls._to_int(snap[5])
            open_price = cls._to_float(snap[6])
            prev_close = cls._to_float(snap[7])
            high = cls._to_float(snap[10]) if len(snap) > 10 else None
            low = cls._to_float(snap[11]) if len(snap) > 11 else None
        else:
            return None

        if price is None or price <= 0:
            return None
        # The SSE web endpoint currently omits prevclose and changepercent for
        # some securities while still returning the absolute daily change.
        if prev_close is None and change is not None and price - change > 0:
            prev_close = price - change
        if change_pct is None and prev_close and prev_close > 0 and change is not None:
            change_pct = change / prev_close * 100
        if change_pct is None and prev_close and prev_close > 0:
            change_pct = (price - prev_close) / prev_close * 100
        return MarketQuote(
            code=code,
            refreshed_at=cls._timestamp_to_datetime(f"{payload.get('date', '')}{str(payload.get('time', '')).zfill(6)}"),
            name=name,
            price=price,
            change_pct=round(change_pct or 0.0, 2),
            open_price=open_price,
            high_price=high,
            low_price=low,
            volume=volume,
            amount=amount,
        )


    @classmethod
    async def _fetch_from_sse_api(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """Fetch Shanghai-listed quotes from the SSE ETF quote page's web feed."""
        candidates = list(dict.fromkeys(code for code in codes if cls._sse_code_supported(code)))
        if not candidates:
            return {}

        url = f"{cls.SSE_MARKET_DATA_BASE_URL}/snap"
        select = "name,last,changepercent,change,amount,volume,open,prevclose,ask,bid,high,low,tradephase"
        headers = cls._build_default_headers(cls.SSE_MARKET_DATA_REFERER)
        result: Dict[str, MarketQuote] = {}
        semaphore = asyncio.Semaphore(8)

        async with market_http_client(timeout=8.0) as client:
            async def fetch_one(code: str) -> Optional[MarketQuote]:
                async with semaphore:
                    try:
                        # The callback must precede select for the endpoint to return
                        # the same JSONP shape used by the SSE page.
                        params = [("callback", "cb"), ("select", select)]
                        response = await client.get(f"{url}/{code}", params=params, headers=headers)
                        response.raise_for_status()
                        quote = cls._parse_sse_snapshot(code, cls._parse_sse_jsonp(response.text))
                        if not quote:
                            logger.info(f"[MarketService] 上交所快照解析为空: {code}")
                        return quote
                    except Exception as e:
                        logger.info(f"[MarketService] 上交所快照获取失败: {code}, {type(e).__name__}")
                        return None

            quotes = await asyncio.gather(*(fetch_one(code) for code in candidates))
        for quote in quotes:
            if quote:
                result[quote.code] = quote
        if result:
            logger.info(f"[MarketService] ✓ 上交所实时行情成功: {len(result)}/{len(candidates)} 个")
        return result


    @classmethod
    async def _fetch_sse_etf_catalog(cls) -> Dict[str, str]:
        """Fetch and briefly cache the ETF code/name list exposed by SSE's quote page."""
        now = time.time()
        if cls._SSE_ETF_CATALOG_CACHE and now < cls._SSE_ETF_CATALOG_EXPIRES_AT:
            return dict(cls._SSE_ETF_CATALOG_CACHE)

        url = f"{cls.SSE_MARKET_DATA_BASE_URL}/list/exchange/ebs"
        params = [
            ("callback", "cb"),
            ("select", "code,name,last"),
            ("begin", "0"),
            ("end", "-1"),
        ]
        headers = cls._build_default_headers(cls.SSE_MARKET_DATA_REFERER)
        try:
            async with market_http_client(timeout=8.0) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
            payload = cls._parse_sse_jsonp(response.text)
        except Exception as e:
            logger.info(f"[MarketService] 上交所ETF列表获取失败: {type(e).__name__}")
            return dict(cls._SSE_ETF_CATALOG_CACHE)

        rows = payload.get("list") if isinstance(payload, dict) else None
        if not isinstance(rows, list) and isinstance(payload, dict):
            rows = payload.get("data")
        if not isinstance(rows, list):
            return dict(cls._SSE_ETF_CATALOG_CACHE)

        catalog: Dict[str, str] = {}
        for row in rows:
            if isinstance(row, dict):
                raw_code = row.get("code") or row.get("CODE") or row.get("symbol")
                name = row.get("name") or row.get("NAME") or row.get("short_name")
            else:
                parts = cls._sse_row_parts(row)
                raw_code = parts[0] if parts else None
                name = parts[1] if len(parts) > 1 else None
            code = str(raw_code or "").strip()
            if code.endswith(".0"):
                code = code[:-2]
            if code.isdigit():
                code = code.zfill(6)
            display_name = str(name or "").strip()
            if len(code) == 6 and code.isdigit() and display_name:
                catalog[code] = display_name

        if catalog:
            cls._SSE_ETF_CATALOG_CACHE = catalog
            cls._SSE_ETF_CATALOG_EXPIRES_AT = now + cls.SSE_ETF_CATALOG_CACHE_TTL
            logger.info(f"[MarketService] ✓ 上交所ETF列表获取到 {len(catalog)} 个")
        return catalog


    @classmethod
    async def _search_sse_etf_catalog(cls, query: str, limit: int) -> List[EtfSearchResult]:
        catalog = await cls._fetch_sse_etf_catalog()
        normalized_query = str(query or "").strip().casefold()
        results: List[EtfSearchResult] = []
        for code, name in catalog.items():
            if normalized_query not in code.casefold() and normalized_query not in name.casefold():
                continue
            results.append(EtfSearchResult(
                code=code,
                name=name,
                category=cls._guess_category(name),
                exchange="SH",
            ))
            if len(results) >= limit:
                break
        return results


    @classmethod
    async def _fetch_history_kline_sse(cls, code: str, days: int = 60) -> List[KLineItem]:
        """Fetch Shanghai-listed daily bars from the public SSE web feed."""
        if not cls._sse_code_supported(code):
            return []
        safe_days = max(1, min(int(days), 365))
        url = f"{cls.SSE_MARKET_DATA_BASE_URL}/dayk/{code}"
        params = [
            ("callback", "cb"),
            ("begin", f"-{safe_days + 5}"),
            ("end", "-1"),
            ("period", "day"),
        ]
        headers = cls._build_default_headers(cls.SSE_MARKET_DATA_REFERER)
        try:
            async with market_http_client(timeout=8.0) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
            payload = cls._parse_sse_jsonp(response.text)
        except Exception as e:
            logger.info(f"[MarketService] 上交所日线请求失败: {code}, {type(e).__name__}")
            return []

        rows = payload.get("kline") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []

        parsed_rows: List[tuple[date, float, float, float, float, int, Optional[float]]] = []
        for row in rows:
            parts = cls._sse_row_parts(row)
            if len(parts) < 6:
                continue
            trade_time = cls._sse_timestamp_to_datetime(parts[0])
            open_price = cls._to_float(parts[1])
            high = cls._to_float(parts[2])
            low = cls._to_float(parts[3])
            close = cls._to_float(parts[4])
            if trade_time is None or None in (open_price, high, low, close) or close <= 0:
                continue
            parsed_rows.append((
                trade_time.date(),
                open_price,
                high,
                low,
                close,
                cls._to_int(parts[5]) or 0,
                cls._to_float(parts[6]) if len(parts) > 6 else None,
            ))

        parsed_rows.sort(key=lambda item: item[0])
        now = now_in_shanghai()
        result: List[KLineItem] = []
        for index, (trade_date, open_price, high, low, close, volume, amount) in enumerate(parsed_rows):
            # SSE can include today's still-forming daily candle during trading.
            # Keep that provisional point out of Redis/DB; the history route adds
            # a transient point from the quote cache for the current session.
            if trade_date == now.date() and now.time() < datetime_time(15, 10):
                continue
            previous_close = parsed_rows[index - 1][4] if index > 0 else None
            change_pct = (close - previous_close) / previous_close * 100 if previous_close and previous_close > 0 else 0.0
            result.append(KLineItem(
                trade_date=trade_date,
                open_price=open_price,
                close_price=close,
                high_price=high,
                low_price=low,
                volume=volume,
                amount=amount,
                change_pct=round(change_pct, 2),
            ))
        result = result[-safe_days:]
        if result:
            logger.info(f"[MarketService] ✓ 上交所日线获取到 {len(result)} 条: {code}")
        return result


    @classmethod
    def _aggregate_sse_intraday_items(cls, items: List[KLineItem], period: str, limit: int) -> List[KLineItem]:
        period_minutes = int(period[:-1]) if period.endswith("m") and period[:-1].isdigit() else 1
        if period_minutes <= 1:
            return cls._normalize_intraday_items(items, limit)

        buckets: Dict[tuple[date, int], List[KLineItem]] = {}
        for item in sorted(items, key=lambda value: value.trade_time or datetime.min.replace(tzinfo=SHANGHAI_TZ)):
            if item.trade_time is None:
                continue
            trade_time = item.trade_time.astimezone(SHANGHAI_TZ) if item.trade_time.tzinfo else item.trade_time.replace(tzinfo=SHANGHAI_TZ)
            minute_of_day = trade_time.hour * 60 + trade_time.minute
            if 570 <= minute_of_day <= 690:
                session_start = 570
                session_end = 690
            elif 780 <= minute_of_day <= 900:
                session_start = 780
                session_end = 900
            else:
                continue
            bucket_start = session_start + ((minute_of_day - session_start) // period_minutes) * period_minutes
            buckets.setdefault((trade_time.date(), bucket_start), []).append(item)

        now = now_in_shanghai()
        aggregated: List[KLineItem] = []
        for (trade_date, bucket_start), group in sorted(buckets.items(), key=lambda entry: entry[0]):
            group.sort(key=lambda item: item.trade_time or datetime.min.replace(tzinfo=SHANGHAI_TZ))
            first = group[0]
            last = group[-1]
            session_end = 690 if bucket_start < 720 else 900
            bucket_end = min(bucket_start + period_minutes, session_end)
            is_provisional = False
            if trade_date == now.date():
                now_minute = now.hour * 60 + now.minute
                is_provisional = bucket_start <= now_minute < bucket_end
            bucket_time = datetime.combine(
                trade_date,
                datetime_time(hour=bucket_start // 60, minute=bucket_start % 60),
                tzinfo=SHANGHAI_TZ,
            )
            amounts = [item.amount for item in group if item.amount is not None]
            aggregated.append(KLineItem(
                trade_date=trade_date,
                trade_time=bucket_time,
                provisional=is_provisional,
                open_price=first.open_price,
                close_price=last.close_price,
                high_price=max(item.high_price for item in group),
                low_price=min(item.low_price for item in group),
                volume=sum(item.volume for item in group),
                amount=sum(amounts) if amounts else None,
                change_pct=0.0,
            ))
        return cls._normalize_intraday_items(aggregated, limit)


    @classmethod
    async def _fetch_intraday_kline_sse(cls, code: str, period: str = "1m", limit: int = 240) -> List[KLineItem]:
        """Fetch today's SSE 1-minute bars and aggregate them to the requested period."""
        if not cls._sse_code_supported(code):
            return []
        today = now_in_shanghai().date()
        url = f"{cls.SSE_MARKET_DATA_BASE_URL}/mink/{code}"
        params = [
            ("callback", "cb"),
            ("select", "date,open,high,low,close,volume,amount"),
            ("begin", "0"),
            ("end", "-1"),
            ("period", today.strftime("%Y%m%d")),
        ]
        headers = cls._build_default_headers(cls.SSE_MARKET_DATA_REFERER)
        try:
            async with market_http_client(timeout=8.0) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
            payload = cls._parse_sse_jsonp(response.text)
        except Exception as e:
            logger.info(f"[MarketService] 上交所分钟线请求失败: {code}, {type(e).__name__}")
            return []

        rows = payload.get("mink") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        now = now_in_shanghai()
        items: List[KLineItem] = []
        for row in rows:
            parts = cls._sse_row_parts(row)
            if len(parts) < 6:
                continue
            trade_time = cls._sse_timestamp_to_datetime(parts[0])
            open_price = cls._to_float(parts[1])
            high = cls._to_float(parts[2])
            low = cls._to_float(parts[3])
            close = cls._to_float(parts[4])
            if trade_time is None or trade_time.date() != today or None in (open_price, high, low, close) or close <= 0:
                continue
            minute_of_day = trade_time.hour * 60 + trade_time.minute
            if not (570 <= minute_of_day <= 690 or 780 <= minute_of_day <= 900) or trade_time > now:
                continue
            items.append(KLineItem(
                trade_date=today,
                trade_time=trade_time,
                provisional=trade_time + timedelta(minutes=1) > now,
                open_price=open_price,
                close_price=close,
                high_price=high,
                low_price=low,
                volume=cls._to_int(parts[5]) or 0,
                amount=cls._to_float(parts[6]) if len(parts) > 6 else None,
                change_pct=0.0,
            ))
        if not items:
            return []
        result = cls._aggregate_sse_intraday_items(items, period, limit)
        if result:
            logger.info(f"[MarketService] ✓ 上交所分钟线获取到 {len(result)} 条: {code}, period={period}")
        return result
