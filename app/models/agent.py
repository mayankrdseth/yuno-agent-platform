from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="llama-3.1-8b-instant")
    tools: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    channels: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Memory — only meaningful on orchestrator agents
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Schedule — cron string + fixed prompt fired when cron triggers
    schedule: Mapped[str | None] = mapped_column(String(120), nullable=True)
    schedule_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Guardrails
    forbidden_topics: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    max_output_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
