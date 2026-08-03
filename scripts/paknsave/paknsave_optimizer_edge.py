"""
Pak'nSave Edge API Optimizer
============================
Two-phase meal cost optimizer using the Pak'nSave Edge API (two-pass pipeline).

Phase 1 (query):  Geocode address → find nearby stores → authenticate → search
                   each ingredient at each store → append ALL results to full_results.csv
Phase 2 (optimise): Read today's results from CSV → find best per-store totals
                    and best mix → print comparison table

Usage:
    python -m scripts.paknsave.paknsave_optimizer_edge "<address>" "<dish>" [--requery false] [--distance 5]

Flags:
    --requery true   (default) Query the API and append new results
    --requery false  Skip API calls, optimise from existing CSV data only
    --distance N     Store search radius in km (default 5)

Defaults:
    Address: 588 Chapel Road, East Tāmaki, Auckland 2016
    Dish:    spaghetti bolognese
"""

import csv
import sys
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd

# Add scripts/combined to path for optimizer_utils
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "combined"))

from paknsave_api import (
    PaknSaveEdgeAPI,
    load_stores,
    find_nearby_stores,
)
from optimizer_utils import (
    CSV_COLUMNS,
    RESULTS_FILE,
    geocode,
    get_ingredients,
    get_quantities,
    parse_paknsave_volume_size,
    _compute_pk_hash,
    load_existing_hashes,
    append_rows,
)


def build_row(company, store, store_id, search_ingredient, product, pass1_hit, now):
    """Build a CSV row dict from a Pak'nSave product.

    Args:
        company: retailer name (e.g. "PaknSave")
        store: store name
        store_id: store UUID
        search_ingredient: the ingredient term we searched for
        product: dict from Pass 2 (singlePrice, promotions, productId, etc.)
        pass1_hit: dict from Pass 1 (category1, _highlightResult) or None
        now: datetime object for timestamps

    Returns:
        dict matching CSV_COLUMNS
    """
    sp = product.get("singlePrice", {})
    promotions = product.get("promotions", [])

    # Parse quantity, measurement_unit, per_unit_quantity, per_unit_price
    quantity, measurement_unit, per_unit_qty, per_unit_price = parse_paknsave_volume_size(
        product.get("displayName", ""),
        sp,
        promotions,
    )

    # Calculate price: per-item price considering promotions
    # If promotion with threshold: use rewardValue / threshold (per-item promo price)
    # Otherwise: use singlePrice.price (regular per-item price)
    price_cents = sp.get("price")
    if promotions:
        best = promotions[0]
        reward = best.get("rewardValue")
        threshold = best.get("threshold")
        if reward is not None and threshold and threshold > 0:
            price_cents = reward / threshold

    price_dollars = round(price_cents / 100.0, 2) if price_cents is not None else ""

    cat1 = pass1_hit.get("category1", []) if pass1_hit else []
    cat1_str = "|".join(cat1) if cat1 else ""

    sku = product.get("productId", "")
    date_str = now.strftime("%Y-%m-%d")

    return {
        "company": company,
        "store": store,
        "store_id": store_id,
        "search_ingredient": search_ingredient,
        "returned_ingredient": product.get("name", ""),
        "price": price_dollars,
        "quantity": quantity if quantity is not None else "",
        "measurement_unit": measurement_unit,
        "per_unit_quantity": per_unit_qty,
        "per_unit_price": per_unit_price if per_unit_price else "",
        "is_sale": bool(promotions),
        "sku": sku,
        "category1": cat1_str,
        "department": "",
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

    print("\nAuthenticating with Edge API (website JWT)...")
    api = PaknSaveEdgeAPI()
    api.authenticate()
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
                products, pass1_hits = api.search_ingredient(
                    store_id=store_id,
                    ingredient=ing,
                    region=region,
                )
            except Exception as e:
                print(f"  {ing}: [ERROR] {e}")
                time.sleep(0.08)
                continue

            pass1_by_id = {h["productID"]: h for h in pass1_hits}

            priced = []
            for prod in products:
                row = build_row(
                    "PaknSave", store_name, store_id, ing,
                    prod, pass1_by_id.get(prod.get("productId", "")), now,
                )
                if row["price"] != "":
                    new_rows.append(row)
                    priced.append(prod)

            if priced:
                best_price = min(p.get("singlePrice", {}).get("price", float("inf")) for p in priced)
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

    cheapest_per_ing_per_store = (
        df.groupby(["store", "search_ingredient"])["price"].min().reset_index()
    )
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
        store_total = (
            df[df["store"] == sn].groupby("search_ingredient")["price"].min().sum()
        )
        totals[sn] = f"${store_total:.2f}"

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

    Usage: python paknsave_optimizer_edge.py "<address>" "<dish>" [--requery false] [--distance 5]
    Defaults to 588 Chapel Road, East Tāmaki, Auckland 2016 / spaghetti bolognese / requery true / distance 5km.
    """
    address = "588 Chapel Road, East Tāmaki, Auckland 2016"
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
