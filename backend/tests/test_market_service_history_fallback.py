import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))

from schemas.market import KLineItem
from schemas.market import MarketQuote
from services.market_service import MarketService
from utils.timezone import now_in_shanghai


class MarketServiceHistoryFallbackTests(unittest.IsolatedAsyncioTestCase):
    def test_sina_symbol_uses_stock_market_prefix(self) -> None:
        self.assertEqual(MarketService._sina_symbol("300059"), "sz300059")
        self.assertEqual(MarketService._sina_symbol("000001"), "sz000001")
        self.assertEqual(MarketService._sina_symbol("159915"), "sz159915")
        self.assertEqual(MarketService._sina_symbol("600519"), "sh600519")
        self.assertEqual(MarketService._sina_symbol("688111"), "sh688111")
        self.assertEqual(MarketService._sina_symbol("513300"), "sh513300")

    def test_expected_kline_min_date_uses_previous_trading_day_intraday(self) -> None:
        from datetime import datetime
        from utils.timezone import SHANGHAI_TZ

        self.assertEqual(
            MarketService._expected_kline_min_date(datetime(2026, 7, 7, 14, 30, tzinfo=SHANGHAI_TZ)),
            date(2026, 7, 6),
        )
        self.assertEqual(
            MarketService._expected_kline_min_date(datetime(2026, 7, 7, 15, 11, tzinfo=SHANGHAI_TZ)),
            date(2026, 7, 7),
        )

    async def test_append_realtime_daily_point_marks_provisional(self) -> None:
        from datetime import datetime
        from utils.timezone import SHANGHAI_TZ

        history = [
            KLineItem(
                trade_date=date(2026, 7, 6),
                open_price=1.46,
                close_price=1.49,
                high_price=1.50,
                low_price=1.45,
                volume=1000,
                amount=100000.0,
                change_pct=1.8,
            )
        ]
        quote = MarketQuote(
            code="515080",
            name="中证红利ETF招商",
            price=1.473,
            change_pct=-1.14,
            open_price=1.492,
            high_price=1.492,
            low_price=1.464,
            volume=2564587,
            amount=377439400.0,
            refreshed_at=datetime(2026, 7, 7, 14, 34, tzinfo=SHANGHAI_TZ),
        )

        with patch.object(MarketService, "get_quote_from_cache", new=AsyncMock(return_value=quote)):
            result = await MarketService.append_realtime_daily_point("515080", history)

        self.assertEqual(len(result), 2)
        self.assertTrue(result[-1].provisional)
        self.assertEqual(result[-1].trade_date, date(2026, 7, 7))
        self.assertEqual(result[-1].close_price, 1.473)

    async def test_history_kline_uses_db_before_public_sources(self) -> None:
        db_kline = [
            KLineItem(
                trade_date=now_in_shanghai().date(),
                open_price=1.0,
                close_price=1.02,
                high_price=1.03,
                low_price=0.99,
                volume=1000,
                amount=1020.0,
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

    async def test_history_kline_refreshes_when_cached_data_is_stale(self) -> None:
        stale_kline = [
            KLineItem(
                trade_date=now_in_shanghai().date() - timedelta(days=7),
                open_price=1.0,
                close_price=1.02,
                high_price=1.03,
                low_price=0.99,
                volume=1000,
                change_pct=2.0,
            )
        ]
        fresh_kline = [
            KLineItem(
                trade_date=now_in_shanghai().date(),
                open_price=1.1,
                close_price=1.12,
                high_price=1.13,
                low_price=1.09,
                volume=1200,
                change_pct=1.8,
            )
        ]

        with (
            patch.object(MarketService, "get_kline_from_cache", new=AsyncMock(return_value=stale_kline)),
            patch.object(MarketService, "get_kline_from_longer_cache", new=AsyncMock(return_value=None)),
            patch.object(MarketService, "get_kline_from_db", new=AsyncMock(return_value=None)),
            patch.object(MarketService, "_fetch_history_kline_ths_industry", return_value=fresh_kline) as ths_fetch,
            patch.object(MarketService, "_cache_and_store_kline", new=AsyncMock()) as cache_store,
        ):
            result = await MarketService.get_history_kline("513300", days=60)

        self.assertEqual(result, fresh_kline)
        ths_fetch.assert_called_once_with("513300", 60)
        cache_store.assert_awaited_once_with("513300", 60, fresh_kline)

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

    async def test_intraday_period_falls_back_to_5m_before_quote(self) -> None:
        from datetime import datetime
        from utils.timezone import SHANGHAI_TZ

        five_minute_data = [KLineItem(
            trade_date=date(2026, 7, 8),
            trade_time=datetime(2026, 7, 8, 13, 20, tzinfo=SHANGHAI_TZ),
            open_price=1.0,
            close_price=1.01,
            high_price=1.02,
            low_price=0.99,
            volume=1000,
            amount=10000.0,
            change_pct=0.0,
        )]
        calls: list[str] = []

        async def qmt_fetch(_code: str, period: str, _limit: int):
            calls.append(period)
            return five_minute_data if period == "5m" else []

        with (
            patch.object(MarketService, "_fetch_intraday_kline_qmt_agent", new=qmt_fetch),
            patch.object(MarketService, "_fetch_intraday_kline_eastmoney", new=AsyncMock(return_value=[])),
            patch("services.market_service.now_in_shanghai", return_value=datetime(2026, 7, 8, 13, 25, tzinfo=SHANGHAI_TZ)),
        ):
            result, source = await MarketService.get_intraday_kline_with_source("589850", period="1m", limit=240)

        self.assertEqual(source, "intraday_5m")
        self.assertEqual(len(result), 1)
        self.assertEqual(calls, ["1m", "5m"])

    async def test_intraday_falls_back_to_realtime_quote(self) -> None:
        from datetime import datetime
        from utils.timezone import SHANGHAI_TZ

        quote = MarketQuote(
            code="515080",
            name="中证红利ETF招商",
            price=1.473,
            change_pct=0.14,
            open_price=1.471,
            high_price=1.491,
            low_price=1.462,
            volume=1640504,
            amount=242263500.0,
            refreshed_at=datetime(2026, 7, 8, 13, 15, tzinfo=SHANGHAI_TZ),
        )

        with (
            patch.object(MarketService, "_fetch_intraday_kline_qmt_agent", new=AsyncMock(return_value=[])),
            patch.object(MarketService, "_fetch_intraday_kline_eastmoney", new=AsyncMock(return_value=[])),
            patch.object(MarketService, "get_quote_from_cache", new=AsyncMock(return_value=quote)),
            patch("services.market_service.now_in_shanghai", return_value=datetime(2026, 7, 8, 13, 20, tzinfo=SHANGHAI_TZ)),
        ):
            result = await MarketService.get_intraday_kline("515080", period="1m", limit=240)

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].provisional)
        self.assertEqual(result[0].trade_date, date(2026, 7, 8))
        self.assertEqual(result[0].close_price, 1.473)

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
                        "amount": 123456.0,
                    }
                ],
            },
        })

        self.assertEqual(len(records), 1)
        self.assertEqual(MarketService._qmt_timestamp_to_date(records[0]["time"]), date(2026, 5, 8))
        self.assertEqual(records[0]["amount"], 123456.0)

    async def test_qmt_history_keeps_amount_on_kline_items(self) -> None:
        payload = {
            "item": {
                "type": "records",
                "records": [
                    {
                        "time": "20260508",
                        "open": 1.0,
                        "high": 1.03,
                        "low": 0.99,
                        "close": 1.02,
                        "volume": 1000,
                        "amount": 123456.0,
                    }
                ],
            }
        }

        with patch.object(MarketService, "_fetch_qmt_agent", new=AsyncMock(return_value=payload)):
            result = await MarketService._fetch_history_kline_qmt_agent("513300", days=60)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].amount, 123456.0)

    def test_ohlcv_dataframe_keeps_amount_on_kline_items(self) -> None:
        pd = __import__("pandas")
        df = pd.DataFrame([
            {
                "日期": "2026-05-08",
                "开盘": 1.0,
                "收盘": 1.02,
                "最高": 1.03,
                "最低": 0.99,
                "成交量": 1000,
                "成交额": 123456.0,
                "涨跌幅": 2.0,
            }
        ])

        result = MarketService._items_from_ohlcv_df(df, days=60)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].amount, 123456.0)

    def test_otc_fund_candidates_skip_listed_securities_and_existing_quotes(self) -> None:
        existing = {
            "001513": MarketQuote(code="001513", name="已有基金", price=1.0, change_pct=0.0),
        }

        result = MarketService._otc_fund_candidate_codes([
            "000725",
            "000811",
            "515080",
            "589850",
            "001513",
            "004432",
        ], existing)

        self.assertEqual(result, ["004432"])

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

    def test_payload_summary_includes_safe_shape(self) -> None:
        summary = MarketService._payload_summary({
            "code": 0,
            "message": "ok",
            "item": {"type": "dataframe", "records": [], "columns": ["time", "close"]},
            "data": {"records": [], "extra": "hidden"},
            "items": [1, 2, 3],
        })

        self.assertIn("keys=", summary)
        self.assertIn("code='0'", summary)
        self.assertIn("item=dict", summary)
        self.assertIn("records=list(len=0)", summary)
        self.assertIn("data=dict", summary)
        self.assertIn("items=list(len=3)", summary)

    def test_eastmoney_intraday_breaker_opens_after_consecutive_failures(self) -> None:
        key = MarketService._eastmoney_intraday_breaker_key("589850", "1m")
        MarketService._EASTMONEY_INTRADAY_FAILURES.pop(key, None)
        MarketService._EASTMONEY_INTRADAY_BREAKER_UNTIL.pop(key, None)

        with patch("services.market_service.time.time", return_value=1000.0):
            MarketService._record_eastmoney_intraday_failure("589850", "1m")
            self.assertFalse(MarketService._is_eastmoney_intraday_breaker_open("589850", "1m"))
            MarketService._record_eastmoney_intraday_failure("589850", "1m")
            self.assertTrue(MarketService._is_eastmoney_intraday_breaker_open("589850", "1m"))
            self.assertTrue(MarketService._is_eastmoney_intraday_breaker_open("589850", "5m"))

        with patch("services.market_service.time.time", return_value=1200.0):
            self.assertFalse(MarketService._is_eastmoney_intraday_breaker_open("589850", "1m"))

        MarketService._EASTMONEY_INTRADAY_FAILURES.pop(key, None)
        MarketService._EASTMONEY_INTRADAY_BREAKER_UNTIL.pop(key, None)


if __name__ == "__main__":
    unittest.main()
