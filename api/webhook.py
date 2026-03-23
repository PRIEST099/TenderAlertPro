"""
webhook.py — WhatsApp webhook logic for TenderAlert Pro.

Key design:
  - Every response includes quick-reply buttons so users never need to type
  - Onboarding detects commands (hi, hello, help) and doesn't save them as company name
  - Returning users are recognized by phone number lookup, not re-onboarded
  - Unsubscribe requires confirmation (2-button "are you sure?")

Pure Python — no framework dependency. Called by api/routers/webhook.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import (  # noqa: E402
    add_subscriber, remove_subscriber, get_subscriber,
    update_subscriber, get_new_tenders, search_tenders,
    get_tenders_for_subscriber, init_db,
)
from whatsapp import (  # noqa: E402
    send_text, send_sector_list, send_buttons, send_tender_digest,
    format_tender_alert, format_status_message, format_search_results,
)

VALID_SECTORS = ["ict", "construction", "health", "education", "agriculture", "consulting", "supply", "all"]

SECTOR_LABELS = {
    "ict": "ICT & Technology",
    "construction": "Works & Construction",
    "health": "Health & Pharma",
    "education": "Education",
    "consulting": "Consulting & Services",
    "supply": "Supply & Goods",
    "all": "All Sectors",
}

# Words that should NOT be treated as a company name during onboarding
KNOWN_COMMANDS = {
    "hi", "hello", "hey", "start", "join", "subscribe",
    "help", "stop", "quit", "cancel", "unsubscribe",
    "status", "me", "profile", "sectors", "sector",
    "list", "tenders", "latest", "new", "today",
    "name", "change name", "change sector",
}

HELP_TEXT = (
    "*TenderAlert Pro — Commands*\n\n"
    "📋 *LIST* — See latest tenders in your sector\n"
    "🔍 *SEARCH <keyword>* — Find specific tenders\n"
    "👤 *STATUS* — View your subscription info\n"
    "📂 *SECTORS* — Change your sector filter\n"
    "✏️ *NAME* — Update your company name\n"
    "❌ *STOP* — Unsubscribe\n"
    "❓ *HELP* — Show this menu"
)

# Standard button sets for common responses
MAIN_BUTTONS = ["View Tenders", "My Status", "Help"]
AFTER_ACTION_BUTTONS = ["View Tenders", "Change Sector", "Help"]
AFTER_TENDERS_BUTTONS = ["Change Sector", "My Status", "Help"]

# Button titles from templates + confirmation
BTN_VIEW_TENDERS   = "view tenders"
BTN_CHANGE_SECTOR  = "change sector"
BTN_STOP_ALERTS    = "stop alerts"
BTN_GET_DIGEST_ALT     = "get today's digest"
BTN_CHANGE_SECTORS_ALT = "change my sectors"
BTN_UNSUBSCRIBE_ALT    = "unsubscribe"
BTN_CONFIRM_UNSUB  = "yes, unsubscribe"
BTN_KEEP_ALERTS    = "no, keep alerts"
BTN_GET_STARTED    = "get started"
BTN_MY_STATUS      = "my status"
BTN_HELP           = "help"


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
        return "text", msg.get("text", {}).get("body", "").strip()

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


# ── Onboarding state machine ─────────────────────────────────────────────

def handle_onboarding(phone: str, msg_type: str, content: str, sub: dict | None):
    """
    Drive new users through onboarding. Recognizes returning users by phone.

    Key fix: if user sends a known command (hi, hello, help) during awaiting_name,
    don't save it as their company name — route them properly instead.
    """
    step = sub["onboarding_step"] if sub else None
    content_lower = content.lower().strip() if content else ""

    # ── Brand new user (not in DB at all) ──
    if sub is None:
        add_subscriber(phone, onboarding_step="awaiting_name")
        send_text(
            phone,
            "*Welcome to TenderAlert Pro!* 🇷🇼\n\n"
            "I send daily Rwanda government tender alerts straight to WhatsApp, "
            "with AI-powered eligibility summaries so you know exactly what each bid requires.\n\n"
            "To get started — what is your *company or organisation name*?"
        )
        return

    # ── Awaiting company name ──
    if step == "awaiting_name":
        # If user sends a greeting or command instead of a name, don't save it as name
        if content_lower in KNOWN_COMMANDS or content_lower.startswith("search "):
            # Check if they already have a company name from a previous session
            existing_name = sub.get("company_name", "").strip()
            if existing_name:
                # They're a returning user — skip onboarding, mark complete
                update_subscriber(phone, onboarding_step="complete")
                company = existing_name
                sector = SECTOR_LABELS.get(sub.get("sectors", "all"), "All Sectors")
                send_text(
                    phone,
                    f"Welcome back, *{company}*! 👋\n\n"
                    f"Your sector: *{sector}*\n\n"
                    f"How can I help you today?"
                )
                send_buttons(phone, "Choose an action:", MAIN_BUTTONS)
                return
            else:
                # Genuinely new user who typed "hello" instead of their name
                send_text(
                    phone,
                    "I'd love to help! But first, I need your *company or organisation name* to get you set up.\n\n"
                    "Just type it below:"
                )
                return

        # Valid company name — save and proceed
        company = content.strip()
        update_subscriber(phone, company_name=company, onboarding_step="awaiting_sector")
        send_text(phone, f"Nice to meet you, *{company}*! 👋\n\nNow choose the sector you want tender alerts for:")
        send_sector_list(phone)
        return

    # ── Awaiting sector selection ──
    if step == "awaiting_sector":
        sector = content_lower
        if sector not in VALID_SECTORS:
            send_text(phone, "I didn't recognise that sector. Please tap one of the options below:")
            send_sector_list(phone)
            return

        label = SECTOR_LABELS.get(sector, "All Sectors")
        update_subscriber(phone, sectors=sector, onboarding_step="complete")
        send_text(
            phone,
            f"✅ *You're all set!*\n\n"
            f"Sector: *{label}*\n"
            f"Alerts: Every morning at *08:00 Kigali time*\n\n"
            f"What would you like to do first?"
        )
        send_buttons(phone, "Choose an action:", ["View Tenders", "My Status", "Help"])
        return

    # ── Awaiting name update (existing user changing name) ──
    if step == "awaiting_name_update":
        if content_lower in KNOWN_COMMANDS:
            update_subscriber(phone, onboarding_step="complete")
            send_text(phone, "Name update cancelled.")
            send_buttons(phone, "What would you like to do?", MAIN_BUTTONS)
            return

        company = content.strip()
        update_subscriber(phone, company_name=company, onboarding_step="complete")
        send_text(phone, f"✅ Updated! Your company name is now *{company}*.")
        send_buttons(phone, "What's next?", AFTER_ACTION_BUTTONS)
        return


# ── Button reply handlers ─────────────────────────────────────────────────

def handle_button_reply(phone: str, button_title: str, sub: dict):
    """Route a Quick Reply button tap to the right action."""
    print(f"[webhook] Button tap from {phone}: {button_title!r}")

    # View tenders / Get digest / Get started
    if button_title in (BTN_VIEW_TENDERS, BTN_GET_DIGEST_ALT, BTN_GET_STARTED):
        tenders = get_tenders_for_subscriber(phone, since_hours=48)
        if tenders:
            message = format_tender_alert(tenders, subscriber_name=sub.get("company_name"))
            send_text(phone, message)
            send_buttons(phone, "What's next?", AFTER_TENDERS_BUTTONS)
        else:
            send_text(phone, "No new tenders in your sector in the last 48 hours. Check back tomorrow morning! ☀️")
            send_buttons(phone, "What would you like to do?", AFTER_ACTION_BUTTONS)

    # Change sector
    elif button_title in (BTN_CHANGE_SECTOR, BTN_CHANGE_SECTORS_ALT):
        update_subscriber(phone, onboarding_step="awaiting_sector")
        send_text(phone, "No problem! Select a new sector below:")
        send_sector_list(phone)

    # Stop alerts — ask for confirmation
    elif button_title in (BTN_STOP_ALERTS, BTN_UNSUBSCRIBE_ALT):
        send_buttons(
            phone,
            "Are you sure you want to stop receiving tender alerts?",
            ["Yes, unsubscribe", "No, keep alerts"]
        )

    # Unsubscribe confirmation: YES
    elif button_title == BTN_CONFIRM_UNSUB:
        remove_subscriber(phone)
        send_text(
            phone,
            "You've been unsubscribed from TenderAlert Pro.\n\n"
            "Message us anytime to rejoin — we'll be here! 👋"
        )

    # Unsubscribe confirmation: NO
    elif button_title == BTN_KEEP_ALERTS:
        send_text(phone, "Great, your alerts are still active! ✅")
        send_buttons(phone, "What would you like to do?", MAIN_BUTTONS)

    # My Status button
    elif button_title == BTN_MY_STATUS:
        send_text(phone, format_status_message(sub))
        send_buttons(phone, "What's next?", AFTER_ACTION_BUTTONS)

    # Help button
    elif button_title == BTN_HELP:
        send_text(phone, HELP_TEXT)
        send_buttons(phone, "Quick actions:", MAIN_BUTTONS)

    else:
        send_text(phone, "I didn't recognise that button. Here's what I can do:")
        send_buttons(phone, "Choose an action:", MAIN_BUTTONS)


# ── Text command handlers ─────────────────────────────────────────────────

def handle_text(phone: str, text: str, sub: dict):
    """Route a free-form text command from an onboarded user."""
    text_lower = text.lower().strip()
    print(f"[webhook] Text from {phone}: {text_lower!r}")

    # ── HELP ──
    if text_lower == "help":
        send_text(phone, HELP_TEXT)
        send_buttons(phone, "Quick actions:", MAIN_BUTTONS)

    # ── STATUS / ME / PROFILE ──
    elif text_lower in ("status", "me", "profile", "my profile", "my status"):
        send_text(phone, format_status_message(sub))
        send_buttons(phone, "What's next?", AFTER_ACTION_BUTTONS)

    # ── SECTORS / CHANGE SECTOR ──
    elif text_lower in ("sectors", "sector", "change sector", "change sectors"):
        update_subscriber(phone, onboarding_step="awaiting_sector")
        send_text(phone, "Select a new sector below:")
        send_sector_list(phone)

    # ── NAME / CHANGE NAME ──
    elif text_lower in ("name", "change name", "update name", "company name"):
        update_subscriber(phone, onboarding_step="awaiting_name_update")
        send_text(phone, "What's the new company or organisation name?")

    # ── LIST / TENDERS / LATEST ──
    elif text_lower in ("list", "tenders", "latest", "new", "today"):
        tenders = get_tenders_for_subscriber(phone, since_hours=48)
        if tenders:
            message = format_tender_alert(tenders, subscriber_name=sub.get("company_name"))
            send_text(phone, message)
            send_buttons(phone, "What's next?", AFTER_TENDERS_BUTTONS)
        else:
            send_text(phone, "No new tenders in your sector in the last 48 hours.\n\nTry *SEARCH <keyword>* to find specific tenders.")
            send_buttons(phone, "What would you like to do?", AFTER_ACTION_BUTTONS)

    # ── SEARCH <keyword> ──
    elif text_lower.startswith("search "):
        keyword = text[7:].strip()
        if len(keyword) < 2:
            send_text(phone, "Please provide a keyword to search.\n\nExample: *search construction*")
            send_buttons(phone, "Or try:", MAIN_BUTTONS)
        else:
            results = search_tenders(keyword, limit=5)
            send_text(phone, format_search_results(results, keyword))
            send_buttons(phone, "What's next?", AFTER_TENDERS_BUTTONS)

    # ── STOP / UNSUBSCRIBE (with confirmation) ──
    elif text_lower in ("stop", "unsubscribe", "quit", "cancel"):
        send_buttons(
            phone,
            "Are you sure you want to stop receiving tender alerts?",
            ["Yes, unsubscribe", "No, keep alerts"]
        )

    # ── GREETINGS (returning user) ──
    elif text_lower in ("hi", "hello", "hey", "start", "join", "subscribe"):
        company = sub.get("company_name") or "there"
        sector = SECTOR_LABELS.get(sub.get("sectors", "all"), "All Sectors")
        send_text(
            phone,
            f"Welcome back, *{company}*! 👋\n\n"
            f"Your sector: *{sector}*"
        )
        send_buttons(phone, "What would you like to do?", MAIN_BUTTONS)

    # ── UNKNOWN COMMAND ──
    else:
        send_text(
            phone,
            "I didn't recognise that command.\n\n"
            "Try one of the buttons below, or type *HELP* for all commands."
        )
        send_buttons(phone, "Choose an action:", MAIN_BUTTONS)


# ── Main dispatcher ───────────────────────────────────────────────────────

def process_webhook_entry(entry: dict):
    """Process a single webhook entry. Called by the FastAPI route."""
    phone = parse_phone(entry)
    if not phone:
        return

    msg_type, content = parse_message(entry)
    if msg_type == "unknown":
        return

    sub = get_subscriber(phone)
    step = sub["onboarding_step"] if sub else None

    # ── Onboarding gate ──
    if sub is None or step in ("awaiting_name", "awaiting_sector", "awaiting_name_update"):
        handle_onboarding(phone, msg_type, content, sub)
        return

    # ── Onboarded users: full command set ──
    if msg_type == "button_reply":
        handle_button_reply(phone, content, sub)

    elif msg_type == "list_reply":
        sector = content if content in VALID_SECTORS else "all"
        label = SECTOR_LABELS.get(sector, "All Sectors")
        update_subscriber(phone, sectors=sector, onboarding_step="complete")
        send_text(phone, f"✅ Updated! You'll now receive alerts for *{label}*.")
        send_buttons(phone, "What's next?", AFTER_ACTION_BUTTONS)

    elif msg_type == "text" and content:
        handle_text(phone, content, sub)
