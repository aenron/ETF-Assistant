import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, Mock, patch
import pandas as pd
from schemas.market import KLineItem, MarketQuote
from services.market_service import MarketService as M
from utils.timezone import SHANGHAI_TZ

class MarketDataQualityTests(unittest.IsolatedAsyncioTestCase):
    def quote(self, stamp, **fields):
        return MarketQuote(code='510300', name='ETF', price=4, change_pct=0,
                           refreshed_at=datetime.fromisoformat(stamp).replace(tzinfo=SHANGHAI_TZ), **fields)

    def test_live_session_rejects_old_and_daily_quotes(self):
        now=datetime(2026,10,9,10,0,tzinfo=SHANGHAI_TZ)
        self.assertTrue(M._quote_is_fresh(self.quote('2026-10-09T09:59:00'),now))
        self.assertFalse(M._quote_is_fresh(self.quote('2026-10-09T09:50:00'),now))
        self.assertFalse(M._quote_is_fresh(self.quote('2026-10-09T09:59:00',quote_type='daily'),now))

    def test_weekend_accepts_friday_but_not_thursday(self):
        now=datetime(2026,10,11,10,0,tzinfo=SHANGHAI_TZ)
        self.assertTrue(M._quote_is_fresh(self.quote('2026-10-09T15:00:00'),now))
        self.assertFalse(M._quote_is_fresh(self.quote('2026-10-08T15:00:00'),now))

    def test_estimated_amount_is_explicit_and_source_input_unmodified(self):
        bar=KLineItem(trade_date=date(2026,10,9),open_price=4,close_price=4,high_price=4,low_price=4,volume=100,change_pct=0)
        actual=M._prepare_kline([bar],'sina_history_estimated_amount')[0]
        self.assertEqual(actual.amount,400)
        self.assertTrue(actual.amount_estimated)
        self.assertEqual(actual.source,'sina_history_estimated_amount')
        self.assertIsNone(bar.source)
        self.assertIsNone(bar.amount)
        self.assertEqual(KLineItem.model_validate_json(actual.model_dump_json()),actual)

    def test_tushare_units_and_source_time(self):
        pro=Mock()
        pro.daily.return_value=pd.DataFrame([dict(trade_date='20261009',open=4,close=4,high=4,low=4,vol=2,amount=3,pct_chg=0)])
        pro.stock_basic.return_value=pd.DataFrame([dict(name='ETF')])
        with patch.object(M,'_get_tushare_pro',return_value=pro):
            q=M._fetch_tushare_quotes_sync(['510300'])['510300']
            bars=M._fetch_history_kline_tushare_sync('510300',days=1)
        self.assertEqual((q.volume,q.amount,q.quote_type),(200,3000,'daily'))
        self.assertEqual((bars[0].volume,bars[0].amount),(200,3000))
        self.assertEqual(q.refreshed_at.hour,15)

    def test_sse_timestamp_is_exchange_time(self):
        quote=M._parse_sse_snapshot('510300',{'date':20261009,'time':162901,'snap':['ETF',4,0,0,100,100,4,4,[],[],4,4]})
        self.assertEqual(quote.refreshed_at,datetime(2026,10,9,16,29,1,tzinfo=SHANGHAI_TZ))

    async def test_failed_refresh_returns_explicitly_stale_cache(self):
        old=self.quote('2026-10-08T15:00:00')
        with patch.object(M,'get_quote_from_cache',AsyncMock(return_value=old)),patch.object(M,'refresh_quotes',AsyncMock(return_value={})),patch('services.market_service.now_in_shanghai',return_value=datetime(2026,10,9,10,tzinfo=SHANGHAI_TZ)):
            result=await M.get_quotes_for_codes(['510300'])
        self.assertTrue(result['510300'].stale)
        self.assertEqual(result['510300'].refreshed_at,old.refreshed_at)

    async def test_unknown_source_timestamp_is_not_fabricated(self):
        q=MarketQuote(code='510300',name='ETF',price=4,change_pct=0,source='eastmoney_etf_spot')
        with patch('services.market_service.settings.redis_enabled',False):
            result=await M.cache_quote(q.code,q)
        self.assertIsNone(result.refreshed_at)
        self.assertIsNotNone(result.fetched_at)
        self.assertTrue(result.stale)
