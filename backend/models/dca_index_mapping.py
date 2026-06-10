from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class DcaIndexMapping(Base):
    __tablename__ = "dca_index_mapping"
    __table_args__ = (UniqueConstraint("etf_code", "keyword", name="uq_dca_index_mapping_code_keyword"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    etf_code: Mapped[str | None] = mapped_column(String(20), index=True)
    keyword: Mapped[str | None] = mapped_column(String(100), index=True)
    index_symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    index_name: Mapped[str | None] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
