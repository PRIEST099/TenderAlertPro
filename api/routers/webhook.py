"""
Webhook router — handles Meta WhatsApp Cloud API webhooks.
GET  /webhook  — verification handshake
POST /webhook  — incoming messages
"""

from fastapi import APIRouter, BackgroundTasks, Request, Query
from fastapi.responses import PlainTextResponse

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from config import WHATSAPP_VERIFY_TOKEN  # noqa: E402
from api.webhook import process_webhook_entry  # noqa: E402

router = APIRouter(tags=["webhook"])


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification — called once when registering the webhook URL."""
    if hub_mode == "subscribe" and hub_token == WHATSAPP_VERIFY_TOKEN:
        print("[webhook] Verified.")
        return PlainTextResponse(hub_challenge)
    return PlainTextResponse("Forbidden", status_code=403)


@router.post("/webhook")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming WhatsApp events (messages + button taps).

    Returns 200 immediately so Meta doesn't retry, then processes in background.
    """
    data = await request.json()
    for entry in data.get("entry", []):
        background_tasks.add_task(process_webhook_entry, entry)
    return {"status": "ok"}
