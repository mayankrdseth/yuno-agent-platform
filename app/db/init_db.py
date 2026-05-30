import json
import logging

from sqlalchemy import select

from app.db.base import Base
from app.db.session import engine, AsyncSessionLocal
from app.models import agent  # noqa: F401
from app.models import workflow_template  # noqa: F401
from app.models import conversation_memory  # noqa: F401  — registers table
from app.models.agent import Agent
from app.models.workflow_template import WorkflowTemplate

logger = logging.getLogger(__name__)

# ─── Pre-built templates ────────────────────────────────────────────────────
BUILTIN_TEMPLATES = [
    {
        "name": "Research Hub",
        "description": "ResearchOrchestrator routes to Researcher (web/wiki) for factual queries or Mathematician (calculator/datetime) for numeric tasks.",
        "agent_names": ["ResearchOrchestrator", "Researcher", "Mathematician"],
        "edge_pairs": [
            ("ResearchOrchestrator", "Researcher"),
            ("ResearchOrchestrator", "Mathematician"),
        ],
        "is_builtin": 1,
    },
    {
        "name": "Support Triage",
        "description": "SupportOrchestrator triages incoming requests: general queries go to Supporter, urgent/complex cases go to Escalator.",
        "agent_names": ["SupportOrchestrator", "Supporter", "Escalator"],
        "edge_pairs": [
            ("SupportOrchestrator", "Supporter"),
            ("SupportOrchestrator", "Escalator"),
        ],
        "is_builtin": 1,
    },
]

# ─── Pre-built agents ────────────────────────────────────────────────────────
BUILTIN_AGENTS = [
    {
        "name": "ResearchOrchestrator",
        "role": "orchestrator",
        "system_prompt": (
            "You are the Research Orchestrator. Read the user request and decide which specialist "
            "should handle it:\n"
            "- Send factual, knowledge, or information queries to Researcher.\n"
            "- Send numeric, calculation, date, or unit conversion queries to Mathematician.\n"
            "Respond ONLY with JSON: {\"target\": \"<agent_name>\", \"reason\": \"<short reason>\"}"
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": [],
        "channels": ["telegram"],
        "is_active": True,
        "max_iterations": 5,
        "memory_enabled": True,
        "forbidden_topics": [],
        "max_output_chars": None,
    },
    {
        "name": "Researcher",
        "role": "agent",
        "system_prompt": (
            "You are the Researcher agent. Find accurate, up-to-date information using your tools. "
            "Structure every answer as: 1) one-sentence summary, 2) key findings as bullet points, "
            "3) a short conclusion. Be factual and concise."
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": ["web_search", "wikipedia"],
        "channels": [],
        "is_active": True,
        "max_iterations": 5,
        "memory_enabled": False,
        "forbidden_topics": [],
        "max_output_chars": None,
    },
    {
        "name": "Mathematician",
        "role": "agent",
        "system_prompt": (
            "You are the Mathematician agent. Solve numeric problems, equations, unit conversions, "
            "and date/time calculations with precision. Always show your working clearly. "
            "Use the calculator tool for arithmetic and the datetime tool for date-related queries."
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": ["calculator", "datetime"],
        "channels": [],
        "is_active": True,
        "max_iterations": 5,
        "memory_enabled": False,
        "forbidden_topics": [],
        "max_output_chars": None,
    },
    {
        "name": "SupportOrchestrator",
        "role": "orchestrator",
        "system_prompt": (
            "You are the Support Orchestrator. Read the incoming support request and triage it:\n"
            "- Send general, routine, or informational queries to Supporter.\n"
            "- Send urgent, complex, unresolved, or escalation requests to Escalator.\n"
            "Respond ONLY with JSON: {\"target\": \"<agent_name>\", \"reason\": \"<short reason>\"}"
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": [],
        "channels": ["telegram"],
        "is_active": True,
        "max_iterations": 5,
        "memory_enabled": True,
        "forbidden_topics": [],
        "max_output_chars": None,
    },
    {
        "name": "Supporter",
        "role": "agent",
        "system_prompt": (
            "You are the Supporter agent. Handle general customer queries with empathy and clarity. "
            "Always: acknowledge the concern, provide a clear and helpful answer, "
            "and close with an offer to assist further. Keep responses friendly and concise."
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": [],
        "channels": [],
        "is_active": True,
        "max_iterations": 3,
        "memory_enabled": False,
        "forbidden_topics": [],
        "max_output_chars": None,
    },
    {
        "name": "Escalator",
        "role": "agent",
        "system_prompt": (
            "You are the Escalator agent. Handle urgent, complex, or unresolved support cases. "
            "Use the datetime tool to timestamp escalation notes. "
            "Provide a structured escalation report: issue summary, urgency level, "
            "recommended next action, and a timestamped note for the support team."
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": ["datetime"],
        "channels": [],
        "is_active": True,
        "max_iterations": 5,
        "memory_enabled": False,
        "forbidden_topics": [],
        "max_output_chars": None,
    },
]


async def _seed_builtin_agents() -> None:
    async with AsyncSessionLocal() as db:
        for agent_def in BUILTIN_AGENTS:
            result = await db.execute(select(Agent).where(Agent.name == agent_def["name"]))
            if result.scalar_one_or_none():
                continue
            db.add(Agent(
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
            ))
            logger.info("Seeded agent: %s (%s)", agent_def["name"], agent_def["role"])
        await db.commit()


async def _seed_builtin_templates() -> None:
    async with AsyncSessionLocal() as db:
        for tpl_def in BUILTIN_TEMPLATES:
            result = await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.name == tpl_def["name"]))
            if result.scalar_one_or_none():
                continue
            db.add(WorkflowTemplate(
                name=tpl_def["name"],
                description=tpl_def["description"],
                agent_ids=json.dumps(tpl_def["agent_names"]),
                edges=json.dumps([{"source": s, "target": t} for s, t in tpl_def["edge_pairs"]]),
                is_builtin=1,
            ))
            logger.info("Seeded template: %s", tpl_def["name"])
        await db.commit()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_builtin_agents()
    await _seed_builtin_templates()
