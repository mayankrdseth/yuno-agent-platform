import json
import logging

from sqlalchemy import select

from app.db.base import Base
from app.db.session import engine, AsyncSessionLocal
from app.models import agent  # noqa: F401
from app.models import workflow_template  # noqa: F401
from app.models.workflow_template import WorkflowTemplate

logger = logging.getLogger(__name__)

# ─── Pre-built templates ────────────────────────────────────────────────────
# These use agent names (not IDs) because IDs are not known at seed time.
# The frontend resolves names → IDs when loading a template.

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
                # Store agent names in agent_ids field for built-in templates
                # Frontend resolves names → actual IDs at load time
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
    await _seed_builtin_templates()
