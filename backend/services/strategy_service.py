from __future__ import annotations

from typing import Optional

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_maker
from models.strategy_schedule_config import StrategyScheduleConfig
from schemas.market import KLineItem
from schemas.strategy import (
    StrategyInfo,
    StrategyRunResponse,
    StrategyScheduleResponse,
    StrategySignalResult,
)
from services.market_service import MarketService
from services.notification_service import NotificationMessage, NotificationService
from services.portfolio_service import PortfolioService
from services.scheduler import scheduler
from utils.timezone import now_in_shanghai


STRATEGY_ID = "tfss_v1"
STRATEGY_NAME = "ETF 决策引擎 (趋势内核 + 场景插件)"
OBSERVATION_POOL = ["513300", "159509", "515080", "511380"]
_last_runs: dict[tuple[int, str], StrategyRunResponse] = {}


class StrategyService:
    @classmethod
    def list_strategies(cls) -> list[StrategyInfo]:
        return [
            StrategyInfo(
                id=STRATEGY_ID,
                name=STRATEGY_NAME,
                description="先用动能分位选择关注标的，再按趋势/震荡环境切换回踩、乖离保护、网格和强制风控。",
            )
        ]

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        multiplier = 2 / (period + 1)
        result: list[float] = []
        for index, value in enumerate(values):
            if index == 0:
                result.append(value)
            else:
                result.append((value - result[index - 1]) * multiplier + result[index - 1])
        return result

    @staticmethod
    def _rsi(values: list[float], period: int = 14) -> Optional[float]:
        if len(values) <= period:
            return None
        gains: list[float] = []
        losses: list[float] = []
        for index in range(1, len(values)):
            change = values[index] - values[index - 1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _atr(klines: list[KLineItem], period: int = 14) -> Optional[float]:
        if len(klines) <= period:
            return None
        true_ranges: list[float] = []
        for index, item in enumerate(klines):
            high = float(item.high_price)
            low = float(item.low_price)
            if index == 0:
                true_ranges.append(high - low)
                continue
            prev_close = float(klines[index - 1].close_price)
            true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        return sum(true_ranges[-period:]) / period

    @classmethod
    def _build_metrics(cls, klines: list[KLineItem]) -> dict | None:
        if len(klines) < 30:
            return None

        closes = [float(item.close_price) for item in klines]
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20
        prev_ma5 = sum(closes[-6:-1]) / 5
        prev_ma20 = sum(closes[-23:-3]) / 20 if len(closes) >= 23 else ma20
        ma20_slope = ma20 - prev_ma20
        ma20_slope_pct = ma20_slope / prev_ma20 * 100 if prev_ma20 > 0 else 0.0
        close = closes[-1]
        prev_close = closes[-2]
        volume = int(klines[-1].volume)
        volume_ma10 = sum(float(item.volume) for item in klines[-10:]) / 10
        atr14 = cls._atr(klines, 14)
        atr_stop_price = close - 2 * atr14 if atr14 is not None else None

        ema12 = cls._ema(closes, 12)
        ema26 = cls._ema(closes, 26)
        dif_series = [ema12[index] - ema26[index] for index in range(len(closes))]
        dea_series = cls._ema(dif_series, 9)
        histogram = [(dif_series[index] - dea_series[index]) * 2 for index in range(len(closes))]
        dif = dif_series[-1]
        dea = dea_series[-1]
        prev_dif = dif_series[-2]
        prev_dea = dea_series[-2]
        hist = histogram[-1]
        rsi14 = cls._rsi(closes, 14)
        prev_rsi = cls._rsi(closes[:-1], 14)
        bias20 = ((close - ma20) / ma20 * 100) if ma20 > 0 else None
        momentum20 = ((close - closes[-21]) / closes[-21] * 100) if len(closes) >= 21 and closes[-21] > 0 else None

        return {
            "close": close,
            "prev_close": prev_close,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "prev_ma5": prev_ma5,
            "ma20_slope": ma20_slope,
            "ma20_slope_pct": ma20_slope_pct,
            "volume": volume,
            "volume_ma10": volume_ma10,
            "atr14": atr14,
            "atr_stop_price": atr_stop_price,
            "dif": dif,
            "dea": dea,
            "hist": hist,
            "rsi14": rsi14,
            "prev_rsi": prev_rsi,
            "bias20": bias20,
            "momentum20": momentum20,
            "macd_dead": prev_dif >= prev_dea and dif < dea,
            "macd_strong": dif > dea and dif > 0,
            "macd_flat": abs(dif - dea) <= max(abs(close) * 0.001, 0.0005),
            "low_volatility": atr14 is not None and close > 0 and (atr14 / close * 100) < 2.5,
        }

    @classmethod
    def _result_from_metrics(
        cls,
        code: str,
        name: str | None,
        metrics: dict | None,
        rotation_rank: int | None = None,
        rotation_top: bool = False,
        target_code: str | None = None,
    ) -> StrategySignalResult:
        if metrics is None:
            return StrategySignalResult(
                etf_code=code,
                etf_name=name,
                signal="insufficient_data",
                signal_label="数据不足",
                confidence=0,
                reasons=["至少需要 30 根日 K 计算趋势跟随信号"],
            )

        close = metrics["close"]
        ma5 = metrics["ma5"]
        ma10 = metrics["ma10"]
        ma20 = metrics["ma20"]
        prev_ma5 = metrics["prev_ma5"]
        ma20_slope = metrics["ma20_slope"]
        ma20_slope_pct = metrics["ma20_slope_pct"]
        dif = metrics["dif"]
        dea = metrics["dea"]
        hist = metrics["hist"]
        rsi14 = metrics["rsi14"]
        bias20 = metrics["bias20"]
        macd_dead = metrics["macd_dead"]
        reasons: list[str] = []
        risk_flags: list[str] = []
        engine_phase = "弱势/空仓"
        grid_action = None
        protection_action = None

        signal = "avoid"
        signal_label = "空仓观察"
        confidence = 45

        if rotation_rank is not None:
            momentum_text = f"{metrics['momentum20']:.2f}%" if metrics["momentum20"] is not None else "不足"
            reasons.append(f"动能分位排名第 {rotation_rank}，20日动能 {momentum_text}")
        if target_code and not rotation_top:
            reasons.append(f"当前动能目标为 {target_code}，本标的非优先关注")

        if close < ma10 or macd_dead:
            signal, signal_label, confidence = "exit", "清仓/离场", 92
            reasons.append("风控层触发：收盘价跌破 MA10 或 MACD 死叉")
        elif close > ma20 and ma20_slope > 0:
            engine_phase = "主升浪/回调"
            if (rsi14 is not None and rsi14 > 85) or (bias20 is not None and bias20 > 10):
                signal, signal_label, confidence = "reduce", "乖离保护", 84
                protection_action = "减仓30%-50%，禁止追高"
                reasons.append("主升浪中过热：RSI 或 BIAS20 触发乖离率保护")
            elif min(ma5, ma10) <= close <= max(ma5, ma10) and close < prev_ma5 and metrics["volume"] > metrics["volume_ma10"]:
                signal, signal_label, confidence = "entry", "均线回踩入场", 76
                reasons.append("趋势未破，价格回踩至 MA5/MA10 区间且成交量高于10日均量")
            elif close > ma10:
                signal, signal_label, confidence = "hold", "趋势锁仓", 70
                reasons.append("标的处于主升浪，价格仍在 MA10 上方")
        elif abs(ma20_slope_pct) < 0.1:
            engine_phase = "震荡带"
            grid_action = "以 MA20 为中轴，1% 步长低吸高抛"
            if close < ma20 and macd_dead:
                signal, signal_label, confidence = "exit", "停止网格", 82
                reasons.append("网格熔断：跌破 MA20 且 MACD 死叉")
            elif metrics["macd_flat"] and metrics["low_volatility"]:
                signal, signal_label, confidence = "hold", "网格运行", 66
                reasons.append("MA20 走平、MACD 粘合且波动率低，适合网格")
            else:
                signal, signal_label, confidence = "avoid", "等待网格条件", 52
                reasons.append("震荡特征不足，暂不启动网格")
        else:
            reasons.append("目标标的不满足主升浪或震荡带条件，空仓观察")

        if metrics["atr_stop_price"] is not None:
            risk_flags.append(f"ATR 动态止损参考 {metrics['atr_stop_price']:.3f}")
        if protection_action:
            risk_flags.append(protection_action)

        return StrategySignalResult(
            etf_code=code,
            etf_name=name,
            signal=signal,
            signal_label=signal_label,
            confidence=confidence,
            close_price=close,
            ma5=ma5,
            ma10=ma10,
            ma20=ma20,
            ma20_slope=ma20_slope,
            volume=metrics["volume"],
            volume_ma10=metrics["volume_ma10"],
            atr14=metrics["atr14"],
            atr_stop_price=metrics["atr_stop_price"],
            momentum20=metrics["momentum20"],
            rotation_rank=rotation_rank,
            rotation_top=rotation_top,
            engine_phase=engine_phase,
            grid_action=grid_action,
            protection_action=protection_action,
            macd_dif=dif,
            macd_dea=dea,
            macd_histogram=hist,
            rsi14=rsi14,
            bias20=bias20,
            reasons=reasons,
            risk_flags=risk_flags,
        )

    @staticmethod
    def _is_listed_etf(code: str) -> bool:
        return code.startswith(("51", "15", "16", "58"))

    @classmethod
    async def run_tfss_v1(cls, session: AsyncSession, user_id: int) -> StrategyRunResponse:
        portfolios = await PortfolioService.get_with_market(session, user_id=user_id)
        portfolio_by_code = {portfolio.etf_code: portfolio for portfolio in portfolios if cls._is_listed_etf(portfolio.etf_code)}
        pool_codes = list(dict.fromkeys([*OBSERVATION_POOL, *portfolio_by_code.keys()]))
        metrics_by_code: dict[str, dict | None] = {}
        name_by_code: dict[str, str | None] = {
            code: portfolio_by_code[code].etf_name for code in portfolio_by_code
        }
        for code in pool_codes:
            klines = await MarketService.get_history_kline(code, days=120)
            metrics_by_code[code] = cls._build_metrics(klines)

        ranked = sorted(
            [
                (code, metrics)
                for code, metrics in metrics_by_code.items()
                if metrics is not None and metrics.get("momentum20") is not None
            ],
            key=lambda item: item[1]["momentum20"],
            reverse=True,
        )
        rank_by_code = {code: index + 1 for index, (code, _) in enumerate(ranked)}
        target_code = ranked[0][0] if ranked else None

        results: list[StrategySignalResult] = []
        for code in pool_codes:
            if code not in portfolio_by_code and code != target_code:
                continue
            portfolio = portfolio_by_code.get(code)
            results.append(cls._result_from_metrics(
                code,
                name_by_code.get(code) or (portfolio.etf_name if portfolio else None),
                metrics_by_code.get(code),
                rotation_rank=rank_by_code.get(code),
                rotation_top=code == target_code,
                target_code=target_code,
            ))

        response = StrategyRunResponse(
            strategy_id=STRATEGY_ID,
            strategy_name=STRATEGY_NAME,
            run_at=now_in_shanghai(),
            total=len(results),
            results=results,
        )
        _last_runs[(user_id, STRATEGY_ID)] = response
        return response

    @classmethod
    def get_last_run(cls, user_id: int) -> Optional[StrategyRunResponse]:
        return _last_runs.get((user_id, STRATEGY_ID))

    @classmethod
    async def run_scheduled_tfss_v1(cls, user_id: int) -> None:
        async with async_session_maker() as session:
            result = await cls.run_tfss_v1(session, user_id)
            sent_count = await cls.send_strategy_notifications(session, user_id, result)
            await session.commit()
            print(f"[Strategy] 用户 {user_id} ETF 决策引擎定时运行完成，推送 {sent_count} 条")

    @classmethod
    async def send_strategy_notifications(
        cls,
        session: AsyncSession,
        user_id: int,
        result: StrategyRunResponse,
    ) -> int:
        configs = await NotificationService.get_enabled_configs(session, user_id)
        if not configs or not result.results:
            return 0

        actionable = [
            item for item in result.results
            if item.signal in {"entry", "reduce", "exit"}
        ]
        focus = actionable or result.results
        lines = []
        for item in focus[:8]:
            risk = f" | {'；'.join(item.risk_flags[:2])}" if item.risk_flags else ""
            lines.append(
                f"{item.etf_code} {item.etf_name or ''}: {item.signal_label} "
                f"({item.confidence}%) 收{item.close_price or 0:.3f}{risk}"
            )
        if len(focus) > 8:
            lines.append(f"其余信号：{len(focus) - 8} 个")

        body = (
            f"运行时间：{result.run_at.strftime('%Y-%m-%d %H:%M')}\n"
            f"分析标的：{result.total} 个\n"
            f"重点信号：{len(actionable)} 个\n\n"
            + "\n".join(lines)
        )
        return await NotificationService.send_message_to_configs(
            session,
            configs,
            NotificationMessage(
                title="【交易策略】ETF 决策引擎信号",
                body=body,
                group="ETF交易策略",
            ),
        )

    @classmethod
    def strategy_job_id(cls, user_id: int) -> str:
        return f"strategy_tfss_v1_user_{user_id}"

    @classmethod
    def _register_schedule_job(cls, user_id: int) -> None:
        job_id = cls.strategy_job_id(user_id)
        scheduler.add_job(
            cls.run_scheduled_tfss_v1,
            trigger=CronTrigger(day_of_week="mon-fri", hour=14, minute=40, timezone="Asia/Shanghai"),
            id=job_id,
            name=f"ETF 决策引擎 - 用户 {user_id}",
            args=[user_id],
            replace_existing=True,
        )

    @classmethod
    async def _get_or_create_schedule_config(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> StrategyScheduleConfig:
        result = await session.execute(
            select(StrategyScheduleConfig).where(
                StrategyScheduleConfig.user_id == user_id,
                StrategyScheduleConfig.strategy_id == STRATEGY_ID,
            )
        )
        config = result.scalar_one_or_none()
        if config is None:
            config = StrategyScheduleConfig(
                user_id=user_id,
                strategy_id=STRATEGY_ID,
                enabled=False,
                interval_minutes=0,
            )
            session.add(config)
            await session.flush()
        return config

    @classmethod
    async def set_schedule(
        cls,
        session: AsyncSession,
        user_id: int,
        enabled: bool,
    ) -> StrategyScheduleResponse:
        config = await cls._get_or_create_schedule_config(session, user_id)
        config.enabled = enabled
        config.interval_minutes = 0
        await session.flush()

        job_id = cls.strategy_job_id(user_id)
        if enabled:
            cls._register_schedule_job(user_id)
        elif scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        return cls._schedule_response(user_id, enabled)

    @classmethod
    def _schedule_response(cls, user_id: int, enabled: bool) -> StrategyScheduleResponse:
        job_id = cls.strategy_job_id(user_id)
        job = scheduler.get_job(job_id)
        return StrategyScheduleResponse(
            strategy_id=STRATEGY_ID,
            enabled=enabled and job is not None,
            job_id=job_id,
            next_run_time=getattr(job, "next_run_time", None) if job else None,
        )

    @classmethod
    async def get_schedule(cls, session: AsyncSession, user_id: int) -> StrategyScheduleResponse:
        config = await cls._get_or_create_schedule_config(session, user_id)
        job_id = cls.strategy_job_id(user_id)
        if config.enabled and scheduler.running and scheduler.get_job(job_id) is None:
            cls._register_schedule_job(user_id)
        return cls._schedule_response(user_id, config.enabled)

    @classmethod
    async def restore_schedules(cls) -> None:
        async with async_session_maker() as session:
            result = await session.execute(
                select(StrategyScheduleConfig).where(
                    StrategyScheduleConfig.strategy_id == STRATEGY_ID,
                    StrategyScheduleConfig.enabled == True,
                )
            )
            configs = result.scalars().all()

        for config in configs:
            cls._register_schedule_job(config.user_id)
        if configs:
            print(f"[Strategy] 已恢复 {len(configs)} 个 ETF 决策引擎定时任务")
