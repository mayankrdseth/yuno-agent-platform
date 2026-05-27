import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_application: Application | None = None

GREETING_INPUTS = {"/start", "start", "hi", "hello", "hey", "help"}


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
        "• What is today's date?"
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

    if normalized in GREETING_INPUTS:
        await update.message.reply_text(
            "👋 Hi! Send me any question or task and I'll route it to the best agent.\n\n"
            "Examples:\n"
            "\"Summarise the benefits of multi-agent systems\"\n"
            "\"What is 234 * 17?\"\n"
            "\"Tell me about the Eiffel Tower\""
        )
        return

    await update.message.reply_text("⚙️ Running multi-agent workflow... please wait.")

    async with AsyncSessionLocal() as db:
        run = await create_run(db, "telegram-workflow", user_message)

        try:
            result = await run_workflow(db, run.id, user_message)

            run = await db.get(WorkflowRun, run.id)
            if run:
                await complete_run(db, run, result["final_response"])

            # Build response text
            routed_to = result.get("routing_decision", "agent")
            reason = result.get("routing_reason", "")
            tool_calls = result.get("tool_calls", [])

            lines = [f"✅ *Workflow complete* — handled by *{routed_to}*"]
            if reason:
                lines.append(f"_Reason: {reason}_")
            if tool_calls:
                tools_used = ", ".join(tc["tool"] for tc in tool_calls)
                lines.append(f"🔧 Tools used: {tools_used}")
            lines.append("")
            lines.append(result["final_response"])

            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="Markdown",
            )

        except Exception as exc:
            logger.exception("Workflow error for run %s: %s", run.id, exc)
            await update.message.reply_text(
                "❌ Something went wrong while processing your request. Please try again."
            )


async def setup_telegram_handlers():
    app = get_telegram_app()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await app.initialize()
    await app.start()
    return app
