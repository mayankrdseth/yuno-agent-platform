from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.workflow_template import WorkflowTemplateCreate
from app.services.workflow_template_service import (
    create_template,
    delete_template,
    list_templates,
    serialize_template,
)

router = APIRouter(prefix="/workflow-templates", tags=["workflow-templates"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("")
async def get_templates(db: DbSession):
    templates = await list_templates(db)
    return [serialize_template(t) for t in templates]


@router.post("", status_code=status.HTTP_201_CREATED)
async def post_template(payload: WorkflowTemplateCreate, db: DbSession):
    tpl = await create_template(db, payload, is_builtin=0)
    return serialize_template(tpl)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_template(template_id: int, db: DbSession):
    deleted = await delete_template(db, template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
