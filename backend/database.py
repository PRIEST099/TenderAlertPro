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

    # ── New tables ──────────────────────────────────────────────────────

    c.execute("""
        CREATE TABLE IF NOT EXISTS awards (
            id TEXT PRIMARY KEY,
            ocid TEXT,
            buyer_name TEXT,
            buyer_id TEXT,
            category TEXT,
            title TEXT,
            supplier_name TEXT,
            supplier_id TEXT,
            award_amount REAL,
            currency TEXT DEFAULT 'RWF',
            award_date TEXT,
            num_bidders INTEGER,
            procurement_method TEXT,
            status TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS company_profiles (
            phone TEXT PRIMARY KEY,
            sectors TEXT,
            certifications TEXT,
            typical_contract_min INTEGER,
            typical_contract_max INTEGER,
            employee_count TEXT,
            past_clients TEXT,
            district TEXT,
            updated_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS user_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            doc_label TEXT,
            file_path TEXT NOT NULL,
            filename TEXT,
            uploaded_at TEXT DEFAULT (datetime('now')),
            UNIQUE(phone, doc_type)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS bid_pipeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            ocid TEXT NOT NULL,
            status TEXT DEFAULT 'watching',
            notes TEXT,
            reminder_7d INTEGER DEFAULT 0,
            reminder_3d INTEGER DEFAULT 0,
            reminder_1d INTEGER DEFAULT 0,
            added_at TEXT,
            updated_at TEXT,
            UNIQUE(phone, ocid)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY,
            phone TEXT NOT NULL,
            tender_id TEXT,
            tender_title TEXT,
            file_path TEXT,
            credits_used INTEGER DEFAULT 1,
            generated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY,
            phone TEXT NOT NULL,
            amount INTEGER NOT NULL,
            type TEXT,
            plan TEXT,
            credits_added INTEGER DEFAULT 0,
            momo_transaction_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS org_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_phone TEXT NOT NULL,
            member_phone TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            added_at TEXT,
            UNIQUE(owner_phone, member_phone)
        )
    """)

    # ── Indexes ──────────────────────────────────────────────────────

    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_awards_buyer ON awards(buyer_name)",
        "CREATE INDEX IF NOT EXISTS idx_awards_supplier ON awards(supplier_name)",
        "CREATE INDEX IF NOT EXISTS idx_awards_category ON awards(category)",
        "CREATE INDEX IF NOT EXISTS idx_pipeline_phone ON bid_pipeline(phone)",
    ]:
        c.execute(idx_sql)

    # ── Column migrations for existing tables ────────────────────────

    migrations = [
        ("subscribers", "company_name",        "TEXT DEFAULT ''"),
        ("subscribers", "onboarding_step",     "TEXT DEFAULT 'awaiting_name'"),
        ("subscribers", "tags",                "TEXT DEFAULT ''"),
        ("subscribers", "deep_analyses_used",  "INTEGER DEFAULT 0"),
        ("subscribers", "subscription_tier",   "TEXT DEFAULT 'free'"),
        ("subscribers", "analysis_reset_date", "TEXT DEFAULT ''"),
        ("subscribers", "credits",             "INTEGER DEFAULT 0"),
        ("subscribers", "rate_limit_exempt",   "INTEGER DEFAULT 0"),
        ("tenders",     "tags",                "TEXT DEFAULT ''"),
        ("tenders",     "deep_analysis",       "TEXT DEFAULT ''"),
        ("tenders",     "published_at",        "TEXT DEFAULT ''"),
        ("tenders",     "sub_category",        "TEXT DEFAULT ''"),
        ("bid_pipeline", "cached_analysis",    "TEXT DEFAULT ''"),
        ("bid_pipeline", "associated_docs",    "TEXT DEFAULT ''"),
    ]
    for table, col, definition in migrations:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
        except Exception:
            pass

    conn.commit()
    conn.close()


def upsert_tender(tender: dict):
    # Remove items_description before insert (not a DB column, used for categorizer)
    tender = dict(tender)
    tender.pop("items_description", None)

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO tenders (ocid, title, description, buyer_name, category, status,
                             value_amount, value_currency, deadline, source_url, raw_json,
                             published_at, fetched_at)
        VALUES (:ocid, :title, :description, :buyer_name, :category, :status,
                :value_amount, :value_currency, :deadline, :source_url, :raw_json,
                :published_at, :fetched_at)
        ON CONFLICT(ocid) DO UPDATE SET
            status = excluded.status,
            deadline = excluded.deadline,
            published_at = COALESCE(excluded.published_at, tenders.published_at),
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
              AND deadline >= date('now')
              AND fetched_at > datetime('now', ? || ' hours')
            ORDER BY deadline ASC
            LIMIT ?
        """, (f"-{since_hours}", limit))
    else:
        c.execute("""
            SELECT * FROM tenders
            WHERE status = 'active'
              AND deadline >= date('now')
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
          AND deadline >= date('now')
        ORDER BY deadline ASC
        LIMIT ?
    """, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_tenders_for_subscriber(phone: str, since_hours: int = 0, limit: int = 10) -> list:
    """Get active tenders filtered by the subscriber's sector preference.
    Matches against category, sub_category, and tags for fine-grained filtering."""
    sub = get_subscriber(phone)
    if not sub:
        return []

    tenders = get_new_tenders(since_hours=since_hours, limit=limit * 3)  # fetch more to filter
    sectors = sub.get("sectors", "all")

    if sectors == "all":
        return tenders[:limit]

    sector = sectors.lower()
    matched = []
    for t in tenders:
        cat = (t.get("category") or "").lower()
        sub_cat = (t.get("sub_category") or "").lower()
        tags = (t.get("tags") or "").lower()

        if (sector in cat or sector in sub_cat or sector in tags
            or (sector == "ict" and ("technology" in sub_cat or "ict" in sub_cat))
            or (sector == "construction" and ("infrastructure" in sub_cat or "construction" in sub_cat or "works" in cat))
            or (sector == "health" and ("medical" in sub_cat or "health" in sub_cat))
            or (sector == "consulting" and ("advisory" in sub_cat or "consulting" in sub_cat or "services" in cat))
            or (sector == "supply" and ("equipment" in sub_cat or "supply" in sub_cat or "goods" in cat))
            or (sector == "education" and ("training" in sub_cat or "education" in sub_cat))
            or (sector == "agriculture" and ("livestock" in sub_cat or "agriculture" in sub_cat))
            or (sector == "energy" and ("utilities" in sub_cat or "energy" in sub_cat))
            or (sector == "other" and (sub_cat in ("", "other")))
        ):
            matched.append(t)
            if len(matched) >= limit:
                break

    return matched


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


# ── Awards (Historical Intelligence) ─────────────────────────────────────

def upsert_award(award: dict):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO awards (id, ocid, buyer_name, buyer_id, category, title,
                           supplier_name, supplier_id, award_amount, currency,
                           award_date, num_bidders, procurement_method, status)
        VALUES (:id, :ocid, :buyer_name, :buyer_id, :category, :title,
                :supplier_name, :supplier_id, :award_amount, :currency,
                :award_date, :num_bidders, :procurement_method, :status)
        ON CONFLICT(id) DO UPDATE SET
            award_amount = excluded.award_amount,
            status = excluded.status,
            award_date = excluded.award_date
    """, award)
    conn.commit()
    conn.close()


def get_buyer_history(buyer_name: str, category: str = None, limit: int = 20) -> list:
    """Get past awards from the same buyer, optionally filtered by category."""
    conn = get_conn()
    c = conn.cursor()
    if category:
        c.execute("""
            SELECT * FROM awards
            WHERE buyer_name = ? AND category = ?
            ORDER BY award_date DESC LIMIT ?
        """, (buyer_name, category, limit))
    else:
        c.execute("""
            SELECT * FROM awards
            WHERE buyer_name = ?
            ORDER BY award_date DESC LIMIT ?
        """, (buyer_name, limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_supplier_wins(supplier_name: str, limit: int = 20) -> list:
    """How often a supplier wins contracts."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM awards WHERE supplier_name = ?
        ORDER BY award_date DESC LIMIT ?
    """, (supplier_name, limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_competition_stats(buyer_name: str, category: str = None) -> dict:
    """Aggregate competition stats for a buyer: avg bidders, avg amount, top suppliers."""
    conn = get_conn()
    c = conn.cursor()

    if category:
        c.execute("""
            SELECT AVG(num_bidders) as avg_bidders,
                   AVG(award_amount) as avg_amount,
                   COUNT(*) as total_awards
            FROM awards WHERE buyer_name = ? AND category = ?
        """, (buyer_name, category))
    else:
        c.execute("""
            SELECT AVG(num_bidders) as avg_bidders,
                   AVG(award_amount) as avg_amount,
                   COUNT(*) as total_awards
            FROM awards WHERE buyer_name = ?
        """, (buyer_name,))

    stats = dict(c.fetchone())

    # Top suppliers for this buyer
    if category:
        c.execute("""
            SELECT supplier_name, COUNT(*) as wins,
                   AVG(award_amount) as avg_amount,
                   SUM(award_amount) as total_value
            FROM awards WHERE buyer_name = ? AND category = ?
            GROUP BY supplier_name ORDER BY wins DESC LIMIT 5
        """, (buyer_name, category))
    else:
        c.execute("""
            SELECT supplier_name, COUNT(*) as wins,
                   AVG(award_amount) as avg_amount,
                   SUM(award_amount) as total_value
            FROM awards WHERE buyer_name = ?
            GROUP BY supplier_name ORDER BY wins DESC LIMIT 5
        """, (buyer_name,))

    stats["top_suppliers"] = [dict(r) for r in c.fetchall()]
    conn.close()
    return stats


def get_awards_count() -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM awards")
    count = c.fetchone()[0]
    conn.close()
    return count


# ── Deep Analysis Cache ──────────────────────────────────────────────────

def save_deep_analysis(ocid: str, analysis_json: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE tenders SET deep_analysis = ? WHERE ocid = ?", (analysis_json, ocid))
    conn.commit()
    conn.close()


def get_deep_analysis(ocid: str) -> str | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT deep_analysis FROM tenders WHERE ocid = ?", (ocid,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        return row[0]
    return None


# ── Subscriber Quota & Credits ───────────────────────────────────────────

def check_analysis_quota(phone: str) -> dict:
    """Check if user can perform a deep analysis. Auto-resets monthly."""
    sub = get_subscriber(phone)
    if not sub:
        return {"allowed": False, "used": 0, "limit": 0, "tier": "none"}

    tier = sub.get("subscription_tier", "free")
    used = sub.get("deep_analyses_used", 0)
    reset_date = sub.get("analysis_reset_date", "")

    # Monthly reset check
    current_month = datetime.utcnow().strftime("%Y-%m")
    if reset_date[:7] != current_month:
        used = 0
        update_subscriber(phone, deep_analyses_used=0, analysis_reset_date=datetime.utcnow().isoformat())

    limits = {"free": 3, "regular": 0, "pro": 999, "business": 999}
    limit = limits.get(tier, 3)

    return {"allowed": used < limit, "used": used, "limit": limit, "tier": tier}


def count_tender_views_today(phone: str) -> int:
    """Count how many tender details this user has viewed today (for Regular tier daily limit)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*) FROM interaction_logs
        WHERE phone = ? AND command = 'tender_detail'
          AND timestamp >= date('now')
    """, (phone,))
    count = c.fetchone()[0]
    conn.close()
    return count


def count_messages_today(phone: str) -> int:
    """Count how many inbound messages this user has sent today (for free tier daily limit)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*) FROM interaction_logs
        WHERE phone = ? AND direction = 'inbound'
          AND timestamp >= date('now')
    """, (phone,))
    count = c.fetchone()[0]
    conn.close()
    return count


def increment_analysis_count(phone: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE subscribers
        SET deep_analyses_used = COALESCE(deep_analyses_used, 0) + 1
        WHERE phone = ?
    """, (phone,))
    conn.commit()
    conn.close()


# ── Company Profiles ─────────────────────────────────────────────────────

def save_company_profile(phone: str, profile: dict):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO company_profiles (phone, sectors, certifications,
            typical_contract_min, typical_contract_max, employee_count,
            past_clients, district, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
            sectors = excluded.sectors,
            certifications = excluded.certifications,
            typical_contract_min = excluded.typical_contract_min,
            typical_contract_max = excluded.typical_contract_max,
            employee_count = excluded.employee_count,
            past_clients = excluded.past_clients,
            district = excluded.district,
            updated_at = excluded.updated_at
    """, (
        phone,
        profile.get("sectors", ""),
        profile.get("certifications", ""),
        profile.get("typical_contract_min"),
        profile.get("typical_contract_max"),
        profile.get("employee_count", ""),
        profile.get("past_clients", ""),
        profile.get("district", ""),
        datetime.utcnow().isoformat(),
    ))
    conn.commit()
    conn.close()


def get_company_profile(phone: str) -> dict | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM company_profiles WHERE phone = ?", (phone,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


# ── User Documents ───────────────────────────────────────────────────────

def upsert_user_document(phone: str, doc_type: str, doc_label: str, file_path: str, filename: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO user_documents (phone, doc_type, doc_label, file_path, filename, uploaded_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(phone, doc_type) DO UPDATE SET
            doc_label = excluded.doc_label,
            file_path = excluded.file_path,
            filename = excluded.filename,
            uploaded_at = excluded.uploaded_at
    """, (phone, doc_type, doc_label, file_path, filename, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_user_documents(phone: str) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM user_documents WHERE phone = ?", (phone,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_user_document(phone: str, doc_type: str) -> dict | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM user_documents WHERE phone = ? AND doc_type = ?", (phone, doc_type))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


# ── Bid Pipeline ─────────────────────────────────────────────────────────

def add_to_pipeline(phone: str, ocid: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO bid_pipeline (phone, ocid, status, added_at, updated_at)
        VALUES (?, ?, 'watching', ?, ?)
        ON CONFLICT(phone, ocid) DO NOTHING
    """, (phone, ocid, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_pipeline(phone: str) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT bp.*, t.title, t.buyer_name, t.deadline, t.value_amount
        FROM bid_pipeline bp
        LEFT JOIN tenders t ON bp.ocid = t.ocid
        WHERE bp.phone = ?
        ORDER BY bp.added_at DESC
    """, (phone,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def update_pipeline_status(phone: str, ocid: str, status: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE bid_pipeline SET status = ?, updated_at = ?
        WHERE phone = ? AND ocid = ?
    """, (status, datetime.utcnow().isoformat(), phone, ocid))
    conn.commit()
    conn.close()


def save_pipeline_analysis(phone: str, ocid: str, analysis_json: str):
    """Cache a deep analysis snapshot in the pipeline item."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE bid_pipeline SET cached_analysis = ?, updated_at = ?
        WHERE phone = ? AND ocid = ?
    """, (analysis_json, datetime.utcnow().isoformat(), phone, ocid))
    conn.commit()
    conn.close()


def get_pipeline_analysis(phone: str, ocid: str) -> dict | None:
    """Retrieve cached deep analysis from pipeline."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT cached_analysis FROM bid_pipeline WHERE phone = ? AND ocid = ?", (phone, ocid))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        import json
        try:
            return json.loads(row[0])
        except Exception:
            return None
    return None


def search_pipeline(phone: str, keyword: str) -> list:
    """Fuzzy search pipeline items by tender title."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT bp.*, t.title, t.buyer_name, t.deadline, t.value_amount, t.deep_analysis
        FROM bid_pipeline bp
        LEFT JOIN tenders t ON bp.ocid = t.ocid
        WHERE bp.phone = ? AND LOWER(t.title) LIKE ?
        ORDER BY bp.added_at DESC
    """, (phone, f"%{keyword.lower()}%"))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_pipeline_item(phone: str, ocid: str) -> dict | None:
    """Fetch a single pipeline item with tender details."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT bp.*, t.title, t.buyer_name, t.deadline, t.value_amount, t.deep_analysis
        FROM bid_pipeline bp
        LEFT JOIN tenders t ON bp.ocid = t.ocid
        WHERE bp.phone = ? AND bp.ocid = ?
    """, (phone, ocid))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


# ── Proposals ────────────────────────────────────────────────────────────

def log_proposal(phone: str, tender_id: str, tender_title: str, file_path: str):
    import uuid
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO proposals (id, phone, tender_id, tender_title, file_path, generated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (str(uuid.uuid4()), phone, tender_id, tender_title, file_path, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_proposal_count(phone: str) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM proposals WHERE phone = ?", (phone,))
    count = c.fetchone()[0]
    conn.close()
    return count


# ── Payments ─────────────────────────────────────────────────────────────

def log_payment(phone: str, amount: int, pay_type: str, plan: str = "", credits_added: int = 0) -> str:
    import uuid
    payment_id = str(uuid.uuid4())[:8]
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO payments (id, phone, amount, type, plan, credits_added, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
    """, (payment_id, phone, amount, pay_type, plan, credits_added, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return payment_id


def confirm_payment(payment_id: str) -> bool:
    """Confirm a payment and apply credits/plan to the subscriber."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM payments WHERE id = ? AND status = 'pending'", (payment_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False

    payment = dict(row)
    phone = payment["phone"]

    c.execute("UPDATE payments SET status = 'confirmed' WHERE id = ?", (payment_id,))

    if payment["type"] == "subscription":
        c.execute("""
            UPDATE subscribers SET subscription_tier = ?, credits = credits + ?
            WHERE phone = ?
        """, (payment["plan"], payment.get("credits_added", 0), phone))
    elif payment["type"] == "credits":
        c.execute("""
            UPDATE subscribers SET credits = COALESCE(credits, 0) + ?
            WHERE phone = ?
        """, (payment["credits_added"], phone))

    conn.commit()
    conn.close()
    return True


def get_payment_history(phone: str) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM payments WHERE phone = ? ORDER BY created_at DESC", (phone,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ── Organization / Team Members ──────────────────────────────────────────

MAX_ORG_MEMBERS = 3


def add_org_member(owner_phone: str, member_phone: str) -> bool:
    """Add a member to an org. Returns False if limit reached or already exists."""
    if count_org_members(owner_phone) >= MAX_ORG_MEMBERS:
        return False
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO org_members (owner_phone, member_phone, role, added_at)
            VALUES (?, ?, 'member', ?)
        """, (owner_phone, member_phone, datetime.utcnow().isoformat()))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def remove_org_member(owner_phone: str, member_phone: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM org_members WHERE owner_phone = ? AND member_phone = ?",
              (owner_phone, member_phone))
    removed = c.rowcount > 0
    conn.commit()
    conn.close()
    return removed


def get_org_members(owner_phone: str) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT om.member_phone, om.role, om.added_at, s.company_name
        FROM org_members om
        LEFT JOIN subscribers s ON om.member_phone = s.phone
        WHERE om.owner_phone = ?
    """, (owner_phone,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_org_owner(member_phone: str) -> str | None:
    """Check if this phone is an org member. Return the owner's phone or None."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT owner_phone FROM org_members WHERE member_phone = ?", (member_phone,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def count_org_members(owner_phone: str) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM org_members WHERE owner_phone = ?", (owner_phone,))
    count = c.fetchone()[0]
    conn.close()
    return count
