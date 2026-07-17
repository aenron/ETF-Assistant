from datetime import datetime
from typing import Optional

from pydantic import field_validator

from schemas.base import ShanghaiBaseModel, ShanghaiOrmModel


SUPPORTED_WATCHLIST_ASSET_TYPES = {"etf", "stock", "otc_fund", "cash", "money_fund"}


class WatchlistCreate(ShanghaiBaseModel):
    code: str
    name: Optional[str] = None
    asset_type: str = "etf"
    note: Optional[str] = None

    @field_validator("code", mode="before")
    @classmethod
    def clean_code(cls, value):
        return str(value or "").strip().upper()

    @field_validator("asset_type", mode="before")
    @classmethod
    def clean_asset_type(cls, value):
        parsed = str(value or "etf").strip()
        return parsed if parsed in SUPPORTED_WATCHLIST_ASSET_TYPES else "etf"


class WatchlistUpdate(ShanghaiBaseModel):
    name: Optional[str] = None
    asset_type: Optional[str] = None
    note: Optional[str] = None
    sort_order: Optional[int] = None

    @field_validator("asset_type", mode="before")
    @classmethod
    def clean_asset_type(cls, value):
        if value is None:
            return None
        parsed = str(value or "").strip()
        return parsed if parsed in SUPPORTED_WATCHLIST_ASSET_TYPES else "etf"


class WatchlistItemResponse(ShanghaiOrmModel):
    id: int
    code: str
    name: Optional[str] = None
    asset_type: str
    note: Optional[str] = None
    sort_order: int
    created_at: datetime
    updated_at: datetime
    current_price: Optional[float] = None
    change_pct: Optional[float] = None
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[float] = None
    iopv: Optional[float] = None
    premium_rate: Optional[float] = None
    market_refreshed_at: Optional[datetime] = None
    is_holding: bool = False
    holding_market_value: Optional[float] = None


class WatchlistRefreshResponse(ShanghaiBaseModel):
    success: bool
    message: str
    refreshed: int
    codes: list[str] = []
