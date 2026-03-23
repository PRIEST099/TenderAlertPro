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

SECTORS: [comma-separated list from ONLY these options: ict, construction, health, education, agriculture, consulting, supply]
Assign 1-3 sectors that best match this tender. Examples:
- Software development → ict
- Road construction → construction
- Hospital equipment → health, supply
- School renovation → education, construction
- Farm inputs → agriculture, supply
- Audit services → consulting

---
Tender Title: {tender['title']}
Buyer: {tender['buyer_name']}
Category: {tender['category']}
Value: {value_str}
Deadline: {deadline}
Description: {description or 'No description provided.'}"""


VALID_SECTORS = {"ict", "construction", "health", "education", "agriculture", "consulting", "supply"}


def parse_sectors_from_response(text: str) -> str:
    """Extract SECTORS: line from Claude's response and return cleaned comma-separated tags."""
    for line in text.splitlines():
        if line.strip().upper().startswith("SECTORS:"):
            raw = line.split(":", 1)[1].strip()
            # Parse comma-separated, validate each against known sectors
            tags = [s.strip().lower() for s in raw.split(",")]
            valid = [t for t in tags if t in VALID_SECTORS]
            return ",".join(valid) if valid else ""
    return ""


def strip_sectors_line(text: str) -> str:
    """Remove the SECTORS: line from the response (don't show it to users)."""
    lines = []
    for line in text.splitlines():
        if not line.strip().upper().startswith("SECTORS:"):
            lines.append(line)
    # Clean trailing whitespace
    return "\n".join(lines).strip()


def enrich_tender(tender: dict) -> tuple[str | None, str]:
    """
    Call Claude to generate an AI summary + sector tags for a single tender.
    Returns (summary_text, tags_csv) on success, (None, "") on failure.
    """
    if not ANTHROPIC_API_KEY:
        print("[ai] ANTHROPIC_API_KEY not set — skipping enrichment.")
        return None, ""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": build_prompt(tender)}],
        )
        full_response = message.content[0].text.strip()
        tags = parse_sectors_from_response(full_response)
        summary = strip_sectors_line(full_response)
        return summary, tags
    except anthropic.APIError as e:
        print(f"[ai] API error for {tender.get('ocid')}: {e}")
        return None, ""
    except Exception as e:
        print(f"[ai] Unexpected error for {tender.get('ocid')}: {e}")
        return None, ""


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
        summary, tags = enrich_tender(t)
        if summary:
            save_ai_summary(t["ocid"], summary, tags=tags)
            enriched += 1
            tag_info = f" [tags: {tags}]" if tags else ""
            print(f"[ai]   ✓ Enriched ({enriched}/{len(tenders)}){tag_info}")
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

        summary, tags = enrich_tender(t)
        if summary:
            print(f"\n  📋 AI Analysis:\n")
            for line in summary.splitlines():
                print(f"     {line}")
            if tags:
                print(f"\n  🏷️  Sectors: {tags}")
        else:
            print("  ✗ Enrichment failed.")
        print()


if __name__ == "__main__":
    init_db()
    preview_enrichment(n=3)
