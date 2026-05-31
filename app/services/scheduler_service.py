"""
Scheduler service — APScheduler cron jobs for scheduled agent runs.

Schedules are stored on orchestrator agents:
  agent.schedule       : cron string e.g. "0 9 * * 1-5"
  agent.schedule_prompt: fixed input sent to the workflow when the cron fires

Jobs are registered at startup and hot-reloaded when an agent is PATCH-ed.

Timezone
--------
All cron expressions are stored and executed in UTC.
The LLM routing prompt instructs the model to convert any user-mentioned
timezone (IST, EST, PST, etc.) to UTC before emitting the cron expression,
so no server-side timezone configuration is required.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def _job_id(agent_id: int) -> str:
    return f"agent_schedule_{agent_id}"


async def _run_scheduled_agent(agent_id: int, prompt: str) -> None:
    """Fired by APScheduler — creates a normal workflow run tagged as 'scheduled'."""
    from app.services.run_service import complete_run, create_run
    from app.services.workflow_service import run_workflow

    logger.info("Scheduled run firing: agent_id=%s prompt='%s'", agent_id, prompt[:60])
    async with AsyncSessionLocal() as db:
        run = await create_run(db, "scheduled", prompt)
        try:
            result = await run_workflow(
                db, run.id, prompt,
                agent_ids=None,
                session_key=f"scheduled_{agent_id}",
            )
            run_obj = await db.get(
                __import__("app.models.workflow_run", fromlist=["WorkflowRun"]).WorkflowRun,
                run.id,
            )
            if run_obj:
                await complete_run(db, run_obj, result["final_response"])
        except Exception as exc:
            logger.exception("Scheduled run failed for agent_id=%s: %s", agent_id, exc)


def register_agent_job(agent_id: int, cron: str, prompt: str) -> None:
    """Add or replace a cron job for an agent (cron must be in UTC)."""
    scheduler = get_scheduler()
    job_id = _job_id(agent_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    try:
        trigger = CronTrigger.from_crontab(cron, timezone="UTC")
        scheduler.add_job(
            _run_scheduled_agent,
            trigger=trigger,
            id=job_id,
            kwargs={"agent_id": agent_id, "prompt": prompt},
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info("Scheduled job registered: agent_id=%s cron='%s' (UTC)", agent_id, cron)
    except Exception as exc:
        logger.error("Failed to register schedule for agent_id=%s cron='%s': %s", agent_id, cron, exc)


def remove_agent_job(agent_id: int) -> None:
    """Remove a cron job for an agent."""
    scheduler = get_scheduler()
    job_id = _job_id(agent_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Scheduled job removed: agent_id=%s", agent_id)


async def reload_all_jobs() -> None:
    """
    Load all active agents with a schedule from DB and register their cron jobs.
    Called at startup after init_db().
    """
    from app.models.agent import Agent
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(
                Agent.schedule.is_not(None),
                Agent.is_active == True,  # noqa: E712
            )
        )
        agents = result.scalars().all()

    for agent in agents:
        if agent.schedule and agent.schedule_prompt:
            register_agent_job(agent.id, agent.schedule, agent.schedule_prompt)

    logger.info("Scheduler: %d job(s) loaded from DB.", len(agents))


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler started.")
