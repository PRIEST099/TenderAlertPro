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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
from api.routers.logs import router as logs_router


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
        # Deadline reminders at 09:00 Kigali (07:00 UTC)
        from scheduler import run_deadline_reminders
        scheduler.add_job(
            run_deadline_reminders,
            "cron",
            hour=7,
            minute=0,
            id="deadline_reminders",
            replace_existing=True,
        )

        scheduler.start()
        print(f"[api] Scheduler started — daily job at {DAILY_HOUR_UTC:02d}:{DAILY_MINUTE_UTC:02d} UTC + deadline reminders at 07:00 UTC")
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

# CORS — allow all origins if "*" is in the list, otherwise use specific origins
cors_origins = ["*"] if "*" in CORS_ORIGINS else CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True if cors_origins != ["*"] else False,
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
app.include_router(logs_router)


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


# ── File serving for proposals/documents (time-limited token) ────────────

@app.get("/api/files/{token}", tags=["files"])
async def serve_file(token: str):
    """Serve a file from storage using a time-limited JWT token.
    Used by WhatsApp to download proposal PDFs."""
    import jwt
    from config import FLASK_SECRET_KEY

    try:
        payload = jwt.decode(token, FLASK_SECRET_KEY, algorithms=["HS256"])
        file_path = Path(payload["path"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="Link expired")
    except (jwt.InvalidTokenError, KeyError):
        raise HTTPException(status_code=403, detail="Invalid token")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=payload.get("filename", "document.pdf"),
    )
