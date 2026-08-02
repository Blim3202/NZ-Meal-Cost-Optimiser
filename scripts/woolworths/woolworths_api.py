"""
Woolworths NZ API Module
========================
Provides functions for interacting with the Woolworths NZ (Countdown) backend API.

The API is hosted at shop.countdown.co.nz and serves Woolworths NZ product data.
Per-store pricing is achieved by injecting a cw-lrkswrdjp cookie constructed from
the store's fulfilmentStoreId (available in data/woolworths_store_data.json as extra1).

Key functions:
    create_session()            - Create a seeded requests.Session with required headers
    set_store_context()         - Inject per-store cookie for pricing
    search_products()           - Keyword search against the product catalogue
    find_cheapest()             - Search and return the lowest-priced result
    get_nearby_stores()         - Haversine distance filter on store coordinates
    geocode()                   - Nominatim geocoding for NZ addresses

Data files:
    data/woolworths_store_data.json  - Store details with extra1 (fulfilmentStoreId)
                                       and extra2 (pickupAddressId)

Reference: Woolworths_API.md (1290+ lines of endpoint documentation)
"""

import json
import requests
import time
import os
from pathlib import Path

BASE_URL = "https://www.woolworths.co.nz/api/v1"
SITE_URL = "https://www.woolworths.co.nz/"

HEADERS = {
    "x-requested-with": "??",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-NZ,en;q=0.9",
    "Referer": "https://www.woolworths.co.nz/",
}

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# Department IDs for non-food categories (excluded when food_only=True)
# Source: /api/v1/shell → mainNavs[1] → Browse departments
NON_FOOD_DEPARTMENT_IDS = {10, 11, 12, 13, 14}
# 10 = Health & Body, 11 = Household, 12 = Baby & Child,
# 13 = Pet, 14 = Back to School


def is_food_department(product):
    """Check if a product belongs to a food department.

    Args:
        product: raw product dict from the API (must contain 'departments' key)

    Returns:
        True if the product is in a food department, False otherwise.
        Products with no department info are included (assumed food).
    """
    depts = product.get("departments", [])
    if not depts:
        return True
    dept_ids = {d.get("id") for d in depts if "id" in d}
    return not dept_ids.intersection(NON_FOOD_DEPARTMENT_IDS)


def _load_store_mapping():
    """Load fulfilmentStoreId mapping from woolworths_store_data.json.

    Returns dict: {pickupAddressId (str): {fulfilmentStoreId (int), name (str)}}
    """
    store_data_path = DATA_DIR / "woolworths_store_data.json"
    if not store_data_path.exists():
        raise FileNotFoundError(f"Store data not found: {store_data_path}")

    with open(store_data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    mapping = {}
    for detail in data.get("siteDetail", []):
        site = detail.get("site", {})
        extra1 = site.get("extra1")
        extra2 = site.get("extra2")
        name = site.get("name", "")
        lat = site.get("latitude")
        lon = site.get("longitude")

        if extra1 and extra2 and str(extra1) != "null" and str(extra2) != "null":
            mapping[str(extra2)] = {
                "fulfilmentStoreId": int(extra1),
                "name": name,
                "lat": lat,
                "lon": lon,
            }
    return mapping


STORE_MAPPING = None


def get_store_mapping():
    """Return the store mapping, loading it once on first call."""
    global STORE_MAPPING
    if STORE_MAPPING is None:
        STORE_MAPPING = _load_store_mapping()
    return STORE_MAPPING


def create_session():
    """Create a requests.Session with Woolworths headers and seed cookies."""
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(SITE_URL, timeout=15)
    return session


def set_store_context(session, pickup_address_id):
    """Set per-store pricing by injecting the cw-lrkswrdjp cookie.

    Args:
        session: requests.Session (must already have baseline cookies from create_session)
        pickup_address_id: str or int — the store's pickupAddressId from pickup-addresses API

    Returns:
        dict with fulfilmentStoreId, method, storeName

    Raises:
        ValueError: if store not found in mapping
        RuntimeError: if cookie injection didn't take effect
    """
    mapping = get_store_mapping()
    store = mapping.get(str(pickup_address_id))
    if not store:
        raise ValueError(f"Store {pickup_address_id} not in mapping")

    fsid = store["fulfilmentStoreId"]
    cookie_val = f"dm-Pickup,f-{fsid},s-38"
    session.cookies.set("cw-lrkswrdjp", cookie_val, domain="www.woolworths.co.nz", path="/")

    # Validate via shell
    resp = session.get(f"{BASE_URL}/shell", timeout=15)
    shell = resp.json()
    fulf = shell.get("context", {}).get("fulfilment", {})
    if fulf.get("fulfilmentStoreId") == 9171:
        raise RuntimeError(
            f"Cookie not accepted — shell still shows default store 9171. "
            f"Expected fulfilmentStoreId {fsid}."
        )

    return {
        "fulfilmentStoreId": fulf.get("fulfilmentStoreId"),
        "method": fulf.get("method"),
        "storeName": store["name"],
    }


def search_products(session, query, size=20, food_only=False):
    """Search for products with the current store context.

    Args:
        session: requests.Session with store context set
        query: search term (e.g. "milk", "beef mince")
        size: max results to return
        food_only: if True, exclude non-food departments
                   (Health & Body, Household, Baby & Child, Pet, Back to School)

    Returns list of product dicts with keys: sku, name, salePrice, originalPrice,
    isSpecial, unitPrice, volumeSize, cupMeasure, url, imageUrl, departments.
    """
    resp = session.get(
        f"{BASE_URL}/products",
        params={"target": "search", "search": query, "size": size},
        timeout=15,
    )
    data = resp.json()
    items = data.get("products", {}).get("items", [])
    results = []
    for item in items:
        if food_only and not is_food_department(item):
            continue
        price_info = item.get("price", {})
        size_info = item.get("size", {})
        departments = item.get("departments", [])
        dept_name = departments[0].get("name", "") if departments else ""
        results.append({
            "sku": item.get("sku"),
            "name": item.get("name", ""),
            "salePrice": price_info.get("salePrice"),
            "originalPrice": price_info.get("originalPrice"),
            "isSpecial": price_info.get("isSpecial", False),
            "unitPrice": size_info.get("cupPrice", ""),
            "volumeSize": size_info.get("volumeSize", ""),
            "cupMeasure": size_info.get("cupMeasure", ""),
            "cupListPrice": size_info.get("cupListPrice", ""),
            "url": item.get("url", ""),
            "imageUrl": item.get("imageUrl", ""),
            "department": dept_name,
        })
    return results


def find_cheapest(session, query, size=20, food_only=False):
    """Search and return the cheapest product for a query.

    Args:
        session: requests.Session with store context set
        query: search term
        size: max results to consider
        food_only: if True, exclude non-food departments

    Returns dict with product info and price, or None if nothing found.
    """
    products = search_products(session, query, size=size, food_only=food_only)
    if not products:
        return None

    priced = [p for p in products if p["salePrice"] is not None]
    if not priced:
        return None

    cheapest = min(priced, key=lambda p: p["salePrice"])
    return cheapest


def get_nearby_stores(user_lat, user_lon, max_dist_km=5):
    """Return stores within max_dist_km, sorted by distance.

    Returns list of dicts: {pickupAddressId, name, fulfilmentStoreId, lat, lon, distance_km}
    """
    import math

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        return R * 2 * math.asin(math.sqrt(a))

    mapping = get_store_mapping()
    nearby = []
    for pid, info in mapping.items():
        if info["lat"] is None or info["lon"] is None:
            continue
        dist = haversine(user_lat, user_lon, info["lat"], info["lon"])
        if dist <= max_dist_km:
            nearby.append({
                "pickupAddressId": pid,
                "name": info["name"],
                "fulfilmentStoreId": info["fulfilmentStoreId"],
                "lat": info["lat"],
                "lon": info["lon"],
                "distance_km": round(dist, 2),
            })
    nearby.sort(key=lambda s: s["distance_km"])
    return nearby


def geocode(address):
    """Geocode a NZ address via Nominatim. Returns (lat, lon) or (None, None)."""
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        headers={"User-Agent": "NZMealCostOptimizer/1.0"},
        params={"q": address, "format": "json", "limit": 1},
    )
    if r.status_code == 200 and r.json():
        loc = r.json()[0]
        return float(loc["lat"]), float(loc["lon"])
    return None, None
