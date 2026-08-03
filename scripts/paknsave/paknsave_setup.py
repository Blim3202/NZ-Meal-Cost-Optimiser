"""
Pak'nSave Unified Store Setup Pipeline

Fetches all Pak'nSave stores from either:
1. Website store-finder page (via __NEXT_DATA__) — 60 stores, GUIDs, coordinates
2. Edge API (via website JWT) — 57 stores, coordinates (3 stores not configured for Edge API)
3. Mobile API (legacy) — 60 stores, coordinates, click-and-collect, delivery

Usage:
    from scripts.paknsave.paknsave_setup import fetch_stores, clean_stores, run_full_setup

    # Full pipeline (default: edge)
    run_full_setup()

    # Edge API source
    run_full_setup(source="edge")

    # Mobile API source (legacy fallback)
    run_full_setup(source="mobile")

    # Store-finder page source
    run_full_setup(source="store_finder")

    # Individual steps
    fetch_stores(source="mobile")
    clean_stores(cleaned=True)
"""
import cloudscraper
import json
import re
import os
import sys
import pandas as pd
import requests

# Data directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..', 'data'))
os.makedirs(DATA_DIR, exist_ok=True)

OUTPUT_CSV = os.path.join(DATA_DIR, "paknsave_stores.csv")
OUTPUT_JSON = os.path.join(DATA_DIR, "paknsave_stores.json")

WEB_BASE = "https://www.paknsave.co.nz"
EDGE_BASE = "https://api-prod.paknsave.co.nz/v1/edge"
MOBILE_BASE = "https://api-prod.prod.fsniwaikato.kiwi/prod"


def _configure_stdout_utf8() -> None:
    """Best-effort stdout UTF-8 configuration for console use.

    Safe to call when this module is imported, because we only touch the
    stream if it actually exposes a reconfigure() method.
    """
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


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


def fetch_stores_from_store_finder(verbose: bool = True) -> pd.DataFrame:
    """
    Fetch stores from store-finder page __NEXT_DATA__.
    Returns 60 stores with GUID, name, address, city, region, lat, lon.
    """
    _configure_stdout_utf8()

    scraper = cloudscraper.create_scraper()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0"}

    if verbose:
        print("Fetching store-finder page __NEXT_DATA__...")
    r = scraper.get("https://www.paknsave.co.nz/store-finder", headers=headers)

    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        r.text,
        re.DOTALL,
    )
    if not match:
        raise SystemExit("Could not find __NEXT_DATA__")

    data = json.loads(match.group(1))
    page_props = data["props"]["pageProps"]

    # Step 1: Build url → store_id map from contentstackStores
    cs_stores = page_props.get("contentstackStores", [])
    url_to_store_id = {}
    for item in cs_stores:
        url = item.get("url", "")
        store_id = item.get("store_id", "")
        if url and store_id:
            url_to_store_id[url] = store_id

    if verbose:
        print(f"Loaded {len(url_to_store_id)} store_id mappings from contentstackStores")

    # Step 2: Extract store details from store_finder.regionStoreGroupings
    page = page_props.get("page", {})
    content_blocks = page.get("page_content", {}).get("content_blocks", [])
    store_finder_block = next(
        (b for b in content_blocks if "store_finder" in b),
        {},
    )
    store_finder = store_finder_block.get("store_finder", {})
    region_groupings = store_finder.get("regionStoreGroupings", {})

    store_entries = []
    for island_key, region_label in [("northIsland", "NI"), ("southIsland", "SI")]:
        groups = region_groupings.get(island_key, [])
        for group in groups:
            stores = group.get("stores", [])
            for store in stores:
                title = store.get("title", "")
                url = store.get("url", "")
                address = store.get("address", "")
                contact = store.get("contactDetails") or {}
                latitude = contact.get("latitude")
                longitude = contact.get("longitude")

                store_id = url_to_store_id.get(url, "")

                city = address.split(",")[0].strip() if address else ""

                store_entries.append({
                    "store_id": store_id,
                    "name": title,
                    "address": address,
                    "city": city,
                    "region": region_label,
                    "latitude": latitude,
                    "longitude": longitude,
                })

    df = pd.DataFrame(store_entries)
    df = df[["store_id", "name", "address", "city", "region", "latitude", "longitude"]]

    if verbose:
        print(f"Found {len(df)} stores from regionStoreGroupings")

    return df


def fetch_stores_from_edge_api(verbose: bool = True) -> pd.DataFrame:
    """
    Fetch stores from Edge API using website JWT.
    Returns 57 stores with coordinates (3 stores not configured for Edge API, In store only. Wairau, Gisborne, Levin).
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
        # Use physicalAddress for city/region if available, else fall back to top-level fields
        phys_addr = s.get("physicalAddress", {})
        city = phys_addr.get("cityName", "") or s.get("city", "")
        region = s.get("region", "NI")  # 'NI' or 'SI'

        store_entries.append({
            "store_id": s.get("id", ""),
            "name": s.get("name", ""),
            "address": s.get("address", ""),
            "city": city,
            "region": region,
            "latitude": s.get("latitude"),
            "longitude": s.get("longitude"),
        })

    df = pd.DataFrame(store_entries)
    df = df[["store_id", "name", "address", "city", "region", "latitude", "longitude"]]

    if verbose:
        print(f"Found {len(df)} stores from Edge API")

    return df


def fetch_stores_from_mobile_api(verbose: bool = True) -> pd.DataFrame:
    """
    Fetch stores from Foodstuffs Mobile API (legacy approach).
    Returns 60 stores with store_id, name, address, coordinates.
    """
    scraper = cloudscraper.create_scraper()
    r = scraper.post(
        f"{MOBILE_BASE}/mobile/user/login/guest",
        json={"banner": "PNS"},
        headers={"User-Agent": "PAKnSAVEApp/4.32.0", "Content-Type": "application/json"},
    )
    r.raise_for_status()
    data = r.json()
    token = data["access_token"]
    auth = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "User-Agent": "PAKnSAVEApp/4.32.0",
        "Content-Type": "application/json",
    }

    if verbose:
        print("Fetching stores from Mobile API...")
    r2 = scraper.get(f"{MOBILE_BASE}/mobile/store/physical", headers=auth, timeout=30)
    r2.raise_for_status()
    stores = r2.json()["stores"]

    if verbose:
        print(f"Found {len(stores)} stores from Mobile API")

    store_entries = []
    for s in stores:
        store_entries.append({
            "store_id": s.get("id", ""),
            "name": s.get("name", ""),
            "address": s.get("address", ""),
            "city": "",
            "region": "",
            "latitude": s.get("latitude"),
            "longitude": s.get("longitude"),
        })

    df = pd.DataFrame(store_entries)
    df = df[["store_id", "name", "address", "city", "region", "latitude", "longitude"]]

    return df


def fetch_stores(source: str = "edge", verbose: bool = True) -> pd.DataFrame:
    """
    Fetch all Pak'nSave stores.

    Args:
        source: "edge" (default, 57 stores via Edge API),
                "mobile" (legacy, 60 stores via Mobile API),
                "store_finder" (website __NEXT_DATA__, 60 stores with store IDs)
        verbose: Print status messages

    Returns:
        DataFrame with store data

    Raises:
        ValueError: If source is not "edge", "mobile", or "store_finder"
    """
    if source == "edge":
        return fetch_stores_from_edge_api(verbose=verbose)
    if source == "mobile":
        return fetch_stores_from_mobile_api(verbose=verbose)
    if source == "store_finder":
        return fetch_stores_from_store_finder(verbose=verbose)
    raise ValueError(
        f"Invalid source: '{source}'. Choose from 'edge', 'mobile', or 'store_finder'"
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
    Run the complete Pak'nSave store setup pipeline.

    Args:
        source: "store_finder" (60 stores), "edge" (default, 57 stores), or "mobile" (60 stores).
        cleaned: If True (default), drop stores without coordinates.
        verbose: Print status messages.

    Returns:
        Final DataFrame with store data.
    """
    if verbose:
        print("=" * 50)
        print("Pak'nSave Store Setup Pipeline")
        print(f"Source: {source}")
        print("=" * 50)

    df = fetch_stores(source=source, verbose=verbose)
    df = clean_stores(df, cleaned=cleaned, verbose=verbose)

    # Overwrite final output
    df.to_csv(OUTPUT_CSV, index=False)
    df.to_json(OUTPUT_JSON, orient="records", indent=2)

    if verbose:
        print(f"\nFinal output: {OUTPUT_CSV} ({len(df)} stores)")
        print("Done.")

    return df


if __name__ == "__main__":
    import sys
    source = sys.argv[1] if len(sys.argv) > 1 else "edge"
    # source = sys.argv[1] if len(sys.argv) > 1 else "store_finder"
    # source = sys.argv[1] if len(sys.argv) > 1 else "mobile"
    run_full_setup(source=source)