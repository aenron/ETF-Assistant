import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from services.szse_service import SzseService
from services.market_service import MarketService
from services.miaoxiang_service import MiaoxiangService
from utils.timezone import SHANGHAI_TZ


def quote_payload():
    return {"code": "0", "datetime": "2026-10-09 15:30", "data": {
        "code": "159915", "name": "创业板ETF易方达", "now": "3.064", "close": "3.053",
        "open": "3.029", "high": "3.074", "low": "2.952", "deltaPercent": "0.36",
        "volume": 27315167, "amount": 8210662643.918, "marketTime": "2026-10-09 15:30:00",
        "netValue": "99", "piciopv": [["15:00", "3.064"], ["15:30", 0]],
    }}


def history_payload():
    return {"code": "0", "data": {"code": "159915", "picupdata": [
        ["2026-10-09", "3.029", "3.064", "2.952", "3.074", ".011", ".36", 27315167, 8210662644],
        ["2026-10-08", "3", "3.053", "2.9", "3.1", ".053", "1.77", 100, 30000],
    ]}}


class SzseParsingTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch("services.szse_service.now_in_shanghai", return_value=datetime(2026, 10, 11, 12, tzinfo=SHANGHAI_TZ))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_supported_codes(self):
        self.assertTrue(SzseService.supports("158030"))
        self.assertTrue(SzseService.supports("159915"))
        for code in ("510300", "004432", "300059", "159915.SH", "159915/../../"):
            self.assertFalse(SzseService.supports(code))

    def test_quote_units_and_source_time(self):
        quote = SzseService.parse_quote("159915", quote_payload())
        self.assertEqual(quote.price, 3.064)
        self.assertEqual(quote.volume, 2731516700)
        self.assertEqual(quote.amount, 8210662643.918)
        self.assertEqual(quote.refreshed_at, datetime(2026, 10, 9, 15, 30, tzinfo=SHANGHAI_TZ))
        self.assertEqual(quote.iopv, 3.064)
        self.assertAlmostEqual(quote.premium_rate, 0)

    def test_net_value_is_not_iopv(self):
        payload = quote_payload()
        payload["data"]["piciopv"] = [["15:30", 0], ["15:00", "NaN"]]
        self.assertIsNone(SzseService.parse_quote("159915", payload).iopv)

    def test_invalid_quotes_are_skipped(self):
        for field, value in (("now", "NaN"), ("high", "2"), ("marketTime", "2025-01-01 15:00:00"), ("marketTime", "2027-01-01"), ("code", "510300"), ("isPurposeful", True)):
            payload = quote_payload()
            payload["data"][field] = value
            self.assertIsNone(SzseService.parse_quote("159915", payload))
        self.assertIsNone(SzseService.parse_quote("159915", {"code": "-1"}))

    def test_change_uses_exchange_previous_close(self):
        payload = quote_payload()
        payload["data"].pop("deltaPercent")
        self.assertAlmostEqual(SzseService.parse_quote("159915", payload).change_pct, (3.064 / 3.053 - 1) * 100)

    def test_history_order_units_and_amount(self):
        bars = SzseService.parse_history("159915", history_payload(), 2)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[-1].high_price, 3.074)
        self.assertEqual(bars[-1].low_price, 2.952)
        self.assertEqual(bars[-1].volume, 2731516700)
        self.assertEqual(bars[-1].amount, 8210662644)
        self.assertLess(bars[0].trade_date, bars[-1].trade_date)
        self.assertEqual(SzseService.parse_history("159915", history_payload(), 250), [])

    def test_history_filters_provisional_duplicates_and_invalid_bars(self):
        payload = history_payload()
        payload["data"]["picupdata"] += [payload["data"]["picupdata"][1], ["2026-10-12", "1", "1", "1", "1", "0", "0", 1, 1]]
        with patch("services.szse_service.now_in_shanghai", return_value=datetime(2026, 10, 9, 14, tzinfo=SHANGHAI_TZ)):
            bars = SzseService.parse_history("159915", payload, 1)
            self.assertEqual(str(bars[0].trade_date), "2026-10-08")
        payload["data"]["picupdata"][0][8] = "Infinity"
        self.assertEqual(SzseService.parse_history("159915", payload, 2), [])


class SzseRequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        SzseService._cache.clear()
        SzseService._locks.clear()
        SzseService._cooldown_until = 0
        enabled = patch("services.szse_service.settings.szse_enabled", True)
        enabled.start()
        self.addCleanup(enabled.stop)

    async def test_request_dedup_and_cache(self):
        client = AsyncMock()
        response = MagicMock()
        response.json.return_value = quote_payload()
        client.get.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch("services.szse_service.market_http_client", return_value=context):
            result = await asyncio.gather(*(SzseService._get("/quote", {"code": "159915"}, 20) for _ in range(3)))
        self.assertEqual(len(result), 3)
        client.get.assert_awaited_once()

    async def test_failure_cooldown(self):
        with patch("services.szse_service.market_http_client", side_effect=RuntimeError) as client:
            self.assertIsNone(await SzseService._get("/quote", {}, 20))
            self.assertIsNone(await SzseService._get("/history", {}, 20))
            client.assert_called_once()

    async def test_disabled_and_unsupported_skip_network(self):
        with patch("services.szse_service.market_http_client") as client:
            self.assertEqual(await SzseService.fetch_quotes(["510300", "004432"]), {})
            self.assertEqual(await SzseService.fetch_history("510300"), [])
            with patch("services.szse_service.settings.szse_enabled", False):
                self.assertIsNone(await SzseService._get("/quote", {}, 20))
            client.assert_not_called()

    async def test_catalog_search_strips_html_and_uses_server_filter(self):
        payload = [{"metadata": {"pagecount": 1}, "data": [
            {"sys_key": "<a><u>159915</u></a>", "kzjcurl": "<a>创业板ETF易方达</a> <a><img /></a>"},
            {"sys_key": "510300", "kzjcurl": "沪深300ETF"},
        ]}]
        with patch.object(SzseService, "_get", AsyncMock(return_value=payload)) as fetch:
            results = await SzseService.search("创业板")
            self.assertEqual([r.code for r in results], ["159915"])
            self.assertEqual(results[0].name, "创业板ETF易方达")
            self.assertEqual(fetch.call_args.args[1]["txtQueryKeyAndJC"], "创业板")

    async def test_history_precedes_miaoxiang_and_sina(self):
        with patch("services.szse_service.now_in_shanghai", return_value=datetime(2026, 10, 11, tzinfo=SHANGHAI_TZ)):
            bars = SzseService.parse_history("159915", history_payload(), 2)
        with (
            patch.object(MarketService, "get_kline_from_cache", AsyncMock(return_value=None)),
            patch.object(MarketService, "_fetch_history_kline_zhitu_index", AsyncMock(return_value=[])),
            patch.object(MarketService, "_fetch_history_kline_ths_industry", return_value=[]),
            patch.object(MarketService, "_fetch_history_kline_sse", AsyncMock(return_value=[])),
            patch.object(SzseService, "fetch_history", AsyncMock(return_value=bars)),
            patch.object(MiaoxiangService, "fetch_history", AsyncMock()) as mx,
            patch.object(MarketService, "_fetch_history_kline_sina", AsyncMock()) as sina,
            patch.object(MarketService, "_cache_and_store_kline", AsyncMock()) as store,
        ):
            self.assertEqual(await MarketService.get_history_kline("159915", 2, prefer_cache=False), bars)
            store.assert_awaited_once_with("159915", 2, bars)
            mx.assert_not_awaited()
            sina.assert_not_awaited()

    async def test_quote_precedes_sina(self):
        with patch("services.szse_service.now_in_shanghai", return_value=datetime(2026, 10, 11, tzinfo=SHANGHAI_TZ)):
            quote = SzseService.parse_quote("159915", quote_payload())
        with (
            patch.object(MarketService, "_fetch_from_sse_api", AsyncMock(return_value={})),
            patch.object(SzseService, "fetch_quotes", AsyncMock(return_value={"159915": quote})),
            patch.object(MarketService, "_fetch_from_sina_api", AsyncMock()) as sina,
            patch.object(MarketService, "cache_quote", AsyncMock(side_effect=lambda code, value: value)),
        ):
            result = await MarketService._fetch_quotes_from_akshare(["159915"])
            self.assertEqual(result["159915"].price, 3.064)
            sina.assert_not_awaited()
