import asyncio
import akshare as ak
import pandas as pd
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession


# 设置环境变量模拟浏览器

from models import EtfProfile
from config import settings
from services.redis_service import RedisService
from utils.timezone import now_in_shanghai


class FundProfileMixin:
    """FundProfileMixin implementation used by FundProfileMixin."""

    @classmethod
    def _profile_cache_key(cls, code: str, year: str) -> str:
        return f"{cls.REDIS_KEY_PROFILE_PREFIX}{code}:{year}"


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
            return {str(key): FundProfileMixin._json_safe_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [FundProfileMixin._json_safe_value(item) for item in value]
        return value


    @staticmethod
    def _clean_record(record: Dict[str, Any]) -> Dict[str, Any]:
        clean: Dict[str, Any] = {}
        for key, value in record.items():
            clean[str(key)] = FundProfileMixin._json_safe_value(value)
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
    async def _fetch_ths_industry_profile_from_source(cls, code: str, target_year: str) -> Optional[Dict[str, Any]]:
        """获取同花顺 88xxxx 行业指数资料，兼容 ETF profile 响应结构。"""
        name = cls._resolve_ths_industry_name(code)
        if not name:
            return None

        result: Dict[str, Any] = {
            "code": code,
            "year": target_year,
            "basic": {
                "代码": code,
                "名称": name,
                "类型": "同花顺行业指数",
                "资料口径": "行业指数行情与行业一览，不包含基金资产配置或基金公告",
            },
            "asset_allocation": [],
            "stock_holdings": [],
            "bond_holdings": [],
            "events": [],
            "errors": [],
            "source": "akshare:ths_industry",
            "refreshed_at": now_in_shanghai().isoformat(),
        }

        try:
            info_df = await asyncio.to_thread(ak.stock_board_industry_info_ths, symbol=name)
            for item in cls._df_records(info_df):
                key = item.get("项目")
                if key:
                    result["basic"][str(key)] = item.get("值")
        except Exception as exc:
            result["errors"].append(f"stock_board_industry_info_ths: {type(exc).__name__}: {exc}")

        try:
            summary_df = await asyncio.to_thread(ak.stock_board_industry_summary_ths)
            if summary_df is not None and not getattr(summary_df, "empty", True) and "板块" in summary_df.columns:
                matched = summary_df[summary_df["板块"].astype(str) == name]
                result["asset_allocation"] = cls._df_records(matched, limit=1)
        except Exception as exc:
            result["errors"].append(f"stock_board_industry_summary_ths: {type(exc).__name__}: {exc}")

        try:
            klines = await asyncio.to_thread(cls._fetch_history_kline_ths_industry, code, 5)
            result["events"] = [
                {
                    "日期": item.trade_date.isoformat(),
                    "开盘": item.open_price,
                    "收盘": item.close_price,
                    "最高": item.high_price,
                    "最低": item.low_price,
                    "成交量": item.volume,
                    "涨跌幅": item.change_pct,
                }
                for item in klines
            ]
        except Exception as exc:
            result["errors"].append(f"stock_board_industry_index_ths: {type(exc).__name__}: {exc}")

        return result


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
        is_ths_industry_code = cls._resolve_ths_industry_name(code) is not None

        if not force_refresh and not is_ths_industry_code:
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
        ths_profile = await cls._fetch_ths_industry_profile_from_source(code, target_year)
        if ths_profile is not None:
            return ths_profile

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
