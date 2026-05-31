import json
import logging

from sqlalchemy import select, text

from app.db.base import Base
from app.db.session import engine, AsyncSessionLocal
from app.models import agent  # noqa: F401
from app.models import workflow_template  # noqa: F401
from app.models import conversation_memory  # noqa: F401
from app.models.agent import Agent
from app.models.workflow_template import WorkflowTemplate

logger = logging.getLogger(__name__)

BUILTIN_TEMPLATES = [
    {
        "name": "Research Hub",
        "description": (
            "ResearchOrchestrator routes queries: factual lookups go to Researcher, "
            "research+summarise requests run as a pipeline (Researcher → Summariser), "
            "and compound queries fan out to both agents in parallel."
        ),
        "agent_names": ["ResearchOrchestrator", "Researcher", "Summariser"],
        "edge_pairs": [
            ("ResearchOrchestrator", "Researcher"),
            ("ResearchOrchestrator", "Summariser"),
            ("Researcher", "Summariser"),  # pipeline edge
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

BUILTIN_AGENTS = [
    {
        "name": "ResearchOrchestrator",
        "role": "orchestrator",
        "system_prompt": (
            "You are the Research Orchestrator. Analyse the user request and decide the routing mode:\n"
            "- SINGLE to Researcher: factual questions, information lookup, knowledge queries\n"
            "- PIPELINE [Researcher → Summariser]: when the user wants research AND a summary/brief/TL;DR\n"
            "- FANOUT [Researcher, Summariser]: when the query independently needs both agents\n"
            "- SCHEDULE: when the user wants to schedule a recurring task\n"
            "Respond ONLY with the routing JSON as instructed."
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": ["calculator", "datetime"],
        "channels": ["telegram"],
        "is_active": True,
        "max_iterations": 5,
        "memory_enabled": True,
        "forbidden_topics": [],
        "max_output_chars": None,
        "skills": ["routing", "intent_detection", "pipeline_orchestration"],
        "interaction_rules": [
            "always respond in JSON when routing",
            "never answer user queries directly",
            "use calculator tool for UTC timezone arithmetic when scheduling",
        ],
    },
    {
        "name": "Researcher",
        "role": "agent",
        "system_prompt": (
            "You are the Researcher agent. Find accurate, up-to-date information using your tools. "
            "Structure every answer as: 1) one-sentence summary, 2) key findings as bullet points, "
            "3) a short conclusion. Be factual, thorough, and cite sources where possible. "
            "Your output may be passed to a Summariser agent — provide complete, detailed research."
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": ["web_search", "wikipedia"],
        "channels": [],
        "is_active": True,
        "max_iterations": 5,
        "memory_enabled": False,
        "forbidden_topics": [],
        "max_output_chars": None,
        "skills": ["web_search", "summarisation", "fact_checking"],
        "interaction_rules": [
            "always cite sources when available",
            "structure answers with bullet points",
            "provide thorough detail — your output may be consumed by another agent",
        ],
    },
    {
        "name": "Summariser",
        "role": "agent",
        "system_prompt": (
            "You are the Summariser agent. Your job is to take detailed research or long-form content "
            "and condense it into a clear, well-structured brief. "
            "Always structure your output as: "
            "1) TL;DR (one sentence), "
            "2) Key points (3-5 bullets), "
            "3) Conclusion (1-2 sentences). "
            "Be concise. Remove redundancy. Preserve the most important facts. "
            "If given raw research notes from a Researcher agent, synthesise them — do not just repeat them."
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": ["web_search", "wikipedia"],
        "channels": [],
        "is_active": True,
        "max_iterations": 3,
        "memory_enabled": False,
        "forbidden_topics": [],
        "max_output_chars": None,
        "skills": ["summarisation", "content_condensing", "structured_briefs"],
        "interaction_rules": [
            "always output in TL;DR → key points → conclusion format",
            "never repeat the source material verbatim — synthesise it",
            "prioritise brevity and clarity over completeness",
        ],
    },
    {
        "name": "SupportOrchestrator",
        "role": "orchestrator",
        "system_prompt": (
            "You are the Support Orchestrator. Read the incoming support request and triage it:\n"
            "- Send general, routine, or informational queries to Supporter.\n"
            "- Send urgent, complex, unresolved, or escalation requests to Escalator.\n"
            "Respond ONLY with JSON: {\"routing_mode\": \"single\", \"target\": \"<agent_name>\", \"reason\": \"<short reason>\"}"
        ),
        "model": "llama-3.3-70b-versatile",
        "tools": ["calculator", "datetime"],
        "channels": ["telegram"],
        "is_active": True,
        "max_iterations": 5,
        "memory_enabled": True,
        "forbidden_topics": [],
        "max_output_chars": None,
        "skills": ["triage", "routing", "urgency_detection"],
        "interaction_rules": [
            "always respond in JSON when routing",
            "classify urgency before routing",
            "use calculator tool for UTC timezone arithmetic when scheduling",
        ],
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
        "skills": ["customer_support", "empathy", "communication"],
        "interaction_rules": [
            "always acknowledge the user's concern first",
            "end responses with an offer to help further",
        ],
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
        "skills": ["escalation", "incident_reporting", "urgency_classification"],
        "interaction_rules": [
            "always include a timestamp in escalation reports",
            "structure output as: summary / urgency / action / timestamp",
        ],
    },
]

_AGENT_MIGRATIONS = [
    ("schedule",          "VARCHAR(120)"),
    ("schedule_prompt",   "TEXT"),
    ("skills",            "TEXT NOT NULL DEFAULT '[]'"),
    ("interaction_rules", "TEXT NOT NULL DEFAULT '[]'"),
]


async def _migrate_agents_table() -> None:
    async with engine.begin() as conn:
        for col_name, col_def in _AGENT_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE agents ADD COLUMN {col_name} {col_def}"))
                logger.info("Migration: added column agents.%s", col_name)
            except Exception:
                pass


async def _seed_builtin_agents() -> None:
    """
    Insert new agents and UPDATE existing ones.
    Fields updated: skills, interaction_rules, forbidden_topics, system_prompt, tools.
    User-customisable fields preserved: model, channels, is_active, memory_enabled,
    max_iterations, max_output_chars, schedule, schedule_prompt.
    """
    async with AsyncSessionLocal() as db:
        for agent_def in BUILTIN_AGENTS:
            result = await db.execute(select(Agent).where(Agent.name == agent_def["name"]))
            existing = result.scalar_one_or_none()

            if existing is None:
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
                    skills=json.dumps(agent_def.get("skills", [])),
                    interaction_rules=json.dumps(agent_def.get("interaction_rules", [])),
                ))
                logger.info("Seeded agent: %s (%s)", agent_def["name"], agent_def["role"])
            else:
                existing.skills            = json.dumps(agent_def.get("skills", []))
                existing.interaction_rules = json.dumps(agent_def.get("interaction_rules", []))
                existing.forbidden_topics  = json.dumps(agent_def["forbidden_topics"])
                existing.system_prompt     = agent_def["system_prompt"]
                existing.tools             = json.dumps(agent_def["tools"])  # update tools too
                logger.info("Updated agent: %s", agent_def["name"])

        await db.commit()


async def _seed_builtin_templates() -> None:
    async with AsyncSessionLocal() as db:
        for tpl_def in BUILTIN_TEMPLATES:
            result = await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.name == tpl_def["name"]))
            existing = result.scalar_one_or_none()
            if existing is None:
                db.add(WorkflowTemplate(
                    name=tpl_def["name"],
                    description=tpl_def["description"],
                    agent_ids=json.dumps(tpl_def["agent_names"]),
                    edges=json.dumps([{"source": s, "target": t} for s, t in tpl_def["edge_pairs"]]),
                    is_builtin=1,
                ))
                logger.info("Seeded template: %s", tpl_def["name"])
            else:
                # Update template description and edges to reflect pipeline addition
                existing.description = tpl_def["description"]
                existing.agent_ids   = json.dumps(tpl_def["agent_names"])
                existing.edges       = json.dumps([{"source": s, "target": t} for s, t in tpl_def["edge_pairs"]])
                logger.info("Updated template: %s", tpl_def["name"])
        await db.commit()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _migrate_agents_table()
    await _seed_builtin_agents()
    await _seed_builtin_templates()
