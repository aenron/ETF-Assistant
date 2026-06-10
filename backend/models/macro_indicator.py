from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class MacroIndicator(Base):
    __tablename__ = "macro_indicator"
    __table_args__ = (UniqueConstraint("region", "indicator_code", "period", name="uq_macro_indicator_region_code_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    region: Mapped[str] = mapped_column(String(20), default="cn", nullable=False, index=True)
    indicator_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    indicator_name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    previous_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    trend: Mapped[str] = mapped_column(String(20), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(50), default="akshare", nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text)
    source_function: Mapped[str | None] = mapped_column(String(100))
    source_column: Mapped[str | None] = mapped_column(String(100))
    raw_period: Mapped[str | None] = mapped_column(String(50))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
