from __future__ import annotations

import asyncio
import math
from datetime import date
from typing import Any

import akshare as ak
import pandas as pd

from services.redis_service import RedisService
from utils.timezone import now_in_shanghai


class IndustryFundamentalService:
    """Low-frequency industry fundamentals used by ETF prosperity scoring."""

    CACHE_PREFIX = "industry:fundamental:"
    CACHE_EXPIRE_SECONDS = 7 * 24 * 3600

    INDUSTRY_PROFILES: dict[str, dict[str, Any]] = {
        "semiconductor": {"label": "半导体", "em_industry": "半导体", "stocks": ["688981.SH", "603501.SH", "688012.SH"], "keywords": ("芯片", "半导体", "集成电路")},
        "ai": {"label": "人工智能", "em_industry": "软件开发", "stocks": ["002230.SZ", "688111.SH", "300033.SZ"], "keywords": ("人工智能", "AI", "算力", "软件", "云计算")},
        "robot": {"label": "机器人", "em_industry": "通用设备", "stocks": ["300124.SZ", "002472.SZ", "688017.SH"], "keywords": ("机器人", "自动化")},
        "communication": {"label": "通信", "em_industry": "通信设备", "stocks": ["000063.SZ", "600941.SH", "600050.SH"], "keywords": ("通信", "5G")},
        "new_energy": {"label": "新能源", "em_industry": "电池", "stocks": ["300750.SZ", "002594.SZ", "300014.SZ"], "keywords": ("新能源", "锂电", "电池", "储能")},
        "solar": {"label": "光伏", "em_industry": "光伏设备", "stocks": ["601012.SH", "300274.SZ", "688223.SH"], "keywords": ("光伏", "风电")},
        "medicine": {"label": "医药", "em_industry": "化学制药", "stocks": ["600276.SH", "300760.SZ", "000661.SZ"], "keywords": ("创新药", "生物", "医药", "医疗")},
        "consumer": {"label": "消费", "em_industry": "食品饮料", "stocks": ["600519.SH", "000858.SZ", "603288.SH"], "keywords": ("消费", "食品", "饮料", "白酒", "家电")},
        "bank": {"label": "银行", "em_industry": "银行", "stocks": ["600036.SH", "601398.SH", "601166.SH"], "keywords": ("银行",)},
        "broker": {"label": "证券", "em_industry": "证券", "stocks": ["600030.SH", "300059.SZ", "601688.SH"], "keywords": ("证券", "券商")},
        "insurance": {"label": "保险", "em_industry": "保险", "stocks": ["601318.SH", "601601.SH", "601628.SH"], "keywords": ("保险",)},
        "property": {"label": "地产", "em_industry": "房地产开发", "stocks": ["000002.SZ", "600048.SH", "001979.SZ"], "keywords": ("地产", "房地产")},
        "defense": {"label": "军工", "em_industry": "航天航空", "stocks": ["600893.SH", "600760.SH", "000768.SZ"], "keywords": ("军工", "国防", "航天", "航空")},
        "agriculture": {"label": "农业", "em_industry": "农牧饲渔", "stocks": ["000876.SZ", "002714.SZ", "600598.SH"], "keywords": ("农业", "养殖", "农牧")},
        "coal": {"label": "煤炭", "em_industry": "煤炭行业", "stocks": ["601088.SH", "601225.SH", "600188.SH"], "keywords": ("煤炭",)},
        "nonferrous": {"label": "有色", "em_industry": "有色金属", "stocks": ["601899.SH", "603799.SH", "601600.SH"], "keywords": ("有色", "铜", "铝")},
        "chemical": {"label": "化工", "em_industry": "化学制品", "stocks": ["600309.SH", "002493.SZ", "600989.SH"], "keywords": ("化工",)},
        "energy": {"label": "能源", "em_industry": "石油行业", "stocks": ["601857.SH", "600028.SH", "600938.SH"], "keywords": ("能源", "原油", "油气")},
    }

    @classmethod
    def resolve_industry_key(cls, code: str, name: str | None = None) -> str | None:
        text = f"{code or ''} {name or ''}".lower()
        for key, profile in cls.INDUSTRY_PROFILES.items():
            if any(keyword.lower() in text for keyword in profile["keywords"]):
                return key
        return None

    @classmethod
    async def get_many(cls, keys: list[str], allow_fetch: bool = True) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for key in dict.fromkeys(k for k in keys if k):
            data = await cls.get(key, allow_fetch=allow_fetch)
            if data:
                result[key] = data
        return result

    @classmethod
    async def get(cls, key: str, allow_fetch: bool = True) -> dict[str, Any] | None:
        cached = await RedisService.get(cls._cache_key(key))
        if cached and isinstance(cached.get("data"), dict):
            return cached["data"]
        if not allow_fetch:
            return None
        data = await asyncio.to_thread(cls._fetch_sync, key)
        if data:
            await RedisService.set(
                cls._cache_key(key),
                {"data": data, "cached_at": now_in_shanghai().isoformat()},
                expire=cls.CACHE_EXPIRE_SECONDS,
            )
        return data

    @classmethod
    async def refresh_all(cls, keys: list[str] | None = None) -> dict[str, dict[str, Any]]:
        target_keys = list(dict.fromkeys(keys or list(cls.INDUSTRY_PROFILES.keys())))
        result: dict[str, dict[str, Any]] = {}
        for key in target_keys:
            data = await asyncio.to_thread(cls._fetch_sync, key)
            if not data:
                continue
            await RedisService.set(
                cls._cache_key(key),
                {"data": data, "cached_at": now_in_shanghai().isoformat()},
                expire=cls.CACHE_EXPIRE_SECONDS,
            )
            result[key] = data
        return result

    @classmethod
    def _cache_key(cls, key: str) -> str:
        return f"{cls.CACHE_PREFIX}{key}"

    @classmethod
    def _fetch_sync(cls, key: str) -> dict[str, Any] | None:
        profile = cls.INDUSTRY_PROFILES.get(key)
        if not profile:
            return None
        errors: list[str] = []
        samples: list[dict[str, Any]] = []
        for symbol in profile["stocks"][:3]:
            try:
                sample = cls._fetch_stock_financials(symbol)
                if sample:
                    samples.append(sample)
            except Exception as exc:
                errors.append(f"{symbol}: {type(exc).__name__}: {exc}")

        forecast = None
        try:
            forecast = cls._fetch_forecast(profile["em_industry"])
        except Exception as exc:
            errors.append(f"forecast:{profile['em_industry']}: {type(exc).__name__}: {exc}")

        metrics = cls._aggregate(profile, samples, forecast, errors)
        return metrics

    @classmethod
    def _fetch_stock_financials(cls, symbol: str) -> dict[str, Any] | None:
        df = ak.stock_financial_analysis_indicator_em(symbol=symbol, indicator="按报告期")
        if df is None or df.empty:
            return None
        latest = df.iloc[0]
        previous = df.iloc[1] if len(df) > 1 else None
        roe = cls._pick_number(latest, ("ROE", "净资产收益率"))
        net_profit_growth = cls._pick_number(latest, ("NETPROFIT_YOY", "净利润同比", "归属净利润同比"))
        revenue_growth = cls._pick_number(latest, ("TOTAL_OPERATE_INCOME_YOY", "营业收入同比", "营收同比"))
        previous_profit_growth = cls._pick_number(previous, ("NETPROFIT_YOY", "净利润同比", "归属净利润同比")) if previous is not None else None
        return {
            "symbol": symbol,
            "report_date": str(latest.get("REPORT_DATE") or latest.get("报告日期") or ""),
            "roe": roe,
            "net_profit_growth": net_profit_growth,
            "revenue_growth": revenue_growth,
            "profit_growth_delta": net_profit_growth - previous_profit_growth if net_profit_growth is not None and previous_profit_growth is not None else None,
        }

    @classmethod
    def _fetch_forecast(cls, industry: str) -> dict[str, Any] | None:
        df = ak.stock_profit_forecast_em(symbol=industry)
        if df is None or df.empty:
            return None
        report_count = cls._mean_column(df, "研报数")
        buy = cls._sum_column(df, "机构投资评级(近六个月)-买入")
        add = cls._sum_column(df, "机构投资评级(近六个月)-增持")
        neutral = cls._sum_column(df, "机构投资评级(近六个月)-中性")
        sell = cls._sum_column(df, "机构投资评级(近六个月)-减持") + cls._sum_column(df, "机构投资评级(近六个月)-卖出")
        eps_cols = [col for col in df.columns if "预测每股收益" in str(col)]
        eps_growth = None
        if len(eps_cols) >= 2:
            current_eps = cls._mean_column(df, eps_cols[0])
            next_eps = cls._mean_column(df, eps_cols[1])
            if current_eps is not None and next_eps is not None and current_eps > 0:
                eps_growth = (next_eps - current_eps) / current_eps * 100
        total_rating = buy + add + neutral + sell
        positive_ratio = (buy + add) / total_rating * 100 if total_rating > 0 else None
        return {
            "industry": industry,
            "sample_size": int(len(df)),
            "avg_report_count": report_count,
            "positive_rating_ratio": positive_ratio,
            "forecast_eps_growth": eps_growth,
        }

    @classmethod
    def _aggregate(cls, profile: dict[str, Any], samples: list[dict[str, Any]], forecast: dict[str, Any] | None, errors: list[str]) -> dict[str, Any]:
        avg_roe = cls._mean([item.get("roe") for item in samples])
        avg_profit_growth = cls._mean([item.get("net_profit_growth") for item in samples])
        avg_revenue_growth = cls._mean([item.get("revenue_growth") for item in samples])
        avg_profit_delta = cls._mean([item.get("profit_growth_delta") for item in samples])
        forecast_eps_growth = cls._clean_number((forecast or {}).get("forecast_eps_growth"))
        positive_rating_ratio = cls._clean_number((forecast or {}).get("positive_rating_ratio"))

        score = 50.0
        score += cls._score_linear(avg_roe, low=5, high=18, weight=18)
        score += cls._score_linear(avg_profit_growth, low=-20, high=40, weight=18)
        score += cls._score_linear(avg_revenue_growth, low=-10, high=25, weight=10)
        score += cls._score_linear(avg_profit_delta, low=-20, high=20, weight=8)
        score += cls._score_linear(forecast_eps_growth, low=-10, high=25, weight=10)
        score += cls._score_linear(positive_rating_ratio, low=35, high=75, weight=8)
        score = max(0.0, min(100.0, score))

        return {
            "industry_key": profile.get("label"),
            "industry_name": profile.get("label"),
            "source": "akshare:eastmoney_finance_and_forecast",
            "updated_at": now_in_shanghai().isoformat(),
            "score": round(score, 1),
            "roe": cls._round(avg_roe),
            "net_profit_growth": cls._round(avg_profit_growth),
            "revenue_growth": cls._round(avg_revenue_growth),
            "profit_growth_delta": cls._round(avg_profit_delta),
            "forecast_eps_growth": cls._round(forecast_eps_growth),
            "positive_rating_ratio": cls._round(positive_rating_ratio),
            "forecast_sample_size": (forecast or {}).get("sample_size"),
            "sample_stocks": samples,
            "errors": errors[:5],
        }

    @staticmethod
    def _pick_number(row, keywords: tuple[str, ...]) -> float | None:
        if row is None:
            return None
        for col in getattr(row, "index", []):
            col_text = str(col)
            if any(keyword.lower() in col_text.lower() for keyword in keywords):
                value = IndustryFundamentalService._clean_number(row.get(col))
                if value is not None:
                    return value
        return None

    @staticmethod
    def _clean_number(value) -> float | None:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
            text = str(value).replace("%", "").replace(",", "").strip()
            if text in {"", "--", "-"}:
                return None
            parsed = float(text)
        except (TypeError, ValueError):
            return None
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed

    @classmethod
    def _mean_column(cls, df: pd.DataFrame, col: str) -> float | None:
        if col not in df.columns:
            return None
        return cls._mean([cls._clean_number(value) for value in df[col].tolist()])

    @classmethod
    def _sum_column(cls, df: pd.DataFrame, col: str) -> float:
        if col not in df.columns:
            return 0.0
        return sum(value for value in (cls._clean_number(item) for item in df[col].tolist()) if value is not None)

    @staticmethod
    def _mean(values) -> float | None:
        clean = [float(value) for value in values if value is not None]
        return sum(clean) / len(clean) if clean else None

    @staticmethod
    def _score_linear(value: float | None, low: float, high: float, weight: float) -> float:
        if value is None or high <= low:
            return 0.0
        ratio = (value - low) / (high - low)
        ratio = max(-1.0, min(1.0, ratio * 2 - 1))
        return ratio * weight

    @staticmethod
    def _round(value: float | None) -> float | None:
        return round(value, 2) if value is not None else None
