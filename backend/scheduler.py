"""
scheduler.py — Runs the daily tender poll + WhatsApp alert job.

Can be run two ways:
  1. Standalone: python scheduler.py          (runs the job now + schedules daily repeat)
  2. One-shot:   python scheduler.py --once   (runs job once and exits — good for cron/Railway)
"""

import sys
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

from database import get_active_subscribers, get_new_tenders, init_db, get_conn
from poller import poll_and_store
from ai_enrichment import enrich_new_tenders
from whatsapp import send_tender_digest

# Run daily at 08:00 Kigali time (UTC+2 = 06:00 UTC)
DAILY_HOUR_UTC = 6
DAILY_MINUTE_UTC = 0


def get_last_poll_timestamp() -> str | None:
    """Get the timestamp of the most recent poll before this one."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT MAX(fetched_at) FROM tenders
    """)
    result = c.fetchone()[0]
    conn.close()
    return result


def get_tenders_from_last_poll() -> list[dict]:
    """Get tenders that were fetched/updated in the most recent poll run."""
    conn = get_conn()
    c = conn.cursor()
    # Get tenders fetched in the last 2 hours (covers any poll run)
    c.execute("""
        SELECT * FROM tenders
        WHERE status = 'active'
          AND deadline > datetime('now')
          AND fetched_at > datetime('now', '-2 hours')
        ORDER BY deadline ASC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def match_tender_to_subscriber(tender: dict, sub_sectors: str) -> bool:
    """Check if a tender matches a subscriber's sector preferences."""
    if sub_sectors == "all":
        return True

    # Check against both broad category and sub_category
    category = (tender.get("category") or "").lower()
    sub_category = (tender.get("sub_category") or "").lower()
    tags = (tender.get("tags") or "").lower()

    # Subscriber may have multiple sectors comma-separated
    for sector in sub_sectors.lower().split(","):
        sector = sector.strip()
        if not sector:
            continue
        if sector in category or sector in sub_category or sector in tags:
            return True
        # Handle common aliases
        if sector == "ict" and ("technology" in sub_category or "ict" in sub_category):
            return True
        if sector == "construction" and ("infrastructure" in sub_category or "construction" in sub_category):
            return True
        if sector == "health" and ("medical" in sub_category or "health" in sub_category):
            return True

    return False


def run_daily_job():
    print(f"\n[scheduler] Job started at {datetime.utcnow().isoformat()}Z")
    init_db()

    # 1. Fetch fresh tenders from RPPA (also categorizes new ones)
    new_count = poll_and_store()
    print(f"[scheduler] {new_count} tenders fetched/updated.")

    if new_count == 0:
        print("[scheduler] No new tenders — skipping alerts.")
        return

    # 2. Enrich new tenders with Claude AI summaries
    enriched = enrich_new_tenders(limit=20)
    print(f"[scheduler] {enriched} tenders enriched with AI summaries.")

    # 3. Get only tenders from this poll run (not all active tenders)
    fresh_tenders = get_tenders_from_last_poll()
    if not fresh_tenders:
        print("[scheduler] No active tenders with future deadlines from this poll — skipping alerts.")
        return

    print(f"[scheduler] {len(fresh_tenders)} fresh active tenders to send.")

    # 4. Get subscribers and send each their filtered digest
    subscribers = get_active_subscribers()
    print(f"[scheduler] Sending alerts to {len(subscribers)} subscriber(s)...")

    sent = 0
    for sub in subscribers:
        # Only complete onboarding subscribers
        if sub.get("onboarding_step") != "complete":
            continue

        sectors = sub.get("sectors", "all")
        tenders_for_sub = [
            t for t in fresh_tenders
            if match_tender_to_subscriber(t, sectors)
        ]

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
