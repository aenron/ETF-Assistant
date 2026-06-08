from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class IndexValuation(Base):
    __tablename__ = "index_valuation"
    __table_args__ = (UniqueConstraint("index_symbol", "trade_date", name="uq_index_valuation_symbol_date"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    index_symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    index_name: Mapped[str | None] = mapped_column(String(100))
    pe: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    pe2: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    pb: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dividend_yield: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dividend_yield2: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
