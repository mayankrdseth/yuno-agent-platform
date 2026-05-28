from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class AgentBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: Literal["orchestrator", "agent"] = "agent"
    system_prompt: str = Field(min_length=1)
    model: str = "llama-3.3-70b-versatile"
    tools: list[str] = []
    channels: list[str] = []
    is_active: bool = True
    max_iterations: int = 5
    memory_enabled: bool = True
    schedule: str | None = None
    forbidden_topics: list[str] = []
    max_output_chars: int | None = None


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: str | None = None
    role: Literal["orchestrator", "agent"] | None = None
    system_prompt: str | None = None
    model: str | None = None
    tools: list[str] | None = None
    channels: list[str] | None = None
    is_active: bool | None = None
    max_iterations: int | None = None
    memory_enabled: bool | None = None
    schedule: str | None = None
    forbidden_topics: list[str] | None = None
    max_output_chars: int | None = None


class AgentRead(AgentBase):
    id: int
    model_config = ConfigDict(from_attributes=True)
