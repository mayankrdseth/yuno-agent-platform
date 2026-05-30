"""
Workflow service.

Model B: the canvas is the workflow definition.

Orchestrator owns the memory:
  - Memory is fetched by agent_id (orchestrator) + session_key before graph runs
  - After graph completes, the (human, ai) turn is saved back
  - session_key: "ui_session" for browser UI, "telegram_{chat_id}" for Telegram

Schedule intent:
  - If orchestrator detects schedule intent, result["schedule_intent"] is non-null
  - workflow_service registers the APScheduler job and updates agent.schedule/schedule_prompt in DB
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
        "schedule": agent.schedule,
        "schedule_prompt": agent.schedule_prompt,
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
    orchestrator = None
    specialists = []
    for agent in agents:
        if agent.role == "orchestrator" and orchestrator is None:
            orchestrator = _agent_to_dict(agent)
        else:
            specialists.append(_agent_to_dict(agent))
    if orchestrator is None and agents:
        logger.warning("No orchestrator found — using first agent '%s' as fallback.", agents[0].name)
        orchestrator = _agent_to_dict(agents[0])
        specialists = [_agent_to_dict(a) for a in agents[1:]]
    return orchestrator, specialists


async def run_workflow(
    db: AsyncSession,
    run_id: int,
    user_input: str,
    agent_ids: list[int] | None = None,
    session_key: str = "ui_session",
) -> WorkflowState:
    if agent_ids is not None:
        raw_agents = await _load_agents_by_ids(db, agent_ids)
        if not raw_agents:
            logger.warning("No active agents for agent_ids — falling back.")
            raw_agents = await _load_active_agents(db)
    else:
        raw_agents = await _load_active_agents(db)

    agents = _deduplicate_agents(raw_agents)

    if len(agents) < 2:
        logger.warning("Fewer than 2 agents — falling back to demo graph.")
        from app.runtime.demo_graph import build_demo_graph
        graph = build_demo_graph()
        initial_state: WorkflowState = {
            "user_input": user_input, "current_step": "start",
            "research_notes": "", "final_response": "", "status": "pending",
            "routing_decision": "", "routing_reason": "",
            "tool_calls": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "schedule_intent": None, "memory_context": "",
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
            "schedule_intent": None, "memory_context": "",
        }

    # ── Memory: fetch last N turns for this orchestrator + session ──────────
    memory_turns: list[dict] = []
    if orchestrator.get("memory_enabled"):
        from app.services.memory_service import get_memory
        # Find the orchestrator Agent ORM object to get its id
        orch_id = orchestrator["id"]
        max_turns = orchestrator.get("max_iterations", 5)
        memory_turns = await get_memory(db, orch_id, session_key, max_turns=max_turns)
        logger.debug("Memory loaded: %d turns for agent_id=%s session=%s", len(memory_turns) // 2, orch_id, session_key)

    # ── Broadcast + persist user message ────────────────────────────────────
    await add_message(db, run_id, "user", user_input, receiver=orchestrator["name"], message_type="input")
    await publish({"run_id": run_id, "sender": "user", "receiver": orchestrator["name"],
                   "content": user_input, "type": "input"})

    graph = build_agent_graph(
        orchestrator=orchestrator,
        specialists=specialists,
        memory_turns=memory_turns,
    )

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
        "schedule_intent": None,
        "memory_context": "",
    }

    result = await graph.ainvoke(initial_state)

    # ── Handle schedule intent ───────────────────────────────────────────────
    schedule_intent = result.get("schedule_intent")
    if schedule_intent:
        cron = schedule_intent.get("cron", "")
        prompt = schedule_intent.get("prompt", user_input)
        orch_agent_id = orchestrator["id"]
        logger.info("Schedule intent detected: agent_id=%s cron='%s' prompt='%s'", orch_agent_id, cron, prompt)
        # Persist schedule to agent DB record
        agent_obj = await db.get(Agent, orch_agent_id)
        if agent_obj:
            agent_obj.schedule = cron
            agent_obj.schedule_prompt = prompt
            await db.commit()
        # Register APScheduler job
        from app.services.scheduler_service import register_agent_job
        register_agent_job(orch_agent_id, cron, prompt)
        await add_message(db, run_id, "system",
                          f"Schedule registered: cron='{cron}' prompt='{prompt}'",
                          receiver=None, message_type="log")
        await publish({"run_id": run_id, "sender": "system", "receiver": None,
                       "content": f"Schedule registered: {cron}", "type": "log"})

    # ── Save memory turn (only for real completed runs, not scheduled stubs) ─
    if orchestrator.get("memory_enabled") and not schedule_intent and result.get("final_response"):
        from app.services.memory_service import save_turn
        await save_turn(
            db,
            agent_id=orchestrator["id"],
            session_key=session_key,
            human_message=user_input,
            ai_message=result["final_response"],
        )

    # ── Broadcast routing + tool call messages ───────────────────────────────
    await add_message(
        db, run_id, orchestrator["name"],
        f"Routing to {result.get('routing_decision', '?')} — {result.get('routing_reason', '')}",
        receiver=result.get("routing_decision", ""), message_type="log",
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
    session_key: str = "ui_session",
) -> WorkflowState:
    return await run_workflow(db, run_id, user_input, agent_ids=agent_ids, session_key=session_key)
