import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate
from app.services.agent_service import create_agent, get_agent, list_agents, update_agent

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
    )


@router.get("", response_model=list[AgentRead])
async def get_agents(db: DbSession):
    agents = await list_agents(db)
    return [serialize_agent(agent) for agent in agents]


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def post_agent(payload: AgentCreate, db: DbSession):
    agent = await create_agent(db, payload)
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
    return serialize_agent(agent)