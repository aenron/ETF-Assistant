import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from services.industry_fundamental_service import IndustryFundamentalService
from services.market_service import MarketService


class RealDataSourceTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_etf_spot_dataframe_includes_iopv_and_premium(self) -> None:
        df = pd.DataFrame([
            {
                "代码": "513300",
                "名称": "纳斯达克ETF",
                "最新价": 1.05,
                "涨跌幅": 1.2,
                "成交量": 100000,
                "成交额": 12345678,
                "IOPV实时估值": 1.0,
                "基金折价率": -5.0,
            }
        ])

        result = MarketService._parse_quotes_from_df(["513300"], df)

        self.assertEqual(result["513300"].iopv, 1.0)
        self.assertEqual(result["513300"].premium_rate, 5.0)
        self.assertEqual(result["513300"].amount, 12345678)

    def test_industry_fundamental_aggregate_uses_real_metrics(self) -> None:
        profile = {"label": "半导体"}
        samples = [
            {"roe": 12.0, "net_profit_growth": 20.0, "revenue_growth": 10.0, "profit_growth_delta": 5.0},
            {"roe": 18.0, "net_profit_growth": 40.0, "revenue_growth": 20.0, "profit_growth_delta": 10.0},
        ]
        forecast = {"forecast_eps_growth": 25.0, "positive_rating_ratio": 80.0, "sample_size": 30}

        result = IndustryFundamentalService._aggregate(profile, samples, forecast, [])

        self.assertEqual(result["industry_name"], "半导体")
        self.assertEqual(result["roe"], 15.0)
        self.assertEqual(result["net_profit_growth"], 30.0)
        self.assertEqual(result["forecast_eps_growth"], 25.0)
        self.assertGreater(result["score"], 70.0)

    def test_industry_key_resolution_uses_etf_name_keywords(self) -> None:
        self.assertEqual(
            IndustryFundamentalService.resolve_industry_key("159995", "芯片ETF"),
            "semiconductor",
        )
        self.assertEqual(
            IndustryFundamentalService.resolve_industry_key("512800", "银行ETF"),
            "bank",
        )

    async def test_quote_enrichment_keeps_price_and_adds_iopv(self) -> None:
        from schemas.market import MarketQuote

        qmt_quote = MarketService._merge_quote(
            existing=MarketQuote(code="513300", name="纳斯达克ETF", price=1.05, change_pct=1.2),
            incoming=MarketQuote(code="513300", name="纳斯达克ETF", price=1.04, change_pct=1.1, iopv=1.0, premium_rate=5.0),
        )

        self.assertEqual(qmt_quote.price, 1.05)
        self.assertEqual(qmt_quote.iopv, 1.0)
        self.assertEqual(qmt_quote.premium_rate, 5.0)

    async def test_fetch_quotes_continues_to_akshare_when_quote_lacks_iopv(self) -> None:
        from schemas.market import MarketQuote

        qmt_quote = MarketQuote(code="513300", name="纳斯达克ETF", price=1.05, change_pct=1.2)
        iopv_quote = MarketQuote(code="513300", name="纳斯达克ETF", price=1.04, change_pct=1.1, iopv=1.0, premium_rate=5.0)

        with (
            patch.object(MarketService, "_fetch_from_qmt_agent", new=AsyncMock(return_value={"513300": qmt_quote})),
            patch.object(MarketService, "_fetch_from_eastmoney_api", new=AsyncMock(return_value={})),
            patch.object(MarketService, "_fetch_from_akshare_etf_spot", new=AsyncMock(return_value={"513300": iopv_quote})) as akshare_fetch,
            patch.object(MarketService, "cache_quote", new=AsyncMock(side_effect=lambda _code, quote: quote)),
        ):
            result = await MarketService._fetch_quotes_from_akshare(["513300"])

        akshare_fetch.assert_awaited_once_with(["513300"])
        self.assertEqual(result["513300"].price, 1.05)
        self.assertEqual(result["513300"].iopv, 1.0)
        self.assertEqual(result["513300"].premium_rate, 5.0)


if __name__ == "__main__":
    unittest.main()
