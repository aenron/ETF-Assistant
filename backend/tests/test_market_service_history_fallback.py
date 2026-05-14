import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from schemas.market import KLineItem
from services.market_service import MarketService


class MarketServiceHistoryFallbackTests(unittest.IsolatedAsyncioTestCase):
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
            patch.object(MarketService, "_fetch_history_kline_akshare", return_value=[]),
            patch.object(MarketService, "_fetch_history_kline_akshare_stock", return_value=[]),
            patch.object(MarketService, "_fetch_history_kline_eastmoney", new=AsyncMock(return_value=[])),
            patch.object(MarketService, "_fetch_history_kline_tushare", new=AsyncMock(return_value=[])),
            patch.object(MarketService, "_fetch_history_kline_sina", new=AsyncMock(return_value=sina_kline)) as sina_fetch,
            patch.object(MarketService, "_fetch_history_kline_akshare_otc_fund", return_value=[]) as otc_fetch,
            patch.object(MarketService, "cache_kline", new=AsyncMock()),
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


if __name__ == "__main__":
    unittest.main()
