"""Stats router — dashboard overview numbers."""

from fastapi import APIRouter, Depends
from api.auth import get_current_admin
from api.models import StatsResponse, OnboardingFunnel
from api.database import count_subscribers, count_tenders, get_onboarding_funnel, get_last_poll_time

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=StatsResponse)
async def get_stats(_admin: str = Depends(get_current_admin)):
    subs = count_subscribers()
    tenders = count_tenders()
    funnel = get_onboarding_funnel()
    last_poll = get_last_poll_time()

    enrichment_rate = (tenders["enriched"] / tenders["total"] * 100) if tenders["total"] > 0 else 0.0

    return StatsResponse(
        total_subscribers=subs["total"],
        active_subscribers=subs["active"],
        inactive_subscribers=subs["inactive"],
        total_tenders=tenders["total"],
        active_tenders=tenders["active"],
        enriched_tenders=tenders["enriched"],
        enrichment_rate=round(enrichment_rate, 1),
        onboarding_funnel=OnboardingFunnel(**funnel),
        last_poll_at=last_poll,
    )
