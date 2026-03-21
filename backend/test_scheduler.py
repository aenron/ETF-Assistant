"""测试定时任务"""
import asyncio
from database import async_session_maker
from services.scheduler import analyze_all_portfolios


async def main():
    print("=" * 50)
    print("手动执行定时分析任务测试")
    print("=" * 50)
    
    await analyze_all_portfolios()
    
    print("=" * 50)
    print("测试完成")


if __name__ == "__main__":
    asyncio.run(main())
