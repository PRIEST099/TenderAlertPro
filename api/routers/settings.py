"""Settings router — API health checks, config status."""

from fastapi import APIRouter, Depends

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from api.auth import get_current_admin
from api.models import SettingsResponse
from config import (  # noqa: E402
    WHATSAPP_TOKEN, WHATSAPP_VERIFY_TOKEN, ADMIN_WHATSAPP_NUMBER,
    ANTHROPIC_API_KEY, DATABASE_PATH, CORS_ORIGINS,
)
from whatsapp import check_sender_status  # noqa: E402

router = APIRouter(prefix="/api/settings", tags=["settings"])


def mask_key(key: str, visible: int = 4) -> str:
    """Show only last N chars of a key: sk-ant-...QxfA"""
    if not key:
        return "(not set)"
    if len(key) <= visible:
        return key
    return "***" + key[-visible:]


@router.get("", response_model=SettingsResponse)
async def get_settings(_admin: str = Depends(get_current_admin)):
    sender_status = check_sender_status()

    return SettingsResponse(
        whatsapp_token_valid=bool(WHATSAPP_TOKEN and "error" not in sender_status),
        whatsapp_sender_status=sender_status,
        anthropic_key_set=bool(ANTHROPIC_API_KEY),
        webhook_verify_token=WHATSAPP_VERIFY_TOKEN,
        admin_number=ADMIN_WHATSAPP_NUMBER,
        database_path=DATABASE_PATH,
        cors_origins=CORS_ORIGINS,
    )
