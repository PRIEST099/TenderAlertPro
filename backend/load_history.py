"""
load_history.py — One-time bulk loader for historical OCDS awards data.

Downloads bulk JSONL.GZ files for 2024-2026 from the Open Contracting Partnership,
extracts every award record, and populates the awards table for historical intelligence.

Usage:
    python load_history.py              # Load all years (2024-2026)
    python load_history.py --year 2025  # Load a specific year only
"""

import gzip
import json
import sys
import uuid
import requests
from datetime import datetime

# Allow running from backend/ or project root
sys.path.insert(0, ".")
sys.path.insert(0, "backend")

from config import DATABASE_PATH
from database import init_db, upsert_award, get_awards_count

BULK_URL_TEMPLATE = "https://fastly.data.open-contracting.org/downloads/rwanda_bulk/3460/{year}.jsonl.gz"
HEADERS = {"User-Agent": "TenderAlertPro/1.0"}

CATEGORY_LABELS = {
    "goods": "Goods / Supply",
    "works": "Works / Construction",
    "services": "Services / Consulting",
}


def extract_awards_from_release(release: dict) -> list[dict]:
    """Extract all award records from a single OCDS release."""
    awards_out = []
    ocid = release.get("ocid", "")
    if not ocid:
        return []

    tender = release.get("tender", {})
    buyer = release.get("buyer", {})
    buyer_name = buyer.get("name", "")
    buyer_id = buyer.get("id", "")
    category_raw = tender.get("mainProcurementCategory", "")
    category = CATEGORY_LABELS.get(category_raw, category_raw or "Other")
    num_bidders = tender.get("numberOfTenderers")
    procurement_method = tender.get("procurementMethod", "")

    for award in release.get("awards", []):
        award_id = award.get("id", str(uuid.uuid4())[:12])
        award_title = award.get("title", tender.get("title", ""))
        award_amount = (award.get("value") or {}).get("amount")
        currency = (award.get("value") or {}).get("currency", "RWF")
        award_date = award.get("date", "")
        award_status = award.get("status", "")

        # Each award may have multiple suppliers (framework agreements)
        suppliers = award.get("suppliers", [])
        if not suppliers:
            suppliers = [{"name": "Unknown", "id": ""}]

        for supplier in suppliers:
            # Create a unique ID combining award ID and supplier
            unique_id = f"{ocid}:{award_id}:{supplier.get('id', '')}"[:200]

            awards_out.append({
                "id": unique_id,
                "ocid": ocid,
                "buyer_name": buyer_name,
                "buyer_id": buyer_id,
                "category": category,
                "title": award_title[:500] if award_title else "",
                "supplier_name": supplier.get("name", "Unknown"),
                "supplier_id": supplier.get("id", ""),
                "award_amount": award_amount,
                "currency": currency,
                "award_date": award_date,
                "num_bidders": num_bidders,
                "procurement_method": procurement_method,
                "status": award_status,
            })

    return awards_out


def load_year(year: int) -> int:
    """Download and process a single year's bulk OCDS data. Returns awards count."""
    url = BULK_URL_TEMPLATE.format(year=year)
    print(f"[load_history] Downloading {year} data from {url}...")

    try:
        resp = requests.get(url, stream=True, timeout=120, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[load_history] Download failed for {year}: {e}")
        return 0

    size_mb = len(resp.content) / (1024 * 1024)
    print(f"[load_history] Downloaded {size_mb:.1f} MB. Decompressing...")

    content = gzip.decompress(resp.content)
    lines = content.splitlines()
    print(f"[load_history] {len(lines)} releases to process...")

    total_awards = 0
    releases_with_awards = 0

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Bulk file may be release packages or individual releases
        releases = obj.get("releases", [obj]) if isinstance(obj, dict) else [obj]

        for release in releases:
            awards = extract_awards_from_release(release)
            if awards:
                releases_with_awards += 1
                for award in awards:
                    upsert_award(award)
                    total_awards += 1

        if (i + 1) % 5000 == 0:
            print(f"[load_history] Processed {i + 1}/{len(lines)} releases, {total_awards} awards so far...")

    print(f"[load_history] {year}: {total_awards} awards from {releases_with_awards} releases")
    return total_awards


def main():
    init_db()

    years = [2024, 2025, 2026]
    if "--year" in sys.argv:
        idx = sys.argv.index("--year")
        if idx + 1 < len(sys.argv):
            years = [int(sys.argv[idx + 1])]

    print(f"[load_history] Loading historical awards for years: {years}")
    print(f"[load_history] Database: {DATABASE_PATH}")
    print(f"[load_history] Awards before: {get_awards_count()}")
    print()

    grand_total = 0
    for year in years:
        count = load_year(year)
        grand_total += count
        print()

    print(f"[load_history] DONE. Total awards loaded: {grand_total}")
    print(f"[load_history] Awards in DB now: {get_awards_count()}")


if __name__ == "__main__":
    main()
