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

    c.execute("""
        CREATE TABLE IF NOT EXISTS interaction_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'inbound',
            msg_type TEXT NOT NULL DEFAULT 'text',
            content TEXT DEFAULT '',
            command TEXT DEFAULT '',
            timestamp TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_logs_phone ON interaction_logs(phone)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON interaction_logs(timestamp)
    """)

    # Migrate existing DBs that predate these columns
    for col, definition in [
        ("company_name",    "TEXT DEFAULT ''"),
        ("onboarding_step", "TEXT DEFAULT 'awaiting_name'"),
        ("tags",            "TEXT DEFAULT ''"),
    ]:
        try:
            c.execute(f"ALTER TABLE subscribers ADD COLUMN {col} {definition}")
        except Exception:
            pass
    try:
        c.execute("ALTER TABLE tenders ADD COLUMN tags TEXT DEFAULT ''")
    except Exception:
        pass

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


def get_new_tenders(since_hours: int = 0, limit: int = 20) -> list:
    """
    Get active tenders with future deadlines.
    since_hours=0 means all active tenders (no fetched_at filter).
    since_hours>0 means only tenders fetched within the last N hours.
    """
    conn = get_conn()
    c = conn.cursor()
    if since_hours > 0:
        c.execute("""
            SELECT * FROM tenders
            WHERE status = 'active'
              AND deadline > datetime('now')
              AND fetched_at > datetime('now', ? || ' hours')
            ORDER BY deadline ASC
            LIMIT ?
        """, (f"-{since_hours}", limit))
    else:
        c.execute("""
            SELECT * FROM tenders
            WHERE status = 'active'
              AND deadline > datetime('now')
            ORDER BY deadline ASC
            LIMIT ?
        """, (limit,))
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


def get_tenders_for_subscriber(phone: str, since_hours: int = 0, limit: int = 10) -> list:
    """Get active tenders filtered by the subscriber's sector preference."""
    sub = get_subscriber(phone)
    if not sub:
        return []

    tenders = get_new_tenders(since_hours=since_hours, limit=limit)
    sectors = sub.get("sectors", "all")

    if sectors == "all":
        return tenders

    sector = sectors.lower()
    return [
        t for t in tenders
        if sector in (t.get("category") or "").lower()
        or sector in (t.get("tags") or "").lower()
    ]


# ── Interaction Logging ────────────────────────────────────────────────────

def log_interaction(phone: str, direction: str, msg_type: str, content: str, command: str = ""):
    """
    Log every inbound/outbound interaction.
    direction: 'inbound' (user→bot) or 'outbound' (bot→user)
    msg_type: 'text', 'button_reply', 'list_reply', 'template', 'buttons', etc.
    command: the resolved command name (e.g. 'help', 'list', 'search', 'onboarding')
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO interaction_logs (phone, direction, msg_type, content, command, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (phone, direction, msg_type, content[:500], command, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_interaction_logs(phone: str = None, limit: int = 50, offset: int = 0) -> list:
    """Get interaction logs, optionally filtered by phone."""
    conn = get_conn()
    c = conn.cursor()
    if phone:
        c.execute("""
            SELECT * FROM interaction_logs WHERE phone = ?
            ORDER BY timestamp DESC LIMIT ? OFFSET ?
        """, (phone, limit, offset))
    else:
        c.execute("""
            SELECT * FROM interaction_logs
            ORDER BY timestamp DESC LIMIT ? OFFSET ?
        """, (limit, offset))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_interaction_stats(period: str = "today") -> list[dict]:
    """
    Get per-user interaction counts for fraud detection.
    period: 'today', 'week', 'month'
    Returns list of {phone, company_name, inbound_count, outbound_count, total, first_seen, last_seen}
    """
    period_filter = {
        "today": "datetime('now', '-1 day')",
        "week": "datetime('now', '-7 days')",
        "month": "datetime('now', '-30 days')",
    }.get(period, "datetime('now', '-1 day')")

    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT
            l.phone,
            COALESCE(s.company_name, 'Unknown') as company_name,
            SUM(CASE WHEN l.direction = 'inbound' THEN 1 ELSE 0 END) as inbound_count,
            SUM(CASE WHEN l.direction = 'outbound' THEN 1 ELSE 0 END) as outbound_count,
            COUNT(*) as total,
            MIN(l.timestamp) as first_seen,
            MAX(l.timestamp) as last_seen,
            COALESCE(s.active, 0) as active
        FROM interaction_logs l
        LEFT JOIN subscribers s ON l.phone = s.phone
        WHERE l.timestamp > {period_filter}
        GROUP BY l.phone
        ORDER BY total DESC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_interaction_count(phone: str, hours: int = 24) -> int:
    """Count interactions from a phone in the last N hours (for rate limiting)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*) FROM interaction_logs
        WHERE phone = ? AND direction = 'inbound'
          AND timestamp > datetime('now', ? || ' hours')
    """, (phone, f"-{hours}"))
    count = c.fetchone()[0]
    conn.close()
    return count


def save_ai_summary(ocid: str, summary: str, tags: str = ""):
    conn = get_conn()
    c = conn.cursor()
    if tags:
        c.execute("UPDATE tenders SET ai_summary = ?, tags = ? WHERE ocid = ?", (summary, tags, ocid))
    else:
        c.execute("UPDATE tenders SET ai_summary = ? WHERE ocid = ?", (summary, ocid))
    conn.commit()
    conn.close()
