import asyncio
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.miaoxiang_service import MiaoxiangService
from services.szse_service import SzseService
from services.market_service import MarketService


def payload(symbol="510300.SH"):
    fields = {
        "OPEN": ("开盘价", ["4.369", "4.418", "4.42"]),
        "HIGH": ("最高价", ["4.4", "4.459", "4.46"]),
        "LOW": ("最低价", ["4.309", "4.358", "4.4"]),
        "CLOSE": ("收盘价", ["4.385", "4.389", "4.432"]),
        "PRE_CLOSE": ("前收盘价", ["4.389", "4.432", "4.45"]),
        "VOLUME": ("成交量", ["1276733125", "750872537", "500000000"]),
        "AMOUNT": ("成交额", ["5564821743", "3307953958", "2000000000"]),
        "DECFQDWJZZZL": ("复权单位净值增长率", ["0.1643", "-1.097", "0.12"]),
    }
    dto = {
        "code": symbol, "entityTagDTO": {"shortName": "沪深300ETF"},
        "rawTable": {"headName": ["2026-10-09", "2026-10-08", "2026-09-30"], **{k: v[1] for k, v in fields.items()}},
        "nameMap": {k: v[0] for k, v in fields.items()},
        "fieldSet": [{"returnCode": k, "returnSourceCode": k, "returnName": v[0]} for k, v in fields.items()],
    }
    return {"success": True, "status": 0, "data": {"status": 0, "data": {"searchDataResultDTO": {"dataTableDTOList": [dto]}}}}


def table(result):
    return result["data"]["data"]["searchDataResultDTO"]["dataTableDTOList"][0]


class MiaoxiangParsingTests(unittest.TestCase):
    def setUp(self):
        fixed = patch.object(MiaoxiangService, "_completed_date", return_value=date(2026, 10, 9))
        fixed.start()
        self.addCleanup(fixed.stop)

    def test_quote_uses_exchange_prices_not_nav_growth(self):
        quote = MiaoxiangService.parse_quote("510300", payload())
        self.assertAlmostEqual(quote.change_pct, (4.385 / 4.389 - 1) * 100, places=4)
        self.assertEqual(quote.amount, 5564821743)
        self.assertEqual(quote.volume, 1276733125)
        self.assertEqual(quote.refreshed_at.date(), date(2026, 10, 9))
        self.assertEqual(quote.refreshed_at.hour, 15)

    def test_previous_close_can_be_derived_from_two_exchange_closes(self):
        result = payload()
        del table(result)["rawTable"]["PRE_CLOSE"]
        quote = MiaoxiangService.parse_quote("510300", result)
        self.assertAlmostEqual(quote.change_pct, (4.385 / 4.389 - 1) * 100, places=4)
        for key, values in table(result)["rawTable"].items():
            table(result)["rawTable"][key] = values[:1]
        self.assertIsNone(MiaoxiangService.parse_quote("510300", result))

    def test_nested_rate_limit_and_wrong_security_are_rejected(self):
        self.assertIsNone(MiaoxiangService.parse_quote("159915", payload()))
        limited = {"status": 0, "data": {"status": -1, "code": 503, "data": payload()}}
        self.assertEqual(MiaoxiangService._business_error(limited), 503)
        self.assertIsNone(MiaoxiangService.parse_quote("510300", limited))

    def test_scaled_units_and_nonfinite_values(self):
        self.assertEqual(MiaoxiangService._number("1.2亿股"), 120000000)
        self.assertEqual(MiaoxiangService._number("2.5", "万手"), 2500000)
        self.assertEqual(MiaoxiangService._number("55.65亿"), 5565000000)
        self.assertEqual(MiaoxiangService._number(0), 0)
        for value in (None, True, "NaN", "inf", "1e999", "0.1%"):
            self.assertIsNone(MiaoxiangService._number(value))

    def test_history_requires_complete_bars_and_requested_length(self):
        result = payload()
        bars = MiaoxiangService.parse_history("510300", result, 2)
        self.assertEqual([x.trade_date for x in bars], [date(2026, 10, 8), date(2026, 10, 9)])
        self.assertEqual(bars[-1].amount, 5564821743)
        self.assertEqual(MiaoxiangService.parse_history("510300", result, 60), [])
        del table(result)["rawTable"]["AMOUNT"]
        self.assertEqual(MiaoxiangService.parse_history("510300", result, 2), [])

    def test_future_stale_interval_and_nav_only_rows_are_rejected(self):
        for dates in (["2026-10-12"], ["2026-08-01"], ["2026-07-13至2026-10-09"]):
            result = payload()
            table(result)["rawTable"]["headName"] = dates
            self.assertIsNone(MiaoxiangService.parse_quote("510300", result))
        result = payload()
        dto = table(result)
        dto["nameMap"]["CLOSE"] = "单位净值"
        self.assertIsNone(MiaoxiangService.parse_quote("510300", result))


class MiaoxiangRequestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        MiaoxiangService._lock = asyncio.Lock()
        MiaoxiangService._cache = {}
        MiaoxiangService._blocked_until = 0
        MiaoxiangService._last_request = 0
        for name, value in (("mx_enabled", True), ("mx_apikey", SecretStr("test-key")), ("mx_min_interval_seconds", 0)):
            p = patch.object(sys.modules[MiaoxiangService.__module__].settings, name, value)
            p.start()
            self.addCleanup(p.stop)

    def client(self, data):
        response = MagicMock()
        response.json.return_value = data
        client = AsyncMock()
        client.post.return_value = response
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        return client, context

    async def test_concurrent_identical_queries_share_one_request(self):
        client, context = self.client(payload())
        with patch("services.miaoxiang_service.market_http_client", return_value=context):
            results = await asyncio.gather(*(MiaoxiangService._query("query", 300) for _ in range(3)))
        self.assertEqual(len(results), 3)
        client.post.assert_awaited_once()
        self.assertEqual(client.post.call_args.kwargs["headers"], {"apikey": "test-key"})

    async def test_business_error_cools_down_and_does_not_cache_success(self):
        client, context = self.client({"status": 0, "data": {"status": -1, "code": 113}})
        with patch("services.miaoxiang_service.market_http_client", return_value=context):
            self.assertEqual(await MiaoxiangService._query("first", 300), {})
            self.assertEqual(await MiaoxiangService._query("second", 300), {})
        client.post.assert_awaited_once()
        self.assertEqual(MiaoxiangService._cache, {})


class MiaoxiangIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_quote_fallback_runs_only_when_realtime_sources_miss(self):
        with patch.object(MiaoxiangService, "_completed_date", return_value=date(2026, 10, 9)):
            quote = MiaoxiangService.parse_quote("510300", payload()).model_copy(update={"iopv": 4.3})
        for realtime in ({"510300": quote}, {}):
            with (
                patch.object(MarketService, "_fetch_from_sse_api", AsyncMock(return_value={})),
                patch.object(SzseService, "fetch_quotes", new=AsyncMock(return_value={})),
                patch.object(MarketService, "_fetch_from_sina_api", AsyncMock(return_value=realtime)),
                patch.object(MarketService, "_fetch_from_tencent_api", AsyncMock(return_value={})),
                patch.object(MiaoxiangService, "enabled", return_value=True),
                patch.object(MiaoxiangService, "fetch_quotes", AsyncMock(return_value={"510300": quote})) as mx,
                patch.object(MarketService, "cache_quote", AsyncMock(side_effect=lambda code, value: value)),
            ):
                result = await MarketService._fetch_quotes_from_akshare(["510300"])
                self.assertEqual(result["510300"].price, 4.385)
                self.assertEqual(mx.await_count, 0 if realtime else 1)

    async def test_miaoxiang_history_precedes_estimated_turnover(self):
        with patch.object(MiaoxiangService, "_completed_date", return_value=date(2026, 10, 9)):
            bars = MiaoxiangService.parse_history("510300", payload(), 2)
        with (
            patch.object(MarketService, "get_kline_from_cache", AsyncMock(return_value=None)),
            patch.object(MarketService, "_fetch_history_kline_zhitu_index", AsyncMock(return_value=[])),
            patch.object(MarketService, "_fetch_history_kline_ths_industry", return_value=[]),
            patch.object(MarketService, "_fetch_history_kline_sse", AsyncMock(return_value=[])),
            patch.object(SzseService, "fetch_history", new=AsyncMock(return_value=[])),
            patch.object(MarketService, "_fetch_history_kline_tushare", AsyncMock(return_value=[])),
            patch.object(MiaoxiangService, "fetch_history", AsyncMock(return_value=bars)),
            patch.object(MarketService, "_fetch_history_kline_sina", AsyncMock()) as sina,
            patch.object(MarketService, "_cache_and_store_kline", AsyncMock()),
        ):
            self.assertEqual(await MarketService.get_history_kline("510300", 2, prefer_cache=False), bars)
            sina.assert_not_awaited()
