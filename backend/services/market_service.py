import akshare as ak
import pandas as pd
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import time
import os

# 设置环境变量模拟浏览器
os.environ.setdefault('HTTP_USER_AGENT', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

from models import EtfInfo, MarketDaily
from schemas.market import MarketQuote, KLineItem, EtfSearchResult
from config import settings
from services.redis_service import RedisService


class MarketService:
    """行情服务 - AKShare封装"""
    
    # Redis缓存key
    REDIS_KEY_QUOTE_PREFIX = "etf:quote:"
    REDIS_KEY_ALL_QUOTES = "etf:all_quotes"
    CACHE_EXPIRE_SECONDS = 604800  # 7天缓存 (7 * 24 * 60 * 60)
    
    @classmethod
    async def get_quote_from_cache(cls, code: str) -> Optional[MarketQuote]:
        """从Redis缓存获取单个ETF行情"""
        if not settings.redis_enabled:
            return None
        cached = await RedisService.get(f"{cls.REDIS_KEY_QUOTE_PREFIX}{code}")
        if cached and "data" in cached:
            return MarketQuote(**cached["data"])
        return None
    
    @classmethod
    async def cache_quote(cls, code: str, quote: MarketQuote):
        """缓存单个ETF行情到Redis（带时间戳）"""
        if settings.redis_enabled:
            cache_data = {
                "data": quote.model_dump(),
                "cached_at": datetime.now().isoformat(),
                "cache_date": date.today().isoformat(),
            }
            await RedisService.set(
                f"{cls.REDIS_KEY_QUOTE_PREFIX}{code}", 
                cache_data, 
                expire=cls.CACHE_EXPIRE_SECONDS
            )
    
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
                    await cls.cache_quote(code, quote)
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
    async def _fetch_quotes_from_akshare(cls, codes: List[str]) -> Dict[str, MarketQuote]:
        """从多个数据源获取指定ETF行情（按优先级尝试）"""
        if not codes:
            return {}
        
        print(f"[MarketService] 开始获取 {len(codes)} 只ETF行情: {codes}")
        
        all_quotes_df = None
        
        # 尝试东方财富接口
        try:
            print("[MarketService] >>> 尝试数据源: 东方财富 (fund_etf_spot_em)")
            all_quotes_df = ak.fund_etf_spot_em()
            print(f"[MarketService] <<< 东方财富成功: 获取到 {len(all_quotes_df)} 只ETF数据")
        except Exception as e:
            print(f"[MarketService] <<< 东方财富失败: {type(e).__name__}: {e}")
        
        # 尝试新浪接口
        if all_quotes_df is None:
            try:
                print("[MarketService] >>> 尝试数据源: 新浪财经 (fund_etf_hist_sina)")
                all_quotes_df = ak.fund_etf_hist_sina(symbol="etf")
                print(f"[MarketService] <<< 新浪财经成功: 获取到 {len(all_quotes_df)} 只ETF数据")
            except Exception as e:
                print(f"[MarketService] <<< 新浪财经失败: {type(e).__name__}: {e}")
        
        # 尝试腾讯接口
        if all_quotes_df is None:
            try:
                print("[MarketService] >>> 尝试数据源: 腾讯财经 (stock_zh_a_spot_em)")
                df = ak.stock_zh_a_spot_em()
                all_quotes_df = df[df["代码"].str.startswith(("51", "15", "58"))]
                print(f"[MarketService] <<< 腾讯财经成功: 获取到 {len(all_quotes_df)} 只ETF数据")
            except Exception as e:
                print(f"[MarketService] <<< 腾讯财经失败: {type(e).__name__}: {e}")
        
        # 成功获取数据，缓存全量数据到Redis
        if all_quotes_df is not None and not all_quotes_df.empty:
            result = cls._parse_quotes_from_df(codes, all_quotes_df)
            if result:
                print(f"[MarketService] ✓ 成功匹配 {len(result)}/{len(codes)} 只ETF行情")
                # 异步缓存全量数据到Redis
                await cls._cache_all_quotes(all_quotes_df)
                return result
        
        # 所有接口都失败，返回空数据
        print("[MarketService] ✗ 所有行情接口均失败，返回空数据")
        return cls._get_empty_quotes(codes)
    
    @classmethod
    async def _cache_all_quotes(cls, df: pd.DataFrame):
        """缓存全量ETF行情数据到Redis"""
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
        for _, row in df.iterrows():
            code = str(row[code_col])
            try:
                quote = MarketQuote(
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
                await cls.cache_quote(code, quote)
                cached_count += 1
            except Exception:
                continue
        
        print(f"[MarketService] ✓ 已缓存 {cached_count} 只ETF行情到Redis (有效期7天, 缓存时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    
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
    def get_history_kline(
        cls, 
        code: str, 
        days: int = 60,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[KLineItem]:
        """获取历史K线数据"""
        if end_date is None:
            end_date = date.today().strftime("%Y%m%d")
        if start_date is None:
            start_date = (date.today() - timedelta(days=days * 2)).strftime("%Y%m%d")
        
        try:
            df = ak.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"
            )
            if df.empty:
                return []
            
            # 取最近N天
            df = df.tail(days)
            
            result = []
            for _, row in df.iterrows():
                result.append(KLineItem(
                    trade_date=pd.to_datetime(row["日期"]).date(),
                    open_price=float(row["开盘"]),
                    close_price=float(row["收盘"]),
                    high_price=float(row["最高"]),
                    low_price=float(row["最低"]),
                    volume=int(row["成交量"]),
                    change_pct=float(row.get("涨跌幅", 0)),
                ))
            return result
        except Exception:
            return []
    
    @classmethod
    async def search_etf(cls, query: str, limit: int = 20) -> List[EtfSearchResult]:
        """搜索ETF"""
        try:
            # 直接从AKShare获取全市场ETF列表
            df = ak.fund_etf_spot_em()
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
    def _guess_category(name: str) -> str:
        """根据名称猜测ETF类别"""
        if any(k in name for k in ["沪深300", "中证500", "中证1000", "上证50", "创业板", "科创50", "科创100"]):
            return "宽基"
        elif any(k in name for k in ["医药", "医疗", "生物", "药"]):
            return "医药"
        elif any(k in name for k in ["芯片", "半导体", "电子", "计算机", "科技", "信息"]):
            return "科技"
        elif any(k in name for k in ["消费", "食品", "饮料", "白酒"]):
            return "消费"
        elif any(k in name for k in ["新能源", "光伏", "锂电", "电池", "储能"]):
            return "新能源"
        elif any(k in name for k in ["银行", "证券", "券商", "保险", "金融"]):
            return "金融"
        elif any(k in name for k in ["军工", "国防"]):
            return "军工"
        elif any(k in name for k in ["黄金", "白银", "豆粕", "原油", "商品"]):
            return "商品"
        elif any(k in name for k in ["债券", "国债", "地方债"]):
            return "债券"
        elif any(k in name for k in ["红利", "股息"]):
            return "红利"
        else:
            return "其他"
    
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
