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
    routing_decision: str            # primary target (backwards compat, always set)
    routing_targets: list[str]       # all target agent names (1 for single, N for compound queries)
    routing_reason: str
    tool_calls: list[dict]
    token_usage: Any
    # Schedule intent extracted by orchestrator
    schedule_intent: dict | None     # {"cron": str, "prompt": str} or None
    # Memory context injected by orchestrator for the specialist
    memory_context: str              # formatted history string passed to specialist
    # Retry / feedback loop
    retry_count: int                 # how many specialist retries have happened
    needs_retry: bool                # orchestrator sets True to trigger a re-route
    last_specialist_output: str      # raw output from the previous specialist attempt
