"""Operations router — manual poll, send, scheduler status."""

from fastapi import APIRouter, Depends, Query

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from api.auth import get_current_admin
from api.models import OperationResult, OperationStatus
from api.database import count_subscribers, count_tenders, get_last_poll_time

router = APIRouter(prefix="/api/operations", tags=["operations"])


@router.post("/poll", response_model=OperationResult)
async def manual_poll(_admin: str = Depends(get_current_admin)):
    """Manually trigger a tender fetch from the RPPA OCDS API."""
    from poller import poll_and_store  # noqa: E402
    try:
        count = poll_and_store()
        return OperationResult(success=True, message=f"Fetched {count} tender(s) from RPPA", count=count)
    except Exception as e:
        return OperationResult(success=False, message=f"Poll failed: {str(e)}", count=0)


@router.post("/send", response_model=OperationResult)
async def manual_send(_admin: str = Depends(get_current_admin)):
    """Manually trigger sending tender digest to all active subscribers."""
    from scheduler import run_daily_job  # noqa: E402
    try:
        run_daily_job()
        subs = count_subscribers()
        return OperationResult(
            success=True,
            message=f"Digest sent to {subs['active']} active subscriber(s)",
            count=subs["active"],
        )
    except Exception as e:
        return OperationResult(success=False, message=f"Send failed: {str(e)}", count=0)


@router.post("/enrich", response_model=OperationResult)
async def manual_enrich(
    limit: int = Query(5, ge=1, le=50, description="Max tenders to enrich in this batch"),
    _admin: str = Depends(get_current_admin),
):
    """Manually trigger AI enrichment on unenriched tenders (batch size configurable)."""
    from ai_enrichment import enrich_new_tenders  # noqa: E402
    try:
        count = enrich_new_tenders(limit=limit)
        return OperationResult(success=True, message=f"Enriched {count} of {limit} requested tender(s)", count=count)
    except Exception as e:
        return OperationResult(success=False, message=f"Enrichment failed: {str(e)}", count=0)


@router.get("/status", response_model=OperationStatus)
async def get_status(_admin: str = Depends(get_current_admin)):
    subs = count_subscribers()
    tenders = count_tenders()
    last_poll = get_last_poll_time()

    return OperationStatus(
        last_poll_at=last_poll,
        total_tenders=tenders["total"],
        total_subscribers=subs["total"],
        scheduler_active=True,  # Always true when server is running (BackgroundScheduler)
        next_run="06:00 UTC / 08:00 Kigali (daily)",
    )
