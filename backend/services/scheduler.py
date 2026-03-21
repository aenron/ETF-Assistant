"""定时任务服务"""
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import async_session_maker
from services.advisor_service import AdvisorService
from services.portfolio_service import PortfolioService


scheduler = AsyncIOScheduler()


async def analyze_all_portfolios():
    """分析所有持仓"""
    print(f"[Scheduler] {datetime.now()} 开始执行定时分析任务...")
    
    async with async_session_maker() as db:
        try:
            # 获取所有持仓
            portfolios = await PortfolioService.get_with_market(db, user_id=1)  # 定时任务使用默认用户
            
            if not portfolios:
                print("[Scheduler] 无持仓数据，跳过分析")
                return
            
            etf_codes = [p.etf_code for p in portfolios]
            print(f"[Scheduler] 共 {len(etf_codes)} 个持仓待分析: {etf_codes}")
            
            # 批量生成建议
            results = await AdvisorService.generate_advice(db, etf_codes)
            
            print(f"[Scheduler] 分析完成，生成 {len(results)} 条建议")
            
            for r in results:
                print(f"  - {r.etf_code}: {r.advice_type} (置信度 {r.confidence}%)")
                
        except Exception as e:
            print(f"[Scheduler] 分析任务执行失败: {e}")


def setup_scheduler():
    """配置定时任务"""
    # 工作日早9点执行 (周一到周五 9:00)
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
    
    print("[Scheduler] 定时任务已配置: 工作日早9点自动分析持仓")


def start_scheduler():
    """启动调度器"""
    setup_scheduler()
    scheduler.start()
    print("[Scheduler] 调度器已启动")


def shutdown_scheduler():
    """关闭调度器"""
    scheduler.shutdown()
    print("[Scheduler] 调度器已关闭")
