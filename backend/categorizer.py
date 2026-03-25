"""
categorizer.py — AI-powered fine-grained tender categorization.

Uses Claude Haiku to classify tenders into specific sub-categories
beyond the 3 broad OCDS categories (goods/services/works).

Batch-processes up to 20 tenders per API call to minimize cost.
"""

import json
import anthropic
from config import ANTHROPIC_API_KEY
from database import get_conn

MODEL = "claude-haiku-4-5-20251001"

# ── Defined sub-categories ──────────────────────────────────────────────

SUB_CATEGORIES = [
    "ICT & Technology",
    "Construction & Infrastructure",
    "Health & Medical",
    "Education & Training",
    "Agriculture & Livestock",
    "Consulting & Advisory",
    "Supply & Equipment",
    "Transport & Logistics",
    "Energy & Utilities",
    "Water & Sanitation",
    "Security & Defense",
    "Finance & Insurance",
    "Environment & Conservation",
    "Hospitality & Events",
    "Legal & Compliance",
    "Media & Communications",
    "Mining & Extractives",
    "Other",
]

CATEGORIES_LIST = "\n".join(f"- {c}" for c in SUB_CATEGORIES)


def build_batch_prompt(tenders: list[dict]) -> str:
    """Build a prompt to classify multiple tenders at once."""
    tender_lines = []
    for i, t in enumerate(tenders):
        items = t.get("items_description", "")
        items_str = f" | Items: {items}" if items else ""
        tender_lines.append(
            f'{i}: "{t["title"]}" | Buyer: {t["buyer_name"]} | '
            f'OCDS category: {t["category"]}{items_str}'
        )

    tenders_block = "\n".join(tender_lines)

    return f"""Classify each tender into exactly ONE sub-category from this list:

{CATEGORIES_LIST}

Tenders to classify:
{tenders_block}

Respond with ONLY a JSON object mapping the index number to the sub-category.
Example: {{"0": "ICT & Technology", "1": "Health & Medical", "2": "Other"}}

Rules:
- Use the title, buyer name, and OCDS category to determine the best fit
- If a tender clearly fits a category, assign it
- If unclear or doesn't fit any specific category, use "Other"
- Be specific: "Supply & Equipment" is for generic supplies, not for health supplies (use "Health & Medical") or IT equipment (use "ICT & Technology")
- Respond with ONLY the JSON, no explanation"""


def classify_batch(tenders: list[dict]) -> dict[int, str]:
    """
    Classify a batch of tenders using Claude Haiku.
    Returns a dict mapping tender index to sub-category.
    """
    if not ANTHROPIC_API_KEY:
        print("[categorizer] No Anthropic API key — skipping classification")
        return {}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": build_batch_prompt(tenders)}],
        )
        text = msg.content[0].text.strip()

        # Parse JSON response — handle markdown code blocks
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        result = json.loads(text)
        return {int(k): v for k, v in result.items()}

    except (json.JSONDecodeError, Exception) as e:
        print(f"[categorizer] Error classifying batch: {e}")
        return {}


def categorize_tender(tender: dict) -> str:
    """Classify a single tender. Returns the sub-category string."""
    result = classify_batch([tender])
    return result.get(0, "Other")


def categorize_new_tenders(batch_size: int = 20) -> int:
    """
    Find tenders without a sub_category and classify them in batches.
    Returns count of tenders categorized.
    """
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        SELECT ocid, title, buyer_name, category, description
        FROM tenders
        WHERE sub_category IS NULL OR sub_category = ''
        ORDER BY fetched_at DESC
        LIMIT 200
    """)
    uncategorized = [dict(r) for r in c.fetchall()]
    conn.close()

    if not uncategorized:
        print("[categorizer] No uncategorized tenders found.")
        return 0

    print(f"[categorizer] Found {len(uncategorized)} uncategorized tenders. Processing in batches of {batch_size}...")

    total = 0
    for i in range(0, len(uncategorized), batch_size):
        batch = uncategorized[i:i + batch_size]
        print(f"[categorizer] Batch {i // batch_size + 1}: classifying {len(batch)} tenders...")

        results = classify_batch(batch)

        conn = get_conn()
        c = conn.cursor()
        for idx, sub_cat in results.items():
            if sub_cat in SUB_CATEGORIES:
                tender = batch[idx]
                c.execute(
                    "UPDATE tenders SET sub_category = ? WHERE ocid = ?",
                    (sub_cat, tender["ocid"]),
                )
                total += 1
        conn.commit()
        conn.close()

        print(f"[categorizer] Batch done. {len(results)} classified.")

    print(f"[categorizer] Total categorized: {total}/{len(uncategorized)}")
    return total


def get_available_categories() -> list[str]:
    """Return list of sub-categories that have at least one tender."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT DISTINCT sub_category FROM tenders
        WHERE sub_category IS NOT NULL AND sub_category != ''
        ORDER BY sub_category
    """)
    cats = [r[0] for r in c.fetchall()]
    conn.close()
    return cats


if __name__ == "__main__":
    from database import init_db
    init_db()

    import sys
    if "--count" in sys.argv:
        cats = get_available_categories()
        print(f"Categories with tenders: {cats}")
    else:
        count = categorize_new_tenders()
        print(f"Done. {count} tenders categorized.")
