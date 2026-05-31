import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate
from app.services.agent_service import create_agent, delete_agent, get_agent, list_agents, update_agent
from app.services.memory_service import clear_memory, list_sessions
from app.services.scheduler_service import register_agent_job, remove_agent_job

router = APIRouter(prefix="/agents", tags=["agents"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def serialize_agent(agent) -> AgentRead:
    return AgentRead(
        id=agent.id,
        name=agent.name,
        role=agent.role,
        system_prompt=agent.system_prompt,
        model=agent.model,
        tools=json.loads(agent.tools or "[]"),
        channels=json.loads(agent.channels or "[]"),
        is_active=agent.is_active,
        max_iterations=agent.max_iterations,
        memory_enabled=agent.memory_enabled,
        schedule=agent.schedule,
        schedule_prompt=agent.schedule_prompt,
        forbidden_topics=json.loads(agent.forbidden_topics or "[]"),
        max_output_chars=agent.max_output_chars,
        # Capability fields — were missing from serialization
        skills=json.loads(agent.skills or "[]"),
        interaction_rules=json.loads(agent.interaction_rules or "[]"),
    )


@router.get("", response_model=list[AgentRead])
async def get_agents(db: DbSession):
    agents = await list_agents(db)
    return [serialize_agent(agent) for agent in agents]


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def post_agent(payload: AgentCreate, db: DbSession):
    agent = await create_agent(db, payload)
    # Register schedule job if provided
    if agent.schedule and agent.schedule_prompt:
        register_agent_job(agent.id, agent.schedule, agent.schedule_prompt)
    return serialize_agent(agent)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent_by_id(agent_id: int, db: DbSession):
    agent = await get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return serialize_agent(agent)


@router.patch("/{agent_id}", response_model=AgentRead)
async def patch_agent(agent_id: int, payload: AgentUpdate, db: DbSession):
    agent = await get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = await update_agent(db, agent, payload)
    # Hot-reload scheduler: remove old job, re-register if schedule set
    remove_agent_job(agent_id)
    if agent.schedule and agent.schedule_prompt:
        register_agent_job(agent.id, agent.schedule, agent.schedule_prompt)
    return serialize_agent(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_agent(agent_id: int, db: DbSession):
    deleted = await delete_agent(db, agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    remove_agent_job(agent_id)


# ── Memory endpoints ─────────────────────────────────────────────────────────

@router.get("/{agent_id}/memory")
async def get_agent_memory_sessions(agent_id: int, db: DbSession):
    """List all memory sessions for an agent with turn counts."""
    agent = await get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    sessions = await list_sessions(db, agent_id)
    return {"agent_id": agent_id, "sessions": sessions}


@router.delete("/{agent_id}/memory", status_code=status.HTTP_200_OK)
async def clear_agent_memory_all(agent_id: int, db: DbSession):
    """Clear ALL memory for an agent across all sessions."""
    agent = await get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    deleted = await clear_memory(db, agent_id)
    return {"deleted_rows": deleted, "message": "All memory cleared."}


@router.delete("/{agent_id}/memory/{session_key:path}", status_code=status.HTTP_200_OK)
async def clear_agent_memory_session(agent_id: int, session_key: str, db: DbSession):
    """Clear memory for a specific session (e.g. telegram_123456789)."""
    agent = await get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    deleted = await clear_memory(db, agent_id, session_key=session_key)
    return {"deleted_rows": deleted, "session_key": session_key, "message": "Session memory cleared."}
