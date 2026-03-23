"""
main.py — TenderAlert Pro unified entry point.

Usage:
  python main.py                  # run full pipeline (poll → enrich → send)
  python main.py --poll           # fetch & store tenders only
  python main.py --enrich         # run AI enrichment only
  python main.py --send           # send WhatsApp digests only
  python main.py --preview        # preview tenders + AI enrichment in console (no WhatsApp)
  python main.py --test-whatsapp  # send a test message to ADMIN_WHATSAPP_NUMBER
  python main.py --schedule       # start the daily scheduler (runs daily at 08:00 Kigali)
"""

import sys
import os

# Ensure backend directory is in path when run from project root
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, get_new_tenders, get_active_subscribers, add_subscriber
from poller import poll_and_store
from ai_enrichment import enrich_new_tenders, preview_enrichment
from whatsapp import send_text, send_tender_digest, check_sender_status
from config import ADMIN_WHATSAPP_NUMBER


def run_full_pipeline():
    """Poll → Enrich → Send. The complete daily job."""
    print("\n🚀 TenderAlert Pro — Full Pipeline")
    print("=" * 50)

    init_db()

    print("\n[1/3] Fetching tenders from RPPA Umucyo...")
    new_count = poll_and_store()
    print(f"      {new_count} tenders fetched/updated.\n")

    print("[2/3] Enriching with Claude AI...")
    enriched = enrich_new_tenders(limit=20)
    print(f"      {enriched} tenders enriched.\n")

    print("[3/3] Sending WhatsApp alerts...")
    all_new = get_new_tenders(since_hours=25)
    if not all_new:
        print("      No active tenders with future deadlines. Nothing to send.")
        return

    subscribers = get_active_subscribers()
    if not subscribers:
        print("      No active subscribers yet.")
        print(f"      Tip: run  python main.py --test-whatsapp  to add yourself.")
        return

    sent = 0
    for sub in subscribers:
        sectors = sub.get("sectors", "all")
        tenders_for_sub = (
            all_new
            if sectors == "all"
            else [t for t in all_new if sectors.lower() in (t.get("category") or "").lower()]
        )
        if not tenders_for_sub:
            continue
        if send_tender_digest(sub["phone"], tenders_for_sub):
            sent += 1

    print(f"      Alerts sent to {sent}/{len(subscribers)} subscriber(s).\n")
    print("✅ Pipeline complete.")


def run_poll():
    init_db()
    print("\n📡 Polling RPPA Umucyo for tenders...")
    count = poll_and_store()
    print(f"Done. {count} tenders fetched/updated.")


def run_enrich():
    init_db()
    print("\n🤖 Running Claude AI enrichment...")
    count = enrich_new_tenders(limit=20)
    print(f"Done. {count} tenders enriched.")


def run_send():
    init_db()
    print("\n📨 Sending WhatsApp digests...")
    all_new = get_new_tenders(since_hours=25)
    if not all_new:
        print("No active tenders with future deadlines found.")
        return

    subscribers = get_active_subscribers()
    if not subscribers:
        print("No active subscribers. Nothing to send.")
        return

    sent = 0
    for sub in subscribers:
        sectors = sub.get("sectors", "all")
        tenders_for_sub = (
            all_new
            if sectors == "all"
            else [t for t in all_new if sectors.lower() in (t.get("category") or "").lower()]
        )
        if not tenders_for_sub:
            continue
        if send_tender_digest(sub["phone"], tenders_for_sub):
            sent += 1

    print(f"Done. Alerts sent to {sent}/{len(subscribers)} subscriber(s).")


def run_test_whatsapp():
    """
    Run a full WhatsApp health check then send a test message.

    Uses the hello_world template (Meta's built-in test template) to confirm
    end-to-end delivery works. Template messages work for business-initiated
    conversations without requiring a 24h session window.
    """
    init_db()
    if not ADMIN_WHATSAPP_NUMBER:
        print("ERROR: ADMIN_WHATSAPP_NUMBER not set in .env")
        return

    # --- Step 1: Check sender phone number status ---
    print("\n[1/3] Checking sender phone number status...")
    status = check_sender_status()
    if "error" in status:
        print(f"  ERROR: {status['error']}")
        return

    sender_number = status.get("display_phone_number", "unknown")
    verified = status.get("code_verification_status", "UNKNOWN")
    account_mode = status.get("account_mode", "UNKNOWN")

    print(f"  Sender   : {sender_number} ({status.get('verified_name', '')})")
    print(f"  Verified : {verified}")
    print(f"  Mode     : {account_mode}")

    # --- Step 2: Confirm tenders are available ---
    print(f"\n[2/3] Checking tender data...")
    tenders = get_new_tenders(since_hours=9999)
    if not tenders:
        from poller import fetch_live_ocds
        tenders = fetch_live_ocds(page_size=3)
    tender_count = len(tenders) if tenders else 0
    print(f"  {tender_count} tender(s) available in DB.")

    # --- Step 3: Send hello_world first to confirm delivery works, then tender template ---
    from whatsapp import send_template, TENDER_ALERT_TEMPLATE
    print(f"\n[3/3] Sending 'hello_world' template to +{ADMIN_WHATSAPP_NUMBER}...")
    print(f"  (Using hello_world to confirm delivery — works without custom template)")
    success = send_template(ADMIN_WHATSAPP_NUMBER, "hello_world")

    if success:
        print(f"\n  hello_world delivered — WhatsApp connection is working!")
        print()
        if TENDER_ALERT_TEMPLATE != "hello_world":
            print(f"  To send the real tender_daily_alert template with buttons:")
            print(f"  1. Get your WABA ID from Meta console (WhatsApp → API Setup)")
            print(f"  2. Run: python setup_template.py --waba-id <YOUR_WABA_ID>")
            print(f"  3. Once approved, run: python -X utf8 main.py --test-whatsapp")
        print()
        print(f"  Tender count ready to send: {tender_count}")
    else:
        print("\n  Send failed — see error above.")
        print(f"  Make sure +{ADMIN_WHATSAPP_NUMBER} is added as an approved recipient in the Meta console.")


def run_schedule():
    """Start the blocking daily scheduler."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from scheduler import run_daily_job, DAILY_HOUR_UTC, DAILY_MINUTE_UTC

    print(f"\n⏰ Starting TenderAlert Pro scheduler...")
    print(f"   Daily job runs at {DAILY_HOUR_UTC:02d}:{DAILY_MINUTE_UTC:02d} UTC (08:00 Kigali)")
    print(f"   Running first job now...\n")

    run_daily_job()

    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(run_daily_job, "cron", hour=DAILY_HOUR_UTC, minute=DAILY_MINUTE_UTC)
    print("\n✅ Scheduler running. Press Ctrl+C to stop.")
    try:
        sched.start()
    except KeyboardInterrupt:
        print("\n[scheduler] Stopped.")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or "--pipeline" in args:
        run_full_pipeline()
    elif "--poll" in args:
        run_poll()
    elif "--enrich" in args:
        run_enrich()
    elif "--send" in args:
        run_send()
    elif "--preview" in args:
        n = int(args[args.index("--preview") + 1]) if len(args) > 1 else 3
        preview_enrichment(n=n)
    elif "--test-whatsapp" in args:
        run_test_whatsapp()
    elif "--schedule" in args:
        run_schedule()
    else:
        print(__doc__)
