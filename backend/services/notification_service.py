"""通知服务"""
import httpx
from typing import Optional, List
from dataclasses import dataclass

from config import settings


@dataclass
class NotificationMessage:
    """通知消息"""
    title: str
    body: str
    group: Optional[str] = None
    icon: Optional[str] = None
    url: Optional[str] = None


class BarkNotifier:
    """Bark推送服务
    
    API文档: https://bark.day.app/#/tutorial
    
    使用方式:
    - 推送内容: https://api.day.app/{key}/{title}/{body}
    - 完整参数: https://api.day.app/{key}/{title}/{body}?group={group}&icon={icon}&url={url}
    """
    
    def __init__(self, key: str, base_url: str = "https://api.day.app"):
        self.key = key
        self.base_url = base_url.rstrip("/")
    
    async def send(self, message: NotificationMessage) -> bool:
        """发送推送通知"""
        if not self.key:
            print("[Bark] 未配置Bark Key，跳过推送")
            return False
        
        url = f"{self.base_url}/{self.key}"
        
        # 构建请求体 (POST方式，支持更多参数)
        payload = {
            "title": message.title,
            "body": message.body,
            "group": message.group,
        }
        
        if message.icon:
            payload["icon"] = message.icon
        if message.url:
            payload["url"] = message.url
        
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json=payload)
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("code") == 200:
                        print(f"[Bark] 推送成功: {message.title}")
                        return True
                    else:
                        print(f"[Bark] 推送失败: {result.get('message', '未知错误')}")
                        return False
                else:
                    print(f"[Bark] 推送失败: HTTP {response.status_code}")
                    return False
                    
        except Exception as e:
            print(f"[Bark] 推送异常: {e}")
            return False
    
    async def send_advice(self, etf_code: str, etf_name: str, advice_type: str, 
                          reason: str, confidence: int) -> bool:
        """发送投资建议通知"""
        advice_labels = {
            "buy": "买入",
            "sell": "卖出",
            "hold": "持有",
            "add": "加仓",
            "reduce": "减仓"
        }
        
        label = advice_labels.get(advice_type, advice_type)
        title = f"【{label}】{etf_code} {etf_name or ''}"
        body = f"置信度: {confidence}%\n\n{reason}"
        
        message = NotificationMessage(
            title=title,
            body=body,
            group="ETF投资建议",
        )
        
        return await self.send(message)


class NotificationService:
    """通知服务"""
    
    _bark: Optional[BarkNotifier] = None
    
    @classmethod
    def get_bark(cls) -> Optional[BarkNotifier]:
        """获取Bark通知器"""
        if cls._bark is None and settings.bark_key:
            cls._bark = BarkNotifier(settings.bark_key, settings.bark_url)
        return cls._bark
    
    @classmethod
    async def send_advice_notification(cls, etf_code: str, etf_name: str,
                                       advice_type: str, reason: str, 
                                       confidence: int) -> bool:
        """发送投资建议通知"""
        bark = cls.get_bark()
        if bark:
            return await bark.send_advice(etf_code, etf_name, advice_type, reason, confidence)
        return False

    @classmethod
    async def send_account_analysis_notification(
        cls,
        summary: str,
        position_advice: str,
        rebalance_advice: str,
        risk_level: str,
        key_actions: List[str],
        confidence: float,
    ) -> bool:
        """发送账户分析通知"""
        bark = cls.get_bark()
        if not bark:
            return False

        risk_labels = {
            "low": "低风险",
            "medium": "中风险",
            "high": "高风险",
        }
        risk_text = risk_labels.get(risk_level, risk_level)
        actions_text = "\n".join(
            f"{index + 1}. {action}" for index, action in enumerate(key_actions[:3])
        ) or "暂无关键操作"
        body = (
            f"风险等级: {risk_text}\n"
            f"置信度: {confidence:.0f}%\n\n"
            f"总体判断:\n{summary}\n\n"
            f"仓位建议:\n{position_advice}\n\n"
            f"调仓建议:\n{rebalance_advice}\n\n"
            f"关键操作:\n{actions_text}"
        )

        message = NotificationMessage(
            title="【账户分析】每周投资建议",
            body=body,
            group="ETF账户分析",
        )
        return await bark.send(message)
    
    @classmethod
    async def send_batch_advices(cls, advices: List[dict]) -> int:
        """批量发送建议通知"""
        success_count = 0
        for advice in advices:
            result = await cls.send_advice_notification(
                etf_code=advice.get("etf_code", ""),
                etf_name=advice.get("etf_name", ""),
                advice_type=advice.get("advice_type", "hold"),
                reason=advice.get("reason", ""),
                confidence=advice.get("confidence", 0)
            )
            if result:
                success_count += 1
        return success_count
