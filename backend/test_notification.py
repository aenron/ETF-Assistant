"""测试Bark通知"""
import asyncio
from config import settings
from services.notification_service import BarkNotifier, NotificationMessage


async def test_bark():
    print("=" * 50)
    print("测试 Bark 通知")
    print("=" * 50)
    print(f"Bark Key: {settings.bark_key[:10]}..." if settings.bark_key else "未配置")
    print(f"Bark URL: {settings.bark_url}")
    print()
    
    if not settings.bark_key:
        print("错误: 请先在 .env 中配置 BARK_KEY")
        return
    
    notifier = BarkNotifier(settings.bark_key, settings.bark_url)
    
    # 测试简单通知
    print("发送测试通知...")
    result = await notifier.send(NotificationMessage(
        title="ETF投资助手 - 测试",
        body="这是一条测试通知，如果您收到此消息，说明Bark配置正确！",
        group="测试"
    ))
    
    if result:
        print("✓ 测试通知发送成功")
    else:
        print("✗ 测试通知发送失败")
    
    print()
    
    # 测试投资建议通知
    print("发送模拟投资建议通知...")
    result2 = await notifier.send_advice(
        etf_code="510300",
        etf_name="沪深300ETF",
        advice_type="hold",
        reason="技术面显示MA5上穿MA10形成金叉，RSI处于50中性区间，建议继续持有观望。",
        confidence=75
    )
    
    if result2:
        print("✓ 投资建议通知发送成功")
    else:
        print("✗ 投资建议通知发送失败")
    
    print()
    print("=" * 50)
    print("测试完成")


if __name__ == "__main__":
    asyncio.run(test_bark())
