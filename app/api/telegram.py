from fastapi import APIRouter, Request
from telegram import Update

from app.core.config import get_settings
from app.services.telegram_service import get_telegram_app

settings = get_settings()

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    app = get_telegram_app()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return {"ok": True}
