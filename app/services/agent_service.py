import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentUpdate


async def list_agents(db: AsyncSession) -> list[Agent]:
    result = await db.execute(select(Agent).order_by(Agent.id.desc()))
    return list(result.scalars().all())


async def get_agent(db: AsyncSession, agent_id: int) -> Agent | None:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def create_agent(db: AsyncSession, payload: AgentCreate) -> Agent:
    agent = Agent(
        name=payload.name,
        role=payload.role,
        system_prompt=payload.system_prompt,
        model=payload.model,
        tools=json.dumps(payload.tools),
        channels=json.dumps(payload.channels),
        is_active=payload.is_active,
        max_iterations=payload.max_iterations,
        memory_enabled=payload.memory_enabled,
        schedule=payload.schedule,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


async def update_agent(db: AsyncSession, agent: Agent, payload: AgentUpdate) -> Agent:
    update_data = payload.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        if field in {"tools", "channels"} and value is not None:
            setattr(agent, field, json.dumps(value))
        else:
            setattr(agent, field, value)

    await db.commit()
    await db.refresh(agent)
    return agent