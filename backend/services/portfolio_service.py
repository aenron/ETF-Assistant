from datetime import date, datetime, time
from decimal import Decimal
import math
from typing import Optional, List, Any
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import Portfolio, EtfInfo, IndexValuation, PortfolioDcaSignalHistory, PortfolioDcaState, DcaIndexMapping, DcaSignalConfig, MacroCycleState
from schemas.portfolio import (
    PortfolioCreate, PortfolioUpdate, PortfolioResponse,
    PortfolioDcaSignalHistoryResponse, PortfolioWithMarket, PortfolioSummary
)
from services.etf_classification_service import EtfClassificationService
from services.industry_fundamental_service import IndustryFundamentalService
from services.market_service import MarketService
from services.redis_service import RedisService
from config import settings
from utils.timezone import now_in_shanghai


class PortfolioService:
    """持仓管理服务"""

    SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
    DCA_VALUATION_CACHE_PREFIX = "dca:valuation:"
    DCA_VALUATION_CACHE_EXPIRE_SECONDS = 86400


    REBALANCE_TARGET_RATIOS = {
        "A股宽基": 30.0,
        "A股成长": 15.0,
        "港股中概": 10.0,
        "美股成长": 12.0,
        "黄金商品": 12.0,
        "债券现金": 18.0,
        "其他": 3.0,
    }
    REBALANCE_IGNORE_DEVIATION_PCT = 3.0
    REBALANCE_SINGLE_ADJUSTMENT_LIMIT_PCT = 10.0

    DEFAULT_DCA_CONFIG = {
        "valuation_deep_green_percentile": 15.0,
        "valuation_green_percentile": 30.0,
        "valuation_red_percentile": 80.0,
        "valuation_min_sample_size": 250,
        "trend_short_ma_days": 20,
        "trend_medium_ma_days": 60,
        "trend_long_ma_days": 120,
        "trend_history_days": 140,
        "trend_slope_shift_days": 5,
        "trend_volume_ma_days": 20,
        "trend_volume_confirm_ratio": 0.8,
        "trend_volume_expand_ratio": 1.2,
        "trend_atr_days": 14,
        "trend_atr_base_multiplier": 1.5,
        "trend_atr_mid_multiplier": 1.8,
        "trend_atr_high_multiplier": 2.0,
        "trend_atr_mid_volatility_pct": 2.5,
        "trend_atr_high_volatility_pct": 4.0,
        "light_confirm_count": 2,
    }

    @classmethod
    async def _get_dca_config(cls, session: AsyncSession) -> dict[str, Any]:
        result = await session.execute(select(DcaSignalConfig).where(DcaSignalConfig.id == 1))
        config = result.scalar_one_or_none()
        if not config:
            return dict(cls.DEFAULT_DCA_CONFIG)
        data = dict(cls.DEFAULT_DCA_CONFIG)
        for key in data:
            value = getattr(config, key, None)
            if value is not None:
                data[key] = float(value) if key not in {"valuation_min_sample_size", "trend_short_ma_days", "trend_medium_ma_days", "trend_long_ma_days", "trend_history_days", "trend_slope_shift_days", "trend_volume_ma_days", "trend_atr_days", "light_confirm_count"} else int(value)
        return data

    @classmethod
    def _shanghai_now(cls) -> datetime:
        return datetime.now(cls.SHANGHAI_TZ)

    @classmethod
    def _quote_refresh_date(cls, refreshed_at) -> Optional[date]:
        if not refreshed_at:
            return None
        if refreshed_at.tzinfo is None:
            return refreshed_at.date()
        return refreshed_at.astimezone(cls.SHANGHAI_TZ).date()

    @classmethod
    def _is_today_market_quote(cls, refreshed_at) -> bool:
        """Treat quote change_pct as today's move once the A-share call auction starts."""
        now = cls._shanghai_now()
        if now.weekday() >= 5:
            return False
        if now.time() < time(9, 15):
            return False
        return cls._quote_refresh_date(refreshed_at) == now.date()

    @staticmethod
    def _finite_float(value, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if math.isnan(parsed) or math.isinf(parsed):
            return default
        return parsed

    @staticmethod
    def _optional_finite_float(value) -> Optional[float]:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed

    @staticmethod
    def _exposure_items(values: dict[str, float], total_value: float) -> list[dict[str, float | str]]:
        return [
            {
                "name": name,
                "market_value": PortfolioService._finite_float(value),
                "ratio": PortfolioService._finite_float(value / total_value * 100 if total_value > 0 else 0),
            }
            for name, value in sorted(values.items(), key=lambda item: item[1], reverse=True)
            if value > 0
        ]

    @staticmethod
    def _build_exposure_alerts(asset_bucket: dict[str, float], region: dict[str, float], style: dict[str, float], risk_tags: dict[str, float], total_value: float) -> list[dict[str, str]]:
        alerts: list[dict[str, str]] = []
        if total_value <= 0:
            return alerts

        def ratio(value: float) -> float:
            return value / total_value * 100

        for name, value in sorted(asset_bucket.items(), key=lambda item: item[1], reverse=True)[:1]:
            pct = ratio(value)
            if pct >= 70:
                alerts.append({"level": "high", "message": f"{name} 占比 {pct:.1f}%，资产桶集中度偏高。"})
            elif pct >= 50:
                alerts.append({"level": "medium", "message": f"{name} 占比 {pct:.1f}%，建议关注单一资产桶波动。"})

        for name, value in sorted(region.items(), key=lambda item: item[1], reverse=True)[:1]:
            pct = ratio(value)
            if pct >= 75:
                alerts.append({"level": "high", "message": f"{name} 地域暴露 {pct:.1f}%，国别/区域集中度较高。"})
            elif pct >= 60:
                alerts.append({"level": "medium", "message": f"{name} 地域暴露 {pct:.1f}%，区域分散度仍可优化。"})

        growth_value = style.get("成长", 0.0)
        if ratio(growth_value) >= 45:
            alerts.append({"level": "medium", "message": f"成长风格占比 {ratio(growth_value):.1f}%，对利率和风险偏好较敏感。"})

        cross_border = risk_tags.get("跨境", 0.0)
        if ratio(cross_border) >= 35:
            alerts.append({"level": "medium", "message": f"跨境 ETF 占比 {ratio(cross_border):.1f}%，需关注汇率、溢价和时差风险。"})

        high_vol = risk_tags.get("高波动", 0.0)
        if ratio(high_vol) >= 35:
            alerts.append({"level": "medium", "message": f"高波动 ETF 占比 {ratio(high_vol):.1f}%，建议控制单次调仓幅度。"})

        if not alerts:
            alerts.append({"level": "low", "message": "当前持仓暴露未发现明显集中风险。"})
        return alerts

    @staticmethod
    def _normalize_target_ratios(targets: dict[str, float]) -> dict[str, float]:
        total = sum(max(0.0, value) for value in targets.values())
        if total <= 0:
            return dict(PortfolioService.REBALANCE_TARGET_RATIOS)
        return {name: value / total * 100 for name, value in targets.items()}

    @staticmethod
    def _macro_adjusted_rebalance_targets(macro_states: dict[str, str] | None = None) -> tuple[dict[str, float], list[str]]:
        targets = dict(PortfolioService.REBALANCE_TARGET_RATIOS)
        notes: list[str] = []
        states = macro_states or {}
        cn = states.get("cn")
        us = states.get("us")
        global_phase = states.get("global")
        if cn == "recovery":
            targets["A股宽基"] += 4
            targets["A股成长"] += 3
            targets["债券现金"] -= 4
            notes.append("中国复苏：A股宽基和A股成长目标仓位上调。")
        elif cn == "overheating":
            targets["A股成长"] -= 3
            targets["黄金商品"] += 3
            targets["债券现金"] += 2
            notes.append("中国过热：成长目标下调，商品和现金缓冲上调。")
        elif cn == "stagflation":
            targets["A股成长"] -= 5
            targets["A股宽基"] -= 3
            targets["黄金商品"] += 4
            targets["债券现金"] += 4
            notes.append("中国滞涨：权益目标下调，黄金和现金缓冲上调。")
        elif cn == "recession":
            targets["A股宽基"] -= 4
            targets["A股成长"] -= 5
            targets["债券现金"] += 7
            notes.append("中国衰退：权益目标下调，债券现金目标上调。")

        if us == "recovery":
            targets["美股成长"] += 3
            notes.append("美国复苏：美股成长目标小幅上调。")
        elif us in {"overheating", "stagflation"}:
            targets["美股成长"] -= 4
            targets["黄金商品"] += 2
            targets["债券现金"] += 2
            notes.append("美国过热/滞涨：美股成长目标下调，防御资产上调。")
        elif us == "recession":
            targets["美股成长"] -= 3
            targets["债券现金"] += 3
            notes.append("美国衰退：跨境权益目标下调。")

        if global_phase == "recovery":
            targets["港股中概"] += 2
            targets["美股成长"] += 1
            notes.append("全球风险偏好修复：跨境权益目标小幅上调。")
        elif global_phase in {"stagflation", "recession"}:
            targets["港股中概"] -= 3
            targets["美股成长"] -= 2
            targets["黄金商品"] += 4
            targets["债券现金"] += 2
            notes.append("全球滞涨/衰退：跨境权益目标下调，黄金和现金缓冲上调。")
        return PortfolioService._normalize_target_ratios(targets), notes

    @staticmethod
    def _bucket_execution_context(portfolios: List[PortfolioWithMarket]) -> dict[str, dict[str, Any]]:
        context: dict[str, dict[str, Any]] = {}
        for p in portfolios:
            bucket = EtfClassificationService.classify(p.etf_code, p.etf_name).asset_bucket
            item = context.setdefault(bucket, {"red": 0, "green": 0, "yellow": 0, "cross_stop": 0, "factor_scores": []})
            light = p.dca_light or p.dca_candidate_light
            if light == "red":
                item["red"] += 1
            elif light in {"green", "deep_green"}:
                item["green"] += 1
            elif light == "yellow":
                item["yellow"] += 1
            risk = getattr(p, "cross_border_risk", None)
            if risk and getattr(risk, "action", None) == "不新增":
                item["cross_stop"] += 1
            factor = getattr(p, "factor_score", None)
            if factor and getattr(factor, "enabled", False):
                score = PortfolioService._optional_finite_float(getattr(factor, "total_score", None))
                if score is not None:
                    item["factor_scores"].append(score)
        return context

    @staticmethod
    def _build_rebalance_plan(asset_bucket: dict[str, float], available_cash: float, total_assets: float, portfolios: List[PortfolioWithMarket] | None = None, macro_states: dict[str, str] | None = None) -> dict:
        targets, macro_notes = PortfolioService._macro_adjusted_rebalance_targets(macro_states)
        execution_context = PortfolioService._bucket_execution_context(portfolios or [])
        current_values = {name: PortfolioService._finite_float(value) for name, value in asset_bucket.items()}
        if available_cash > 0:
            current_values["债券现金"] = current_values.get("债券现金", 0.0) + PortfolioService._finite_float(available_cash)
        for name in targets:
            current_values.setdefault(name, 0.0)

        single_limit = total_assets * PortfolioService.REBALANCE_SINGLE_ADJUSTMENT_LIMIT_PCT / 100 if total_assets > 0 else 0.0
        items = []
        for name, target_ratio in targets.items():
            current_value = current_values.get(name, 0.0)
            current_ratio = current_value / total_assets * 100 if total_assets > 0 else 0.0
            deviation = current_ratio - target_ratio
            raw_amount = (target_ratio - current_ratio) / 100 * total_assets if total_assets > 0 else 0.0
            suggested_amount = max(-single_limit, min(single_limit, raw_amount)) if single_limit > 0 else 0.0
            ctx = execution_context.get(name, {})
            avg_factor = sum(ctx.get("factor_scores", [])) / len(ctx.get("factor_scores", [])) if ctx.get("factor_scores") else None
            execution_status = "hold"
            execution_label = "保持观察"
            if abs(deviation) < PortfolioService.REBALANCE_IGNORE_DEVIATION_PCT:
                action = "保持"
                suggested_amount = 0.0
                reason = f"当前 {current_ratio:.1f}%，接近动态目标 {target_ratio:.1f}%。"
            elif deviation < 0:
                action = "增配"
                if ctx.get("cross_stop", 0) > 0:
                    execution_status = "blocked"
                    execution_label = "禁止新增"
                    suggested_amount = 0.0
                    reason = f"当前低于动态目标 {abs(deviation):.1f} 个百分点，但该资产桶存在跨境风控禁止新增，先不执行。"
                elif ctx.get("red", 0) > 0 and ctx.get("green", 0) == 0:
                    execution_status = "wait_signal"
                    execution_label = "等待买点"
                    suggested_amount = 0.0
                    reason = f"当前低于动态目标 {abs(deviation):.1f} 个百分点，但持仓红灯占优，等待红绿灯修复。"
                elif avg_factor is not None and avg_factor < 45:
                    execution_status = "wait_signal"
                    execution_label = "等待四因子修复"
                    suggested_amount = 0.0
                    reason = f"当前低于动态目标 {abs(deviation):.1f} 个百分点，但行业四因子均分 {avg_factor:.1f} 偏弱。"
                elif ctx.get("green", 0) > 0:
                    execution_status = "executable"
                    execution_label = "可立即执行"
                    reason = f"当前低于动态目标 {abs(deviation):.1f} 个百分点，且资产桶内存在绿灯标的，可用新增资金分批补足。"
                else:
                    execution_status = "wait_signal"
                    execution_label = "等待买点"
                    reason = f"当前低于动态目标 {abs(deviation):.1f} 个百分点，方向可增配，但需等待红绿灯确认。"
            else:
                action = "减配"
                execution_status = "reduce"
                execution_label = "建议减配"
                reason = f"当前高于动态目标 {deviation:.1f} 个百分点，后续新增资金优先避开该资产桶。"
            items.append({
                "name": name,
                "current_value": PortfolioService._finite_float(current_value),
                "current_ratio": PortfolioService._finite_float(current_ratio),
                "target_ratio": PortfolioService._finite_float(target_ratio),
                "deviation_ratio": PortfolioService._finite_float(deviation),
                "suggested_amount": PortfolioService._finite_float(suggested_amount),
                "action": action,
                "execution_status": execution_status,
                "execution_label": execution_label,
                "reason": reason,
            })

        items.sort(key=lambda item: (item["execution_status"] == "hold", -abs(item["deviation_ratio"])))
        notes = [
            "目标仓位已根据宏观时钟动态调整。",
            *macro_notes,
            f"单项建议调仓金额已限制在总资产 {PortfolioService.REBALANCE_SINGLE_ADJUSTMENT_LIMIT_PCT:.0f}% 以内。",
            "可执行状态同时考虑红绿灯、跨境风控和行业四因子评分。",
        ]
        return {
            "total_assets": PortfolioService._finite_float(total_assets),
            "single_adjustment_limit": PortfolioService._finite_float(single_limit),
            "items": items,
            "notes": notes,
        }

    @staticmethod
    def build_summary_from_portfolios(portfolios: List[PortfolioWithMarket], available_cash: float = 0.0, macro_states: dict[str, str] | None = None) -> PortfolioSummary:
        """基于已拉取的持仓+行情结果构建汇总，避免重复查询和重复拉行情。"""
        total_market_value = 0.0
        total_cost = 0.0
        today_pnl = 0.0
        today_previous_value = 0.0
        has_today_pnl = False
        category_distribution = {}
        asset_bucket_exposure: dict[str, float] = {}
        region_exposure: dict[str, float] = {}
        style_exposure: dict[str, float] = {}
        risk_tag_exposure: dict[str, float] = {}

        for p in portfolios:
            market_value = PortfolioService._optional_finite_float(p.market_value)
            if market_value is not None and market_value > 0:
                total_market_value += market_value
                cost = PortfolioService._finite_float(p.shares) * PortfolioService._finite_float(p.cost_price)
                total_cost += cost

                item_today_pnl = PortfolioService._optional_finite_float(p.today_pnl)
                if item_today_pnl is not None:
                    today_pnl += item_today_pnl
                    today_previous_value += market_value - item_today_pnl
                    has_today_pnl = True

                category = MarketService._guess_category(p.etf_name or "")
                if category not in category_distribution:
                    category_distribution[category] = 0.0
                category_distribution[category] += market_value

                classification = EtfClassificationService.classify(p.etf_code, p.etf_name)
                asset_bucket_exposure[classification.asset_bucket] = asset_bucket_exposure.get(classification.asset_bucket, 0.0) + market_value
                region_exposure[classification.region] = region_exposure.get(classification.region, 0.0) + market_value
                style_exposure[classification.style] = style_exposure.get(classification.style, 0.0) + market_value
                for tag in classification.risk_tags:
                    risk_tag_exposure[tag] = risk_tag_exposure.get(tag, 0.0) + market_value

        total_pnl = total_market_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
        today_pnl_value = today_pnl if has_today_pnl else None
        today_pnl_pct = (today_pnl / today_previous_value * 100) if has_today_pnl and today_previous_value > 0 else None
        total_assets = total_market_value + PortfolioService._finite_float(available_cash)
        exposure_analysis = {
            "asset_bucket": PortfolioService._exposure_items(asset_bucket_exposure, total_market_value),
            "region": PortfolioService._exposure_items(region_exposure, total_market_value),
            "style": PortfolioService._exposure_items(style_exposure, total_market_value),
            "risk_tags": PortfolioService._exposure_items(risk_tag_exposure, total_market_value),
            "alerts": PortfolioService._build_exposure_alerts(asset_bucket_exposure, region_exposure, style_exposure, risk_tag_exposure, total_market_value),
        }
        rebalance_plan = PortfolioService._build_rebalance_plan(asset_bucket_exposure, PortfolioService._finite_float(available_cash), total_assets, portfolios, macro_states)

        return PortfolioSummary(
            total_market_value=PortfolioService._finite_float(total_market_value),
            total_cost=PortfolioService._finite_float(total_cost),
            total_pnl=PortfolioService._finite_float(total_pnl),
            total_pnl_pct=PortfolioService._finite_float(total_pnl_pct),
            today_pnl=PortfolioService._optional_finite_float(today_pnl_value),
            today_pnl_pct=PortfolioService._optional_finite_float(today_pnl_pct),
            category_distribution={
                category: PortfolioService._finite_float(value)
                for category, value in category_distribution.items()
            },
            total_assets=PortfolioService._finite_float(total_assets),
            exposure_analysis=exposure_analysis,
            rebalance_plan=rebalance_plan,
        )
    
    @staticmethod
    async def get_all(session: AsyncSession, user_id: int) -> List[PortfolioResponse]:
        """获取所有持仓"""
        result = await session.execute(
            select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)
        )
        portfolios = result.scalars().all()
        return [PortfolioResponse.model_validate(p) for p in portfolios]
    
    @staticmethod
    async def get_by_id(
        session: AsyncSession, portfolio_id: int, user_id: int
    ) -> Optional[PortfolioResponse]:
        """获取单个持仓"""
        result = await session.execute(
            select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
        )
        portfolio = result.scalar_one_or_none()
        return PortfolioResponse.model_validate(portfolio) if portfolio else None
    

    @staticmethod
    async def get_dca_signal_history(
        session: AsyncSession,
        portfolio_id: int,
        user_id: int,
        limit: int = 30,
    ) -> list[PortfolioDcaSignalHistoryResponse] | None:
        portfolio_result = await session.execute(
            select(Portfolio.id).where(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
        )
        if portfolio_result.scalar_one_or_none() is None:
            return None

        safe_limit = max(1, min(limit, 100))
        result = await session.execute(
            select(PortfolioDcaSignalHistory)
            .where(
                PortfolioDcaSignalHistory.portfolio_id == portfolio_id,
                PortfolioDcaSignalHistory.user_id == user_id,
            )
            .order_by(PortfolioDcaSignalHistory.scanned_at.desc(), PortfolioDcaSignalHistory.id.desc())
            .limit(safe_limit)
        )
        return [PortfolioDcaSignalHistoryResponse.model_validate(item, from_attributes=True) for item in result.scalars().all()]

    @staticmethod
    async def create(
        session: AsyncSession, data: PortfolioCreate, user_id: int
    ) -> PortfolioResponse:
        """创建持仓"""
        portfolio = Portfolio(
            user_id=user_id,
            etf_code=data.etf_code,
            shares=data.shares,
            cost_price=data.cost_price,
            buy_date=data.buy_date,
            note=data.note,
        )
        session.add(portfolio)
        await session.flush()
        await session.refresh(portfolio)
        return PortfolioResponse.model_validate(portfolio)
    
    @staticmethod
    async def update(
        session: AsyncSession, 
        portfolio_id: int, 
        data: PortfolioUpdate,
        user_id: int,
    ) -> Optional[PortfolioResponse]:
        """更新持仓"""
        result = await session.execute(
            select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
        )
        portfolio = result.scalar_one_or_none()
        if not portfolio:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(portfolio, key, value)
        
        await session.flush()
        await session.refresh(portfolio)
        return PortfolioResponse.model_validate(portfolio)
    
    @staticmethod
    async def delete(session: AsyncSession, portfolio_id: int, user_id: int) -> bool:
        """删除持仓"""
        result = await session.execute(
            select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
        )
        portfolio = result.scalar_one_or_none()
        if not portfolio:
            return False
        
        await session.delete(portfolio)
        return True
    


    @staticmethod
    def _fallback_broad_index_symbol(name: str) -> str | None:
        candidates = [
            ("中证A500", "000510"),
            ("A500", "000510"),
            ("沪深300", "000300"),
            ("中证500", "000905"),
            ("中证1000", "000852"),
            ("科创50", "000688"),
            ("上证50", "000016"),
            ("创业板指", "399006"),
        ]
        for keyword, symbol in candidates:
            if keyword in name:
                return symbol
        return None

    @classmethod
    async def _resolve_broad_index_symbol(cls, session: AsyncSession, code: str, name: str) -> tuple[str | None, str]:
        normalized_code = (code or "").strip()
        if normalized_code:
            result = await session.execute(
                select(DcaIndexMapping)
                .where(DcaIndexMapping.enabled == True, DcaIndexMapping.etf_code == normalized_code)
                .order_by(DcaIndexMapping.id.asc())
                .limit(1)
            )
            mapping = result.scalar_one_or_none()
            if mapping:
                return mapping.index_symbol, f"配置映射：{normalized_code}->{mapping.index_symbol}"

        result = await session.execute(
            select(DcaIndexMapping)
            .where(DcaIndexMapping.enabled == True, DcaIndexMapping.keyword.is_not(None))
            .order_by(DcaIndexMapping.id.asc())
        )
        for mapping in result.scalars().all():
            if mapping.keyword and mapping.keyword in name:
                return mapping.index_symbol, f"关键词映射：{mapping.keyword}->{mapping.index_symbol}"

        fallback = cls._fallback_broad_index_symbol(name)
        if fallback:
            return fallback, f"内置映射：{fallback}"
        return None, "未配置宽基估值指数映射"

    @classmethod
    async def _cache_valuation_result(cls, index_symbol: str, valuation: dict[str, Any]) -> None:
        if not settings.redis_enabled:
            return
        await RedisService.set(
            f"{cls.DCA_VALUATION_CACHE_PREFIX}{index_symbol}",
            {"data": valuation},
            expire=cls.DCA_VALUATION_CACHE_EXPIRE_SECONDS,
        )

    @classmethod
    async def _valuation_from_db(cls, session: AsyncSession, index_symbol: str, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
        result = await session.execute(
            select(IndexValuation)
            .where(IndexValuation.index_symbol == index_symbol)
            .order_by(IndexValuation.trade_date.desc())
        )
        rows = result.scalars().all()
        pe_values = [
            float(row.pe)
            for row in rows
            if row.pe is not None and float(row.pe) > 0
        ]
        pb_values = [
            float(row.pb)
            for row in rows
            if row.pb is not None and float(row.pb) > 0
        ]
        if not rows or not pe_values:
            return None
        config = config or PortfolioService.DEFAULT_DCA_CONFIG
        green_percentile = float(config.get("valuation_green_percentile", 30.0)) / 100
        deep_green_percentile = float(config.get("valuation_deep_green_percentile", 15.0)) / 100

        latest = rows[0]
        current_pe = float(latest.pe) if latest.pe is not None else pe_values[0]
        current_pb = float(latest.pb) if latest.pb is not None else None
        pe_percentile = sum(1 for value in pe_values if value <= current_pe) / len(pe_values) * 100
        pb_percentile = None
        if current_pb is not None and pb_values:
            pb_percentile = sum(1 for value in pb_values if value <= current_pb) / len(pb_values) * 100
        percentile = pe_percentile * 0.6 + pb_percentile * 0.4 if pb_percentile is not None else pe_percentile
        sorted_pe = sorted(pe_values)
        sorted_pb = sorted(pb_values)
        pe_green = sorted_pe[max(0, min(len(sorted_pe) - 1, int(len(sorted_pe) * green_percentile) - 1))] if sorted_pe else None
        pe_deep_green = sorted_pe[max(0, min(len(sorted_pe) - 1, int(len(sorted_pe) * deep_green_percentile) - 1))] if sorted_pe else None
        pb_green = sorted_pb[max(0, min(len(sorted_pb) - 1, int(len(sorted_pb) * green_percentile) - 1))] if sorted_pb else None
        pb_deep_green = sorted_pb[max(0, min(len(sorted_pb) - 1, int(len(sorted_pb) * deep_green_percentile) - 1))] if sorted_pb else None
        return {
            "pe": round(current_pe, 2),
            "pb": round(current_pb, 2) if current_pb is not None else None,
            "pe_percentile": round(pe_percentile, 1),
            "pb_percentile": round(pb_percentile, 1) if pb_percentile is not None else None,
            "percentile": round(percentile, 1),
            "sample_size": min(len(pe_values), len(pb_values)) if pb_values else len(pe_values),
            "pe_green": round(pe_green, 2) if pe_green is not None else None,
            "pe_deep_green": round(pe_deep_green, 2) if pe_deep_green is not None else None,
            "pb_green": round(pb_green, 2) if pb_green is not None else None,
            "pb_deep_green": round(pb_deep_green, 2) if pb_deep_green is not None else None,
            "start_date": str(rows[-1].trade_date),
            "end_date": str(latest.trade_date),
            "cached_at": now_in_shanghai().isoformat(),
            "source": "db",
        }

    @classmethod
    async def _sync_broad_valuation_from_akshare(cls, session: AsyncSession, index_symbol: str, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
        try:
            import akshare as ak

            source = "csindex_history"
            try:
                df = await __import__("asyncio").to_thread(ak.stock_zh_index_value_csindex, symbol=index_symbol)
            except TypeError:
                df = None

            if df is None or df.empty:
                source = "csindex_latest"
                df = await __import__("asyncio").to_thread(ak.stock_zh_index_value_csindex)
                if df is None or df.empty:
                    return None

                code_col = "指数代码" if "指数代码" in df.columns else "index_code" if "index_code" in df.columns else None
                if code_col:
                    df = df[df[code_col].astype(str).str.zfill(6) == index_symbol]
                if df.empty:
                    return None

            values = []
            date_col = "日期" if "日期" in df.columns else "date" if "date" in df.columns else df.columns[0]
            pe_col = "市盈率1" if "市盈率1" in df.columns else "市盈率" if "市盈率" in df.columns else "pe" if "pe" in df.columns else "PE" if "PE" in df.columns else None
            pe2_col = "市盈率2" if "市盈率2" in df.columns else "pe_ttm" if "pe_ttm" in df.columns else None
            pb_col = "市净率1" if "市净率1" in df.columns else "市净率" if "市净率" in df.columns else "pb" if "pb" in df.columns else "PB" if "PB" in df.columns else None
            dy_col = "股息率1" if "股息率1" in df.columns else "股息率" if "股息率" in df.columns else "dv_ratio" if "dv_ratio" in df.columns else None
            dy2_col = "股息率2" if "股息率2" in df.columns else None
            name_col = "指数中文简称" if "指数中文简称" in df.columns else "指数中文全称" if "指数中文全称" in df.columns else "指数名称" if "指数名称" in df.columns else None
            if pe_col is None:
                return None

            for _, row in df.iterrows():
                trade_date_value = row.get(date_col)
                try:
                    trade_date = trade_date_value if isinstance(trade_date_value, date) else date.fromisoformat(str(trade_date_value).split(" ")[0])
                except Exception:
                    continue

                pe = cls._optional_finite_float(row.get(pe_col))
                if pe is None or pe <= 0:
                    continue
                pe2 = cls._optional_finite_float(row.get(pe2_col)) if pe2_col else None
                pb = cls._optional_finite_float(row.get(pb_col)) if pb_col else None
                dividend_yield = cls._optional_finite_float(row.get(dy_col)) if dy_col else None
                dividend_yield2 = cls._optional_finite_float(row.get(dy2_col)) if dy2_col else None
                values.append({
                    "index_symbol": index_symbol,
                    "trade_date": trade_date,
                    "index_name": str(row.get(name_col) or "") if name_col else "",
                    "pe": Decimal(str(pe)),
                    "pe2": Decimal(str(pe2)) if pe2 is not None else None,
                    "pb": Decimal(str(pb)) if pb is not None and pb > 0 else None,
                    "dividend_yield": Decimal(str(dividend_yield)) if dividend_yield is not None else None,
                    "dividend_yield2": Decimal(str(dividend_yield2)) if dividend_yield2 is not None else None,
                })

            if not values:
                return None

            stmt = insert(IndexValuation).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["index_symbol", "trade_date"],
                set_={
                    "index_name": stmt.excluded.index_name,
                    "pe": stmt.excluded.pe,
                    "pe2": stmt.excluded.pe2,
                    "pb": stmt.excluded.pb,
                    "dividend_yield": stmt.excluded.dividend_yield,
                    "dividend_yield2": stmt.excluded.dividend_yield2,
                    "updated_at": func.now(),
                },
            )
            await session.execute(stmt)
            await session.flush()
            valuation = await cls._valuation_from_db(session, index_symbol, config)
            if valuation:
                valuation["source"] = source
            return valuation
        except Exception as exc:
            print(f"[PortfolioService] 宽基估值获取失败: {index_symbol}, {exc}")
            return None

    @classmethod
    async def _fetch_broad_valuation(cls, session: AsyncSession, index_symbol: str, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
        cache_key = f"{cls.DCA_VALUATION_CACHE_PREFIX}{index_symbol}"
        if settings.redis_enabled:
            cached = await RedisService.get(cache_key)
            if cached and isinstance(cached.get("data"), dict):
                return cached["data"]

        valuation = await cls._valuation_from_db(session, index_symbol, config)
        if valuation:
            await cls._cache_valuation_result(index_symbol, valuation)
            return valuation

        valuation = await cls._sync_broad_valuation_from_akshare(session, index_symbol, config)
        if valuation:
            await cls._cache_valuation_result(index_symbol, valuation)
        return valuation

    @staticmethod
    def _estimate_valuation_trigger_price(current_price: float | None, current_value: float | None, target_value: float | None) -> float | None:
        if current_price is None or current_price <= 0 or current_value is None or current_value <= 0 or target_value is None or target_value <= 0:
            return None
        return round(current_price * target_value / current_value, 3)

    @staticmethod
    def _dca_quality_score(signal: dict, config: dict[str, Any] | None = None) -> float:
        config = config or PortfolioService.DEFAULT_DCA_CONFIG
        min_sample_size = int(config.get("valuation_min_sample_size", 250))
        red_threshold = float(config.get("valuation_red_percentile", 80.0))
        score = 50.0
        percentile = PortfolioService._optional_finite_float(signal.get("dca_valuation_percentile"))
        if percentile is not None:
            score += max(0.0, 50.0 - percentile) * 0.7
            if percentile > red_threshold:
                score -= 25
        distance_pct = PortfolioService._optional_finite_float(signal.get("dca_trend_distance_pct"))
        slope_pct = PortfolioService._optional_finite_float(signal.get("dca_trend_ma20_slope_pct"))
        atr_band_pct = PortfolioService._optional_finite_float(signal.get("dca_trend_atr_band_pct"))
        if slope_pct is not None:
            score += max(-10.0, min(10.0, slope_pct * 2))
        if distance_pct is not None and atr_band_pct is not None:
            score += 10 if abs(distance_pct) <= atr_band_pct else -10
        sample_size = signal.get("dca_valuation_sample_size")
        if isinstance(sample_size, int):
            if sample_size < min_sample_size:
                score -= 20
            elif sample_size >= 750:
                score += 5
        if signal.get("dca_light") == "red":
            score = min(score, 35)
        if signal.get("dca_light") == "deep_green":
            score += 10
        return round(max(0.0, min(100.0, score)), 1)

    @staticmethod
    def _valuation_dca_signal(valuation: dict[str, Any] | None, config: dict[str, Any] | None = None) -> dict:
        config = config or PortfolioService.DEFAULT_DCA_CONFIG
        min_sample_size = int(config.get("valuation_min_sample_size", 250))
        deep_green_threshold = float(config.get("valuation_deep_green_percentile", 15.0))
        green_threshold = float(config.get("valuation_green_percentile", 30.0))
        red_threshold = float(config.get("valuation_red_percentile", 80.0))
        if not valuation:
            return {
                "dca_track": "valuation",
                "dca_light": "yellow",
                "dca_label": "黄灯：估值待确认",
                "dca_action": "只执行基础定投",
                "dca_reason": "未能获取PE历史估值百分位，暂不触发增强加仓",
                "dca_next_trigger_price": None,
                "dca_valuation_percentile": None,
                "dca_valuation_pe": None,
                "dca_valuation_pb": None,
                "dca_valuation_pe_percentile": None,
                "dca_valuation_pb_percentile": None,
                "dca_valuation_sample_size": None,
                "dca_decision_steps": ["资产轨道：估值轨", "估值数据：未能获取PE/PB历史估值", "最终动作：只执行基础定投"],
                "dca_quality_score": 30.0,
                "dca_green_trigger_price": None,
                "dca_deep_green_trigger_price": None,
                "dca_budget_multiplier": 1.0,
                "dca_budget_label": "基础定投 1x",
            }

        percentile = float(valuation["percentile"])
        pe = float(valuation["pe"])
        pb = PortfolioService._optional_finite_float(valuation.get("pb"))
        pe_percentile = PortfolioService._optional_finite_float(valuation.get("pe_percentile"))
        pb_percentile = PortfolioService._optional_finite_float(valuation.get("pb_percentile"))
        sample_size = int(valuation.get("sample_size") or 0)
        green_trigger_price = PortfolioService._estimate_valuation_trigger_price(None, pe, PortfolioService._optional_finite_float(valuation.get("pe_green")))
        deep_green_trigger_price = PortfolioService._estimate_valuation_trigger_price(None, pe, PortfolioService._optional_finite_float(valuation.get("pe_deep_green")))
        sample_text = f"样本{valuation['start_date']}至{valuation['end_date']}，{sample_size}条"
        metric_text = f"PE {pe:.2f}" + (f"、PB {pb:.2f}" if pb is not None else "")
        percentile_text = f"综合分位{percentile:.1f}%"
        if pe_percentile is not None and pb_percentile is not None:
            percentile_text += f"（PE {pe_percentile:.1f}% / PB {pb_percentile:.1f}%）"
        base = {
            "dca_track": "valuation",
            "dca_next_trigger_price": None,
            "dca_valuation_percentile": percentile,
            "dca_valuation_pe": pe,
            "dca_valuation_pb": pb,
            "dca_valuation_pe_percentile": pe_percentile,
            "dca_valuation_pb_percentile": pb_percentile,
            "dca_valuation_sample_size": sample_size,
            "dca_green_trigger_price": green_trigger_price,
            "dca_deep_green_trigger_price": deep_green_trigger_price,
            "dca_decision_steps": [
                "资产轨道：估值轨",
                f"估值判断：{percentile_text}",
            ],
            "dca_budget_multiplier": 1.0,
            "dca_budget_label": "基础定投 1x",
        }
        if sample_size < min_sample_size:
            return {
                **base,
                "dca_light": "yellow",
                "dca_label": "黄灯：估值样本不足",
                "dca_action": "只执行基础定投",
                "dca_decision_steps": [*base["dca_decision_steps"], "样本检查：历史样本不足", "最终动作：基础定投 1x"],
                "dca_reason": f"当前{metric_text}，接口仅返回{sample_size}条近期估值，不能作为长期历史百分位判断，{sample_text}",
            }
        if percentile < deep_green_threshold:
            return {
                **base,
                "dca_light": "deep_green",
                "dca_label": "深绿：极度低估",
                "dca_action": "可大额建立/增加底仓",
                "dca_budget_multiplier": 3.0,
                "dca_budget_label": "增强定投 3x",
                "dca_decision_steps": [*base["dca_decision_steps"], "估值区间：深绿，极度低估", "最终动作：增强定投 3x"],
                "dca_reason": f"当前{metric_text}，{percentile_text}，{sample_text}",
            }
        if percentile < green_threshold:
            return {
                **base,
                "dca_light": "green",
                "dca_label": "浅绿：合理低估",
                "dca_action": "执行基准定投，可小幅增强",
                "dca_budget_multiplier": 1.5,
                "dca_budget_label": "增强定投 1.5x",
                "dca_decision_steps": [*base["dca_decision_steps"], "估值区间：浅绿，合理低估", "最终动作：增强定投 1.5x"],
                "dca_reason": f"当前{metric_text}，{percentile_text}，{sample_text}",
            }
        if percentile > red_threshold:
            return {
                **base,
                "dca_light": "red",
                "dca_label": "红灯：显著高估",
                "dca_action": "暂停新增定投",
                "dca_budget_multiplier": 0.0,
                "dca_budget_label": "暂停 0x",
                "dca_decision_steps": [*base["dca_decision_steps"], "估值区间：红灯，显著高估", "最终动作：暂停新增定投"],
                "dca_reason": f"当前{metric_text}，{percentile_text}，{sample_text}",
            }
        return {
            **base,
            "dca_light": "yellow",
            "dca_label": "黄灯：估值合理",
            "dca_action": "只执行基础定投",
            "dca_decision_steps": [*base["dca_decision_steps"], "估值区间：黄灯，估值合理", "最终动作：基础定投 1x"],
            "dca_reason": f"当前{metric_text}，{percentile_text}，{sample_text}",
        }


    @classmethod
    async def _apply_broad_trend_confirmation(cls, code: str, current_price: float, signal: dict, config: dict[str, Any] | None = None) -> dict:
        if signal.get("dca_track") != "valuation" or signal.get("dca_light") not in {"deep_green", "green"}:
            return signal
        config = config or cls.DEFAULT_DCA_CONFIG
        short_ma_days = int(config["trend_short_ma_days"])
        slope_shift_days = int(config["trend_slope_shift_days"])
        history_days = int(config["trend_history_days"])
        min_kline_days = short_ma_days + slope_shift_days + 3

        klines = await MarketService.get_history_kline(code, days=history_days)
        if len(klines) < min_kline_days:
            return {
                **signal,
                "dca_light": "yellow",
                "dca_label": "黄灯：低估待趋势确认",
                "dca_action": "只执行基础定投",
                "dca_budget_multiplier": 1.0,
                "dca_budget_label": "基础定投 1x",
                "dca_decision_steps": [*(signal.get("dca_decision_steps") or []), "趋势确认：历史K线不足", "最终动作：基础定投 1x"],
                "dca_reason": f"{signal.get('dca_reason') or ''}；宽基低估但趋势数据不足，暂不触发增强加仓",
            }

        closes = [float(item.close_price) for item in klines]
        ma20 = sum(closes[-short_ma_days:]) / short_ma_days
        prev_ma20 = sum(closes[-(short_ma_days + slope_shift_days + 3):-(slope_shift_days + 3)]) / short_ma_days
        ma20_slope_pct = (ma20 - prev_ma20) / prev_ma20 * 100 if prev_ma20 > 0 else 0.0
        distance_pct = (current_price - ma20) / ma20 * 100 if ma20 > 0 else 0.0
        next_trigger = round(ma20, 3) if ma20 > 0 else signal.get("dca_next_trigger_price")

        if current_price < ma20 and ma20_slope_pct < 0:
            return {
                **signal,
                "dca_light": "yellow",
                "dca_label": "黄灯：低估但趋势未稳",
                "dca_action": "只执行基础定投，等待站回MA20",
                "dca_budget_multiplier": 1.0,
                "dca_budget_label": "基础定投 1x",
                "dca_next_trigger_price": next_trigger,
                "dca_trend_ma20": round(ma20, 4),
                "dca_trend_ma20_slope_pct": round(ma20_slope_pct, 3),
                "dca_trend_distance_pct": round(distance_pct, 3),
                "dca_decision_steps": [*(signal.get("dca_decision_steps") or []), "趋势确认：价格低于MA20且MA20下行", "最终动作：降级为基础定投 1x"],
                "dca_reason": f"{signal.get('dca_reason') or ''}；但价格低于MA20且MA20下行，距离MA20约{distance_pct:.1f}%，增强加仓等待趋势企稳",
            }

        return {
            **signal,
            "dca_next_trigger_price": next_trigger,
            "dca_trend_ma20": round(ma20, 4),
            "dca_trend_ma20_slope_pct": round(ma20_slope_pct, 3),
            "dca_trend_distance_pct": round(distance_pct, 3),
            "dca_decision_steps": [*(signal.get("dca_decision_steps") or []), "趋势确认：MA20未明显走坏", f"最终动作：{signal.get('dca_budget_label') or signal.get('dca_action') or '-'}"],
            "dca_reason": f"{signal.get('dca_reason') or ''}；趋势确认：价格相对MA20约{distance_pct:.1f}%，MA20斜率{ma20_slope_pct:.2f}%",
        }

    @classmethod
    def _finalize_dca_signal(cls, signal: dict, current_price: float | None = None, valuation: dict[str, Any] | None = None, config: dict[str, Any] | None = None) -> dict:
        if valuation and current_price is not None and current_price > 0:
            pe = cls._optional_finite_float(valuation.get("pe"))
            pb = cls._optional_finite_float(valuation.get("pb"))
            pe_green_price = cls._estimate_valuation_trigger_price(current_price, pe, cls._optional_finite_float(valuation.get("pe_green")))
            pe_deep_price = cls._estimate_valuation_trigger_price(current_price, pe, cls._optional_finite_float(valuation.get("pe_deep_green")))
            pb_green_price = cls._estimate_valuation_trigger_price(current_price, pb, cls._optional_finite_float(valuation.get("pb_green")))
            pb_deep_price = cls._estimate_valuation_trigger_price(current_price, pb, cls._optional_finite_float(valuation.get("pb_deep_green")))
            green_candidates = [value for value in [pe_green_price, pb_green_price] if value is not None]
            deep_candidates = [value for value in [pe_deep_price, pb_deep_price] if value is not None]
            signal["dca_green_trigger_price"] = round(sum(green_candidates) / len(green_candidates), 3) if green_candidates else None
            signal["dca_deep_green_trigger_price"] = round(sum(deep_candidates) / len(deep_candidates), 3) if deep_candidates else None
        signal["dca_quality_score"] = cls._dca_quality_score(signal, config)
        return signal

    @classmethod
    async def _build_dca_signal(
        cls,
        session: AsyncSession,
        code: str,
        name: str | None,
        current_price: float | None,
        track_override: str | None = None,
    ) -> dict:
        config = await cls._get_dca_config(session)
        display_name = name or ""
        track = (track_override or "auto").strip()
        if track == "disabled":
            return {
                "dca_track": "disabled",
                "dca_light": None,
                "dca_label": "定投灯关闭",
                "dca_action": "不参与定投灯",
                "dca_reason": "该持仓已手动关闭定投灯",
                "dca_next_trigger_price": None,
                "dca_valuation_percentile": None,
                "dca_valuation_pe": None,
                "dca_budget_multiplier": 0.0,
                "dca_budget_label": "暂停 0x",
            }

        category = MarketService._guess_category(display_name)
        is_core_broad = track == "valuation" or (track == "auto" and (category == "宽基指数" or any(
            keyword in display_name
            for keyword in ["沪深300", "中证500", "中证A500", "A500", "科创50", "上证50"]
        )))

        if current_price is None or current_price <= 0:
            return {
                "dca_track": "unknown",
                "dca_light": "yellow",
                "dca_label": "黄灯：行情不足",
                "dca_action": "暂缓定投",
                "dca_reason": "当前价格缺失，无法判断加仓窗口",
                "dca_next_trigger_price": None,
                "dca_budget_multiplier": 1.0,
                "dca_budget_label": "基础定投 1x",
            }

        if is_core_broad:
            index_symbol, mapping_reason = await cls._resolve_broad_index_symbol(session, code, display_name)
            valuation = await cls._fetch_broad_valuation(session, index_symbol, config) if index_symbol else None
            signal = cls._valuation_dca_signal(valuation, config)
            signal["dca_decision_steps"] = [f"估值指数：{mapping_reason}", *(signal.get("dca_decision_steps") or [])]
            signal = await cls._apply_broad_trend_confirmation(code, current_price, signal, config)
            return cls._finalize_dca_signal(signal, current_price, valuation, config)

        klines = await MarketService.get_history_kline(code, days=int(config["trend_history_days"]))
        short_ma_days = int(config["trend_short_ma_days"])
        medium_ma_days = int(config["trend_medium_ma_days"])
        long_ma_days = int(config["trend_long_ma_days"])
        slope_shift_days = int(config["trend_slope_shift_days"])
        volume_ma_days = int(config["trend_volume_ma_days"])
        atr_days = int(config["trend_atr_days"])
        min_kline_days = short_ma_days + slope_shift_days + 3
        if len(klines) < min_kline_days:
            return {
                "dca_track": "trend",
                "dca_light": "yellow",
                "dca_label": "黄灯：趋势数据不足",
                "dca_action": "暂缓定投",
                "dca_reason": "历史K线不足，无法稳定计算短期均线斜率",
                "dca_next_trigger_price": None,
                "dca_budget_multiplier": 1.0,
                "dca_budget_label": "基础定投 1x",
                "dca_decision_steps": ["资产轨道：趋势轨", "趋势数据：历史K线不足", "最终动作：暂缓定投"],
                "dca_quality_score": 50.0,
            }

        closes = [float(item.close_price) for item in klines]
        ma20 = sum(closes[-short_ma_days:]) / short_ma_days
        prev_ma20 = sum(closes[-(short_ma_days + slope_shift_days + 3):-(slope_shift_days + 3)]) / short_ma_days
        ma20_slope_pct = (ma20 - prev_ma20) / prev_ma20 * 100 if prev_ma20 > 0 else 0.0
        ma60 = sum(closes[-medium_ma_days:]) / medium_ma_days if len(closes) >= medium_ma_days else None
        prev_ma60 = sum(closes[-(medium_ma_days + slope_shift_days):-slope_shift_days]) / medium_ma_days if len(closes) >= medium_ma_days + slope_shift_days else None
        ma60_slope_pct = (ma60 - prev_ma60) / prev_ma60 * 100 if ma60 is not None and prev_ma60 and prev_ma60 > 0 else None
        ma120 = sum(closes[-long_ma_days:]) / long_ma_days if len(closes) >= long_ma_days else None
        prev_ma120 = sum(closes[-(long_ma_days + slope_shift_days):-slope_shift_days]) / long_ma_days if len(closes) >= long_ma_days + slope_shift_days else None
        ma120_slope_pct = (ma120 - prev_ma120) / prev_ma120 * 100 if ma120 is not None and prev_ma120 and prev_ma120 > 0 else None
        distance = current_price - ma20
        distance_pct = distance / ma20 * 100 if ma20 > 0 else 0.0
        ma60_distance_pct = (current_price - ma60) / ma60 * 100 if ma60 and ma60 > 0 else None
        ma120_distance_pct = (current_price - ma120) / ma120 * 100 if ma120 and ma120 > 0 else None

        volumes = [float(getattr(item, "volume", 0) or 0) for item in klines]
        current_volume = volumes[-1] if volumes else 0.0
        volume_ma20_values = [value for value in volumes[-volume_ma_days:] if value > 0]
        volume_ma20 = sum(volume_ma20_values) / len(volume_ma20_values) if volume_ma20_values else None
        volume_ratio = current_volume / volume_ma20 if volume_ma20 and current_volume > 0 else None
        volume_text = f"量能为20日均量的{volume_ratio:.2f}倍" if volume_ratio is not None else "成交量数据不足"
        volume_confirmed = volume_ratio is None or volume_ratio >= float(config["trend_volume_confirm_ratio"])
        volume_expanded = volume_ratio is not None and volume_ratio >= float(config["trend_volume_expand_ratio"])

        true_ranges = []
        for index in range(1, len(klines)):
            high = float(klines[index].high_price)
            low = float(klines[index].low_price)
            prev_close = float(klines[index - 1].close_price)
            if high <= 0 or low <= 0 or prev_close <= 0:
                continue
            true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        atr14 = sum(true_ranges[-atr_days:]) / atr_days if len(true_ranges) >= atr_days else None
        atr_pct = atr14 / ma20 * 100 if atr14 is not None and ma20 > 0 else None
        atr_multiplier = float(config["trend_atr_high_multiplier"]) if atr_pct is not None and atr_pct >= float(config["trend_atr_high_volatility_pct"]) else float(config["trend_atr_mid_multiplier"]) if atr_pct is not None and atr_pct >= float(config["trend_atr_mid_volatility_pct"]) else float(config["trend_atr_base_multiplier"])
        atr_band = atr14 * atr_multiplier if atr14 is not None else ma20 * 0.03
        atr_band_pct = atr_band / ma20 * 100 if ma20 > 0 else 0.0
        next_trigger = round(ma20 + atr_band, 3) if ma20 > 0 else None
        atr_text = f"ATR14 {atr14:.3f}，{atr_multiplier:g}倍ATR约{atr_band_pct:.1f}%" if atr14 is not None else "ATR数据不足，使用3%固定阈值"
        medium_trend_ok = ma60 is None or current_price >= ma60 or (ma60_slope_pct is not None and ma60_slope_pct >= 0)
        medium_trend_weak = ma60 is not None and current_price < ma60 and (ma60_slope_pct is None or ma60_slope_pct < 0)
        long_trend_weak = ma120 is not None and current_price < ma120 and (ma120_slope_pct is None or ma120_slope_pct < 0)
        medium_trend_text = (
            f"MA60 {ma60:.3f}，距离{ma60_distance_pct:.1f}%" if ma60 is not None and ma60_distance_pct is not None else "MA60数据不足"
        )
        long_trend_text = (
            f"MA120 {ma120:.3f}，距离{ma120_distance_pct:.1f}%" if ma120 is not None and ma120_distance_pct is not None else "MA120数据不足"
        )

        if current_price > ma20 and ma20_slope_pct > 0:
            if distance <= atr_band and medium_trend_ok and volume_confirmed:
                return {
                    "dca_track": "trend",
                    "dca_light": "green",
                    "dca_label": "绿灯：右侧回踩",
                    "dca_action": "允许定投加仓",
                    "dca_budget_multiplier": 1.5,
                    "dca_budget_label": "增强定投 1.5x",
                    "dca_reason": f"价格高于MA20且MA20上行，距离MA20约{distance_pct:.1f}%，处于波动容忍区间内；{medium_trend_text}；{volume_text}；{atr_text}",
                    "dca_next_trigger_price": next_trigger,
                    "dca_trend_ma20": round(ma20, 4),
                    "dca_trend_ma20_slope_pct": round(ma20_slope_pct, 3),
                    "dca_trend_distance_pct": round(distance_pct, 3),
                    "dca_trend_atr14": round(atr14, 4) if atr14 is not None else None,
                    "dca_trend_atr_band_pct": round(atr_band_pct, 3),
                    "dca_trend_ma60": round(ma60, 4) if ma60 is not None else None,
                    "dca_trend_ma60_slope_pct": round(ma60_slope_pct, 3) if ma60_slope_pct is not None else None,
                    "dca_trend_ma120": round(ma120, 4) if ma120 is not None else None,
                    "dca_trend_ma120_slope_pct": round(ma120_slope_pct, 3) if ma120_slope_pct is not None else None,
                    "dca_trend_volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
                    "dca_trend_atr_multiplier": atr_multiplier,
                    "dca_decision_steps": ["资产轨道：趋势轨", "短期趋势：价格高于MA20且MA20上行", "中期过滤：MA60未明显走弱", "量能确认：成交量未明显萎缩", f"波动过滤：价格处于{atr_multiplier:g}倍ATR容忍区间内", "最终动作：增强定投 1.5x"],
                    "dca_quality_score": 72.0 if volume_expanded else 68.0,
                }
            return {
                "dca_track": "trend",
                "dca_light": "yellow",
                "dca_label": "黄灯：等待回踩" if distance > atr_band else "黄灯：趋势确认不足",
                "dca_action": "等待回踩到趋势触发价附近" if distance > atr_band else "等待中期趋势和量能确认",
                "dca_budget_multiplier": 1.0,
                "dca_budget_label": "基础定投 1x",
                "dca_reason": f"MA20上行，价格距离MA20约{distance_pct:.1f}%；{medium_trend_text}；{volume_text}；{atr_text}。{'价格偏离过大，不宜追高' if distance > atr_band else '中期趋势或量能确认不足，暂不增强加仓'}",
                "dca_next_trigger_price": next_trigger,
                "dca_trend_ma20": round(ma20, 4),
                "dca_trend_ma20_slope_pct": round(ma20_slope_pct, 3),
                "dca_trend_distance_pct": round(distance_pct, 3),
                "dca_trend_atr14": round(atr14, 4) if atr14 is not None else None,
                "dca_trend_atr_band_pct": round(atr_band_pct, 3),
                "dca_trend_ma60": round(ma60, 4) if ma60 is not None else None,
                "dca_trend_ma60_slope_pct": round(ma60_slope_pct, 3) if ma60_slope_pct is not None else None,
                "dca_trend_ma120": round(ma120, 4) if ma120 is not None else None,
                "dca_trend_ma120_slope_pct": round(ma120_slope_pct, 3) if ma120_slope_pct is not None else None,
                "dca_trend_volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
                "dca_trend_atr_multiplier": atr_multiplier,
                "dca_decision_steps": ["资产轨道：趋势轨", "短期趋势：价格高于MA20且MA20上行", "中期过滤：MA60偏弱" if not medium_trend_ok else "中期过滤：MA60未明显走弱", "量能确认：成交量偏弱" if not volume_confirmed else "量能确认：成交量可接受", f"波动过滤：{'价格超过' if distance > atr_band else '价格未超过'}{atr_multiplier:g}倍ATR容忍区间", "最终动作：等待回踩或确认"],
                "dca_quality_score": 54.0 if (not medium_trend_ok or not volume_confirmed) else 58.0,
            }

        if current_price < ma20 and (ma20_slope_pct < 0 or medium_trend_weak or long_trend_weak):
            deep_break = abs(distance) > atr_band or medium_trend_weak or long_trend_weak
            return {
                "dca_track": "trend",
                "dca_light": "red",
                "dca_label": "红灯：中期转弱" if long_trend_weak else "红灯：破位下行" if deep_break else "红灯：弱势下行",
                "dca_action": "暂停定投，等待重新站回MA60" if (medium_trend_weak or long_trend_weak) else "暂停定投，等待重新站回MA20" if deep_break else "暂停增强定投，观察MA20修复",
                "dca_budget_multiplier": 0.0,
                "dca_budget_label": "暂停 0x",
                "dca_reason": f"价格低于MA20，距离MA20约{distance_pct:.1f}%；{medium_trend_text}；{long_trend_text}；{'中长期均线转弱' if long_trend_weak else 'MA60过滤转弱' if medium_trend_weak else '短期趋势下行'}，禁止左侧抄底",
                "dca_next_trigger_price": round(ma60, 3) if (medium_trend_weak or long_trend_weak) and ma60 else round(ma20, 3) if ma20 > 0 else next_trigger,
                "dca_trend_ma20": round(ma20, 4),
                "dca_trend_ma20_slope_pct": round(ma20_slope_pct, 3),
                "dca_trend_distance_pct": round(distance_pct, 3),
                "dca_trend_atr14": round(atr14, 4) if atr14 is not None else None,
                "dca_trend_atr_band_pct": round(atr_band_pct, 3),
                "dca_trend_ma60": round(ma60, 4) if ma60 is not None else None,
                "dca_trend_ma60_slope_pct": round(ma60_slope_pct, 3) if ma60_slope_pct is not None else None,
                "dca_trend_ma120": round(ma120, 4) if ma120 is not None else None,
                "dca_trend_ma120_slope_pct": round(ma120_slope_pct, 3) if ma120_slope_pct is not None else None,
                "dca_trend_volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
                "dca_trend_atr_multiplier": atr_multiplier,
                "dca_decision_steps": ["资产轨道：趋势轨", "短期趋势：价格低于MA20", "中期过滤：跌破MA60且MA60走弱" if medium_trend_weak else "中期过滤：MA60未明显转弱", "长期过滤：跌破MA120且MA120走弱" if long_trend_weak else "长期过滤：MA120未明显转弱或数据不足", "风险分层：中期转弱" if long_trend_weak else "风险分层：破位下行" if deep_break else "风险分层：弱势下行", "最终动作：暂停定投"],
                "dca_quality_score": 18.0 if long_trend_weak else 24.0 if medium_trend_weak else 25.0 if deep_break else 32.0,
            }

        if current_price < ma20 and ma20_slope_pct >= 0:
            return {
                "dca_track": "trend",
                "dca_light": "yellow",
                "dca_label": "黄灯：趋势修复中",
                "dca_action": "等待价格站回MA20",
                "dca_budget_multiplier": 1.0,
                "dca_budget_label": "基础定投 1x",
                "dca_reason": f"MA20已不再下行，但价格仍低于MA20，距离MA20约{distance_pct:.1f}%；{medium_trend_text}；{volume_text}，需要先站回MA20确认修复",
                "dca_next_trigger_price": round(ma60, 3) if (medium_trend_weak or long_trend_weak) and ma60 else round(ma20, 3) if ma20 > 0 else next_trigger,
                "dca_trend_ma20": round(ma20, 4),
                "dca_trend_ma20_slope_pct": round(ma20_slope_pct, 3),
                "dca_trend_distance_pct": round(distance_pct, 3),
                "dca_trend_atr14": round(atr14, 4) if atr14 is not None else None,
                "dca_trend_atr_band_pct": round(atr_band_pct, 3),
                "dca_trend_ma60": round(ma60, 4) if ma60 is not None else None,
                "dca_trend_ma60_slope_pct": round(ma60_slope_pct, 3) if ma60_slope_pct is not None else None,
                "dca_trend_ma120": round(ma120, 4) if ma120 is not None else None,
                "dca_trend_ma120_slope_pct": round(ma120_slope_pct, 3) if ma120_slope_pct is not None else None,
                "dca_trend_volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
                "dca_trend_atr_multiplier": atr_multiplier,
                "dca_decision_steps": ["资产轨道：趋势轨", "短期趋势：MA20未继续下行", "位置判断：价格仍低于MA20", "中期过滤：MA60偏弱" if medium_trend_weak else "中期过滤：MA60未明显转弱", "量能确认：成交量偏弱" if not volume_confirmed else "量能确认：成交量可接受", "最终动作：等待站回MA20"],
                "dca_quality_score": 48.0,
            }

        if current_price >= ma20 and ma20_slope_pct <= 0:
            return {
                "dca_track": "trend",
                "dca_light": "yellow",
                "dca_label": "黄灯：站上但未转强",
                "dca_action": "等待MA20斜率转正",
                "dca_budget_multiplier": 1.0,
                "dca_budget_label": "基础定投 1x",
                "dca_reason": f"价格已站上MA20，但MA20斜率仍未转正（{ma20_slope_pct:.2f}%）；{medium_trend_text}；{volume_text}，趋势强度不足，暂不增强加仓",
                "dca_next_trigger_price": next_trigger,
                "dca_trend_ma20": round(ma20, 4),
                "dca_trend_ma20_slope_pct": round(ma20_slope_pct, 3),
                "dca_trend_distance_pct": round(distance_pct, 3),
                "dca_trend_atr14": round(atr14, 4) if atr14 is not None else None,
                "dca_trend_atr_band_pct": round(atr_band_pct, 3),
                "dca_trend_ma60": round(ma60, 4) if ma60 is not None else None,
                "dca_trend_ma60_slope_pct": round(ma60_slope_pct, 3) if ma60_slope_pct is not None else None,
                "dca_trend_ma120": round(ma120, 4) if ma120 is not None else None,
                "dca_trend_ma120_slope_pct": round(ma120_slope_pct, 3) if ma120_slope_pct is not None else None,
                "dca_trend_volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
                "dca_trend_atr_multiplier": atr_multiplier,
                "dca_decision_steps": ["资产轨道：趋势轨", "位置判断：价格已站上MA20", "短期趋势：MA20斜率未转正", "中期过滤：MA60偏弱" if medium_trend_weak else "中期过滤：MA60未明显转弱", "量能确认：成交量偏弱" if not volume_confirmed else "量能确认：成交量可接受", "最终动作：等待趋势转强"],
                "dca_quality_score": 52.0,
            }

        return {
            "dca_track": "trend",
            "dca_light": "yellow",
            "dca_label": "黄灯：均线缠绕",
            "dca_action": "观察等待",
            "dca_budget_multiplier": 1.0,
            "dca_budget_label": "基础定投 1x",
            "dca_reason": f"价格与MA20、MA20斜率方向不一致，距离MA20约{distance_pct:.1f}%，趋势信号不足",
            "dca_next_trigger_price": next_trigger,
            "dca_trend_ma20": round(ma20, 4),
            "dca_trend_ma20_slope_pct": round(ma20_slope_pct, 3),
            "dca_trend_distance_pct": round(distance_pct, 3),
            "dca_trend_atr14": round(atr14, 4) if atr14 is not None else None,
            "dca_trend_atr_band_pct": round(atr_band_pct, 3),
            "dca_decision_steps": ["资产轨道：趋势轨", "趋势判断：价格与MA20或斜率方向不一致", "最终动作：观察等待"],
            "dca_quality_score": 50.0,
        }

    @classmethod
    def _state_dca_signal(
        cls,
        state: PortfolioDcaState | None,
        history: PortfolioDcaSignalHistory | None = None,
    ) -> dict | None:
        if not state or state.last_light is None:
            return None
        metrics = history.metrics if history and isinstance(history.metrics, dict) else {}
        budget_multiplier = (
            cls._optional_finite_float(history.budget_multiplier)
            if history and history.budget_multiplier is not None
            else cls._optional_finite_float(state.last_budget_multiplier)
        )
        trigger_price = (
            cls._optional_finite_float(history.trigger_price)
            if history and history.trigger_price is not None
            else cls._optional_finite_float(state.last_trigger_price)
        )
        use_history_text = bool(history and history.persisted_light == state.last_light)
        return {
            "dca_track": metrics.get("track"),
            "dca_light": state.last_light,
            "dca_label": state.last_label,
            "dca_action": state.last_action,
            "dca_reason": history.reason if use_history_text and history.reason else "使用最近一次正式红绿灯状态；候选变化需满足确认次数后才会切换",
            "dca_next_trigger_price": trigger_price,
            "dca_valuation_percentile": cls._optional_finite_float(metrics.get("valuation_percentile")),
            "dca_valuation_pe": cls._optional_finite_float(metrics.get("valuation_pe")),
            "dca_valuation_pb": cls._optional_finite_float(metrics.get("valuation_pb")),
            "dca_valuation_pe_percentile": cls._optional_finite_float(metrics.get("valuation_pe_percentile")),
            "dca_valuation_pb_percentile": cls._optional_finite_float(metrics.get("valuation_pb_percentile")),
            "dca_valuation_sample_size": metrics.get("valuation_sample_size"),
            "dca_trend_ma20": cls._optional_finite_float(metrics.get("trend_ma20")),
            "dca_trend_ma20_slope_pct": cls._optional_finite_float(metrics.get("trend_ma20_slope_pct")),
            "dca_trend_distance_pct": cls._optional_finite_float(metrics.get("trend_distance_pct")),
            "dca_trend_atr14": cls._optional_finite_float(metrics.get("trend_atr14")),
            "dca_trend_atr_band_pct": cls._optional_finite_float(metrics.get("trend_atr_band_pct")),
            "dca_trend_ma60": cls._optional_finite_float(metrics.get("trend_ma60")),
            "dca_trend_ma60_slope_pct": cls._optional_finite_float(metrics.get("trend_ma60_slope_pct")),
            "dca_trend_ma120": cls._optional_finite_float(metrics.get("trend_ma120")),
            "dca_trend_ma120_slope_pct": cls._optional_finite_float(metrics.get("trend_ma120_slope_pct")),
            "dca_trend_volume_ratio": cls._optional_finite_float(metrics.get("trend_volume_ratio")),
            "dca_trend_atr_multiplier": cls._optional_finite_float(metrics.get("trend_atr_multiplier")),
            "dca_decision_steps": metrics.get("decision_steps") or ["使用最近一次后台红绿灯扫描结果", "等待下一次 10:30 或 14:40 后台更新刷新完整指标"],
            "dca_quality_score": cls._optional_finite_float(metrics.get("quality_score")),
            "dca_green_trigger_price": cls._optional_finite_float(metrics.get("green_trigger_price")),
            "dca_deep_green_trigger_price": cls._optional_finite_float(metrics.get("deep_green_trigger_price")),
            "dca_budget_multiplier": budget_multiplier,
            "dca_budget_label": None,
        }

    @classmethod
    def _pending_dca_signal(cls, track_override: str | None = None) -> dict:
        return {
            "dca_track": track_override or "unknown",
            "dca_light": "yellow",
            "dca_label": "黄灯：待后台计算",
            "dca_action": "等待后台更新",
            "dca_reason": "该持仓暂无缓存行情或红绿灯扫描结果，后台任务会在 10:30 / 14:40 更新",
            "dca_next_trigger_price": None,
            "dca_valuation_percentile": None,
            "dca_valuation_pe": None,
            "dca_valuation_pb": None,
            "dca_valuation_pe_percentile": None,
            "dca_valuation_pb_percentile": None,
            "dca_valuation_sample_size": None,
            "dca_trend_ma20": None,
            "dca_trend_ma20_slope_pct": None,
            "dca_trend_distance_pct": None,
            "dca_trend_atr14": None,
            "dca_trend_atr_band_pct": None,
            "dca_trend_ma60": None,
            "dca_trend_ma60_slope_pct": None,
            "dca_trend_ma120": None,
            "dca_trend_ma120_slope_pct": None,
            "dca_trend_volume_ratio": None,
            "dca_trend_atr_multiplier": None,
            "dca_decision_steps": ["列表接口：只读取缓存，不阻塞拉取外部数据", "最终动作：等待后台红绿灯数据更新"],
            "dca_candidate_light": None,
            "dca_candidate_confirm_count": None,
            "dca_quality_score": None,
            "dca_green_trigger_price": None,
            "dca_deep_green_trigger_price": None,
            "dca_budget_multiplier": 1.0,
            "dca_budget_label": "待计算",
        }

    @classmethod
    def _build_market_factor_metrics(cls, quote, dca_signal: dict) -> dict[str, float | None]:
        price = cls._optional_finite_float(getattr(quote, "price", None) if quote else None)
        amount = cls._optional_finite_float(getattr(quote, "amount", None) if quote else None)
        volume = cls._optional_finite_float(getattr(quote, "volume", None) if quote else None)
        volume_ratio = cls._optional_finite_float(dca_signal.get("dca_trend_volume_ratio"))
        ma20 = cls._optional_finite_float(dca_signal.get("dca_trend_ma20"))
        momentum20 = ((price - ma20) / ma20 * 100) if price is not None and ma20 and ma20 > 0 else None

        liquidity_score = None
        if amount is not None and amount > 0:
            if amount >= 500_000_000:
                liquidity_score = 90.0
            elif amount >= 100_000_000:
                liquidity_score = 75.0
            elif amount >= 30_000_000:
                liquidity_score = 60.0
            elif amount >= 10_000_000:
                liquidity_score = 45.0
            else:
                liquidity_score = 30.0
        elif volume is not None and volume > 0:
            liquidity_score = 50.0

        return {
            "amount": amount,
            "volume": volume,
            "volume_ratio": volume_ratio,
            "momentum20": momentum20,
            "liquidity_score": liquidity_score,
        }

    @classmethod
    def _build_factor_score(cls, code: str, name: str | None, quote, dca_signal: dict, fundamentals: dict | None = None) -> dict:
        classification = EtfClassificationService.classify(code, name)
        display_name = name or ""
        broad_keywords = ("沪深300", "中证500", "中证1000", "上证50", "A50", "深证100", "中证A500", "A500", "宽基", "全指", "红利", "股息")
        sector_keywords = (
            "芯片", "半导体", "人工智能", "AI", "机器人", "算力", "通信", "5G", "软件", "云计算", "科技",
            "新能源", "光伏", "锂电", "电池", "储能", "风电", "创新药", "生物", "医药", "医疗",
            "消费", "食品", "饮料", "白酒", "家电", "银行", "证券", "券商", "保险", "金融", "地产",
            "军工", "国防", "农业", "煤炭", "有色", "化工", "能源"
        )
        is_sector = any(keyword.lower() in f"{code} {display_name}".lower() for keyword in sector_keywords) and not any(keyword in display_name for keyword in broad_keywords)
        if not is_sector:
            return {
                "enabled": False,
                "total_score": 0.0,
                "macro_score": 0.0,
                "technical_score": 0.0,
                "sentiment_score": 0.0,
                "prosperity_score": 0.0,
                "rating": "不适用",
                "action": "不适用",
                "reason": "该 ETF 暂按宽基、跨境、商品或债券处理，不参与行业四因子评分。",
                "factors": [],
                "momentum20": None,
                "amount": None,
                "liquidity_score": None,
            }

        macro_score = 55.0
        factors: list[str] = []
        if classification.style == "成长":
            macro_score += 8
            factors.append("宏观：成长风格对流动性和风险偏好更敏感，基础分上调。")
        elif classification.style == "周期":
            macro_score += 4
            factors.append("宏观：周期行业更依赖经济修复，基础分中性偏正。")
        elif classification.style == "防御":
            macro_score += 2
            factors.append("宏观：防御行业波动较低，基础分略上调。")

        technical_score = cls._optional_finite_float(dca_signal.get("dca_quality_score"))
        if technical_score is None:
            light = dca_signal.get("dca_light")
            technical_score = 72.0 if light in {"deep_green", "green"} else 35.0 if light == "red" else 50.0
        factors.append(f"技术：复用红绿灯质量分 {technical_score:.1f}。")

        market_metrics = cls._build_market_factor_metrics(quote, dca_signal)
        change_pct = cls._optional_finite_float(getattr(quote, "change_pct", None) if quote else None)
        volume_ratio = cls._optional_finite_float(market_metrics.get("volume_ratio"))
        amount = cls._optional_finite_float(market_metrics.get("amount"))
        momentum20 = cls._optional_finite_float(market_metrics.get("momentum20"))
        liquidity_score = cls._optional_finite_float(market_metrics.get("liquidity_score"))
        sentiment_score = 50.0
        if change_pct is not None:
            sentiment_score += max(-18.0, min(18.0, change_pct * 3))
            factors.append(f"情绪：当日涨跌 {change_pct:.2f}%。")
        if momentum20 is not None:
            sentiment_score += max(-12.0, min(12.0, momentum20 * 0.8))
            factors.append(f"动量：价格相对MA20 {momentum20:.2f}%。")
        if volume_ratio is not None:
            sentiment_score += max(-10.0, min(10.0, (volume_ratio - 1) * 12))
            factors.append(f"情绪：量能约 {volume_ratio:.2f} 倍。")
        else:
            factors.append("情绪：量能数据不足，按中性处理。")
        if amount is not None:
            factors.append(f"流动性：实时成交额约 {amount / 100_000_000:.2f} 亿元。")
        if liquidity_score is not None:
            sentiment_score = sentiment_score * 0.75 + liquidity_score * 0.25

        prosperity_score = cls._optional_finite_float((fundamentals or {}).get("score")) or 50.0
        if fundamentals:
            industry_name = fundamentals.get("industry_name") or fundamentals.get("industry_key") or "行业"
            factors.append(f"景气度：{industry_name} 基本面分 {prosperity_score:.1f}。")
            roe = cls._optional_finite_float(fundamentals.get("roe"))
            profit_growth = cls._optional_finite_float(fundamentals.get("net_profit_growth"))
            forecast_growth = cls._optional_finite_float(fundamentals.get("forecast_eps_growth"))
            positive_ratio = cls._optional_finite_float(fundamentals.get("positive_rating_ratio"))
            if roe is not None:
                factors.append(f"ROE：代表成份股均值约 {roe:.2f}%。")
            if profit_growth is not None:
                factors.append(f"利润：代表成份股净利润同比约 {profit_growth:.2f}%。")
            if forecast_growth is not None:
                factors.append(f"盈利预测：未来一年 EPS 预测增速约 {forecast_growth:.2f}%。")
            if positive_ratio is not None:
                factors.append(f"机构预期：买入/增持占比约 {positive_ratio:.1f}%。")
        else:
            factors.append("景气度：暂无行业基本面缓存，按中性处理。")

        macro_score = max(0.0, min(100.0, macro_score))
        technical_score = max(0.0, min(100.0, technical_score))
        sentiment_score = max(0.0, min(100.0, sentiment_score))
        prosperity_score = max(0.0, min(100.0, prosperity_score))
        total_score = round(macro_score * 0.25 + technical_score * 0.35 + sentiment_score * 0.20 + prosperity_score * 0.20, 1)
        if total_score >= 75:
            rating, action = "强", "优先观察加仓"
        elif total_score >= 60:
            rating, action = "中强", "可小额配置"
        elif total_score >= 45:
            rating, action = "中性", "持有观察"
        else:
            rating, action = "弱", "谨慎或减配"
        return {
            "enabled": True,
            "total_score": total_score,
            "macro_score": round(macro_score, 1),
            "technical_score": round(technical_score, 1),
            "sentiment_score": round(sentiment_score, 1),
            "prosperity_score": round(prosperity_score, 1),
            "rating": rating,
            "action": action,
            "reason": "行业四因子评分为宏观、技术、情绪、景气度的加权结果；情绪接入实时成交额、量能和动量，景气度接入行业 ROE、利润增速和盈利预测。",
            "factors": factors,
            "momentum20": round(momentum20, 3) if momentum20 is not None else None,
            "amount": round(amount, 2) if amount is not None else None,
            "liquidity_score": round(liquidity_score, 1) if liquidity_score is not None else None,
        }

    @classmethod
    def _build_cross_border_risk(cls, code: str, name: str | None, market_value: float | None = None, total_market_value: float | None = None, quote=None) -> dict:
        classification = EtfClassificationService.classify(code, name)
        risk_tags = list(classification.risk_tags)
        is_cross_border = "跨境" in risk_tags
        if not is_cross_border:
            return {
                "is_cross_border": False,
                "risk_level": "low",
                "risk_tags": risk_tags,
                "max_position_hint": classification.max_position_hint,
                "budget_multiplier_adjustment": 1.0,
                "action": "常规执行",
                "reason": "非跨境 ETF，按常规红绿灯和宏观轮动规则执行。",
                "warnings": [],
                "iopv": None,
                "premium_rate": None,
            }

        current_weight = (market_value / total_market_value) if market_value and total_market_value and total_market_value > 0 else None
        price = cls._optional_finite_float(getattr(quote, "price", None) if quote else None)
        iopv = cls._optional_finite_float(getattr(quote, "iopv", None) if quote else None)
        premium_rate = ((price - iopv) / iopv * 100) if price is not None and iopv and iopv > 0 else None
        warnings = [
            "跨境 ETF 受海外交易时段影响，A 股交易时间内净值可能滞后。",
            "需要关注人民币汇率波动，汇率会放大或抵消底层资产收益。",
        ]
        if premium_rate is None:
            warnings.append("当前行情源未返回实时 IOPV，溢价率不可用，红绿灯不代表可追高买入。")
        else:
            warnings.append(f"实时溢价率约 {premium_rate:.2f}%。")
        risk_level = "medium"
        adjustment = 0.8
        action = "降倍率执行"

        if "高波动" in risk_tags or classification.asset_bucket in {"港股中概", "美股成长"}:
            risk_level = "high"
            adjustment = 0.6
            action = "小额分批"
            warnings.append("该类跨境成长 ETF 波动和估值弹性较高，绿灯也建议分批执行。")

        if premium_rate is not None and premium_rate >= 5:
            risk_level = "high"
            adjustment = 0.0
            action = "不新增"
            warnings.append("溢价率高于 5%，暂停新增，等待溢价回落。")
        elif premium_rate is not None and premium_rate >= 2:
            risk_level = "high"
            adjustment = min(adjustment, 0.4)
            action = "显著降倍率"
            warnings.append("溢价率高于 2%，只允许小额分批。")

        if current_weight is not None and current_weight >= classification.max_position_hint:
            risk_level = "high"
            adjustment = 0.0
            action = "不新增"
            warnings.append(f"当前单品种权重约 {current_weight * 100:.1f}%，已达到或超过建议上限 {classification.max_position_hint * 100:.0f}%。")

        return {
            "is_cross_border": True,
            "risk_level": risk_level,
            "risk_tags": risk_tags,
            "max_position_hint": classification.max_position_hint,
            "budget_multiplier_adjustment": adjustment,
            "action": action,
            "reason": "跨境 ETF 需要叠加汇率、时差、溢价和 T+0 交易风险约束。",
            "warnings": warnings,
            "iopv": round(iopv, 4) if iopv is not None else None,
            "premium_rate": round(premium_rate, 3) if premium_rate is not None else None,
        }

    @classmethod
    def _apply_cross_border_risk_to_signal(cls, signal: dict, risk: dict) -> dict:
        if not risk.get("is_cross_border"):
            return signal
        adjustment = cls._finite_float(risk.get("budget_multiplier_adjustment"), 1.0)
        current_multiplier = cls._optional_finite_float(signal.get("dca_budget_multiplier"))
        if current_multiplier is not None:
            adjusted = round(max(0.0, current_multiplier * adjustment), 2)
            signal["dca_budget_multiplier"] = adjusted
            if adjusted <= 0:
                signal["dca_budget_label"] = "跨境风控暂停 0x"
            elif adjusted < current_multiplier:
                signal["dca_budget_label"] = f"跨境风控 {adjusted:g}x"
        steps = list(signal.get("dca_decision_steps") or [])
        steps.append(f"跨境风控：{risk.get('action') or '降倍率执行'}")
        signal["dca_decision_steps"] = steps
        warning_text = "；".join(risk.get("warnings") or [])
        if warning_text:
            signal["dca_reason"] = f"{signal.get('dca_reason') or ''}；跨境风控：{warning_text}"
        return signal

    @classmethod
    async def get_with_market(
        cls, session: AsyncSession, user_id: int, compute_dca: bool = False
    ) -> List[PortfolioWithMarket]:
        """获取持仓列表（含实时行情）"""
        result = await session.execute(
            select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)
        )
        portfolios = result.scalars().all()
        
        if not portfolios:
            return []
        
        etf_codes = [p.etf_code for p in portfolios]
        if compute_dca:
            quotes = await MarketService.get_quotes_for_codes(etf_codes)
        else:
            # 持仓列表只读取缓存行情，避免新增 ETF 缺数据时阻塞整张表。
            quotes = await MarketService.get_cached_quotes_for_codes(etf_codes)
        info_result = await session.execute(select(EtfInfo).where(EtfInfo.code.in_(etf_codes)))
        etf_name_by_code = {item.code: item.name for item in info_result.scalars().all()}
        state_result = await session.execute(select(PortfolioDcaState).where(PortfolioDcaState.portfolio_id.in_([p.id for p in portfolios])))
        dca_state_by_portfolio_id = {item.portfolio_id: item for item in state_result.scalars().all()}
        dca_history_by_portfolio_id: dict[int, PortfolioDcaSignalHistory] = {}
        if not compute_dca:
            history_result = await session.execute(
                select(PortfolioDcaSignalHistory)
                .where(
                    PortfolioDcaSignalHistory.user_id == user_id,
                    PortfolioDcaSignalHistory.portfolio_id.in_([p.id for p in portfolios]),
                )
                .order_by(
                    PortfolioDcaSignalHistory.portfolio_id.asc(),
                    PortfolioDcaSignalHistory.scanned_at.desc(),
                    PortfolioDcaSignalHistory.id.desc(),
                )
            )
            for history in history_result.scalars().all():
                dca_history_by_portfolio_id.setdefault(history.portfolio_id, history)
        
        estimated_total_market_value = 0.0
        for p in portfolios:
            quote = quotes.get(p.etf_code)
            price = cls._optional_finite_float(quote.price) if quote else None
            if price is not None and price > 0:
                estimated_total_market_value += cls._finite_float(p.shares) * price

        industry_key_by_code = {
            p.etf_code: IndustryFundamentalService.resolve_industry_key(
                p.etf_code,
                (quotes.get(p.etf_code).name if quotes.get(p.etf_code) else None) or etf_name_by_code.get(p.etf_code),
            )
            for p in portfolios
        }
        fundamental_by_key = await IndustryFundamentalService.get_many(
            [key for key in industry_key_by_code.values() if key],
            allow_fetch=compute_dca,
        )

        results = []
        for p in portfolios:
            quote = quotes.get(p.etf_code)
            display_name = (quote.name if quote else None) or etf_name_by_code.get(p.etf_code)
            price = cls._optional_finite_float(quote.price) if quote else None
            dca_state = dca_state_by_portfolio_id.get(p.id)
            if compute_dca:
                dca_signal = await cls._build_dca_signal(session, p.etf_code, display_name, price, p.dca_track_override)
            else:
                dca_signal = cls._state_dca_signal(
                    dca_state,
                    dca_history_by_portfolio_id.get(p.id),
                ) or cls._pending_dca_signal(p.dca_track_override)
            if dca_state:
                dca_signal["dca_candidate_light"] = dca_state.candidate_light
                dca_signal["dca_candidate_confirm_count"] = dca_state.candidate_confirm_count
            else:
                dca_signal["dca_candidate_light"] = None
                dca_signal["dca_candidate_confirm_count"] = None
            estimated_market_value = cls._finite_float(p.shares) * price if price is not None and price > 0 else None
            cross_border_risk = cls._build_cross_border_risk(p.etf_code, display_name, estimated_market_value, estimated_total_market_value, quote)
            dca_signal = cls._apply_cross_border_risk_to_signal(dca_signal, cross_border_risk)
            industry_key = industry_key_by_code.get(p.etf_code)
            factor_score = cls._build_factor_score(p.etf_code, display_name, quote, dca_signal, fundamental_by_key.get(industry_key) if industry_key else None)
            if quote and price is not None and price > 0:
                shares = cls._finite_float(p.shares)
                cost_price = cls._finite_float(p.cost_price)
                change_pct = cls._optional_finite_float(quote.change_pct)
                market_value = shares * price
                cost = shares * cost_price
                pnl = market_value - cost
                pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0
                today_pnl = None
                today_pnl_pct = None
                today = cls._shanghai_now().date()
                if cls._is_today_market_quote(quote.refreshed_at):
                    if p.buy_date == today:
                        today_pnl = pnl
                        today_pnl_pct = pnl_pct
                    elif change_pct is not None:
                        previous_value = market_value / (1 + change_pct / 100) if change_pct != -100 else 0.0
                        today_pnl = market_value - previous_value
                        today_pnl_pct = change_pct
                
                holding_days = None
                if p.buy_date:
                    holding_days = (today - p.buy_date).days
                
                results.append(PortfolioWithMarket(
                    id=p.id,
                    etf_code=p.etf_code,
                    shares=float(p.shares),
                    cost_price=float(p.cost_price),
                    buy_date=p.buy_date,
                    note=p.note,
                    dca_track_override=p.dca_track_override,
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                    etf_name=display_name,
                    current_price=price,
                    change_pct=change_pct,
                    market_refreshed_at=quote.refreshed_at,
                    market_value=cls._finite_float(market_value),
                    pnl=cls._finite_float(pnl),
                    pnl_pct=cls._finite_float(pnl_pct),
                    today_pnl=cls._optional_finite_float(today_pnl),
                    today_pnl_pct=cls._optional_finite_float(today_pnl_pct),
                    holding_days=holding_days,
                    cross_border_risk=cross_border_risk,
                    factor_score=factor_score,
                    **dca_signal,
                ))
            else:
                results.append(PortfolioWithMarket(
                    id=p.id,
                    etf_code=p.etf_code,
                    shares=float(p.shares),
                    cost_price=float(p.cost_price),
                    buy_date=p.buy_date,
                    note=p.note,
                    dca_track_override=p.dca_track_override,
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                    etf_name=display_name,
                    cross_border_risk=cross_border_risk,
                    factor_score=factor_score,
                    **dca_signal,
                ))
        
        return results
    
    @staticmethod
    async def get_summary(session: AsyncSession, user_id: int) -> PortfolioSummary:
        """获取持仓汇总"""
        from models.user import User
        
        portfolios = await PortfolioService.get_with_market(session, user_id=user_id, compute_dca=False)
        # 获取用户可用资金
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        available_cash = float(user.account_balance) if user and user.account_balance else 0.0
        macro_result = await session.execute(
            select(MacroCycleState)
            .where(MacroCycleState.region.in_(["cn", "us", "global"]))
            .order_by(MacroCycleState.region.asc(), MacroCycleState.observed_at.desc(), MacroCycleState.id.desc())
        )
        macro_states: dict[str, str] = {}
        for state in macro_result.scalars().all():
            macro_states.setdefault(state.region, state.cycle_phase)
        
        return PortfolioService.build_summary_from_portfolios(portfolios, available_cash, macro_states)
