from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class MacroCycleState(Base):
    __tablename__ = "macro_cycle_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    region: Mapped[str] = mapped_column(String(20), default="cn", nullable=False, index=True)
    cycle_phase: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    growth_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    inflation_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    growth_trend: Mapped[str] = mapped_column(String(20), nullable=False)
    inflation_trend: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=50, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    dca_impact: Mapped[str | None] = mapped_column(Text)
    source_note: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), default="auto", nullable=False, index=True)
    override_until: Mapped[datetime | None] = mapped_column(DateTime)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
