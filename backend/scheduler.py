"""
scheduler.py — Runs the daily tender poll + WhatsApp alert job.

Can be run two ways:
  1. Standalone: python scheduler.py          (runs the job now + schedules daily repeat)
  2. One-shot:   python scheduler.py --once   (runs job once and exits — good for cron/Railway)
"""

import sys
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

from database import get_active_subscribers, get_new_tenders, init_db
from poller import poll_and_store
from ai_enrichment import enrich_new_tenders
from whatsapp import send_tender_digest

# Run daily at 08:00 Kigali time (UTC+2 = 06:00 UTC)
DAILY_HOUR_UTC = 6
DAILY_MINUTE_UTC = 0


def run_daily_job():
    print(f"\n[scheduler] Job started at {datetime.utcnow().isoformat()}Z")
    init_db()

    # 1. Fetch fresh tenders from RPPA
    new_count = poll_and_store()
    print(f"[scheduler] {new_count} tenders fetched/updated.")

    if new_count == 0:
        print("[scheduler] No new tenders — skipping alerts.")
        return

    # 2. Enrich new tenders with Claude AI summaries
    enriched = enrich_new_tenders(limit=20)
    print(f"[scheduler] {enriched} tenders enriched with AI summaries.")

    # 3. Get all active tenders with future deadlines (includes ai_summary)
    all_new = get_new_tenders(since_hours=25)
    if not all_new:
        print("[scheduler] No active tenders with future deadlines — skipping alerts.")
        return

    # 4. Get subscribers and send each their filtered digest
    subscribers = get_active_subscribers()
    print(f"[scheduler] Sending alerts to {len(subscribers)} subscriber(s)...")

    sent = 0
    for sub in subscribers:
        sectors = sub.get("sectors", "all")
        tenders_for_sub = (
            all_new
            if sectors == "all"
            else [
                t for t in all_new
                if sectors.lower() in (t.get("category") or "").lower()
                or sectors.lower() in (t.get("tags") or "").lower()
            ]
        )

        if not tenders_for_sub:
            continue

        success = send_tender_digest(sub["phone"], tenders_for_sub)
        if success:
            sent += 1

    print(f"[scheduler] Alerts sent to {sent}/{len(subscribers)} subscribers.")
    print(f"[scheduler] Job finished at {datetime.utcnow().isoformat()}Z\n")


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_daily_job()
    else:
        print(f"[scheduler] Running job now, then scheduling daily at {DAILY_HOUR_UTC:02d}:{DAILY_MINUTE_UTC:02d} UTC (08:00 Kigali)...")
        run_daily_job()

        scheduler = BlockingScheduler(timezone="UTC")
        scheduler.add_job(run_daily_job, "cron", hour=DAILY_HOUR_UTC, minute=DAILY_MINUTE_UTC)
        print(f"[scheduler] Scheduler running. Press Ctrl+C to stop.")
        try:
            scheduler.start()
        except KeyboardInterrupt:
            print("[scheduler] Stopped.")
