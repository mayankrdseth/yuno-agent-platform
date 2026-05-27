from pydantic import BaseModel, Field


class WorkflowRunRequest(BaseModel):
    user_input: str = Field(min_length=1)


class WorkflowRunResponse(BaseModel):
    current_step: str
    research_notes: str
    final_response: str
    status: str


class WorkflowRunSummary(BaseModel):
    id: int
    workflow_name: str
    status: str
    input_text: str
    output_text: str | None
    created_at: str
    completed_at: str | None


class WorkflowMessageRead(BaseModel):
    id: int
    run_id: int
    sender: str
    receiver: str | None
    message_type: str
    content: str
    created_at: str