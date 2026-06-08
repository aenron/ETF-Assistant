from datetime import date, datetime, time
from decimal import Decimal
import math
from typing import Optional, List, Any
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import Portfolio, EtfInfo, IndexValuation, PortfolioDcaSignalHistory, PortfolioDcaState
from schemas.portfolio import (
    PortfolioCreate, PortfolioUpdate, PortfolioResponse,
    PortfolioDcaSignalHistoryResponse, PortfolioWithMarket, PortfolioSummary
)
from services.market_service import MarketService
from services.redis_service import RedisService
from config import settings
from utils.timezone import now_in_shanghai


class PortfolioService:
    """持仓管理服务"""

    SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
    DCA_VALUATION_CACHE_PREFIX = "dca:valuation:"
    DCA_VALUATION_CACHE_EXPIRE_SECONDS = 86400

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
    def build_summary_from_portfolios(portfolios: List[PortfolioWithMarket], available_cash: float = 0.0) -> PortfolioSummary:
        """基于已拉取的持仓+行情结果构建汇总，避免重复查询和重复拉行情。"""
        total_market_value = 0.0
        total_cost = 0.0
        today_pnl = 0.0
        today_previous_value = 0.0
        has_today_pnl = False
        category_distribution = {}

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

        total_pnl = total_market_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
        today_pnl_value = today_pnl if has_today_pnl else None
        today_pnl_pct = (today_pnl / today_previous_value * 100) if has_today_pnl and today_previous_value > 0 else None
        total_assets = total_market_value + PortfolioService._finite_float(available_cash)

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
    def _broad_index_symbol(name: str) -> str | None:
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
    async def _cache_valuation_result(cls, index_symbol: str, valuation: dict[str, Any]) -> None:
        if not settings.redis_enabled:
            return
        await RedisService.set(
            f"{cls.DCA_VALUATION_CACHE_PREFIX}{index_symbol}",
            {"data": valuation},
            expire=cls.DCA_VALUATION_CACHE_EXPIRE_SECONDS,
        )

    @classmethod
    async def _valuation_from_db(cls, session: AsyncSession, index_symbol: str) -> dict[str, Any] | None:
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
        pe_green = sorted_pe[max(0, min(len(sorted_pe) - 1, int(len(sorted_pe) * 0.30) - 1))] if sorted_pe else None
        pe_deep_green = sorted_pe[max(0, min(len(sorted_pe) - 1, int(len(sorted_pe) * 0.15) - 1))] if sorted_pe else None
        pb_green = sorted_pb[max(0, min(len(sorted_pb) - 1, int(len(sorted_pb) * 0.30) - 1))] if sorted_pb else None
        pb_deep_green = sorted_pb[max(0, min(len(sorted_pb) - 1, int(len(sorted_pb) * 0.15) - 1))] if sorted_pb else None
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
    async def _sync_broad_valuation_from_akshare(cls, session: AsyncSession, index_symbol: str) -> dict[str, Any] | None:
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
            valuation = await cls._valuation_from_db(session, index_symbol)
            if valuation:
                valuation["source"] = source
            return valuation
        except Exception as exc:
            print(f"[PortfolioService] 宽基估值获取失败: {index_symbol}, {exc}")
            return None

    @classmethod
    async def _fetch_broad_valuation(cls, session: AsyncSession, index_symbol: str) -> dict[str, Any] | None:
        cache_key = f"{cls.DCA_VALUATION_CACHE_PREFIX}{index_symbol}"
        if settings.redis_enabled:
            cached = await RedisService.get(cache_key)
            if cached and isinstance(cached.get("data"), dict):
                return cached["data"]

        valuation = await cls._valuation_from_db(session, index_symbol)
        if valuation:
            await cls._cache_valuation_result(index_symbol, valuation)
            return valuation

        valuation = await cls._sync_broad_valuation_from_akshare(session, index_symbol)
        if valuation:
            await cls._cache_valuation_result(index_symbol, valuation)
        return valuation

    @staticmethod
    def _estimate_valuation_trigger_price(current_price: float | None, current_value: float | None, target_value: float | None) -> float | None:
        if current_price is None or current_price <= 0 or current_value is None or current_value <= 0 or target_value is None or target_value <= 0:
            return None
        return round(current_price * target_value / current_value, 3)

    @staticmethod
    def _dca_quality_score(signal: dict) -> float:
        score = 50.0
        percentile = PortfolioService._optional_finite_float(signal.get("dca_valuation_percentile"))
        if percentile is not None:
            score += max(0.0, 50.0 - percentile) * 0.7
            if percentile > 80:
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
            if sample_size < 250:
                score -= 20
            elif sample_size >= 750:
                score += 5
        if signal.get("dca_light") == "red":
            score = min(score, 35)
        if signal.get("dca_light") == "deep_green":
            score += 10
        return round(max(0.0, min(100.0, score)), 1)

    @staticmethod
    def _valuation_dca_signal(valuation: dict[str, Any] | None) -> dict:
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
        if sample_size < 250:
            return {
                **base,
                "dca_light": "yellow",
                "dca_label": "黄灯：估值样本不足",
                "dca_action": "只执行基础定投",
                "dca_decision_steps": [*base["dca_decision_steps"], "样本检查：历史样本不足", "最终动作：基础定投 1x"],
                "dca_reason": f"当前{metric_text}，接口仅返回{sample_size}条近期估值，不能作为长期历史百分位判断，{sample_text}",
            }
        if percentile < 15:
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
        if percentile < 30:
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
        if percentile > 80:
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
    async def _apply_broad_trend_confirmation(cls, code: str, current_price: float, signal: dict) -> dict:
        if signal.get("dca_track") != "valuation" or signal.get("dca_light") not in {"deep_green", "green"}:
            return signal

        klines = await MarketService.get_history_kline(code, days=60)
        if len(klines) < 23:
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
        ma20 = sum(closes[-20:]) / 20
        prev_ma20 = sum(closes[-23:-3]) / 20
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
    def _finalize_dca_signal(cls, signal: dict, current_price: float | None = None, valuation: dict[str, Any] | None = None) -> dict:
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
        signal["dca_quality_score"] = cls._dca_quality_score(signal)
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
            index_symbol = cls._broad_index_symbol(display_name)
            valuation = await cls._fetch_broad_valuation(session, index_symbol) if index_symbol else None
            signal = cls._valuation_dca_signal(valuation)
            signal = await cls._apply_broad_trend_confirmation(code, current_price, signal)
            return cls._finalize_dca_signal(signal, current_price, valuation)

        klines = await MarketService.get_history_kline(code, days=60)
        if len(klines) < 23:
            return {
                "dca_track": "trend",
                "dca_light": "yellow",
                "dca_label": "黄灯：趋势数据不足",
                "dca_action": "暂缓定投",
                "dca_reason": "少于23根日K，无法稳定计算MA20斜率",
                "dca_next_trigger_price": None,
                "dca_budget_multiplier": 1.0,
                "dca_budget_label": "基础定投 1x",
                "dca_decision_steps": ["资产轨道：趋势轨", "趋势数据：少于23根日K", "最终动作：暂缓定投"],
                "dca_quality_score": 50.0,
            }

        closes = [float(item.close_price) for item in klines]
        ma20 = sum(closes[-20:]) / 20
        prev_ma20 = sum(closes[-23:-3]) / 20
        ma20_slope_pct = (ma20 - prev_ma20) / prev_ma20 * 100 if prev_ma20 > 0 else 0.0
        distance = current_price - ma20
        distance_pct = distance / ma20 * 100 if ma20 > 0 else 0.0

        true_ranges = []
        for index in range(1, len(klines)):
            high = float(klines[index].high_price)
            low = float(klines[index].low_price)
            prev_close = float(klines[index - 1].close_price)
            if high <= 0 or low <= 0 or prev_close <= 0:
                continue
            true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        atr14 = sum(true_ranges[-14:]) / 14 if len(true_ranges) >= 14 else None
        atr_band = atr14 * 1.5 if atr14 is not None else ma20 * 0.03
        atr_band_pct = atr_band / ma20 * 100 if ma20 > 0 else 0.0
        next_trigger = round(ma20 + atr_band, 3) if ma20 > 0 else None
        atr_text = f"ATR14 {atr14:.3f}，1.5倍ATR约{atr_band_pct:.1f}%" if atr14 is not None else "ATR数据不足，使用3%固定阈值"

        if current_price > ma20 and ma20_slope_pct > 0:
            if distance <= atr_band:
                return {
                    "dca_track": "trend",
                    "dca_light": "green",
                    "dca_label": "绿灯：右侧回踩",
                    "dca_action": "允许定投加仓",
                    "dca_budget_multiplier": 1.5,
                    "dca_budget_label": "增强定投 1.5x",
                    "dca_reason": f"价格高于MA20且MA20上行，距离MA20约{distance_pct:.1f}%，处于波动容忍区间内，{atr_text}",
                    "dca_next_trigger_price": next_trigger,
                    "dca_trend_ma20": round(ma20, 4),
                    "dca_trend_ma20_slope_pct": round(ma20_slope_pct, 3),
                    "dca_trend_distance_pct": round(distance_pct, 3),
                    "dca_trend_atr14": round(atr14, 4) if atr14 is not None else None,
                    "dca_trend_atr_band_pct": round(atr_band_pct, 3),
                    "dca_decision_steps": ["资产轨道：趋势轨", "趋势判断：价格高于MA20且MA20上行", "波动过滤：价格处于1.5倍ATR容忍区间内", "最终动作：增强定投 1.5x"],
                "dca_quality_score": 50.0,
                }
            return {
                "dca_track": "trend",
                "dca_light": "yellow",
                "dca_label": "黄灯：趋势偏强但偏离",
                "dca_action": "等待回踩再加仓",
                "dca_budget_multiplier": 1.0,
                "dca_budget_label": "基础定投 1x",
                "dca_reason": f"MA20上行但价格距离MA20约{distance_pct:.1f}%，已超过波动容忍区间，不宜追高，{atr_text}",
                "dca_next_trigger_price": next_trigger,
                "dca_trend_ma20": round(ma20, 4),
                "dca_trend_ma20_slope_pct": round(ma20_slope_pct, 3),
                "dca_trend_distance_pct": round(distance_pct, 3),
                "dca_trend_atr14": round(atr14, 4) if atr14 is not None else None,
                "dca_trend_atr_band_pct": round(atr_band_pct, 3),
                "dca_decision_steps": ["资产轨道：趋势轨", "趋势判断：价格高于MA20且MA20上行", "波动过滤：价格超过1.5倍ATR容忍区间", "最终动作：等待回踩"],
                "dca_quality_score": 50.0,
            }

        if current_price < ma20 and ma20_slope_pct < 0:
            return {
                "dca_track": "trend",
                "dca_light": "red",
                "dca_label": "红灯：下行趋势",
                "dca_action": "暂停定投",
                "dca_budget_multiplier": 0.0,
                "dca_budget_label": "暂停 0x",
                "dca_reason": "价格低于MA20且MA20斜率向下，禁止左侧抄底",
                "dca_next_trigger_price": next_trigger,
                "dca_trend_ma20": round(ma20, 4),
                "dca_trend_ma20_slope_pct": round(ma20_slope_pct, 3),
                "dca_trend_distance_pct": round(distance_pct, 3),
                "dca_trend_atr14": round(atr14, 4) if atr14 is not None else None,
                "dca_trend_atr_band_pct": round(atr_band_pct, 3),
                "dca_decision_steps": ["资产轨道：趋势轨", "趋势判断：价格低于MA20且MA20下行", "最终动作：暂停定投"],
                "dca_quality_score": 50.0,
            }

        return {
            "dca_track": "trend",
            "dca_light": "yellow",
            "dca_label": "黄灯：趋势未确认",
            "dca_action": "观察等待",
            "dca_budget_multiplier": 1.0,
            "dca_budget_label": "基础定投 1x",
            "dca_reason": f"价格在MA20附近或趋势方向不一致，距离MA20约{distance_pct:.1f}%",
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
    async def get_with_market(
        cls, session: AsyncSession, user_id: int
    ) -> List[PortfolioWithMarket]:
        """获取持仓列表（含实时行情）"""
        result = await session.execute(
            select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)
        )
        portfolios = result.scalars().all()
        
        if not portfolios:
            return []
        
        # 只获取持仓ETF的行情（优先从Redis缓存）
        etf_codes = [p.etf_code for p in portfolios]
        quotes = await MarketService.get_quotes_for_codes(etf_codes)
        info_result = await session.execute(select(EtfInfo).where(EtfInfo.code.in_(etf_codes)))
        etf_name_by_code = {item.code: item.name for item in info_result.scalars().all()}
        state_result = await session.execute(select(PortfolioDcaState).where(PortfolioDcaState.portfolio_id.in_([p.id for p in portfolios])))
        dca_state_by_portfolio_id = {item.portfolio_id: item for item in state_result.scalars().all()}
        
        results = []
        for p in portfolios:
            quote = quotes.get(p.etf_code)
            display_name = (quote.name if quote else None) or etf_name_by_code.get(p.etf_code)
            price = cls._optional_finite_float(quote.price) if quote else None
            dca_signal = await cls._build_dca_signal(session, p.etf_code, display_name, price, p.dca_track_override)
            dca_state = dca_state_by_portfolio_id.get(p.id)
            if dca_state:
                dca_signal["dca_candidate_light"] = dca_state.candidate_light
                dca_signal["dca_candidate_confirm_count"] = dca_state.candidate_confirm_count
            else:
                dca_signal["dca_candidate_light"] = None
                dca_signal["dca_candidate_confirm_count"] = None
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
                    **dca_signal,
                ))
        
        return results
    
    @staticmethod
    async def get_summary(session: AsyncSession, user_id: int) -> PortfolioSummary:
        """获取持仓汇总"""
        from models.user import User
        
        portfolios = await PortfolioService.get_with_market(session, user_id=user_id)
        # 获取用户可用资金
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        available_cash = float(user.account_balance) if user and user.account_balance else 0.0
        
        return PortfolioService.build_summary_from_portfolios(portfolios, available_cash)
