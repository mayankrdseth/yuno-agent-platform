import json
import logging

from sqlalchemy import select

from app.db.base import Base
from app.db.session import engine, AsyncSessionLocal
from app.models import agent  # noqa: F401
from app.models import workflow_template  # noqa: F401
from app.models.agent import Agent
from app.models.workflow_template import WorkflowTemplate

logger = logging.getLogger(__name__)

# ─── Pre-built templates ────────────────────────────────────────────────────

BUILTIN_TEMPLATES = [
    {
        "name": "Research & Summarize",
        "description": "Orchestrator routes a research query to the Researcher who uses web_search / wikipedia to produce a structured summary.",
        "agent_names": ["Orchestrator", "Researcher"],
        "edge_pairs": [("Orchestrator", "Researcher")],
        "is_builtin": 1,
    },
    {
        "name": "Support Triage",
        "description": "Orchestrator triages an incoming support request: routes technical questions to Researcher and general queries to Supporter.",
        "agent_names": ["Orchestrator", "Supporter", "Researcher"],
        "edge_pairs": [("Orchestrator", "Supporter"), ("Orchestrator", "Researcher")],
        "is_builtin": 1,
    },
]

# ─── Pre-built agents ────────────────────────────────────────────────────────
# These agents match the names used in BUILTIN_TEMPLATES above.
# Seeding is idempotent — skipped if an agent with the same name already exists.

BUILTIN_AGENTS = [
    {
        "name": "Orchestrator",
        "role": "Orchestrator",
        "system_prompt": (
            "You are the Orchestrator agent. Your only job is to read the user's request "
            "and decide which specialist agent should handle it. "
            "You do NOT answer the question yourself. "
            "Respond with a JSON object: {\"target\": \"<agent_name>\", \"reason\": \"<short reason>\"}."
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": [],
        "channels": [],
        "is_active": True,
        "max_iterations": 3,
        "memory_enabled": True,
        "forbidden_topics": [],
        "max_output_chars": None,
    },
    {
        "name": "Researcher",
        "role": "Research Specialist",
        "system_prompt": (
            "You are the Researcher agent. You specialise in finding accurate, up-to-date "
            "information on any topic. Use the web_search or wikipedia tool when available. "
            "Always structure your answer with: a one-sentence summary, key findings as bullet "
            "points, and a short conclusion. Be factual and concise."
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": ["web_search", "wikipedia"],
        "channels": [],
        "is_active": True,
        "max_iterations": 5,
        "memory_enabled": True,
        "forbidden_topics": [],
        "max_output_chars": None,
    },
    {
        "name": "Supporter",
        "role": "Customer Support Specialist",
        "system_prompt": (
            "You are the Supporter agent. You handle general customer support queries with "
            "empathy, clarity, and professionalism. "
            "Always acknowledge the user's concern, provide a clear answer or next steps, "
            "and end with an offer to help further. Keep responses friendly and concise."
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": [],
        "channels": [],
        "is_active": True,
        "max_iterations": 3,
        "memory_enabled": True,
        "forbidden_topics": [],
        "max_output_chars": None,
    },
]


async def _seed_builtin_agents() -> None:
    """Insert built-in agents if they don't already exist (idempotent by name)."""
    async with AsyncSessionLocal() as db:
        for agent_def in BUILTIN_AGENTS:
            result = await db.execute(
                select(Agent).where(Agent.name == agent_def["name"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                continue

            agent_obj = Agent(
                name=agent_def["name"],
                role=agent_def["role"],
                system_prompt=agent_def["system_prompt"],
                model=agent_def["model"],
                tools=json.dumps(agent_def["tools"]),
                channels=json.dumps(agent_def["channels"]),
                is_active=agent_def["is_active"],
                max_iterations=agent_def["max_iterations"],
                memory_enabled=agent_def["memory_enabled"],
                forbidden_topics=json.dumps(agent_def["forbidden_topics"]),
                max_output_chars=agent_def["max_output_chars"],
            )
            db.add(agent_obj)
            logger.info("Seeded built-in agent: %s (%s)", agent_def["name"], agent_def["role"])

        await db.commit()


async def _seed_builtin_templates() -> None:
    """Insert built-in templates if they don't already exist (idempotent)."""
    async with AsyncSessionLocal() as db:
        for tpl_def in BUILTIN_TEMPLATES:
            result = await db.execute(
                select(WorkflowTemplate).where(WorkflowTemplate.name == tpl_def["name"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                continue

            tpl = WorkflowTemplate(
                name=tpl_def["name"],
                description=tpl_def["description"],
                agent_ids=json.dumps(tpl_def["agent_names"]),
                edges=json.dumps(
                    [{"source": s, "target": t} for s, t in tpl_def["edge_pairs"]]
                ),
                is_builtin=1,
            )
            db.add(tpl)
            logger.info("Seeded built-in template: %s", tpl_def["name"])

        await db.commit()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_builtin_agents()      # agents first — templates reference their names
    await _seed_builtin_templates()
