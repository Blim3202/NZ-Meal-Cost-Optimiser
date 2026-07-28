"""
New World Edge API - Category1 Discovery
==========================================

Two discovery methods:
  1. Edge API categories endpoint (GET /v1/edge/store/{id}/categories)
  2. Algolia search hits (collecting unique category1 arrays from broad queries)

The categories endpoint gives us the navigation tree.  The Algolia hits
give us the actual category1 values that appear on products in the search
index — these are what we filter on in Pass 1 of the two-pass pipeline.

Usage:
    python scripts/newworld/Exploration/explore_categories.py
"""

import sys
import json
import time
import requests
from collections import Counter
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

WEB_BASE = "https://www.newworld.co.nz"
EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"
BROAD_QUERIES = [
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "r", "s", "t", "v", "w",
    "beef", "chicken", "lamb", "pork", "fish", "milk", "bread", "rice",
    "pasta", "cheese", "egg", "butter", "flour", "sugar", "oil", "salt",
    "pepper", "garlic", "onion", "tomato", "potato", "carrot", "apple",
    "banana", "orange", "water", "juice", "beer", "wine", "coffee", "tea",
    "dog", "cat", "baby", "nappy", "shampoo", "soap", "detergent",
    "vitamin", "toy", "battery",
]


def get_website_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    session.get(WEB_BASE, timeout=30)
    session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    token = session.cookies.get("fs-user-token")
    if not token:
        raise RuntimeError("Failed to obtain fs-user-token")
    return token


def auth_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }


def store_cookies(store_id, region="NI"):
    return {
        "eCom_STORE_ID": store_id,
        "STORE_ID_V2": f"{store_id}|False",
        "Region": region,
    }


def get_first_store(token):
    headers = auth_headers(token)
    r = requests.get(f"{EDGE_BASE}/store", headers=headers, timeout=30)
    r.raise_for_status()
    stores = r.json().get("stores", [])
    if not stores:
        raise RuntimeError("No stores returned")
    for s in stores:
        if s.get("region") == "NI":
            return s["id"], s.get("name", "Unknown")
    return stores[0]["id"], stores[0].get("name", "Unknown")


def fetch_categories_tree(token, store_id):
    headers = auth_headers(token)
    cookies = store_cookies(store_id)
    r = requests.get(
        f"{EDGE_BASE}/store/{store_id}/categories",
        headers=headers,
        cookies=cookies,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def walk_category_tree(nodes, depth=0, results=None):
    if results is None:
        results = []
    for node in (nodes or []):
        name = node.get("name", "?")
        code = node.get("code", "")
        indent = "  " * depth
        suffix = f"  (code: {code})" if code else ""
        line = f"{indent}{name}{suffix}"
        print(line)
        results.append((name, code, depth))
        walk_category_tree(node.get("children", []), depth + 1, results)
    return results


def search_algolia(token, store_id, query, hits_per_page=50):
    headers = auth_headers(token)
    cookies = store_cookies(store_id)
    payload = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": hits_per_page,
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
    return r.json().get("hits", [])


def main():
    print("=" * 80)
    print("NEW WORLD EDGE API — CATEGORY1 DISCOVERY")
    print("=" * 80)
    print()

    print("Step 1: Authenticating...")
    token = get_website_session()
    print(f"  JWT: {token[:40]}...")
    print()

    print("Step 2: Getting a store...")
    store_id, store_name = get_first_store(token)
    print(f"  Store: {store_name} ({store_id})")
    print()

    print("=" * 80)
    print("STEP 3: Categories Endpoint /v1/edge/store/{id}/categories")
    print("=" * 80)
    print()
    print("This is the navigation category tree returned by the Edge API.")
    print("It mirrors the website's Browse department/aisle/shelf structure.")
    print("NOTE: This may NOT exactly match the category1 values in Algolia")
    print("hits — those are a separate classification on the product itself.")
    print()
    try:
        tree = fetch_categories_tree(token, store_id)
        if isinstance(tree, list):
            nodes = tree
        elif isinstance(tree, dict):
            nodes = tree.get("categories") or tree.get("data") or tree.get("items")
            if nodes is None:
                print("  Unexpected response structure. Keys:", list(tree.keys()))
                nodes = []
        else:
            print(f"  Unexpected type: {type(tree)}")
            nodes = []

        if nodes:
            tree_entries = walk_category_tree(nodes)
            print(f"\n  Total category tree nodes: {len(tree_entries)}")
        else:
            print("  (empty tree)")
    except Exception as e:
        print(f"  ERROR fetching categories: {e}")
    print()

    print("=" * 80)
    print("STEP 4: Algolia Search — Collecting category1 Values")
    print("=" * 80)
    print()
    print("Running broad search queries against products-index to discover")
    print("all unique category1 values that appear in the search index.")
    print(f"Queries to run: {len(BROAD_QUERIES)}")
    print()

    cat1_counter = Counter()
    cat1_full_combos = Counter()
    cat1_examples = {}

    for i, query in enumerate(BROAD_QUERIES, 1):
        try:
            hits = search_algolia(token, store_id, query, hits_per_page=50)
            for h in hits:
                cat1 = h.get("category1", [])
                display_name = h.get("DisplayName", "")
                combo_key = tuple(sorted(cat1)) if cat1 else ("(none)",)
                cat1_full_combos[combo_key] += 1
                for c in cat1:
                    cat1_counter[c] += 1
                    if c not in cat1_examples:
                        cat1_examples[c] = display_name
            print(f"  [{i:2d}/{len(BROAD_QUERIES)}] query='{query}' → {len(hits)} hits")
        except Exception as e:
            print(f"  [{i:2d}/{len(BROAD_QUERIES)}] query='{query}' → ERROR: {e}")
        time.sleep(0.12)

    print()

    print("=" * 80)
    print("STEP 5: All Unique category1 Values (sorted by frequency)")
    print("=" * 80)
    print()
    print(f"{'Value':<50} {'Count':>6}  {'Example Product'}")
    print(f"{'─' * 50} {'─' * 6}  {'─' * 40}")

    for value, count in cat1_counter.most_common():
        example = cat1_examples.get(value, "")[:40]
        print(f"{value:<50} {count:>6}  {example}")

    print(f"\n  Total unique category1 values: {len(cat1_counter)}")
    print()

    print("=" * 80)
    print("STEP 6: All Unique category1 Combinations (sorted by frequency)")
    print("=" * 80)
    print()
    print(f"{'Combination':<75} {'Count':>6}")
    print(f"{'─' * 75} {'─' * 6}")

    for combo, count in cat1_full_combos.most_common():
        combo_str = " | ".join(combo)
        print(f"{combo_str:<75} {count:>6}")

    print(f"\n  Total unique combinations: {len(cat1_full_combos)}")

    # ── Save step 6 results to file ─────────────────────────────
    observed_data = {
        "cat1_counter": dict(cat1_counter),
        "cat1_full_combos": {
            " | ".join(combo): count for combo, count in cat1_full_combos.items()
        },
    }
    output_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "data"
        / "observed_category1_newworld.json"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(observed_data, f, indent=2, ensure_ascii=False)
    print(f"  Saved to {output_path}")
    print()

    print("=" * 80)
    print("STEP 7: Pet Food & Non-Ingredient category1 Values")
    print("=" * 80)
    print()

    pet_values = {v for v in cat1_counter if v.lower() in {
        "dog", "cat", "pet", "pet food", "dog food", "cat food", "treats"
    }}
    print(f"Pet-related values found: {pet_values or '(none)'}")
    print()

    non_food_keywords = {
        "pet", "dog", "cat", "treat", "baby", "nappy", "formula",
        "household", "cleaning", "detergent", "paper", "plastic",
        "shampoo", "soap", "toothpaste", "deodorant", "lotion",
        "vitamin", "supplement", "pharmacy", "health",
        "tobacco", "vape", "smoking",
        "kitchen", "cookware", "utensil", "storage",
        "toy", "entertainment", "gift", "magazine", "stationery",
        "garden", "garage", "hardware", "electrical",
        "clothing", "accessory", "bag",
        "battery",
    }
    likely_non_food = {
        v for v in cat1_counter
        if any(kw in v.lower() for kw in non_food_keywords)
    }
    print(f"Likely non-food values (heuristic):")
    for v in sorted(likely_non_food):
        print(f"  {v:<40} (count: {cat1_counter[v]}, example: {cat1_examples.get(v, '')[:35]})")
    print()

    print("=" * 80)
    print("STEP 8: Suggested NON_INGREDIENT_CATEGORIES (copy-paste ready)")
    print("=" * 80)
    print()
    print("Based on the discovered values, here is a suggested filter set")
    print("for the two-pass pipeline.  Review and adjust as needed.")
    print()

    print("# All discovered category1 values — pick what to exclude:")
    print("ALL_DISCOVERED_CATEGORY1 = {")
    for value in sorted(cat1_counter.keys()):
        count = cat1_counter[value]
        flag = "  # <-- likely non-ingredient" if value in likely_non_food else ""
        print(f'    "{value}",{flag}')
    print("}")
    print()

    print("# Suggested NON_INGREDIENT_CATEGORIES (conservative):")
    print("# Excludes: pet, baby, household, health, tobacco, kitchenware")
    print("NON_INGREDIENT_CATEGORIES = {")
    for value in sorted(likely_non_food):
        print(f'    "{value}",')
    print("}")
    print()

    print("Done.")
    print("=" * 80)


if __name__ == "__main__":
    main()