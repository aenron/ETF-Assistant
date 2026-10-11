import logging

logger = logging.getLogger("uvicorn.error.tushare")

import asyncio
from datetime import date
from typing import List, Dict

try:
    import tushare as ts
except Exception:
    ts = None

# 设置环境变量模拟浏览器

from schemas.market import MarketQuote, KLineItem
from config import settings


from services.market.formats import MarketFormatMixin

class TushareProviderMixin(MarketFormatMixin):
    """tushare market parsing and retrieval."""

    @classmethod
    def _get_tushare_pro(cls):
        if ts is None:
            return None
        token = settings.tushare_token.strip()
        if not token:
            return None
        if cls._TUSHARE_PRO is None:
            try:
                ts.set_token(token)
                cls._TUSHARE_PRO = ts.pro_api(token)
            except Exception as e:
                logger.info(f"[MarketService] Tushare初始化失败: {e}")
                return None
        return cls._TUSHARE_PRO


    @staticmethod
    def _tushare_ts_code_candidates(code: str) -> List[str]:
        clean = str(code or "").strip()
        if "." in clean:
            return [clean.upper()]

        candidates: List[str] = []
        if clean.startswith(("60", "68", "51", "58", "50", "56", "110", "113", "118")):
            candidates.append(f"{clean}.SH")
        if clean.startswith(("00", "30", "15", "16", "18", "12", "13")):
            candidates.append(f"{clean}.SZ")
        if clean.startswith(("43", "82", "83", "87", "88", "92")):
            candidates.append(f"{clean}.BJ")
        candidates.extend([f"{clean}.SH", f"{clean}.SZ", f"{clean}.BJ"])
        return list(dict.fromkeys(candidates))


    @classmethod
    def _fetch_tushare_quotes_sync(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """使用 Tushare daily + basic 信息补充最近交易日行情。"""
        pro = cls._get_tushare_pro()
        if pro is None:
            return {}

        result: Dict[str, MarketQuote] = {}
        for code in codes:
            for ts_code in cls._tushare_ts_code_candidates(code):
                try:
                    df = pro.daily(ts_code=ts_code, limit=1)
                    if df is None or df.empty:
                        df = pro.fund_daily(ts_code=ts_code, limit=1)
                    if df is None or df.empty:
                        continue

                    row = df.iloc[0]
                    name = ""
                    try:
                        if ts_code.endswith((".SH", ".SZ", ".BJ")):
                            basic_df = pro.stock_basic(ts_code=ts_code, fields="ts_code,name")
                            if basic_df is not None and not basic_df.empty:
                                name = str(basic_df.iloc[0].get("name") or "")
                    except Exception:
                        pass
                    if not name:
                        name = code

                    result[code] = MarketQuote(
                        code=code,
                        name=name,
                        price=float(row.get("close") or 0),
                        change_pct=float(row.get("pct_chg") or 0),
                        open_price=cls._to_float(row.get("open")),
                        high_price=cls._to_float(row.get("high")),
                        low_price=cls._to_float(row.get("low")),
                        volume=(cls._to_int(row.get("vol")) or 0) * 100,
                        quote_type="daily",
                        refreshed_at=cls._timestamp_to_datetime(str(row.get("trade_date")) + "150000"),
                        amount=(cls._to_float(row.get("amount")) * 1000 if cls._to_float(row.get("amount")) is not None else None),
                    )
                    break
                except Exception as e:
                    logger.info(f"[MarketService] Tushare行情获取失败: {code} {ts_code}, {e}")
        return result


    @classmethod
    async def _fetch_from_tushare_api(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        return await asyncio.to_thread(cls._fetch_tushare_quotes_sync, codes)


    @classmethod
    def _fetch_history_kline_tushare_sync(cls, code: str, days: int = 60) -> List[KLineItem]:
        """使用 Tushare 获取股票/场内基金最近日线。"""
        pro = cls._get_tushare_pro()
        if pro is None:
            return []

        for ts_code in cls._tushare_ts_code_candidates(code):
            try:
                df = pro.daily(ts_code=ts_code, limit=days)
                if df is None or df.empty:
                    df = pro.fund_daily(ts_code=ts_code, limit=days)
                if df is None or df.empty:
                    continue

                df = df.sort_values("trade_date")
                result: List[KLineItem] = []
                for _, row in df.iterrows():
                    trade_date_text = str(row.get("trade_date") or "")
                    if not trade_date_text:
                        continue
                    result.append(KLineItem(
                        trade_date=date.fromisoformat(
                            f"{trade_date_text[:4]}-{trade_date_text[4:6]}-{trade_date_text[6:8]}"
                        ),
                        open_price=float(row.get("open") or 0),
                        close_price=float(row.get("close") or 0),
                        high_price=float(row.get("high") or 0),
                        low_price=float(row.get("low") or 0),
                        volume=(cls._to_int(row.get("vol")) or 0) * 100,
                        amount=(cls._to_float(row.get("amount")) * 1000 if cls._to_float(row.get("amount")) is not None else None),
                        change_pct=float(row.get("pct_chg") or 0),
                    ))
                if result:
                    return result
            except Exception as e:
                logger.info(f"[MarketService] Tushare历史K线获取失败: {code} {ts_code}, {e}")
        return []


    @classmethod
    async def _fetch_history_kline_tushare(cls, code: str, days: int = 60) -> List[KLineItem]:
        return await asyncio.to_thread(cls._fetch_history_kline_tushare_sync, code, days)
