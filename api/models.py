"""
models.py — Pydantic schemas for API request/response validation.
"""

from pydantic import BaseModel, Field
from typing import Generic, TypeVar, Optional
from datetime import datetime

T = TypeVar("T")


# ── Auth ──────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Paginated Response ────────────────────────────────────────────────────

class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int
    pages: int


# ── Stats ─────────────────────────────────────────────────────────────────

class OnboardingFunnel(BaseModel):
    awaiting_name: int = 0
    awaiting_sector: int = 0
    complete: int = 0


class StatsResponse(BaseModel):
    total_subscribers: int
    active_subscribers: int
    inactive_subscribers: int
    total_tenders: int
    active_tenders: int
    enriched_tenders: int
    enrichment_rate: float
    onboarding_funnel: OnboardingFunnel
    last_poll_at: Optional[str] = None


# ── Subscribers ───────────────────────────────────────────────────────────

class SubscriberOut(BaseModel):
    """Subscriber with masked phone (for list views)."""
    id: int
    phone: str
    phone_masked: str
    company_name: str
    sectors: str
    onboarding_step: str
    active: bool
    created_at: Optional[str] = None


class SubscriberDetail(BaseModel):
    """Full subscriber detail (admin only)."""
    id: int
    phone: str
    company_name: str
    sectors: str
    onboarding_step: str
    active: bool
    subscription_tier: str = "free"
    rate_limit_exempt: bool = False
    credits: int = 0
    deep_analyses_used: int = 0
    created_at: Optional[str] = None


# ── Tenders ───────────────────────────────────────────────────────────────

class TenderOut(BaseModel):
    """Tender summary for list views."""
    ocid: str
    title: str
    buyer_name: str
    category: str
    sub_category: Optional[str] = None
    value_amount: Optional[float] = None
    value_currency: str = "RWF"
    deadline: Optional[str] = None
    status: str
    has_ai_summary: bool
    fetched_at: Optional[str] = None


class TenderDetail(BaseModel):
    """Full tender detail including AI summary."""
    ocid: str
    title: str
    description: str
    buyer_name: str
    category: str
    value_amount: Optional[float] = None
    value_currency: str = "RWF"
    deadline: Optional[str] = None
    status: str
    source_url: str
    ai_summary: Optional[str] = None
    fetched_at: Optional[str] = None


# ── Operations ────────────────────────────────────────────────────────────

class OperationResult(BaseModel):
    success: bool
    message: str
    count: int = 0


class OperationStatus(BaseModel):
    last_poll_at: Optional[str] = None
    total_tenders: int = 0
    total_subscribers: int = 0
    scheduler_active: bool = False
    next_run: Optional[str] = None


# ── Settings ──────────────────────────────────────────────────────────────

class SettingsResponse(BaseModel):
    whatsapp_token_valid: bool
    whatsapp_sender_status: dict
    anthropic_key_set: bool
    webhook_verify_token: str
    admin_number: str
    database_path: str
    cors_origins: list[str]


# ── Messages ──────────────────────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4096)


class CreateSubscriberRequest(BaseModel):
    phone: str = Field(min_length=9, max_length=15, description="Phone in international format without +, e.g. 250788123456")
    company_name: str = ""
    sectors: str = "all"
