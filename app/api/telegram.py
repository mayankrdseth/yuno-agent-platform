import logging

from fastapi import APIRouter, HTTPException, Request
from telegram import Update

from app.services.telegram_service import get_telegram_app

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, get_telegram_app().bot)
        await get_telegram_app().process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.exception("Error processing Telegram update")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/set-webhook")
async def set_webhook(webhook_url: str):
    bot = get_telegram_app().bot
    result = await bot.set_webhook(url=f"{webhook_url}/telegram/webhook")
    return {"ok": result, "webhook_url": f"{webhook_url}/telegram/webhook"}


@router.get("/webhook-info")
async def webhook_info():
    bot = get_telegram_app().bot
    info = await bot.get_webhook_info()
    return {
        "url": info.url,
        "pending_update_count": info.pending_update_count,
        "last_error_message": info.last_error_message,
    }