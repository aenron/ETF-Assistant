import logging

logger = logging.getLogger("uvicorn.error.otc")

from services.market.http_client import market_http_client
import asyncio
import akshare as ak
import pandas as pd
from datetime import date
from typing import Optional, List, Dict, Any
import json


# 设置环境变量模拟浏览器

from schemas.market import MarketQuote, KLineItem
from config import settings
from services.redis_service import RedisService
from utils.timezone import now_in_shanghai


from services.market.formats import MarketFormatMixin

class OtcProviderMixin(MarketFormatMixin):
    """otc market parsing and retrieval."""

    @classmethod
    def _otc_fund_candidate_codes(cls, codes: List[str], existing: Dict[str, MarketQuote]) -> List[str]:
        candidates: List[str] = []
        for code in codes:
            clean = str(code or "").strip()
            if not clean or clean in existing:
                continue
            if cls._looks_like_listed_security_code(clean):
                continue
            candidates.append(clean)
        return list(dict.fromkeys(candidates))


    @classmethod
    async def _fetch_otc_fund_quote(cls, code: str) -> Optional[MarketQuote]:
        """Fetch OTC fund estimate/net value from Eastmoney fundgz endpoint."""
        url = f"https://fundgz.1234567.com.cn/js/{code}.js"
        headers = cls._build_default_headers("https://fund.eastmoney.com/")
        try:
            async with market_http_client(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
            text = response.text.strip()
            if text.startswith("jsonpgz("):
                text = text[len("jsonpgz("):].rstrip(");")
            data = json.loads(text)
        except Exception as e:
            logger.info(f"[MarketService] 场外基金估值请求失败: {code}, {e}")
            return None

        price = cls._to_float(data.get("gsz")) or cls._to_float(data.get("dwjz"))
        if price is None or price <= 0:
            return None
        return MarketQuote(
            code=code,
            name=str(data.get("name") or ""),
            price=price,
            refreshed_at=cls._timestamp_to_datetime(data.get("gztime") or data.get("jzrq")),
            quote_type="estimate" if cls._to_float(data.get("gsz")) else "nav",
            change_pct=cls._to_float(data.get("gszzl")) or 0.0,
            open_price=None,
            high_price=None,
            low_price=None,
            volume=None,
            amount=None,
        )


    @classmethod
    async def _fetch_from_otc_fund_api(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        result: Dict[str, MarketQuote] = {}
        for code in codes:
            quote = await cls._fetch_otc_fund_quote(code)
            if quote:
                result[code] = quote
        return result


    @classmethod
    def _fetch_history_kline_akshare_otc_fund(cls, code: str, days: int = 60) -> List[KLineItem]:
        """使用akshare获取场外基金净值走势，映射成日线收盘价。"""
        try:
            logger.info(f"[MarketService] >>> akshare获取场外基金净值: {code}")
            df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
            if df is None or df.empty:
                return []
            df = df.tail(days)
            result = []
            date_col = "净值日期" if "净值日期" in df.columns else "日期" if "日期" in df.columns else df.columns[0]
            value_col = "单位净值" if "单位净值" in df.columns else "净值" if "净值" in df.columns else df.columns[1]
            change_col = "日增长率" if "日增长率" in df.columns else None
            for _, row in df.iterrows():
                value = float(row[value_col])
                if change_col and row.get(change_col) not in (None, ""):
                    change_pct = float(str(row[change_col]).replace("%", ""))
                elif result and result[-1].close_price > 0:
                    change_pct = (value - result[-1].close_price) / result[-1].close_price * 100
                else:
                    change_pct = 0.0
                result.append(KLineItem(
                    trade_date=row[date_col] if isinstance(row[date_col], date) else date.fromisoformat(str(row[date_col]).split(" ")[0]),
                    open_price=value,
                    close_price=value,
                    high_price=value,
                    low_price=value,
                    volume=0,
                    amount=None,
                    change_pct=round(change_pct, 2),
                ))
            return result
        except Exception as e:
            logger.info(f"[MarketService] akshare场外基金净值获取失败: {e}")
        return []


    @classmethod
    def _otc_fund_daily_snapshot_from_df(cls, df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """Normalize AkShare's open-fund daily table into a code-indexed snapshot."""
        if df is None or df.empty:
            return {}

        snapshot: Dict[str, Dict[str, Any]] = {}
        for _, row in df.iterrows():
            raw_code = str(row.get("基金代码") or "").strip()
            if not raw_code:
                continue
            code = raw_code.zfill(6) if raw_code.isdigit() else raw_code
            price = cls._to_float(row.get("单位净值"))
            if price is None or price <= 0:
                continue
            snapshot[code] = {
                "name": str(row.get("基金简称") or "").strip(),
                "price": price,
                "nav_date": str(row.get("净值日期") or ""),
                "change_pct": cls._to_float(row.get("日增长率")) or 0.0,
            }
        return snapshot


    @classmethod
    async def _get_otc_fund_daily_snapshot(cls) -> Dict[str, Dict[str, Any]]:
        """Return latest disclosed NAVs for open-end funds, with Redis caching."""
        if settings.redis_enabled:
            cached = await RedisService.get(cls.REDIS_KEY_OTC_FUND_DAILY_SNAPSHOT)
            if cached and isinstance(cached.get("data"), dict):
                return cached["data"]

        try:
            df = await asyncio.to_thread(ak.fund_open_fund_daily_em)
            snapshot = cls._otc_fund_daily_snapshot_from_df(df)
        except Exception as e:
            logger.info(f"[MarketService] 开放式基金每日净值列表获取失败: {e}")
            return {}

        if snapshot and settings.redis_enabled:
            await RedisService.set(
                cls.REDIS_KEY_OTC_FUND_DAILY_SNAPSHOT,
                {"data": snapshot, "cached_at": now_in_shanghai().isoformat()},
                expire=cls.OTC_FUND_DAILY_CACHE_EXPIRE_SECONDS,
            )
        return snapshot


    @classmethod
    def _fetch_otc_fund_quote_from_history_sync(cls, code: str) -> Optional[MarketQuote]:
        """Use the latest confirmed NAV when the daily table is temporarily unavailable."""
        history = cls._fetch_history_kline_akshare_otc_fund(code, days=5)
        if not history:
            return None
        latest = history[-1]
        return MarketQuote(
            code=code,
            name="",
            price=latest.close_price,
            refreshed_at=cls._timestamp_to_datetime(str(latest.trade_date)),
            quote_type="nav",
            change_pct=latest.change_pct,
            open_price=None,
            high_price=None,
            low_price=None,
            volume=None,
            amount=None,
        )


    @classmethod
    def _fetch_otc_fund_name_sync(cls, code: str) -> str:
        """Read a fund's display name independently from its NAV source."""
        try:
            df = ak.fund_individual_basic_info_xq(symbol=code)
        except Exception as e:
            logger.info(f"[MarketService] 场外基金基础资料获取失败: {code}, {e}")
            return ""
        if df is None or df.empty:
            return ""
        for _, row in df.iterrows():
            key = str(row.get("item") or row.get("项目") or "").strip()
            if key not in {"基金名称", "基金简称", "名称"}:
                continue
            value = str(row.get("value") or row.get("值") or "").strip()
            if value and value.lower() != "nan":
                return value
        return ""


    @classmethod
    async def _fetch_from_otc_fund_daily_api(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """Fetch OTC-fund names and latest disclosed NAVs before intraday estimates."""
        if not codes:
            return {}

        snapshot = await cls._get_otc_fund_daily_snapshot()
        result: Dict[str, MarketQuote] = {}
        for code in codes:
            item = snapshot.get(code)
            if not item:
                continue
            result[code] = MarketQuote(
                code=code,
                name=str(item.get("name") or ""),
                price=cls._to_float(item.get("price")) or 0.0,
                refreshed_at=cls._timestamp_to_datetime(item.get("nav_date")),
                quote_type="nav",
                change_pct=cls._to_float(item.get("change_pct")) or 0.0,
                open_price=None,
                high_price=None,
                low_price=None,
                volume=None,
                amount=None,
            )

        for code in codes:
            if code in result:
                continue
            quote = await asyncio.to_thread(cls._fetch_otc_fund_quote_from_history_sync, code)
            if quote:
                result[code] = quote

        for code, quote in list(result.items()):
            if quote.name:
                continue
            name = await asyncio.to_thread(cls._fetch_otc_fund_name_sync, code)
            if name:
                result[code] = quote.model_copy(update={"name": name})

        return result
