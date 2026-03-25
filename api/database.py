"""
database.py — Dashboard-specific database queries.
Reuses the connection factory from backend/database.py.
Adds pagination, aggregates, and export functions needed by the admin API.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_conn, init_db  # noqa: E402


def mask_phone(phone: str) -> str:
    """Mask a phone number for privacy: 250791637302 → 250791***302"""
    if len(phone) <= 6:
        return phone
    return phone[:6] + "***" + phone[-3:]


# ── Stats / Aggregates ────────────────────────────────────────────────────

def count_subscribers() -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM subscribers")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM subscribers WHERE active = 1")
    active = c.fetchone()[0]
    conn.close()
    return {"total": total, "active": active, "inactive": total - active}


def count_tenders() -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tenders")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM tenders WHERE status = 'active' AND deadline > datetime('now')")
    active = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM tenders WHERE ai_summary IS NOT NULL AND ai_summary != ''")
    enriched = c.fetchone()[0]
    conn.close()
    return {"total": total, "active": active, "enriched": enriched}


def get_onboarding_funnel() -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT onboarding_step, COUNT(*) as cnt
        FROM subscribers WHERE active = 1
        GROUP BY onboarding_step
    """)
    result = {"awaiting_name": 0, "awaiting_sector": 0, "complete": 0}
    for row in c.fetchall():
        step = row["onboarding_step"] or "awaiting_name"
        if step in result:
            result[step] = row["cnt"]
    conn.close()
    return result


def get_last_poll_time() -> str | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT MAX(fetched_at) FROM tenders")
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


# ── Subscribers ───────────────────────────────────────────────────────────

def get_subscribers_paginated(
    page: int = 1,
    per_page: int = 20,
    sector: str | None = None,
    status: str | None = None,  # "active", "inactive", "onboarding"
    search: str | None = None,
) -> tuple[list[dict], int]:
    """Returns (rows, total_count) with pagination and filtering."""
    conn = get_conn()
    c = conn.cursor()

    where_clauses = []
    params = []

    if sector and sector != "all":
        where_clauses.append("sectors = ?")
        params.append(sector)

    if status == "active":
        where_clauses.append("active = 1 AND onboarding_step = 'complete'")
    elif status == "inactive":
        where_clauses.append("active = 0")
    elif status == "onboarding":
        where_clauses.append("active = 1 AND onboarding_step != 'complete'")

    if search:
        where_clauses.append("(company_name LIKE ? OR phone LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Count
    c.execute(f"SELECT COUNT(*) FROM subscribers WHERE {where_sql}", params)
    total = c.fetchone()[0]

    # Paginated rows
    offset = (page - 1) * per_page
    c.execute(
        f"SELECT * FROM subscribers WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    # Mask phone numbers for list view
    for row in rows:
        row["phone_masked"] = mask_phone(row.get("phone", ""))

    return rows, total


def export_subscribers() -> list[dict]:
    """Return all active subscribers for CSV export."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT phone, company_name, sectors, onboarding_step, created_at
        FROM subscribers WHERE active = 1
        ORDER BY created_at DESC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ── Tenders ───────────────────────────────────────────────────────────────

def get_tenders_paginated(
    page: int = 1,
    per_page: int = 20,
    sector: str | None = None,
    enrichment: str | None = None,  # "enriched", "pending", None
    deadline_from: str | None = None,
    deadline_to: str | None = None,
    search: str | None = None,
    value_min: float | None = None,
    value_max: float | None = None,
) -> tuple[list[dict], int]:
    """Returns (rows, total_count) with pagination and filtering."""
    conn = get_conn()
    c = conn.cursor()

    where_clauses = []
    params = []

    if sector and sector != "all":
        where_clauses.append("LOWER(category) LIKE ?")
        params.append(f"%{sector.lower()}%")

    if enrichment == "enriched":
        where_clauses.append("ai_summary IS NOT NULL AND ai_summary != ''")
    elif enrichment == "pending":
        where_clauses.append("(ai_summary IS NULL OR ai_summary = '')")

    if deadline_from:
        where_clauses.append("deadline >= ?")
        params.append(deadline_from)
    if deadline_to:
        where_clauses.append("deadline <= ?")
        params.append(deadline_to)

    if search:
        where_clauses.append("(LOWER(title) LIKE ? OR LOWER(buyer_name) LIKE ? OR LOWER(ocid) LIKE ?)")
        term = f"%{search.lower()}%"
        params.extend([term, term, term])

    if value_min is not None:
        where_clauses.append("value_amount >= ?")
        params.append(value_min)
    if value_max is not None:
        where_clauses.append("value_amount <= ?")
        params.append(value_max)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    c.execute(f"SELECT COUNT(*) FROM tenders WHERE {where_sql}", params)
    total = c.fetchone()[0]

    offset = (page - 1) * per_page
    c.execute(
        f"""SELECT ocid, title, buyer_name, category, value_amount, value_currency,
                   deadline, status, ai_summary, fetched_at
            FROM tenders WHERE {where_sql}
            ORDER BY
                CASE WHEN status = 'active' AND deadline > datetime('now') THEN 0 ELSE 1 END,
                deadline ASC
            LIMIT ? OFFSET ?""",
        params + [per_page, offset],
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    # Add has_ai_summary flag
    for row in rows:
        row["has_ai_summary"] = bool(row.get("ai_summary"))
        row.pop("ai_summary", None)  # Don't send full summary in list view

    return rows, total


def get_tender_by_ocid(ocid: str) -> dict | None:
    """Full tender detail including AI summary."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM tenders WHERE ocid = ?", (ocid,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None
