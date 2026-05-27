from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WorkflowMessage(Base):
    __tablename__ = "workflow_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), nullable=False)
    sender: Mapped[str] = mapped_column(String(120), nullable=False)
    receiver: Mapped[str | None] = mapped_column(String(120), nullable=True)
    message_type: Mapped[str] = mapped_column(String(50), nullable=False, default="log")
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run = relationship("WorkflowRun", back_populates="messages")