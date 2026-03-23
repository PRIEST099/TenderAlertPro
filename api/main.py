"""
main.py — FastAPI application for TenderAlert Pro.

Serves:
  - WhatsApp webhook (GET/POST /webhook)
  - Admin REST API (GET/POST /api/*)
  - Health check (GET /health)
  - BackgroundScheduler for daily poll+enrich+send job
"""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Make backend/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import CORS_ORIGINS  # noqa: E402
from database import init_db  # noqa: E402

from api.auth import create_token, verify_password
from api.models import LoginRequest, TokenResponse

# Routers
from api.routers.webhook import router as webhook_router
from api.routers.stats import router as stats_router
from api.routers.subscribers import router as subscribers_router
from api.routers.tenders import router as tenders_router
from api.routers.operations import router as operations_router
from api.routers.settings import router as settings_router


# ── Scheduler ─────────────────────────────────────────────────────────────

scheduler = None


def start_scheduler():
    global scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from scheduler import run_daily_job, DAILY_HOUR_UTC, DAILY_MINUTE_UTC

        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(
            run_daily_job,
            "cron",
            hour=DAILY_HOUR_UTC,
            minute=DAILY_MINUTE_UTC,
            id="daily_tender_job",
            replace_existing=True,
        )
        scheduler.start()
        print(f"[api] Scheduler started — daily job at {DAILY_HOUR_UTC:02d}:{DAILY_MINUTE_UTC:02d} UTC")
    except Exception as e:
        print(f"[api] Failed to start scheduler: {e}")


def stop_scheduler():
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        print("[api] Scheduler stopped.")


# ── Lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    start_scheduler()
    print("[api] TenderAlert Pro API started.")
    yield
    # Shutdown
    stop_scheduler()


# ── App ───────────────────────────────────────────────────────────────────

app = FastAPI(
    title="TenderAlert Pro API",
    description="Admin API + WhatsApp webhook for Rwanda government tender alerts",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(webhook_router)
app.include_router(stats_router)
app.include_router(subscribers_router)
app.include_router(tenders_router)
app.include_router(operations_router)
app.include_router(settings_router)


# ── Auth endpoint ─────────────────────────────────────────────────────────

@app.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(body: LoginRequest):
    if not verify_password(body.password):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Wrong password")
    token = create_token()
    return TokenResponse(access_token=token)


# ── Health ────────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
async def health():
    return {"status": "running", "service": "TenderAlert Pro API"}
