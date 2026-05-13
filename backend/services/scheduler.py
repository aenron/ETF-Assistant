"""定时任务服务"""
import asyncio
from inspect import iscoroutinefunction
from sqlalchemy import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from database import async_session_maker
from models.portfolio import Portfolio
from models.scheduler_job_config import SchedulerJobConfig
from models.user import User
from services.advisor_service import AdvisorService
from services.market_service import MarketService
from services.portfolio_service import PortfolioService
from services.notification_service import NotificationService
from utils.timezone import now_in_shanghai


scheduler = AsyncIOScheduler()


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

        # 计算实际可用现金：账户总金额 - 持仓市值
        portfolios = await PortfolioService.get_with_market(db, user_id=user_id)
        summary = PortfolioService.build_summary_from_portfolios(portfolios)
        total_market_value = summary.total_market_value
        
        # 如果用户设置了账户总金额，计算可用现金；否则为0
        user_total_balance = float(user.account_balance) if user.account_balance else 0.0
        available_cash = max(0.0, user_total_balance - total_market_value)
        
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
    """定时刷新活跃用户持仓涉及的行情缓存"""
    print(f"[Scheduler] {now_in_shanghai()} 开始执行行情刷新任务...")

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
                print("[Scheduler] 无持仓ETF，跳过行情刷新")
                return

            print(f"[Scheduler] 共 {len(codes)} 只ETF待刷新行情")
        except Exception as e:
            print(f"[Scheduler] 加载ETF列表失败: {e}")
            return

    quotes = await MarketService.refresh_quotes(codes)
    print(f"[Scheduler] 行情刷新完成，成功缓存 {len(quotes)} 只ETF")


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

    # A股集合竞价开始后每5分钟刷新一次行情缓存。用一个组合触发器保持任务列表简洁。
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
        name='行情缓存刷新',
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

    print("[Scheduler] 定时任务已配置: 工作日 15:05 自动执行收盘持仓分析")
    print("[Scheduler] 定时任务已配置: 每周五 15:10 自动执行本周账户分析并推送")
    print("[Scheduler] 定时任务已配置: A股集合竞价开始后每5分钟自动刷新行情缓存，15:00收盘补刷一次")
    print("[Scheduler] 定时任务已配置: 工作日 09:15、13:15 自动刷新ETF资料缓存")


def start_scheduler():
    """启动调度器"""
    setup_scheduler()
    scheduler.start()
    print("[Scheduler] 调度器已启动")


def shutdown_scheduler():
    """关闭调度器"""
    scheduler.shutdown()
    print("[Scheduler] 调度器已关闭")
