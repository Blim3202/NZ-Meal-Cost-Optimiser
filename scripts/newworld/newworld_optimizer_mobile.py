"""
New World Mobile API Optimizer
==============================
Finds the cheapest New World store for a given dish within 5km of a NZ address.

Uses the Foodstuffs Mobile API (api-prod.prod.fsniwaikato.kiwi/prod) with guest token auth.
Single-pass search: returns first/most-relevant result per query (no explicit relevance matching).

Orders results by cheapest per-unit price (per kg, ml, piece, etc.) where available,
falling back to total item price.

Usage:
    python -m scripts.newworld.newworld_optimizer_mobile "Botany Town Centre, Auckland" "spaghetti bolognese"
"""

import sys
import time
import pandas as pd
from pathlib import Path
from typing import Optional

from newworld_api import (
    NewWorldMobileAPI,
    load_stores,
    geocode,
    find_nearby_stores,
    get_ingredients,
    haversine,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
OUTPUT_CSV = DATA_DIR / "newworld_mobile_latest_results.csv"


def search_ingredient_at_store(
    api: NewWorldMobileAPI,
    store_id: str,
    ingredient: str,
) -> list[dict]:
    """
    Search for one ingredient at one store via Mobile API.
    Returns enriched product list with price, unit_price, name, size.
    """
    try:
        results = api.search_products(store_id, ingredient)
    except Exception as e:
        print(f"    [ERROR] {ingredient}: {e}")
        return []

    if not results:
        return []

    products = results if isinstance(results, list) else results.get("products", [])
    enriched = []
    for p in products:
        price = NewWorldMobileAPI.extract_price(p)
        if price is None:
            continue
        enriched.append({
            "product_id": p.get("productId"),
            "name": NewWorldMobileAPI.get_product_name(p),
            "size": NewWorldMobileAPI.get_product_size(p),
            "price": price,
            "unit_price": NewWorldMobileAPI.extract_unit_price(p),
            "is_promo": False,  # Mobile API doesn't surface promo flag distinctly
        })
    return enriched


def pick_cheapest_per_unit(products: list[dict]) -> dict | None:
    """
    Pick the cheapest product by unit price (per kg/L/each).
    Falls back to absolute price if unit_price unavailable.
    """
    if not products:
        return None

    import re

    def parse_unit_price(up_str: str) -> float | None:
        if not up_str:
            return None
        m = re.search(r"[\d.]+", up_str.replace(",", ""))
        return float(m.group()) if m else None

    priced = []
    for p in products:
        up = parse_unit_price(p.get("unit_price", ""))
        priced.append((up if up is not None else p["price"], p))

    priced.sort(key=lambda x: x[0])
    return priced[0][1]


def optimize_dish_mobile(
    address: str,
    dish_name: str,
    radius_km: float = 5.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Main optimization function using Mobile API.

    Returns:
        summary_df: DataFrame with store totals sorted by cheapest
        detail_df:  DataFrame with per-ingredient breakdown per store
    """
    print("=" * 70)
    print(f"New World Mobile API Optimizer -- {dish_name.title()}")
    print("=" * 70)

    # 1. Geocode address
    print(f"\n[1] Geocoding: {address}")
    user_lat, user_lon = geocode(address)
    if user_lat is None:
        raise ValueError(f"Could not geocode address: {address}")
    print(f"    Coordinates: {user_lat:.5f}, {user_lon:.5f}")

    # 2. Find nearby stores (from CSV produced by newworld_setup.py)
    print(f"\n[2] Finding stores within {radius_km} km...")
    nearby = find_nearby_stores(user_lat, user_lon, radius_km)
    if not nearby:
        raise ValueError(f"No New World stores within {radius_km} km")
    print(f"    Found {len(nearby)} stores:")
    for s in nearby:
        print(f"      {s['name']:35s} {s['distance_km']:.1f} km")

    # 3. Initialize Mobile API (guest token auth)
    print("\n[3] Authenticating with Mobile API (guest token)...")
    api = NewWorldMobileAPI()
    api._ensure_token()
    print("    Authenticated successfully")

    # 4. Get ingredients
    ingredients = get_ingredients(dish_name)
    print(f"\n[4] Dish: {dish_name.title()}")
    print(f"    Ingredients ({len(ingredients)}): {', '.join(ingredients)}")

    # 5. Search each ingredient at each store
    print("\n[5] Searching products (mobile API single-pass)...")
    all_results = []

    for store in nearby:
        store_id = store["store_id"]
        store_name = store["name"]
        store_dist = store["distance_km"]

        print(f"\n  --- {store_name} ({store_dist:.1f} km) ---")
        store_total = 0.0
        found_count = 0

        for ing in ingredients:
            print(f"    Searching: {ing} ...", end=" ", flush=True)
            products = search_ingredient_at_store(api, store_id, ing)
            if products:
                best = pick_cheapest_per_unit(products)
                if best:
                    store_total += best["price"]
                    found_count += 1
                    unit_str = f" ({best['unit_price']})" if best['unit_price'] else ""
                    print(f"${best['price']:.2f}{unit_str}  --  {best['name'][:50]}")
                    all_results.append({
                        "store": store_name,
                        "store_id": store_id,
                        "distance_km": store_dist,
                        "ingredient": ing,
                        "product_name": best["name"],
                        "product_size": best["size"],
                        "price": best["price"],
                        "unit_price": best["unit_price"],
                        "is_promo": best["is_promo"],
                    })
                else:
                    print("no valid price")
            else:
                print("NOT FOUND")
            time.sleep(0.08)  # gentle rate limit

        print(f"    Subtotal: ${store_total:.2f}  ({found_count}/{len(ingredients)} found)")

    if not all_results:
        raise ValueError("No products found for any ingredient at any store")

    # 6. Build DataFrames
    df = pd.DataFrame(all_results)

    # Per-store summary (sum of cheapest per ingredient)
    summary_rows = []
    for store_name in df["store"].unique():
        store_df = df[df["store"] == store_name]
        cheapest_per_ing = store_df.loc[store_df.groupby("ingredient")["price"].idxmin()]
        total = cheapest_per_ing["price"].sum()
        found = len(cheapest_per_ing)
        dist = store_df["distance_km"].iloc[0]
        summary_rows.append({
            "store": store_name,
            "distance_km": dist,
            "items_found": found,
            "total_cost": round(total, 2),
        })

    summary_df = pd.DataFrame(summary_rows).sort_values("total_cost").reset_index(drop=True)

    # Detailed breakdown table
    detail_rows = []
    for ing in ingredients:
        row = {"Ingredient": ing}
        for store_name in summary_df["store"]:
            match = df[(df["ingredient"] == ing) & (df["store"] == store_name)]
            if not match.empty:
                best = match.loc[match["price"].idxmin()]
                unit = f" ({best['unit_price']})" if best["unit_price"] else ""
                row[store_name] = f"${best['price']:.2f}{unit} -- {best['product_name'][:40]}"
            else:
                row[store_name] = "NOT FOUND"
        detail_rows.append(row)

    detail_df = pd.DataFrame(detail_rows).set_index("Ingredient")

    # 7. Output summary
    print("\n" + "=" * 70)
    print("COST COMPARISON (cheapest per-unit price at each store)")
    print("=" * 70)
    print(summary_df.to_string(index=False))

    best = summary_df.iloc[0]
    print(f"\n>>> CHEAPEST: {best['store']} -- ${best['total_cost']:.2f} total ({best['items_found']}/{len(ingredients)} items)")

    print("\n" + "=" * 70)
    print("DETAILED BREAKDOWN (cheapest product per ingredient per store)")
    print("=" * 70)
    print(detail_df.to_string())

    # 8. Save results
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"\n[OK] Full results saved to {OUTPUT_CSV}")

    return summary_df, detail_df


def main():
    if len(sys.argv) > 2:
        address = sys.argv[1]
        dish = sys.argv[2]
    else:
        address = "Botany Town Centre, Auckland"
        dish = "spaghetti bolognese"

    try:
        optimize_dish_mobile(address, dish)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()