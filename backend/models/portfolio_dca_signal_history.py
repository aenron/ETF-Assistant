from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class PortfolioDcaSignalHistory(Base):
    __tablename__ = "portfolio_dca_signal_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, ForeignKey("portfolio.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    etf_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    signal_light: Mapped[str | None] = mapped_column(String(30))
    persisted_light: Mapped[str | None] = mapped_column(String(30))
    candidate_light: Mapped[str | None] = mapped_column(String(30))
    candidate_confirm_count: Mapped[int | None] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str | None] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(Text)
    budget_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    trigger_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    metrics: Mapped[dict | None] = mapped_column(JSONB)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
