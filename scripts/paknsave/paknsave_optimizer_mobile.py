"""
Pak'nSave Mobile API Optimizer
==============================
Two-phase meal cost optimizer using the Pak'nSave Mobile API (single-pass pipeline).

Phase 1 (query):  Geocode address → find nearby stores → authenticate → search
                   each ingredient at each store → append ALL results to full_results.csv
Phase 2 (optimise): Read today's results from CSV → find best per-store totals
                    and best mix → print comparison table

Usage:
    python -m scripts.paknsave.paknsave_optimizer_mobile "<address>" "<dish>" [--requery false] [--distance 5]

Flags:
    --requery true   (default) Query the API and append new results
    --requery false  Skip API calls, optimise from existing CSV data only
    --distance N     Store search radius in km (default 5)

Defaults:
    Address: 588 Chapel Road, East Tāmaki, Auckland 2016
    Dish:    spaghetti bolognese
"""

import sys
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd

# Add scripts/combined to path for optimizer_utils
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "combined"))

from paknsave_api import (
    PaknSaveMobileAPI,
    find_nearby_stores,
)
from optimizer_utils import (
    CSV_COLUMNS,
    RESULTS_FILE,
    geocode,
    get_ingredients,
    get_quantities,
    parse_paknsave_mobile_unit,
    _compute_pk_hash,
    load_existing_hashes,
    append_rows,
)


def build_row(company, store, store_id, search_ingredient, product, now):
    """Build a CSV row dict from a Pak'nSave Mobile API product.

    Args:
        company: retailer name (e.g. "PaknSave")
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

    # Mobile API: `units` packs the "count + measure" together (e.g. "3 x 31g"),
    # and `unitPrice` is a formatted string (e.g. "$18.99/kg").
    # parse_paknsave_mobile_unit splits both in one call → quantity, measurement_unit,
    # per_unit_quantity, per_unit_price. It handles the sachet/pack edge case
    # "3 x 31g" → quantity=3, measurement_unit="x 31g", and the bare-"ea" fallback
    # (no unitPrice) where per_unit_qty="ea" and per_unit_price mirrors the item's
    # own price (passed as `price_cents`) so the per-unit columns aren't blank.
    quantity, measurement_unit, per_unit_qty, per_unit_price = parse_paknsave_mobile_unit(
        product.get("units", ""),
        product.get("unitPrice", ""),
        price_cents,
    )

    # Mobile API categories: [0] = category1 (sub_department), [1] = category2 (subsub_department).
    # There is no department (category0) in the mobile response.
    # NOTE (future): the department could be reverse-engineered from the sub_department
    # by reading the full product category tree (e.g. the store's /products/category
    # endpoint), then mapped back onto each row. Leaving department empty for now.
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
        "per_unit_price": per_unit_price,
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
        print(f"Error: No Pak'nSave stores found within {max_dist_km} km")
        return False

    print(f"Found {len(nearby)} stores within {max_dist_km} km:")
    for s in nearby:
        print(f"  {s['name']:35s} {s['distance_km']:.1f} km")

    print("\nAuthenticating with Mobile API (guest token)...")
    api = PaknSaveMobileAPI()
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

            # Mobile API returns list directly, not wrapped in "products" key
            products = results if isinstance(results, list) else (results or [])

            priced = []
            for prod in products:
                row = build_row("PaknSave", store_name, store_id, ing, prod, now)
                if row["price"] != "":
                    new_rows.append(row)
                    priced.append(prod)

            if priced:
                # Find cheapest product (by regular price in cents) across all results for this ingredient
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


def analyze_results(df, ingredients, dish_name):
    """Build per-store cost summary and per-ingredient comparison table.

    Args:
        df: DataFrame with columns matching CSV_COLUMNS
        ingredients: list of ingredient search terms for the dish
        dish_name: dish name used to look up quantities

    Returns:
        (summary, table) where:
        - summary: DataFrame indexed by store with total_cost column, sorted cheapest first
        - table: DataFrame indexed by ingredient with per-store prices, best price/store, and TOTAL row
    """
    df = df.copy()
    df["price"] = df["price"].astype(float)

    # Step 1: For each (store, ingredient), keep only the cheapest product
    cheapest_per_ing_per_store = (
        df.groupby(["store", "search_ingredient"])["price"].min().reset_index()
    )
    # Step 2: Sum cheapest ingredients per store → total dish cost
    summary = (
        cheapest_per_ing_per_store.groupby("store")["price"]
        .sum()
        .reset_index()
    )
    summary.columns = ["store", "total_cost"]
    summary = summary.set_index("store").sort_values("total_cost")

    store_names = sorted(df["store"].unique())
    quantities = get_quantities(dish_name)

    rows = []
    for ing in ingredients:
        row = {"Ingredient": ing, "Qty": quantities.get(ing, "-")}
        for sn in store_names:
            match = df[(df["search_ingredient"] == ing) & (df["store"] == sn)]
            if not match.empty:
                best_prod = match.loc[match["price"].idxmin()]
                row[sn] = f"${best_prod['price']:.2f}"
            else:
                row[sn] = "NOT FOUND"

        # Find which store has the cheapest price for this ingredient
        prices = []
        for sn in store_names:
            match = df[(df["search_ingredient"] == ing) & (df["store"] == sn)]
            if not match.empty:
                prices.append(
                    (sn, match.loc[match["price"].idxmin()]["price"])
                )
        if prices:
            best_sn, best_px = min(prices, key=lambda x: x[1])
            row["Best Price"] = f"${best_px:.2f}"
            row["Best Store"] = best_sn
        else:
            row["Best Price"] = "-"
            row["Best Store"] = "-"
        rows.append(row)

    table = pd.DataFrame(rows).set_index("Ingredient")

    totals = {"Qty": ""}
    for sn in store_names:
        # Sum cheapest price per ingredient at this specific store
        store_total = (
            df[df["store"] == sn].groupby("search_ingredient")["price"].min().sum()
        )
        totals[sn] = f"${store_total:.2f}"

    # Best mix: sum of cheapest-per-ingredient across ALL stores (not limited to one store)
    best_total_mix = 0
    for ing in ingredients:
        ing_prices = df[df["search_ingredient"] == ing]["price"]
        if not ing_prices.empty:
            best_total_mix += ing_prices.min()

    totals["Best Price"] = f"${best_total_mix:.2f}"
    totals["Best Store"] = "(mix)"
    table.loc["TOTAL"] = totals

    return summary, table


def optimise(dish_name):
    """Phase 2: Read today's results from CSV and print comparison table."""
    if not RESULTS_FILE.exists():
        print(f"No results file found: {RESULTS_FILE}")
        return

    df = pd.read_csv(RESULTS_FILE, encoding="utf-8")
    today_str = date.today().strftime("%Y-%m-%d")
    df_today = df[df["date_created"] == today_str]

    if df_today.empty:
        print(f"No results found for today ({today_str})")
        return

    ingredients = get_ingredients(dish_name)
    # Filter to only ingredients that actually appear in today's CSV data
    dish_ings = [i for i in ingredients if i in df_today["search_ingredient"].values]

    if not dish_ings:
        print(f"No results for dish '{dish_name}' ingredients in today's data")
        return

    df_dish = df_today[df_today["search_ingredient"].isin(dish_ings)]

    summary, table = analyze_results(df_dish, dish_ings, dish_name)

    print("\n" + "=" * 70)
    print(f"TOTAL COST COMPARISON -- {dish_name.upper()}")
    print("=" * 70)
    print(summary.to_string())
    print("\n" + "=" * 70)
    print("PER-INGREDIENT BREAKDOWN")
    print("=" * 70)
    print(table.to_string())


def main():
    """CLI entrypoint.

    Usage: python paknsave_optimizer_mobile.py "<address>" "<dish>" [--requery false] [--distance 5]
    Defaults to 588 Chapel Road, East Tāmaki, Auckland 2016 / spaghetti bolognese / requery true / distance 5km.
    """
    address = "588 Chapel Road, East Tāmaki, Auckland 2016"
    dish = "spaghetti bolognese"
    requery = True
    max_dist_km = 5

    # Manual arg parsing: collect positional args, handle --flag value pairs
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
