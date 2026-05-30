from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class WorkflowState(TypedDict):
    user_input: str
    current_step: str
    research_notes: str
    final_response: str
    status: str
    routing_decision: str
    routing_reason: str
    tool_calls: list[dict]
    token_usage: Any
    # Schedule intent extracted by orchestrator
    schedule_intent: dict | None     # {"cron": str, "prompt": str} or None
    # Memory context injected by orchestrator for the specialist
    memory_context: str              # formatted history string passed to specialist
