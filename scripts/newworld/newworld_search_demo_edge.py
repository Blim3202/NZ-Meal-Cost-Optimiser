"""
New World NZ Product Search Demo — EDGE API (Two-Pass)
=========================================================
Example script demonstrating two-pass product search via the New World Edge API.
Searches for a given ingredient at New World Albany and prints the top 10 results
with pricing details.

What it does:
    1. Authenticates via website JWT (fs-user-token cookie)
    2. Runs Pass 1: relevance search via products-index (returns productIDs)
    3. Runs Pass 2: per-store pricing via paginated/products (PRICE_ASC)
    4. Prints top 10 results with pricing, unit price, and category1
    5. Dumps raw JSON for the first product

Store info:
    Name:       New World Albany
    Store ID:   773ad0a0-024e-46c5-a94b-df1cf86d25cc

Usage:
    python scripts/newworld/newworld_search_demo_edge.py [ingredient]
    python scripts/newworld/newworld_search_demo_edge.py "milk"

Reference: NewWorld_API.md section 6 (Edge API two-pass pipeline)
"""

import argparse
import json
import requests
import sys

WEB_BASE = "https://www.newworld.co.nz"
EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"

STORE_NAME = "New World Albany"
STORE_ID = "773ad0a0-024e-46c5-a94b-df1cf86d25cc"

NON_FOOD_CATEGORIES = {
    "Dog", "Cat", "Pet Health & Accessories", "Birds, Fish & Small Animals",
    "Baby & Toddler Food", "Baby & Toddler Toiletries", "Baby Formula",
    "Baby Wipes", "Nappies & Changing", "Nursing & Feeding",
    "Cleaning & Accessories", "Dishwashing", "Bathroom & Toilet Cleaners",
    "Kitchen Cleaners", "Laundry", "Food Wrap, Storage & Bags",
    "Pest & Insect Control", "Homewares",
    "Bath, Shower & Soap", "Dental & Oral Care", "Deodorant & Body Sprays",
    "Hair Care", "Make Up & Nail Care", "Medical & First Aid",
    "Period & Continence Care", "Shaving & Hair Removal", "Skin Care & Sun Care",
    "Tissues & Cotton Wool", "Toilet Paper, Tissues & Paper Towels",
    "Vitamins & Supplements",
    "Stationery & Entertainment", "Clothing & Accessories",
    "Garage & Outdoor", "Batteries & Electrical",
}


def authenticate(session):
    session.get(WEB_BASE, timeout=30)
    r = session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    r.raise_for_status()
    token = session.cookies.get("fs-user-token")
    if not token:
        print("ERROR: Failed to obtain fs-user-token cookie")
        sys.exit(1)
    return token


def auth_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0",
    }


def store_cookies(store_id, region="NI"):
    return {
        "eCom_STORE_ID": store_id,
        "STORE_ID_V2": f"{store_id}|False",
        "Region": region,
    }


def pass1_relevance_search(token, store_id, query, max_hits=20):
    headers = auth_headers(token)
    cookies = store_cookies(store_id)
    payload = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": max_hits,
        "storeId": store_id,
    }
    r = requests.post(
        f"{EDGE_BASE}/search/products/query/index/products-index",
        headers=headers,
        json=payload,
        cookies=cookies,
        timeout=30,
    )
    r.raise_for_status()
    hits = r.json().get("hits", [])

    product_ids = []
    raw_hits = []
    for h in hits:
        hr = h.get("_highlightResult", {})
        matched = any(
            isinstance(v, dict) and v.get("matchedWords")
            for v in hr.values()
        )
        cat1 = h.get("category1", [])
        if matched and not any(c in NON_FOOD_CATEGORIES for c in cat1):
            product_ids.append(h["productID"])
            raw_hits.append(h)
    return product_ids, raw_hits


def pass2_per_store_pricing(token, store_id, query, product_ids, hits_per_page=10):
    if not product_ids:
        return []
    headers = auth_headers(token)
    cookies = store_cookies(store_id)
    filter_str = " OR ".join(f"productID:{pid}" for pid in product_ids)
    payload = {
        "algoliaQuery": {"query": query, "filters": filter_str},
        "page": 0,
        "hitsPerPage": hits_per_page,
        "storeId": store_id,
        "sortOrder": "PRICE_ASC",
    }
    r = requests.post(
        f"{EDGE_BASE}/search/paginated/products",
        headers=headers,
        json=payload,
        cookies=cookies,
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("products", [])


def extract_price(product):
    sp = product.get("singlePrice", {})
    price_cents = sp.get("price")
    promo = product.get("promotions", [])
    promo_val = promo[0].get("rewardValue") if promo else None
    final_cents = promo_val if promo_val is not None else price_cents
    return final_cents / 100.0 if final_cents else None


def main():
    parser = argparse.ArgumentParser(
        description="New World Edge API product search demo (two-pass pipeline).",
        epilog="Example: python newworld_search_demo_edge.py 'milk'",
    )
    parser.add_argument(
        "ingredient",
        nargs="?",
        default="milk",
        help="Ingredient to search for (default: 'milk')",
    )
    args = parser.parse_args()
    query = args.ingredient

    print(f"=== New World Product Search Demo (EDGE API) ===")
    print(f"Store: {STORE_NAME} ({STORE_ID})")
    print()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    print("Step 1: Authenticating...")
    token = authenticate(session)
    print(f"  JWT: {token[:40]}...")
    print()

    print(f"Step 2: Pass 1 — Relevance search for '{query}'")
    product_ids, raw_hits = pass1_relevance_search(token, STORE_ID, query, max_hits=20)
    print(f"  Matched productIDs: {len(product_ids)}")
    print()

    print(f"Step 3: Pass 2 — Per-store pricing (PRICE_ASC)")
    products = pass2_per_store_pricing(token, STORE_ID, query, product_ids, hits_per_page=10)
    print(f"  Products with pricing: {len(products)}")
    print()

    print(f"Top 10 results for '{query}' at {STORE_NAME}:")
    print("=" * 80)
    for i, prod in enumerate(products[:10], 1):
        name = prod.get("name") or prod.get("displayName") or ""
        size = prod.get("displayName") or prod.get("size") or ""
        cat1 = prod.get("category1", [])
        cat_trees = prod.get("categoryTrees", [])
        price = extract_price(prod)
        sp = prod.get("singlePrice", {})
        unit_price = sp.get("unitPrice") or sp.get("pricePerUnit") or ""
        promo = prod.get("promotions", [])
        promo_price = promo[0].get("rewardValue") / 100.0 if promo and promo[0].get("rewardValue") else None

        price_str = f"${price:.2f}" if price is not None else "N/A"
        if promo_price is not None and promo_price != price:
            price_str += f" (was ${prod.get('singlePrice', {}).get('price', 0) / 100.0:.2f})"

        print(f"{i:>2}. {name}")
        print(f"    Size: {size}")
        print(f"    Category1: {', '.join(cat1) if cat1 else '(none)'}")
        print(f"    CategoryTree: {cat_trees if cat_trees else '(none)'}")
        print(f"    Price: {price_str}  |  Unit: {unit_price}")
        print()

    if raw_hits:
        print("=" * 80)
        print("RAW JSON for first Pass 1 relevance hit:")
        print(json.dumps(raw_hits[0], indent=2))
        print()

    if products:
        print("=" * 80)
        print("RAW JSON for first Pass 2 product (with pricing):")
        print(json.dumps(products[0], indent=2))


if __name__ == "__main__":
    main()