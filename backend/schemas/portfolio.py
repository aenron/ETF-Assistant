import math

from pydantic import field_validator
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List

from schemas.base import ShanghaiBaseModel, ShanghaiOrmModel


def _finite_float(value, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def _optional_finite_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


class DecimalModel(ShanghaiBaseModel):
    pass


class PortfolioBase(ShanghaiBaseModel):
    etf_code: str
    shares: float
    cost_price: float
    buy_date: Optional[date] = None
    note: Optional[str] = None
    dca_track_override: Optional[str] = None


class PortfolioCreate(PortfolioBase):
    pass


class PortfolioUpdate(ShanghaiBaseModel):
    shares: Optional[float] = None
    cost_price: Optional[float] = None
    buy_date: Optional[date] = None
    note: Optional[str] = None
    dca_track_override: Optional[str] = None


class PortfolioResponse(PortfolioBase, ShanghaiOrmModel):
    id: int
    created_at: datetime
    updated_at: datetime

class PortfolioFactorScore(ShanghaiBaseModel):
    enabled: bool = False
    total_score: float = 0.0
    macro_score: float = 0.0
    technical_score: float = 0.0
    sentiment_score: float = 0.0
    prosperity_score: float = 0.0
    rating: str = "不适用"
    action: str = "不适用"
    reason: str = "仅行业或主题 ETF 参与四因子评分。"
    factors: list[str] = []
    momentum20: Optional[float] = None
    amount: Optional[float] = None
    liquidity_score: Optional[float] = None


class PortfolioCrossBorderRisk(ShanghaiBaseModel):
    is_cross_border: bool = False
    risk_level: str = "low"
    risk_tags: list[str] = []
    max_position_hint: float = 0.0
    budget_multiplier_adjustment: float = 1.0
    action: str = "常规执行"
    reason: str = "非跨境 ETF，按常规持仓规则处理。"
    warnings: list[str] = []
    iopv: Optional[float] = None
    premium_rate: Optional[float] = None


class PortfolioWithMarket(PortfolioResponse):
    """持仓信息 + 实时行情"""
    etf_name: Optional[str] = None
    current_price: Optional[float] = None
    change_pct: Optional[float] = None
    market_refreshed_at: Optional[datetime] = None
    market_value: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    today_pnl: Optional[float] = None
    today_pnl_pct: Optional[float] = None
    holding_days: Optional[int] = None
    dca_track: Optional[str] = None
    dca_light: Optional[str] = None
    dca_label: Optional[str] = None
    dca_action: Optional[str] = None
    dca_reason: Optional[str] = None
    dca_next_trigger_price: Optional[float] = None
    dca_valuation_percentile: Optional[float] = None
    dca_valuation_pe: Optional[float] = None
    dca_valuation_pb: Optional[float] = None
    dca_valuation_pe_percentile: Optional[float] = None
    dca_valuation_pb_percentile: Optional[float] = None
    dca_valuation_sample_size: Optional[int] = None
    dca_trend_ma20: Optional[float] = None
    dca_trend_ma20_slope_pct: Optional[float] = None
    dca_trend_distance_pct: Optional[float] = None
    dca_trend_atr14: Optional[float] = None
    dca_trend_atr_band_pct: Optional[float] = None
    dca_trend_ma60: Optional[float] = None
    dca_trend_ma60_slope_pct: Optional[float] = None
    dca_trend_ma120: Optional[float] = None
    dca_trend_ma120_slope_pct: Optional[float] = None
    dca_trend_volume_ratio: Optional[float] = None
    dca_trend_atr_multiplier: Optional[float] = None
    dca_decision_steps: Optional[List[str]] = None
    dca_candidate_light: Optional[str] = None
    dca_candidate_confirm_count: Optional[int] = None
    dca_quality_score: Optional[float] = None
    dca_green_trigger_price: Optional[float] = None
    dca_deep_green_trigger_price: Optional[float] = None
    dca_budget_multiplier: Optional[float] = None
    dca_budget_label: Optional[str] = None
    cross_border_risk: Optional[PortfolioCrossBorderRisk] = None
    factor_score: Optional[PortfolioFactorScore] = None

    @field_validator(
        "current_price",
        "change_pct",
        "market_value",
        "pnl",
        "pnl_pct",
        "today_pnl",
        "today_pnl_pct",
        "dca_next_trigger_price",
        "dca_valuation_percentile",
        "dca_valuation_pe",
        "dca_valuation_pb",
        "dca_valuation_pe_percentile",
        "dca_valuation_pb_percentile",
        "dca_trend_ma20",
        "dca_trend_ma20_slope_pct",
        "dca_trend_distance_pct",
        "dca_trend_atr14",
        "dca_trend_atr_band_pct",
        "dca_trend_ma60",
        "dca_trend_ma60_slope_pct",
        "dca_trend_ma120",
        "dca_trend_ma120_slope_pct",
        "dca_trend_volume_ratio",
        "dca_trend_atr_multiplier",
        "dca_quality_score",
        "dca_green_trigger_price",
        "dca_deep_green_trigger_price",
        "dca_budget_multiplier",
        mode="before",
    )
    @classmethod
    def clean_optional_float(cls, value):
        return _optional_finite_float(value)


class PortfolioExposureItem(ShanghaiBaseModel):
    name: str
    market_value: float
    ratio: float


class PortfolioExposureAlert(ShanghaiBaseModel):
    level: str
    message: str


class PortfolioExposureAnalysis(ShanghaiBaseModel):
    asset_bucket: list[PortfolioExposureItem] = []
    region: list[PortfolioExposureItem] = []
    style: list[PortfolioExposureItem] = []
    risk_tags: list[PortfolioExposureItem] = []
    alerts: list[PortfolioExposureAlert] = []


class PortfolioRebalanceItem(ShanghaiBaseModel):
    name: str
    current_value: float
    current_ratio: float
    target_ratio: float
    deviation_ratio: float
    suggested_amount: float
    action: str
    execution_status: str = "hold"
    execution_label: str = "保持观察"
    reason: str


class PortfolioRebalancePlan(ShanghaiBaseModel):
    total_assets: float
    single_adjustment_limit: float
    items: list[PortfolioRebalanceItem] = []
    notes: list[str] = []


class PortfolioSummary(ShanghaiBaseModel):
    """持仓汇总"""
    total_market_value: float
    total_cost: float
    total_pnl: float
    total_pnl_pct: float
    today_pnl: Optional[float] = None
    today_pnl_pct: Optional[float] = None
    category_distribution: dict[str, float]
    total_assets: Optional[float] = None  # 总金额 = 持仓市值 + 可用资金
    holding_count: int = 0
    missing_quote_count: int = 0
    exposure_analysis: Optional[PortfolioExposureAnalysis] = None
    rebalance_plan: Optional[PortfolioRebalancePlan] = None

    @field_validator("total_market_value", "total_cost", "total_pnl", "total_pnl_pct", mode="before")
    @classmethod
    def clean_required_float(cls, value):
        return _finite_float(value)

    @field_validator("today_pnl", "today_pnl_pct", "total_assets", mode="before")
    @classmethod
    def clean_summary_optional_float(cls, value):
        return _optional_finite_float(value)

    @field_validator("category_distribution", mode="before")
    @classmethod
    def clean_category_distribution(cls, value):
        if not isinstance(value, dict):
            return {}
        return {str(key): _finite_float(item) for key, item in value.items()}


class PortfolioDcaSignalHistoryResponse(ShanghaiBaseModel):
    id: int
    portfolio_id: int
    etf_code: str
    signal_light: Optional[str] = None
    persisted_light: Optional[str] = None
    candidate_light: Optional[str] = None
    candidate_confirm_count: Optional[int] = None
    label: Optional[str] = None
    action: Optional[str] = None
    reason: Optional[str] = None
    budget_multiplier: Optional[float] = None
    trigger_price: Optional[float] = None
    price: Optional[float] = None
    metrics: Optional[dict] = None
    scanned_at: datetime

    @field_validator("budget_multiplier", "trigger_price", "price", mode="before")
    @classmethod
    def clean_history_optional_float(cls, value):
        return _optional_finite_float(value)


class DcaIndexMappingBase(ShanghaiBaseModel):
    etf_code: Optional[str] = None
    keyword: Optional[str] = None
    index_symbol: str
    index_name: Optional[str] = None
    enabled: bool = True


class DcaIndexMappingCreate(DcaIndexMappingBase):
    pass


class DcaIndexMappingUpdate(ShanghaiBaseModel):
    etf_code: Optional[str] = None
    keyword: Optional[str] = None
    index_symbol: Optional[str] = None
    index_name: Optional[str] = None
    enabled: Optional[bool] = None


class DcaIndexMappingResponse(DcaIndexMappingBase, ShanghaiOrmModel):
    id: int
    created_at: datetime
    updated_at: datetime


class DcaSignalConfigBase(ShanghaiBaseModel):
    valuation_deep_green_percentile: float = 15
    valuation_green_percentile: float = 30
    valuation_red_percentile: float = 80
    valuation_min_sample_size: int = 250
    trend_short_ma_days: int = 20
    trend_medium_ma_days: int = 60
    trend_long_ma_days: int = 120
    trend_history_days: int = 140
    trend_slope_shift_days: int = 5
    trend_volume_ma_days: int = 20
    trend_volume_confirm_ratio: float = 0.8
    trend_volume_expand_ratio: float = 1.2
    trend_atr_days: int = 14
    trend_atr_base_multiplier: float = 1.5
    trend_atr_mid_multiplier: float = 1.8
    trend_atr_high_multiplier: float = 2.0
    trend_atr_mid_volatility_pct: float = 2.5
    trend_atr_high_volatility_pct: float = 4.0
    light_confirm_count: int = 2


class DcaSignalConfigUpdate(ShanghaiBaseModel):
    valuation_deep_green_percentile: Optional[float] = None
    valuation_green_percentile: Optional[float] = None
    valuation_red_percentile: Optional[float] = None
    valuation_min_sample_size: Optional[int] = None
    trend_short_ma_days: Optional[int] = None
    trend_medium_ma_days: Optional[int] = None
    trend_long_ma_days: Optional[int] = None
    trend_history_days: Optional[int] = None
    trend_slope_shift_days: Optional[int] = None
    trend_volume_ma_days: Optional[int] = None
    trend_volume_confirm_ratio: Optional[float] = None
    trend_volume_expand_ratio: Optional[float] = None
    trend_atr_days: Optional[int] = None
    trend_atr_base_multiplier: Optional[float] = None
    trend_atr_mid_multiplier: Optional[float] = None
    trend_atr_high_multiplier: Optional[float] = None
    trend_atr_mid_volatility_pct: Optional[float] = None
    trend_atr_high_volatility_pct: Optional[float] = None
    light_confirm_count: Optional[int] = None


class DcaSignalConfigResponse(DcaSignalConfigBase, ShanghaiOrmModel):
    id: int
    updated_at: datetime
