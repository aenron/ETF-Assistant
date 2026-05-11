import asyncio
import akshare as ak
import httpx
import pandas as pd
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import time
import os
import random
import json

# 设置环境变量模拟浏览器
os.environ.setdefault('HTTP_USER_AGENT', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

from models import EtfInfo, EtfProfile, MarketDaily
from schemas.market import MarketQuote, KLineItem, EtfSearchResult, TechnicalIndicators
from config import settings
from services.redis_service import RedisService
from utils.timezone import now_in_shanghai


class MarketService:
    """行情服务 - AKShare封装"""
    
    # Redis缓存key
    REDIS_KEY_QUOTE_PREFIX = "etf:quote:"
    REDIS_KEY_KLINE_PREFIX = "etf:kline:"
    REDIS_KEY_PROFILE_PREFIX = "etf:profile:"
    REDIS_KEY_ALL_QUOTES = "etf:all_quotes"
    CACHE_EXPIRE_SECONDS = 604800  # 7天缓存 (7 * 24 * 60 * 60)
    KLINE_CACHE_EXPIRE_SECONDS = 7200  # 2小时缓存
    PROFILE_CACHE_EXPIRE_SECONDS = 86400  # ETF资料1天缓存，后台定时刷新

    @staticmethod
    def _with_refresh_time(
        quote: MarketQuote,
        refreshed_at: Optional[datetime] = None,
    ) -> MarketQuote:
        """为行情附加刷新时间"""
        return quote.model_copy(update={"refreshed_at": refreshed_at or now_in_shanghai()})
    
    @classmethod
    async def get_quote_from_cache(cls, code: str) -> Optional[MarketQuote]:
        """从Redis缓存获取单个ETF行情"""
        if not settings.redis_enabled:
            return None
        cached = await RedisService.get(f"{cls.REDIS_KEY_QUOTE_PREFIX}{code}")
        if cached and "data" in cached:
            data = dict(cached["data"])
            data["refreshed_at"] = data.get("refreshed_at") or cached.get("cached_at")
            return MarketQuote(**data)
        return None

    @classmethod
    def _kline_cache_key(cls, code: str, days: int) -> str:
        return f"{cls.REDIS_KEY_KLINE_PREFIX}{code}:{days}"

    @classmethod
    def _profile_cache_key(cls, code: str, year: str) -> str:
        return f"{cls.REDIS_KEY_PROFILE_PREFIX}{code}:{year}"

    @classmethod
    async def get_kline_from_cache(cls, code: str, days: int) -> Optional[List[KLineItem]]:
        """从 Redis 读取历史 K 线缓存"""
        if not settings.redis_enabled:
            return None

        cached = await RedisService.get(cls._kline_cache_key(code, days))
        if not cached or "data" not in cached:
            return None

        try:
            return [KLineItem(**item) for item in cached["data"]]
        except Exception as e:
            print(f"[MarketService] K线缓存反序列化失败: {code}, {e}")
            return None

    @classmethod
    async def cache_kline(cls, code: str, days: int, data: List[KLineItem]) -> None:
        """缓存历史 K 线到 Redis"""
        if not settings.redis_enabled or not data:
            return

        payload = {
            "data": [item.model_dump(mode="json") for item in data],
            "cached_at": now_in_shanghai().isoformat(),
        }
        await RedisService.set(
            cls._kline_cache_key(code, days),
            payload,
            expire=cls.KLINE_CACHE_EXPIRE_SECONDS,
        )

    @classmethod
    async def get_etf_profile_from_cache(cls, code: str, year: str) -> Optional[Dict[str, Any]]:
        if not settings.redis_enabled:
            return None
        cached = await RedisService.get(cls._profile_cache_key(code, year))
        if cached and "data" in cached:
            return cached["data"]
        return None

    @classmethod
    async def cache_etf_profile(cls, code: str, year: str, data: Dict[str, Any]) -> None:
        if not settings.redis_enabled:
            return
        await RedisService.set(
            cls._profile_cache_key(code, year),
            {
                "data": data,
                "cached_at": now_in_shanghai().isoformat(),
            },
            expire=cls.PROFILE_CACHE_EXPIRE_SECONDS,
        )
    
    @classmethod
    async def cache_quote(cls, code: str, quote: MarketQuote) -> MarketQuote:
        """缓存单个ETF行情到Redis（带时间戳）"""
        # 不缓存空数据或价格为0的数据
        if quote.price <= 0:
            print(f"[MarketService] 跳过缓存空数据: {code}")
            return quote

        quote_with_time = cls._with_refresh_time(quote, quote.refreshed_at)
        if settings.redis_enabled:
            cache_data = {
                "data": quote_with_time.model_dump(mode="json"),
                "cached_at": quote_with_time.refreshed_at.isoformat() if quote_with_time.refreshed_at else now_in_shanghai().isoformat(),
                "cache_date": now_in_shanghai().date().isoformat(),
            }
            await RedisService.set(
                f"{cls.REDIS_KEY_QUOTE_PREFIX}{code}", 
                cache_data, 
                expire=cls.CACHE_EXPIRE_SECONDS
            )
        return quote_with_time
    
    @classmethod
    async def get_quotes_for_codes(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """获取指定ETF代码的行情（优先从Redis缓存，失败时使用旧缓存）"""
        result = {}
        uncached_codes = []
        
        # 先从Redis获取
        for code in codes:
            cached = await cls.get_quote_from_cache(code)
            if cached:
                result[code] = cached
            else:
                uncached_codes.append(code)
        
        # 未缓存的从AKShare获取
        if uncached_codes:
            try:
                quotes = await cls._fetch_quotes_from_akshare(uncached_codes)
                for code, quote in quotes.items():
                    result[code] = quote
            except Exception as e:
                print(f"[MarketService] ✗ 获取行情失败: {e}")
                # 尝试从旧缓存获取（即使过期）
                for code in uncached_codes:
                    if code not in result:
                        cached = await cls._get_expired_cache(code)
                        if cached:
                            print(f"[MarketService] ⚠ 使用过期缓存数据: {code}")
                            result[code] = cached
        
        return result
    
    @classmethod
    async def refresh_quote(cls, code: str) -> Optional[MarketQuote]:
        """强制刷新单个ETF行情（跳过缓存）"""
        try:
            quotes = await cls._fetch_quotes_from_akshare([code])
            if code in quotes:
                return quotes[code]
        except Exception as e:
            print(f"[MarketService] 刷新行情失败: {code}, {e}")
        return None
    
    @classmethod
    async def refresh_quotes(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """强制刷新多个ETF行情（跳过缓存）"""
        if not codes:
            return {}
        
        try:
            quotes = await cls._fetch_quotes_from_akshare(codes)
            return quotes
        except Exception as e:
            print(f"[MarketService] 批量刷新行情失败: {e}")
            return {}
    
    @classmethod
    async def _get_expired_cache(cls, code: str) -> Optional[MarketQuote]:
        """获取过期的缓存数据（作为降级方案）"""
        if not settings.redis_enabled:
            return None
        try:
            cached = await RedisService.get(f"{cls.REDIS_KEY_QUOTE_PREFIX}{code}")
            if cached and "data" in cached:
                return MarketQuote(**cached["data"])
        except Exception:
            pass
        return None
    
    @classmethod
    def _build_default_headers(cls, referer: str) -> Dict[str, str]:
        return {
            "User-Agent": os.environ["HTTP_USER_AGENT"],
            "Referer": referer,
        }

    @classmethod
    async def _fetch_from_eastmoney_api(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """直接从东方财富API获取行情（绕过akshare爬虫）"""
        # 东方财富ETF行情API
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1,
            "pz": 500,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6267cc896",
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024",
            "fields": "f1,f2,f3,f4,f5,f6,f7,f12,f13,f14,f15,f16,f17,f18"
        }
        headers = cls._build_default_headers("https://quote.eastmoney.com/")
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
            
            if data.get("data") and data["data"].get("diff"):
                result = {}
                for item in data["data"]["diff"]:
                    code = item.get("f12", "")
                    name = item.get("f14", "")
                    price = item.get("f2", 0)
                    change_pct = item.get("f3", 0)
                    
                    if code in codes:
                        result[code] = MarketQuote(
                            code=code,
                            name=name,
                            price=float(price) if price else 0.0,
                            change_pct=float(change_pct) if change_pct else 0.0,
                            open_price=None,
                            high_price=None,
                            low_price=None,
                            volume=None,
                        )
                return result
        except Exception as e:
            print(f"[MarketService] 东方财富API请求失败: {e}")
        
        return {}
    
    @classmethod
    async def _fetch_from_sina_api(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """从新浪财经API获取行情（备用）"""
        # 新浪财经实时行情API
        # 格式: https://hq.sinajs.cn/list=sh513300,sz159915
        code_list = []
        for code in codes:
            # 判断市场：51开头是上海，15/16开头是深圳
            if code.startswith("51") or code.startswith("58"):
                code_list.append(f"sh{code}")
            elif code.startswith("15") or code.startswith("16"):
                code_list.append(f"sz{code}")
            else:
                code_list.append(f"sh{code}")
        
        url = f"https://hq.sinajs.cn/list={','.join(code_list)}"
        headers = cls._build_default_headers("https://finance.sina.com.cn/")
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
            # 返回格式: var hq_str_sh513300="名称,今开,昨收,当前价格,最高,最低,买一,卖一,成交量,成交额,..."
            text = response.text
            result = {}
            
            for line in text.strip().split('\n'):
                if '=' in line and '"' in line:
                    # 解析: var hq_str_sh513300="..."
                    match = line.split('="')
                    if len(match) == 2:
                        full_code = match[0].replace('var hq_str_', '')
                        data_str = match[1].rstrip('";')
                        
                        # 提取纯代码
                        code = full_code[2:] if full_code.startswith(('sh', 'sz')) else full_code
                        
                        if data_str and code in codes:
                            parts = data_str.split(',')
                            if len(parts) >= 6:
                                name = parts[0]
                                open_price = float(parts[1]) if parts[1] else None
                                prev_close = float(parts[2]) if parts[2] else 0
                                price = float(parts[3]) if parts[3] else 0
                                high = float(parts[4]) if parts[4] else None
                                low = float(parts[5]) if parts[5] else None
                                
                                # 计算涨跌幅
                                change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                                
                                result[code] = MarketQuote(
                                    code=code,
                                    name=name,
                                    price=price,
                                    change_pct=round(change_pct, 2),
                                    open_price=open_price,
                                    high_price=high,
                                    low_price=low,
                                    volume=int(parts[8]) if len(parts) > 8 and parts[8] else None,
                                )
            return result
        except Exception as e:
            print(f"[MarketService] 新浪API请求失败: {e}")
        
        return {}
    
    @classmethod
    def _fetch_history_kline_akshare(cls, code: str, days: int = 60) -> List[KLineItem]:
        """使用akshare获取历史K线数据"""
        try:
            print(f"[MarketService] >>> akshare获取历史K线: {code}")
            df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
            
            if df is not None and not df.empty:
                # 取最近N天
                df = df.tail(days)
                result = []
                for _, row in df.iterrows():
                    # 计算涨跌幅
                    change_pct = 0.0
                    if row.get("收盘") and len(result) > 0:
                        prev_close = result[-1].close_price
                        if prev_close > 0:
                            change_pct = (row["收盘"] - prev_close) / prev_close * 100
                    
                    result.append(KLineItem(
                        trade_date=row["日期"] if isinstance(row["日期"], date) else date.fromisoformat(str(row["日期"])),
                        open_price=float(row["开盘"]),
                        close_price=float(row["收盘"]),
                        high_price=float(row["最高"]),
                        low_price=float(row["最低"]),
                        volume=int(row["成交量"]),
                        change_pct=round(change_pct, 2),
                    ))
                print(f"[MarketService] ✓ akshare获取到 {len(result)} 条K线")
                return result
        except Exception as e:
            print(f"[MarketService] akshare获取历史K线失败: {e}")
        
        return []
    
    @classmethod
    async def _fetch_history_kline_eastmoney(cls, code: str, days: int = 60) -> List[KLineItem]:
        """从东方财富API获取历史K线数据（备用）"""
        # 东方财富历史K线API
        # 判断市场
        market = "1" if code.startswith(("51", "58")) else "0"  # 1=上海, 0=深圳
        secid = f"{market}.{code}"
        
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",  # 日K
            "fqt": "1",    # 前复权
            "end": "20500000",
            "lmt": str(days),
        }
        headers = cls._build_default_headers("https://quote.eastmoney.com/")
        
        try:
            print(f"[MarketService] >>> 东方财富API获取历史K线: {code}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
            
            if data.get("data") and data["data"].get("klines"):
                result = []
                klines = data["data"]["klines"]
                
                for i, line in enumerate(klines):
                    parts = line.split(',')
                    if len(parts) >= 6:
                        # 计算涨跌幅
                        change_pct = 0.0
                        if i > 0:
                            prev_close = result[-1].close_price
                            close = float(parts[2])
                            if prev_close > 0:
                                change_pct = (close - prev_close) / prev_close * 100
                        
                        result.append(KLineItem(
                            trade_date=date.fromisoformat(parts[0]),
                            open_price=float(parts[1]),
                            close_price=float(parts[2]),
                            high_price=float(parts[3]),
                            low_price=float(parts[4]),
                            volume=int(parts[5]),
                            change_pct=round(change_pct, 2),
                        ))
                
                print(f"[MarketService] ✓ 东方财富API获取到 {len(result)} 条K线")
                return result
        except Exception as e:
            print(f"[MarketService] 东方财富API获取历史K线失败: {e}")
        
        return []
    
    @classmethod
    async def _fetch_history_kline_sina(cls, code: str, days: int = 60) -> List[KLineItem]:
        """从新浪财经API获取历史K线数据"""
        if code.startswith(("51", "58")):
            symbol = f"sh{code}"
        elif code.startswith(("15", "16")):
            symbol = f"sz{code}"
        else:
            symbol = f"sh{code}"
        
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            "symbol": symbol,
            "scale": "240",
            "ma": "no",
            "datalen": str(days),
        }
        headers = cls._build_default_headers("https://finance.sina.com.cn/")
        
        try:
            print(f"[MarketService] >>> 新浪API获取历史K线: {code} ({symbol})")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
            
            if data and isinstance(data, list):
                result = []
                for i, item in enumerate(data):
                    change_pct = 0.0
                    if i > 0:
                        prev_close = result[-1].close_price
                        close = float(item["close"])
                        if prev_close > 0:
                            change_pct = (close - prev_close) / prev_close * 100
                    
                    result.append(KLineItem(
                        trade_date=date.fromisoformat(item["day"].split(" ")[0]),
                        open_price=float(item["open"]),
                        close_price=float(item["close"]),
                        high_price=float(item["high"]),
                        low_price=float(item["low"]),
                        volume=int(item["volume"]),
                        change_pct=round(change_pct, 2),
                    ))
                
                print(f"[MarketService] ✓ 新浪API获取到 {len(result)} 条K线")
                return result
        except Exception as e:
            print(f"[MarketService] 新浪API获取历史K线失败: {e}")
        
        return []
    
    @classmethod
    async def get_history_kline(cls, code: str, days: int = 60) -> List[KLineItem]:
        """获取历史K线数据（akshare → 东方财富API → 新浪API）"""
        print(f"[MarketService] 开始获取历史K线: {code}, 天数: {days}")

        cached = await cls.get_kline_from_cache(code, days)
        if cached:
            return cached
        
        # 优先使用akshare
        try:
            result = await asyncio.to_thread(cls._fetch_history_kline_akshare, code, days)
            if result:
                await cls.cache_kline(code, days, result)
                return result
        except Exception as e:
            print(f"[MarketService] akshare获取K线异常: {e}")
        
        # 备用：东方财富API
        try:
            result = await cls._fetch_history_kline_eastmoney(code, days)
            if result:
                await cls.cache_kline(code, days, result)
                return result
        except Exception as e:
            print(f"[MarketService] 东方财富API获取K线异常: {e}")
        
        # 备用：新浪API
        try:
            result = await cls._fetch_history_kline_sina(code, days)
            if result:
                await cls.cache_kline(code, days, result)
                return result
        except Exception as e:
            print(f"[MarketService] 新浪API获取K线异常: {e}")
        
        print(f"[MarketService] ✗ 历史K线获取失败: {code}")
        return []
    
    @classmethod
    def calculate_technical_indicators(cls, klines: List[KLineItem]) -> TechnicalIndicators:
        """计算技术指标"""
        if len(klines) < 5:
            return TechnicalIndicators()
        
        # 收盘价列表
        closes = [k.close_price for k in klines]
        
        # MA均线
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
        ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else None
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
        
        # RSI(14)
        rsi14 = None
        if len(closes) >= 15:
            gains = []
            losses = []
            for i in range(1, 15):
                change = closes[-i] - closes[-i-1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))
            
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi14 = 100 - (100 / (1 + rs))
            else:
                rsi14 = 100.0
        
        # MACD (12, 26, 9)
        macd_dif = None
        macd_dea = None
        macd_histogram = None
        
        if len(closes) >= 26:
            # 计算EMA
            def ema(prices: List[float], period: int) -> List[float]:
                multiplier = 2 / (period + 1)
                ema_values = [sum(prices[:period]) / period]
                for price in prices[period:]:
                    ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
                return ema_values
            
            ema12 = ema(closes, 12)
            ema26 = ema(closes, 26)
            
            # DIF
            dif_values = []
            for i in range(len(ema26)):
                dif_values.append(ema12[i + (len(ema12) - len(ema26))] - ema26[i])
            
            macd_dif = dif_values[-1]
            
            # DEA (DIF的9日EMA)
            if len(dif_values) >= 9:
                dea_values = ema(dif_values, 9)
                macd_dea = dea_values[-1]
                macd_histogram = 2 * (macd_dif - macd_dea)
        
        return TechnicalIndicators(
            ma5=round(ma5, 3) if ma5 else None,
            ma10=round(ma10, 3) if ma10 else None,
            ma20=round(ma20, 3) if ma20 else None,
            rsi14=round(rsi14, 2) if rsi14 else None,
            macd_dif=round(macd_dif, 4) if macd_dif else None,
            macd_dea=round(macd_dea, 4) if macd_dea else None,
            macd_histogram=round(macd_histogram, 4) if macd_histogram else None,
        )
    
    @classmethod
    async def _fetch_quotes_from_akshare(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """从数据源获取指定ETF行情"""
        if not codes:
            return {}
        
        print(f"[MarketService] 开始获取 {len(codes)} 只ETF行情: {codes}")
        
        # 优先使用东方财富API
        result = await cls._fetch_from_eastmoney_api(codes)
        if result:
            print(f"[MarketService] ✓ 东方财富API成功: {len(result)} 只ETF")
            for code, quote in result.items():
                result[code] = await cls.cache_quote(code, quote)
            return result
        
        # 备用：新浪财经API
        print("[MarketService] >>> 尝试备用数据源: 新浪财经API")
        result = await cls._fetch_from_sina_api(codes)
        if result:
            print(f"[MarketService] ✓ 新浪API成功: {len(result)} 只ETF")
            for code, quote in result.items():
                result[code] = await cls.cache_quote(code, quote)
            return result
        
        # 获取失败，返回空数据
        print("[MarketService] ✗ 所有数据源均失败，返回空数据")
        return cls._get_empty_quotes(codes)
    
    @classmethod
    async def _cache_all_quotes(cls, df: pd.DataFrame, session: Optional[AsyncSession] = None):
        """缓存全量ETF行情数据到Redis，并同步ETF基本信息到数据库"""
        if not settings.redis_enabled:
            return
        
        # 兼容不同数据源的列名
        code_col = "代码" if "代码" in df.columns else "code" if "code" in df.columns else df.columns[0]
        name_col = "名称" if "名称" in df.columns else "name" if "name" in df.columns else df.columns[1]
        price_col = "最新价" if "最新价" in df.columns else "收盘" if "收盘" in df.columns else df.columns[2]
        change_col = "涨跌幅" if "涨跌幅" in df.columns else df.columns[3] if len(df.columns) > 3 else None
        open_col = "今开" if "今开" in df.columns else None
        high_col = "最高" if "最高" in df.columns else None
        low_col = "最低" if "最低" in df.columns else None
        volume_col = "成交量" if "成交量" in df.columns else None
        amount_col = "成交额" if "成交额" in df.columns else None
        
        cached_count = 0
        etf_infos_to_save = []
        
        for _, row in df.iterrows():
            code = str(row[code_col])
            name = str(row.get(name_col, ""))
            try:
                quote = MarketQuote(
                    code=code,
                    name=name,
                    price=float(row.get(price_col, 0) or 0),
                    change_pct=float(row.get(change_col, 0) or 0) if change_col else 0.0,
                    open_price=float(row.get(open_col, 0)) if open_col and row.get(open_col) else None,
                    high_price=float(row.get(high_col, 0)) if high_col and row.get(high_col) else None,
                    low_price=float(row.get(low_col, 0)) if low_col and row.get(low_col) else None,
                    volume=int(row.get(volume_col, 0)) if volume_col and row.get(volume_col) else None,
                    amount=float(row.get(amount_col, 0)) if amount_col and row.get(amount_col) else None,
                )
                await cls.cache_quote(code, quote)
                cached_count += 1
                
                # 收集 ETF 基本信息
                if name:
                    etf_infos_to_save.append((code, name))
            except Exception:
                continue
        
        # 同步 ETF 基本信息到数据库
        if session and etf_infos_to_save:
            try:
                from sqlalchemy.dialects.postgresql import insert
                for code, name in etf_infos_to_save:
                    # 使用 UPSERT 语法，不存在则插入，存在则忽略
                    stmt = insert(EtfInfo).values(code=code, name=name).on_conflict_do_nothing(index_elements=['code'])
                    await session.execute(stmt)
                await session.commit()
                print(f"[MarketService] ✓ 已同步 {len(etf_infos_to_save)} 只ETF基本信息到数据库")
            except Exception as e:
                print(f"[MarketService] 同步ETF基本信息失败: {e}")
        
        print(f"[MarketService] ✓ 已缓存 {cached_count} 只ETF行情到Redis (有效期7天, 缓存时间: {now_in_shanghai().strftime('%Y-%m-%d %H:%M:%S %Z')})")
    
    @classmethod
    def _parse_quotes_from_df(cls, codes: List[str], df: pd.DataFrame) -> Dict[str, MarketQuote]:
        """从DataFrame解析行情数据"""
        result = {}
        
        # 兼容不同数据源的列名
        code_col = "代码" if "代码" in df.columns else "code" if "code" in df.columns else df.columns[0]
        name_col = "名称" if "名称" in df.columns else "name" if "name" in df.columns else df.columns[1]
        price_col = "最新价" if "最新价" in df.columns else "收盘" if "收盘" in df.columns else df.columns[2]
        change_col = "涨跌幅" if "涨跌幅" in df.columns else df.columns[3] if len(df.columns) > 3 else None
        open_col = "今开" if "今开" in df.columns else None
        high_col = "最高" if "最高" in df.columns else None
        low_col = "最低" if "最低" in df.columns else None
        volume_col = "成交量" if "成交量" in df.columns else None
        amount_col = "成交额" if "成交额" in df.columns else None
        
        for code in codes:
            row = df[df[code_col] == code]
            if not row.empty:
                row = row.iloc[0]
                result[code] = MarketQuote(
                    code=code,
                    name=str(row.get(name_col, "")),
                    price=float(row.get(price_col, 0) or 0),
                    change_pct=float(row.get(change_col, 0) or 0) if change_col else 0.0,
                    open_price=float(row.get(open_col, 0)) if open_col and row.get(open_col) else None,
                    high_price=float(row.get(high_col, 0)) if high_col and row.get(high_col) else None,
                    low_price=float(row.get(low_col, 0)) if low_col and row.get(low_col) else None,
                    volume=int(row.get(volume_col, 0)) if volume_col and row.get(volume_col) else None,
                    amount=float(row.get(amount_col, 0)) if amount_col and row.get(amount_col) else None,
                )
        return result
    
    @classmethod
    def _get_empty_quotes(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """返回空行情数据（无数据时使用）"""
        result = {}
        for code in codes:
            result[code] = MarketQuote(
                code=code,
                name="",
                price=0.0,
                change_pct=0.0,
                open_price=None,
                high_price=None,
                low_price=None,
                volume=None,
                amount=None,
            )
        print(f"[MarketService] 返回空数据 {len(result)} 只ETF")
        return result
    
    @classmethod
    async def search_etf(cls, query: str, limit: int = 20) -> List[EtfSearchResult]:
        """搜索ETF"""
        try:
            # akshare 仍是同步库，放到线程池里避免阻塞事件循环
            df = await asyncio.to_thread(ak.fund_etf_spot_em)
            if df.empty:
                return []
            
            # 按代码或名称搜索
            mask = df["代码"].str.contains(query, case=False, na=False) | \
                   df["名称"].str.contains(query, case=False, na=False)
            result_df = df[mask].head(limit)
            
            results = []
            for _, row in result_df.iterrows():
                results.append(EtfSearchResult(
                    code=str(row["代码"]),
                    name=str(row["名称"]),
                    category=cls._guess_category(str(row["名称"])),
                    exchange="SH" if str(row["代码"]).startswith("5") else "SZ",
                ))
            return results
        except Exception as e:
            print(f"[MarketService] ETF搜索失败: {e}")
            return []

    @staticmethod
    def _json_safe_value(value: Any) -> Any:
        try:
            if hasattr(value, "item"):
                value = value.item()
        except Exception:
            pass

        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, dict):
            return {str(key): MarketService._json_safe_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [MarketService._json_safe_value(item) for item in value]
        return value

    @staticmethod
    def _clean_record(record: Dict[str, Any]) -> Dict[str, Any]:
        clean: Dict[str, Any] = {}
        for key, value in record.items():
            clean[str(key)] = MarketService._json_safe_value(value)
        return clean

    @staticmethod
    def _visible_profile_errors(errors: List[str]) -> List[str]:
        return [
            item for item in errors
            if "fund_individual_basic_info_xq" not in item
            and "fund_portfolio_bond_hold_em" not in item
        ]

    @classmethod
    def _df_records(cls, df, limit: int | None = None) -> List[Dict[str, Any]]:
        if df is None or getattr(df, "empty", True):
            return []
        if limit is not None:
            df = df.head(limit)
        return [cls._clean_record(dict(row)) for _, row in df.iterrows()]

    @classmethod
    async def get_etf_profile(
        cls,
        code: str,
        year: int | None = None,
        session: Optional[AsyncSession] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """获取 ETF/基金资料，优先读取 Redis 和数据库缓存。"""
        target_year = str(year or datetime.now().year)

        if not force_refresh:
            cached = await cls.get_etf_profile_from_cache(code, target_year)
            if cached:
                return cached

            if session is not None:
                stored = await cls._get_etf_profile_from_db(session, code, target_year)
                if stored:
                    await cls.cache_etf_profile(code, target_year, stored)
                    return stored

        result = await cls._fetch_etf_profile_from_source(code, target_year)
        if session is not None:
            await cls.save_etf_profile(session, result)
        await cls.cache_etf_profile(code, target_year, result)
        return result

    @classmethod
    async def _get_etf_profile_from_db(
        cls,
        session: AsyncSession,
        code: str,
        year: str,
    ) -> Optional[Dict[str, Any]]:
        record = await session.get(EtfProfile, {"code": code, "year": year})
        if not record:
            return None
        return {
            "code": record.code,
            "year": record.year,
            "basic": record.basic or {},
            "asset_allocation": record.asset_allocation or [],
            "stock_holdings": record.stock_holdings or [],
            "bond_holdings": record.bond_holdings or [],
            "events": record.events or [],
            "errors": record.errors or [],
            "source": record.source,
            "refreshed_at": record.refreshed_at.isoformat() if record.refreshed_at else None,
        }

    @classmethod
    async def save_etf_profile(cls, session: AsyncSession, data: Dict[str, Any]) -> None:
        code = str(data.get("code") or "")
        year = str(data.get("year") or datetime.now().year)
        if not code:
            return

        record = await session.get(EtfProfile, {"code": code, "year": year})
        if record is None:
            record = EtfProfile(code=code, year=year, refresh_count=0)
            session.add(record)

        record.basic = cls._json_safe_value(data.get("basic") or {})
        record.asset_allocation = cls._json_safe_value(data.get("asset_allocation") or [])
        record.stock_holdings = cls._json_safe_value(data.get("stock_holdings") or [])
        record.bond_holdings = cls._json_safe_value(data.get("bond_holdings") or [])
        record.events = cls._json_safe_value(data.get("events") or [])
        record.errors = cls._visible_profile_errors(cls._json_safe_value(data.get("errors") or []))
        record.source = data.get("source") or "akshare"
        record.refresh_count = (record.refresh_count or 0) + 1
        await session.flush()

    @classmethod
    async def _fetch_etf_profile_from_source(cls, code: str, target_year: str) -> Dict[str, Any]:
        """从 AkShare 拉取 ETF/基金资料、资产配置、持仓股票和公告提醒。"""
        result: Dict[str, Any] = {
            "code": code,
            "year": target_year,
            "basic": {},
            "asset_allocation": [],
            "stock_holdings": [],
            "bond_holdings": [],
            "events": [],
            "errors": [],
            "source": "akshare",
            "refreshed_at": now_in_shanghai().isoformat(),
        }

        async def run_ak(name: str, *args, optional: bool = False, **kwargs):
            fn = getattr(ak, name, None)
            if fn is None:
                if not optional:
                    result["errors"].append(f"{name} 不可用")
                return None
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as exc:
                message = f"{name}: {type(exc).__name__}: {exc}"
                if optional:
                    result.setdefault("warnings", []).append(message)
                else:
                    result["errors"].append(message)
                return None

        basic_df = await run_ak("fund_individual_basic_info_xq", symbol=code, optional=True)
        basic_records = cls._df_records(basic_df)
        if basic_records:
            basic: Dict[str, Any] = {}
            for index, item in enumerate(basic_records):
                key = item.get("item") or item.get("项目") or item.get("名称") or f"字段{index + 1}"
                value = item.get("value") or item.get("值") or item.get("内容")
                basic[str(key)] = value
            result["basic"] = basic

        if not result["basic"]:
            etf_df = await run_ak("fund_etf_spot_em")
            if etf_df is not None and not getattr(etf_df, "empty", True) and "代码" in etf_df.columns:
                matched = etf_df[etf_df["代码"].astype(str) == code]
                if not matched.empty:
                    result["basic"] = cls._clean_record(dict(matched.iloc[0]))

        allocation_df = await run_ak("fund_individual_detail_hold_xq", symbol=code, date=f"{target_year}1231")
        result["asset_allocation"] = cls._df_records(allocation_df, limit=20)

        stock_df = await run_ak("fund_portfolio_hold_em", symbol=code, date=target_year)
        result["stock_holdings"] = cls._df_records(stock_df, limit=50)

        bond_df = await run_ak("fund_portfolio_bond_hold_em", symbol=code, date=target_year, optional=True)
        result["bond_holdings"] = cls._df_records(bond_df, limit=50)

        events_df = await run_ak("fund_open_fund_info_em", symbol=code, indicator="基金公告")
        result["events"] = cls._df_records(events_df, limit=10)
        result["errors"] = cls._visible_profile_errors(result["errors"])
        return result
    
    @staticmethod
    def _guess_category(name: str) -> str:
        """根据名称猜测ETF类别"""
        if any(k in name for k in ["货币", "现金", "短融", "同业存单"]):
            return "现金管理"
        elif any(k in name for k in ["国债", "地方债", "政金债", "信用债", "可转债", "债券"]):
            return "债券"
        elif any(k in name for k in ["沪深300", "中证500", "中证1000", "上证50", "创业板指", "深证100", "A50", "全指", "科创宽基"]):
            return "宽基指数"
        elif any(k in name for k in ["红利", "股息", "高股息", "央企红利"]):
            return "红利策略"
        elif any(k in name for k in ["恒生", "纳指", "纳斯达克", "标普", "日经", "德国", "法国", "海外", "全球", "美国", "港股"]):
            return "海外市场"
        elif any(k in name for k in ["医药", "医疗", "生物", "创新药", "疫苗", "中药"]):
            return "医药医疗"
        elif any(k in name for k in ["芯片", "半导体", "集成电路"]):
            return "半导体芯片"
        elif any(k in name for k in ["人工智能", "AI", "机器人", "算力", "通信", "5G", "软件", "云计算", "信息技术", "计算机", "科技"]):
            return "TMT/人工智能"
        elif any(k in name for k in ["消费", "食品", "饮料", "白酒", "家电", "养殖", "农业消费"]):
            return "消费"
        elif any(k in name for k in ["新能源", "光伏", "锂电", "电池", "储能", "风电", "电车", "新能源汽车"]):
            return "新能源"
        elif any(k in name for k in ["银行", "证券", "券商", "保险", "金融", "地产", "房地产"]):
            return "金融地产"
        elif any(k in name for k in ["军工", "国防", "航空航天"]):
            return "军工国防"
        elif any(k in name for k in ["黄金", "白银", "贵金属"]):
            return "贵金属"
        elif any(k in name for k in ["原油", "煤炭", "油气", "能源", "化工"]):
            return "能源化工"
        elif any(k in name for k in ["豆粕", "农产品", "农业", "饲料"]):
            return "农产品"
        elif any(k in name for k in ["REIT", "reits", "不动产"]):
            return "REITs"
        else:
            return "未分类"
    
    @classmethod
    def calc_technical_indicators(cls, kline_data: List[KLineItem]) -> Dict[str, Any]:
        """计算技术指标"""
        if len(kline_data) < 20:
            return {}
        
        closes = [float(k.close_price) for k in kline_data]
        
        # 均线
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20
        
        # RSI (14)
        if len(closes) >= 15:
            gains = []
            losses = []
            for i in range(1, 15):
                change = closes[-i] - closes[-i-1]
                if change > 0:
                    gains.append(change)
                else:
                    losses.append(abs(change))
            avg_gain = sum(gains) / 14 if gains else 0
            avg_loss = sum(losses) / 14 if losses else 0.001
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        else:
            rsi = 50
        
        # MACD (简化版)
        ema12 = closes[-1]
        ema26 = closes[-1]
        for i, c in enumerate(reversed(closes)):
            ema12 = c * (2/14) + ema12 * (12/14)
            ema26 = c * (2/27) + ema26 * (25/27)
            if i > 30:
                break
        dif = ema12 - ema26
        dea = dif * (2/10)  # 简化
        macd_bar = (dif - dea) * 2
        
        return {
            "ma5": round(ma5, 4),
            "ma10": round(ma10, 4),
            "ma20": round(ma20, 4),
            "rsi": round(rsi, 2),
            "dif": round(dif, 4),
            "dea": round(dea, 4),
            "macd_bar": round(macd_bar, 4),
        }
    
    @staticmethod
    async def save_market_daily(session: AsyncSession, code: str, data: List[KLineItem]):
        """保存历史行情到数据库"""
        for item in data:
            existing = await session.execute(
                select(MarketDaily).where(
                    MarketDaily.etf_code == code,
                    MarketDaily.trade_date == item.trade_date
                )
            )
            if existing.scalar_one_or_none():
                continue
            
            record = MarketDaily(
                etf_code=code,
                trade_date=item.trade_date,
                open_price=item.open_price,
                close_price=item.close_price,
                high_price=item.high_price,
                low_price=item.low_price,
                volume=item.volume,
                change_pct=item.change_pct,
            )
            session.add(record)
