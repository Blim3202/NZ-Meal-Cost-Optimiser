"""
Foodstuffs Unified Store Setup Pipeline

Fetches all Foodstuffs stores (Pak'nSave or New World) from either:
1. Mobile API (legacy) — 60 stores (paknsave) / 149 stores (newworld)
2. Edge API (via website JWT) — 57 stores (paknsave) / ~148 stores (newworld)
3. Store-finder page via __NEXT_DATA__ (paknsave only) — 60 stores

Note: The store-finder method is only available for Pak'nSave
(because New World's store-finder does not expose store GUIDs in
the same way).

Usage:
    from scripts.foodstuffs.Foodstuffs_setup import fetch_stores, clean_stores, run_full_setup

    # Full pipeline (default: edge, paknsave)
    run_full_setup()

    # New World stores via Edge API
    run_full_setup(brand="newworld")

    # Pak'nSave stores via store-finder
    run_full_setup(brand="paknsave", source="store_finder")

    # Mobile API (legacy) for either brand
    run_full_setup(brand="newworld", source="mobile")
    run_full_setup(brand="paknsave", source="mobile")

    # Individual steps
    stores = fetch_stores(brand="newworld", source="edge")
    stores = fetch_stores(brand="newworld", source="mobile")
    cleaned = clean_stores(stores, brand="newworld")
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
DATA_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

BRANDS = {
    "paknsave": {
        "web_base": "https://www.paknsave.co.nz",
        "edge_base": "https://api-prod.paknsave.co.nz/v1/edge",
        "mobile_base": "https://api-prod.prod.fsniwaikato.kiwi/prod",
        "store_finder_url": "https://www.paknsave.co.nz/store-finder",
        "stores_csv": os.path.join(DATA_DIR, "paknsave_stores.csv"),
        "stores_json": os.path.join(DATA_DIR, "paknsave_stores.json"),
        "banner": "PNS",
        "user_agent": "PAKnSAVEApp/4.32.0",
        "sources": ["edge", "mobile", "store_finder"],
    },
    "newworld": {
        "web_base": "https://www.newworld.co.nz",
        "edge_base": "https://api-prod.newworld.co.nz/v1/edge",
        "mobile_base": "https://api-prod.prod.fsniwaikato.kiwi/prod",
        "stores_csv": os.path.join(DATA_DIR, "newworld_stores.csv"),
        "stores_json": os.path.join(DATA_DIR, "newworld_stores.json"),
        "banner": "MNW",
        "user_agent": "NewWorldApp/4.32.0",
        "sources": ["edge", "mobile"],
    },
}


def get_website_jwt(brand="paknsave", verbose=True):
    web_base = BRANDS[brand]["web_base"]
    if verbose:
        print("  Getting website JWT...")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": web_base,
        "Referer": web_base + "/",
    })
    session.get(web_base, timeout=30)
    r = session.post(f"{web_base}/api/user/get-current-user", json={}, timeout=30)
    r.raise_for_status()
    token = session.cookies.get("fs-user-token")
    if not token:
        raise RuntimeError("Failed to get fs-user-token cookie")
    if verbose:
        print(f"  Got JWT: {token[:30]}...")
    return token


def fetch_stores_from_store_finder(brand="paknsave", verbose=True):
    cfg = BRANDS[brand]
    sys.stdout.reconfigure(encoding="utf-8")

    scraper = cloudscraper.create_scraper()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0"}

    if verbose:
        print(f"Fetching store-finder page __NEXT_DATA__ for {brand}...")
    r = scraper.get(cfg["store_finder_url"], headers=headers)

    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        r.text,
        re.DOTALL,
    )
    if not match:
        raise SystemExit("Could not find __NEXT_DATA__")

    data = json.loads(match.group(1))
    page_props = data["props"]["pageProps"]

    cs_stores = page_props.get("contentstackStores", [])
    url_to_store_id = {}
    for item in cs_stores:
        url = item.get("url", "")
        store_id = item.get("store_id", "")
        if url and store_id:
            url_to_store_id[url] = store_id

    if verbose:
        print(f"Loaded {len(url_to_store_id)} store_id mappings from contentstackStores")

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


def fetch_stores_from_mobile_api(brand="paknsave", verbose=True):
    cfg = BRANDS[brand]
    scraper = cloudscraper.create_scraper()

    if verbose:
        print(f"Fetching stores from Mobile API for {brand}...")
    r = scraper.post(
        f"{cfg['mobile_base']}/mobile/user/login/guest",
        json={"banner": cfg["banner"]},
        headers={"User-Agent": cfg["user_agent"], "Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    token = data["access_token"]
    auth = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "User-Agent": cfg["user_agent"],
        "Content-Type": "application/json",
    }

    r2 = scraper.get(
        f"{cfg['mobile_base']}/mobile/store/physical", headers=auth, timeout=30
    )
    r2.raise_for_status()
    stores = r2.json()["stores"]

    store_entries = []
    for s in stores:
        store_entries.append(
            {
                "store_id": s.get("id", ""),
                "name": s.get("name", ""),
                "address": s.get("address", ""),
                "city": "",
                "region": "",
                "latitude": s.get("latitude"),
                "longitude": s.get("longitude"),
            }
        )

    df = pd.DataFrame(store_entries)
    df = df[["store_id", "name", "address", "city", "region", "latitude", "longitude"]]

    if verbose:
        print(f"Found {len(df)} stores from Mobile API")

    return df


def fetch_stores_from_edge_api(brand="paknsave", verbose=True):
    token = get_website_jwt(brand=brand, verbose=verbose)
    cfg = BRANDS[brand]

    headers = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": cfg["web_base"],
        "Referer": f"{cfg['web_base']}/",
        "User-Agent": "Mozilla/5.0",
    }

    if verbose:
        print(f"Fetching store list from Edge API for {brand}...")
    r = requests.get(f"{cfg['edge_base']}/store", headers=headers, timeout=30)
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
        })

    df = pd.DataFrame(store_entries)
    df = df[["store_id", "name", "address", "city", "region", "latitude", "longitude"]]

    if verbose:
        print(f"Found {len(df)} stores from Edge API")

    return df


def fetch_stores(brand="paknsave", source="edge", verbose=True):
    cfg = BRANDS[brand]
    if source not in cfg["sources"]:
        valid = ", ".join(cfg["sources"])
        raise ValueError(
            f"Invalid source '{source}' for brand '{brand}'. Valid sources: {valid}"
        )
    if source == "edge":
        return fetch_stores_from_edge_api(brand=brand, verbose=verbose)
    if source == "mobile":
        return fetch_stores_from_mobile_api(brand=brand, verbose=verbose)
    if source == "store_finder":
        return fetch_stores_from_store_finder(brand=brand, verbose=verbose)


def clean_stores(df=None, brand="paknsave", cleaned=True, verbose=True):
    cfg = BRANDS[brand]
    if df is None:
        csv_path = cfg["stores_csv"]
        df = pd.read_csv(csv_path)

    if cleaned:
        before = len(df)
        df = df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
        dropped = before - len(df)
        if verbose:
            print(f"Cleaned: dropped {dropped} stores without coordinates ({len(df)} remaining)")
    else:
        if verbose:
            print(f"Keeping all {len(df)} stores (cleaned=False)")

    df = df[["store_id", "name", "address", "city", "region", "latitude", "longitude"]]
    return df


def run_full_setup(brand="paknsave", source="edge", cleaned=True, verbose=True):
    cfg = BRANDS[brand]
    if verbose:
        print("=" * 50)
        print(f"Foodstuffs {brand.title()} Store Setup Pipeline")
        print(f"Source: {source}")
        print("=" * 50)

    df = fetch_stores(brand=brand, source=source, verbose=verbose)
    df = clean_stores(df, brand=brand, cleaned=cleaned, verbose=verbose)

    csv_path = cfg["stores_csv"]
    json_path = cfg["stores_json"]
    df.to_csv(csv_path, index=False)
    df.to_json(json_path, orient="records", indent=2)

    if verbose:
        print(f"\nFinal output: {csv_path} ({len(df)} stores)")
        print("Done.")

    return df


if __name__ == "__main__":
    brand = sys.argv[1] if len(sys.argv) > 1 else "paknsave"
    # brand = sys.argv[1] if len(sys.argv) > 1 else "newworld"
    source = sys.argv[2] if len(sys.argv) > 2 else "edge"
    # source = sys.argv[2] if len(sys.argv) > 2 else "mobile"
    # source = sys.argv[2] if len(sys.argv) > 2 else "storefinder"
    run_full_setup(brand=brand, source=source)