"""
New World Unified Store Setup Pipeline
======================================
Fetches all New World stores and writes a 10-column CSV/JSON to
data/newworld_stores.csv / .json with columns:
    store_id, name, address, city, region, latitude, longitude,
    banner, click_and_collect, delivery

Usage:
    python -m scripts.newworld.newworld_setup --source edge --cleaned true

Flags:
    --source    "edge" (default 148 stores via Edge API) ,
                or "mobile" (legacy, 149 stores)
    --cleaned  "true" (default) drop stores without coordinates, or "false" to keep all
"""
import argparse
import cloudscraper
import json
import os
import re
import sys
import pandas as pd
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

OUTPUT_CSV = os.path.join(DATA_DIR, "newworld_stores.csv")
OUTPUT_JSON = os.path.join(DATA_DIR, "newworld_stores.json")

WEB_BASE = "https://www.newworld.co.nz"
EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"
MOBILE_BASE = "https://api-prod.prod.fsniwaikato.kiwi/prod"
EXPECTED_COLUMNS = ["store_id", "name", "address", "city", "region", "latitude", "longitude", "banner", "click_and_collect", "delivery"]


def get_website_jwt(verbose: bool = True) -> str:
    """Get website JWT (fs-user-token) via get-current-user endpoint."""
    if verbose:
        print("  Getting website JWT...")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    session.get(WEB_BASE, timeout=30)
    r = session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    r.raise_for_status()
    token = session.cookies.get("fs-user-token")
    if not token:
        raise RuntimeError("Failed to get fs-user-token cookie")
    if verbose:
        print(f"  Got JWT: {token[:30]}...")
    return token


def fetch_stores_from_edge_api(verbose: bool = True) -> pd.DataFrame:
    """
    Fetch stores from New World Edge API using website JWT.
    Returns 148 stores with store_id, name, address, city, region, coordinates.
    """
    token = get_website_jwt(verbose=verbose)

    headers = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/",
        "User-Agent": "Mozilla/5.0",
    }

    if verbose:
        print("Fetching store list from Edge API...")
    r = requests.get(f"{EDGE_BASE}/store", headers=headers, timeout=30)
    r.raise_for_status()
    stores = r.json().get("stores", [])

    store_entries = []
    for s in stores:
        phys_addr = s.get("physicalAddress", {})
        city = phys_addr.get("cityName", "") or s.get("city", "")
        region = s.get("region", "NI")

        store_entries.append({
            "store_id": s.get("id", ""),
            "name": s.get("name", ""),
            "address": s.get("address", ""),
            "city": city,
            "region": region,
            "latitude": s.get("latitude"),
            "longitude": s.get("longitude"),
            "banner": s.get("banner", "MNW"),
            "click_and_collect": s.get("clickAndCollect", False),
            "delivery": s.get("delivery", False),
        })

    df = pd.DataFrame(store_entries)
    df = df[EXPECTED_COLUMNS]

    if verbose:
        print(f"Found {len(df)} stores from Edge API")

    return df


def fetch_stores_from_mobile_api(verbose: bool = True) -> pd.DataFrame:
    """
    Fetch stores from Foodstuffs Mobile API (legacy approach).
    Returns 149 stores with store_id, name, address, coordinates, click-and-collect, delivery.
    """
    scraper = cloudscraper.create_scraper()
    r = scraper.post(
        f"{MOBILE_BASE}/mobile/user/login/guest",
        json={"banner": "MNW"},
        headers={"User-Agent": "NewWorldApp/4.32.0", "Content-Type": "application/json"},
    )
    r.raise_for_status()
    data = r.json()
    token = data["access_token"]
    auth = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "User-Agent": "NewWorldApp/4.32.0",
        "Content-Type": "application/json",
    }

    if verbose:
        print("Fetching stores from Mobile API...")
    r2 = scraper.get(f"{MOBILE_BASE}/mobile/store/physical", headers=auth, timeout=30)
    r2.raise_for_status()
    stores = r2.json()["stores"]
    nw_stores = [s for s in stores if s.get("banner") == "MNW"]

    if verbose:
        print(f"Found {len(nw_stores)} New World stores from Mobile API")

    store_entries = []
    for s in nw_stores:
        store_entries.append({
            "store_id": s.get("id", ""),
            "name": s.get("name", ""),
            "address": s.get("address", ""),
            "city": "",
            "region": "",
            "latitude": s.get("latitude"),
            "longitude": s.get("longitude"),
            "banner": s.get("banner", "MNW"),
            "click_and_collect": s.get("clickAndCollect", False),
            "delivery": s.get("delivery", False),
        })

    df = pd.DataFrame(store_entries)
    df = df[EXPECTED_COLUMNS]

    return df


def fetch_stores(source: str = "edge", verbose: bool = True) -> pd.DataFrame:
    """
    Fetch all New World stores from the specified source.

    Args:
        source: "edge" (default, 148 stores via Edge API),
                "mobile" (legacy, 149 stores via Mobile API)
        verbose: Print status messages

    Returns:
        DataFrame with store data

    Raises:
        ValueError: If source is not "edge" or "mobile"
    """
    if source == "edge":
        return fetch_stores_from_edge_api(verbose=verbose)
    if source == "mobile":
        return fetch_stores_from_mobile_api(verbose=verbose)
    raise ValueError(
        f"Invalid source: '{source}'. Choose from 'edge' or 'mobile'"
    )


def clean_stores(df: pd.DataFrame | None = None, cleaned: bool = True, verbose: bool = True) -> pd.DataFrame:
    """
    Optionally drop stores without latitude/longitude.

    Args:
        df: DataFrame from fetch_stores(). If None, reads from CSV.
        cleaned: If True (default), drop rows where lat/lon are NaN.
        verbose: Print status messages.

    Returns:
        Cleaned DataFrame.
    """
    if df is None:
        df = pd.read_csv(OUTPUT_CSV)

    if cleaned:
        before = len(df)
        df = df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
        dropped = before - len(df)
        if verbose:
            print(f"Cleaned: dropped {dropped} stores without coordinates ({len(df)} remaining)")
    else:
        if verbose:
            print(f"Keeping all {len(df)} stores (cleaned=False)")

    return df


def run_full_setup(source: str = "edge", cleaned: bool = True, verbose: bool = True) -> pd.DataFrame:
    """
    Run the complete New World store setup pipeline.

    Args:
        source: "edge" (default) or "mobile".
        cleaned: If True (default), drop stores without coordinates.
        verbose: Print status messages.

    Returns:
        Final DataFrame with store data.
    """
    if verbose:
        print("=" * 50)
        print("New World Store Setup Pipeline")
        print(f"Source: {source}")
        print("=" * 50)

    df = fetch_stores(source=source, verbose=verbose)
    df = clean_stores(df, cleaned=cleaned, verbose=verbose)

    df = _enforce_schema(df)
    df.to_csv(OUTPUT_CSV, index=False)
    df.to_json(OUTPUT_JSON, orient="records", indent=2)

    if verbose:
        print(f"\nFinal output: {OUTPUT_CSV} ({len(df)} stores)")
        print("Done.")

    return df


def _enforce_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure the DataFrame has exactly the 10 expected columns, filling missing ones with defaults."""
    for col in EXPECTED_COLUMNS:
        if col not in df.columns:
            if col == "banner":
                df[col] = "MNW"
            elif col in ("click_and_collect", "delivery"):
                df[col] = False
            else:
                df[col] = ""
    return df[EXPECTED_COLUMNS]


def _parse_cleaned(value: str) -> bool:
    """Parse the --cleaned argument into a boolean."""
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: '{value}'. Use 'true' or 'false'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="New World Store Setup Pipeline"
    )
    parser.add_argument(
        "--source",
        choices=["edge", "mobile"],
        default="edge",
        help="Data source: 'edge' (default, 148 stores via Edge API) or 'mobile' (legacy, 149 stores)",
    )
    parser.add_argument(
        "--cleaned",
        type=_parse_cleaned,
        default=True,
        help="Drop stores without coordinates: 'true' (default) or 'false'",
    )
    args = parser.parse_args()

    run_full_setup(source=args.source, cleaned=args.cleaned)
