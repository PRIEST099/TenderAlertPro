"""Interaction logs + fraud detection router."""

import math
from fastapi import APIRouter, Depends, Query, HTTPException

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from api.auth import get_current_admin
from api.models import PaginatedResponse
from database import get_interaction_logs, get_interaction_stats, get_subscriber  # noqa: E402
from pydantic import BaseModel
from typing import Optional


class InteractionLog(BaseModel):
    id: int
    phone: str
    direction: str
    msg_type: str
    content: str
    command: str
    timestamp: str


class UserActivityStats(BaseModel):
    phone: str
    company_name: str
    inbound_count: int
    outbound_count: int
    total: int
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    active: bool = True
    risk_level: str = "normal"  # normal, warning, suspicious


class FraudReport(BaseModel):
    period: str
    total_users: int
    total_interactions: int
    suspicious_users: list[UserActivityStats]
    warnings: list[str]
    ai_analysis: Optional[str] = None


router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("", response_model=PaginatedResponse[InteractionLog])
async def list_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    phone: str | None = None,
    _admin: str = Depends(get_current_admin),
):
    """Get interaction logs, optionally filtered by phone."""
    offset = (page - 1) * per_page
    logs = get_interaction_logs(phone=phone, limit=per_page + 1, offset=offset)

    # Estimate if there are more pages
    has_more = len(logs) > per_page
    logs = logs[:per_page]

    # For total count, get a larger set (approximate)
    all_logs = get_interaction_logs(phone=phone, limit=10000, offset=0)
    total = len(all_logs)

    items = [InteractionLog(**log) for log in logs]
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page) if per_page else 0,
    )


@router.get("/subscriber/{phone}")
async def get_subscriber_logs(
    phone: str,
    limit: int = Query(50, ge=1, le=200),
    _admin: str = Depends(get_current_admin),
):
    """Get all interaction logs for a specific subscriber."""
    sub = get_subscriber(phone)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    logs = get_interaction_logs(phone=phone, limit=limit)
    return {
        "subscriber": {
            "phone": sub["phone"],
            "company_name": sub.get("company_name", ""),
            "sectors": sub.get("sectors", "all"),
            "active": bool(sub.get("active")),
        },
        "logs": [InteractionLog(**log) for log in logs],
        "total": len(logs),
    }


@router.get("/activity")
async def get_activity_stats(
    period: str = Query("today", pattern="^(today|week|month)$"),
    _admin: str = Depends(get_current_admin),
):
    """Get per-user interaction stats for a given period."""
    stats = get_interaction_stats(period=period)

    # Flag suspicious activity
    users = []
    for s in stats:
        risk = "normal"
        if s["inbound_count"] > 50:
            risk = "suspicious"
        elif s["inbound_count"] > 20:
            risk = "warning"
        users.append(UserActivityStats(
            phone=s["phone"],
            company_name=s["company_name"],
            inbound_count=s["inbound_count"],
            outbound_count=s["outbound_count"],
            total=s["total"],
            first_seen=s["first_seen"],
            last_seen=s["last_seen"],
            active=bool(s["active"]),
            risk_level=risk,
        ))

    return {
        "period": period,
        "users": users,
        "total_users": len(users),
        "total_interactions": sum(u.total for u in users),
        "suspicious_count": sum(1 for u in users if u.risk_level == "suspicious"),
        "warning_count": sum(1 for u in users if u.risk_level == "warning"),
    }


@router.post("/analyze")
async def analyze_fraud(
    period: str = Query("today", pattern="^(today|week|month)$"),
    _admin: str = Depends(get_current_admin),
):
    """Use Claude AI to analyze interaction patterns and detect fraud/abuse."""
    stats = get_interaction_stats(period=period)

    if not stats:
        return FraudReport(
            period=period, total_users=0, total_interactions=0,
            suspicious_users=[], warnings=["No interactions found for this period."],
        )

    # Build analysis prompt for Claude
    import anthropic
    from config import ANTHROPIC_API_KEY  # noqa: E402

    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")

    # Format interaction data for Claude
    data_lines = []
    for s in stats:
        data_lines.append(
            f"Phone: {s['phone']}, Company: {s['company_name']}, "
            f"Inbound: {s['inbound_count']}, Outbound: {s['outbound_count']}, "
            f"Total: {s['total']}, First: {s['first_seen']}, Last: {s['last_seen']}, "
            f"Active: {s['active']}"
        )

    prompt = f"""You are a security analyst for TenderAlert Pro, a WhatsApp-based Rwanda government tender alert service.

Analyze these user interaction logs from the {period} period and identify:

1. **Suspicious accounts**: Users sending an unusually high number of messages (potential spam/abuse)
2. **Bot-like behavior**: Rapid-fire messages, repetitive patterns, or non-human timing
3. **Abuse patterns**: Users who might be scraping data, testing vulnerabilities, or abusing the service
4. **Recommendations**: Specific actions for each flagged user (warn, rate-limit, suspend)

User interaction data:
{chr(10).join(data_lines)}

Respond in this EXACT format:

RISK SUMMARY:
[1-2 sentence overview of the overall risk level]

FLAGGED USERS:
[For each suspicious user, on its own line:]
- Phone: [number] | Risk: [HIGH/MEDIUM/LOW] | Reason: [brief explanation] | Action: [warn/rate-limit/suspend]

RECOMMENDATIONS:
• [actionable recommendation 1]
• [actionable recommendation 2]
• [actionable recommendation 3 if needed]

If no suspicious activity is found, say "No suspicious activity detected" and still provide general recommendations."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        ai_analysis = message.content[0].text.strip()
    except Exception as e:
        ai_analysis = f"AI analysis failed: {str(e)}"

    # Build suspicious user list
    suspicious = []
    for s in stats:
        risk = "normal"
        if s["inbound_count"] > 50:
            risk = "suspicious"
        elif s["inbound_count"] > 20:
            risk = "warning"
        if risk != "normal":
            suspicious.append(UserActivityStats(
                phone=s["phone"],
                company_name=s["company_name"],
                inbound_count=s["inbound_count"],
                outbound_count=s["outbound_count"],
                total=s["total"],
                first_seen=s["first_seen"],
                last_seen=s["last_seen"],
                active=bool(s["active"]),
                risk_level=risk,
            ))

    return FraudReport(
        period=period,
        total_users=len(stats),
        total_interactions=sum(s["total"] for s in stats),
        suspicious_users=suspicious,
        warnings=[],
        ai_analysis=ai_analysis,
    )
