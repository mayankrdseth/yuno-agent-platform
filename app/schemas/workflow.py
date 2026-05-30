from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowEdge(BaseModel):
    source: str
    target: str


class WorkflowRunRequest(BaseModel):
    user_input: str = Field(min_length=1)
    agent_ids: list[int] | None = None
    edges: list[WorkflowEdge] | None = None
    session_key: str = "ui_session"


class WorkflowRunResponse(BaseModel):
    current_step: str
    research_notes: str
    final_response: str
    status: str
    schedule_intent: dict | None = None


class WorkflowRunSummary(BaseModel):
    id: int
    workflow_name: str
    status: str
    input_text: str
    output_text: str | None
    created_at: str
    completed_at: str | None
    total_tokens: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    estimated_cost_usd: float | None = None


class WorkflowMessageRead(BaseModel):
    id: int
    run_id: int
    sender: str
    receiver: str | None
    message_type: str
    content: str
    created_at: str
