"""
bot.py — Flask webhook handler for incoming WhatsApp messages.

Message flow:
  1. New number messages → onboarding wizard (name → sector → complete)
  2. Onboarded users → button replies + text commands

Onboarding steps (stored in subscribers.onboarding_step):
  awaiting_name   → bot asked for company/org name, waiting for reply
  awaiting_sector → bot sent sector list, waiting for user to tap one
  complete        → fully onboarded, receives daily alerts

Button payloads (from procurement_notice template):
  "Get Today's Digest"  → send full tender list (free-form, inside session)
  "Change My Sectors"   → re-open sector list picker
  "Unsubscribe"         → deactivate subscriber

Webhook verification (GET /webhook) is also handled here.
"""

from flask import Flask, request, jsonify

from config import WHATSAPP_VERIFY_TOKEN, FLASK_SECRET_KEY, FLASK_PORT
from database import (
    add_subscriber, remove_subscriber, get_subscriber,
    update_subscriber, get_active_subscribers, get_new_tenders, init_db
)
from whatsapp import send_text, send_sector_list, send_buttons, send_tender_digest

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

VALID_SECTORS = ["ict", "construction", "health", "education", "agriculture", "consulting", "supply", "all"]

HELP_TEXT = (
    "*TenderAlert Pro — Commands*\n\n"
    "• *STOP* — Unsubscribe\n"
    "• *SECTORS* — Change your sector filter\n"
    "• *HELP* — Show this menu"
)

# Button titles from the procurement_notice template (must match exactly, lowercase)
BTN_GET_DIGEST     = "get today's digest"
BTN_CHANGE_SECTORS = "change my sectors"
BTN_UNSUBSCRIBE    = "unsubscribe"


# ---------------------------------------------------------------------------
# Payload parsers
# ---------------------------------------------------------------------------

def parse_phone(entry: dict) -> str | None:
    """Extract sender phone number from a webhook payload entry."""
    try:
        return entry["changes"][0]["value"]["messages"][0]["from"]
    except (KeyError, IndexError):
        return None


def parse_message(entry: dict) -> tuple[str, str]:
    """
    Return (msg_type, content) from a webhook entry.

    msg_type values:
      'text'         — free-form text message
      'button_reply' — Quick Reply button tap (from template)
      'list_reply'   — List row selection (from sector picker)
      'unknown'      — status updates or unsupported types
    content is always lowercased and stripped.
    """
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
            # id is the sector key we set (e.g. "ict", "construction")
            row_id = interactive["list_reply"].get("id", "").strip().lower()
            return "list_reply", row_id

    return msg_type, ""


# ---------------------------------------------------------------------------
# Onboarding state machine
# ---------------------------------------------------------------------------

def handle_onboarding(phone: str, msg_type: str, content: str, sub: dict | None):
    """
    Drive a new user through the 2-step onboarding wizard.

    Step 1 (awaiting_name):  ask for company/org name
    Step 2 (awaiting_sector): show interactive sector list
    Step 3 (complete):        confirm and start daily alerts
    """
    step = sub["onboarding_step"] if sub else None

    # Brand-new number — create row and ask for name
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

    # Step 1: user replied with their company name
    if step == "awaiting_name":
        company = content.strip() if content else "Unknown"
        update_subscriber(phone, company_name=company, onboarding_step="awaiting_sector")
        send_text(phone, f"Nice to meet you, *{company}*! 👋\n\nNow choose the sector you want tender alerts for:")
        send_sector_list(phone)
        return

    # Step 2: user tapped a sector from the list
    if step == "awaiting_sector":
        sector = content if content in VALID_SECTORS else "all"
        label = {
            "ict": "ICT & Technology", "construction": "Works & Construction",
            "health": "Health & Pharma", "education": "Education",
            "consulting": "Consulting & Services", "supply": "Supply & Goods",
            "all": "All Sectors",
        }.get(sector, "All Sectors")

        update_subscriber(phone, sectors=sector, onboarding_step="complete")
        send_text(
            phone,
            f"✅ *You're all set!*\n\n"
            f"Sector: *{label}*\n\n"
            f"You'll receive a daily morning alert every time new Rwanda government tenders "
            f"are published in your sector.\n\n"
            f"Reply *HELP* anytime to see available commands."
        )
        return


# ---------------------------------------------------------------------------
# Button reply handlers (onboarded users only)
# ---------------------------------------------------------------------------

def handle_button_reply(phone: str, button_title: str):
    """Route a Quick Reply button tap to the right action."""
    print(f"[bot] Button tap from {phone}: {button_title!r}")

    if button_title == BTN_GET_DIGEST:
        init_db()
        tenders = get_new_tenders(since_hours=25)
        if tenders:
            # Free-form is fine here — user just tapped a button (24h session open)
            send_tender_digest(phone, tenders, use_template=False)
        else:
            send_text(phone, "No new tenders in the last 24 hours. Check back tomorrow morning! ☀️")

    elif button_title == BTN_CHANGE_SECTORS:
        update_subscriber(phone, onboarding_step="awaiting_sector")
        send_text(phone, "No problem! Select a new sector below:")
        send_sector_list(phone)

    elif button_title == BTN_UNSUBSCRIBE:
        remove_subscriber(phone)
        send_text(
            phone,
            "You've been unsubscribed from TenderAlert Pro.\n\n"
            "Message us anytime to rejoin. We'll miss you! 👋"
        )

    else:
        send_text(phone, HELP_TEXT)


# ---------------------------------------------------------------------------
# Text command handlers (onboarded users only)
# ---------------------------------------------------------------------------

def handle_text(phone: str, text: str):
    """Route a free-form text command."""
    print(f"[bot] Text from {phone}: {text!r}")

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


# ---------------------------------------------------------------------------
# Webhook routes
# ---------------------------------------------------------------------------

@app.get("/webhook")
def verify_webhook():
    """Meta webhook verification — called once when you register the webhook URL."""
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        print("[bot] Webhook verified.")
        return challenge, 200
    return "Forbidden", 403


@app.post("/webhook")
def receive_message():
    """Handle all incoming WhatsApp events."""
    data = request.get_json(silent=True) or {}

    for entry in data.get("entry", []):
        phone = parse_phone(entry)
        if not phone:
            continue

        msg_type, content = parse_message(entry)

        # Status updates (delivered, read) — ignore silently
        if msg_type == "unknown":
            continue

        sub = get_subscriber(phone)
        step = sub["onboarding_step"] if sub else None

        # --- Onboarding gate ---
        # New user OR mid-onboarding: drive the wizard regardless of message type
        if sub is None or step in ("awaiting_name", "awaiting_sector"):
            # For list_reply during awaiting_sector, pass the row id as content
            handle_onboarding(phone, msg_type, content, sub)
            continue

        # --- Onboarded users: full command set ---
        if msg_type == "button_reply":
            handle_button_reply(phone, content)

        elif msg_type == "list_reply":
            # User tapped sector list outside onboarding (re-triggered via "Change My Sectors")
            sector = content if content in VALID_SECTORS else "all"
            label = {
                "ict": "ICT & Technology", "construction": "Works & Construction",
                "health": "Health & Pharma", "education": "Education",
                "consulting": "Consulting & Services", "supply": "Supply & Goods",
                "all": "All Sectors",
            }.get(sector, "All Sectors")
            update_subscriber(phone, sectors=sector, onboarding_step="complete")
            send_text(phone, f"✅ Updated! You'll now receive alerts for *{label}*.")

        elif msg_type == "text" and content:
            handle_text(phone, content)

    return jsonify({"status": "ok"}), 200


@app.get("/health")
def health():
    return jsonify({"status": "running", "service": "TenderAlert Pro Bot"}), 200


if __name__ == "__main__":
    print(f"[bot] Starting webhook server on port {FLASK_PORT}")
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False)
