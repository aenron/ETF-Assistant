from sqlalchemy import String, Numeric, BigInteger, DateTime, Date, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from datetime import date
from decimal import Decimal
from database import Base


class MarketDaily(Base):
    __tablename__ = "market_daily"
    __table_args__ = (UniqueConstraint("etf_code", "trade_date", name="uq_etf_date"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    etf_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    high_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    low_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
