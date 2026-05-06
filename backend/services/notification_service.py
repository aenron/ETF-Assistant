"""通知服务"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user_notification_config import UserNotificationConfig
from schemas.notification import (
    BarkNotificationConfigUpdate,
    NotificationConfigResponse,
    TelegramNotificationConfigUpdate,
)


DEFAULT_BARK_URL = "https://api.day.app"
DEFAULT_TELEGRAM_URL = "https://api.telegram.org"
PROVIDER_BARK = "bark"
PROVIDER_TELEGRAM = "telegram"
SUPPORTED_PROVIDERS = (PROVIDER_BARK, PROVIDER_TELEGRAM)


@dataclass
class NotificationMessage:
    title: str
    body: str
    group: Optional[str] = None
    icon: Optional[str] = None
    url: Optional[str] = None


class BarkNotifier:
    def __init__(self, key: str, base_url: str = DEFAULT_BARK_URL):
        self.key = key
        self.base_url = base_url.rstrip("/")

    async def send(self, message: NotificationMessage) -> tuple[bool, str]:
        if not self.key:
            return False, "未配置Bark Key"

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
                response = await client.post(f"{self.base_url}/{self.key}", json=payload)
            if response.status_code != 200:
                return False, f"HTTP {response.status_code}"
            result = response.json()
            if result.get("code") == 200:
                return True, "推送成功"
            return False, str(result.get("message", "未知错误"))
        except Exception as exc:
            return False, str(exc)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, base_url: str = DEFAULT_TELEGRAM_URL):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = base_url.rstrip("/")

    async def send(self, message: NotificationMessage) -> tuple[bool, str]:
        if not self.bot_token or not self.chat_id:
            return False, "未配置Telegram Bot Token或Chat ID"

        payload = {
            "chat_id": self.chat_id,
            "text": f"{message.title}\n\n{message.body}",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(f"{self.base_url}/bot{self.bot_token}/sendMessage", json=payload)
            if response.status_code != 200:
                return False, f"HTTP {response.status_code}"
            result = response.json()
            if result.get("ok") is True:
                return True, "推送成功"
            return False, str(result.get("description", "未知错误"))
        except Exception as exc:
            return False, str(exc)


class NotificationService:
    """用户级通知服务"""

    @staticmethod
    def mask_secret(value: str | None) -> str | None:
        if not value:
            return None
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}***{value[-4:]}"

    @staticmethod
    def mask_chat_id(value: str | None) -> str | None:
        if not value:
            return None
        if len(value) <= 6:
            return "*" * len(value)
        return f"{value[:2]}***{value[-2:]}"

    @classmethod
    async def get_config(
        cls,
        session: AsyncSession,
        user_id: int,
        provider: str,
    ) -> UserNotificationConfig | None:
        result = await session.execute(
            select(UserNotificationConfig).where(
                UserNotificationConfig.user_id == user_id,
                UserNotificationConfig.provider == provider,
            )
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_or_init_config(
        cls,
        session: AsyncSession,
        user_id: int,
        provider: str,
    ) -> UserNotificationConfig:
        config = await cls.get_config(session, user_id, provider)
        if config:
            return config

        default_base_url = DEFAULT_BARK_URL if provider == PROVIDER_BARK else DEFAULT_TELEGRAM_URL
        config = UserNotificationConfig(
            user_id=user_id,
            provider=provider,
            enabled=False,
            device_key=None,
            chat_id=None,
            base_url=default_base_url,
        )
        session.add(config)
        await session.flush()
        return config

    @classmethod
    async def list_or_init_configs(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> list[UserNotificationConfig]:
        configs = []
        for provider in SUPPORTED_PROVIDERS:
            configs.append(await cls.get_or_init_config(session, user_id, provider))
        return configs

    @classmethod
    def to_response(cls, config: UserNotificationConfig) -> NotificationConfigResponse:
        return NotificationConfigResponse(
            id=config.id,
            provider=config.provider,
            enabled=config.enabled,
            configured=bool(config.device_key and (config.provider != PROVIDER_TELEGRAM or config.chat_id)),
            device_key_masked=cls.mask_secret(config.device_key),
            chat_id_masked=cls.mask_chat_id(config.chat_id),
            base_url=config.base_url or (DEFAULT_BARK_URL if config.provider == PROVIDER_BARK else DEFAULT_TELEGRAM_URL),
            last_test_at=config.last_test_at,
            last_test_success=config.last_test_success,
            last_error=config.last_error,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

    @classmethod
    async def upsert_bark_config(
        cls,
        session: AsyncSession,
        user_id: int,
        data: BarkNotificationConfigUpdate,
    ) -> UserNotificationConfig:
        config = await cls.get_or_init_config(session, user_id, PROVIDER_BARK)
        config.enabled = data.enabled
        config.base_url = data.base_url or DEFAULT_BARK_URL
        if data.device_key:
            config.device_key = data.device_key

        if config.enabled and not config.device_key:
            config.enabled = False
            config.last_error = "未配置Bark Key，已自动关闭通知"
        else:
            config.last_error = None

        await session.flush()
        await session.refresh(config)
        return config

    @classmethod
    async def upsert_telegram_config(
        cls,
        session: AsyncSession,
        user_id: int,
        data: TelegramNotificationConfigUpdate,
    ) -> UserNotificationConfig:
        config = await cls.get_or_init_config(session, user_id, PROVIDER_TELEGRAM)
        config.enabled = data.enabled
        config.base_url = data.base_url or DEFAULT_TELEGRAM_URL
        if data.bot_token:
            config.device_key = data.bot_token
        if data.chat_id:
            config.chat_id = data.chat_id

        if config.enabled and (not config.device_key or not config.chat_id):
            config.enabled = False
            config.last_error = "未配置Telegram Bot Token或Chat ID，已自动关闭通知"
        else:
            config.last_error = None

        await session.flush()
        await session.refresh(config)
        return config

    @classmethod
    def build_notifier(cls, config: UserNotificationConfig):
        if config.provider == PROVIDER_BARK:
            return BarkNotifier(config.device_key or "", config.base_url or DEFAULT_BARK_URL) if config.device_key else None
        if config.provider == PROVIDER_TELEGRAM:
            return (
                TelegramNotifier(config.device_key or "", config.chat_id or "", config.base_url or DEFAULT_TELEGRAM_URL)
                if config.device_key and config.chat_id
                else None
            )
        return None

    @classmethod
    async def mark_test_result(
        cls,
        session: AsyncSession,
        config: UserNotificationConfig,
        success: bool,
        message: str,
    ) -> UserNotificationConfig:
        config.last_test_at = datetime.now()
        config.last_test_success = success
        config.last_error = None if success else message
        await session.flush()
        await session.refresh(config)
        return config

    @classmethod
    async def send_test_notification(
        cls,
        session: AsyncSession,
        user_id: int,
        provider: str,
    ) -> tuple[bool, str, UserNotificationConfig]:
        config = await cls.get_or_init_config(session, user_id, provider)
        notifier = cls.build_notifier(config)
        if notifier is None:
            missing = "请先配置Bark Key" if provider == PROVIDER_BARK else "请先配置Telegram Bot Token和Chat ID"
            updated = await cls.mark_test_result(session, config, False, missing)
            return False, missing, updated

        test_body = "这是一条测试通知，说明你的配置已生效。"
        success, message = await notifier.send(
            NotificationMessage(
                title="【测试通知】ETF投资智能体",
                body=test_body,
                group="ETF通知测试" if provider == PROVIDER_BARK else None,
            )
        )
        updated = await cls.mark_test_result(session, config, success, message)
        result_message = "测试通知发送成功" if success else f"测试通知发送失败: {message}"
        return success, result_message, updated

    @classmethod
    async def get_enabled_configs(
        cls,
        session: AsyncSession,
        user_id: int,
    ) -> list[UserNotificationConfig]:
        result = await session.execute(
            select(UserNotificationConfig).where(
                UserNotificationConfig.user_id == user_id,
                UserNotificationConfig.enabled == True,
                UserNotificationConfig.provider.in_(SUPPORTED_PROVIDERS),
            )
        )
        configs = result.scalars().all()
        return [config for config in configs if cls.build_notifier(config) is not None]

    @staticmethod
    def format_confidence(confidence: float | Decimal | int | None) -> str:
        if confidence is None:
            return "0"
        return f"{float(confidence):.0f}"

    @classmethod
    async def send_message_to_configs(
        cls,
        session: AsyncSession,
        configs: Sequence[UserNotificationConfig],
        message: NotificationMessage,
    ) -> int:
        success_count = 0
        last_error: str | None = None
        for config in configs:
            notifier = cls.build_notifier(config)
            if notifier is None:
                continue
            success, error_message = await notifier.send(message)
            if success:
                success_count += 1
                config.last_error = None
            else:
                last_error = error_message
                config.last_error = error_message
        await session.flush()
        return success_count if success_count > 0 else 0

    @classmethod
    async def send_user_advice_notifications(
        cls,
        session: AsyncSession,
        user_id: int,
        advices: Sequence,
    ) -> int:
        configs = await cls.get_enabled_configs(session, user_id)
        if not configs:
            return 0

        advice_labels = {
            "buy": "买入",
            "sell": "卖出",
            "hold": "持有",
            "add": "加仓",
            "reduce": "减仓",
        }

        success_count = 0
        for advice in advices:
            label = advice_labels.get(getattr(advice, "advice_type", "hold"), getattr(advice, "advice_type", "hold"))
            success_count += await cls.send_message_to_configs(
                session,
                configs,
                NotificationMessage(
                    title=f"【收盘分析·{label}】{getattr(advice, 'etf_code', '')} {getattr(advice, 'etf_name', '') or ''}",
                    body=f"置信度: {cls.format_confidence(getattr(advice, 'confidence', 0))}%\n\n{getattr(advice, 'reason', '')}",
                    group="ETF收盘分析",
                ),
            )
        return success_count

    @classmethod
    async def send_user_account_analysis_notification(
        cls,
        session: AsyncSession,
        user_id: int,
        summary: str,
        position_advice: str,
        rebalance_advice: str,
        risk_level: str,
        key_actions: List[str],
        confidence: float,
    ) -> bool:
        configs = await cls.get_enabled_configs(session, user_id)
        if not configs:
            return False

        risk_labels = {
            "low": "低风险",
            "medium": "中风险",
            "high": "高风险",
        }
        actions_text = "\n".join(
            f"{index + 1}. {action}" for index, action in enumerate(key_actions[:3])
        ) or "暂无关键操作"
        sent_count = await cls.send_message_to_configs(
            session,
            configs,
            NotificationMessage(
                title="【本周分析】账户投资建议",
                body=(
                    f"风险等级: {risk_labels.get(risk_level, risk_level)}\n"
                    f"置信度: {cls.format_confidence(confidence)}%\n\n"
                    f"本周总体判断:\n{summary}\n\n"
                    f"本周仓位建议:\n{position_advice}\n\n"
                    f"本周调仓建议:\n{rebalance_advice}\n\n"
                    f"本周关键操作:\n{actions_text}"
                ),
                group="ETF本周分析",
            ),
        )
        return sent_count > 0
