import asyncio
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from models.market_daily import MarketDaily
from schemas.market import KLineItem
from services.market_service import MarketService
from services.market.http_client import market_http_client, close_market_http_clients


class MarketOptimizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_upsert_is_batched_and_updates_duplicates(self):
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        statements = []
        event.listen(engine.sync_engine, 'before_cursor_execute', lambda conn, cursor, statement, parameters, context, many: statements.append(statement))
        async with engine.begin() as conn:
            await conn.run_sync(MarketDaily.__table__.create)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        bars = [KLineItem(trade_date=date(2026, 1, 1), open_price=1, close_price=1.1, high_price=1.2, low_price=.9, volume=100, amount=110, change_pct=10, source="sse_history", amount_estimated=True)]
        async with maker() as session:
            statements.clear()
            await MarketService.save_market_daily(session, '159915', bars + bars)
            await session.commit()
            self.assertEqual(len(statements), 1)
            await MarketService.save_market_daily(session, '159915', [bars[0].model_copy(update={'amount': 120})])
            await session.commit()
            rows = (await session.execute(select(MarketDaily))).scalars().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(float(rows[0].amount), 120)
            self.assertEqual(rows[0].source, "sse_history")
            self.assertEqual(rows[0].adjustment, "none")
            self.assertTrue(rows[0].amount_estimated)
        await engine.dispose()

    async def test_http_client_is_reused_and_closed(self):
        async with market_http_client(8) as first:
            async with market_http_client(8) as second:
                self.assertIs(first, second)
        self.assertFalse(first.is_closed)
        await close_market_http_clients()
        self.assertTrue(first.is_closed)

    async def test_identical_quote_refreshes_share_a_task(self):
        with patch.object(MarketService, '_refresh_quotes', AsyncMock(return_value={})) as fetch:
            await asyncio.gather(*(MarketService.refresh_quotes(['159915','510300']) for _ in range(5)))
            fetch.assert_awaited_once_with(['159915','510300'])
        self.assertFalse(MarketService._QUOTE_REFRESH_TASKS)

    async def test_search_catalog_is_cached_and_query_is_literal(self):
        import pandas as pd
        MarketService._ETF_SEARCH_CACHE = None
        MarketService._ETF_SEARCH_EXPIRES_AT = 0
        MarketService._ETF_SEARCH_LOCK = asyncio.Lock()
        frame = pd.DataFrame([{'代码':'159915','名称':'创业板ETF'}])
        with (
            patch('services.market_service.ak.fund_etf_spot_em', return_value=frame) as fetch,
            patch.object(MarketService, '_search_sse_etf_catalog', AsyncMock(return_value=[])),
            patch('services.market_service.SzseService.search', AsyncMock(return_value=[])),
        ):
            self.assertEqual(len(await MarketService.search_etf('创业板')),1)
            self.assertEqual(await MarketService.search_etf('['),[])
            fetch.assert_called_once()
        MarketService._ETF_SEARCH_CACHE = None
