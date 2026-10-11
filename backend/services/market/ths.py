import logging

logger = logging.getLogger("uvicorn.error.ths")

import asyncio
import akshare as ak
from datetime import timedelta
from typing import Optional, List, Dict


# 设置环境变量模拟浏览器

from schemas.market import MarketQuote, KLineItem
from utils.timezone import now_in_shanghai


from services.market.formats import MarketFormatMixin

class ThsProviderMixin(MarketFormatMixin):
    """ths market parsing and retrieval."""

    @classmethod
    def _get_ths_industry_name_map(cls) -> Dict[str, str]:
        if cls._THS_INDUSTRY_NAME_MAP is not None:
            return cls._THS_INDUSTRY_NAME_MAP

        mapping: Dict[str, str] = {}
        try:
            df = ak.stock_board_industry_name_ths()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("code") or "").strip()
                    name = str(row.get("name") or "").strip()
                    if code and name:
                        mapping[code] = name
        except Exception as e:
            logger.info(f"[MarketService] 同花顺行业代码表获取失败: {e}")

        cls._THS_INDUSTRY_NAME_MAP = mapping
        return mapping


    @classmethod
    def _resolve_ths_industry_name(cls, code: str) -> Optional[str]:
        clean = str(code or "").strip()
        if not clean.startswith("88"):
            return None
        return cls._get_ths_industry_name_map().get(clean)


    @classmethod
    def _fetch_history_kline_ths_industry(cls, code: str, days: int = 60) -> List[KLineItem]:
        """使用同花顺行业指数获取 88xxxx 行业代码历史行情。"""
        name = cls._resolve_ths_industry_name(code)
        if not name:
            return []

        try:
            end_date = now_in_shanghai().strftime("%Y%m%d")
            start_date = (now_in_shanghai() - timedelta(days=max(days * 3, 30))).strftime("%Y%m%d")
            logger.info(f"[MarketService] >>> 同花顺行业指数获取历史K线: {code} {name}")
            df = ak.stock_board_industry_index_ths(
                symbol=name,
                start_date=start_date,
                end_date=end_date,
            )
            if df is None or df.empty:
                return []
            df = df.rename(columns={
                "开盘价": "开盘",
                "收盘价": "收盘",
                "最高价": "最高",
                "最低价": "最低",
            })
            return cls._items_from_ohlcv_df(df, days)
        except Exception as e:
            logger.info(f"[MarketService] 同花顺行业指数历史K线获取失败: {code}, {e}")
            return []


    @classmethod
    def _fetch_ths_industry_quote(cls, code: str) -> Optional[MarketQuote]:
        """使用同花顺行业指数最近日线生成 88xxxx 实时/最新行情。"""
        data = cls._fetch_history_kline_ths_industry(code, days=2)
        if not data:
            return None

        latest = data[-1]
        name = cls._resolve_ths_industry_name(code) or ""
        return MarketQuote(
            code=code,
            name=name,
            price=latest.close_price,
            change_pct=latest.change_pct,
            open_price=latest.open_price,
            high_price=latest.high_price,
            low_price=latest.low_price,
            volume=latest.volume,
            amount=latest.amount,
        )


    @classmethod
    async def _fetch_from_ths_industry_api(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        result: Dict[str, MarketQuote] = {}
        for code in codes:
            quote = await asyncio.to_thread(cls._fetch_ths_industry_quote, code)
            if quote:
                result[code] = quote
        return result
