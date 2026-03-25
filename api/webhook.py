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

import os

from database import (  # noqa: E402
    add_subscriber, remove_subscriber, get_subscriber,
    update_subscriber, get_new_tenders, search_tenders,
    get_tenders_for_subscriber, init_db,
    log_interaction, get_interaction_count,
    check_analysis_quota, increment_analysis_count,
    get_company_profile, save_company_profile,
    get_user_documents, add_to_pipeline, get_pipeline, update_pipeline_status,
    log_payment, confirm_payment,
)
from whatsapp import (  # noqa: E402
    send_text, send_sector_list, send_buttons, send_tender_digest,
    send_tender_list, format_tender_detail,
    format_tender_alert, format_status_message, format_search_results,
    format_deep_analysis, format_pipeline, format_documents_checklist,
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
# In-memory cache: phone → list of tenders (for tender selection by index)
# Cleared when user selects a tender or after timeout (simple dict, not persistent)
_user_tender_cache: dict[str, list[dict]] = {}

MAIN_BUTTONS = ["View Tenders", "My Status", "Help"]
AFTER_ACTION_BUTTONS = ["View Tenders", "Change Sector", "Help"]
AFTER_TENDERS_BUTTONS = ["Change Sector", "My Status", "Help"]
AFTER_DETAIL_BUTTONS = ["Deep Analyze", "View Tenders", "Help"]
AFTER_ANALYSIS_BUTTONS = ["Save to Pipeline", "View Tenders", "Help"]

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

# Cache for current tender being viewed (for Deep Analyze flow)
_user_current_tender: dict[str, dict] = {}

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
BTN_DEEP_ANALYZE   = "deep analyze"
BTN_SAVE_PIPELINE  = "save to pipeline"
BTN_GEN_PROPOSAL   = "generate proposal"


# ── Payload parsing ───────────────────────────────────────────────────────

def parse_phone(entry: dict) -> str | None:
    try:
        return entry["changes"][0]["value"]["messages"][0]["from"]
    except (KeyError, IndexError):
        return None


def parse_message(entry: dict) -> tuple[str, str]:
    """Return (msg_type, content). msg_type: text, button_reply, list_reply, document, or raw WhatsApp type."""
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

    # View tenders / Get digest / Get started → send interactive tender list
    if button_title in (BTN_VIEW_TENDERS, BTN_GET_DIGEST_ALT, BTN_GET_STARTED):
        tenders = get_tenders_for_subscriber(phone)
        if tenders:
            # Store tenders in memory for this user so we can look them up by index
            _user_tender_cache[phone] = tenders[:10]
            send_tender_list(phone, tenders)
        else:
            send_text(phone, "No active tenders in your sector right now. Check back tomorrow morning! ☀️")
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

    # Deep Analyze
    elif button_title == BTN_DEEP_ANALYZE:
        handle_deep_analyze(phone, sub)

    # Save to Pipeline
    elif button_title == BTN_SAVE_PIPELINE:
        tender = _user_current_tender.get(phone)
        if tender:
            add_to_pipeline(phone, tender["ocid"])
            send_text(phone, f"✅ Saved to your bid pipeline as *watching*.\n\nReply *PIPELINE* to see your tracked tenders.")
            send_buttons(phone, "What's next?", MAIN_BUTTONS)
        else:
            send_text(phone, "No tender selected. Browse tenders first:")
            send_buttons(phone, "Choose an action:", MAIN_BUTTONS)

    # Generate Proposal
    elif button_title == BTN_GEN_PROPOSAL:
        tender = _user_current_tender.get(phone)
        if tender:
            handle_propose(phone, tender.get("ocid", ""), sub)
        else:
            send_text(phone, "No tender selected. Browse tenders first:")
            send_buttons(phone, "Choose an action:", MAIN_BUTTONS)

    else:
        send_text(phone, "I didn't recognise that button. Here's what I can do:")
        send_buttons(phone, "Choose an action:", MAIN_BUTTONS)


# ── Tender selection handler ───────────────────────────────────────────────

def handle_tender_selection(phone: str, content: str, sub: dict):
    """
    User tapped a specific tender from the interactive list.
    Enrich it with Claude on-the-fly if needed, then send the full detail.
    """
    print(f"[webhook] Tender selection from {phone}: {content!r}")

    # Extract index from "tender:0", "tender:1", etc.
    try:
        idx = int(content.split(":")[1])
    except (IndexError, ValueError):
        send_text(phone, "Something went wrong. Try again:")
        send_buttons(phone, "Choose an action:", MAIN_BUTTONS)
        return

    # Look up the tender from cache
    cached = _user_tender_cache.get(phone, [])
    if idx < 0 or idx >= len(cached):
        # Cache expired or invalid — re-fetch
        tenders = get_tenders_for_subscriber(phone)
        if idx < len(tenders):
            cached = tenders[:10]
            _user_tender_cache[phone] = cached
        else:
            send_text(phone, "That tender is no longer available. Here are the latest:")
            tenders = get_tenders_for_subscriber(phone)
            if tenders:
                _user_tender_cache[phone] = tenders[:10]
                send_tender_list(phone, tenders)
            else:
                send_buttons(phone, "What would you like to do?", MAIN_BUTTONS)
            return

    tender = cached[idx]

    # Enrich on-the-fly if no AI summary exists
    if not tender.get("ai_summary"):
        send_text(phone, "🤖 _Analyzing this tender with AI... one moment..._")
        try:
            from ai_enrichment import enrich_tender  # noqa: E402
            from database import save_ai_summary  # noqa: E402
            summary, tags = enrich_tender(tender)
            if summary:
                save_ai_summary(tender["ocid"], summary, tags=tags)
                tender["ai_summary"] = summary
        except Exception as e:
            print(f"[webhook] On-the-fly enrichment failed: {e}")

    # Send the full tender detail
    detail = format_tender_detail(tender)
    send_text(phone, detail)

    # Store current tender for Deep Analyze flow, then show buttons
    _user_current_tender[phone] = tender
    send_buttons(phone, "Want deeper intel on this tender?", AFTER_DETAIL_BUTTONS)

    # Clear the list cache (but keep current tender)
    _user_tender_cache.pop(phone, None)


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

    # ── LIST / TENDERS / LATEST ── send interactive list (tap to see AI detail)
    elif text_lower in ("list", "tenders", "latest", "new", "today"):
        tenders = get_tenders_for_subscriber(phone)
        if tenders:
            _user_tender_cache[phone] = tenders[:10]
            send_tender_list(phone, tenders)
        else:
            send_text(phone, "No active tenders in your sector right now.\n\nTry *SEARCH <keyword>* to find specific tenders.")
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

    # ── DOCS (document checklist) ──
    elif text_lower == "docs":
        docs = get_user_documents(phone)
        send_text(phone, format_documents_checklist(docs))
        send_buttons(phone, "What's next?", MAIN_BUTTONS)

    # ── PIPELINE (bid tracker) ──
    elif text_lower == "pipeline":
        items = get_pipeline(phone)
        send_text(phone, format_pipeline(items))
        send_buttons(phone, "What's next?", MAIN_BUTTONS)

    # ── CREDITS (check balance) ──
    elif text_lower == "credits":
        credits = sub.get("credits", 0)
        tier = sub.get("subscription_tier", "free")
        send_text(phone, f"💳 *Your Credits*\n\nPlan: *{tier.title()}*\nProposal credits: *{credits}*\n\nReply *BUY CREDITS* to top up.")
        send_buttons(phone, "What's next?", MAIN_BUTTONS)

    # ── BUY CREDITS ──
    elif text_lower in ("buy credits", "buy", "upgrade", "subscribe", "pricing"):
        handle_buy_credits(phone)

    # ── PAID [amount] ──
    elif text_lower.startswith("paid "):
        handle_paid_confirmation(phone, text)

    # ── SAVE [tender_id] ──
    elif text_lower.startswith("save "):
        tender_ref = text[5:].strip()
        handle_save_to_pipeline(phone, tender_ref)

    # ── PROPOSE [tender_id] ──
    elif text_lower.startswith("propose "):
        tender_ref = text[8:].strip()
        handle_propose(phone, tender_ref, sub)

    # ── ADMIN commands ──
    elif text_lower.startswith("admin "):
        handle_admin(phone, text)

    # ── UNKNOWN COMMAND ──
    else:
        send_text(
            phone,
            "I didn't recognise that command.\n\n"
            "Try one of the buttons below, or type *HELP* for all commands."
        )
        send_buttons(phone, "Choose an action:", MAIN_BUTTONS)


# ── Deep Analyze handler ──────────────────────────────────────────────────

PAYWALL_MESSAGE = (
    "🔒 *You've used your 3 free deep analyses this month.*\n\n"
    "Upgrade to *TenderAlert Pro* to unlock:\n"
    "  ✅ Unlimited deep analyses\n"
    "  ✅ Historical winner intelligence\n"
    "  ✅ Bid pipeline tracker\n"
    "  ✅ Priority alerts\n\n"
    "*Pro: RWF 75,000/month*\n"
    "*Business: RWF 180,000/month*\n\n"
    "Reply *BUY CREDITS* to see payment options."
)


def handle_deep_analyze(phone: str, sub: dict):
    """Perform AI deep analysis on the last-viewed tender."""
    tender = _user_current_tender.get(phone)
    if not tender:
        send_text(phone, "I lost track of which tender you were viewing. Please select one again:")
        tenders = get_tenders_for_subscriber(phone)
        if tenders:
            _user_tender_cache[phone] = tenders[:10]
            send_tender_list(phone, tenders)
        else:
            send_buttons(phone, "What would you like to do?", MAIN_BUTTONS)
        return

    # Check quota
    quota = check_analysis_quota(phone)
    if not quota["allowed"]:
        send_text(phone, PAYWALL_MESSAGE)
        send_buttons(phone, "What would you like to do?", MAIN_BUTTONS)
        return

    send_text(phone, "🔍 _Performing deep analysis with historical intelligence... this takes 10-15 seconds..._")

    try:
        from ai_enrichment import deep_analyze_tender
        analysis = deep_analyze_tender(tender)
    except Exception as e:
        print(f"[webhook] Deep analysis error: {e}")
        analysis = None

    if not analysis:
        send_text(phone, "Sorry, the deep analysis failed. Please try again later.")
        send_buttons(phone, "What would you like to do?", MAIN_BUTTONS)
        return

    # Send formatted multi-message analysis
    messages = format_deep_analysis(analysis, tender)
    for msg in messages:
        send_text(phone, msg)

    send_buttons(phone, "What's next?", AFTER_ANALYSIS_BUTTONS)

    # Increment counter and log
    increment_analysis_count(phone)
    log_interaction(phone, "outbound", "deep_analysis", f"deep:{tender.get('ocid', '')}", command="deep_analyze")
    _user_current_tender.pop(phone, None)


# ── Document handling ────────────────────────────────────────────────────

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


def handle_incoming_document(phone: str, entry: dict):
    """Handle a document (PDF) sent by the user."""
    try:
        msg = entry["changes"][0]["value"]["messages"][0]
        doc = msg.get("document", {})
        media_id = doc.get("id")
        filename = doc.get("filename", "document.pdf")
        caption = (doc.get("caption") or msg.get("text", {}).get("body", "")).strip().lower()
    except (KeyError, IndexError):
        send_text(phone, "I couldn't process that document. Please try again.")
        return

    # Detect document type from caption
    doc_type = "other"
    for key in DOCUMENT_TYPES:
        if key in caption:
            doc_type = key
            break

    try:
        from documents import download_whatsapp_media, save_document
        from database import upsert_user_document

        file_bytes = download_whatsapp_media(media_id)
        if not file_bytes:
            send_text(phone, "Failed to download the document. Please try sending it again.")
            return

        file_path = save_document(phone, doc_type, filename, file_bytes)
        doc_label = DOCUMENT_TYPES.get(doc_type, "Other Document")
        upsert_user_document(phone, doc_type, doc_label, file_path, filename)

        docs = get_user_documents(phone)
        send_text(phone, f"✅ *{doc_label} saved!*\n\n{format_documents_checklist(docs)}")
        send_buttons(phone, "What's next?", MAIN_BUTTONS)

    except Exception as e:
        print(f"[webhook] Document handling error: {e}")
        send_text(phone, "Something went wrong processing your document. Please try again.")
        send_buttons(phone, "What's next?", MAIN_BUTTONS)


# ── Pipeline handler ─────────────────────────────────────────────────────

def handle_save_to_pipeline(phone: str, tender_ref: str):
    """Save a tender to the user's bid pipeline."""
    from database import get_conn
    conn = get_conn()
    c = conn.cursor()
    # Find tender by partial OCID match
    c.execute("SELECT ocid, title FROM tenders WHERE ocid LIKE ? LIMIT 1", (f"%{tender_ref}%",))
    row = c.fetchone()
    conn.close()

    if not row:
        send_text(phone, f"No tender found matching '{tender_ref}'. Try the full reference number.")
        send_buttons(phone, "What's next?", MAIN_BUTTONS)
        return

    add_to_pipeline(phone, row[0])
    send_text(phone, f"✅ *Saved to pipeline:*\n{row[1][:60]}\n\nReply *PIPELINE* to see your tracked tenders.")
    send_buttons(phone, "What's next?", MAIN_BUTTONS)


# ── Proposal handler ─────────────────────────────────────────────────────

def handle_propose(phone: str, tender_ref: str, sub: dict):
    """Generate an AI proposal for a tender."""
    credits = sub.get("credits", 0)
    if credits < 1:
        send_text(
            phone,
            "🔒 *Proposal generation requires 1 credit.*\n\n"
            f"Your balance: *{credits} credits*\n\n"
            "Reply *BUY CREDITS* to purchase credits."
        )
        send_buttons(phone, "What's next?", MAIN_BUTTONS)
        return

    from database import get_conn
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM tenders WHERE ocid LIKE ? LIMIT 1", (f"%{tender_ref}%",))
    row = c.fetchone()
    conn.close()

    if not row:
        send_text(phone, f"No tender found matching '{tender_ref}'.")
        send_buttons(phone, "What's next?", MAIN_BUTTONS)
        return

    tender = dict(row)
    send_text(phone, "📝 _Generating your proposal draft... this takes 20-30 seconds..._")

    try:
        from documents import load_document_as_base64
        from ai_enrichment import generate_proposal_content
        from pdf_builder import build_proposal_pdf, save_proposal_pdf
        from database import log_proposal

        # Load user documents
        docs = get_user_documents(phone)
        docs_base64 = []
        for doc in docs:
            b64 = load_document_as_base64(doc["file_path"])
            if b64:
                docs_base64.append({
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": b64}
                })

        profile = get_company_profile(phone) or {}
        profile["company_name"] = sub.get("company_name", "")

        proposal = generate_proposal_content(tender, docs_base64, profile)
        if not proposal:
            send_text(phone, "Sorry, proposal generation failed. Your credit was not deducted. Try again later.")
            send_buttons(phone, "What's next?", MAIN_BUTTONS)
            return

        pdf_bytes = build_proposal_pdf(proposal, tender, sub)
        file_path = save_proposal_pdf(phone, tender.get("ocid", ""), pdf_bytes)

        # Deduct credit
        update_subscriber(phone, credits=credits - 1)
        log_proposal(phone, tender.get("ocid", ""), tender.get("title", ""), file_path)

        # Send the PDF (for now send a success message — PDF sending via WhatsApp requires public URL)
        send_text(
            phone,
            f"✅ *Proposal draft generated!*\n\n"
            f"📋 Includes: Cover letter, company profile, methodology, experience, document checklist.\n\n"
            f"⚠️ *Before submitting:*\n"
            f"  1. Review and customize the methodology\n"
            f"  2. Add your financial proposal separately\n"
            f"  3. Attach your actual certificate documents\n\n"
            f"Credits remaining: *{credits - 1}*\n"
            f"Reply *BUY CREDITS* to top up."
        )
        send_buttons(phone, "What's next?", MAIN_BUTTONS)

    except Exception as e:
        print(f"[webhook] Proposal generation error: {e}")
        send_text(phone, "Something went wrong generating the proposal. Your credit was not deducted.")
        send_buttons(phone, "What's next?", MAIN_BUTTONS)


# ── Buy credits / payment ────────────────────────────────────────────────

MOMO_NUMBER = os.getenv("MOMO_NUMBER", "078XXXXXXX")


def handle_buy_credits(phone: str):
    send_text(
        phone,
        f"💳 *TenderAlert Pro — Pricing*\n\n"
        f"*Subscriptions:*\n"
        f"  🟢 Pro: RWF 75,000/month\n"
        f"     Unlimited analyses + pipeline tracker\n"
        f"  🔵 Business: RWF 180,000/month\n"
        f"     Everything + 5 proposal credits/month\n\n"
        f"*Proposal Credits:*\n"
        f"  1 credit  — RWF 15,000\n"
        f"  3 credits — RWF 40,000 (save RWF 5,000)\n"
        f"  10 credits — RWF 120,000 (save RWF 30,000)\n\n"
        f"*How to pay (MTN MoMo):*\n"
        f"Send to: *{MOMO_NUMBER}*\n"
        f"Reference: your WhatsApp number\n\n"
        f"After payment, reply *PAID [amount]*\n"
        f"Example: *PAID 75000*"
    )
    send_buttons(phone, "Questions?", ["View Tenders", "My Status", "Help"])


def handle_paid_confirmation(phone: str, text: str):
    try:
        amount = int(text.lower().replace("paid", "").strip())
    except ValueError:
        send_text(phone, "Please specify the amount. Example: *PAID 75000*")
        return

    # Determine payment type, plan, and credits from amount
    PAYMENT_MAP = {
        75000:  ("subscription", "pro", 0),
        180000: ("subscription", "business", 5),
        15000:  ("credits", "", 1),
        40000:  ("credits", "", 3),
        120000: ("credits", "", 10),
    }

    pay_type, plan, credits_added = PAYMENT_MAP.get(amount, ("credits", "", 0))
    if amount not in PAYMENT_MAP:
        # Unknown amount — log as pending for admin review
        pay_type = "pending"
        plan = ""
        credits_added = 0

    payment_id = log_payment(phone, amount, pay_type=pay_type, plan=plan, credits_added=credits_added)

    type_desc = ""
    if pay_type == "subscription":
        type_desc = f"Plan: *{plan.title()}*"
    elif credits_added > 0:
        type_desc = f"Credits: *{credits_added}*"
    else:
        type_desc = "Pending admin review"

    send_text(
        phone,
        f"✅ *Payment of RWF {amount:,} noted!*\n\n"
        f"Payment ID: *{payment_id}*\n"
        f"{type_desc}\n\n"
        f"We'll verify and credit your account within 15 minutes.\n\n"
        f"Reply *CREDITS* to check your balance."
    )
    send_buttons(phone, "While you wait:", MAIN_BUTTONS)


# ── Admin commands ───────────────────────────────────────────────────────

def handle_admin(phone: str, text: str):
    """Handle admin commands: admin [secret] [command] [args]"""
    parts = text.split()
    if len(parts) < 3 or not ADMIN_SECRET:
        return

    secret = parts[1]
    if secret != ADMIN_SECRET:
        return  # Silently ignore wrong secret

    cmd = parts[2].lower()

    if cmd == "upgrade" and len(parts) >= 5:
        target = parts[3]
        plan = parts[4].lower()
        if plan in ("pro", "business"):
            credits_add = 5 if plan == "business" else 0
            update_subscriber(target, subscription_tier=plan, credits=credits_add)
            send_text(phone, f"✅ Upgraded {target} to *{plan}*" + (f" with {credits_add} credits" if credits_add else ""))
        else:
            send_text(phone, "Invalid plan. Use: pro or business")

    elif cmd == "credits" and len(parts) >= 5:
        target = parts[3]
        try:
            amount = int(parts[4])
            sub = get_subscriber(target)
            if sub:
                new_credits = (sub.get("credits") or 0) + amount
                update_subscriber(target, credits=new_credits)
                send_text(phone, f"✅ Added {amount} credits to {target}. New balance: {new_credits}")
            else:
                send_text(phone, f"Subscriber {target} not found.")
        except ValueError:
            send_text(phone, "Invalid amount.")

    elif cmd == "confirm" and len(parts) >= 4:
        payment_id = parts[3]
        if confirm_payment(payment_id):
            send_text(phone, f"✅ Payment {payment_id} confirmed and applied.")
        else:
            send_text(phone, f"Payment {payment_id} not found or already confirmed.")

    elif cmd == "stats":
        from database import get_active_subscribers, get_awards_count, get_conn
        subs = get_active_subscribers()
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM tenders")
        total_tenders = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM proposals")
        total_proposals = c.fetchone()[0]
        conn.close()
        send_text(
            phone,
            f"📊 *Admin Stats*\n\n"
            f"Subscribers: {len(subs)}\n"
            f"Tenders: {total_tenders}\n"
            f"Awards: {get_awards_count()}\n"
            f"Proposals generated: {total_proposals}"
        )


# ── Rate limiting ──────────────────────────────────────────────────────────

RATE_LIMIT_PER_HOUR = 30  # Max inbound messages per user per hour


def is_rate_limited(phone: str) -> bool:
    """Check if a user has exceeded the rate limit. Exempt users skip the check."""
    sub = get_subscriber(phone)
    if sub and sub.get("rate_limit_exempt"):
        return False
    count = get_interaction_count(phone, hours=1)
    return count >= RATE_LIMIT_PER_HOUR


# ── Resolve command name for logging ──────────────────────────────────────

def resolve_command(msg_type: str, content: str) -> str:
    """Map a message to a command name for logging."""
    if msg_type == "button_reply":
        return f"button:{content}"
    if msg_type == "list_reply":
        return f"sector_select:{content}"
    if msg_type == "document":
        return "document_upload"

    text = content.lower().strip()
    if text in ("help",): return "help"
    if text in ("status", "me", "profile", "my profile", "my status"): return "status"
    if text in ("sectors", "sector", "change sector", "change sectors"): return "sectors"
    if text in ("name", "change name", "update name", "company name"): return "name"
    if text in ("list", "tenders", "latest", "new", "today"): return "list"
    if text.startswith("search "): return "search"
    if text in ("stop", "unsubscribe", "quit", "cancel"): return "stop"
    if text in ("hi", "hello", "hey", "start", "join", "subscribe"): return "greeting"
    return "unknown"


# ── Main dispatcher ───────────────────────────────────────────────────────

def process_webhook_entry(entry: dict):
    """Process a single webhook entry. Called by the FastAPI route."""
    phone = parse_phone(entry)
    if not phone:
        return

    msg_type, content = parse_message(entry)
    if msg_type == "unknown":
        return

    # Log every inbound interaction
    command = resolve_command(msg_type, content)
    log_interaction(phone, "inbound", msg_type, content, command=command)

    # Rate limiting
    if is_rate_limited(phone):
        send_text(phone, "⚠️ You're sending messages too quickly. Please wait a few minutes before trying again.")
        log_interaction(phone, "outbound", "text", "rate_limited", command="rate_limit")
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
        # Distinguish tender selection (id starts with "tender:") from sector selection
        if content.startswith("tender:"):
            handle_tender_selection(phone, content, sub)
        else:
            sector = content if content in VALID_SECTORS else "all"
            label = SECTOR_LABELS.get(sector, "All Sectors")
            update_subscriber(phone, sectors=sector, onboarding_step="complete")
            send_text(phone, f"✅ Updated! You'll now receive alerts for *{label}*.")
            send_buttons(phone, "What's next?", AFTER_ACTION_BUTTONS)

    elif msg_type == "document":
        handle_incoming_document(phone, entry)

    elif msg_type == "text" and content:
        handle_text(phone, content, sub)
