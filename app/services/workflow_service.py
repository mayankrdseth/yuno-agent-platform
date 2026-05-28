"""
Workflow service.

Model B: the canvas is the workflow definition.
- When agent_ids is provided (from frontend canvas), only those agents are loaded.
- When agent_ids is None (e.g. Telegram), all active agents are loaded as fallback.

Orchestrator detection: exact match on role == "orchestrator" (Literal enum).
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.broadcast import publish
from app.models.agent import Agent
from app.runtime.agent_graph import _estimate_cost, build_agent_graph
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
        "tools": json.loads(agent.tools) if isinstance(agent.tools, str) else (agent.tools or []),
        "channels": json.loads(agent.channels) if isinstance(agent.channels, str) else (agent.channels or []),
        "max_iterations": agent.max_iterations,
        "memory_enabled": agent.memory_enabled,
        "forbidden_topics": json.loads(agent.forbidden_topics) if isinstance(agent.forbidden_topics, str) else (agent.forbidden_topics or []),
        "max_output_chars": agent.max_output_chars,
    }


async def _load_active_agents(db: AsyncSession) -> list[Agent]:
    result = await db.execute(select(Agent).where(Agent.is_active == True))  # noqa: E712
    return list(result.scalars().all())


async def _load_agents_by_ids(db: AsyncSession, agent_ids: list[int]) -> list[Agent]:
    result = await db.execute(
        select(Agent).where(Agent.id.in_(agent_ids), Agent.is_active == True)  # noqa: E712
    )
    agents = list(result.scalars().all())
    order = {aid: i for i, aid in enumerate(agent_ids)}
    agents.sort(key=lambda a: order.get(a.id, 999))
    return agents


def _deduplicate_agents(agents: list[Agent]) -> list[Agent]:
    seen: set[str] = set()
    unique: list[Agent] = []
    for agent in agents:
        if agent.name not in seen:
            seen.add(agent.name)
            unique.append(agent)
        else:
            logger.warning("Duplicate agent name '%s' (id=%s) — skipped.", agent.name, agent.id)
    return unique


def _split_agents(agents: list[Agent]) -> tuple[dict | None, list[dict]]:
    """
    Split agents into orchestrator + specialists.
    Uses exact role == "orchestrator" match (Literal enum — no string search needed).
    Falls back to first agent if none has orchestrator role.
    """
    orchestrator = None
    specialists = []

    for agent in agents:
        if agent.role == "orchestrator" and orchestrator is None:
            orchestrator = _agent_to_dict(agent)
        else:
            specialists.append(_agent_to_dict(agent))

    if orchestrator is None and agents:
        logger.warning(
            "No orchestrator role found — using first agent '%s' as fallback.",
            agents[0].name,
        )
        orchestrator = _agent_to_dict(agents[0])
        specialists = [_agent_to_dict(a) for a in agents[1:]]

    return orchestrator, specialists


async def run_workflow(
    db: AsyncSession,
    run_id: int,
    user_input: str,
    agent_ids: list[int] | None = None,
) -> WorkflowState:
    if agent_ids is not None:
        raw_agents = await _load_agents_by_ids(db, agent_ids)
        if not raw_agents:
            logger.warning("No active agents found for the provided agent_ids — falling back.")
            raw_agents = await _load_active_agents(db)
    else:
        raw_agents = await _load_active_agents(db)

    agents = _deduplicate_agents(raw_agents)

    if len(agents) < 2:
        logger.warning("Fewer than 2 active agents — falling back to demo graph.")
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
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        return await graph.ainvoke(initial_state)

    orchestrator, specialists = _split_agents(agents)

    if not specialists:
        logger.error("No specialist agents available.")
        return {
            "user_input": user_input, "current_step": "error",
            "research_notes": "", "final_response": "No specialist agents configured.",
            "status": "failed", "routing_decision": "", "routing_reason": "",
            "tool_calls": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

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
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

    result = await graph.ainvoke(initial_state)

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

    for tc in result.get("tool_calls", []):
        msg = f"Tool called: {tc['tool']}({tc['input']}) → {tc['result'][:200]}"
        await add_message(db, run_id, result.get("routing_decision", "agent"),
                          msg, receiver=None, message_type="tool_call")
        await publish({"run_id": run_id, "sender": result.get("routing_decision", "agent"),
                       "receiver": None, "content": msg, "type": "tool_call"})

    usage = result.get("token_usage") or {}
    total_tok = usage.get("total_tokens", 0)
    cost = _estimate_cost(orchestrator.get("model", ""), usage)
    token_msg = (
        f"Tokens used: {total_tok} "
        f"(prompt={usage.get('prompt_tokens',0)}, completion={usage.get('completion_tokens',0)}) "
        f"| Estimated cost: ${cost:.6f}"
    )
    await add_message(db, run_id, "system", token_msg, receiver=None, message_type="log")
    await publish({"run_id": run_id, "sender": "system", "receiver": None,
                   "content": token_msg, "type": "log"})

    await add_message(db, run_id, result.get("routing_decision", "agent"),
                      result["final_response"], receiver="user", message_type="output")
    await publish({"run_id": run_id, "sender": result.get("routing_decision", "agent"),
                   "receiver": "user", "content": result["final_response"], "type": "output"})

    return result


async def run_demo_workflow(
    db: AsyncSession,
    run_id: int,
    user_input: str,
    agent_ids: list[int] | None = None,
) -> WorkflowState:
    return await run_workflow(db, run_id, user_input, agent_ids=agent_ids)
