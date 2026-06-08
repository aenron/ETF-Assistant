from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class PortfolioDcaState(Base):
    __tablename__ = "portfolio_dca_state"
    __table_args__ = (UniqueConstraint("portfolio_id", name="uq_portfolio_dca_state_portfolio"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, ForeignKey("portfolio.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    etf_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    last_light: Mapped[str | None] = mapped_column(String(30))
    last_label: Mapped[str | None] = mapped_column(String(100))
    last_action: Mapped[str | None] = mapped_column(String(100))
    last_budget_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    last_trigger_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    last_notified_key: Mapped[str | None] = mapped_column(String(200))
    pending_notify_key: Mapped[str | None] = mapped_column(String(200), index=True)
    pending_notify_reason: Mapped[str | None] = mapped_column(String(100))
    candidate_light: Mapped[str | None] = mapped_column(String(30))
    candidate_confirm_count: Mapped[int | None] = mapped_column(Integer)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
