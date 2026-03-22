"""测试账户分析 Bark 推送"""
import asyncio

from config import settings
from services.notification_service import NotificationService


async def test_account_analysis_notification():
    print("=" * 50)
    print("测试账户分析 Bark 推送")
    print("=" * 50)
    print(f"Bark Key: {settings.bark_key[:10]}..." if settings.bark_key else "未配置")
    print(f"Bark URL: {settings.bark_url}")
    print()

    if not settings.bark_key:
        print("错误: 请先在 .env 中配置 BARK_KEY")
        return

    print("发送模拟账户分析通知...")
    result = await NotificationService.send_account_analysis_notification(
        summary="当前账户整体仓位适中，但行业集中度偏高，短期需要关注波动风险。",
        position_advice="建议暂不继续加仓，保留部分现金等待更明确的加仓时机。",
        rebalance_advice="适当降低单一行业ETF权重，逐步提升宽基ETF占比，改善组合分散度。",
        risk_level="medium",
        key_actions=[
            "将高波动行业ETF仓位下调至组合的20%以内",
            "优先分批增配宽基ETF而非追涨主题ETF",
            "保留10%-15%现金用于后续回撤时再配置",
        ],
        confidence=82,
    )

    if result:
        print("✓ 账户分析通知发送成功")
    else:
        print("✗ 账户分析通知发送失败")

    print()
    print("=" * 50)
    print("测试完成")


if __name__ == "__main__":
    asyncio.run(test_account_analysis_notification())
