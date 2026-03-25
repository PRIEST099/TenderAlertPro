"""Subscribers router — CRUD, export, manual messaging."""

import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from api.auth import get_current_admin
from api.models import SubscriberOut, SubscriberDetail, PaginatedResponse, SendMessageRequest, CreateSubscriberRequest
from api.database import get_subscribers_paginated, export_subscribers
from database import get_subscriber, update_subscriber, add_subscriber  # noqa: E402
from whatsapp import send_text  # noqa: E402
import math

router = APIRouter(prefix="/api/subscribers", tags=["subscribers"])


@router.get("", response_model=PaginatedResponse[SubscriberOut])
async def list_subscribers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sector: str | None = None,
    status: str | None = None,
    search: str | None = None,
    _admin: str = Depends(get_current_admin),
):
    rows, total = get_subscribers_paginated(page, per_page, sector, status, search)
    items = [
        SubscriberOut(
            id=r["id"],
            phone=r.get("phone", ""),
            phone_masked=r["phone_masked"],
            company_name=r.get("company_name", ""),
            sectors=r.get("sectors", "all"),
            onboarding_step=r.get("onboarding_step", "complete"),
            active=bool(r.get("active", 1)),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page) if per_page else 0,
    )


@router.post("", response_model=SubscriberDetail)
async def create_subscriber(
    body: CreateSubscriberRequest,
    _admin: str = Depends(get_current_admin),
):
    """Manually add a subscriber from the admin dashboard."""
    existing = get_subscriber(body.phone)
    if existing and existing.get("active"):
        raise HTTPException(status_code=409, detail="Subscriber already exists and is active")

    add_subscriber(body.phone, sectors=body.sectors, onboarding_step="complete")
    update_subscriber(body.phone, company_name=body.company_name)

    sub = get_subscriber(body.phone)
    return SubscriberDetail(
        id=sub["id"],
        phone=sub["phone"],
        company_name=sub.get("company_name", ""),
        sectors=sub.get("sectors", "all"),
        onboarding_step=sub.get("onboarding_step", "complete"),
        active=bool(sub.get("active", 1)),
        created_at=sub.get("created_at"),
    )


@router.get("/export")
async def export_csv(_admin: str = Depends(get_current_admin)):
    """Download all active subscribers as CSV."""
    rows = export_subscribers()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["phone", "company_name", "sectors", "onboarding_step", "created_at"])
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=subscribers.csv"},
    )


@router.get("/{phone}", response_model=SubscriberDetail)
async def get_subscriber_detail(phone: str, _admin: str = Depends(get_current_admin)):
    sub = get_subscriber(phone)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return SubscriberDetail(
        id=sub["id"],
        phone=sub["phone"],
        company_name=sub.get("company_name", ""),
        sectors=sub.get("sectors", "all"),
        onboarding_step=sub.get("onboarding_step", "complete"),
        active=bool(sub.get("active", 1)),
        subscription_tier=sub.get("subscription_tier", "free"),
        rate_limit_exempt=bool(sub.get("rate_limit_exempt", 0)),
        credits=sub.get("credits", 0),
        deep_analyses_used=sub.get("deep_analyses_used", 0),
        created_at=sub.get("created_at"),
    )


@router.post("/{phone}/upgrade")
async def upgrade_subscriber(
    phone: str,
    body: dict,
    _admin: str = Depends(get_current_admin),
):
    """Upgrade or downgrade a subscriber's tier."""
    sub = get_subscriber(phone)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    tier = body.get("tier", "free")
    if tier not in ("free", "regular", "pro", "business"):
        raise HTTPException(status_code=400, detail="Invalid tier. Use 'free', 'regular', 'pro', or 'business'")

    credits_map = {"free": 0, "regular": 0, "pro": 0, "business": 5}
    credits = credits_map.get(tier, 0)
    update_subscriber(phone, subscription_tier=tier, credits=credits)

    # Notify the user about the tier change via WhatsApp
    try:
        if tier == "free":
            send_text(phone, "Your TenderAlert Pro subscription has been changed to *Free* tier.")
        elif tier == "regular":
            send_text(phone, "🟢 *Your subscription has been upgraded to Regular!*\n\nYou now have full tender details and 10 views per day.\n\nReply *STATUS* to see your profile.")
        elif tier == "pro":
            send_text(phone, "👑 *Your subscription has been upgraded to Pro!*\n\nUnlimited tender views + deep analyses + bid pipeline.\n\nReply *STATUS* to see your profile.")
        elif tier == "business":
            send_text(phone, "💎 *Your subscription has been upgraded to Business!*\n\nEverything in Pro + 5 proposal credits/month.\n\nReply *STATUS* to see your profile.")
    except Exception as e:
        print(f"[subscribers] Failed to notify user about tier change: {e}")

    # Notify admin
    try:
        from whatsapp import notify_admin
        notify_admin(f"👤 *Tier Change*\n{phone} → *{tier.title()}*\n(via admin dashboard)")
    except Exception:
        pass

    return {"success": True, "tier": tier, "credits": credits, "message": f"Subscriber updated to {tier.title()}"}


@router.post("/{phone}/toggle-rate-limit")
async def toggle_rate_limit(
    phone: str,
    _admin: str = Depends(get_current_admin),
):
    """Toggle rate limit exemption for a subscriber."""
    sub = get_subscriber(phone)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    current = sub.get("rate_limit_exempt", 0)
    new_value = 0 if current else 1
    update_subscriber(phone, rate_limit_exempt=new_value)

    status = "exempt" if new_value else "enforced"
    return {"success": True, "rate_limit_exempt": bool(new_value), "message": f"Rate limit {status} for {phone}"}


@router.post("/{phone}/message")
async def send_manual_message(
    phone: str,
    body: SendMessageRequest,
    _admin: str = Depends(get_current_admin),
):
    """Send a manual WhatsApp text message to a subscriber."""
    sub = get_subscriber(phone)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    success = send_text(phone, body.message)
    if success:
        return {"success": True, "message": f"Message sent to {phone}"}
    raise HTTPException(status_code=502, detail="WhatsApp API failed to send message")
