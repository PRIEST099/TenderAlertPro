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
        created_at=sub.get("created_at"),
    )


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
