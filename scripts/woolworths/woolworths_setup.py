"""
Woolworths NZ Store Setup Pipeline
===================================
Builds the two data files consumed by the optimiser and API module:

    1. data/woolworths_store_data.json  — raw CDX site-location response (183 sites)
    2. data/woolworths_stores.csv       — cleaned canonical store list keyed on
                                          extra1 (fulfilmentStoreId), with lat/lon

Pipeline (single function):
    fetch_store_data(cleaned=True)
        GET https://api.cdx.nz/site-location/api/v1/sites
        Writes the two files above. `cleaned=True` drops stores without valid
        coordinates or with extra1 == "null" (literal string emitted by CDX
        for missing values). The resulting woolworths_stores.csv is the
        canonical store list — its `id` column is the store_id used everywhere
        downstream (optimiser results, and the cw-lrkswrdjp cookie's
        `f-{id}` field).

Legacy (detached from the main pipeline — kept for historical reference only):
    fetch_store_choices()
        GET /api/v1/addresses/pickup-addresses (Woolworths website)
        Output: data/woolworths_store_choices.json + .csv
        Deprecated: this API returns pickupAddressId (extra2), which no longer
        drives store identity. Store identity now comes from CDX extra1.
        The function is retained so it can be called ad-hoc to regenerate the
        legacy files, but is NOT called by fetch_store_data() or __main__.

Usage:
    # Run full pipeline (produces both output files)
    python woolworths_setup.py

    # Import and call directly
    from woolworths_setup import fetch_store_data
    fetch_store_data(cleaned=True)

Reference: Woolworths_API.md section 15 (store setup process)
"""

import requests
import json
import csv
import pandas as pd
from pathlib import Path
import sys

DATA_DIR = Path(__file__).parent.parent.parent / "data"
JSON_DATA = DATA_DIR / "woolworths_store_data.json"
CSV_STORES = DATA_DIR / "woolworths_stores.csv"

# Legacy (commented out — not used by the current pipeline):
# JSON_CHOICES = DATA_DIR / "woolworths_store_choices.json"
# CSV_CHOICES = DATA_DIR / "woolworths_store_choices.csv"

# Hardcoded exclusions — stores that CDX still lists but are permanently
# closed. CDX has not yet reflected these closures, so we filter them here
# to prevent the optimiser / API from targeting defunct stores.
# Format: {extra1: "human-readable reason with shutdown date"}
EXCLUDED_STORE_IDS = {
    "9285": "Te Atatu Woolworths — permanently shut down on 24/04/2025; "
            "CDX listing not yet updated (returned by CDX but not in store_choices pipeline).",
    "9035": "Kaikohe Woolworths — permanently shut down on 15/02/2026; "
            "CDX listing not yet updated (returned by CDX but not in store_choices pipeline).",
}


def clean_null(value):
    """Clean null or empty values to return a default string."""
    if value is None:
        return ""
    if isinstance(value, str) and value.strip() == "":
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# Current pipeline
# ---------------------------------------------------------------------------

def fetch_store_data(cleaned: bool = True) -> list[dict]:
    """
    Fetch store location data from the CDX API and produce the two canonical
    Woolworths data files.

    Writes:
        data/woolworths_store_data.json  — raw CDX response (183 sites, unchanged)
        data/woolworths_stores.csv       — cleaned 5-column store list keyed on
                                            extra1 (fulfilmentStoreId)

    Args:
        cleaned: If True (default), drop stores where:
            - extra1 is missing or the literal string "null" (invalid store id)
            - latitude or longitude are missing or non-numeric
        If False, keep all stores (with blank coords where present).
    Returns:
        The cleaned list of store dicts (id, name, address, latitude, longitude).
    """
    WOOLWORTHS_API_BASE_URL = "https://api.cdx.nz/site-location/api/v1/sites"
    DEFAULT_LATITUDE = -41.24564052749397
    DEFAULT_LONGITUDE = 173.1994906580824

    headers = {
        "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    }

    params = {
        "latitude": DEFAULT_LATITUDE,
        "longitude": DEFAULT_LONGITUDE,
    }

    print(f"Fetching data from: {WOOLWORTHS_API_BASE_URL} with parameters {params}")
    try:
        response = requests.get(WOOLWORTHS_API_BASE_URL, headers=headers, params=params, timeout=20)
        response.raise_for_status()
        stores_data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Error fetching data: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Error decoding JSON response: {e}")
        sys.exit(1)

    # Write raw CDX JSON (file 1: woolworths_store_data.json)
    with open(JSON_DATA, "w", encoding="utf-8") as f:
        json.dump(stores_data, f, indent=4, ensure_ascii=False)
    print(f"[OK] Saved raw JSON to {JSON_DATA}")

    sites = stores_data.get("siteDetail", [])
    if not sites:
        print("[ERROR] No site data found in the response.")
        return []

    # Build the cleaned 5-column store list (file 2: woolworths_stores.csv)
    rows = []
    for item in sites:
        site = item.get("site", {})
        extra1 = clean_null(site.get("extra1"))
        # Skip sites without a usable fulfilmentStoreId (extra1). CDX emits the
        # literal string "null" for missing values; clean_null keeps it as a
        # non-empty token, so filter it explicitly.
        if not extra1 or str(extra1).lower() == "null":
            continue
        # Skip hardcoded exclusions (permanently shut-down stores that CDX
        # still lists).
        if str(extra1) in EXCLUDED_STORE_IDS:
            print(f"[INFO] Skipping shut-down store extra1={extra1}: "
                  f"{EXCLUDED_STORE_IDS[str(extra1)]}")
            continue
        rows.append({
            "id": extra1,
            "name": clean_null(site.get("name")).lstrip(),
            "address": clean_null(site.get("addressLine1")),
            "latitude": clean_null(site.get("latitude")),
            "longitude": clean_null(site.get("longitude")),
        })

    if cleaned:
        original_len = len(rows)

        def _valid_coord(v):
            if v is None or v == "":
                return False
            try:
                float(v)
                return True
            except (ValueError, TypeError):
                return False

        rows = [r for r in rows if _valid_coord(r["latitude"]) and _valid_coord(r["longitude"])]
        print(f"[INFO] Dropped {original_len - len(rows)} stores without coordinates (cleaned=True)")

    merged = pd.DataFrame(rows, columns=["id", "name", "address", "latitude", "longitude"])
    merged.to_csv(CSV_STORES, index=False, encoding="utf-8")
    print(f"[OK] Saved {len(merged)} woolworths stores (keyed on extra1) at {CSV_STORES}.\n")
    return merged.to_dict("records")


# ---------------------------------------------------------------------------
# Legacy (detached — kept for reference only)
# ---------------------------------------------------------------------------

def fetch_store_choices() -> list[dict]:
    """
    [LEGACY] Fetch Woolworths pickup store choices from the pickup-addresses API.

    NOT called by fetch_store_data() or the main pipeline. Retained so it can
    be invoked ad-hoc to regenerate the legacy data/woolworths_store_choices.*
    files for historical reference.

    Returns pickup locations keyed by pickupAddressId (extra2) — deprecated as
    the store identity source. Store identity now comes from CDX extra1.
    """
    WOOLWORTHS_API_BASE_URL = "https://www.woolworths.co.nz/api/v1/addresses/pickup-addresses"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.woolworths.co.nz/bookatimeslot/(hww-modal:change-pick-up-store)",
        "X-Requested-With": "OnlineShopping.WebApp",
        "X-UI-Ver": "7.75.24",
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
    }

    session = requests.Session()
    session.headers.update(headers)

    try:
        session.get("https://www.woolworths.co.nz/bookatimeslot", timeout=20)
    except requests.RequestException as e:
        print(f"[ERROR] Error visiting initial page: {e}")
        sys.exit(1)

    print(f"Fetching data from: {WOOLWORTHS_API_BASE_URL}")
    try:
        response = session.get(WOOLWORTHS_API_BASE_URL, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"[ERROR] Error fetching data: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Error decoding JSON response: {e}")
        sys.exit(1)

    # Legacy output paths — defined here for the detached legacy function only
    JSON_CHOICES = DATA_DIR / "woolworths_store_choices.json"
    CSV_CHOICES = DATA_DIR / "woolworths_store_choices.csv"

    DATA_DIR.mkdir(exist_ok=True)
    with open(JSON_CHOICES, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[OK] Saved raw JSON to {JSON_CHOICES}")

    # Dedup across all storeAreas by id
    seen_ids = set()
    stores = []
    for area in data.get("storeAreas", []):
        for store in area.get("storeAddresses", []):
            sid = store.get("id")
            if sid not in seen_ids:
                seen_ids.add(sid)
                stores.append(store)

    if not stores:
        print("[ERROR] No store addresses found in any area")
        sys.exit(1)

    fieldnames = ["id", "name", "address"]
    with open(CSV_CHOICES, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for store in stores:
            writer.writerow({
                "id": store.get("id"),
                "name": store.get("name"),
                "address": store.get("address"),
            })

    print(f"[OK] Saved {len(stores)} unique locations to {CSV_CHOICES}")
    return stores


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_full_setup():
    """Run the full pipeline: fetch CDX data and emit both output files."""
    print("=" * 60)
    print("Fetching Woolworths store location data (CDX API)...")
    print("=" * 60)
    fetch_store_data(cleaned=True)

    print("=" * 60)
    print("[OK] Woolworths store setup complete!")
    print(f"  - {JSON_DATA}")
    print(f"  - {CSV_STORES}")
    print("=" * 60)


if __name__ == "__main__":
    run_full_setup()
