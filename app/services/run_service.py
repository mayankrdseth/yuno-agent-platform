from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow_message import WorkflowMessage
from app.models.workflow_run import WorkflowRun


async def create_run(db: AsyncSession, workflow_name: str, input_text: str) -> WorkflowRun:
    run = WorkflowRun(
        workflow_name=workflow_name,
        status="running",
        input_text=input_text,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def add_message(
    db: AsyncSession,
    run_id: int,
    sender: str,
    content: str,
    receiver: str | None = None,
    message_type: str = "log",
) -> WorkflowMessage:
    message = WorkflowMessage(
        run_id=run_id,
        sender=sender,
        receiver=receiver,
        message_type=message_type,
        content=content,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def complete_run(db: AsyncSession, run: WorkflowRun, output_text: str) -> WorkflowRun:
    run.status = "completed"
    run.output_text = output_text
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)
    return run


async def list_runs(db: AsyncSession, limit: int = 50) -> list[WorkflowRun]:
    result = await db.execute(
        select(WorkflowRun).order_by(WorkflowRun.id.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_run(db: AsyncSession, run_id: int) -> WorkflowRun | None:
    return await db.get(WorkflowRun, run_id)


async def get_run_messages(db: AsyncSession, run_id: int) -> list[WorkflowMessage]:
    result = await db.execute(
        select(WorkflowMessage)
        .where(WorkflowMessage.run_id == run_id)
        .order_by(WorkflowMessage.id.asc())
    )
    return list(result.scalars().all())