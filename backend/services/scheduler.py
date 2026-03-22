"""定时任务服务"""
from datetime import datetime
from sqlalchemy import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import async_session_maker
from models.portfolio import Portfolio
from models.user import User
from services.advisor_service import AdvisorService
from services.market_service import MarketService
from services.portfolio_service import PortfolioService
from services.notification_service import NotificationService


scheduler = AsyncIOScheduler()


async def analyze_user_portfolios(user_id: int):
    """分析单个用户的持仓"""
    async with async_session_maker() as db:
        portfolios = await PortfolioService.get_with_market(db, user_id=user_id)

        if not portfolios:
            print(f"[Scheduler] 用户 {user_id} 无持仓数据，跳过分析")
            return []

        etf_codes = [p.etf_code for p in portfolios]
        print(f"[Scheduler] 用户 {user_id} 共 {len(etf_codes)} 个持仓待分析: {etf_codes}")

        results = await AdvisorService.generate_advice(db, etf_codes, user_id=user_id)
        await db.commit()
        print(f"[Scheduler] 用户 {user_id} 分析完成，生成 {len(results)} 条建议")

        for r in results:
            print(f"  - user={user_id} {r.etf_code}: {r.advice_type} (置信度 {r.confidence}%)")

        if results:
            print(f"[Scheduler] 开始发送用户 {user_id} 的推送通知...")
            for r in results:
                await NotificationService.send_advice_notification(
                    etf_code=r.etf_code,
                    etf_name=r.etf_name or "",
                    advice_type=r.advice_type,
                    reason=r.reason,
                    confidence=r.confidence
                )
            print(f"[Scheduler] 用户 {user_id} 推送通知发送完成")

        return results


async def analyze_user_account(user_id: int):
    """分析单个用户的账户并推送摘要"""
    async with async_session_maker() as db:
        user = await db.get(User, user_id)
        if not user or not user.is_active:
            print(f"[Scheduler] 用户 {user_id} 不存在或已禁用，跳过账户分析")
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
        )
        await db.commit()
        print(f"[Scheduler] 用户 {user_id} 账户分析完成，风险等级 {analysis.risk_level}")

        pushed = await NotificationService.send_account_analysis_notification(
            summary=analysis.summary,
            position_advice=analysis.position_advice,
            rebalance_advice=analysis.rebalance_advice,
            risk_level=analysis.risk_level,
            key_actions=analysis.key_actions,
            confidence=analysis.confidence,
        )
        print(
            f"[Scheduler] 用户 {user_id} 账户分析推送"
            f"{'成功' if pushed else '未发送或失败'}"
        )
        return analysis


async def analyze_all_portfolios():
    """分析所有活跃用户的持仓"""
    print(f"[Scheduler] {datetime.now()} 开始执行定时分析任务...")

    async with async_session_maker() as db:
        try:
            result = await db.execute(select(User.id).where(User.is_active == True))
            user_ids = result.scalars().all()

            if not user_ids:
                print("[Scheduler] 无活跃用户，跳过分析")
                return

            print(f"[Scheduler] 共 {len(user_ids)} 个活跃用户待分析")
        except Exception as e:
            print(f"[Scheduler] 加载用户列表失败: {e}")
            return

    for user_id in user_ids:
        try:
            await analyze_user_portfolios(user_id)
        except Exception as e:
            print(f"[Scheduler] 用户 {user_id} 分析任务执行失败: {e}")


async def analyze_all_accounts():
    """分析所有活跃用户的账户并推送摘要"""
    print(f"[Scheduler] {datetime.now()} 开始执行账户分析定时任务...")

    async with async_session_maker() as db:
        try:
            result = await db.execute(select(User.id).where(User.is_active == True))
            user_ids = result.scalars().all()

            if not user_ids:
                print("[Scheduler] 无活跃用户，跳过账户分析")
                return

            print(f"[Scheduler] 共 {len(user_ids)} 个活跃用户待执行账户分析")
        except Exception as e:
            print(f"[Scheduler] 加载用户列表失败: {e}")
            return

    for user_id in user_ids:
        try:
            await analyze_user_account(user_id)
        except Exception as e:
            print(f"[Scheduler] 用户 {user_id} 账户分析任务执行失败: {e}")


async def refresh_market_quotes():
    """定时刷新活跃用户持仓涉及的行情缓存"""
    print(f"[Scheduler] {datetime.now()} 开始执行行情刷新任务...")

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


def setup_scheduler():
    """配置定时任务"""
    # 工作日早9点执行个股持仓分析
    scheduler.add_job(
        analyze_all_portfolios,
        trigger=CronTrigger(
            day_of_week='mon-fri',
            hour=9,
            minute=0,
            timezone='Asia/Shanghai'
        ),
        id='daily_analysis',
        name='每日持仓分析',
        replace_existing=True
    )

    # 每周一早9点执行账户分析并推送
    scheduler.add_job(
        analyze_all_accounts,
        trigger=CronTrigger(
            day_of_week='mon',
            hour=9,
            minute=0,
            timezone='Asia/Shanghai'
        ),
        id='weekly_account_analysis',
        name='每周账户分析',
        replace_existing=True
    )

    # A股开盘时段每30分钟刷新一次行情缓存
    for hour, minute in [(9, 30), (10, 0), (10, 30), (11, 0), (13, 0), (13, 30), (14, 0), (14, 30)]:
        scheduler.add_job(
            refresh_market_quotes,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=hour,
                minute=minute,
                timezone='Asia/Shanghai'
            ),
            id=f'market_refresh_{hour}_{minute}',
            name=f'行情缓存刷新 {hour:02d}:{minute:02d}',
            replace_existing=True
        )

    print("[Scheduler] 定时任务已配置: 工作日早9点自动分析持仓")
    print("[Scheduler] 定时任务已配置: 每周一早9点自动执行账户分析并推送")
    print("[Scheduler] 定时任务已配置: 开盘时段每30分钟自动刷新行情缓存")


def start_scheduler():
    """启动调度器"""
    setup_scheduler()
    scheduler.start()
    print("[Scheduler] 调度器已启动")


def shutdown_scheduler():
    """关闭调度器"""
    scheduler.shutdown()
    print("[Scheduler] 调度器已关闭")
