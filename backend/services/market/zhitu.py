import logging

logger = logging.getLogger("uvicorn.error.zhitu")

from services.market.http_client import market_http_client
from datetime import date, datetime
from typing import Optional, List, Dict, Any


# 设置环境变量模拟浏览器

from models import EtfInfo
from schemas.market import MarketQuote, KLineItem
from config import settings
from database import async_session_maker
from utils.timezone import SHANGHAI_TZ, now_in_shanghai


from services.market.formats import MarketFormatMixin

class ZhituProviderMixin(MarketFormatMixin):
    """zhitu market parsing and retrieval."""

    @staticmethod
    def _zhitu_symbol(code: str) -> str:
        clean = str(code or "").strip().upper()
        if "." in clean:
            return clean
        if clean.startswith("399"):
            return f"{clean}.SZ"
        if clean.startswith("000"):
            return f"{clean}.SH"
        if clean.startswith(("00", "30", "15", "16", "18", "12", "13")):
            return f"{clean}.SZ"
        if clean.startswith(("60", "68", "51", "58", "50", "56", "110", "113", "118")):
            return f"{clean}.SH"
        return clean


    @staticmethod
    def _is_zhitu_index_code(code: str) -> bool:
        clean = str(code or "").strip().upper()
        return clean.startswith(("000", "399")) or clean.endswith((".SH", ".SZ")) and clean[:6].startswith(("000", "399"))


    @classmethod
    def _zhitu_token(cls) -> str:
        return settings.zhitu_token.strip()


    @staticmethod
    def _safe_zhitu_error_summary(error: Exception) -> str:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        return f"HTTP {status_code}" if status_code is not None else type(error).__name__


    @staticmethod
    def _parse_zhitu_time(value: Any) -> Optional[datetime]:
        if not value:
            return None
        raw = str(value).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d%H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=SHANGHAI_TZ)
            except ValueError:
                continue
        return None


    @classmethod
    async def _fetch_zhitu_etf_names(cls, codes: List[str]) -> Dict[str, str]:
        token = cls._zhitu_token()
        if not token or not codes:
            return {}
        target_codes = {str(code).strip() for code in codes if code}
        try:
            async with market_http_client(timeout=12.0) as client:
                response = await client.get(
                    "https://api.zhituapi.com/fund/list/etf",
                    params={"token": token},
                    headers=cls._build_default_headers("https://www.zhituapi.com/"),
                )
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.info(f"[MarketService] 智兔ETF列表获取失败: {cls._safe_zhitu_error_summary(e)}")
            return {}
        if not isinstance(data, list):
            return {}

        names: Dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            raw_code = str(item.get("dm") or "").split(".")[0]
            name = str(item.get("mc") or "").strip()
            if raw_code in target_codes and name:
                names[raw_code] = name
        if names:
            try:
                async with async_session_maker() as session:
                    for code, name in names.items():
                        existing = await session.get(EtfInfo, code)
                        if existing:
                            existing.name = name
                        else:
                            session.add(EtfInfo(code=code, name=name, category=None, exchange=None))
                    await session.commit()
            except Exception as e:
                logger.info(f"[MarketService] 保存智兔ETF名称失败: {e}")
        return names


    @classmethod
    async def _fetch_quotes_from_zhitu(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        token = cls._zhitu_token()
        if not settings.zhitu_realtime_enabled or not token:
            return {}

        result: Dict[str, MarketQuote] = {}
        resolved_names: Dict[str, str] = {}
        headers = cls._build_default_headers("https://www.zhituapi.com/")
        async with market_http_client(timeout=10.0) as client:
            for code in codes:
                clean = str(code or "").strip()
                if not clean or clean.startswith(("000", "399")):
                    continue
                url = f"https://api.zhituapi.com/fund/real/ssjy/{clean}"
                try:
                    response = await client.get(url, params={"token": token}, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                except Exception as e:
                    logger.info(f"[MarketService] 智兔实时行情失败: {clean}, {cls._safe_zhitu_error_summary(e)}")
                    continue

                if not isinstance(data, dict) or data.get("error"):
                    if isinstance(data, dict) and data.get("error"):
                        logger.info(f"[MarketService] 智兔实时行情无数据: {clean}, {data.get('error')}")
                    continue

                price = cls._to_float(data.get("p"))
                if price is None or price <= 0:
                    continue

                name = await cls._resolve_quote_name(clean)
                if not name:
                    if not resolved_names:
                        resolved_names = await cls._fetch_zhitu_etf_names(codes)
                    name = resolved_names.get(clean, "")

                quote = MarketQuote(
                    code=clean,
                    name=name,
                    price=price,
                    change_pct=cls._to_float(data.get("pc")) or 0.0,
                    open_price=cls._to_float(data.get("o")),
                    high_price=cls._to_float(data.get("h")),
                    low_price=cls._to_float(data.get("l")),
                    volume=cls._to_int(data.get("pv") or data.get("v")),
                    amount=cls._to_float(data.get("cje")),
                    refreshed_at=cls._parse_zhitu_time(data.get("t")) or now_in_shanghai(),
                )
                result[clean] = await cls.cache_quote(clean, quote)
        if result:
            logger.info(f"[MarketService] 智兔实时行情获取成功: {len(result)}/{len(codes)}")
        return result


    @classmethod
    async def _fetch_history_kline_zhitu_index(cls, code: str, days: int = 60) -> List[KLineItem]:
        token = cls._zhitu_token()
        if not token or not cls._is_zhitu_index_code(code):
            return []

        symbol = cls._zhitu_symbol(code)
        url = f"https://api.zhituapi.com/hz/history/fsjy/{symbol}/d"
        headers = cls._build_default_headers("https://www.zhituapi.com/")
        try:
            logger.info(f"[MarketService] >>> 智兔指数历史K线: {code} ({symbol})")
            async with market_http_client(timeout=12.0) as client:
                response = await client.get(url, params={"token": token, "lt": str(days)}, headers=headers)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.info(f"[MarketService] 智兔指数历史K线失败: {code}, {cls._safe_zhitu_error_summary(e)}")
            return []

        if not isinstance(data, list):
            if isinstance(data, dict) and data.get("error"):
                logger.info(f"[MarketService] 智兔指数历史K线无数据: {code}, {data.get('error')}")
            return []

        result: List[KLineItem] = []
        for item in data[-days:]:
            try:
                close = cls._to_float(item.get("c"))
                prev_close = cls._to_float(item.get("pc"))
                if close is None:
                    continue
                change_pct = (close - prev_close) / prev_close * 100 if prev_close and prev_close > 0 else 0.0
                result.append(KLineItem(
                    trade_date=date.fromisoformat(str(item.get("t")).split(" ")[0]),
                    open_price=cls._to_float(item.get("o")) or close,
                    close_price=close,
                    high_price=cls._to_float(item.get("h")) or close,
                    low_price=cls._to_float(item.get("l")) or close,
                    volume=cls._to_int(item.get("v")) or 0,
                    amount=cls._to_float(item.get("a")),
                    change_pct=round(change_pct, 2),
                ))
            except Exception:
                continue
        if result:
            logger.info(f"[MarketService] ✓ 智兔指数历史K线获取到 {len(result)} 条")
        return result
