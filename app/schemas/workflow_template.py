from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class EdgeSchema(BaseModel):
    source: str
    target: str


class WorkflowTemplateCreate(BaseModel):
    name: str
    description: str | None = None
    agent_ids: list[int]
    edges: list[EdgeSchema] = []


class WorkflowTemplateRead(BaseModel):
    id: int
    name: str
    description: str | None
    agent_ids: list[int]
    edges: list[EdgeSchema]
    is_builtin: int
    created_at: datetime

    model_config = {"from_attributes": True}
