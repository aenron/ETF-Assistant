from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class StrategyRunCache(Base):
    """用户级交易策略最近一次运行结果缓存。"""

    __tablename__ = "strategy_run_cache"
    __table_args__ = (
        UniqueConstraint("user_id", "strategy_id", name="uq_strategy_run_cache_user_strategy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    strategy_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
