from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class DcaSignalConfig(Base):
    __tablename__ = "dca_signal_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    valuation_deep_green_percentile: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=15, nullable=False)
    valuation_green_percentile: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=30, nullable=False)
    valuation_red_percentile: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=80, nullable=False)
    valuation_min_sample_size: Mapped[int] = mapped_column(Integer, default=250, nullable=False)
    trend_short_ma_days: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    trend_medium_ma_days: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    trend_long_ma_days: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    trend_history_days: Mapped[int] = mapped_column(Integer, default=140, nullable=False)
    trend_slope_shift_days: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    trend_volume_ma_days: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    trend_volume_confirm_ratio: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=0.8, nullable=False)
    trend_volume_expand_ratio: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=1.2, nullable=False)
    trend_atr_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    trend_atr_base_multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=1.5, nullable=False)
    trend_atr_mid_multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=1.8, nullable=False)
    trend_atr_high_multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=2.0, nullable=False)
    trend_atr_mid_volatility_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=2.5, nullable=False)
    trend_atr_high_volatility_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=4.0, nullable=False)
    light_confirm_count: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
