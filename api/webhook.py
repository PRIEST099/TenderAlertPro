"""
webhook.py — WhatsApp webhook logic extracted from bot.py.
Pure Python functions with no Flask/FastAPI dependency.
Called by api/routers/webhook.py (FastAPI routes).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import (  # noqa: E402
    add_subscriber, remove_subscriber, get_subscriber,
    update_subscriber, get_new_tenders, init_db,
)
from whatsapp import send_text, send_sector_list, send_tender_digest  # noqa: E402

VALID_SECTORS = ["ict", "construction", "health", "education", "agriculture", "consulting", "supply", "all"]

HELP_TEXT = (
    "*TenderAlert Pro — Commands*\n\n"
    "• *STOP* — Unsubscribe\n"
    "• *SECTORS* — Change your sector filter\n"
    "• *HELP* — Show this menu"
)

SECTOR_LABELS = {
    "ict": "ICT & Technology",
    "construction": "Works & Construction",
    "health": "Health & Pharma",
    "education": "Education",
    "consulting": "Consulting & Services",
    "supply": "Supply & Goods",
    "all": "All Sectors",
}

# Button titles — must match template buttons exactly (lowercased)
# tender_update template buttons:
BTN_GET_DIGEST     = "view tenders"
BTN_CHANGE_SECTORS = "change sector"
BTN_UNSUBSCRIBE    = "stop alerts"
# Also match old procurement_notice buttons (in case both are active)
BTN_GET_DIGEST_ALT     = "get today's digest"
BTN_CHANGE_SECTORS_ALT = "change my sectors"
BTN_UNSUBSCRIBE_ALT    = "unsubscribe"


# ── Payload parsing ───────────────────────────────────────────────────────

def parse_phone(entry: dict) -> str | None:
    try:
        return entry["changes"][0]["value"]["messages"][0]["from"]
    except (KeyError, IndexError):
        return None


def parse_message(entry: dict) -> tuple[str, str]:
    """Return (msg_type, content). msg_type: text, button_reply, list_reply, unknown."""
    try:
        msg = entry["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError):
        return "unknown", ""

    msg_type = msg.get("type", "unknown")

    if msg_type == "text":
        return "text", msg.get("text", {}).get("body", "").strip().lower()

    if msg_type == "interactive":
        interactive = msg.get("interactive", {})
        itype = interactive.get("type")
        if itype == "button_reply":
            title = interactive["button_reply"].get("title", "").strip().lower()
            return "button_reply", title
        if itype == "list_reply":
            row_id = interactive["list_reply"].get("id", "").strip().lower()
            return "list_reply", row_id

    return msg_type, ""


# ── Onboarding ────────────────────────────────────────────────────────────

def handle_onboarding(phone: str, msg_type: str, content: str, sub: dict | None):
    step = sub["onboarding_step"] if sub else None

    if sub is None:
        add_subscriber(phone, onboarding_step="awaiting_name")
        send_text(
            phone,
            "*Welcome to TenderAlert Pro!* \n\n"
            "I send daily Rwanda government tender alerts straight to WhatsApp, "
            "with AI-powered eligibility summaries so you know exactly what each bid requires.\n\n"
            "To get started — what is your *company or organisation name*?"
        )
        return

    if step == "awaiting_name":
        company = content.strip() if content else "Unknown"
        update_subscriber(phone, company_name=company, onboarding_step="awaiting_sector")
        send_text(phone, f"Nice to meet you, *{company}*!\n\nNow choose the sector you want tender alerts for:")
        send_sector_list(phone)
        return

    if step == "awaiting_sector":
        sector = content if content in VALID_SECTORS else "all"
        label = SECTOR_LABELS.get(sector, "All Sectors")
        update_subscriber(phone, sectors=sector, onboarding_step="complete")
        send_text(
            phone,
            f"*You're all set!*\n\n"
            f"Sector: *{label}*\n\n"
            f"You'll receive a daily morning alert every time new Rwanda government tenders "
            f"are published in your sector.\n\n"
            f"Reply *HELP* anytime to see available commands."
        )
        return


# ── Button replies ────────────────────────────────────────────────────────

def handle_button_reply(phone: str, button_title: str):
    print(f"[webhook] Button tap from {phone}: {button_title!r}")

    if button_title in (BTN_GET_DIGEST, BTN_GET_DIGEST_ALT, "get started"):
        init_db()
        tenders = get_new_tenders(since_hours=25)
        if tenders:
            send_tender_digest(phone, tenders, use_template=False)
        else:
            send_text(phone, "No new tenders in the last 24 hours. Check back tomorrow morning!")

    elif button_title in (BTN_CHANGE_SECTORS, BTN_CHANGE_SECTORS_ALT):
        update_subscriber(phone, onboarding_step="awaiting_sector")
        send_text(phone, "No problem! Select a new sector below:")
        send_sector_list(phone)

    elif button_title in (BTN_UNSUBSCRIBE, BTN_UNSUBSCRIBE_ALT):
        remove_subscriber(phone)
        send_text(phone, "You've been unsubscribed from TenderAlert Pro.\n\nMessage us anytime to rejoin.")

    else:
        send_text(phone, HELP_TEXT)


# ── Text commands ─────────────────────────────────────────────────────────

def handle_text(phone: str, text: str):
    print(f"[webhook] Text from {phone}: {text!r}")

    if text in ("stop", "unsubscribe", "quit"):
        remove_subscriber(phone)
        send_text(phone, "You've been unsubscribed. Message us anytime to rejoin.")

    elif text in ("sectors", "sector", "change sector"):
        update_subscriber(phone, onboarding_step="awaiting_sector")
        send_text(phone, "Select a new sector below:")
        send_sector_list(phone)

    elif text == "help":
        send_text(phone, HELP_TEXT)

    else:
        send_text(phone, "I didn't understand that.\n\nReply *HELP* to see available commands.")


# ── Main dispatcher ───────────────────────────────────────────────────────

def process_webhook_entry(entry: dict):
    """Process a single webhook entry (one message). Called by the FastAPI route."""
    phone = parse_phone(entry)
    if not phone:
        return

    msg_type, content = parse_message(entry)
    if msg_type == "unknown":
        return

    sub = get_subscriber(phone)
    step = sub["onboarding_step"] if sub else None

    # Onboarding gate
    if sub is None or step in ("awaiting_name", "awaiting_sector"):
        handle_onboarding(phone, msg_type, content, sub)
        return

    # Onboarded users
    if msg_type == "button_reply":
        handle_button_reply(phone, content)

    elif msg_type == "list_reply":
        sector = content if content in VALID_SECTORS else "all"
        label = SECTOR_LABELS.get(sector, "All Sectors")
        update_subscriber(phone, sectors=sector, onboarding_step="complete")
        send_text(phone, f"Updated! You'll now receive alerts for *{label}*.")

    elif msg_type == "text" and content:
        handle_text(phone, content)
