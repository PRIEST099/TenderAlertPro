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
from whatsapp import send_tender_digest, send_text, send_buttons

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
          AND deadline >= date('now')
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

    # Monthly resets (runs only on the 1st)
    run_monthly_resets()

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


def get_pipeline_deadlines_due(days_ahead: int) -> list:
    """Get pipeline items with deadlines X days from now that haven't been reminded."""
    conn = get_conn()
    c = conn.cursor()
    reminder_col = f"reminder_{days_ahead}d" if days_ahead in (1, 3, 7) else "reminder_7d"
    c.execute(f"""
        SELECT bp.phone, bp.ocid, bp.status, bp.{reminder_col},
               t.title, t.deadline, t.buyer_name,
               s.subscription_tier, s.company_name
        FROM bid_pipeline bp
        JOIN tenders t ON bp.ocid = t.ocid
        JOIN subscribers s ON bp.phone = s.phone
        WHERE date(t.deadline) = date('now', '+{days_ahead} days')
          AND bp.{reminder_col} = 0
          AND s.active = 1
          AND s.subscription_tier IN ('pro', 'business')
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def mark_reminder_sent(phone: str, ocid: str, days: int):
    """Mark a pipeline reminder as sent."""
    conn = get_conn()
    c = conn.cursor()
    col = f"reminder_{days}d" if days in (1, 3, 7) else "reminder_7d"
    c.execute(f"UPDATE bid_pipeline SET {col} = 1 WHERE phone = ? AND ocid = ?", (phone, ocid))
    conn.commit()
    conn.close()


def run_deadline_reminders():
    """Send deadline reminders for pipeline items due in 7, 3, or 1 day(s)."""
    print(f"[scheduler] Checking pipeline deadline reminders...")
    total_sent = 0

    for days in [7, 3, 1]:
        items = get_pipeline_deadlines_due(days)
        if not items:
            continue

        urgency = {7: "📅", 3: "⚠️", 1: "🔴"}[days]
        label = {7: "7 days", 3: "3 days", 1: "TOMORROW"}[days]

        for item in items:
            msg = (
                f"{urgency} *Deadline Alert — {label}*\n\n"
                f"*{item['title'][:60]}*\n"
                f"🏢 {item.get('buyer_name', 'Unknown')}\n"
                f"⏰ Deadline: {(item.get('deadline') or '')[:10]}\n"
                f"📂 Pipeline status: _{item.get('status', 'watching')}_\n\n"
                f"Don't miss this! Review your bid preparation."
            )
            success = send_text(item["phone"], msg)
            if success:
                send_buttons(item["phone"], "Quick actions:", ["View Pipeline", "Deep Analyze", "Help"])
                mark_reminder_sent(item["phone"], item["ocid"], days)
                total_sent += 1

    print(f"[scheduler] Sent {total_sent} deadline reminders.")


def run_monthly_resets():
    """Reset monthly analysis counts + add Business tier credits on 1st of month."""
    today = datetime.utcnow()
    if today.day != 1:
        return

    first_of_month = today.strftime("%Y-%m-01")
    conn = get_conn()
    c = conn.cursor()

    # Reset analysis counts for all subscribers
    c.execute("""
        UPDATE subscribers
        SET deep_analyses_used = 0, analysis_reset_date = ?
        WHERE analysis_reset_date < ? OR analysis_reset_date IS NULL OR analysis_reset_date = ''
    """, (first_of_month, first_of_month))
    reset_count = c.rowcount

    # Add 5 proposal credits to Business tier subscribers
    c.execute("""
        UPDATE subscribers
        SET credits = COALESCE(credits, 0) + 5
        WHERE subscription_tier = 'business' AND active = 1
    """)
    credits_added = c.rowcount

    conn.commit()
    conn.close()
    print(f"[scheduler] Monthly reset: {reset_count} analysis counts reset, {credits_added} Business accounts got +5 credits.")


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_daily_job()
    else:
        print(f"[scheduler] Running job now, then scheduling daily at {DAILY_HOUR_UTC:02d}:{DAILY_MINUTE_UTC:02d} UTC (08:00 Kigali)...")
        run_daily_job()

        scheduler = BlockingScheduler(timezone="UTC")
        scheduler.add_job(run_daily_job, "cron", hour=DAILY_HOUR_UTC, minute=DAILY_MINUTE_UTC)
        # Deadline reminders at 09:00 Kigali (07:00 UTC) — 1 hour after tender poll
        scheduler.add_job(run_deadline_reminders, "cron", hour=7, minute=0)
        print(f"[scheduler] Scheduler running. Press Ctrl+C to stop.")
        try:
            scheduler.start()
        except KeyboardInterrupt:
            print("[scheduler] Stopped.")
