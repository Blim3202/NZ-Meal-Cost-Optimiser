"""
Woolworths NZ Meal Cost Optimizer
==================================
Compares the total cost of cooking a dish across nearby Woolworths stores.

For a given NZ address and dish name, this script:
    1. Geocodes the address via Nominatim
    2. Finds all Woolworths stores within 5 km (haversine)
    3. For each store, creates a fresh session and injects per-store pricing
    4. Searches for each ingredient and selects the cheapest product
    5. Outputs a per-ingredient and total cost comparison table

The 21 hand-curated dishes and their ingredients are defined in DISH_INGREDIENTS
and DISH_QUANTITIES below. No NLP/LLM parsing yet.

Usage:
    python woolworths_optimizer.py "<address>" "<dish>" [output.csv]

Examples:
    python woolworths_optimizer.py "123 Queen Street, Auckland CBD" "spaghetti bolognese"
    python woolworths_optimizer.py "50 Parnell Road, Auckland" "chicken curry" results.csv

Defaults (no args):
    Address: 123 Queen Street, Auckland CBD, 1010
    Dish:    spaghetti bolognese

Output:
    - Terminal: summary table (total cost per store) + per-ingredient breakdown
    - CSV:      data/woolworths_latest_results.csv

Dependencies: woolworths_api.py (imported as module), pandas

Reference: Woolworths_API.md, Woolworths_API.md section 10 (production architecture)
"""

import sys
import pandas as pd
from woolworths_api import (
    create_session,
    set_store_context,
    search_products,
    find_cheapest,
    get_nearby_stores,
    geocode,
)

DISH_INGREDIENTS = {
    "spaghetti bolognese": ["beef mince", "spaghetti pasta", "canned tomatoes", "onion", "carrot", "garlic", "mixed herbs"],
    "chicken stir fry": ["chicken breast", "stir fry vegetables", "soy sauce", "rice noodles"],
    "beef stir fry": ["beef strips", "stir fry vegetables", "soy sauce", "rice noodles"],
    "roast lamb": ["lamb roast", "potato", "carrot", "broccoli", "stock"],
    "chicken curry": ["chicken thigh", "curry paste", "coconut milk", "rice", "onion"],
    "beef curry": ["diced beef", "curry paste", "coconut milk", "rice", "onion"],
    "fish and chips": ["fish fillet", "potato", "oil"],
    "nachos": ["beef mince", "tortilla chips", "cheese", "beans", "sour cream"],
    "pumpkin soup": ["pumpkin", "onion", "cream", "stock", "bread"],
    "tacos": ["beef mince", "taco shells", "lettuce", "tomato", "cheese", "sour cream"],
    "lamb chops": ["lamb chops", "potato", "mint sauce", "mixed vegetables"],
    "butter chicken": ["chicken thigh", "butter chicken sauce", "rice", "cream"],
    "lasagne": ["beef mince", "lasagne sheets", "cheese", "canned tomatoes", "milk", "butter", "flour"],
    "shepherd's pie": ["beef mince", "potato", "carrot", "peas", "stock"],
    "pizza": ["pizza base", "pizza sauce", "cheese", "pepperoni"],
    "vegie stir fry": ["stir fry vegetables", "tofu", "soy sauce", "rice noodles", "garlic"],
    "frittata": ["eggs", "potato", "onion", "cheese", "milk"],
    "pancakes": ["flour", "eggs", "milk", "sugar", "butter"],
    "chicken soup": ["chicken breast", "carrot", "onion", "celery", "stock", "pasta"],
    "tomato pasta": ["pasta", "canned tomatoes", "garlic", "olive oil", "mixed herbs", "cheese"],
    "chicken katsu": ["chicken breast", "flour", "eggs", "bread", "rice", "katsu sauce"],
}

DISH_QUANTITIES = {
    "spaghetti bolognese": {
        "beef mince": "500g",
        "spaghetti pasta": "400g",
        "canned tomatoes": "1 can (400g)",
        "onion": "1 medium",
        "carrot": "2 medium",
        "garlic": "2 cloves",
        "mixed herbs": "1 tsp",
    },
    "chicken stir fry": {
        "chicken breast": "2 fillets (~400g)",
        "stir fry vegetables": "1 bag (500g)",
        "soy sauce": "2 tbsp",
        "rice noodles": "250g",
    },
    "beef stir fry": {
        "beef strips": "400g",
        "stir fry vegetables": "1 bag (500g)",
        "soy sauce": "2 tbsp",
        "rice noodles": "250g",
    },
    "roast lamb": {
        "lamb roast": "1.2kg",
        "potato": "4 medium",
        "carrot": "3 medium",
        "broccoli": "1 head",
        "stock": "2 cups",
    },
    "chicken curry": {
        "chicken thigh": "500g",
        "curry paste": "2 tbsp",
        "coconut milk": "1 can (400ml)",
        "rice": "1.5 cups",
        "onion": "1 medium",
    },
    "beef curry": {
        "diced beef": "500g",
        "curry paste": "2 tbsp",
        "coconut milk": "1 can (400ml)",
        "rice": "1.5 cups",
        "onion": "1 medium",
    },
    "fish and chips": {
        "fish fillet": "2 fillets (~400g)",
        "potato": "4 medium",
        "oil": "for frying",
    },
    "nachos": {
        "beef mince": "300g",
        "tortilla chips": "1 bag (200g)",
        "cheese": "1 cup shredded",
        "beans": "1 can (400g)",
        "sour cream": "1/2 cup",
    },
    "pumpkin soup": {
        "pumpkin": "1kg",
        "onion": "1 medium",
        "cream": "1/2 cup",
        "stock": "2 cups",
        "bread": "4 slices",
    },
    "tacos": {
        "beef mince": "400g",
        "taco shells": "1 pack (12 shells)",
        "lettuce": "1/2 head",
        "tomato": "2 medium",
        "cheese": "1 cup shredded",
        "sour cream": "1/2 cup",
    },
    "lamb chops": {
        "lamb chops": "4 chops (~600g)",
        "potato": "4 medium",
        "mint sauce": "2 tbsp",
    },
    "butter chicken": {
        "chicken thigh": "500g",
        "butter chicken sauce": "1 jar",
        "rice": "1.5 cups",
        "cream": "1/2 cup",
    },
    "lasagne": {
        "beef mince": "500g",
        "lasagne sheets": "1 pack",
        "cheese": "1 cup shredded",
        "canned tomatoes": "1 can (400g)",
        "milk": "1 cup",
        "butter": "2 tbsp",
        "flour": "2 tbsp",
    },
    "shepherd's pie": {
        "beef mince": "500g",
        "potato": "4 medium",
        "carrot": "2 medium",
        "peas": "1 cup",
        "stock": "1/2 cup",
    },
    "pizza": {
        "pizza base": "1 base",
        "pizza sauce": "1/2 cup",
        "cheese": "1.5 cups shredded",
        "pepperoni": "1 pack",
    },
    "vegie stir fry": {
        "stir fry vegetables": "1 bag (500g)",
        "tofu": "1 block (400g)",
        "soy sauce": "2 tbsp",
        "rice noodles": "250g",
        "garlic": "2 cloves",
    },
    "frittata": {
        "eggs": "6 eggs",
        "potato": "2 medium",
        "onion": "1 medium",
        "cheese": "1 cup shredded",
        "milk": "1/4 cup",
    },
    "pancakes": {
        "flour": "1.5 cups",
        "eggs": "1 egg",
        "milk": "1 cup",
        "sugar": "2 tbsp",
        "butter": "2 tbsp",
    },
    "chicken soup": {
        "chicken breast": "2 fillets (~400g)",
        "carrot": "2 medium",
        "onion": "1 medium",
        "celery": "2 stalks",
        "stock": "4 cups",
        "pasta": "1 cup",
    },
    "tomato pasta": {
        "pasta": "400g",
        "canned tomatoes": "1 can (400g)",
        "garlic": "2 cloves",
        "olive oil": "2 tbsp",
        "mixed herbs": "1 tsp",
        "cheese": "1/4 cup grated",
    },
    "chicken katsu": {
        "chicken breast": "2 fillets (~400g)",
        "flour": "1/2 cup",
        "eggs": "2 eggs",
        "bread": "1 cup breadcrumbs",
        "rice": "1.5 cups",
        "katsu sauce": "1/3 cup",
    },
}


def get_ingredients(dish_name):
    return DISH_INGREDIENTS.get(dish_name.lower().strip(), [dish_name])


def get_quantities(dish_name):
    return DISH_QUANTITIES.get(dish_name.lower().strip(), {})


def analyze_results(df, ingredients, dish_name):
    df["price_float"] = df["price"].astype(float)

    cheapest_per_ing_per_store = (
        df.groupby(["store", "ingredient"])["price_float"].min().reset_index()
    )
    summary = (
        cheapest_per_ing_per_store.groupby("store")["price_float"]
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
            match = df[(df["ingredient"] == ing) & (df["store"] == sn)]
            if not match.empty:
                best_prod = match.loc[match["price_float"].idxmin()]
                row[sn] = f"${best_prod['price_float']:.2f} ({best_prod['unitPrice']})"
            else:
                row[sn] = "NOT FOUND"

        prices = []
        for sn in store_names:
            match = df[(df["ingredient"] == ing) & (df["store"] == sn)]
            if not match.empty:
                prices.append(
                    (sn, match.loc[match["price_float"].idxmin()]["price_float"])
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
            df[df["store"] == sn].groupby("ingredient")["price_float"].min().sum()
        )
        totals[sn] = f"${store_total:.2f}"

    best_total_mix = 0
    for ing in ingredients:
        ing_prices = df[df["ingredient"] == ing]["price_float"]
        if not ing_prices.empty:
            best_total_mix += ing_prices.min()

    totals["Best Price"] = f"${best_total_mix:.2f}"
    totals["Best Store"] = "(mix)"
    table.loc["TOTAL"] = totals

    return summary, table


def main():
    if len(sys.argv) > 2:
        USER_ADDRESS = sys.argv[1]
        DISH_NAME = sys.argv[2]
        OUTPUT_FILE = sys.argv[3] if len(sys.argv) > 3 else "data/woolworths_latest_results.csv"
    else:
        USER_ADDRESS = "123 Queen Street, Auckland CBD, 1010"
        DISH_NAME = "spaghetti bolognese"
        OUTPUT_FILE = "data/woolworths_latest_results"

    user_lat, user_lon = geocode(USER_ADDRESS)
    if user_lat is None:
        print(f"Error: Could not geocode address '{USER_ADDRESS}'")
        sys.exit(1)

    nearby = get_nearby_stores(user_lat, user_lon, max_dist_km=2)
    if not nearby:
        print("Error: No Woolworths stores found within 2 km")
        sys.exit(1)

    print(f"Found {len(nearby)} stores within 2 km:")
    for s in nearby:
        print(f"  {s['name']} ({s['distance_km']} km)")

    ingredients = get_ingredients(DISH_NAME)
    quantities = get_quantities(DISH_NAME)
    print(f"\nDish: {DISH_NAME}")
    print(f"Ingredients: {', '.join(ingredients)}")

    all_data = []

    for store in nearby:
        store_name = store["name"]
        pid = store["pickupAddressId"]
        print(f"\n--- Store: {store_name} (id={pid}, {store['distance_km']} km) ---")

        session = create_session()
        try:
            ctx = set_store_context(session, pid)
            print(f"  Context set: {ctx['method']}, fulfilmentStoreId={ctx['fulfilmentStoreId']}")
        except RuntimeError as e:
            print(f"  [WARN] {e} — skipping store")
            continue

        for ing in ingredients:
            print(f"  Searching: {ing}")
            cheapest = find_cheapest(session, ing, food_only=True)
            if cheapest:
                all_data.append({
                    "store": store_name,
                    "ingredient": ing,
                    "name": cheapest["name"],
                    "price": cheapest["salePrice"],
                    "unitPrice": cheapest["unitPrice"],
                    "volumeSize": cheapest["volumeSize"],
                    "sku": cheapest["sku"],
                })
                vol = f" [{cheapest['volumeSize']}]" if cheapest["volumeSize"] else ""
                print(
                    # f"    ${cheapest['salePrice']:.2f} — {cheapest['name'][:50]} {vol} ({cheapest['unitPrice']})"
                    f"    ${cheapest['salePrice']:.2f} — {cheapest['name'][:50]} {vol}"
                )
            else:
                print("    Not found")

    if not all_data:
        print("\nNo results collected")
        sys.exit(1)

    df = pd.DataFrame(all_data)
    summary, table = analyze_results(df, ingredients, DISH_NAME)

    print("\n" + "=" * 70)
    print(f"TOTAL COST COMPARISON — {DISH_NAME.upper()}")
    print("=" * 70)
    print(summary.to_string())
    print("\n" + "=" * 70)
    print("PER-INGREDIENT BREAKDOWN")
    print("=" * 70)
    print(table.to_string())

    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\nResults saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
