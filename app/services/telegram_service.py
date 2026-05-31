import html
import logging
import re

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_application: Application | None = None

GREETING_INPUTS = {"/start", "start", "hi", "hello", "hey", "help"}


def _safe_html(text: str) -> str:
    """Escape text for Telegram HTML parse_mode.

    Telegram HTML only supports <b>, <i>, <code>, <pre>, <a>.
    Escape everything else so arbitrary LLM output never breaks sending.
    """
    return html.escape(str(text), quote=False)


def get_telegram_app() -> Application:
    global _application
    if _application is None:
        _application = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .updater(None)
            .build()
        )
    return _application


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hello! I'm the Yuno Agent Platform bot.\n\n"
        "I route your requests to the right specialist agent automatically.\n\n"
        "Try asking me anything, for example:\n"
        "• What is the speed of light?\n"
        "• Calculate 15% of 2400\n"
        "• Who is Elon Musk?\n"
        "• What is today's date?\n\n"
        "📅 You can also schedule tasks naturally:\n"
        "• \"Every morning at 9am summarise today's AI news\"\n"
        "• \"Every Monday give me top ML papers\"\n\n"
        "Commands:\n"
        "/forget — clear my memory of our conversation\n"
        "/memory — show what I remember\n"
        "/schedule — list active schedules\n"
        "/unschedule — cancel the active schedule"
    )


async def forget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear conversation memory for this Telegram user."""
    from app.db.session import AsyncSessionLocal
    from app.services.memory_service import clear_memory
    from app.models.agent import Agent
    from sqlalchemy import select

    chat_id = update.effective_chat.id
    session_key = f"telegram_{chat_id}"

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(Agent.role == "orchestrator", Agent.is_active == True)  # noqa: E712
        )
        orchestrators = result.scalars().all()
        total_deleted = 0
        for orch in orchestrators:
            total_deleted += await clear_memory(db, orch.id, session_key=session_key)

    await update.message.reply_text(
        "✅ Memory cleared! I've forgotten our conversation history.\n"
        "Starting fresh from your next message."
    )
    logger.info("Memory cleared via /forget: session=%s deleted=%d", session_key, total_deleted)


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the last few remembered turns for this user."""
    from app.db.session import AsyncSessionLocal
    from app.services.memory_service import get_memory
    from app.models.agent import Agent
    from sqlalchemy import select

    chat_id = update.effective_chat.id
    session_key = f"telegram_{chat_id}"

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(Agent.role == "orchestrator", Agent.is_active == True)  # noqa: E712
        )
        orchestrator = result.scalars().first()
        if not orchestrator:
            await update.message.reply_text("No orchestrator agent found.")
            return
        turns = await get_memory(db, orchestrator.id, session_key, max_turns=3)

    if not turns:
        await update.message.reply_text(
            "🧠 I don't have any memory of our conversation yet.\n"
            "Start chatting and I'll remember our exchanges!"
        )
        return

    lines = ["🧠 <b>Here's what I remember from our conversation:</b>\n"]
    for m in turns:
        prefix = "👤 You" if m["role"] == "human" else "🤖 Me"
        content = _safe_html(m["content"][:200] + ("..." if len(m["content"]) > 200 else ""))
        lines.append(f"{prefix}: {content}")
    lines.append("\n<i>Use /forget to clear this memory.</i>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List active schedules."""
    from app.db.session import AsyncSessionLocal
    from app.models.agent import Agent
    from sqlalchemy import select
    from app.services.scheduler_service import get_scheduler

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(Agent.schedule.is_not(None), Agent.is_active == True)  # noqa: E712
        )
        scheduled_agents = result.scalars().all()

    if not scheduled_agents:
        await update.message.reply_text(
            "📅 No active schedules.\n"
            "To schedule a task, just tell me naturally:\n"
            "\"Every morning at 9am summarise today's AI news\""
        )
        return

    scheduler = get_scheduler()
    lines = ["📅 <b>Active Schedules:</b>\n"]
    for agent in scheduled_agents:
        job_id = f"agent_schedule_{agent.id}"
        job = scheduler.get_job(job_id)
        next_run = str(job.next_run_time) if job and job.next_run_time else "unknown"
        lines.append(
            f"• <b>{_safe_html(agent.name)}</b>\n"
            f"  Cron: <code>{_safe_html(agent.schedule)}</code>\n"
            f"  Task: {_safe_html(agent.schedule_prompt[:80])}\n"
            f"  Next run: {_safe_html(next_run)}\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def unschedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel the schedule for the primary orchestrator agent."""
    from app.db.session import AsyncSessionLocal
    from app.models.agent import Agent
    from sqlalchemy import select
    from app.services.scheduler_service import remove_agent_job

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(
                Agent.role == "orchestrator",
                Agent.schedule.is_not(None),
                Agent.is_active == True,  # noqa: E712
            )
        )
        agents = result.scalars().all()
        if not agents:
            await update.message.reply_text("No active schedule found to cancel.")
            return
        for agent in agents:
            remove_agent_job(agent.id)
            agent.schedule = None
            agent.schedule_prompt = None
        await db.commit()

    await update.message.reply_text(
        "✅ Schedule cancelled! I won't run any more automatic tasks.\n"
        "You can set a new schedule anytime by telling me naturally."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from app.db.session import AsyncSessionLocal
    from app.models.workflow_run import WorkflowRun
    from app.services.run_service import complete_run, create_run
    from app.services.workflow_service import run_workflow

    if not update.message or not update.message.text:
        return

    user_message = update.message.text.strip()
    normalized = user_message.lower()
    chat_id = update.effective_chat.id
    session_key = f"telegram_{chat_id}"

    if normalized in GREETING_INPUTS:
        await update.message.reply_text(
            "👋 Hi! Send me any question or task and I'll route it to the best agent.\n\n"
            "Examples:\n"
            "\"Summarise the benefits of multi-agent systems\"\n"
            "\"What is 234 * 17?\"\n"
            "\"Tell me about the Eiffel Tower\"\n\n"
            "📅 Schedule tasks naturally:\n"
            "\"Every morning at 9am summarise today's AI news\""
        )
        return

    await update.message.reply_text("⚙️ Running multi-agent workflow... please wait.")

    async with AsyncSessionLocal() as db:
        run = await create_run(db, "telegram-workflow", user_message)

        try:
            result = await run_workflow(
                db, run.id, user_message,
                session_key=session_key,
            )

            run_obj = await db.get(WorkflowRun, run.id)
            if run_obj:
                await complete_run(db, run_obj, result["final_response"])

            # ── Schedule confirmation ──────────────────────────────────────
            schedule_intent = result.get("schedule_intent")
            if schedule_intent:
                from app.services.scheduler_service import get_scheduler
                scheduler = get_scheduler()
                from app.models.agent import Agent
                from sqlalchemy import select
                orch_result = await db.execute(
                    select(Agent).where(Agent.role == "orchestrator", Agent.is_active == True)  # noqa: E712
                )
                orch = orch_result.scalars().first()
                next_run = "(check /schedule for next run time)"
                if orch:
                    job = scheduler.get_job(f"agent_schedule_{orch.id}")
                    if job and job.next_run_time:
                        next_run = str(job.next_run_time)

                await update.message.reply_text(
                    f"✅ <b>Schedule set!</b>\n\n"
                    f"Cron: <code>{_safe_html(schedule_intent['cron'])}</code>\n"
                    f"Task: {_safe_html(schedule_intent['prompt'])}\n"
                    f"Next run: {_safe_html(next_run)}\n\n"
                    f"Use /schedule to view all schedules\n"
                    f"Use /unschedule to cancel",
                    parse_mode="HTML",
                )
                return

            # ── Normal response ────────────────────────────────────────────
            routed_to = result.get("routing_decision", "agent")
            reason = result.get("routing_reason", "")
            tool_calls = result.get("tool_calls", [])

            # Build header in HTML (safe, no LLM content here)
            header_lines = [f"✅ <b>Workflow complete</b> — handled by <b>{_safe_html(routed_to)}</b>"]
            if reason:
                header_lines.append(f"<i>Reason: {_safe_html(reason)}</i>")
            if tool_calls:
                tools_used = ", ".join(tc.get("tool", "?") for tc in tool_calls)
                header_lines.append(f"🔧 Tools used: <code>{_safe_html(tools_used)}</code>")

            header = "\n".join(header_lines)

            # LLM response: escape all HTML special chars so it renders as
            # plain text inside the HTML message — no parse errors possible.
            body = _safe_html(result["final_response"])

            full_message = f"{header}\n\n{body}"

            # Telegram messages cap at 4096 chars
            if len(full_message) > 4096:
                full_message = full_message[:4090] + "…"

            await update.message.reply_text(full_message, parse_mode="HTML")

        except Exception as exc:
            logger.exception("Workflow error for run %s: %s", run.id, exc)
            await update.message.reply_text(
                "❌ Something went wrong while processing your request. Please try again."
            )


async def setup_telegram_handlers():
    app = get_telegram_app()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("forget", forget_command))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(CommandHandler("unschedule", unschedule_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await app.initialize()
    await app.start()
    return app
