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


def send_pdf_via_whatsapp(phone: str, file_path: str, filename: str, caption: str) -> bool:
    """Send a PDF document to a WhatsApp user.
    Requires a publicly accessible URL — for MVP, we note this limitation.
    """
    # TODO: Upload to a public file host (Cloudinary, file.io, etc.)
    # For now, log and return False — the proposal text is sent separately
    print(f"[documents] PDF sending not yet implemented. File at: {file_path}")
    return False
