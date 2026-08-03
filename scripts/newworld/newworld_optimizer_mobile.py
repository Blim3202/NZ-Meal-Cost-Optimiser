"""
New World Mobile API Optimizer
=================================
Two-phase meal cost optimizer using the New World Mobile API (single-pass pipeline).

Phase 1 (query):  Geocode address → find nearby stores → authenticate → search
                    each ingredient at each store → append ALL results to full_results.csv
Phase 2 (optimise): Read today's results from CSV → find best per-store totals
                     and best mix → print comparison table

Usage:
    python -m scripts.newworld.newworld_optimizer_mobile "<address>" "<dish>" [--requery false] [--distance 5]

Flags:
    --requery true   (default) Query the API and append new results
    --requery false  Skip API calls, optimise from existing CSV data only
    --distance N     Store search radius in km (default 5)

Defaults:
    Address: Botany Town Centre, Auckland
    Dish:    spaghetti bolognese
"""

import sys
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "combined"))

from newworld_api import (
    NewWorldMobileAPI,
    find_nearby_stores,
)
from optimizer_utils import (
    CSV_COLUMNS,
    RESULTS_FILE,
    analyze_results,
    geocode,
    get_ingredients,
    get_quantities,
    optimise,
    parse_foodstuffs_mobile_unit,
    _compute_pk_hash,
    load_existing_hashes,
    append_rows,
)


def build_row(company, store, store_id, search_ingredient, product, now):
    """Build a CSV row dict from a New World Mobile API product.

    Args:
        company: retailer name (e.g. "NewWorld")
        store: store name
        store_id: store UUID
        search_ingredient: the ingredient term we searched for
        product: dict from Mobile API (price, name, units, unitPrice, productId, etc.)
        now: datetime object for timestamps

    Returns:
        dict matching CSV_COLUMNS
    """
    price_cents = product.get("price")
    price_dollars = round(price_cents / 100.0, 2) if price_cents is not None else ""

    quantity, measurement_unit, per_unit_qty, per_unit_price = parse_foodstuffs_mobile_unit(
        product.get("units", ""),
        product.get("unitPrice", ""),
        price_cents,
    )

    categories = product.get("categories", []) or []
    sub_department = categories[0] if categories else ""
    department = ""

    sku = product.get("productId", "")
    date_str = now.strftime("%Y-%m-%d")

    return {
        "company": company,
        "store": store,
        "store_id": store_id,
        "search_ingredient": search_ingredient,
        "returned_ingredient": product.get("name", ""),
        "price": price_dollars,
        "quantity": quantity,
        "measurement_unit": measurement_unit,
        "per_unit_quantity": per_unit_qty,
        "per_unit_price": per_unit_price if per_unit_price else "",
        "is_sale": False,
        "sku": sku,
        "department": department,
        "sub_department": sub_department,
        "datetime_created": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date_created": date_str,
        "pk_hash": _compute_pk_hash(store_id, sku, date_str),
    }


def query_and_save(user_address, dish_name, requery, max_dist_km=5.0):
    """Phase 1: Query the API and append results to CSV.

    Args:
        user_address: NZ address to geocode
        dish_name: dish to search ingredients for
        requery: if False, skip API and read existing CSV
        max_dist_km: maximum store search radius in km (default 5)

    Returns True if data is available (newly queried or already in CSV).
    """
    if not requery:
        if RESULTS_FILE.exists():
            return True
        print("No existing results file — run with --requery true to query the API")
        return False

    user_lat, user_lon = geocode(user_address)
    if user_lat is None or user_lon is None:
        print(f"Error: Could not geocode address '{user_address}'")
        return False

    print(f"Geocoding: {user_address}")
    print(f"           lat: {user_lat:.6f}  lon: {user_lon:.6f}")
    print()

    nearby = find_nearby_stores(user_lat, user_lon, radius_km=max_dist_km)
    if not nearby:
        print(f"Error: No New World stores found within {max_dist_km} km")
        return False

    print(f"Found {len(nearby)} stores within {max_dist_km} km:")
    for s in nearby:
        print(f"  {s['name']:35s} {s['distance_km']:.1f} km")

    print("\nAuthenticating with Mobile API (guest token)...")
    api = NewWorldMobileAPI()
    api._ensure_token()
    print("    Authenticated successfully")

    ingredients = get_ingredients(dish_name)
    print(f"\nDish: {dish_name}")
    print(f"Ingredients: {', '.join(ingredients)}")

    now = datetime.now()
    new_rows = []

    for store in nearby:
        store_id = store["store_id"]
        store_name = store["name"]
        region = store.get("region", "NI")
        print(f"\n--- {store_name} ({store['distance_km']:.1f} km, {region}) ---")

        for ing in ingredients:
            try:
                results = api.search_products(store_id, ing)
            except Exception as e:
                print(f"  {ing}: [ERROR] {e}")
                time.sleep(0.1)
                continue

            products = results if isinstance(results, list) else (results or [])

            priced = []
            for prod in products:
                row = build_row("NewWorld", store_name, store_id, ing, prod, now)
                if row["price"] != "":
                    new_rows.append(row)
                    priced.append(prod)

            if priced:
                best_price = min(p.get("price", float("inf")) for p in priced)
                print(f"  {ing}: {len(priced)} results (best: ${best_price / 100:.2f})")
            else:
                print(f"  {ing}: NOT FOUND")

            time.sleep(0.08)

    if not new_rows:
        print("\nNo results collected from API")
        return False

    appended, skipped = append_rows(new_rows)
    print(f"\nAppended {appended} rows to {RESULTS_FILE.name} ({skipped} duplicates skipped)")
    return True



def main():
    """CLI entrypoint.

    Usage: python newworld_optimizer_mobile.py "<address>" "<dish>" [--requery false] [--distance 5]
    Defaults to Botany Town Centre, Auckland / spaghetti bolognese / requery true / distance 5km.
    """
    address = "Botany Town Centre, Auckland"
    dish = "spaghetti bolognese"
    requery = True
    max_dist_km = 5

    positional = []
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--requery":
            if i + 1 < len(sys.argv):
                requery = sys.argv[i + 1].lower() != "false"
                i += 2
            else:
                requery = True
                i += 1
        elif sys.argv[i] == "--distance":
            if i + 1 < len(sys.argv):
                max_dist_km = float(sys.argv[i + 1])
                i += 2
            else:
                i += 1
        else:
            positional.append(sys.argv[i])
            i += 1

    if len(positional) >= 1:
        address = positional[0]
    if len(positional) >= 2:
        dish = positional[1]

    has_data = query_and_save(address, dish, requery, max_dist_km=max_dist_km)
    if has_data:
        optimise(dish)


if __name__ == "__main__":
    main()