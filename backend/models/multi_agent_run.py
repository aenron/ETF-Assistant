from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class MultiAgentRun(Base):
    __tablename__ = "multi_agent_run"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scene: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    use_portfolio_context: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_debate_rounds: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    collapse_debate_by_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
