from __future__ import annotations

import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow_template import WorkflowTemplate
from app.schemas.workflow_template import WorkflowTemplateCreate


async def list_templates(db: AsyncSession) -> list[WorkflowTemplate]:
    result = await db.execute(select(WorkflowTemplate).order_by(WorkflowTemplate.id))
    return list(result.scalars().all())


async def get_template(db: AsyncSession, template_id: int) -> WorkflowTemplate | None:
    result = await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.id == template_id))
    return result.scalar_one_or_none()


async def create_template(db: AsyncSession, payload: WorkflowTemplateCreate, is_builtin: int = 0) -> WorkflowTemplate:
    tpl = WorkflowTemplate(
        name=payload.name,
        description=payload.description,
        agent_ids=json.dumps(payload.agent_ids),
        edges=json.dumps([e.model_dump() for e in payload.edges]),
        is_builtin=is_builtin,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return tpl


async def delete_template(db: AsyncSession, template_id: int) -> bool:
    tpl = await get_template(db, template_id)
    if not tpl:
        return False
    await db.delete(tpl)
    await db.commit()
    return True


def serialize_template(tpl: WorkflowTemplate):
    return {
        "id": tpl.id,
        "name": tpl.name,
        "description": tpl.description,
        "agent_ids": json.loads(tpl.agent_ids),
        "edges": json.loads(tpl.edges),
        "is_builtin": tpl.is_builtin,
        "created_at": tpl.created_at,
    }
