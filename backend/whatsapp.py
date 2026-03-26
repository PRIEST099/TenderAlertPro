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


def _log_outbound(phone: str, msg_type: str, content: str, command: str = ""):
    """Log an outbound message to the interaction_logs table."""
    try:
        from database import log_interaction
        log_interaction(phone, direction="outbound", msg_type=msg_type, content=content, command=command)
    except Exception:
        pass  # Don't let logging failures break message sending

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
            _log_outbound(phone, "text", message[:200])
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
            _log_outbound(phone, "template", f"template:{template_name}", command="daily_alert")
            return True
        err = data.get("error", {})
        print(f"[whatsapp] Template send failed: {err.get('code')} — {err.get('message')}")
        return False
    except requests.RequestException as e:
        print(f"[whatsapp] Request failed: {e}")
        return False


def notify_admin(message: str, amount: str = None, phone_from: str = None,
                  pay_type: str = None, ref: str = None) -> bool:
    """
    Send a notification to the admin. Three-level fallback:
    1. send_text (works if admin messaged bot within 24h)
    2. payment_alert template with structured params (works anytime, carries data)
    3. hello_world template (last resort, no data but admin knows to check dashboard)
    """
    from config import ADMIN_NOTIFICATION_NUMBER
    if not ADMIN_NOTIFICATION_NUMBER:
        print("[whatsapp] No ADMIN_NOTIFICATION_NUMBER configured — skipping notification")
        return False

    # Try free-form text first (works within 24h session)
    success = send_text(ADMIN_NOTIFICATION_NUMBER, message)
    if success:
        return True

    # Fallback 1: payment_alert template with structured data
    if amount and phone_from:
        print("[whatsapp] send_text to admin failed (no session), trying payment_alert template")
        components = [{
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(amount)},
                {"type": "text", "text": str(phone_from)},
                {"type": "text", "text": str(pay_type or "payment")},
                {"type": "text", "text": str(ref or "N/A")},
            ]
        }]
        result = send_template(ADMIN_NOTIFICATION_NUMBER, "payment_alert", components=components)
        if result:
            return True

    # Fallback 2: hello_world template (last resort — admin checks dashboard)
    print("[whatsapp] Falling back to hello_world template for admin notification")
    return send_template(ADMIN_NOTIFICATION_NUMBER, "hello_world")


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
                        "title": "Popular Sectors",
                        "rows": [
                            {"id": "all",            "title": "All Sectors", "description": "Get alerts for everything"},
                            {"id": "ict",            "title": "ICT & Technology"},
                            {"id": "construction",   "title": "Construction", "description": "Infrastructure & works"},
                            {"id": "health",         "title": "Health & Medical"},
                            {"id": "consulting",     "title": "Consulting & Advisory"},
                        ],
                    },
                    {
                        "title": "More Sectors",
                        "rows": [
                            {"id": "supply",         "title": "Supply & Equipment"},
                            {"id": "education",      "title": "Education & Training"},
                            {"id": "agriculture",    "title": "Agriculture"},
                            {"id": "energy",         "title": "Energy & Utilities"},
                            {"id": "other",          "title": "Other / Uncategorized", "description": "Unique tenders outside standard sectors"},
                        ],
                    },
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
            _log_outbound(phone, "list", "sector_picker", command="sector_list")
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
            _log_outbound(phone, "buttons", f"buttons:{','.join(buttons)}", command="buttons")
            return True
        print(f"[whatsapp] send_buttons failed: {resp.json().get('error', {}).get('message')}")
        return False
    except requests.RequestException as e:
        print(f"[whatsapp] send_buttons failed: {e}")
        return False


def send_tender_list(phone: str, tenders: list[dict], tier: str = "pro") -> bool:
    """
    Send an interactive LIST of tenders — user taps one to see AI-enriched details.
    Each row ID is 'tender:{index}' to distinguish from sector list replies.
    Max 10 tenders per list. Free tier hides buyer name.
    """
    if not tenders:
        return send_text(phone, "No active tenders found in your sector right now.")

    rows = []
    for i, t in enumerate(tenders[:10]):
        title = t.get("title", "Untitled")[:24]  # WhatsApp max row title
        deadline = (t.get("deadline") or "")[:10] or "No deadline"
        if tier == "free":
            desc = f"Deadline: {deadline}"[:72]
        else:
            desc = f"{t.get('buyer_name', '')[:30]} | {deadline}"[:72]

        rows.append({
            "id": f"tender:{i}",
            "title": title,
            "description": desc,
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": f"📋 *{len(tenders)} active tender(s)* in your sector.\n\nTap any tender to see the full AI-powered eligibility analysis:"
            },
            "action": {
                "button": "View Tenders",
                "sections": [{
                    "title": "Active Tenders",
                    "rows": rows,
                }],
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
            print(f"[whatsapp] Tender list ({len(rows)} items) sent to {phone}")
            _log_outbound(phone, "list", f"tender_list:{len(rows)}_items", command="tender_list")
            return True
        print(f"[whatsapp] Tender list failed: {resp.json().get('error', {}).get('message')}")
        return False
    except requests.RequestException as e:
        print(f"[whatsapp] send_tender_list failed: {e}")
        return False


def format_tender_detail(tender: dict) -> str:
    """
    Format a single tender with full AI enrichment for WhatsApp.
    This is what users see when they tap a specific tender.
    """
    title = tender.get("title", "Untitled")
    buyer = tender.get("buyer_name", "Unknown")
    category = tender.get("category", "Other")
    sub_category = tender.get("sub_category", "")
    value_str = f"RWF {tender['value_amount']:,.0f}" if tender.get("value_amount") else "Value not disclosed"
    deadline = (tender.get("deadline") or "")[:10] or "Not specified"
    ocid = tender.get("ocid", "")
    status = tender.get("status", "unknown")

    # Deadline urgency
    deadline_note = ""
    if deadline != "Not specified":
        try:
            from datetime import datetime, timezone
            dl = datetime.fromisoformat(tender["deadline"].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            # Compare dates (not datetimes) so "today" is handled correctly
            if dl.date() < now.date():
                deadline_note = " ⛔ *EXPIRED*"
            elif dl.date() == now.date():
                deadline_note = " ⚠️ *Ends Today*"
            elif (dl.date() - now.date()).days <= 3:
                deadline_note = f" 🔴 *{(dl.date() - now.date()).days}d left*"
            elif (dl.date() - now.date()).days <= 7:
                deadline_note = f" 🟡 *{(dl.date() - now.date()).days}d left*"
            else:
                deadline_note = f" 🟢 *{(dl.date() - now.date()).days}d left*"
        except Exception:
            pass

    # Category display
    cat_display = category
    if sub_category and sub_category != category and sub_category != "Other":
        cat_display = f"{category} → {sub_category}"

    lines = [
        f"📋 *{title}*\n",
        f"🏢 *Buyer:* {buyer}",
        f"📂 *Category:* {cat_display}",
        f"💰 *Value:* {value_str}",
        f"⏰ *Deadline:* {deadline}{deadline_note}",
        f"📊 *Status:* {status.title()}",
    ]

    # AI enrichment (the main value)
    ai_summary = tender.get("ai_summary")
    if ai_summary:
        lines.append(f"\n🤖 *AI Eligibility Analysis:*\n\n{ai_summary}")
    else:
        lines.append("\n⏳ _AI analysis not yet available for this tender._")

    # Reference number for searching on Umucyo
    if ocid:
        ref = ocid.replace("ocds-ozzobm-", "")
        lines.append(f"\n📎 *Ref:* {ref}")
        lines.append(f"🔗 View on Umucyo: https://umucyo.gov.rw")

    return "\n".join(lines)


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
        "ict": "ICT & Technology", "construction": "Construction & Infrastructure",
        "health": "Health & Medical", "education": "Education & Training",
        "consulting": "Consulting & Advisory", "supply": "Supply & Equipment",
        "agriculture": "Agriculture & Livestock", "energy": "Energy & Utilities",
        "other": "Other / Uncategorized", "all": "All Sectors",
    }
    sector = sector_labels.get(sub.get("sectors", "all"), sub.get("sectors", "all"))
    company = sub.get("company_name") or "Not set"
    joined = (sub.get("created_at") or "")[:10] or "Unknown"
    status = "Active" if sub.get("active") else "Inactive"
    tier = (sub.get("subscription_tier") or "free").title()
    credits = sub.get("credits", 0)
    analyses = sub.get("deep_analyses_used", 0)

    tier_icons = {"pro": "👑", "business": "💎", "regular": "🟢", "free": "🆓"}
    tier_icon = tier_icons.get(tier.lower(), "🆓")

    lines = [
        f"*Your TenderAlert Pro Profile* 🇷🇼\n",
        f"🏢 Company: *{company}*",
        f"📂 Sector: *{sector}*",
        f"📅 Joined: {joined}",
        f"{'✅' if sub.get('active') else '❌'} Status: *{status}*",
        f"\n{tier_icon} Plan: *{tier}*",
        f"🔍 Deep analyses used: *{analyses}*",
    ]

    if credits > 0:
        lines.append(f"💳 Proposal credits: *{credits}*")

    lines.append(
        f"\n_Tap a button below or type:_\n"
        f"*SECTORS* — change sector\n"
        f"*NAME* — update company name\n"
        f"*CREDITS* — view balance"
    )

    return "\n".join(lines)


def format_deep_analysis(analysis: dict, tender: dict, user_docs: list[dict] = None) -> list[str]:
    """
    Format a deep analysis result into 2-3 WhatsApp messages.
    Each message stays under 4096 characters.
    If user_docs provided, cross-references required docs with uploaded docs.
    Returns a list of message strings.
    """
    messages = []

    # ── Message 1: Summary + Qualification + Documents ───────────────
    qual = analysis.get("qualification", {})
    assessment = qual.get("assessment", "NEEDS_REVIEW")
    assessment_emoji = {"LIKELY_ELIGIBLE": "✅", "UNLIKELY": "❌", "NEEDS_REVIEW": "⚠️"}.get(assessment, "⚠️")
    assessment_label = assessment.replace("_", " ").title()

    msg1_parts = [
        f"📊 *DEEP ANALYSIS*",
        f"*{tender.get('title', '')}*",
        "",
        f"📝 {analysis.get('summary', 'No summary available.')}",
        "",
        f"{assessment_emoji} *Qualification: {assessment_label}*",
    ]
    for reason in qual.get("reasons", [])[:5]:
        msg1_parts.append(f"  • {reason}")

    docs = analysis.get("required_documents", [])
    if docs:
        msg1_parts.append("")
        msg1_parts.append("📋 *Required Documents:*")

        # Cross-reference with user's uploaded documents
        user_doc_types = {d["doc_type"] for d in (user_docs or [])}
        DOC_KEYWORD_MAP = {
            "rra": ["tax", "rra", "tax clearance"],
            "rdb": ["registration", "rdb", "company registration"],
            "rssb": ["rssb", "social security", "pension"],
            "vat": ["vat"],
            "profile": ["profile", "brochure", "company profile"],
            "contract": ["contract", "reference", "past contract", "experience"],
            "cv": ["cv", "personnel", "staff", "curriculum"],
            "iso": ["iso", "certification", "quality"],
        }

        on_file = 0
        for i, doc in enumerate(docs[:8], 1):
            doc_lower = doc.lower()
            matched = False
            for doc_type, keywords in DOC_KEYWORD_MAP.items():
                if doc_type in user_doc_types and any(kw in doc_lower for kw in keywords):
                    msg1_parts.append(f"  {i}. ✅ {doc} _(on file)_")
                    matched = True
                    on_file += 1
                    break
            if not matched:
                msg1_parts.append(f"  {i}. ❌ {doc}")

        if user_docs is not None:
            msg1_parts.append(f"\n📁 _{on_file}/{len(docs[:8])} documents on file_")
            if on_file < len(docs[:8]):
                msg1_parts.append("_Send PDFs with caption (rdb, rra, cv...) to upload missing docs_")

    criteria = analysis.get("evaluation_criteria", [])
    if criteria:
        msg1_parts.append("")
        msg1_parts.append("📊 *Evaluation Criteria:*")
        for c in criteria[:5]:
            msg1_parts.append(f"  • {c}")

    messages.append("\n".join(msg1_parts))

    # ── Message 2: Historical Intelligence + Risks ───────────────────
    comp = analysis.get("competition_insight", {})
    msg2_parts = ["🏆 *HISTORICAL INTELLIGENCE*", ""]

    top_winners = comp.get("top_winners_from_buyer", [])
    if top_winners:
        msg2_parts.append(f"*Who wins contracts from {tender.get('buyer_name', 'this buyer')}?*")
        for i, w in enumerate(top_winners[:5], 1):
            avg = w.get("avg_amount")
            avg_str = f"avg RWF {avg:,.0f}" if avg else "amount unknown"
            msg2_parts.append(f"  {i}. {w.get('name', '?')} — {w.get('wins', 0)} win(s), {avg_str}")
        msg2_parts.append("")

    msg2_parts.append("📊 *Competition Level:*")
    num_this = comp.get("num_bidders_this_tender")
    hist_avg = comp.get("historical_avg_bidders")
    if num_this:
        msg2_parts.append(f"  • {num_this} companies bid on this tender")
    if hist_avg:
        msg2_parts.append(f"  • Historical average: {hist_avg:.1f} bidders")

    win_range = comp.get("typical_winning_range", {})
    if win_range.get("min") and win_range.get("max"):
        msg2_parts.append(f"  • Typical winning range: RWF {win_range['min']:,.0f} – {win_range['max']:,.0f}")

    tender_value = tender.get("value_amount")
    if tender_value:
        msg2_parts.append(f"  • This tender value: RWF {tender_value:,.0f}")

    budget = analysis.get("budget_info")
    if budget and budget != "Not disclosed":
        msg2_parts.append(f"  • Budget: {budget}")

    risks = analysis.get("risk_factors", [])
    if risks:
        msg2_parts.append("")
        msg2_parts.append("⚠️ *Risk Factors:*")
        for risk in risks[:5]:
            msg2_parts.append(f"  • {risk}")

    messages.append("\n".join(msg2_parts))

    # ── Message 3: Recommendation ────────────────────────────────────
    rec = analysis.get("recommendation", "RESEARCH_MORE")
    rec_emoji = {"WORTH_BIDDING": "👍", "SKIP": "⏭️", "RESEARCH_MORE": "🔍"}.get(rec, "🔍")
    rec_label = rec.replace("_", " ").title()

    msg3_parts = [
        f"{rec_emoji} *Recommendation: {rec_label}*",
        analysis.get("recommendation_reason", ""),
    ]

    deadlines = analysis.get("key_deadlines", [])
    if deadlines:
        msg3_parts.append("")
        msg3_parts.append("📅 *Key Deadlines:*")
        for d in deadlines[:3]:
            msg3_parts.append(f"  • {d.get('event', '')}: {d.get('date', '')}")

    ocid = tender.get("ocid", "")
    if ocid:
        ref = ocid.replace("ocds-ozzobm-", "")
        msg3_parts.append(f"\n📎 *Ref:* {ref}")
        msg3_parts.append(f"🔗 Search on Umucyo: umucyo.gov.rw")

    messages.append("\n".join(msg3_parts))

    return messages


def format_pipeline(items: list[dict]) -> str:
    """Format the bid pipeline as a kanban-style text list."""
    if not items:
        return "Your bid pipeline is empty.\n\nUse *SAVE [tender_id]* after viewing a tender to start tracking it."

    groups = {}
    for item in items:
        status = item.get("status", "watching")
        groups.setdefault(status, []).append(item)

    status_emoji = {"watching": "👀", "preparing": "📝", "submitted": "📤", "won": "🏆", "lost": "❌"}
    status_order = ["watching", "preparing", "submitted", "won", "lost"]

    lines = ["*📋 Your Bid Pipeline*\n"]
    for status in status_order:
        items_in_status = groups.get(status, [])
        if not items_in_status:
            continue
        emoji = status_emoji.get(status, "•")
        lines.append(f"{emoji} *{status.upper()}* ({len(items_in_status)})")
        for item in items_in_status[:5]:
            title = (item.get("title") or "Untitled")[:40]
            deadline = (item.get("deadline") or "")[:10]
            lines.append(f"  • {title}")
            if deadline:
                lines.append(f"    ⏰ Deadline: {deadline}")
        lines.append("")

    lines.append("_Reply UPDATE [id] [status] to change status_")
    return "\n".join(lines)


def format_documents_checklist(docs_on_file: list[dict]) -> str:
    """Format a document checklist showing what's uploaded vs missing."""
    DOCUMENT_TYPES = {
        "rdb": "RDB Company Registration Certificate",
        "rra": "RRA Tax Clearance Certificate",
        "rssb": "RSSB Certificate",
        "vat": "VAT Certificate",
        "profile": "Company Profile / Brochure",
        "contract": "Past Contract / Reference Letter",
        "cv": "Key Personnel CV",
        "iso": "ISO or Other Certification",
    }

    have = {d["doc_type"] for d in docs_on_file}

    lines = ["📁 *Your Documents on File:*\n"]
    for key, label in DOCUMENT_TYPES.items():
        if key in have:
            lines.append(f"  ✅ {label}")
        else:
            lines.append(f"  ❌ {label}")

    lines.append(f"\n_{len(have)}/{len(DOCUMENT_TYPES)} documents uploaded_")
    lines.append("\nSend a PDF with a caption (e.g. *rdb*, *rra*, *cv*) to upload.")
    lines.append("Reply *DOCS* anytime to see this list.")
    return "\n".join(lines)


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
