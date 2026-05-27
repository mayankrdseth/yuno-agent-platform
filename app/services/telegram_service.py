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
        "Send me a research or workflow task and I'll run it through the multi-agent system.\n\n"
        "Example:\n"
        "Research the benefits of async Python for scalable APIs."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from app.db.session import AsyncSessionLocal
    from app.models.workflow_run import WorkflowRun
    from app.services.run_service import complete_run, create_run
    from app.services.workflow_service import run_demo_workflow

    if not update.message or not update.message.text:
        return

    user_message = update.message.text.strip()
    normalized_message = user_message.lower()

    if normalized_message in GREETING_INPUTS:
        await update.message.reply_text(
            "👋 Hi! I'm your agent orchestration demo bot.\n\n"
            "Send me a real research or workflow request, for example:\n"
            "\"Summarize the benefits of multi-agent systems for customer support.\""
        )
        return

    await update.message.reply_text(
        "⚙️ Running multi-agent workflow... please wait."
    )

    async with AsyncSessionLocal() as db:
        run = await create_run(db, "telegram-workflow", user_message)
        result = await run_demo_workflow(db, run.id, user_message)

        run = await db.get(WorkflowRun, run.id)
        if run:
            await complete_run(db, run, result["final_response"])

    await update.message.reply_text(
        f"✅ Workflow complete!\n\n"
        f"Research notes:\n{result['research_notes']}\n\n"
        f"Final response:\n{result['final_response']}"
    )


async def setup_telegram_handlers():
    app = get_telegram_app()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await app.initialize()
    await app.start()
    return app