"""
Foodstuffs Edge API Optimizer
================================
Finds the cheapest Foodstuffs (Pak'nSave or New World) store for a given dish within 5km of a NZ address.

Uses the Edge API two-pass pipeline:
  PASS 1: Relevance matching via Algolia products-index (with _highlightResult.matchedWords)
  PASS 2: Per-store pricing via paginated/products with Algolia filters + PRICE_ASC

Works for both Pak'nSave (PNS) and New World (MNW) brands.

Orders results by cheapest per-unit price (per kg, ml, piece, etc.) where available,
falling back to total item price.

Usage:
    python -m scripts.foodstuffs.Foodstuffs_optimizer_edge "Botany Town Centre, Auckland" "spaghetti bolognese"
    python -m scripts.foodstuffs.Foodstuffs_optimizer_edge "Botany Town Centre, Auckland" "spaghetti bolognese" newworld
"""
import sys
import time
import re
import pandas as pd
from pathlib import Path
from typing import Optional

# Adjusts relative imports style to allow module or script calling
try:
    from .Foodstuffs_api import (
        FoodstuffsEdgeAPI,
        load_stores,
        geocode,
        find_nearby_stores,
        get_ingredients,
        BRANDS,
    )
except ImportError:
    from Foodstuffs_api import (
        FoodstuffsEdgeAPI,
        load_stores,
        geocode,
        find_nearby_stores,
        get_ingredients,
        BRANDS,
    )

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

OUTPUT_CSV = {
    "paknsave": DATA_DIR / "paknsave_latest_results.csv",
    "newworld": DATA_DIR / "newworld_latest_results.csv",
}
MAX_DISPLAY = 80


def search_ingredient_at_store(
    api: FoodstuffsEdgeAPI,
    store: dict,
    ingredient: str,
    max_relevance: int = 20,
) -> list[dict]:
    store_id = store["store_id"]
    region = store.get("region", "NI")
    try:
        products = api.search_ingredient(
            store_id=store_id,
            ingredient=ingredient,
            max_relevance=max_relevance,
            region=region,
        )
    except Exception as e:
        print(f"    [ERROR] {ingredient}: {e}")
        return []

    enriched = []
    for p in products:
        price = FoodstuffsEdgeAPI.extract_price(p)
        if price is None:
            continue
        enriched.append({
            "product_id": p.get("productID"),
            "name": FoodstuffsEdgeAPI.get_product_name(p),
            "size": FoodstuffsEdgeAPI.get_product_size(p),
            "price": price,
            "unit_price": FoodstuffsEdgeAPI.extract_unit_price(p),
            "is_promo": bool(p.get("promotions")),
        })
    return enriched


def pick_cheapest_per_unit(products: list[dict]) -> Optional[dict]:
    if not products:
        return None

    def parse_unit_price(up_str: str) -> Optional[float]:
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


def optimize_dish_edge(
    address: str,
    dish_name: str,
    brand: str = "paknsave",
    radius_km: float = 5.0,
    max_relevance: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    web_base = BRANDS[brand]["web_base"]
    title = brand.title()
    print("=" * 70)
    print(f"{title} Edge API Optimizer -- {dish_name.title()}")
    print("=" * 70)

    print(f"\n[1] Geocoding: {address}")
    user_lat, user_lon = geocode(address)
    if user_lat is None:
        raise ValueError(f"Could not geocode address: {address}")
    print(f"    Coordinates: {user_lat:.5f}, {user_lon:.5f}")

    print(f"\n[2] Finding {brand} stores within {radius_km} km...")
    nearby = find_nearby_stores(user_lat, user_lon, brand=brand, radius_km=radius_km)
    if not nearby:
        raise ValueError(f"No {brand} stores within {radius_km} km")
    print(f"    Found {len(nearby)} stores:")
    for s in nearby:
        print(f"      {s['name']:35s} {s['distance_km']:.1f} km  ({s.get('region', '?')})")

    print("\n[3] Authenticating with Edge API (website JWT)...")
    api = FoodstuffsEdgeAPI(brand=brand)
    api.authenticate()
    print("    Authenticated successfully")

    ingredients = get_ingredients(dish_name)
    print(f"\n[4] Dish: {dish_name.title()}")
    print(f"    Ingredients ({len(ingredients)}): {', '.join(ingredients)}")

    print("\n[5] Searching products (two-pass per ingredient per store)...")
    all_results = []

    for store in nearby:
        store_id = store["store_id"]
        store_name = store["name"]
        store_dist = store["distance_km"]
        region = store.get("region", "NI")

        print(f"\n  --- {store_name} ({store_dist:.1f} km, {region}) ---")
        store_total = 0.0
        found_count = 0

        for ing in ingredients:
            print(f"    Searching: {ing} ...", end=" ", flush=True)
            products = search_ingredient_at_store(api, store, ing, max_relevance)
            if products:
                best = pick_cheapest_per_unit(products)
                if best:
                    store_total += best["price"]
                    found_count += 1
                    unit_str = f" ({best['unit_price']})" if best["unit_price"] else ""
                    promo_str = "  [PROMO]" if best["is_promo"] else ""
                    name_display = best["name"][:MAX_DISPLAY] if len(best["name"]) > MAX_DISPLAY else best["name"]
                    print(f"${best['price']:.2f}{unit_str}{promo_str}  --  {name_display}")
                    all_results.append({
                        "store": store_name,
                        "store_id": store_id,
                        "brand": brand,
                        "distance_km": store_dist,
                        "region": region,
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
            time.sleep(0.08)

        print(f"    Subtotal: ${store_total:.2f}  ({found_count}/{len(ingredients)} found)")

    if not all_results:
        raise ValueError("No products found for any ingredient at any store")

    df = pd.DataFrame(all_results)

    summary_rows = []
    for store_name in df["store"].unique():
        store_df = df[df["store"] == store_name]
        cheapest_per_ing = store_df.loc[store_df.groupby("ingredient")["price"].idxmin()]
        total = cheapest_per_ing["price"].sum()
        found = len(cheapest_per_ing)
        dist = store_df["distance_km"].iloc[0]
        region = store_df["region"].iloc[0]
        summary_rows.append({
            "store": store_name,
            "brand": brand,
            "distance_km": dist,
            "region": region,
            "items_found": found,
            "total_cost": round(total, 2),
        })

    summary_df = pd.DataFrame(summary_rows).sort_values("total_cost").reset_index(drop=True)

    detail_rows = []
    for ing in ingredients:
        row = {"Ingredient": ing}
        for store_name in summary_df["store"]:
            match = df[(df["ingredient"] == ing) & (df["store"] == store_name)]
            if not match.empty:
                best = match.loc[match["price"].idxmin()]
                unit = f" ({best['unit_price']})" if best["unit_price"] else ""
                name_display = best["product_name"][:MAX_DISPLAY] if len(best["product_name"]) > MAX_DISPLAY else best["product_name"]
                row[store_name] = f"${best['price']:.2f}{unit} -- {name_display}"
            else:
                row[store_name] = "NOT FOUND"
        detail_rows.append(row)

    detail_df = pd.DataFrame(detail_rows).set_index("Ingredient")

    print("\n" + "=" * 70)
    print("COST COMPARISON (cheapest per-unit price at each store)")
    print("=" * 70)
    print(summary_df.to_string(index=False))

    best = summary_df.iloc[0]
    print(f"\n>>> CHEAPEST: {best['store']} ({brand}) -- ${best['total_cost']:.2f} total ({best['items_found']}/{len(ingredients)} items)")

    print("\n" + "=" * 70)
    print("DETAILED BREAKDOWN (cheapest product per ingredient per store)")
    print("=" * 70)
    print(detail_df.to_string())

    output_csv = OUTPUT_CSV[brand]
    df.to_csv(output_csv, index=False, encoding="utf-8")
    print(f"\n[OK] Full results saved to {output_csv}")

    return summary_df, detail_df


def main():
    if len(sys.argv) > 2:
        address = sys.argv[1]
        dish = sys.argv[2]
        brand = sys.argv[3] if len(sys.argv) > 3 else "paknsave"
    else:
        address = "Botany Town Centre, Auckland"
        dish = "spaghetti bolognese"
        brand = "newworld"

    if brand not in BRANDS:
        print(f"[ERROR] Unknown brand: '{brand}'. Choose from: {list(BRANDS.keys())}")
        sys.exit(1)

    try:
        optimize_dish_edge(address, dish, brand=brand)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()