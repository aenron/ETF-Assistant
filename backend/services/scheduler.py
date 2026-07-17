"""定时任务服务"""
import asyncio
from collections import defaultdict
from inspect import iscoroutinefunction
from decimal import Decimal

from sqlalchemy import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from database import async_session_maker
from models.etf_info import EtfInfo
from models.portfolio import Portfolio
from models.portfolio_dca_signal_history import PortfolioDcaSignalHistory
from models.portfolio_dca_state import PortfolioDcaState
from models.dca_signal_config import DcaSignalConfig
from models.scheduler_job_config import SchedulerJobConfig
from models.user import User
from models.watchlist_item import WatchlistItem
from services.advisor_service import AdvisorService
from services.market_service import MarketService
from services.industry_fundamental_service import IndustryFundamentalService
from services.macro_service import MacroDataService
from services.portfolio_service import PortfolioService
from services.notification_service import NotificationMessage, NotificationService
from utils.timezone import now_in_shanghai, now_in_utc_naive


scheduler = AsyncIOScheduler()


async def _get_active_portfolio_codes(task_name: str) -> list[str]:
    async with async_session_maker() as db:
        try:
            result = await db.execute(
                select(Portfolio.etf_code)
                .join(User, Portfolio.user_id == User.id)
                .where(User.is_active == True)
                .distinct()
            )
            codes = sorted({code for code in result.scalars().all() if code})
            if not codes:
                print(f"[Scheduler] 无持仓ETF，跳过{task_name}")
            return codes
        except Exception as e:
            print(f"[Scheduler] 加载ETF列表失败，跳过{task_name}: {e}")
            return []


async def _get_active_market_refresh_codes(task_name: str) -> list[str]:
    async with async_session_maker() as db:
        try:
            portfolio_result = await db.execute(
                select(Portfolio.etf_code)
                .join(User, Portfolio.user_id == User.id)
                .where(User.is_active == True)
                .distinct()
            )
            watchlist_result = await db.execute(
                select(WatchlistItem.code)
                .join(User, WatchlistItem.user_id == User.id)
                .where(User.is_active == True)
                .distinct()
            )
            portfolio_codes = {code for code in portfolio_result.scalars().all() if code}
            watchlist_codes = {code for code in watchlist_result.scalars().all() if code}
            codes = sorted(portfolio_codes | watchlist_codes)
            if not codes:
                print(f"[Scheduler] 无持仓或自选品种，跳过{task_name}")
            else:
                print(
                    f"[Scheduler] {task_name}范围：持仓 {len(portfolio_codes)} 只，"
                    f"自选 {len(watchlist_codes)} 只，去重后 {len(codes)} 只"
                )
            return codes
        except Exception as e:
            print(f"[Scheduler] 加载持仓/自选品种失败，跳过{task_name}: {e}")
            return []


def _format_datetime(value):
    if value is None:
        return None
    return value.isoformat()


def _serialize_job(job):
    next_run_time = getattr(job, "next_run_time", None)
    return {
        "id": job.id,
        "name": job.name,
        "trigger": str(job.trigger),
        "next_run_time": _format_datetime(next_run_time),
        "enabled": next_run_time is not None,
    }


def list_scheduler_jobs():
    """列出当前调度器任务状态"""
    return {
        "running": scheduler.running,
        "jobs": sorted(
            [_serialize_job(job) for job in scheduler.get_jobs()],
            key=lambda item: item["id"],
        ),
    }


async def ensure_scheduler_job_configs(db):
    """确保当前注册的任务都有持久化配置"""
    result = await db.execute(select(SchedulerJobConfig))
    configs = {config.job_id: config for config in result.scalars().all()}

    created = False
    current_job_ids = {job.id for job in scheduler.get_jobs()}
    for job in scheduler.get_jobs():
        if job.id not in configs:
            db.add(SchedulerJobConfig(job_id=job.id, enabled=True))
            created = True

    for job_id, config in configs.items():
        if job_id.startswith("market_refresh_") and job_id not in current_job_ids:
            await db.delete(config)
            created = True

    if created:
        await db.flush()


async def get_scheduler_job_enabled_map(db):
    """读取任务启用配置"""
    await ensure_scheduler_job_configs(db)
    result = await db.execute(select(SchedulerJobConfig))
    return {config.job_id: config.enabled for config in result.scalars().all()}


async def set_scheduler_job_enabled(db, job_id: str, enabled: bool):
    """更新任务启用配置"""
    await ensure_scheduler_job_configs(db)
    result = await db.execute(
        select(SchedulerJobConfig).where(SchedulerJobConfig.job_id == job_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        config = SchedulerJobConfig(job_id=job_id, enabled=enabled)
        db.add(config)
    else:
        config.enabled = enabled
    await db.flush()
    return config


async def apply_scheduler_job_configs():
    """启动时应用持久化任务开关"""
    async with async_session_maker() as db:
        enabled_map = await get_scheduler_job_enabled_map(db)
        await db.commit()

    for job_id, enabled in enabled_map.items():
        job = get_scheduler_job(job_id)
        if not job:
            continue
        if enabled:
            scheduler.resume_job(job_id)
        else:
            scheduler.pause_job(job_id)


def get_scheduler_job(job_id: str):
    """获取单个调度任务"""
    return scheduler.get_job(job_id)


def pause_scheduler_job(job_id: str):
    """暂停单个调度任务"""
    scheduler.pause_job(job_id)
    return get_scheduler_job(job_id)


def resume_scheduler_job(job_id: str):
    """恢复单个调度任务"""
    scheduler.resume_job(job_id)
    return get_scheduler_job(job_id)


def trigger_scheduler_job_now(job_id: str):
    """手动触发单个调度任务，不影响原有 cron 计划"""
    job = get_scheduler_job(job_id)
    if not job:
        return None

    func = job.func
    if iscoroutinefunction(func):
        asyncio.create_task(func(*job.args, **job.kwargs))
    else:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, lambda: func(*job.args, **job.kwargs))
    return job



def _dca_history_metrics(portfolio) -> dict:
    return {
        "track": portfolio.dca_track,
        "valuation_percentile": portfolio.dca_valuation_percentile,
        "valuation_pe": portfolio.dca_valuation_pe,
        "valuation_pb": portfolio.dca_valuation_pb,
        "valuation_pe_percentile": portfolio.dca_valuation_pe_percentile,
        "valuation_pb_percentile": portfolio.dca_valuation_pb_percentile,
        "valuation_sample_size": portfolio.dca_valuation_sample_size,
        "trend_ma20": portfolio.dca_trend_ma20,
        "trend_ma20_slope_pct": portfolio.dca_trend_ma20_slope_pct,
        "trend_distance_pct": portfolio.dca_trend_distance_pct,
        "trend_atr14": portfolio.dca_trend_atr14,
        "trend_atr_band_pct": portfolio.dca_trend_atr_band_pct,
        "trend_ma60": getattr(portfolio, "dca_trend_ma60", None),
        "trend_ma60_slope_pct": getattr(portfolio, "dca_trend_ma60_slope_pct", None),
        "trend_ma120": getattr(portfolio, "dca_trend_ma120", None),
        "trend_ma120_slope_pct": getattr(portfolio, "dca_trend_ma120_slope_pct", None),
        "trend_volume_ratio": getattr(portfolio, "dca_trend_volume_ratio", None),
        "trend_atr_multiplier": getattr(portfolio, "dca_trend_atr_multiplier", None),
        "decision_steps": portfolio.dca_decision_steps,
        "quality_score": portfolio.dca_quality_score,
        "green_trigger_price": portfolio.dca_green_trigger_price,
        "deep_green_trigger_price": portfolio.dca_deep_green_trigger_price,
    }


def _add_dca_history(db, state: PortfolioDcaState, portfolio, user_id: int) -> None:
    db.add(PortfolioDcaSignalHistory(
        portfolio_id=portfolio.id,
        user_id=user_id,
        etf_code=portfolio.etf_code,
        signal_light=portfolio.dca_light,
        persisted_light=state.last_light,
        candidate_light=state.candidate_light,
        candidate_confirm_count=state.candidate_confirm_count,
        label=portfolio.dca_label,
        action=portfolio.dca_action,
        reason=portfolio.dca_reason,
        budget_multiplier=_to_decimal(portfolio.dca_budget_multiplier),
        trigger_price=_to_decimal(portfolio.dca_next_trigger_price),
        price=_to_decimal(portfolio.current_price),
        metrics=_dca_history_metrics(portfolio),
        scanned_at=now_in_utc_naive(),
    ))

def _dca_notify_key(portfolio) -> str:
    return f"{portfolio.etf_code}:{portfolio.dca_light}:{portfolio.dca_budget_multiplier}:{portfolio.dca_next_trigger_price}"


def _to_decimal(value):
    if value is None:
        return None
    return Decimal(str(value))


def _dca_trigger_reached(portfolio, state: PortfolioDcaState | None) -> bool:
    if portfolio.current_price is None or portfolio.dca_next_trigger_price is None:
        return False
    if portfolio.dca_light == "red" or portfolio.dca_track == "disabled":
        return False
    current_price = float(portfolio.current_price)
    trigger_price = float(portfolio.dca_next_trigger_price)
    if current_price > trigger_price:
        return False
    if state is None or state.last_trigger_price is None:
        return True
    return abs(float(state.last_trigger_price) - trigger_price) > 0.0001


def _dca_changed(portfolio, state: PortfolioDcaState | None) -> bool:
    if state is None or state.last_light is None:
        return False
    if state.last_light != portfolio.dca_light:
        return True
    previous = float(state.last_budget_multiplier) if state.last_budget_multiplier is not None else None
    current = float(portfolio.dca_budget_multiplier) if portfolio.dca_budget_multiplier is not None else None
    return previous != current


def _update_dca_state(state: PortfolioDcaState, portfolio) -> None:
    state.etf_code = portfolio.etf_code
    state.last_light = portfolio.dca_light
    state.last_label = portfolio.dca_label
    state.last_action = portfolio.dca_action
    state.last_budget_multiplier = _to_decimal(portfolio.dca_budget_multiplier)
    state.last_trigger_price = _to_decimal(portfolio.dca_next_trigger_price)
    state.last_price = _to_decimal(portfolio.current_price)
    state.last_scanned_at = now_in_utc_naive()


def _update_dca_scan_time(state: PortfolioDcaState, portfolio) -> None:
    state.etf_code = portfolio.etf_code
    state.last_scanned_at = now_in_utc_naive()


def _apply_dca_debounce(state: PortfolioDcaState, portfolio, confirm_count: int = 2) -> tuple[bool, str | None]:
    current_light = portfolio.dca_light
    if state.last_light is None:
        state.candidate_light = None
        state.candidate_confirm_count = 0
        _update_dca_state(state, portfolio)
        return False, None

    if current_light == state.last_light:
        state.candidate_light = None
        state.candidate_confirm_count = 0
        _update_dca_state(state, portfolio)
        return False, None

    if state.candidate_light == current_light:
        state.candidate_confirm_count = (state.candidate_confirm_count or 1) + 1
    else:
        state.candidate_light = current_light
        state.candidate_confirm_count = 1

    safe_confirm_count = max(1, int(confirm_count or 2))
    if (state.candidate_confirm_count or 0) >= safe_confirm_count:
        previous_light = state.last_light
        state.candidate_light = None
        state.candidate_confirm_count = 0
        _update_dca_state(state, portfolio)
        return True, f"红绿灯连续{safe_confirm_count}次确认变化：{previous_light or '-'} -> {current_light or '-'}"

    _update_dca_scan_time(state, portfolio)
    return False, f"红绿灯变化待确认：{state.last_light or '-'} -> {current_light or '-'}，{state.candidate_confirm_count or 0}/{safe_confirm_count}"


async def update_user_dca_signals(user_id: int, etf_codes: list[str] | None = None):
    """计算并持久化单个用户的红绿灯状态，只标记待通知事件，不发送通知。"""
    target_codes = {code for code in (etf_codes or []) if code}
    async with async_session_maker() as db:
        portfolios = await PortfolioService.get_with_market(
            db,
            user_id=user_id,
            compute_dca=True,
            etf_codes=sorted(target_codes) if target_codes else None,
        )
        if not portfolios:
            return []

        ids = [portfolio.id for portfolio in portfolios]
        config_result = await db.execute(select(DcaSignalConfig).where(DcaSignalConfig.id == 1))
        config = config_result.scalar_one_or_none()
        light_confirm_count = config.light_confirm_count if config else 2
        result = await db.execute(select(PortfolioDcaState).where(PortfolioDcaState.portfolio_id.in_(ids)))
        states = {state.portfolio_id: state for state in result.scalars().all()}
        events = []

        for portfolio in portfolios:
            state = states.get(portfolio.id)
            notify_key = _dca_notify_key(portfolio)
            reason = None
            is_new_state = False
            if state is None:
                state = PortfolioDcaState(
                    portfolio_id=portfolio.id,
                    user_id=user_id,
                    etf_code=portfolio.etf_code,
                )
                db.add(state)
                states[portfolio.id] = state
                is_new_state = True
            elif state.last_light != portfolio.dca_light:
                changed, debounce_reason = _apply_dca_debounce(state, portfolio, light_confirm_count)
                if changed:
                    reason = debounce_reason or "红绿灯连续2次确认变化"
                    notify_key = _dca_notify_key(portfolio)
                else:
                    reason = None
                    if debounce_reason:
                        print(f"[Scheduler] 用户 {user_id} {portfolio.etf_code} {debounce_reason}")
            else:
                state.candidate_light = None
                state.candidate_confirm_count = 0
                if _dca_changed(portfolio, state):
                    reason = "资金倍率或触发价变化"
                    _update_dca_state(state, portfolio)
                elif _dca_trigger_reached(portfolio, state):
                    reason = "到达下一触发价"
                    _update_dca_state(state, portfolio)
                else:
                    _update_dca_state(state, portfolio)

            if not is_new_state and reason and state.last_notified_key != notify_key:
                state.pending_notify_key = notify_key
                state.pending_notify_reason = reason
                events.append((portfolio, reason))
            if is_new_state:
                _update_dca_state(state, portfolio)
            state.user_id = user_id
            _add_dca_history(db, state, portfolio, user_id)

        await db.commit()
        scope = f"，范围 {sorted(target_codes)}" if target_codes else ""
        print(f"[Scheduler] 用户 {user_id} DCA红绿灯状态更新完成{scope}，待通知 {len(events)} 个")
        return events


async def update_all_dca_signals():
    print(f"[Scheduler] {now_in_shanghai()} 开始执行DCA红绿灯数据更新任务...")
    async with async_session_maker() as db:
        result = await db.execute(select(User.id).where(User.is_active == True))
        user_ids = result.scalars().all()
    if not user_ids:
        print("[Scheduler] 无活跃用户，跳过DCA红绿灯数据更新")
        return
    print(f"[Scheduler] 共 {len(user_ids)} 个活跃用户待更新DCA红绿灯数据")
    for user_id in user_ids:
        try:
            await update_user_dca_signals(user_id)
        except Exception as e:
            print(f"[Scheduler] 用户 {user_id} DCA红绿灯状态更新失败: {e}")


def _dca_state_notify_key(state: PortfolioDcaState) -> str:
    return state.pending_notify_key or f"{state.etf_code}:{state.last_light}:{state.last_budget_multiplier}:{state.last_trigger_price}"


def _format_dca_state_line(state: PortfolioDcaState, etf_name: str | None) -> str:
    meta = state.last_action or "-"
    if state.last_budget_multiplier is not None:
        meta = f"{meta} | {float(state.last_budget_multiplier):g}x"
    price = f"现价 {float(state.last_price):.3f}" if state.last_price is not None else "现价 -"
    trigger = f"触发价 {float(state.last_trigger_price):.3f}" if state.last_trigger_price is not None else "触发价 -"
    reason = state.pending_notify_reason or "定投信号变化"
    display_name = etf_name or "名称未知"
    return f"{state.etf_code} {display_name}: {state.last_label or '-'} | {meta} | {price} | {trigger} | {reason}"


async def _resolve_dca_etf_names(rows) -> dict[str, str]:
    """为 DCA 通知解析 ETF 名称，优先使用数据库，其次使用行情缓存和实时行情。"""
    name_by_code: dict[str, str] = {}
    missing_codes: list[str] = []
    for state, _, etf_info in rows:
        code = state.etf_code
        if code in name_by_code:
            continue
        name = etf_info.name if etf_info else None
        if name:
            name_by_code[code] = name
        else:
            missing_codes.append(code)

    missing_codes = list(dict.fromkeys(missing_codes))
    if not missing_codes:
        return name_by_code

    cached_quotes = await MarketService.get_cached_quotes_for_codes(missing_codes)
    for code, quote in cached_quotes.items():
        if quote.name and code not in name_by_code:
            name_by_code[code] = quote.name

    still_missing = [code for code in missing_codes if code not in name_by_code]
    if still_missing:
        quotes = await MarketService.get_quotes_for_codes(still_missing)
        for code, quote in quotes.items():
            if quote.name and code not in name_by_code:
                name_by_code[code] = quote.name

    return name_by_code


async def notify_user_dca_signals(user_id: int):
    """发送单个用户已持久化的红绿灯待通知事件，不重新计算状态。"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(PortfolioDcaState, Portfolio, EtfInfo)
            .join(Portfolio, PortfolioDcaState.portfolio_id == Portfolio.id)
            .outerjoin(EtfInfo, EtfInfo.code == PortfolioDcaState.etf_code)
            .where(
                PortfolioDcaState.user_id == user_id,
                PortfolioDcaState.pending_notify_key.is_not(None),
            )
            .order_by(PortfolioDcaState.etf_code.asc())
        )
        rows = result.all()
        if not rows:
            print(f"[Scheduler] 用户 {user_id} 无DCA红绿灯待通知事件")
            return 0

        configs = await NotificationService.get_enabled_configs(db, user_id)
        if not configs:
            print(f"[Scheduler] 用户 {user_id} 有 {len(rows)} 个DCA红绿灯待通知事件，但未启用有效通知配置")
            await db.commit()
            return 0

        grouped = defaultdict(list)
        for state, portfolio, etf_info in rows:
            grouped[state.last_light or "unknown"].append((state, portfolio, etf_info))
        name_by_code = await _resolve_dca_etf_names(rows)

        group_order = ["deep_green", "green", "yellow", "red", "unknown"]
        group_titles = {
            "deep_green": "深绿：极度低估/重点加仓",
            "green": "绿灯：允许增强定投",
            "yellow": "黄灯：观察或基础定投",
            "red": "红灯：暂停新增定投",
            "unknown": "其他信号",
        }
        lines = []
        shown_count = 0
        max_items = 12
        for light in group_order:
            items = grouped.get(light)
            if not items:
                continue
            lines.append(f"【{group_titles[light]}】")
            for state, portfolio, etf_info in items:
                if shown_count >= max_items:
                    continue
                lines.append(_format_dca_state_line(state, name_by_code.get(state.etf_code)))
                shown_count += 1
            lines.append("")
        if len(rows) > shown_count:
            lines.append(f"其余变化：{len(rows) - shown_count} 个")

        sent_count = await NotificationService.send_message_to_configs(
            db,
            configs,
            NotificationMessage(
                title="【定投红绿灯】信号变化",
                body="\n".join(line for line in lines if line is not None).strip(),
                group="ETF定投红绿灯",
            ),
        )
        if sent_count:
            for state, _, _ in rows:
                state.last_notified_key = _dca_state_notify_key(state)
                state.pending_notify_key = None
                state.pending_notify_reason = None
        await db.commit()
        print(f"[Scheduler] 用户 {user_id} DCA红绿灯通知完成，推送 {sent_count} 条，事件 {len(rows)} 个")
        return sent_count


async def notify_all_dca_signals():
    print(f"[Scheduler] {now_in_shanghai()} 开始执行DCA红绿灯通知任务...")
    async with async_session_maker() as db:
        result = await db.execute(
            select(PortfolioDcaState.user_id)
            .where(PortfolioDcaState.pending_notify_key.is_not(None))
            .distinct()
        )
        user_ids = result.scalars().all()
    if not user_ids:
        print("[Scheduler] 无DCA红绿灯待通知事件，跳过通知推送")
        return
    print(f"[Scheduler] 共 {len(user_ids)} 个用户存在DCA红绿灯待通知事件")
    for user_id in user_ids:
        try:
            await notify_user_dca_signals(user_id)
        except Exception as e:
            print(f"[Scheduler] 用户 {user_id} DCA红绿灯通知失败: {e}")


async def send_user_dca_daily_summary(user_id: int):
    """发送单个用户的红绿灯全量日报，不依赖待通知事件。"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(PortfolioDcaState, Portfolio, EtfInfo)
            .join(Portfolio, PortfolioDcaState.portfolio_id == Portfolio.id)
            .outerjoin(EtfInfo, EtfInfo.code == PortfolioDcaState.etf_code)
            .where(PortfolioDcaState.user_id == user_id)
            .order_by(PortfolioDcaState.etf_code.asc())
        )
        rows = result.all()
        if not rows:
            print(f"[Scheduler] 用户 {user_id} 无DCA红绿灯状态，跳过日报")
            return 0

        configs = await NotificationService.get_enabled_configs(db, user_id)
        if not configs:
            print(f"[Scheduler] 用户 {user_id} 有 {len(rows)} 个DCA红绿灯状态，但未启用有效通知配置")
            await db.commit()
            return 0

        grouped = defaultdict(list)
        for state, portfolio, etf_info in rows:
            grouped[state.last_light or "unknown"].append((state, portfolio, etf_info))
        name_by_code = await _resolve_dca_etf_names(rows)

        group_order = ["deep_green", "green", "yellow", "red", "unknown"]
        group_titles = {
            "deep_green": "深绿：极度低估/重点加仓",
            "green": "绿灯：允许增强定投",
            "yellow": "黄灯：观察或基础定投",
            "red": "红灯：暂停新增定投",
            "unknown": "其他/未识别",
        }
        lines = [f"扫描时间：{now_in_shanghai().strftime('%Y-%m-%d %H:%M')}"]
        shown_count = 0
        max_items = 30
        for light in group_order:
            items = grouped.get(light)
            if not items:
                continue
            lines.append("")
            lines.append(f"【{group_titles[light]}】{len(items)} 个")
            for state, portfolio, etf_info in items:
                if shown_count >= max_items:
                    continue
                lines.append(_format_dca_state_line(state, name_by_code.get(state.etf_code)))
                shown_count += 1
        if len(rows) > shown_count:
            lines.append("")
            lines.append(f"其余持仓：{len(rows) - shown_count} 个")

        sent_count = await NotificationService.send_message_to_configs(
            db,
            configs,
            NotificationMessage(
                title="【定投红绿灯日报】全量概览",
                body="\n".join(lines).strip(),
                group="ETF定投红绿灯日报",
            ),
        )
        await db.commit()
        print(f"[Scheduler] 用户 {user_id} DCA红绿灯日报完成，推送 {sent_count} 条，状态 {len(rows)} 个")
        return sent_count


async def send_all_dca_daily_summaries():
    print(f"[Scheduler] {now_in_shanghai()} 开始执行DCA红绿灯日报任务...")
    async with async_session_maker() as db:
        result = await db.execute(
            select(PortfolioDcaState.user_id)
            .distinct()
        )
        user_ids = result.scalars().all()
    if not user_ids:
        print("[Scheduler] 无DCA红绿灯状态，跳过日报推送")
        return
    print(f"[Scheduler] 共 {len(user_ids)} 个用户待发送DCA红绿灯日报")
    for user_id in user_ids:
        try:
            await send_user_dca_daily_summary(user_id)
        except Exception as e:
            print(f"[Scheduler] 用户 {user_id} DCA红绿灯日报失败: {e}")


async def analyze_user_portfolios(user_id: int):
    """执行单个用户的收盘持仓分析"""
    async with async_session_maker() as db:
        portfolios = await PortfolioService.get_with_market(db, user_id=user_id)

        if not portfolios:
            print(f"[Scheduler] 用户 {user_id} 无持仓数据，跳过收盘分析")
            return []

        etf_codes = [p.etf_code for p in portfolios]
        print(f"[Scheduler] 用户 {user_id} 共 {len(etf_codes)} 个持仓待执行收盘分析: {etf_codes}")

        results = await AdvisorService.generate_advice(
            db,
            etf_codes,
            user_id=user_id,
            analysis_mode="scheduled",
        )
        await db.commit()
        print(f"[Scheduler] 用户 {user_id} 收盘分析完成，生成 {len(results)} 条建议")

        for r in results:
            print(f"  - user={user_id} {r.etf_code}: {r.advice_type} (置信度 {r.confidence}%)")

        if results:
            print(f"[Scheduler] 开始发送用户 {user_id} 的收盘分析推送通知...")
            sent_count = await NotificationService.send_user_advice_notifications(db, user_id, results)
            await db.commit()
            print(f"[Scheduler] 用户 {user_id} 收盘分析推送通知发送完成，成功发送 {sent_count} 条")

        return results


async def analyze_user_account(user_id: int):
    """执行单个用户的本周账户分析并推送摘要"""
    async with async_session_maker() as db:
        user = await db.get(User, user_id)
        if not user or not user.is_active:
            print(f"[Scheduler] 用户 {user_id} 不存在或已禁用，跳过本周账户分析")
            return None

        # user.account_balance 表示前端维护的可用资金，不是总资产。
        available_cash = (
            PortfolioService._finite_float(user.account_balance)
            if user.account_balance is not None
            else 0.0
        )
        
        analysis = await AdvisorService.generate_account_analysis(
            db,
            user_id=user_id,
            account_balance=available_cash,
            analysis_mode="scheduled",
        )
        await db.commit()
        print(f"[Scheduler] 用户 {user_id} 本周账户分析完成，风险等级 {analysis.risk_level}")

        pushed = await NotificationService.send_user_account_analysis_notification(
            db,
            user_id,
            summary=analysis.summary,
            position_advice=analysis.position_advice,
            rebalance_advice=analysis.rebalance_advice,
            risk_level=analysis.risk_level,
            key_actions=analysis.key_actions,
            confidence=analysis.confidence,
        )
        await db.commit()
        print(
            f"[Scheduler] 用户 {user_id} 本周账户分析推送"
            f"{'成功' if pushed else '未发送或失败'}"
        )
        return analysis


async def analyze_all_portfolios():
    """执行所有活跃用户的收盘持仓分析"""
    print(f"[Scheduler] {now_in_shanghai()} 开始执行收盘持仓分析定时任务...")

    async with async_session_maker() as db:
        try:
            result = await db.execute(select(User.id).where(User.is_active == True))
            user_ids = result.scalars().all()

            if not user_ids:
                print("[Scheduler] 无活跃用户，跳过收盘分析")
                return

            print(f"[Scheduler] 共 {len(user_ids)} 个活跃用户待执行收盘分析")
        except Exception as e:
            print(f"[Scheduler] 加载用户列表失败: {e}")
            return

    for user_id in user_ids:
        try:
            await analyze_user_portfolios(user_id)
        except Exception as e:
            print(f"[Scheduler] 用户 {user_id} 收盘分析任务执行失败: {e}")


async def analyze_all_accounts():
    """执行所有活跃用户的本周账户分析并推送摘要"""
    print(f"[Scheduler] {now_in_shanghai()} 开始执行本周账户分析定时任务...")

    async with async_session_maker() as db:
        try:
            result = await db.execute(select(User.id).where(User.is_active == True))
            user_ids = result.scalars().all()

            if not user_ids:
                print("[Scheduler] 无活跃用户，跳过本周账户分析")
                return

            print(f"[Scheduler] 共 {len(user_ids)} 个活跃用户待执行本周账户分析")
        except Exception as e:
            print(f"[Scheduler] 加载用户列表失败: {e}")
            return

    for user_id in user_ids:
        try:
            await analyze_user_account(user_id)
        except Exception as e:
            print(f"[Scheduler] 用户 {user_id} 本周账户分析任务执行失败: {e}")


async def refresh_market_quotes():
    """轻刷新：定时刷新活跃用户持仓和自选品种的最新行情快照。"""
    print(f"[Scheduler] {now_in_shanghai()} 开始执行行情轻刷新任务...")

    codes = await _get_active_market_refresh_codes("行情轻刷新")
    if not codes:
        return

    print(f"[Scheduler] 共 {len(codes)} 只品种待轻刷新行情")
    quotes = await MarketService.refresh_quotes(codes)
    print(f"[Scheduler] 行情轻刷新完成，成功缓存 {len(quotes)} 只品种")


async def _refresh_one_market_history(code: str, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        last_error = None
        for attempt in range(1, 3):
            try:
                data = await MarketService.get_history_kline(code, days=60, prefer_cache=False)
                if not data:
                    last_error = "无数据"
                    print(f"[Scheduler] 行情重刷新无数据: {code}, 第 {attempt}/2 次")
                else:
                    latest = data[-1]
                    total_rows = len(data)
                    missing_amount = sum(1 for item in data if item.amount is None)
                    amount_complete_rate = ((total_rows - missing_amount) / total_rows * 100) if total_rows else 0.0
                    amount_state = "含成交额" if latest.amount is not None else "最新缺成交额"
                    if missing_amount:
                        amount_state = f"{amount_state}, 缺 {missing_amount}/{total_rows} 条"
                    print(
                        f"[Scheduler] 行情重刷新完成: {code}, {total_rows} 条, 最新 {latest.trade_date}, "
                        f"{amount_state}, 成交额完整率 {amount_complete_rate:.1f}%"
                    )
                    return {
                        "code": code,
                        "success": True,
                        "missing_amount": missing_amount,
                        "amount_complete_rate": amount_complete_rate,
                        "error": None,
                    }
            except Exception as e:
                last_error = str(e)
                print(f"[Scheduler] 行情重刷新失败: {code}, 第 {attempt}/2 次, {e}")

            if attempt == 1:
                await asyncio.sleep(1)

        return {
            "code": code,
            "success": False,
            "missing_amount": 0,
            "amount_complete_rate": 0.0,
            "error": last_error or "未知错误",
        }


async def refresh_market_history():
    """重刷新：刷新近 60 日 K 线和成交额，供技术指标与交易指示使用。"""
    print(f"[Scheduler] {now_in_shanghai()} 开始执行行情重刷新任务...")

    codes = await _get_active_portfolio_codes("行情重刷新")
    if not codes:
        return

    semaphore = asyncio.Semaphore(4)
    results = await asyncio.gather(*(_refresh_one_market_history(code, semaphore) for code in codes))
    success_count = sum(1 for item in results if item["success"])
    failed = [item for item in results if not item["success"]]
    missing_amount = [item for item in results if item["success"] and item["missing_amount"]]
    low_amount_complete = [
        item for item in results
        if item["success"] and item["amount_complete_rate"] < 80.0
    ]

    if failed:
        failed_text = ", ".join(f"{item['code']}({item['error']})" for item in failed[:10])
        more = f" 等 {len(failed)} 只" if len(failed) > 10 else ""
        print(f"[Scheduler] 行情重刷新失败明细: {failed_text}{more}")
    if missing_amount:
        missing_text = ", ".join(f"{item['code']}缺{item['missing_amount']}条" for item in missing_amount[:10])
        more = f" 等 {len(missing_amount)} 只" if len(missing_amount) > 10 else ""
        print(f"[Scheduler] 行情重刷新成交额缺失明细: {missing_text}{more}")
    if low_amount_complete:
        low_text = ", ".join(
            f"{item['code']}完整率{item['amount_complete_rate']:.1f}%"
            for item in low_amount_complete[:10]
        )
        more = f" 等 {len(low_amount_complete)} 只" if len(low_amount_complete) > 10 else ""
        print(f"[Scheduler] 行情重刷新成交额完整率低于80%: {low_text}{more}")

    print(
        f"[Scheduler] 行情重刷新完成，成功 {success_count}/{len(codes)} 只ETF，"
        f"失败 {len(failed)} 只，成交额缺失 {len(missing_amount)} 只，"
        f"完整率低于80% {len(low_amount_complete)} 只"
    )


async def refresh_etf_profiles():
    """定时刷新活跃用户持仓涉及的 ETF 资料缓存和数据库快照"""
    current_year = now_in_shanghai().year
    print(f"[Scheduler] {now_in_shanghai()} 开始执行ETF资料刷新任务...")

    async with async_session_maker() as db:
        try:
            result = await db.execute(
                select(Portfolio.etf_code)
                .join(User, Portfolio.user_id == User.id)
                .where(User.is_active == True)
                .distinct()
            )
            codes = sorted({code for code in result.scalars().all() if code})
            if not codes:
                print("[Scheduler] 无持仓ETF，跳过ETF资料刷新")
                return

            print(f"[Scheduler] 共 {len(codes)} 只ETF待刷新资料")
        except Exception as e:
            print(f"[Scheduler] 加载ETF列表失败: {e}")
            return

        success_count = 0
        for code in codes:
            try:
                profile = await MarketService.get_etf_profile(
                    code,
                    year=current_year,
                    session=db,
                    force_refresh=True,
                )
                await db.commit()
                if not profile.get("errors"):
                    success_count += 1
                print(f"[Scheduler] ETF资料刷新完成: {code}")
            except Exception as e:
                await db.rollback()
                print(f"[Scheduler] ETF资料刷新失败: {code}, {e}")

    print(f"[Scheduler] ETF资料刷新完成，成功刷新 {success_count}/{len(codes)} 只ETF")


async def refresh_industry_fundamentals():
    """定时刷新行业 ROE、利润增速和盈利预测缓存。"""
    print(f"[Scheduler] {now_in_shanghai()} 开始执行行业基本面刷新任务...")
    try:
        result = await IndustryFundamentalService.refresh_all()
        print(f"[Scheduler] 行业基本面刷新完成，成功刷新 {len(result)} 个行业")
    except Exception as e:
        print(f"[Scheduler] 行业基本面刷新任务失败: {e}")


async def refresh_macro_data():
    """定时采集宏观指标并生成自动美林时钟状态。"""
    print(f"[Scheduler] {now_in_shanghai()} 开始执行宏观数据刷新任务...")
    async with async_session_maker() as db:
        try:
            state, indicators, errors = await MacroDataService.refresh(db)
            if not indicators:
                await db.rollback()
                print(f"[Scheduler] 宏观数据刷新失败: {errors}")
                return
            await db.commit()
            print(
                f"[Scheduler] 宏观数据刷新完成，指标 {len(indicators)} 个，"
                f"阶段 {state.cycle_phase if state else '-'}，错误 {len(errors)} 个"
            )
        except Exception as e:
            await db.rollback()
            print(f"[Scheduler] 宏观数据刷新任务失败: {e}")


def setup_scheduler():
    """配置定时任务"""
    # 工作日收盘后 15:05 执行持仓分析
    scheduler.add_job(
        analyze_all_portfolios,
        trigger=CronTrigger(
            day_of_week='mon-fri',
            hour=15,
            minute=5,
            timezone='Asia/Shanghai'
        ),
        id='daily_analysis',
        name='每日收盘持仓分析',
        replace_existing=True
    )

    # 每周五收盘后 15:10 执行账户分析并推送
    scheduler.add_job(
        analyze_all_accounts,
        trigger=CronTrigger(
            day_of_week='fri',
            hour=15,
            minute=10,
            timezone='Asia/Shanghai'
        ),
        id='weekly_account_analysis',
        name='每周收盘账户分析',
        replace_existing=True
    )

    # 轻刷新：盘中高频刷新最新行情快照，避免频繁拉取历史K线。
    market_refresh_trigger = OrTrigger([
        CronTrigger(day_of_week='mon-fri', hour=9, minute='15-59/5', timezone='Asia/Shanghai'),
        CronTrigger(day_of_week='mon-fri', hour=10, minute='*/5', timezone='Asia/Shanghai'),
        CronTrigger(day_of_week='mon-fri', hour=11, minute='0-30/5', timezone='Asia/Shanghai'),
        CronTrigger(day_of_week='mon-fri', hour='13,14', minute='*/5', timezone='Asia/Shanghai'),
        CronTrigger(day_of_week='mon-fri', hour=15, minute=0, timezone='Asia/Shanghai'),
    ])
    scheduler.add_job(
        refresh_market_quotes,
        trigger=market_refresh_trigger,
        id='market_refresh',
        name='行情轻刷新',
        replace_existing=True
    )

    # 重刷新：低频刷新 60 日 K 线和成交额，供技术指标、交易指示和红绿灯使用。
    market_history_refresh_trigger = OrTrigger([
        CronTrigger(day_of_week='mon-fri', hour=10, minute=35, timezone='Asia/Shanghai'),
        CronTrigger(day_of_week='mon-fri', hour=14, minute=35, timezone='Asia/Shanghai'),
        CronTrigger(day_of_week='mon-fri', hour=15, minute=2, timezone='Asia/Shanghai'),
    ])
    scheduler.add_job(
        refresh_market_history,
        trigger=market_history_refresh_trigger,
        id='market_history_refresh',
        name='行情重刷新',
        replace_existing=True
    )

    # 工作日 10:30 盘中轻量扫描，14:40 尾盘主扫描；均会持久化红绿灯状态与历史快照。
    dca_signal_update_trigger = OrTrigger([
        CronTrigger(day_of_week='mon-fri', hour=10, minute=30, timezone='Asia/Shanghai'),
        CronTrigger(day_of_week='mon-fri', hour=14, minute=40, timezone='Asia/Shanghai'),
    ])
    scheduler.add_job(
        update_all_dca_signals,
        trigger=dca_signal_update_trigger,
        id='dca_signal_update',
        name='定投红绿灯数据更新',
        replace_existing=True
    )

    # 工作日 14:45 发送已持久化的红绿灯变化通知。
    scheduler.add_job(
        notify_all_dca_signals,
        trigger=CronTrigger(
            day_of_week='mon-fri',
            hour=14,
            minute=45,
            timezone='Asia/Shanghai'
        ),
        id='dca_signal_notify',
        name='定投红绿灯变化通知',
        replace_existing=True
    )

    # 工作日 14:46 发送红绿灯全量日报概览。
    scheduler.add_job(
        send_all_dca_daily_summaries,
        trigger=CronTrigger(
            day_of_week='mon-fri',
            hour=14,
            minute=46,
            timezone='Asia/Shanghai'
        ),
        id='dca_signal_daily_summary',
        name='定投红绿灯日报',
        replace_existing=True
    )

    # 工作日盘前和午后刷新 ETF 资料快照，供持仓详情页直接读取缓存。
    scheduler.add_job(
        refresh_etf_profiles,
        trigger=CronTrigger(
            day_of_week='mon-fri',
            hour='9,13',
            minute=15,
            timezone='Asia/Shanghai'
        ),
        id='etf_profile_refresh',
        name='ETF资料缓存刷新',
        replace_existing=True
    )


    # 每周一盘前刷新行业基本面低频数据。
    scheduler.add_job(
        refresh_industry_fundamentals,
        trigger=CronTrigger(
            day_of_week='mon',
            hour=8,
            minute=10,
            timezone='Asia/Shanghai'
        ),
        id='industry_fundamental_refresh',
        name='行业基本面刷新',
        replace_existing=True
    )

    # 每周一盘前刷新低频宏观指标和美林时钟状态。
    scheduler.add_job(
        refresh_macro_data,
        trigger=CronTrigger(
            day_of_week='mon',
            hour=8,
            minute=30,
            timezone='Asia/Shanghai'
        ),
        id='macro_data_refresh',
        name='宏观数据刷新',
        replace_existing=True
    )

    print("[Scheduler] 定时任务已配置: 工作日 15:05 自动执行收盘持仓分析")
    print("[Scheduler] 定时任务已配置: 每周五 15:10 自动执行本周账户分析并推送")
    print("[Scheduler] 定时任务已配置: A股交易时段每5分钟自动轻刷新行情快照，15:00收盘补刷一次")
    print("[Scheduler] 定时任务已配置: 工作日 10:35、14:35、15:02 自动重刷新60日K线和成交额")
    print("[Scheduler] 定时任务已配置: 工作日 09:15、13:15 自动刷新ETF资料缓存")
    print("[Scheduler] 定时任务已配置: 工作日 14:40 自动更新定投红绿灯数据")
    print("[Scheduler] 定时任务已配置: 工作日 14:45 自动推送定投红绿灯变化通知")
    print("[Scheduler] 定时任务已配置: 工作日 14:46 自动推送定投红绿灯日报")
    print("[Scheduler] 定时任务已配置: 每周一 08:10 自动刷新行业基本面")
    print("[Scheduler] 定时任务已配置: 每周一 08:30 自动刷新宏观指标和美林时钟")


def start_scheduler():
    """启动调度器"""
    setup_scheduler()
    scheduler.start()
    print("[Scheduler] 调度器已启动")


def shutdown_scheduler():
    """关闭调度器"""
    scheduler.shutdown()
    print("[Scheduler] 调度器已关闭")
