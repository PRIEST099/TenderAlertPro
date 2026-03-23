"""
poller.py — Fetches Rwanda government tenders from the Umucyo OCDS API.

Strategy:
1. Try the live OCDS REST API (https://ocds.umucyo.gov.rw/opendata/api/v1/releases/all)
   - Filters by date_from (last N days) for incremental updates
   - Paginates via links.next until exhausted
2. Fall back to the OCP bulk JSONL.GZ download for the current year

Run directly to test: python poller.py
"""

import gzip
import json
import sys
import requests
from datetime import datetime, date, timezone

from config import UMUCYO_OCDS_ENDPOINT, UMUCYO_BULK_URL
from database import init_db, upsert_tender

HEADERS = {"Accept": "application/json", "User-Agent": "TenderAlertPro/1.0"}

# Map OCDS mainProcurementCategory values to friendly labels
CATEGORY_LABELS = {
    "goods": "Goods / Supply",
    "works": "Works / Construction",
    "services": "Services / Consulting",
}


def normalize_release(release: dict) -> dict | None:
    """Convert an OCDS release object to our flat tender schema."""
    tender = release.get("tender", {})
    if not tender:
        return None

    ocid = release.get("ocid", "")
    if not ocid:
        return None

    title = tender.get("title") or release.get("description") or "Untitled tender"
    description = tender.get("description", "")
    buyer = release.get("buyer", {})
    buyer_name = buyer.get("name", "Unknown entity")
    category_raw = tender.get("mainProcurementCategory", "")
    category = CATEGORY_LABELS.get(category_raw, category_raw or "Other")
    status = tender.get("status", "unknown")

    value_block = tender.get("value") or {}
    value_amount = value_block.get("amount")
    value_currency = value_block.get("currency", "RWF")

    period = tender.get("tenderPeriod") or {}
    deadline = period.get("endDate", "")

    source_url = f"https://ocds.umucyo.gov.rw/opendata/api/v1/releases?ocid={ocid}"

    return {
        "ocid": ocid,
        "title": title[:500],
        "description": (description or "")[:2000],
        "buyer_name": buyer_name[:300],
        "category": category,
        "status": status,
        "value_amount": value_amount,
        "value_currency": value_currency,
        "deadline": deadline,
        "source_url": source_url,
        "raw_json": json.dumps(release),
        "fetched_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    }


def fetch_live_ocds(page_size: int = 100, lookback_days: int = 2) -> list[dict]:
    """
    Fetch tenders from the live Umucyo OCDS REST API.

    Uses date_from to fetch only recent tenders (last `lookback_days` days),
    then follows links.next for pagination until exhausted.

    Returns a list of normalized tender dicts.
    """
    from datetime import timedelta
    date_from = (date.today() - timedelta(days=lookback_days)).isoformat()

    print(f"[poller] Fetching live OCDS API (from {date_from}): {UMUCYO_OCDS_ENDPOINT}")

    tenders = []
    url = UMUCYO_OCDS_ENDPOINT
    params = {
        "date_from": date_from,
        "limit": page_size,
        "sort_direction": "desc",
    }

    while url:
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            if not resp.content.strip():
                print("[poller] Live API returned empty body.")
                break
            data = resp.json()
        except requests.exceptions.JSONDecodeError:
            print(f"[poller] Live API returned non-JSON (status {resp.status_code}). Falling back.")
            return []
        except requests.RequestException as e:
            print(f"[poller] Live API request error: {e}")
            return []

        releases = data.get("releases", []) if isinstance(data, dict) else []
        if not releases:
            break

        for release in releases:
            normalized = normalize_release(release)
            if normalized:
                tenders.append(normalized)

        # Follow links.next for next page; clear params after first request
        # (the next URL already contains all needed query params)
        next_url = data.get("links", {}).get("next")
        if next_url:
            url = next_url
            params = {}  # next_url already has all params embedded
            print(f"[poller] Page fetched ({len(tenders)} so far), following next page...")
        else:
            break

    print(f"[poller] Live API done. {len(tenders)} tenders fetched.")
    return tenders


def fetch_bulk_ocds(year: int = None) -> list[dict]:
    """
    Download and parse the OCP bulk JSONL.GZ file for the given year.
    Only processes releases with status 'active' or 'planning' to keep it fast.
    """
    if year is None:
        year = date.today().year
    url = UMUCYO_BULK_URL.format(year=year)
    print(f"[poller] Downloading bulk OCDS data: {url}")

    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[poller] Bulk download error: {e}")
        return []

    tenders = []
    content = gzip.decompress(resp.content)
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Bulk file may be a release package or individual releases
        releases = obj.get("releases", [obj]) if isinstance(obj, dict) else [obj]
        for release in releases:
            t_status = release.get("tender", {}).get("status", "")
            if t_status not in ("active", "planning", ""):
                continue
            normalized = normalize_release(release)
            if normalized:
                tenders.append(normalized)

    return tenders


def poll_and_store(limit: int = None) -> int:
    """
    Main entry: try live endpoint first, fall back to bulk download.
    Stores new tenders in DB. Returns count of new records inserted.
    """
    init_db()

    tenders = fetch_live_ocds()
    if not tenders:
        print("[poller] Live endpoint returned nothing, trying bulk download...")
        tenders = fetch_bulk_ocds()

    if not tenders:
        print("[poller] No tenders fetched from any source.")
        return 0

    if limit:
        tenders = tenders[:limit]

    new_count = 0
    for t in tenders:
        result = upsert_tender(t)
        if result:
            new_count += 1

    print(f"[poller] Done. {len(tenders)} tenders processed, {new_count} new/updated.")
    return new_count


def preview(n: int = 10):
    """Print the first N tenders to stdout — useful for testing."""
    tenders = fetch_live_ocds(page_size=n)
    if not tenders:
        print("[poller] Live endpoint empty — fetching from bulk (this may take a moment)...")
        tenders = fetch_bulk_ocds()[:n]

    if not tenders:
        print("[poller] No data returned from any source. Check your network or API availability.")
        return

    print(f"\n{'='*60}")
    print(f"  TenderAlert Pro — Sample Tenders ({len(tenders)} shown)")
    print(f"{'='*60}\n")
    for i, t in enumerate(tenders, 1):
        value_str = f"RWF {t['value_amount']:,.0f}" if t["value_amount"] else "Value not disclosed"
        deadline_str = t["deadline"][:10] if t["deadline"] else "No deadline listed"
        print(f"[{i}] {t['title']}")
        print(f"     Buyer    : {t['buyer_name']}")
        print(f"     Category : {t['category']}")
        print(f"     Value    : {value_str}")
        print(f"     Deadline : {deadline_str}")
        print(f"     Status   : {t['status']}")
        print(f"     Link     : {t['source_url']}")
        print()


if __name__ == "__main__":
    if "--preview" in sys.argv or len(sys.argv) == 1:
        preview(n=10)
    else:
        count = poll_and_store()
        print(f"Inserted/updated {count} tenders.")
