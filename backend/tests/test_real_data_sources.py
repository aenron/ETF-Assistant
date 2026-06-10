import sys
import unittest
from pathlib import Path

import pandas as pd

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from services.industry_fundamental_service import IndustryFundamentalService
from services.market_service import MarketService


class RealDataSourceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
