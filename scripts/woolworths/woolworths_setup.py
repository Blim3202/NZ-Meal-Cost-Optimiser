"""
Woolworths NZ Store Setup Pipeline
===================================
Builds the unified store listing used by the optimizer and API module.

Three-step pipeline:
    Step 1 - fetch_store_choices()
        GET /api/v1/addresses/pickup-addresses
        Returns ~188 unique pickup locations across all storeAreas.
        Area 494 ("All Pick up locations") only has ~171 stores; regional areas
        contain additional pickup points (e.g., Woolworths Chartwell).
        Outputs: data/woolworths_store_choices.json, .csv

    Step 2 - fetch_store_data()
        GET https://api.cdx.nz/site-location/api/v1/sites
        Returns store details including lat/lon, extra1 (fulfilmentStoreId),
        and extra2 (pickupAddressId).
        Outputs: data/woolworths_store_data.json, .csv

    Step 3 - merge_stores()
        Joins choices (pickupAddressId) with data (lat/lon) on SiteDataID.
        With cleaned=True (default), drops stores without coordinates.
        Outputs: data/woolworths_stores.csv (177 stores with coords)

Usage:
    # Run full pipeline
    python woolworths_setup.py

    # Import individual steps
    from woolworths_setup import fetch_store_choices, fetch_store_data, merge_stores
    fetch_store_choices()
    fetch_store_data()
    merge_stores(cleaned=True)

Reference: Woolworths_API.md section 15 (store setup process)
"""

import requests
import json
import csv
import os
import pandas as pd
from pathlib import Path
import sys

DATA_DIR = Path(__file__).parent.parent.parent / "data"
JSON_CHOICES = DATA_DIR / "woolworths_store_choices.json"
CSV_CHOICES = DATA_DIR / "woolworths_store_choices.csv"
JSON_DATA = DATA_DIR / "woolworths_store_data.json"
CSV_DATA = DATA_DIR / "woolworths_store_data.csv"
CSV_MERGED = DATA_DIR / "woolworths_stores.csv"


def clean_null(value):
    """Clean null or empty values to return a default string."""
    if value is None:
        return ""
    if isinstance(value, str) and value.strip() == "":
        return ""
    return str(value)


def fetch_store_choices() -> list[dict]:
    """
    Fetch Woolworths pickup store choices from the API.
    Returns a list of dicts with keys: id, name, address
    Dedupes across all storeAreas (area 494 'All Pick up locations' only has ~171 stores;
    regional areas contain additional pickup points like Woolworths Chartwell).
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


def fetch_store_data() -> list[dict]:
    """
    Fetch Woolworths store location data (lat/lon, extra IDs) from CDX API.
    Returns a list of dicts with keys: Store Name, Suburb, Address, Postcode, State,
    SiteDataID, latitude, longitude, Key Facilities
    """
    WOOLWORTHS_API_BASE_URL = "https://api.cdx.nz/site-location/api/v1/sites"
    # Apprx default coordinates for NZ when viewing https://www.woolworths.co.nz/store-finder/search in incognito
    DEFAULT_LATITUDE = -41.24564052749397
    DEFAULT_LONGITUDE = 173.1994906580824

    headers = {
        "sec-ch-ua": "\"Google Chrome\";v=\"149\", \"Chromium\";v=\"149\", \"Not)A;Brand\";v=\"24\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
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

    with open(JSON_DATA, "w", encoding="utf-8") as f:
        json.dump(stores_data, f, indent=4, ensure_ascii=False)
    print(f"[OK] Successfully downloaded and saved store JSON data to {JSON_DATA}")

    sites = stores_data.get('siteDetail', [])
    if not sites:
        print("[ERROR] No site data found in the response.")
        return []

    table_data = []
    for item in sites:
        site = item.get('site', {})

        name = clean_null(site.get('name'))
        suburb = clean_null(site.get('suburb'))
        address = clean_null(site.get('addressLine1'))
        postcode = clean_null(site.get('postcode'))
        state = clean_null(site.get('state'))
        SiteDataID = clean_null(site.get('extra2'))
        latitude = clean_null(site.get('latitude'))
        longitude = clean_null(site.get('longitude'))
        facilities = site.get('facilityList', {}).get('facility', [])
        facilities_str = ", ".join(facilities) if facilities else "None listed"

        table_data.append([
            name, suburb, address, postcode, state,
            SiteDataID, latitude, longitude, facilities_str
        ])

    headers = [
        "Store Name", "Suburb", "Address", "Postcode", "State",
        "SiteDataID", "latitude", "longitude", "Key Facilities"
    ]

    with open(CSV_DATA, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)
        writer.writerows(table_data)

    print(f"[OK] Successfully saved structured data for {len(sites)} woolworths stores at {CSV_DATA}.\n")
    return table_data


def merge_stores(cleaned: bool = True) -> pd.DataFrame:
    """
    Merge woolworths_store_choices.csv (pickup IDs + names) with
    woolworths_store_data.csv (lat/lon keyed by SiteDataID).
    
    Args:
        cleaned: If True (default), drop rows where latitude or longitude are NaN.
                 If False, keep all rows including those without coordinates.
    Returns the merged DataFrame.
    """
    df_choices = pd.read_csv(CSV_CHOICES)
    df_data = pd.read_csv(CSV_DATA)

    df_data_subset = df_data[['SiteDataID', 'latitude', 'longitude']]

    merged = df_choices.merge(
        df_data_subset,
        left_on='id',
        right_on='SiteDataID',
        how='left'
    ).drop('SiteDataID', axis=1)

    if cleaned:
        original_len = len(merged)
        merged = merged.dropna(subset=['latitude', 'longitude'])
        print(f"[INFO] Dropped {original_len - len(merged)} stores without coordinates (cleaned=True)")

    merged.to_csv(CSV_MERGED, index=False, encoding='utf-8')
    print(f"[OK] Successfully saved merged data for {len(merged)} woolworths stores at {CSV_MERGED}.\n")
    return merged


def run_full_setup():
    """Run the complete pipeline: fetch choices, fetch data, merge."""
    print("=" * 60)
    print("Step 1: Fetching Woolworths store choices (pickup locations)...")
    print("=" * 60)
    fetch_store_choices()

    print("=" * 60)
    print("Step 2: Fetching Woolworths store location data (CDX API)...")
    print("=" * 60)
    fetch_store_data()

    print("=" * 60)
    print("Step 3: Merging store choices with location data...")
    print("=" * 60)
    merge_stores(cleaned=True)

    print("=" * 60)
    print("[OK] Woolworths store setup complete!")
    print("=" * 60)


if __name__ == "__main__":
    run_full_setup()