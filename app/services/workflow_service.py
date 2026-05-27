"""
Workflow service.

Loads orchestrator and specialist agents from the database,
builds a dynamic LangGraph, and executes it.
Publishes every step to the WebSocket broadcast channel.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.broadcast import publish
from app.models.agent import Agent
from app.runtime.agent_graph import build_agent_graph
from app.runtime.state import WorkflowState
from app.services.run_service import add_message

logger = logging.getLogger(__name__)


def _agent_to_dict(agent: Agent) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "role": agent.role,
        "system_prompt": agent.system_prompt,
        "model": agent.model,
        "tools": json.loads(agent.tools) if isinstance(agent.tools, str) else agent.tools,
        "channels": json.loads(agent.channels) if isinstance(agent.channels, str) else agent.channels,
        "max_iterations": agent.max_iterations,
        "memory_enabled": agent.memory_enabled,
    }


async def _load_active_agents(db: AsyncSession) -> list[Agent]:
    result = await db.execute(select(Agent).where(Agent.is_active == True))  # noqa: E712
    return list(result.scalars().all())


def _split_agents(agents: list[Agent]) -> tuple[dict | None, list[dict]]:
    """
    Split agents into orchestrator and specialists.
    The orchestrator is identified by:
      1. role containing 'orchestrator' (case-insensitive), OR
      2. channels containing 'telegram', OR
      3. first agent in the list as fallback
    All other agents are specialists.
    """
    orchestrator = None
    specialists = []

    for agent in agents:
        channels = json.loads(agent.channels) if isinstance(agent.channels, str) else agent.channels
        role_lower = agent.role.lower()
        if "orchestrator" in role_lower or "telegram" in channels:
            if orchestrator is None:
                orchestrator = _agent_to_dict(agent)
                continue
        specialists.append(_agent_to_dict(agent))

    if orchestrator is None and agents:
        orchestrator = _agent_to_dict(agents[0])
        specialists = [_agent_to_dict(a) for a in agents[1:]]

    return orchestrator, specialists


async def run_workflow(
    db: AsyncSession,
    run_id: int,
    user_input: str,
) -> WorkflowState:
    """
    Main entry point for running a multi-agent workflow.
    Falls back to demo graph if fewer than 2 agents exist in DB.
    """
    agents = await _load_active_agents(db)

    if len(agents) < 2:
        logger.warning("Fewer than 2 active agents found — falling back to demo graph")
        from app.runtime.demo_graph import build_demo_graph
        graph = build_demo_graph()
        initial_state: WorkflowState = {
            "user_input": user_input,
            "current_step": "start",
            "research_notes": "",
            "final_response": "",
            "status": "pending",
            "routing_decision": "",
            "routing_reason": "",
            "tool_calls": [],
        }
        return await graph.ainvoke(initial_state)

    orchestrator, specialists = _split_agents(agents)

    if not specialists:
        specialists = [_agent_to_dict(a) for a in agents if _agent_to_dict(a) != orchestrator]

    if not specialists:
        logger.error("No specialist agents available")
        return {
            "user_input": user_input, "current_step": "error",
            "research_notes": "", "final_response": "No specialist agents configured.",
            "status": "failed", "routing_decision": "", "routing_reason": "", "tool_calls": [],
        }

    # Publish input event
    await add_message(db, run_id, "user", user_input, receiver=orchestrator["name"], message_type="input")
    await publish({"run_id": run_id, "sender": "user", "receiver": orchestrator["name"],
                   "content": user_input, "type": "input"})

    graph = build_agent_graph(orchestrator=orchestrator, specialists=specialists)

    initial_state: WorkflowState = {
        "user_input": user_input,
        "current_step": "start",
        "research_notes": "",
        "final_response": "",
        "status": "pending",
        "routing_decision": "",
        "routing_reason": "",
        "tool_calls": [],
    }

    result = await graph.ainvoke(initial_state)

    # Publish routing decision
    await add_message(
        db, run_id, orchestrator["name"],
        f"Routing to {result.get('routing_decision', '?')} — {result.get('routing_reason', '')}",
        receiver=result.get("routing_decision", ""),
        message_type="log",
    )
    await publish({
        "run_id": run_id, "sender": orchestrator["name"],
        "receiver": result.get("routing_decision", ""),
        "content": f"Routing to {result.get('routing_decision', '?')}: {result.get('routing_reason', '')}",
        "type": "log",
    })

    # Publish tool calls if any
    for tc in result.get("tool_calls", []):
        msg = f"Tool called: {tc['tool']}({tc['input']}) → {tc['result'][:200]}"
        await add_message(
            db, run_id, result.get("routing_decision", "agent"),
            msg, receiver=None, message_type="tool_call",
        )
        await publish({
            "run_id": run_id,
            "sender": result.get("routing_decision", "agent"),
            "receiver": None,
            "content": msg,
            "type": "tool_call",
        })

    # Publish final output
    await add_message(
        db, run_id, result.get("routing_decision", "agent"),
        result["final_response"], receiver="user", message_type="output",
    )
    await publish({
        "run_id": run_id,
        "sender": result.get("routing_decision", "agent"),
        "receiver": "user",
        "content": result["final_response"],
        "type": "output",
    })

    return result


# Keep backward-compat alias used by old callers
async def run_demo_workflow(
    db: AsyncSession,
    run_id: int,
    user_input: str,
) -> WorkflowState:
    return await run_workflow(db, run_id, user_input)
