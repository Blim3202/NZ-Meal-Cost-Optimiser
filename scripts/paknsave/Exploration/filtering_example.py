"""
Pak'nSave Edge API — Product Relevance & Category Filtering Guide
==================================================================

Demonstrates how the two-pass Edge API pipeline filters irrelevant products
when searching for ingredients, with a focus on the "beef mince" problem
(where "beef mince seasoning" or similar products match the query but are
not the actual ingredient).

This script runs three variants of Pass 1 (relevance search) for every
nearby Pak'nSave store and compares the results:

  VARIANT A — No category filter at all (raw Algolia relevance)
  VARIANT B — Pet food filter only (current production baseline)
  VARIANT C — Full non-ingredient category blacklist (recommended)

Each variant searches for "beef mince", returns the top 20 relevant
productIDs from Pass 1, then fetches per-store pricing for all matched
products via Pass 2.  Results are printed side-by-side so you can see
exactly which products each filter removes or keeps.

Usage:
    python scripts/paknsave/filtering_example.py "Botany Town Centre, Auckland"
    python scripts/paknsave/filtering_example.py  # uses default address

Requirements:
    - requests
    - The Pak'nSave Edge API must be accessible (no special auth beyond
      the website JWT flow which is fully automated in this script).

Discovery:
    Run `python scripts/paknsave/Exploration/explore_categories.py` to re-discover
    all category1 values from the Pak'nSave Algolia index.  The sets
    below were populated from actual API data (89 unique values found).
"""

import sys
import json
import time
import math
import requests
from collections import defaultdict

# Ensure UTF-8 output on Windows consoles
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ─── Constants ────────────────────────────────────────────────────────────
WEB_BASE = "https://www.paknsave.co.nz"
EDGE_BASE = "https://api-prod.paknsave.co.nz/v1/edge"
QUERY = "beef mince"
MAX_HITS = 20  # top N relevance matches per store per variant
MAX_RETAIL_PRICE = 50.00  # cap for display (skip absurdly priced items)

# ─── All 89 discovered category1 values (from explore_categories.py) ─────
# Every distinct value that appears in ANY product's category1 array
# across the Algolia products-index.  Grouped by type for clarity.
#
# To re-discover:  python scripts/paknsave/Exploration/explore_categories.py

# ── Meat & Seafood (ingredient) ──────────────────────────────────────────
# Beef, Chicken & Poultry, Lamb, Pork & Ham, Seafood,
# Mince Sausages & Meatballs, Offal & Bones, Deli Meats,
# Deli Meats & Smoked Fish

# ── Produce (ingredient) ─────────────────────────────────────────────────
# Vegetables, Fruit, Fresh Salad & Herbs, Organic Fruit & Vegetables

# ── Dairy & Eggs (ingredient) ────────────────────────────────────────────
# Milk, Eggs, Cheese, Butter & Margarine, Yoghurt,
# Cream Custard & Desserts

# ── Pantry & Baking (ingredient) ─────────────────────────────────────────
# Canned Foods & Packets, Pasta Rice & Noodles, Baking Supplies & Sugar,
# Oil & Vinegar, Spices Seasoning & Coatings,
# Cooking Sauces Stocks & Marinades, Table Sauces Dressings & Condiments,
# Jams Honey & Spreads, Long Life & Dairy Free Milk, Breakfast Cereals,
# Desserts, World Foods

# ── Bakery & Bread (ingredient-ish) ──────────────────────────────────────
# Sliced & Packaged Bread, Bagels Crumpets & Pancakes,
# Burger Buns Rolls & Garlic Bread, Cakes Muffins & Desserts,
# In-Store Bakery, Gluten Free Low Carb & Keto

# ── Frozen (ingredient-ish) ──────────────────────────────────────────────
# Frozen Vegetables, Frozen Chicken & Meat, Frozen Fish & Seafood,
# Frozen Chips & Hash Browns, Frozen Dumplings Pies & Snacks,
# Frozen Pizza & Ready Meals, Ice Cream & Sorbet

# ── Beverages (not ingredient) ───────────────────────────────────────────
# Soft Drinks & Mixers, Juice & Smoothies, Water, Coffee, Tea,
# Sports & Energy Drinks, Beer, Red Wine, White Wine,
# Hot Chocolate & Milk Drinks, Syrups Cordials & Powdered Drinks,
# Kombucha & Functional Drinks

# ── Snacks & Convenience (borderline) ────────────────────────────────────
# Chips Nuts & Snacks, Chocolate Sweets & Chewing Gum,
# Biscuits & Crackers, Lunchbox Snacks, Ready to Eat,
# Easy Meals & Meal Kits, Chilled Pasta Pizza & Garlic Bread,
# Chilled Soups & Ready Meals, Dips Hummus & Antipasti

# ── Non-Food (clearly not ingredient) ────────────────────────────────────
# Dog, Cat,
# Baby & Toddler Food, Baby & Toddler Toiletries, Baby Formula,
# Baby Wipes, Nappies & Changing,
# Bath Shower & Soap, Hair Care, Dental & Oral Care,
# Deodorant & Body Sprays, Skin Care & Sun Care,
# Cleaning & Accessories, Dishwashing, Kitchen Cleaners, Laundry,
# Pest & Insect Control,
# Batteries & Electrical, Food Wrap Storage & Bags,
# Stationery & Entertainment,
# Toilet Paper Tissues & Paper Towels, Tissues & Cotton Wool,
# Vitamins & Supplements, Medical & First Aid

# ─── Non-Ingredient Category Blacklist ────────────────────────────────────
# These are ALL 89 discovered category1 values that represent products
# which are NOT raw cooking ingredients.  Every value here was confirmed
# to exist in the Pak'nSave Algolia index by logging the category1 responses from a wide search (May include more).
#
# The blacklist is additive — Variant B (pet food only) is a strict
# subset of this set.
NON_INGREDIENT_CATEGORIES = {
    # ── Pet food ──────────────────────────────────────────────────────
    "Dog",              # 46 hits — dog food, dog rolls, dog treats
    "Cat",              # 48 hits — cat food, cat treats, cat litter
    # ── Baby products ─────────────────────────────────────────────────
    "Baby & Toddler Food",      # 40 hits — baby purees, puffs, snacks
    "Baby & Toddler Toiletries", #  2 hits — baby soap, baby shampoo
    "Baby Formula",              #  1 hit  — infant formula
    "Baby Wipes",                # 18 hits — baby wipes
    "Nappies & Changing",        # 35 hits — nappies, nappy pants
    # ── Personal care ─────────────────────────────────────────────────
    "Bath, Shower & Soap",       # 37 hits — body wash, hand soap, soap bars
    "Hair Care",                 # 40 hits — shampoo, conditioner, styling
    "Dental & Oral Care",        #  5 hits — toothpaste, toothbrush, mouthwash
    "Deodorant & Body Sprays",   #  1 hit  — deodorant
    "Skin Care & Sun Care",      #  2 hits — body lotion, sunscreen
    # ── Household cleaning ────────────────────────────────────────────
    "Cleaning & Accessories",    #  4 hits — cleaning sprays, cloths
    "Dishwashing",               # 45 hits — dishwasher tablets, dish liquid
    "Kitchen Cleaners",          #  2 hits — kitchen spray, steel wool
    "Laundry",                   #  8 hits — laundry powder, fabric softener
    "Pest & Insect Control",     #  1 hit  — fly spray, insect repellent
    # ── Paper & storage ───────────────────────────────────────────────
    "Toilet Paper, Tissues & Paper Towels",  # 51 hits — toilet paper, paper towels
    "Tissues & Cotton Wool",     # 16 hits — facial tissues, cotton buds
    "Food Wrap, Storage & Bags", #  6 hits — cling wrap, bin liners, containers
    # ── Household non-food ────────────────────────────────────────────
    "Batteries & Electrical",    # 40 hits — batteries, light bulbs, phone accessories
    "Stationery & Entertainment",# 40 hits — toys, magazines, stationery, party supplies
    # ── Health & supplements ──────────────────────────────────────────
    "Vitamins & Supplements",    # 26 hits — fish oil, multivitamins
    "Medical & First Aid",       #  2 hits — pain relief, antiseptic
}

# ─── Pet food categories (subset of the above, used in Variant B) ───────
PET_FOOD_CATEGORIES = {"Dog", "Cat"}


# ─── Helper functions ─────────────────────────────────────────────────────

def get_website_session():
    """
    Obtain a website JWT (fs-user-token) via the standard Foodstuffs
    website flow.  This token authenticates all Edge API calls.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    session.get(WEB_BASE, timeout=30)
    session.post(
        f"{WEB_BASE}/api/user/get-current-user",
        json={},
        timeout=30,
    )
    token = session.cookies.get("fs-user-token")
    if not token:
        raise RuntimeError("Failed to obtain fs-user-token cookie")
    return token, session


def auth_headers(token):
    """Headers required for all authenticated Edge API calls."""
    return {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0",
    }


def store_cookies(store_id, region="NI"):
    """Cookies that set the store context for per-store pricing."""
    return {
        "eCom_STORE_ID": store_id,
        "STORE_ID_V2": f"{store_id}|False",
        "Region": region,
    }


def pass1_relevance_search(token, store_id, query, max_hits=20,
                           category_filter=None):
    """
    PASS 1 — Relevance matching via Algolia products-index.

    Returns enriched hits with category1 arrays so callers can inspect
    exactly what the filter would keep or exclude.
    """
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

    results = []
    for h in hits:
        hr = h.get("_highlightResult", {})
        cat1 = h.get("category1", [])
        display_name = h.get("DisplayName", "")

        # Print raw hit data
        print(f"\n    === Hit #{len(results) + 1} ===")
        print(f"    DisplayName : {display_name}")
        print(f"    category1   : {cat1}")
        print(f"    _highlightResult :")
        for field_name, field_val in hr.items():
            if isinstance(field_val, dict):
                mw = field_val.get("matchedWords", [])
                val = field_val.get("value", "")
                clean_val = val.replace("<em>", "").replace("</em>", "")
                print(f"      {field_name:35s} matchedWords={mw}")
                print(f"        {'':>35s} value={clean_val}")
        print()

        # Which fields had matchedWords?
        matched_fields = {}
        for field_name, field_val in hr.items():
            if isinstance(field_val, dict) and field_val.get("matchedWords"):
                matched_fields[field_name] = field_val["matchedWords"]

        has_any_match = bool(matched_fields)

        # Category filter
        passes_filter = True
        if category_filter is not None:
            if any(c in category_filter for c in cat1):
                passes_filter = False

        displayName_matched = (
            isinstance(hr.get("DisplayName"), dict)
            and hr["DisplayName"].get("matchedWords")
        )
        brand_matched = (
            isinstance(hr.get("brand"), dict)
            and hr["brand"].get("matchedWords")
        )
        category2AndBrand_matched = (
            isinstance(hr.get("category2AndBrand"), dict)
            and hr["category2AndBrand"].get("matchedWords")
        )

        results.append({
            "productID": h.get("productID", ""),
            "DisplayName": display_name,
            "category1": cat1,
            "category2": h.get("category2", []),
            "brand": h.get("brand", ""),
            "averagePrice": h.get("averagePrice"),
            "has_any_match": has_any_match,
            "matched_fields": matched_fields,
            "displayName_matched": displayName_matched,
            "brand_matched": brand_matched,
            "category2AndBrand_matched": category2AndBrand_matched,
            "passes_filter": passes_filter,
        })

    return results, hits


def pass2_per_store_pricing(token, store_id, query, product_ids, region="NI"):
    """
    PASS 2 — Per-store pricing via paginated/products with Algolia filters.
    """
    if not product_ids:
        return []

    headers = auth_headers(token)
    cookies = store_cookies(store_id, region)
    filter_str = " OR ".join(f"productID:{pid}" for pid in product_ids)
    payload = {
        "algoliaQuery": {"query": query, "filters": filter_str},
        "page": 0,
        "hitsPerPage": max(len(product_ids), 50),
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
    """Extract final price in dollars. Promo price wins over regular."""
    sp = product.get("singlePrice", {})
    price_cents = sp.get("price")
    promo = product.get("promotions", [])
    promo_val = promo[0].get("rewardValue") if promo else None
    final_cents = promo_val if promo_val is not None else price_cents
    return final_cents / 100.0 if final_cents else None


def extract_unit_price(product):
    """Extract unit price string (e.g. '$10.00/kg')."""
    sp = product.get("singlePrice", {})
    return sp.get("unitPrice") or sp.get("pricePerUnit") or ""


def geocode(address):
    """Geocode a NZ address via Nominatim."""
    time.sleep(1.2)  # respect Nominatim rate limit
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        headers={"User-Agent": "NZMealCostOptimizer/1.0"},
        params={"q": address, "format": "json", "limit": 1},
        timeout=15,
    )
    if r.status_code == 200 and r.json():
        loc = r.json()[0]
        return float(loc["lat"]), float(loc["lon"])
    return None, None


def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def load_stores():
    """Load store list from the project's CSV output."""
    import csv
    from pathlib import Path
    stores = []
    csv_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "paknsave_stores.csv"
    if not csv_path.exists():
        return stores
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                row["latitude"] = float(row["latitude"])
                row["longitude"] = float(row["longitude"])
                stores.append(row)
            except (ValueError, KeyError):
                continue
    return stores


def find_nearby_stores(user_lat, user_lon, radius_km=1.0):
    """Return stores within radius_km, sorted by distance."""
    stores = load_stores()
    nearby = []
    for s in stores:
        try:
            d = haversine(user_lat, user_lon, s["latitude"], s["longitude"])
            if d <= radius_km:
                nearby.append({**s, "distance_km": round(d, 2)})
        except (KeyError, ValueError):
            continue
    nearby.sort(key=lambda x: x["distance_km"])
    return nearby


# ─── Main execution ───────────────────────────────────────────────────────

def main():
    address = sys.argv[1] if len(sys.argv) > 1 else "Botany Town Centre, Auckland 2016"

    print("=" * 80)
    print("PAK'nSAVE EDGE API — PRODUCT RELEVANCE & CATEGORY FILTERING GUIDE")
    print("=" * 80)
    print()
    print("This script demonstrates three filtering strategies for Pass 1")
    print("(Algolia relevance search) of the two-pass Edge API pipeline.")
    print()
    print(f"Search query:  '{QUERY}'")
    print(f"Address:       {address}")
    print()

    # ── Step 1: Authentication ──────────────────────────────────────────
    print("STEP 1: Authenticating with Pak'nSave website...")
    token, _ = get_website_session()
    print(f"  Got fs-user-token (JWT): {token[:40]}...")
    print()

    # ── Step 2: Geocode & find nearby stores ────────────────────────────
    print("STEP 2: Geocoding address and finding nearby stores...")
    user_lat, user_lon = geocode(address)
    if user_lat is None:
        print("  ERROR: Could not geocode address.  Exiting.")
        sys.exit(1)
    print(f"  Coordinates: {user_lat:.5f}, {user_lon:.5f}")

    nearby = find_nearby_stores(user_lat, user_lon, radius_km=1.0)
    if not nearby:
        print("  ERROR: No Pak'nSave stores within 1 km.  Exiting.")
        sys.exit(1)
    print(f"  Found {len(nearby)} store(s) within 1 km:")
    for s in nearby:
        print(f"    {s['name']:40s} {s['distance_km']:.2f} km  ({s.get('region', '?')})")
    print()

    # ── Step 3: Show discovered category1 values ───────────────────────
    print("=" * 80)
    print("STEP 3: Discovered category1 Values (from Pak'nSave Algolia Index)")
    print("=" * 80)
    print()
    print("These are ALL 89 unique category1 values confirmed to exist in the")
    print("Pak'nSave Algolia products-index.  They were discovered by running")
    print("62 broad search queries and collecting every category1 array seen.")
    print()
    print("To re-discover: python scripts/paknsave/Exploration/explore_categories.py")
    print()

    all_categories = sorted(NON_INGREDIENT_CATEGORIES)
    food_categories = [
        "Beef", "Chicken & Poultry", "Lamb", "Pork & Ham", "Seafood",
        "Mince, Sausages & Meatballs", "Offal & Bones", "Deli Meats",
        "Deli Meats & Smoked Fish",
        "Vegetables", "Fruit", "Fresh Salad & Herbs", "Organic Fruit & Vegetables",
        "Milk", "Eggs", "Cheese", "Butter & Margarine", "Yoghurt",
        "Cream, Custard & Desserts",
        "Canned Foods & Packets", "Pasta, Rice & Noodles",
        "Baking Supplies & Sugar", "Oil & Vinegar",
        "Spices, Seasoning & Coatings",
        "Cooking Sauces, Stocks & Marinades",
        "Table Sauces, Dressings & Condiments",
        "Jams, Honey & Spreads", "Long Life & Dairy Free Milk",
        "Breakfast Cereals", "Desserts", "World Foods",
        "Sliced & Packaged Bread", "Bagels, Crumpets & Pancakes",
        "Burger Buns, Rolls & Garlic Bread", "Cakes, Muffins & Desserts",
        "In-Store Bakery", "Gluten Free, Low Carb & Keto",
        "Frozen Vegetables", "Frozen Chicken & Meat", "Frozen Fish & Seafood",
        "Frozen Chips & Hash Browns", "Frozen Dumplings, Pies & Snacks",
        "Frozen Pizza & Ready Meals", "Ice Cream & Sorbet",
        "Soft Drinks & Mixers", "Juice & Smoothies", "Water", "Coffee", "Tea",
        "Sports & Energy Drinks", "Beer", "Red Wine", "White Wine",
        "Hot Chocolate & Milk Drinks", "Syrups, Cordials & Powdered Drinks",
        "Kombucha & Functional Drinks",
        "Chips, Nuts & Snacks", "Chocolate, Sweets & Chewing Gum",
        "Biscuits & Crackers", "Lunchbox Snacks", "Ready to Eat",
        "Easy Meals & Meal Kits", "Chilled Pasta, Pizza & Garlic Bread",
        "Chilled Soups & Ready Meals", "Dips, Hummus & Antipasti",
    ]

    print(f"{'NON-INGREDIENT (blacklisted)':<50} {'FOOD/INGREDIENT (kept)'}")
    print(f"{'─' * 50} {'─' * 30}")
    max_len = max(len(all_categories), len(food_categories))
    for i in range(max_len):
        left = all_categories[i] if i < len(all_categories) else ""
        right = food_categories[i] if i < len(food_categories) else ""
        left_mark = "  ✗" if left else ""
        right_mark = "  ✓" if right else ""
        print(f"  {left:<48}{left_mark}   {right:<28}{right_mark}")
    print()
    print(f"  Non-ingredient categories: {len(all_categories)}")
    print(f"  Food/ingredient categories: {len(food_categories)}")
    print(f"  Total unique category1 values: {len(all_categories) + len(food_categories)}")
    print()

    # ── Step 4: Run Pass 1 for each variant on each store ──────────────
    print("=" * 80)
    print("STEP 4: Pass 1 Relevance Search — Three Variants Compared")
    print("=" * 80)
    print()

    # Collect results across all three variants per store
    all_results = defaultdict(lambda: defaultdict(dict))

    for store in nearby:
        store_id = store["store_id"]
        store_name = store["name"]
        region = store.get("region", "NI")
        print("-" * 70)
        print(f"  Store: {store_name} ({store['distance_km']:.2f} km, {region})")
        print("-" * 70)

        for variant_name, category_filter in [
            ("A — NO FILTER (raw Algolia relevance)", None),
            ("B — PET FOOD FILTER ONLY (current baseline)", PET_FOOD_CATEGORIES),
            ("C — FULL NON-INGREDIENT BLACKLIST (recommended)", NON_INGREDIENT_CATEGORIES),
        ]:
            pass1_results, raw_hits = pass1_relevance_search(
                token, store_id, QUERY, MAX_HITS, category_filter
            )

            passed_ids = [
                r["productID"] for r in pass1_results
                if r["passes_filter"] and r["has_any_match"]
            ]
            failed_ids = [
                r["productID"] for r in pass1_results
                if not r["passes_filter"] and r["has_any_match"]
            ]

            print(f"\n  [{variant_name}]")
            print(f"    Raw Algolia hits: {len(raw_hits)}")
            print(f"    After relevance (matchedWords): {len(passed_ids) + len(failed_ids)}")
            print(f"    Passed filter: {len(passed_ids)}")
            print(f"    Filtered out:  {len(failed_ids)}")

            if passed_ids:
                priced = pass2_per_store_pricing(
                    token, store_id, QUERY, passed_ids, region
                )
                priced.sort(
                    key=lambda p: (
                        extract_price(p) if extract_price(p) is not None else 9999
                    )
                )
                all_results[variant_name][store_name] = {
                    "passed_count": len(passed_ids),
                    "failed_count": len(failed_ids),
                    "raw_hits": len(raw_hits),
                    "priced_products": priced[:MAX_HITS],
                }

                print(f"\n    Top {min(len(priced), MAX_HITS)} priced results (after Pass 2):")
                for i, p in enumerate(priced[:MAX_HITS], 1):
                    price = extract_price(p)
                    name = p.get("name") or p.get("DisplayName") or "Unknown"
                    size = p.get("displayName") or ""
                    unit = extract_unit_price(p)
                    promo = " [PROMO]" if p.get("promotions") else ""
                    cat1 = p.get("category1", [])
                    if price is not None and price <= MAX_RETAIL_PRICE:
                        print(
                            f"      {i:2d}. ${price:5.2f}  {name}"
                            f"{(' ' + size) if size else ''}"
                            f"  [{', '.join(cat1)}]"
                            f"  {unit}{promo}"
                        )
            else:
                all_results[variant_name][store_name] = {
                    "passed_count": 0,
                    "failed_count": len(failed_ids),
                    "raw_hits": len(raw_hits),
                    "priced_products": [],
                }
                print("    No products passed the filter (nothing to price)")

            # Show filtered-out products
            if failed_ids and variant_name != "A — NO FILTER (raw Algolia relevance)":
                filtered_out = [
                    r for r in pass1_results
                    if not r["passes_filter"] and r["has_any_match"]
                ]
                if filtered_out:
                    print(f"\n    Products FILTERED OUT by this variant (would appear in A):")
                    for r in filtered_out[:10]:
                        cats = ", ".join(r["category1"]) if r["category1"] else "(none)"
                        match_info = (
                            f"matched in: {', '.join(r['matched_fields'].keys())}"
                        )
                        print(
                            f"      ✗ {r['DisplayName'][:50]}"
                            f"  [{cats}]  ({match_info})"
                        )
                    if len(filtered_out) > 10:
                        print(f"      ... and {len(filtered_out) - 10} more")

            time.sleep(0.15)

    # ── Step 5: Cross-store comparison summary ──────────────────────────
    print()
    print("=" * 80)
    print("STEP 5: Cross-Store Comparison Summary")
    print("=" * 80)
    print()

    for variant_name, stores_data in all_results.items():
        print(f"\n{'─' * 60}")
        print(f"  {variant_name}")
        print(f"{'─' * 60}")

        for store_name, data in stores_data.items():
            priced = data["priced_products"]
            if priced:
                cheapest = priced[0]
                cheap_price = extract_price(cheapest)
                cheap_name = cheapest.get("name") or cheapest.get("DisplayName") or ""
                print(
                    f"  {store_name:40s}  "
                    f"{data['passed_count']} matched → "
                    f"cheapest: ${cheap_price:.2f}  {cheap_name[:40]}"
                )
            else:
                print(
                    f"  {store_name:40s}  "
                    f"{data['passed_count']} matched → no priced results"
                )

    # ── Step 6: Filtering mechanism explained ───────────────────────────
    print()
    print("=" * 80)
    print("STEP 6: How Each Filter Works")
    print("=" * 80)
    print()
    print("""
VARIANT A — NO FILTER
  Every product where Algolia's _highlightResult has non-empty matchedWords
  is kept.  Maximum recall, maximum noise.

VARIANT B — PET FOOD FILTER ONLY (production baseline)
  Excludes products whose category1 contains "Dog" or "Cat".
  Removes pet food but keeps seasoning, sauces, household items, etc.

VARIANT C — FULL NON-INGREDIENT BLACKLIST (recommended)
  Excludes ALL 26 non-ingredient category1 values discovered from the
  Pak'nSave Algolia index.  Every value was confirmed to exist (not
  guessed).  See NON_INGREDIENT_CATEGORIES at the top of this file.

HOW THE BLACKLIST WORKS:
  1. Pass 1 returns hits from Algolia, each with a category1 array.
  2. For each hit, check if ANY category1 value is in the blacklist.
  3. If yes → exclude from Pass 2 (no pricing fetched).
  4. If no  → include in Pass 2 (pricing fetched, sorted PRICE_ASC).

THE category1 FIELD:
  Each product has a category1 array (e.g. ["Beef", "Mince, Sausages &
  Meatballs"]).  These are the EXACT values returned by the Algolia
  index — they come from the Pak'nSave product taxonomy, not from us.
  There are 89 unique values total across all products.
""")

    # ── Step 7: Recommendations ──────────────────────────────────────────
    print("=" * 80)
    print("STEP 7: Recommendations")
    print("=" * 80)
    print()
    print("""
RECOMMENDED: Use Variant C (full blacklist) in production.

To update the blacklist:
  1. Run:  python scripts/paknsave/Exploration/explore_categories.py
  2. Review the output for any new category1 values.
  3. Add non-ingredient values to NON_INGREDIENT_CATEGORIES.

The blacklist currently contains 26 values.  If a legitimate ingredient
product is wrongly excluded (unlikely — all food categories are kept),
remove its category1 value from the set.

FUTURE IMPROVEMENTS:
  - Whitelist approach: instead of blacklisting, maintain a whitelist of
    ingredient-relevant category1 values per ingredient type.
  - DisplayName scoring: require that DisplayName has matchedWords, not
    just any field (brand/category matches are less reliable).
  - Multi-query disambiguation: search "beef mince" then verify the top
    result is actually raw mince, not a sauce or seasoning.
""")

    print("Done.")
    print("=" * 80)


if __name__ == "__main__":
    main()
