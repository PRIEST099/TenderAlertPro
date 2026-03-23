import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (one level up from backend/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)

# Umucyo OCDS
UMUCYO_OCDS_ENDPOINT = "https://ocds.umucyo.gov.rw/opendata/api/v1/releases/all"
UMUCYO_BULK_URL = "https://fastly.data.open-contracting.org/downloads/rwanda_bulk/3460/{year}.jsonl.gz"

# Meta WhatsApp Cloud API
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "tenderalert_verify")
WHATSAPP_API_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

# Admin
ADMIN_WHATSAPP_NUMBER = os.getenv("ADMIN_WHATSAPP_NUMBER", "")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Database — defaults to Railway volume path; local .env overrides for dev
DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/tenderalert.db")

# App
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
FLASK_PORT = int(os.getenv("PORT", 5000))

# Admin Dashboard Auth
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-jwt-secret-change-me")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
