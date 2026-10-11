import logging

logger = logging.getLogger("uvicorn.error.eastmoney")

from services.market.http_client import market_http_client
import asyncio
import akshare as ak
from datetime import date, datetime
from typing import Optional, List, Dict
import time


# 设置环境变量模拟浏览器

from schemas.market import MarketQuote, KLineItem
from utils.timezone import SHANGHAI_TZ


from services.market.formats import MarketFormatMixin

class EastmoneyProviderMixin(MarketFormatMixin):
    """eastmoney market parsing and retrieval."""

    @classmethod
    def _eastmoney_secid_candidates(cls, code: str) -> List[str]:
        """Return Eastmoney secid candidates for stocks, funds, indices and sector codes."""
        clean = str(code or "").strip()
        if "." in clean:
            market, symbol = clean.split(".", 1)
            if market.isdigit() and symbol:
                return [clean]

        candidates: List[str] = []
        if clean.startswith(("00", "30", "15", "16", "18", "39")):
            candidates.append(f"0.{clean}")
        if clean.startswith(("60", "68", "51", "58", "50", "56", "000")):
            candidates.append(f"1.{clean}")
        if clean.startswith(("43", "82", "83", "87", "88", "92")):
            # 裸 88xxxx 优先视为同花顺行业代码，不能自动尝试东方财富 90.xxxxxx。
            candidates.extend([f"0.{clean}", f"2.{clean}"])
        if clean.upper().startswith(("BK", "GN")):
            candidates.append(f"90.{clean.upper()}")

        candidates.extend([f"1.{clean}", f"0.{clean}", f"2.{clean}"])
        return list(dict.fromkeys(candidates))


    @classmethod
    async def _fetch_single_from_eastmoney_quote(cls, code: str) -> Optional[MarketQuote]:
        """Fetch a single broad-market quote from Eastmoney qt/stock/get."""
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        headers = cls._build_default_headers("https://quote.eastmoney.com/")
        errors: List[str] = []

        for secid in cls._eastmoney_secid_candidates(code):
            params = {
                "ut": "bd1d9ddb04089700cf9c27f6267cc896",
                "fltt": 2,
                "invt": 2,
                "fields": "f43,f44,f45,f46,f47,f48,f58,f107,f116,f117,f152,f168,f169,f170",
                "secid": secid,
            }
            try:
                async with market_http_client(timeout=10.0) as client:
                    response = await client.get(url, params=params, headers=headers)
                    response.raise_for_status()
                    data = response.json().get("data") or {}
            except Exception as e:
                errors.append(f"{secid}: {type(e).__name__}: {e}")
                continue

            name = str(data.get("f58") or "").strip()
            price = cls._to_float(data.get("f43"))
            if not name or price is None or price <= 0:
                continue

            return MarketQuote(
                code=code,
                name=name,
                price=price,
                change_pct=cls._to_float(data.get("f170")) or 0.0,
                open_price=cls._to_float(data.get("f46")),
                high_price=cls._to_float(data.get("f44")),
                low_price=cls._to_float(data.get("f45")),
                volume=cls._to_int(data.get("f47")),
                amount=cls._to_float(data.get("f48")),
            )
        if errors:
            logger.info(
                f"[MarketService] 东方财富单证券行情请求失败: {code}, "
                f"尝试 {len(errors)} 个secid 均失败，首个错误: {errors[0]}"
            )
        return None


    @classmethod
    async def _fetch_from_eastmoney_quote_api(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """Fetch stocks, listed funds, indices and sector quotes one by one."""
        result: Dict[str, MarketQuote] = {}
        for code in codes:
            quote = await cls._fetch_single_from_eastmoney_quote(code)
            if quote:
                result[code] = quote
        return result


    @classmethod
    async def _fetch_from_eastmoney_api(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """直接从东方财富API获取行情（绕过akshare爬虫）"""
        # 东方财富ETF行情API
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1,
            "pz": 500,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6267cc896",
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024",
            "fields": "f1,f2,f3,f4,f5,f6,f7,f12,f13,f14,f15,f16,f17,f18"
        }
        headers = cls._build_default_headers("https://quote.eastmoney.com/")

        try:
            async with market_http_client(timeout=10.0) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()

            if data.get("data") and data["data"].get("diff"):
                result = {}
                for item in data["data"]["diff"]:
                    code = item.get("f12", "")
                    name = item.get("f14", "")
                    price = item.get("f2", 0)
                    change_pct = item.get("f3", 0)

                    if code in codes:
                        result[code] = MarketQuote(
                            code=code,
                            name=name,
                            price=float(price) if price else 0.0,
                            change_pct=float(change_pct) if change_pct else 0.0,
                            open_price=None,
                            high_price=None,
                            low_price=None,
                            volume=cls._to_int(item.get("f5")),
                            amount=cls._to_float(item.get("f6")),
                        )
                return result
        except Exception as e:
            logger.info(f"[MarketService] 东方财富API请求失败: {e}")

        return {}


    @classmethod
    def _fetch_from_akshare_etf_spot_sync(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """使用 AkShare ETF 实时列表兜底，适合场内 ETF/LOF。"""
        try:
            df = ak.fund_etf_spot_em()
        except Exception as e:
            logger.info(f"[MarketService] AkShare ETF实时列表获取失败: {e}")
            return {}

        return cls._parse_quotes_from_df(codes, df)


    @classmethod
    async def _fetch_from_akshare_etf_spot(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        return await asyncio.to_thread(cls._fetch_from_akshare_etf_spot_sync, codes)


    @classmethod
    def _fetch_history_kline_akshare(cls, code: str, days: int = 60) -> List[KLineItem]:
        """使用akshare获取场内ETF历史K线数据"""
        try:
            logger.info(f"[MarketService] >>> akshare获取历史K线: {code}")
            df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
            result = cls._items_from_ohlcv_df(df, days)
            if result:
                logger.info(f"[MarketService] ✓ akshare获取到 {len(result)} 条K线")
                return result
        except Exception as e:
            logger.info(f"[MarketService] akshare获取历史K线失败: {e}")

        return []


    @classmethod
    def _fetch_history_kline_akshare_stock(cls, code: str, days: int = 60) -> List[KLineItem]:
        """使用akshare获取A股历史K线数据"""
        try:
            logger.info(f"[MarketService] >>> akshare获取股票历史K线: {code}")
            df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
            result = cls._items_from_ohlcv_df(df, days)
            if result:
                logger.info(f"[MarketService] ✓ akshare股票K线获取到 {len(result)} 条")
                return result
        except Exception as e:
            logger.info(f"[MarketService] akshare股票K线获取失败: {e}")
        return []


    @classmethod
    async def _fetch_history_kline_eastmoney(cls, code: str, days: int = 60) -> List[KLineItem]:
        """从东方财富API获取历史K线数据（备用）"""
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        headers = cls._build_default_headers("https://quote.eastmoney.com/")

        for secid in cls._eastmoney_secid_candidates(code):
            params = {
                "secid": secid,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101",  # 日K
                "fqt": "1",    # 前复权
                "end": "20500000",
                "lmt": str(days),
            }
            try:
                logger.info(f"[MarketService] >>> 东方财富API获取历史K线: {code} ({secid})")
                async with market_http_client(timeout=10.0) as client:
                    response = await client.get(url, params=params, headers=headers)
                    response.raise_for_status()
                    data = response.json()

                if data.get("data") and data["data"].get("klines"):
                    result = []
                    klines = data["data"]["klines"]

                    for i, line in enumerate(klines):
                        parts = line.split(',')
                        if len(parts) >= 6:
                            close = float(parts[2])
                            change_pct = float(parts[8]) if len(parts) > 8 and parts[8] else 0.0
                            if i > 0 and not change_pct:
                                prev_close = result[-1].close_price
                                if prev_close > 0:
                                    change_pct = (close - prev_close) / prev_close * 100

                            result.append(KLineItem(
                                trade_date=date.fromisoformat(parts[0]),
                                open_price=float(parts[1]),
                                close_price=close,
                                high_price=float(parts[3]),
                                low_price=float(parts[4]),
                                volume=cls._to_int(parts[5]) or 0,
                                amount=cls._to_float(parts[6]) if len(parts) > 6 else None,
                                change_pct=round(change_pct, 2),
                            ))

                    logger.info(f"[MarketService] ✓ 东方财富API获取到 {len(result)} 条K线")
                    return result
            except Exception as e:
                logger.info(f"[MarketService] 东方财富API获取历史K线失败: {code} {secid}, {e}")

        return []


    @classmethod
    def _eastmoney_intraday_breaker_key(cls, code: str, period: str) -> str:
        return str(code or "").strip()


    @classmethod
    def _is_eastmoney_intraday_breaker_open(cls, code: str, period: str) -> bool:
        key = cls._eastmoney_intraday_breaker_key(code, period)
        until = cls._EASTMONEY_INTRADAY_BREAKER_UNTIL.get(key, 0.0)
        if until <= time.time():
            cls._EASTMONEY_INTRADAY_BREAKER_UNTIL.pop(key, None)
            return False
        remaining = max(0, int(until - time.time()))
        logger.info(f"[MarketService] 东方财富分钟K线代码级熔断中: {code}, skip_period={period}, remaining={remaining}s")
        return True


    @classmethod
    def _record_eastmoney_intraday_success(cls, code: str, period: str) -> None:
        key = cls._eastmoney_intraday_breaker_key(code, period)
        cls._EASTMONEY_INTRADAY_FAILURES.pop(key, None)
        cls._EASTMONEY_INTRADAY_BREAKER_UNTIL.pop(key, None)


    @classmethod
    def _record_eastmoney_intraday_failure(cls, code: str, period: str) -> None:
        key = cls._eastmoney_intraday_breaker_key(code, period)
        failures = cls._EASTMONEY_INTRADAY_FAILURES.get(key, 0) + 1
        cls._EASTMONEY_INTRADAY_FAILURES[key] = failures
        if failures >= cls.EASTMONEY_INTRADAY_FAILURE_THRESHOLD:
            cls._EASTMONEY_INTRADAY_BREAKER_UNTIL[key] = time.time() + cls.EASTMONEY_INTRADAY_BREAKER_SECONDS
            cls._EASTMONEY_INTRADAY_FAILURES[key] = 0
            logger.info(f"[MarketService] 东方财富分钟K线连续失败，开启代码级熔断: {code}, failed_period={period}, duration={cls.EASTMONEY_INTRADAY_BREAKER_SECONDS}s")


    @classmethod
    async def _fetch_intraday_kline_eastmoney(cls, code: str, period: str = "1m", limit: int = 240) -> List[KLineItem]:
        if cls._is_eastmoney_intraday_breaker_open(code, period):
            return []
        klt_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "60m": "60"}
        klt = klt_map.get(period, "1")
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        headers = cls._build_default_headers("https://quote.eastmoney.com/")
        for secid in cls._eastmoney_secid_candidates(code):
            params = {
                "secid": secid,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": klt,
                "fqt": "1",
                "end": "20500000",
                "lmt": str(limit),
            }
            try:
                logger.info(f"[MarketService] >>> 东方财富API获取分钟K线: {code} ({secid})")
                async with market_http_client(timeout=10.0) as client:
                    response = await client.get(url, params=params, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                klines = data.get("data", {}).get("klines") if isinstance(data, dict) else None
                if not klines:
                    continue
                result: List[KLineItem] = []
                for line in klines:
                    parts = str(line).split(',')
                    if len(parts) < 6:
                        continue
                    parsed_time = datetime.fromisoformat(parts[0])
                    trade_time = parsed_time.astimezone(SHANGHAI_TZ) if parsed_time.tzinfo else parsed_time.replace(tzinfo=SHANGHAI_TZ)
                    result.append(KLineItem(
                        trade_date=trade_time.date(),
                        trade_time=trade_time,
                        open_price=float(parts[1]),
                        close_price=float(parts[2]),
                        high_price=float(parts[3]),
                        low_price=float(parts[4]),
                        volume=cls._to_int(parts[5]) or 0,
                        amount=cls._to_float(parts[6]) if len(parts) > 6 else None,
                        change_pct=0.0,
                    ))
                normalized = cls._normalize_intraday_items(result, limit)
                if normalized:
                    cls._record_eastmoney_intraday_success(code, period)
                    logger.info(f"[MarketService] ✓ 东方财富分钟K线获取到 {len(normalized)} 条")
                    return normalized
            except Exception as e:
                logger.info(f"[MarketService] 东方财富分钟K线获取失败: {code} {secid}, {e}")
        cls._record_eastmoney_intraday_failure(code, period)
        return []
