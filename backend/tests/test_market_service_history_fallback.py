import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from schemas.market import KLineItem
from schemas.market import MarketQuote
from services.market_service import MarketService


class MarketServiceHistoryFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_kline_uses_db_before_public_sources(self) -> None:
        db_kline = [
            KLineItem(
                trade_date=date(2026, 5, 8),
                open_price=1.0,
                close_price=1.02,
                high_price=1.03,
                low_price=0.99,
                volume=1000,
                change_pct=2.0,
            )
        ]

        with (
            patch.object(MarketService, "get_kline_from_cache", new=AsyncMock(return_value=None)),
            patch.object(MarketService, "get_kline_from_longer_cache", new=AsyncMock(return_value=None)),
            patch.object(MarketService, "get_kline_from_db", new=AsyncMock(return_value=db_kline)) as db_fetch,
            patch.object(MarketService, "_fetch_history_kline_ths_industry", return_value=[]) as ths_fetch,
        ):
            result = await MarketService.get_history_kline("513300", days=60)

        self.assertEqual(result, db_kline)
        db_fetch.assert_awaited_once_with("513300", 60)
        ths_fetch.assert_not_called()

    async def test_sina_fallback_runs_before_otc_fund_nav(self) -> None:
        sina_kline = [
            KLineItem(
                trade_date=date(2026, 5, 8),
                open_price=1.0,
                close_price=1.02,
                high_price=1.03,
                low_price=0.99,
                volume=1000,
                change_pct=2.0,
            )
        ]

        with (
            patch.object(MarketService, "_fetch_history_kline_ths_industry", return_value=[]),
            patch.object(MarketService, "get_kline_from_cache", new=AsyncMock(return_value=None)),
            patch.object(MarketService, "get_kline_from_longer_cache", new=AsyncMock(return_value=None)),
            patch.object(MarketService, "get_kline_from_db", new=AsyncMock(return_value=None)),
            patch.object(MarketService, "_fetch_history_kline_qmt_agent", new=AsyncMock(return_value=[])),
            patch.object(MarketService, "_fetch_history_kline_akshare", return_value=[]),
            patch.object(MarketService, "_fetch_history_kline_akshare_stock", return_value=[]),
            patch.object(MarketService, "_fetch_history_kline_eastmoney", new=AsyncMock(return_value=[])),
            patch.object(MarketService, "_fetch_history_kline_tushare", new=AsyncMock(return_value=[])),
            patch.object(MarketService, "_fetch_history_kline_sina", new=AsyncMock(return_value=sina_kline)) as sina_fetch,
            patch.object(MarketService, "_fetch_history_kline_akshare_otc_fund", return_value=[]) as otc_fetch,
            patch.object(MarketService, "cache_kline", new=AsyncMock()),
            patch.object(MarketService, "_cache_and_store_kline", new=AsyncMock()),
            patch("services.market_service.settings") as settings,
            patch("services.market_service.asyncio.to_thread") as to_thread,
        ):
            settings.tushare_token = ""

            async def run_sync(function, *args, **kwargs):
                return function(*args, **kwargs)

            to_thread.side_effect = run_sync

            result = await MarketService.get_history_kline("513300", days=60)

        self.assertEqual(result, sina_kline)
        sina_fetch.assert_awaited_once_with("513300", 60)
        otc_fetch.assert_not_called()

    async def test_qmt_agent_runs_before_public_history_sources(self) -> None:
        qmt_kline = [
            KLineItem(
                trade_date=date(2026, 5, 8),
                open_price=1.0,
                close_price=1.02,
                high_price=1.03,
                low_price=0.99,
                volume=1000,
                change_pct=2.0,
            )
        ]

        with (
            patch.object(MarketService, "_fetch_history_kline_ths_industry", return_value=[]),
            patch.object(MarketService, "get_kline_from_cache", new=AsyncMock(return_value=None)),
            patch.object(MarketService, "get_kline_from_longer_cache", new=AsyncMock(return_value=None)),
            patch.object(MarketService, "get_kline_from_db", new=AsyncMock(return_value=None)),
            patch.object(MarketService, "_fetch_history_kline_qmt_agent", new=AsyncMock(return_value=qmt_kline)) as qmt_fetch,
            patch.object(MarketService, "_fetch_history_kline_akshare", return_value=[]) as akshare_fetch,
            patch.object(MarketService, "cache_kline", new=AsyncMock()),
            patch.object(MarketService, "_cache_and_store_kline", new=AsyncMock()),
            patch("services.market_service.asyncio.to_thread") as to_thread,
        ):
            async def run_sync(function, *args, **kwargs):
                return function(*args, **kwargs)

            to_thread.side_effect = run_sync

            result = await MarketService.get_history_kline("513300", days=60)

        self.assertEqual(result, qmt_kline)
        qmt_fetch.assert_awaited_once_with("513300", 60)
        akshare_fetch.assert_not_called()

    def test_qmt_dataframe_records_convert_to_kline_items(self) -> None:
        records = MarketService._qmt_records({
            "symbol": "513300.SH",
            "item": {
                "type": "dataframe",
                "columns": ["time", "open", "high", "low", "close", "volume", "amount"],
                "records": [
                    {
                        "time": "20260508",
                        "open": 1.0,
                        "high": 1.03,
                        "low": 0.99,
                        "close": 1.02,
                        "volume": 1000,
                    }
                ],
            },
        })

        self.assertEqual(len(records), 1)
        self.assertEqual(MarketService._qmt_timestamp_to_date(records[0]["time"]), date(2026, 5, 8))

    async def test_cache_quote_keeps_cached_name_when_new_quote_name_empty(self) -> None:
        cached_quote = MarketQuote(code="513300", name="纳斯达克ETF", price=1.0, change_pct=0.0)
        fresh_quote = MarketQuote(code="513300", name="", price=1.2, change_pct=1.0)

        with (
            patch.object(MarketService, "get_quote_from_cache", new=AsyncMock(return_value=cached_quote)),
            patch("services.market_service.settings") as settings,
            patch("services.market_service.RedisService.set", new=AsyncMock()) as redis_set,
        ):
            settings.redis_enabled = True
            result = await MarketService.cache_quote("513300", fresh_quote)

        self.assertEqual(result.name, "纳斯达克ETF")
        redis_set.assert_awaited_once()

    async def test_public_quote_source_enriches_qmt_empty_name(self) -> None:
        qmt_quote = MarketQuote(code="513300", name="", price=1.2, change_pct=1.0)
        public_quote = MarketQuote(code="513300", name="纳斯达克ETF", price=1.19, change_pct=0.8)

        with (
            patch.object(MarketService, "_fetch_from_qmt_agent", new=AsyncMock(return_value={"513300": qmt_quote})),
            patch.object(MarketService, "_fetch_from_eastmoney_api", new=AsyncMock(return_value={"513300": public_quote})),
            patch.object(MarketService, "cache_quote", new=AsyncMock(side_effect=lambda _code, quote: quote)),
        ):
            result = await MarketService._fetch_quotes_from_akshare(["513300"])

        self.assertEqual(result["513300"].name, "纳斯达克ETF")
        self.assertEqual(result["513300"].price, 1.2)


if __name__ == "__main__":
    unittest.main()
