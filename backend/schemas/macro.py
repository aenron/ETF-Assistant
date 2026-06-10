from datetime import datetime
from typing import Optional, Literal

from pydantic import field_validator

from schemas.base import ShanghaiBaseModel, ShanghaiOrmModel

MacroPhase = Literal["recovery", "overheating", "stagflation", "recession"]
MacroTrend = Literal["up", "down", "flat", "unclear"]
MacroRegion = Literal["cn", "us", "global"]
MacroSourceType = Literal["auto", "manual"]


class MacroCycleStateBase(ShanghaiBaseModel):
    region: MacroRegion = "cn"
    cycle_phase: MacroPhase = "recovery"
    growth_score: float = 0
    inflation_score: float = 0
    growth_trend: MacroTrend = "unclear"
    inflation_trend: MacroTrend = "unclear"
    confidence: float = 50
    summary: Optional[str] = None
    dca_impact: Optional[str] = None
    source_note: Optional[str] = None
    source_type: MacroSourceType = "manual"
    override_until: Optional[datetime] = None
    observed_at: Optional[datetime] = None

    @field_validator("growth_score", "inflation_score", "confidence")
    @classmethod
    def validate_score(cls, value: float) -> float:
        if value < 0 or value > 100:
            raise ValueError("分数必须在 0 到 100 之间")
        return value


class MacroCycleStateCreate(MacroCycleStateBase):
    pass


class MacroCycleStateResponse(MacroCycleStateBase, ShanghaiOrmModel):
    id: int
    observed_at: datetime
    created_at: datetime
    updated_at: datetime


class MacroIndicatorResponse(ShanghaiOrmModel):
    id: int
    region: MacroRegion
    indicator_code: str
    indicator_name: str
    category: str
    period: str
    value: float
    previous_value: Optional[float] = None
    trend: MacroTrend
    unit: Optional[str] = None
    source: str
    source_note: Optional[str] = None
    source_function: Optional[str] = None
    source_column: Optional[str] = None
    raw_period: Optional[str] = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime


class MacroRefreshResponse(ShanghaiBaseModel):
    success: bool
    message: str
    indicators_saved: int
    state: Optional[MacroCycleStateResponse] = None
    errors: list[str] = []
