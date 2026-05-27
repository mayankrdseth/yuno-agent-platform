from typing import Literal
from typing_extensions import TypedDict


class WorkflowState(TypedDict):
    user_input: str
    current_step: str
    research_notes: str
    final_response: str
    status: Literal["pending", "running", "completed", "failed"]