from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models.user import User
from routers.auth import get_current_user
from schemas.notification import (
    BarkNotificationConfigUpdate,
    NotificationConfigListResponse,
    NotificationConfigResponse,
    NotificationTestResponse,
    TelegramNotificationConfigUpdate,
)
from services.notification_service import NotificationService


router = APIRouter(prefix="/api/notification-configs", tags=["通知配置"])


@router.get("", response_model=NotificationConfigListResponse)
async def list_notification_configs(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    configs = await NotificationService.list_or_init_configs(db, current_user.id)
    return NotificationConfigListResponse(configs=[NotificationService.to_response(config) for config in configs])


@router.put("/bark", response_model=NotificationConfigResponse)
async def upsert_bark_config(
    data: BarkNotificationConfigUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    config = await NotificationService.upsert_bark_config(db, current_user.id, data)
    return NotificationService.to_response(config)


@router.put("/telegram", response_model=NotificationConfigResponse)
async def upsert_telegram_config(
    data: TelegramNotificationConfigUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    config = await NotificationService.upsert_telegram_config(db, current_user.id, data)
    return NotificationService.to_response(config)


@router.post("/bark/test", response_model=NotificationTestResponse)
async def test_bark_config(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    success, message, config = await NotificationService.send_test_notification(db, current_user.id)
    return NotificationTestResponse(
        success=success,
        message=message,
        config=NotificationService.to_response(config),
    )


@router.post("/telegram/test", response_model=NotificationTestResponse)
async def test_telegram_config(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    success, message, config = await NotificationService.send_test_notification(db, current_user.id, provider="telegram")
    return NotificationTestResponse(
        success=success,
        message=message,
        config=NotificationService.to_response(config),
    )
