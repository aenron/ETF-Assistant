from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class EtfProfile(Base):
    """ETF/基金资料快照缓存"""

    __tablename__ = "etf_profile"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    year: Mapped[str] = mapped_column(String(4), primary_key=True)
    basic: Mapped[dict] = mapped_column(JSON, default=dict)
    asset_allocation: Mapped[list] = mapped_column(JSON, default=list)
    stock_holdings: Mapped[list] = mapped_column(JSON, default=list)
    bond_holdings: Mapped[list] = mapped_column(JSON, default=list)
    events: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str | None] = mapped_column(String(50), default="akshare")
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    refresh_count: Mapped[int] = mapped_column(Integer, default=0)
