"""
documents.py — Handle WhatsApp media downloads, file storage, and PDF sending.
"""

import base64
import os
from pathlib import Path

import requests
from config import WHATSAPP_TOKEN, WHATSAPP_API_URL, WHATSAPP_PHONE_NUMBER_ID

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./storage/documents"))


def download_whatsapp_media(media_id: str) -> bytes | None:
    """Download a media file from WhatsApp.
    Step 1: GET media URL from Graph API.
    Step 2: Download the actual bytes.
    """
    if not WHATSAPP_TOKEN:
        print("[documents] Missing WHATSAPP_TOKEN")
        return None

    try:
        # Get media URL
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=10,
        )
        r.raise_for_status()
        media_url = r.json().get("url")
        if not media_url:
            print(f"[documents] No URL in media response for {media_id}")
            return None

        # Download actual bytes
        r2 = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=30,
        )
        r2.raise_for_status()
        return r2.content

    except requests.RequestException as e:
        print(f"[documents] Media download failed: {e}")
        return None


def save_document(phone: str, doc_type: str, filename: str, file_bytes: bytes) -> str:
    """Save document bytes to disk. Returns the file path."""
    from datetime import datetime

    user_dir = STORAGE_DIR / phone
    user_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{doc_type}_{timestamp}.pdf"
    file_path = user_dir / safe_name

    file_path.write_bytes(file_bytes)
    print(f"[documents] Saved {len(file_bytes)} bytes to {file_path}")
    return str(file_path)


def load_document_as_base64(file_path: str) -> str | None:
    """Read a file and return base64-encoded string for Claude API."""
    try:
        data = Path(file_path).read_bytes()
        return base64.b64encode(data).decode("utf-8")
    except Exception as e:
        print(f"[documents] Failed to read {file_path}: {e}")
        return None


def generate_file_token(file_path: str, filename: str, expires_hours: int = 1) -> str:
    """Generate a time-limited JWT token for serving a file."""
    import jwt
    from datetime import datetime, timedelta
    from config import FLASK_SECRET_KEY

    payload = {
        "path": file_path,
        "filename": filename,
        "exp": datetime.utcnow() + timedelta(hours=expires_hours),
    }
    return jwt.encode(payload, FLASK_SECRET_KEY, algorithm="HS256")


def send_pdf_via_whatsapp(phone: str, file_path: str, filename: str, caption: str = "") -> bool:
    """Send a PDF document to a WhatsApp user via a time-limited public URL.
    Uses the /api/files/{token} endpoint on Railway to serve the file.
    """
    railway_url = os.getenv("RAILWAY_PUBLIC_URL", os.getenv("RAILWAY_STATIC_URL", ""))
    if not railway_url:
        # Fallback: try to construct from common Railway patterns
        railway_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
        if railway_url and not railway_url.startswith("http"):
            railway_url = f"https://{railway_url}"

    if not railway_url:
        print("[documents] No RAILWAY_PUBLIC_URL set — can't serve PDF. Set this env var.")
        return False

    # Generate time-limited token
    token = generate_file_token(file_path, filename, expires_hours=24)
    public_url = f"{railway_url}/api/files/{token}"

    # Send via WhatsApp document message
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "document",
        "document": {
            "link": public_url,
            "filename": filename,
            "caption": caption or f"TenderAlert Pro — {filename}",
        },
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(WHATSAPP_API_URL, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            print(f"[documents] PDF sent to {phone}: {filename}")
            return True
        else:
            err = resp.json().get("error", {})
            print(f"[documents] PDF send failed: {err.get('code')} — {err.get('message')}")
            return False
    except requests.RequestException as e:
        print(f"[documents] PDF send request failed: {e}")
        return False
