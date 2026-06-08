from datetime import datetime
from typing import Literal, Optional

from pydantic import Field

from schemas.base import ShanghaiBaseModel


StrategyId = Literal["tfss_v1"]
StrategySignal = Literal["entry", "hold", "reduce", "exit", "avoid", "insufficient_data"]


class StrategyInfo(ShanghaiBaseModel):
    id: StrategyId
    name: str
    description: str
    enabled: bool = True


class StrategyRunRequest(ShanghaiBaseModel):
    strategy_id: StrategyId = "tfss_v1"


class StrategyScheduleRequest(ShanghaiBaseModel):
    enabled: bool


class StrategyScheduleResponse(ShanghaiBaseModel):
    strategy_id: StrategyId
    enabled: bool
    cron: str = "交易日 14:40"
    job_id: str
    next_run_time: Optional[datetime] = None


class StrategySignalResult(ShanghaiBaseModel):
    etf_code: str
    etf_name: Optional[str] = None
    signal: StrategySignal
    signal_label: str
    confidence: int
    close_price: Optional[float] = None
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma20_slope: Optional[float] = None
    volume: Optional[int] = None
    volume_ma10: Optional[float] = None
    atr14: Optional[float] = None
    atr_stop_price: Optional[float] = None
    momentum20: Optional[float] = None
    rotation_rank: Optional[int] = None
    rotation_top: Optional[bool] = None
    engine_phase: Optional[str] = None
    grid_action: Optional[str] = None
    protection_action: Optional[str] = None
    macd_dif: Optional[float] = None
    macd_dea: Optional[float] = None
    macd_histogram: Optional[float] = None
    rsi14: Optional[float] = None
    bias20: Optional[float] = None
    reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class StrategyRunResponse(ShanghaiBaseModel):
    strategy_id: StrategyId
    strategy_name: str
    run_at: datetime
    total: int
    results: list[StrategySignalResult]
