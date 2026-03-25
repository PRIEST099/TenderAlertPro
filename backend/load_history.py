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
    """Download and process a single year's bulk OCDS data. Returns awards count.
    Uses streaming decompression to keep memory usage low (~5MB instead of 200MB).
    """
    url = BULK_URL_TEMPLATE.format(year=year)
    print(f"[load_history] Downloading + streaming {year} data from {url}...")

    try:
        resp = requests.get(url, stream=True, timeout=300, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[load_history] Download failed for {year}: {e}")
        return 0

    total_awards = 0
    releases_with_awards = 0
    line_count = 0

    # Stream decompress — never loads full file into RAM
    import io
    raw_stream = io.BytesIO()
    downloaded = 0
    for chunk in resp.iter_content(chunk_size=65536):
        raw_stream.write(chunk)
        downloaded += len(chunk)

    raw_stream.seek(0)
    print(f"[load_history] Downloaded {downloaded / 1024 / 1024:.1f} MB. Streaming decompression...")

    # Decompress in streaming mode using gzip file wrapper
    with gzip.GzipFile(fileobj=raw_stream) as gz:
        for raw_line in gz:
            line = raw_line.strip()
            if not line:
                continue
            line_count += 1

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            releases = obj.get("releases", [obj]) if isinstance(obj, dict) else [obj]

            for release in releases:
                awards = extract_awards_from_release(release)
                if awards:
                    releases_with_awards += 1
                    for award in awards:
                        upsert_award(award)
                        total_awards += 1

            if line_count % 500 == 0:
                print(f"[load_history] Processed {line_count} releases, {total_awards} awards so far...")

    print(f"[load_history] {year}: {total_awards} awards from {releases_with_awards}/{line_count} releases")
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
