from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConversationMemory(Base):
    """
    Stores conversation turns keyed by (agent_id, session_key).

    session_key conventions:
      - Browser UI  : "ui_session"  (single shared key for all canvas runs)
      - Telegram    : "telegram_{chat_id}"  (one per user)
    """
    __tablename__ = "conversation_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False)   # "human" | "ai"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
