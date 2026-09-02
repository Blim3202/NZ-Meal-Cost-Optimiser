"""
Pak'nSave Edge API - Two-Pass Pipeline Demo
===========================================
Demonstrates the complete two-pass pipeline for Pak'nSave:
- PASS 1: Relevance matching via Algolia products-index (with _highlightResult.matchedWords)
- PASS 2: Per-store pricing via paginated/products with Algolia filters + PRICE_ASC sort

This is the same architecture proven for New World Edge API, now applied to Pak'nSave.
Both chains share the same Foodstuffs backend (api-prod.paknsave.co.nz / api-prod.newworld.co.nz).
"""

import requests
import time
from pathlib import Path

from NZMealOptimiser.pricing.optimiser_utils import DISHES, get_ingredients

WEB_BASE = "https://www.paknsave.co.nz"
EDGE_BASE = "https://api-prod.paknsave.co.nz/v1/edge"


def get_website_session():
    """Get website JWT (fs-user-token) - same flow as New World."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    session.get(WEB_BASE, timeout=30)
    session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    return session.cookies.get("fs-user-token")


def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0",
    }


def get_store_cookies(store_id):
    return {
        "eCom_STORE_ID": store_id,
        "STORE_ID_V2": f"{store_id}|False",
        "Region": "NI",
    }


def pass1_relevance_search(token, store_id, query, max_relevance=20):
    """
    PASS 1: Algolia relevance search.
    Returns productIDs with non-empty _highlightResult.matchedWords.
    Filters out pet food categories (Dog, Cat, Pet) using category1 field.
    """
    headers = get_headers(token)
    cookies = get_store_cookies(store_id)
    payload = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": max_relevance,
        "storeId": store_id,
    }
    r = requests.post(
        f"{EDGE_BASE}/search/products/query/index/products-index",
        headers=headers, json=payload, cookies=cookies, timeout=30
    )
    r.raise_for_status()
    hits = r.json().get("hits", [])

    pet_categories = {"Dog", "Cat", "Pet"}
    product_ids = []
    for h in hits:
        hr = h.get("_highlightResult", {})
        matched = [f for f, v in hr.items() if isinstance(v, dict) and v.get("matchedWords")]
        cat1 = h.get("category1", [])
        if matched and not any(c in pet_categories for c in cat1):
            product_ids.append(h["productID"])
    return product_ids


def pass2_per_store_pricing(token, store_id, query, product_ids, hits_per_page=50):
    """
    PASS 2: Per-store pricing for exactly the relevant products from Pass 1.
    Uses Algolia filter syntax: productID:xxx OR productID:yyy
    Sorts by PRICE_ASC to get cheapest at this store.
    """
    if not product_ids:
        return []

    headers = get_headers(token)
    cookies = get_store_cookies(store_id)
    filter_str = " OR ".join([f"productID:{pid}" for pid in product_ids])
    payload = {
        "algoliaQuery": {"query": query, "filters": filter_str},
        "page": 0,
        "hitsPerPage": hits_per_page,
        "storeId": store_id,
        "sortOrder": "PRICE_ASC",
    }
    r = requests.post(
        f"{EDGE_BASE}/search/paginated/products",
        headers=headers, json=payload, cookies=cookies, timeout=30
    )
    r.raise_for_status()
    return r.json().get("products", [])


def two_pass_search(token, store_id, query, max_relevance=20):
    """Complete two-pass pipeline."""
    product_ids = pass1_relevance_search(token, store_id, query, max_relevance)
    return pass2_per_store_pricing(token, store_id, query, product_ids)


def extract_price(product):
    """Extract final price (promo if available, else regular) in dollars."""
    sp = product.get("singlePrice", {})
    price = sp.get("price")
    promo = product.get("promotions", [])
    promo_val = promo[0].get("rewardValue") if promo else None
    final_cents = promo_val if promo_val is not None else price
    return final_cents / 100 if final_cents else None


def get_stores(token):
    headers = get_headers(token)
    r = requests.get(f"{EDGE_BASE}/store", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json().get("stores", [])


def haversine(lat1, lon1, lat2, lon2):
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def geocode(address):
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        headers={"User-Agent": "NZMealCostOptimiser/1.0"},
        params={"q": address, "format": "json", "limit": 1},
        timeout=30
    )
    if r.status_code == 200 and r.json():
        loc = r.json()[0]
        return float(loc["lat"]), float(loc["lon"])
    return None, None


def find_nearby(user_lat, user_lon, stores, radius_km=5):
    nearby = []
    for s in stores:
        d = haversine(user_lat, user_lon, s["latitude"], s["longitude"])
        if d <= radius_km:
            nearby.append({**s, "distance_km": d})
    nearby.sort(key=lambda x: x["distance_km"])
    return nearby


def main():
    print("=" * 70)
    print("Pak'nSave Edge API - Two-Pass Pipeline Proof of Concept")
    print("=" * 70)

    # Auth
    print("\n[1] Getting website JWT...")
    token = get_website_session()
    print(f"    Got token: {token[:30]}...")

    # Store listing
    print("\n[2] Fetching store list...")
    stores = get_stores(token)
    print(f"    Found {len(stores)} stores")

    # Test address: Botany, Auckland
    address = "Botany, Auckland"
    print(f"\n[3] Geocoding '{address}'...")
    user_lat, user_lon = geocode(address)
    print(f"    Coordinates: {user_lat}, {user_lon}")

    # Nearby stores
    print("\n[4] Finding nearby stores (5km radius)...")
    nearby = find_nearby(user_lat, user_lon, stores, radius_km=5)
    print(f"    Found {len(nearby)} nearby stores:")
    for s in nearby[:5]:
        print(f"      {s['name']} - {s['distance_km']:.1f} km")

    # Test dish
    dish = "spaghetti bolognese"
    ingredients = get_ingredients(dish)
    print(f"\n[5] Optimising dish: {dish}")
    print(f"    Ingredients: {ingredients}")

    # Test two-pass for each ingredient at each store
    results = []
    for store in nearby[:3]:
        store_id = store["id"]
        store_name = store["name"]
        print(f"\n  --- {store_name} ---")
        total = 0.0
        for ing in ingredients:
            products = two_pass_search(token, store_id, ing, max_relevance=20)
            if products:
                cheapest = min(products, key=lambda p: extract_price(p) or 9999)
                price = extract_price(cheapest)
                name = cheapest.get("name", "")
                size = cheapest.get("displayName", "")
                print(f"    {ing:25s} ${price:.2f}  ({name} {size})")
                total += price
            else:
                print(f"    {ing:25s} NOT FOUND")
            time.sleep(0.1)
        print(f"    {'TOTAL':25s} ${total:.2f}")
        results.append((store_name, total, store["distance_km"]))

    # Summary
    results.sort(key=lambda x: x[1])
    print("\n" + "=" * 70)
    print("COST COMPARISON")
    print("=" * 70)
    for i, (name, total, dist) in enumerate(results):
        print(f"  {i+1}. {name:30s} ${total:.2f}  ({dist:.1f} km)")
    print("=" * 70)

    # Demonstrate Pass 1 detail for one ingredient
    print("\n[6] PASS 1 Detail (beef mince at first store):")
    store_id = nearby[0]["id"]
    product_ids = pass1_relevance_search(token, store_id, "beef mince", max_relevance=20)
    print(f"    Relevant product IDs found: {len(product_ids)}")
    for pid in product_ids[:10]:
        print(f"      {pid}")

    print("\n[7] PASS 2 Pricing for those IDs (sorted PRICE_ASC):")
    products = pass2_per_store_pricing(token, store_id, "beef mince", product_ids)
    for p in products[:8]:
        price = extract_price(p)
        name = p.get("name", "")
        size = p.get("displayName", "")
        promo = p.get("promotions", [])
        promo_str = f" (PROMO: ${promo[0]['rewardValue']/100:.2f})" if promo else ""
        print(f"      ${price:.2f}  {name} {size}{promo_str}")


if __name__ == "__main__":
    main()