from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.workflow_run import WorkflowRun
from app.runtime.agent_graph import _estimate_cost
from app.schemas.workflow import (
    WorkflowMessageRead,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowRunSummary,
)
from app.services.run_service import (
    complete_run,
    create_run,
    get_run,
    get_run_messages,
    list_runs,
)
from app.services.workflow_service import run_demo_workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("/demo-run", response_model=WorkflowRunResponse)
async def execute_demo_workflow(
    payload: WorkflowRunRequest,
    db: AsyncSession = Depends(get_db_session),
):
    if payload.agent_ids is not None and len(payload.agent_ids) < 2:
        raise HTTPException(
            status_code=400,
            detail="Add at least 2 agents to the workflow canvas before running.",
        )

    run = await create_run(db, "demo-workflow", payload.user_input)
    result = await run_demo_workflow(
        db,
        run.id,
        payload.user_input,
        agent_ids=payload.agent_ids,
    )

    run = await db.get(WorkflowRun, run.id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Extract token usage from result
    usage = result.get("token_usage") or {}
    total_tokens = usage.get("total_tokens") or None
    prompt_tokens = usage.get("prompt_tokens") or None
    completion_tokens = usage.get("completion_tokens") or None
    estimated_cost = _estimate_cost("", usage) if total_tokens else None

    await complete_run(
        db, run, result["final_response"],
        total_tokens=total_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimated_cost,
    )

    return WorkflowRunResponse(
        current_step=result["current_step"],
        research_notes=result["research_notes"],
        final_response=result["final_response"],
        status=result["status"],
    )


@router.get("/runs", response_model=list[WorkflowRunSummary])
async def get_workflow_runs(
    limit: int = 50,
    db: AsyncSession = Depends(get_db_session),
):
    runs = await list_runs(db, limit=limit)
    return [
        WorkflowRunSummary(
            id=run.id,
            workflow_name=run.workflow_name,
            status=run.status,
            input_text=run.input_text,
            output_text=run.output_text,
            created_at=str(run.created_at),
            completed_at=str(run.completed_at) if run.completed_at else None,
            total_tokens=run.total_tokens,
            prompt_tokens=run.prompt_tokens,
            completion_tokens=run.completion_tokens,
            estimated_cost_usd=run.estimated_cost_usd,
        )
        for run in runs
    ]


@router.get("/runs/{run_id}/messages", response_model=list[WorkflowMessageRead])
async def get_workflow_run_messages(
    run_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    run = await get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    messages = await get_run_messages(db, run_id)
    return [
        WorkflowMessageRead(
            id=msg.id,
            run_id=msg.run_id,
            sender=msg.sender,
            receiver=msg.receiver,
            message_type=msg.message_type,
            content=msg.content,
            created_at=str(msg.created_at),
        )
        for msg in messages
    ]
