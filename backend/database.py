import sqlite3
from datetime import datetime
from config import DATABASE_PATH


def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Allow concurrent reads during writes
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS tenders (
            ocid TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            buyer_name TEXT,
            category TEXT,
            status TEXT,
            value_amount REAL,
            value_currency TEXT,
            deadline TEXT,
            source_url TEXT,
            raw_json TEXT,
            ai_summary TEXT,
            fetched_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            sectors TEXT DEFAULT 'all',
            active INTEGER DEFAULT 1,
            company_name TEXT DEFAULT '',
            onboarding_step TEXT DEFAULT 'awaiting_name',
            created_at TEXT
        )
    """)

    # Migrate existing DBs that predate these two columns
    for col, definition in [
        ("company_name",    "TEXT DEFAULT ''"),
        ("onboarding_step", "TEXT DEFAULT 'awaiting_name'"),
    ]:
        try:
            c.execute(f"ALTER TABLE subscribers ADD COLUMN {col} {definition}")
        except Exception:
            pass  # Column already exists — safe to ignore

    conn.commit()
    conn.close()


def upsert_tender(tender: dict):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO tenders (ocid, title, description, buyer_name, category, status,
                             value_amount, value_currency, deadline, source_url, raw_json, fetched_at)
        VALUES (:ocid, :title, :description, :buyer_name, :category, :status,
                :value_amount, :value_currency, :deadline, :source_url, :raw_json, :fetched_at)
        ON CONFLICT(ocid) DO UPDATE SET
            status = excluded.status,
            deadline = excluded.deadline,
            fetched_at = excluded.fetched_at
    """, tender)
    inserted = c.rowcount
    conn.commit()
    conn.close()
    return inserted


def get_new_tenders(since_hours: int = 25) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM tenders
        WHERE status = 'active'
          AND deadline > datetime('now')
          AND fetched_at > datetime('now', ? || ' hours')
        ORDER BY deadline ASC
    """, (f"-{since_hours}",))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_subscriber(phone: str) -> dict | None:
    """Return a single subscriber row as a dict, or None if not found."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM subscribers WHERE phone = ?", (phone,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def update_subscriber(phone: str, **kwargs):
    """
    Update arbitrary fields on a subscriber row.
    Usage: update_subscriber("250788...", onboarding_step="complete", sectors="ict")
    """
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [phone]
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"UPDATE subscribers SET {fields} WHERE phone = ?", values)
    conn.commit()
    conn.close()


def add_subscriber(phone: str, sectors: str = "all", onboarding_step: str = "awaiting_name"):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO subscribers (phone, sectors, active, onboarding_step, created_at)
        VALUES (?, ?, 1, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET active = 1, sectors = excluded.sectors
    """, (phone, sectors, onboarding_step, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def remove_subscriber(phone: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE subscribers SET active = 0 WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


def get_active_subscribers() -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM subscribers WHERE active = 1")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def search_tenders(keyword: str, limit: int = 3) -> list:
    """Search active tenders by keyword in title or buyer name."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM tenders
        WHERE (title LIKE ? OR buyer_name LIKE ? OR description LIKE ?)
          AND status = 'active'
          AND deadline > datetime('now')
        ORDER BY deadline ASC
        LIMIT ?
    """, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_tenders_for_subscriber(phone: str, since_hours: int = 48) -> list:
    """Get recent tenders filtered by the subscriber's sector preference."""
    sub = get_subscriber(phone)
    if not sub:
        return []

    tenders = get_new_tenders(since_hours=since_hours)
    sectors = sub.get("sectors", "all")

    if sectors == "all":
        return tenders

    return [t for t in tenders if sectors.lower() in (t.get("category") or "").lower()]


def save_ai_summary(ocid: str, summary: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE tenders SET ai_summary = ? WHERE ocid = ?", (summary, ocid))
    conn.commit()
    conn.close()
