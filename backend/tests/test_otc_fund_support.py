import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from datetime import date, timedelta
from pathlib import Path

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from schemas.market import KLineItem, MarketQuote
from schemas.portfolio import PortfolioCreate
from services.portfolio_service import PortfolioService
from services.trend_signal_service import build_otc_fund_trend_signal


class OtcFundSupportTests(unittest.TestCase):
    def _history(self, closes: list[float]) -> list[KLineItem]:
        start = date(2026, 1, 1)
        return [
            KLineItem(
                trade_date=start + timedelta(days=index),
                open_price=value,
                close_price=value,
                high_price=value,
                low_price=value,
                volume=0,
                change_pct=0.0 if index == 0 else (value - closes[index - 1]) / closes[index - 1] * 100,
            )
            for index, value in enumerate(closes)
        ]

    def test_portfolio_create_defaults_to_auto(self) -> None:
        data = PortfolioCreate(etf_code="510300", shares=100.0, cost_price=4.0)
        self.assertEqual(data.asset_type, "auto")

    def test_auto_detects_stock_codes_before_otc_fund_lookup(self) -> None:
        class FakeSession:
            async def get(self, model, key):
                return None

        async def run_test():
            return await PortfolioService.detect_asset_type(FakeSession(), "600519", "auto")

        import asyncio

        with patch("services.portfolio_service.MarketService._fetch_otc_fund_quote", new=AsyncMock()) as fetch_quote:
            asset_type = asyncio.run(run_test())
        self.assertEqual(asset_type, "stock")
        fetch_quote.assert_not_called()

    def test_cash_like_assets_use_unit_nav_validation(self) -> None:
        PortfolioService._validate_portfolio_price_fields("cash", 1.0)
        PortfolioService._validate_portfolio_price_fields("money_fund", 1.0)
        with self.assertRaises(ValueError):
            PortfolioService._validate_portfolio_price_fields("cash", 0.99)

    def test_otc_fund_trend_signal_uses_nav_rules(self) -> None:
        closes = [1.0 + index * 0.002 for index in range(65)]
        signal = build_otc_fund_trend_signal(self._history(closes))
        self.assertEqual(signal["action"], "buy")
        self.assertEqual(signal["label"], "正常定投")
        self.assertTrue(any(check["label"] == "净值站上 MA20" for check in signal["buyChecks"]))

    def test_otc_fund_trend_signal_slows_when_nav_breaks_down(self) -> None:
        closes = [1.2 - index * 0.004 for index in range(65)]
        signal = build_otc_fund_trend_signal(self._history(closes))
        self.assertIn(signal["action"], {"reduce", "watch"})
        self.assertIn(signal["label"], {"放缓定投", "观察修复"})

    def test_otc_fund_cost_nav_rejects_total_amount(self) -> None:
        with self.assertRaises(ValueError):
            PortfolioService._validate_portfolio_price_fields("otc_fund", 900.0)
        PortfolioService._validate_portfolio_price_fields("otc_fund", 0.9)
        PortfolioService._validate_portfolio_price_fields("etf", 900.0)


    def test_portfolio_cash_moves_with_trade_price_on_reduction(self) -> None:
        from decimal import Decimal
        from schemas.portfolio import PortfolioUpdate

        user = SimpleNamespace(account_balance=Decimal("10000.00"))
        portfolio = SimpleNamespace(
            id=1,
            user_id=7,
            etf_code="510300",
            asset_type="etf",
            shares=Decimal("100.00"),
            cost_price=Decimal("4.0000"),
            buy_date=None,
            note=None,
            dca_track_override=None,
            created_at=None,
            updated_at=None,
        )

        class FakeResult:
            def __init__(self, value):
                self.value = value

            def scalar_one_or_none(self):
                return self.value

        class FakeSession:
            def __init__(self):
                self.added = None
                self.created = None

            async def get(self, model, key):
                return user

            def add(self, item):
                self.added = item
                self.created = item
                if getattr(item, "id", None) is None:
                    item.id = 2
                    item.created_at = None
                    item.updated_at = None

            async def execute(self, statement):
                return FakeResult(portfolio)

            async def flush(self):
                pass

            async def refresh(self, item):
                pass

        async def run_test():
            session = FakeSession()
            with patch.object(PortfolioService, "detect_asset_type", return_value="etf"):
                await PortfolioService.create(session, PortfolioCreate(etf_code="510500", shares=200.0, cost_price=3.0), 7)
            after_create = user.account_balance
            await PortfolioService.update(session, 1, PortfolioUpdate(shares=150.0, cost_price=4.0), 7)
            after_add = user.account_balance
            with patch.object(PortfolioService, "_release_price_for_cash", return_value=Decimal("5.0")):
                await PortfolioService.update(session, 1, PortfolioUpdate(shares=80.0, cost_price=4.0), 7)
            after_reduce = user.account_balance
            return after_create, after_add, after_reduce

        import asyncio

        after_create, after_add, after_reduce = asyncio.run(run_test())
        self.assertEqual(after_create, Decimal("9400.00"))
        self.assertEqual(after_add, Decimal("9200.00"))
        self.assertEqual(after_reduce, Decimal("9550.00"))

    def test_delete_portfolio_cleans_dca_dependencies_and_releases_cash(self) -> None:
        from decimal import Decimal

        user = SimpleNamespace(account_balance=Decimal("1000.00"))
        portfolio = SimpleNamespace(id=41, user_id=7, etf_code="510300", asset_type="etf", shares=Decimal("100.00"), cost_price=Decimal("4.0000"))

        class FakeResult:
            def __init__(self, value):
                self.value = value

            def scalar_one_or_none(self):
                return self.value

        class FakeSession:
            def __init__(self):
                self.execute_calls = []
                self.deleted = None

            async def get(self, model, key):
                return user

            async def execute(self, statement):
                self.execute_calls.append(statement)
                return FakeResult(portfolio if len(self.execute_calls) == 1 else None)

            async def delete(self, item):
                self.deleted = item

        async def run_test():
            session = FakeSession()
            with patch.object(PortfolioService, "_release_price_for_cash", return_value=Decimal("5.0")):
                deleted = await PortfolioService.delete(session, 41, 7)
            return deleted, session

        import asyncio

        deleted, session = asyncio.run(run_test())
        cleanup_sql = [str(statement) for statement in session.execute_calls[1:]]
        self.assertTrue(deleted)
        self.assertEqual(len(session.execute_calls), 3)
        self.assertIn("portfolio_dca_signal_history", cleanup_sql[0])
        self.assertIn("portfolio_dca_state", cleanup_sql[1])
        self.assertIs(session.deleted, portfolio)
        self.assertEqual(user.account_balance, Decimal("1500.000"))


    def test_migrate_legacy_otc_fund_holdings_updates_confirmed_funds(self) -> None:
        class FakeScalarResult:
            def __init__(self, values):
                self.values = values

            def all(self):
                return self.values

        class FakeResult:
            def __init__(self, values):
                self.values = values

            def scalars(self):
                return FakeScalarResult(self.values)

        class FakeSession:
            def __init__(self):
                self.portfolios = [
                    SimpleNamespace(id=1, user_id=7, etf_code="000001", asset_type="etf"),
                    SimpleNamespace(id=2, user_id=7, etf_code="510300", asset_type="etf"),
                    SimpleNamespace(id=3, user_id=7, etf_code="159915", asset_type="etf"),
                ]
                self.calls = 0
                self.flushed = False

            async def execute(self, statement):
                self.calls += 1
                return FakeResult(self.portfolios if self.calls == 1 else ["510300"])

            async def flush(self):
                self.flushed = True

        async def run_test():
            dry_session = FakeSession()
            apply_session = FakeSession()
            with patch(
                "services.portfolio_service.MarketService._fetch_otc_fund_quote",
                new=AsyncMock(return_value=MarketQuote(code="000001", name="测试混合基金", price=1.234, change_pct=0.5)),
            ):
                dry = await PortfolioService.migrate_legacy_otc_fund_holdings(dry_session, dry_run=True)
                applied = await PortfolioService.migrate_legacy_otc_fund_holdings(apply_session, dry_run=False)
            return dry, applied, apply_session

        import asyncio

        dry, applied, session = asyncio.run(run_test())
        self.assertEqual(dry["matched"], 1)
        self.assertEqual(dry["updated"], 0)
        self.assertEqual(applied["matched"], 1)
        self.assertEqual(applied["updated"], 1)
        self.assertEqual(session.portfolios[0].asset_type, "otc_fund")
        self.assertEqual(session.portfolios[1].asset_type, "etf")
        self.assertEqual(session.portfolios[2].asset_type, "etf")
        self.assertTrue(session.flushed)


if __name__ == "__main__":
    unittest.main()
