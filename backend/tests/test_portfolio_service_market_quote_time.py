import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

fake_market_service = types.ModuleType("services.market_service")


class _FakeMarketService:
    pass


fake_market_service.MarketService = _FakeMarketService
sys.modules.setdefault("services.market_service", fake_market_service)

from services.portfolio_service import PortfolioService


class PortfolioServiceMarketQuoteTimeTests(unittest.TestCase):
    def test_treats_0915_as_start_of_today_market_quote(self) -> None:
        now = datetime(2026, 5, 8, 9, 15, tzinfo=PortfolioService.SHANGHAI_TZ)
        refreshed_at = datetime(2026, 5, 8, 9, 14, tzinfo=PortfolioService.SHANGHAI_TZ)

        with patch.object(PortfolioService, "_shanghai_now", return_value=now):
            self.assertTrue(PortfolioService._is_today_market_quote(refreshed_at))


if __name__ == "__main__":
    unittest.main()
