from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class BarkNotificationConfigUpdate(BaseModel):
    enabled: bool = False
    device_key: str = Field(default="", max_length=255)
    base_url: str = Field(default="https://api.day.app", max_length=255)

    @field_validator("device_key", mode="before")
    @classmethod
    def normalize_device_key(cls, value: str | None) -> str:
        return (value or "").strip()

    @field_validator("base_url", mode="before")
    @classmethod
    def normalize_base_url(cls, value: str | None) -> str:
        normalized = (value or "https://api.day.app").strip()
        return normalized.rstrip("/")


class TelegramNotificationConfigUpdate(BaseModel):
    enabled: bool = False
    bot_token: str = Field(default="", max_length=255)
    chat_id: str = Field(default="", max_length=255)
    base_url: str = Field(default="https://api.telegram.org", max_length=255)

    @field_validator("bot_token", "chat_id", mode="before")
    @classmethod
    def normalize_text(cls, value: str | None) -> str:
        return (value or "").strip()

    @field_validator("base_url", mode="before")
    @classmethod
    def normalize_telegram_base_url(cls, value: str | None) -> str:
        normalized = (value or "https://api.telegram.org").strip()
        return normalized.rstrip("/")


class NotificationConfigResponse(BaseModel):
    id: int | None = None
    provider: str
    enabled: bool
    configured: bool
    device_key_masked: str | None = None
    chat_id_masked: str | None = None
    base_url: str
    last_test_at: datetime | None = None
    last_test_success: bool | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NotificationConfigListResponse(BaseModel):
    configs: list[NotificationConfigResponse]


class NotificationTestResponse(BaseModel):
    success: bool
    message: str
    config: NotificationConfigResponse
