from fastapi import APIRouter

from app.api.agents import router as agents_router
from app.api.health import router as health_router
from app.api.monitor import router as monitor_router
from app.api.telegram import router as telegram_router
from app.api.workflow_templates import router as workflow_templates_router
from app.api.workflows import router as workflows_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(agents_router, prefix="/agents", tags=["agents"])
api_router.include_router(workflows_router, prefix="/workflows", tags=["workflows"])
api_router.include_router(workflow_templates_router, prefix="/workflow-templates", tags=["workflow-templates"])
api_router.include_router(telegram_router, prefix="/telegram", tags=["telegram"])
api_router.include_router(monitor_router, tags=["monitor"])
