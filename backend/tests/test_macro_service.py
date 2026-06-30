import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from models.macro_indicator import MacroIndicator
from services.macro_service import MacroDataService


class MacroServiceTests(unittest.IsolatedAsyncioTestCase):
    def _indicator(
        self,
        *,
        region: str,
        code: str,
        name: str,
        category: str,
        period: str,
        value: float,
        previous: float | None = None,
        trend: str = "flat",
    ) -> MacroIndicator:
        return MacroIndicator(
            region=region,
            indicator_code=code,
            indicator_name=name,
            category=category,
            period=period,
            value=Decimal(str(value)),
            previous_value=Decimal(str(previous)) if previous is not None else None,
            trend=trend,
            fetched_at=datetime.utcnow(),
        )

    def test_fred_yoy_transform_uses_index_values(self) -> None:
        rows = [(pd.Timestamp(f"2025-{month:02d}-01"), 100 + month) for month in range(1, 13)]
        rows.extend([
            (pd.Timestamp("2026-01-01"), 113.3),
            (pd.Timestamp("2026-02-01"), 114.4),
        ])

        frame = MacroDataService._fred_rows_to_frame(rows, "yoy")

        self.assertIsNotNone(frame)
        latest = frame.iloc[-1]
        self.assertEqual(latest["date"], "2026-02-01")
        self.assertAlmostEqual(latest["value"], (114.4 / 102 - 1) * 100, places=4)
        self.assertAlmostEqual(latest["previous"], (113.3 / 101 - 1) * 100, places=4)

    def test_fred_nonfarm_transform_converts_thousands_to_ten_thousand(self) -> None:
        rows = [
            (pd.Timestamp("2026-03-01"), 160000),
            (pd.Timestamp("2026-04-01"), 160120),
            (pd.Timestamp("2026-05-01"), 160250),
        ]

        frame = MacroDataService._fred_rows_to_frame(rows, "monthly_diff_ten_thousand")

        self.assertIsNotNone(frame)
        latest = frame.iloc[-1]
        self.assertEqual(latest["date"], "2026-05-01")
        self.assertEqual(latest["value"], 13.0)
        self.assertEqual(latest["previous"], 12.0)

    def test_stale_monthly_indicator_is_not_fresh(self) -> None:
        item = self._indicator(
            region="us",
            code="us_pmi",
            name="美国PMI",
            category="growth",
            period="2025-09-02",
            value=53,
            previous=49.8,
            trend="up",
        )

        self.assertFalse(MacroDataService._is_indicator_fresh(item))

    def test_us_resilient_reinflation_is_not_maxed_out(self) -> None:
        indicators = [
            self._indicator(region="us", code="us_cpi_yoy", name="美国CPI同比", category="inflation", period="2026-05-01", value=4.27, previous=3.947, trend="up"),
            self._indicator(region="us", code="us_unemployment_rate", name="美国失业率", category="growth", period="2026-05-01", value=4.3, previous=4.3, trend="flat"),
            self._indicator(region="us", code="us_fed_rate", name="美国联邦基金利率", category="liquidity", period="2026-05-01", value=3.63, previous=3.64, trend="down"),
            self._indicator(region="us", code="us_nonfarm", name="美国非农就业", category="growth", period="2026-05-01", value=17.2, previous=17.9, trend="down"),
            self._indicator(region="us", code="us_pce", name="美国PCE物价", category="inflation", period="2026-05-01", value=3.412, previous=3.3187, trend="up"),
            self._indicator(region="us", code="us_10y_yield", name="美国10年期国债收益率", category="liquidity", period="2026-06-24", value=4.41, previous=4.5, trend="down"),
        ]

        growth_score, inflation_score, growth_trend, inflation_trend = MacroDataService._score_us_cycle(indicators)

        self.assertEqual(growth_trend, "up")
        self.assertEqual(inflation_trend, "up")
        self.assertLess(growth_score, 70)
        self.assertGreaterEqual(growth_score, 60)
        self.assertLess(inflation_score, 90)
        self.assertGreaterEqual(inflation_score, 75)

    async def test_build_cycle_state_excludes_stale_us_indicators(self) -> None:
        session = type("Session", (), {"add": lambda _self, _item: None, "flush": AsyncMock()})()
        indicators = [
            self._indicator(
                region="us",
                code="us_pmi",
                name="美国PMI",
                category="growth",
                period="2025-09-02",
                value=53,
                previous=49.8,
                trend="up",
            ),
            self._indicator(
                region="us",
                code="us_10y_yield",
                name="美国10年期国债收益率",
                category="liquidity",
                period="2026-06-18",
                value=4.46,
                previous=4.49,
                trend="down",
            ),
        ]

        state = await MacroDataService.build_cycle_state(session, region="us", indicators=indicators)

        self.assertIn("已剔除过期指标", state.summary)
        self.assertLess(float(state.confidence), 55)
        self.assertNotEqual(float(state.growth_score), 84.0)

    async def test_global_missing_core_proxies_lowers_confidence_and_summary(self) -> None:
        session = type("Session", (), {"add": lambda _self, _item: None, "flush": AsyncMock()})()
        indicators = [
            self._indicator(
                region="global",
                code="global_gold",
                name="黄金价格",
                category="risk",
                period="2026-06-22",
                value=4190,
                previous=4245,
                trend="down",
            ),
            self._indicator(
                region="global",
                code="global_oil",
                name="原油价格",
                category="inflation",
                period="2026-06-22",
                value=77,
                previous=75,
                trend="up",
            ),
        ]

        state = await MacroDataService.build_cycle_state(session, region="global", indicators=indicators)

        self.assertIn("全球风险/流动性代理", state.summary)
        self.assertLessEqual(float(state.confidence), 35)


if __name__ == "__main__":
    unittest.main()
