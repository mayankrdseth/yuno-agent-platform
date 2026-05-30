"""
Memory service — CRUD for ConversationMemory.

All memory is scoped to the orchestrator agent.
Session key conventions:
  Browser UI  -> "ui_session"
  Telegram    -> "telegram_{chat_id}"
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_memory import ConversationMemory

logger = logging.getLogger(__name__)


async def get_memory(
    db: AsyncSession,
    agent_id: int,
    session_key: str,
    max_turns: int = 5,
) -> list[dict]:
    """
    Return the last `max_turns` human/ai message pairs for this session.
    Returns a flat list of {role, content} dicts ordered oldest-first.
    We fetch 2*max_turns rows (each turn = 1 human + 1 ai) and return them.
    """
    result = await db.execute(
        select(ConversationMemory)
        .where(
            ConversationMemory.agent_id == agent_id,
            ConversationMemory.session_key == session_key,
        )
        .order_by(ConversationMemory.id.desc())
        .limit(max_turns * 2)
    )
    rows = list(reversed(result.scalars().all()))
    return [{"role": r.role, "content": r.content} for r in rows]


async def save_turn(
    db: AsyncSession,
    agent_id: int,
    session_key: str,
    human_message: str,
    ai_message: str,
) -> None:
    """Persist one human+ai exchange."""
    db.add(ConversationMemory(agent_id=agent_id, session_key=session_key, role="human", content=human_message))
    db.add(ConversationMemory(agent_id=agent_id, session_key=session_key, role="ai", content=ai_message))
    await db.commit()
    logger.debug("Memory saved: agent_id=%s session=%s", agent_id, session_key)


async def clear_memory(
    db: AsyncSession,
    agent_id: int,
    session_key: str | None = None,
) -> int:
    """
    Delete memory for an agent.
    If session_key is provided, only that session is cleared.
    Returns number of rows deleted.
    """
    stmt = delete(ConversationMemory).where(ConversationMemory.agent_id == agent_id)
    if session_key:
        stmt = stmt.where(ConversationMemory.session_key == session_key)
    result = await db.execute(stmt)
    await db.commit()
    deleted = result.rowcount
    logger.info("Memory cleared: agent_id=%s session=%s rows=%s", agent_id, session_key, deleted)
    return deleted


async def list_sessions(
    db: AsyncSession,
    agent_id: int,
) -> list[dict]:
    """
    Return all sessions for an agent with turn count and last activity.
    Returns list of {session_key, turn_count, last_active}.
    """
    result = await db.execute(
        select(
            ConversationMemory.session_key,
            func.count(ConversationMemory.id).label("row_count"),
            func.max(ConversationMemory.created_at).label("last_active"),
        )
        .where(ConversationMemory.agent_id == agent_id)
        .group_by(ConversationMemory.session_key)
        .order_by(func.max(ConversationMemory.created_at).desc())
    )
    rows = result.all()
    return [
        {
            "session_key": r.session_key,
            "turn_count": r.row_count // 2,   # each turn = 2 rows
            "last_active": str(r.last_active),
        }
        for r in rows
    ]
