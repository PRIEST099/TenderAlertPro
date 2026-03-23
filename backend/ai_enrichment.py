"""
ai_enrichment.py — Uses Claude API to enrich raw tenders with AI summaries
and eligibility checklists.

This is the core value-add of TenderAlert Pro over a raw data feed.
For each tender, Claude produces:
  - A plain-English summary (what the buyer actually wants)
  - An eligibility checklist (documents, certs, experience required)
  - A difficulty rating (Easy / Medium / Hard)

Run directly to test: python ai_enrichment.py
"""

import anthropic
from config import ANTHROPIC_API_KEY
from database import get_conn, save_ai_summary, init_db

MODEL = "claude-haiku-4-5-20251001"  # Fast + cost-efficient for structured extraction
MAX_DESCRIPTION_CHARS = 1500        # Truncate long descriptions to control token spend
ENRICH_BATCH_SIZE = 20              # Max tenders enriched per scheduler run


def build_prompt(tender: dict) -> str:
    """Build the Claude prompt for a single tender."""
    value_str = (
        f"RWF {tender['value_amount']:,.0f}"
        if tender.get("value_amount")
        else "Not disclosed"
    )
    deadline = (tender.get("deadline") or "")[:10] or "Not specified"
    description = (tender.get("description") or "")[:MAX_DESCRIPTION_CHARS]

    return f"""You are a procurement analyst helping Rwandan businesses find tender opportunities.

Analyze this government tender and respond in EXACTLY this format (no extra text):

SUMMARY:
[2 plain-English sentences explaining what the buyer wants and what the winning bidder will do]

CHECKLIST:
• [requirement 1 — document, certification, or qualification needed]
• [requirement 2]
• [requirement 3]
• [requirement 4 if applicable]
• [requirement 5 if applicable]

DIFFICULTY: [Easy / Medium / Hard]
Easy = any registered SME can apply | Medium = need proven experience + specific docs | Hard = large firm + specialized certifications required

---
Tender Title: {tender['title']}
Buyer: {tender['buyer_name']}
Category: {tender['category']}
Value: {value_str}
Deadline: {deadline}
Description: {description or 'No description provided.'}"""


def enrich_tender(tender: dict) -> str | None:
    """
    Call Claude to generate an AI summary for a single tender.
    Returns the formatted string on success, None on failure.
    """
    if not ANTHROPIC_API_KEY:
        print("[ai] ANTHROPIC_API_KEY not set — skipping enrichment.")
        return None

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": build_prompt(tender)}],
        )
        return message.content[0].text.strip()
    except anthropic.APIError as e:
        print(f"[ai] API error for {tender.get('ocid')}: {e}")
        return None
    except Exception as e:
        print(f"[ai] Unexpected error for {tender.get('ocid')}: {e}")
        return None


def get_unenriched_tenders(limit: int = ENRICH_BATCH_SIZE) -> list[dict]:
    """
    Fetch active tenders with a future deadline that don't have an AI summary yet.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        SELECT * FROM tenders
        WHERE (ai_summary IS NULL OR ai_summary = '')
          AND status = 'active'
          AND deadline > datetime('now')
        ORDER BY deadline ASC
        LIMIT ?
        """,
        (limit,),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def enrich_new_tenders(limit: int = ENRICH_BATCH_SIZE) -> int:
    """
    Enrich up to `limit` unenriched active tenders with Claude summaries.
    Returns the count of successfully enriched tenders.
    """
    tenders = get_unenriched_tenders(limit)

    if not tenders:
        print("[ai] No unenriched tenders to process.")
        return 0

    print(f"[ai] Enriching {len(tenders)} tender(s) with Claude...")
    enriched = 0

    for t in tenders:
        short_title = t["title"][:60] + ("..." if len(t["title"]) > 60 else "")
        print(f"[ai] → {short_title}")
        summary = enrich_tender(t)
        if summary:
            save_ai_summary(t["ocid"], summary)
            enriched += 1
            print(f"[ai]   ✓ Enriched ({enriched}/{len(tenders)})")
        else:
            print(f"[ai]   ✗ Failed — skipping")

    print(f"[ai] Done. {enriched}/{len(tenders)} tenders enriched.")
    return enriched


def preview_enrichment(n: int = 3):
    """
    Fetch N real tenders, enrich them with Claude, and print to console.
    Used for testing without sending WhatsApp messages.
    """
    from poller import fetch_live_ocds, fetch_bulk_ocds

    print("[ai] Fetching tenders for preview enrichment...")
    tenders = fetch_live_ocds(page_size=n)
    if not tenders:
        tenders = fetch_bulk_ocds()[:n]

    if not tenders:
        print("[ai] No tenders fetched — check your network or RPPA API.")
        return

    print("\n" + "=" * 65)
    print(f"  TenderAlert Pro - AI Enrichment Preview ({len(tenders)} tenders)")
    print("=" * 65 + "\n")

    for i, t in enumerate(tenders, 1):
        value_str = f"RWF {t['value_amount']:,.0f}" if t.get("value_amount") else "Value TBD"
        deadline = (t.get("deadline") or "")[:10] or "No deadline"

        print("-" * 65)
        print(f"[{i}] {t['title']}")
        print(f"     Buyer    : {t['buyer_name']}")
        print(f"     Category : {t['category']}")
        print(f"     Value    : {value_str}")
        print(f"     Deadline : {deadline}")
        print(f"\n  ⏳ Calling Claude...")

        summary = enrich_tender(t)
        if summary:
            print(f"\n  📋 AI Analysis:\n")
            for line in summary.splitlines():
                print(f"     {line}")
        else:
            print("  ✗ Enrichment failed.")
        print()


if __name__ == "__main__":
    init_db()
    preview_enrichment(n=3)
