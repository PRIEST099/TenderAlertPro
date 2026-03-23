"""
whatsapp.py — Send messages via the Meta WhatsApp Cloud API.

WhatsApp message types:
  - Template messages : business-initiated, works anytime, requires pre-approved templates
  - Free-form text    : only works within 24h AFTER the user messages us first (session window)

For TenderAlert Pro:
  - Daily alerts → template messages (TENDER_ALERT_TEMPLATE)
  - Replies to user messages → free-form text (inside 24h session window)
"""

import requests
from config import WHATSAPP_TOKEN, WHATSAPP_API_URL, WHATSAPP_PHONE_NUMBER_ID

# Name of the approved Meta template used for outbound tender alerts.
# "hello_world" ships with every Meta account — use it for connection tests.
# Replace with "tender_daily_alert" once you create and get that template approved.
TENDER_ALERT_TEMPLATE = "tender_update"
TENDER_ALERT_TEMPLATE_LANG = "en_US"


def check_sender_status() -> dict:
    """
    Query Meta API for the current status of our sending phone number.
    Returns a dict with display_phone_number, code_verification_status, platform_type.
    """
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"error": "Missing WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID"}
    try:
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}",
            params={
                "access_token": WHATSAPP_TOKEN,
                "fields": "display_phone_number,verified_name,code_verification_status,account_mode,platform_type",
            },
            timeout=10,
        )
        return r.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def send_text(phone: str, message: str) -> bool:
    """
    Send a plain text WhatsApp message to a phone number.
    Phone must be in international format without '+', e.g. '250788123456'.
    Returns True on success, False with a descriptive error on failure.
    """
    if not WHATSAPP_TOKEN or not WHATSAPP_API_URL:
        print("[whatsapp] ERROR: Missing WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID in .env")
        return False

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message},
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(WHATSAPP_API_URL, json=payload, headers=headers, timeout=15)
        data = resp.json()

        if resp.status_code == 200:
            msg_id = data.get("messages", [{}])[0].get("id", "unknown")
            print(f"[whatsapp] API accepted message to {phone} (id: {msg_id[:30]}...)")
            print(f"[whatsapp] NOTE: API acceptance != delivery. Check phone for the message.")
            return True

        # Parse and surface useful error info
        err = data.get("error", {})
        code = err.get("code")
        msg = err.get("message", "Unknown error")

        if code == 131030:
            print(f"[whatsapp] ERROR {code}: Recipient {phone} is not in the approved test recipient list.")
            print("  Fix: Go to Meta Developer Console → WhatsApp → API Setup → Manage phone number list")
            print(f"  Add +{phone}, enter the code WhatsApp sends to that number.")
        elif code == 133010:
            print(f"[whatsapp] ERROR {code}: Sender phone number is not registered/verified.")
            print("  Fix: Go to Meta Developer Console → WhatsApp → API Setup")
            print("  Click 'Send verification code' next to the test number, enter the code.")
        else:
            print(f"[whatsapp] ERROR {code}: {msg}")

        return False

    except requests.RequestException as e:
        print(f"[whatsapp] Request failed to {phone}: {e}")
        return False


def send_template(phone: str, template_name: str, lang: str = "en_US", components: list = None) -> bool:
    """
    Send a WhatsApp template message — works for business-initiated conversations
    (i.e. when the user has NOT messaged us first).

    components: list of template component objects for variable substitution.
    See Meta docs for format:
    https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates
    """
    if not WHATSAPP_TOKEN or not WHATSAPP_API_URL:
        print("[whatsapp] ERROR: Missing WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID in .env")
        return False

    template_block: dict = {"name": template_name, "language": {"code": lang}}
    if components:
        template_block["components"] = components

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": template_block,
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(WHATSAPP_API_URL, json=payload, headers=headers, timeout=15)
        data = resp.json()
        if resp.status_code == 200:
            msg_id = data.get("messages", [{}])[0].get("id", "")
            print(f"[whatsapp] Template '{template_name}' sent to {phone} (id: {msg_id[:30]}...)")
            return True
        err = data.get("error", {})
        print(f"[whatsapp] Template send failed: {err.get('code')} — {err.get('message')}")
        return False
    except requests.RequestException as e:
        print(f"[whatsapp] Request failed: {e}")
        return False


def format_tender_alert(tenders: list[dict], subscriber_name: str = None) -> str:
    """
    Format a list of tender dicts into a clean WhatsApp digest message.
    Includes AI summary + eligibility checklist when available.
    Keeps it under WhatsApp's 4096-char limit.
    """
    greeting = f"Hello {subscriber_name}! " if subscriber_name else ""
    lines = [
        f"*{greeting}🇷🇼 TenderAlert Pro — Daily Digest*",
        f"_{len(tenders)} new tender(s) matching your profile_\n",
    ]

    for i, t in enumerate(tenders[:5], 1):  # max 5 per message to stay readable
        value_str = f"RWF {t['value_amount']:,.0f}" if t.get("value_amount") else "Value TBD"
        deadline = (t.get("deadline") or "")[:10] or "See link"

        block = (
            f"*{i}. {t['title']}*\n"
            f"   🏢 {t['buyer_name']}\n"
            f"   📂 {t['category']}  |  💰 {value_str}\n"
            f"   ⏰ Deadline: {deadline}"
        )

        # Append AI summary + eligibility checklist when available
        if t.get("ai_summary"):
            block += f"\n\n{t['ai_summary']}"

        block += f"\n\n   🔗 {t['source_url']}"
        lines.append(block)

    if len(tenders) > 5:
        lines.append(f"\n_...and {len(tenders) - 5} more. Reply *LIST* to see more._")

    lines.append("\n_Reply *HELP* for commands | *STOP* to unsubscribe_")
    return "\n\n".join(lines)


def send_tender_template(phone: str, tender_count: int) -> bool:
    """
    Send the daily tender alert template with Quick Reply buttons.

    Template: tender_daily_alert
    Variable {{1}} = number of new tenders today

    Buttons (Quick Reply — user taps one, webhook receives button payload):
      "Get Today's Digest"  → bot sends the full AI-enriched tender list
      "Change My Sectors"   → bot sends sector picker
      "Unsubscribe"         → bot removes subscriber

    This is a business-initiated message — works anytime without a session window.
    """
    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(tender_count)}
            ],
        }
    ]
    return send_template(phone, TENDER_ALERT_TEMPLATE, lang=TENDER_ALERT_TEMPLATE_LANG, components=components)


def send_tender_digest(phone: str, tenders: list[dict], use_template: bool = True) -> bool:
    """
    Send a tender digest to a subscriber.

    use_template=True  → sends template with buttons (works anytime, for daily scheduler)
    use_template=False → sends free-form text (only inside a 24h session window, e.g. after
                         the user taps 'Get Today's Digest' and the bot replies inline)
    """
    if not tenders:
        return False

    if use_template:
        return send_tender_template(phone, tender_count=len(tenders))

    # Free-form — only valid inside a 24h session (bot replies to button taps)
    message = format_tender_alert(tenders)
    return send_text(phone, message)


def send_sector_list(phone: str) -> bool:
    """
    Send an interactive LIST message so the user can pick their sector with one tap.
    List messages support up to 10 rows — no typing required.
    Only valid inside a 24-hour session window (i.e. the user has just messaged us).
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": "Select your primary sector to receive daily tender alerts:"
            },
            "action": {
                "button": "Choose Sector",
                "sections": [
                    {
                        "title": "Available Sectors",
                        "rows": [
                            {"id": "ict",          "title": "ICT & Technology"},
                            {"id": "construction", "title": "Works & Construction"},
                            {"id": "health",       "title": "Health & Pharma"},
                            {"id": "education",    "title": "Education"},
                            {"id": "consulting",   "title": "Consulting & Services"},
                            {"id": "supply",       "title": "Supply & Goods"},
                            {"id": "all",          "title": "All Sectors"},
                        ],
                    }
                ],
            },
        },
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(WHATSAPP_API_URL, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            print(f"[whatsapp] Sector list sent to {phone}")
            return True
        print(f"[whatsapp] Sector list failed: {resp.json().get('error', {}).get('message')}")
        return False
    except requests.RequestException as e:
        print(f"[whatsapp] send_sector_list failed: {e}")
        return False


def send_buttons(phone: str, body: str, buttons: list[str]) -> bool:
    """
    Send a quick-reply button message (max 3 buttons).
    Only valid inside a 24-hour session window.
    """
    if not buttons or len(buttons) > 3:
        raise ValueError("send_buttons requires 1–3 button labels.")
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": str(i), "title": btn}}
                    for i, btn in enumerate(buttons)
                ]
            },
        },
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(WHATSAPP_API_URL, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            print(f"[whatsapp] Buttons sent to {phone}")
            return True
        print(f"[whatsapp] send_buttons failed: {resp.json().get('error', {}).get('message')}")
        return False
    except requests.RequestException as e:
        print(f"[whatsapp] send_buttons failed: {e}")
        return False


def send_welcome(phone: str) -> bool:
    message = (
        "*Welcome to TenderAlert Pro!* \n\n"
        "You're now subscribed to daily Rwanda government tender alerts.\n\n"
        "You'll receive a message every morning with new tenders matching your sectors.\n\n"
        "Commands:\n"
        "• Reply *SECTORS* to change which sectors you follow\n"
        "• Reply *STOP* to unsubscribe\n\n"
        "_Powered by Rwanda RPPA Umucyo data_"
    )
    return send_text(phone, message)


def format_status_message(sub: dict) -> str:
    """Format a subscriber's profile info for the STATUS command."""
    sector_labels = {
        "ict": "ICT & Technology", "construction": "Works & Construction",
        "health": "Health & Pharma", "education": "Education",
        "consulting": "Consulting & Services", "supply": "Supply & Goods",
        "all": "All Sectors",
    }
    sector = sector_labels.get(sub.get("sectors", "all"), sub.get("sectors", "all"))
    company = sub.get("company_name") or "Not set"
    joined = (sub.get("created_at") or "")[:10] or "Unknown"
    status = "Active" if sub.get("active") else "Inactive"

    return (
        f"*Your TenderAlert Pro Subscription*\n\n"
        f"🏢 Company: *{company}*\n"
        f"📂 Sector: *{sector}*\n"
        f"📅 Joined: {joined}\n"
        f"{'✅' if sub.get('active') else '❌'} Status: {status}\n\n"
        f"Reply *SECTORS* to change sector\n"
        f"Reply *NAME* to update company name"
    )


def format_search_results(tenders: list[dict], keyword: str) -> str:
    """Format tender search results for the SEARCH command."""
    if not tenders:
        return f"No active tenders matching '*{keyword}*'.\n\nTry a different keyword, e.g. *search construction*"

    lines = [f"🔍 *{len(tenders)} tender(s) matching '{keyword}':*\n"]

    for i, t in enumerate(tenders[:5], 1):
        value_str = f"RWF {t['value_amount']:,.0f}" if t.get("value_amount") else "Value TBD"
        deadline = (t.get("deadline") or "")[:10] or "TBD"
        lines.append(
            f"*{i}. {t['title']}*\n"
            f"   🏢 {t['buyer_name']}\n"
            f"   💰 {value_str}  |  ⏰ {deadline}\n"
            f"   🔗 {t['source_url']}"
        )

    lines.append("\n_Reply *LIST* for all recent tenders | *HELP* for commands_")
    return "\n\n".join(lines)
