"""Tenders router — list, detail, trigger AI enrichment."""

import math
from fastapi import APIRouter, Depends, HTTPException, Query

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from api.auth import get_current_admin
from api.models import TenderOut, TenderDetail, PaginatedResponse, OperationResult
from api.database import get_tenders_paginated, get_tender_by_ocid

router = APIRouter(prefix="/api/tenders", tags=["tenders"])


@router.get("", response_model=PaginatedResponse[TenderOut])
async def list_tenders(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sector: str | None = None,
    enrichment: str | None = None,
    deadline_from: str | None = None,
    deadline_to: str | None = None,
    search: str | None = None,
    value_min: float | None = None,
    value_max: float | None = None,
    _admin: str = Depends(get_current_admin),
):
    rows, total = get_tenders_paginated(page, per_page, sector, enrichment, deadline_from, deadline_to, search, value_min, value_max)
    items = [
        TenderOut(
            ocid=r["ocid"],
            title=r["title"],
            buyer_name=r.get("buyer_name", ""),
            category=r.get("category", ""),
            sub_category=r.get("sub_category", ""),
            value_amount=r.get("value_amount"),
            value_currency=r.get("value_currency", "RWF"),
            deadline=r.get("deadline"),
            status=r.get("status", ""),
            has_ai_summary=r.get("has_ai_summary", False),
            fetched_at=r.get("fetched_at"),
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


@router.get("/{ocid:path}", response_model=TenderDetail)
async def get_tender_detail(ocid: str, _admin: str = Depends(get_current_admin)):
    tender = get_tender_by_ocid(ocid)
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    return TenderDetail(
        ocid=tender["ocid"],
        title=tender["title"],
        description=tender.get("description", ""),
        buyer_name=tender.get("buyer_name", ""),
        category=tender.get("category", ""),
        value_amount=tender.get("value_amount"),
        value_currency=tender.get("value_currency", "RWF"),
        deadline=tender.get("deadline"),
        status=tender.get("status", ""),
        source_url=tender.get("source_url", ""),
        ai_summary=tender.get("ai_summary"),
        fetched_at=tender.get("fetched_at"),
    )


@router.post("/{ocid:path}/enrich", response_model=OperationResult)
async def enrich_tender_endpoint(ocid: str, _admin: str = Depends(get_current_admin)):
    """Trigger Claude AI enrichment for a specific tender."""
    tender = get_tender_by_ocid(ocid)
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    from ai_enrichment import enrich_tender  # noqa: E402
    from database import save_ai_summary  # noqa: E402

    summary, tags = enrich_tender(tender)
    if summary:
        save_ai_summary(ocid, summary, tags=tags)
        tag_msg = f" [sectors: {tags}]" if tags else ""
        return OperationResult(success=True, message=f"Tender enriched successfully{tag_msg}", count=1)
    raise HTTPException(status_code=502, detail="AI enrichment failed — check Anthropic API key")
