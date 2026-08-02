"""
Woolworths NZ Meal Cost Optimizer
=================================
Queries the Woolworths backend for ingredient prices across nearby stores,
persists results to data/full_results.csv, and finds the cheapest
combination for a given dish.

Two phases:
    Phase 1 (query):  Geocode address → find nearby stores → search each
                      ingredient at each store → append rows to CSV
    Phase 2 (optimise): Read today's results from CSV → find best
                        per-store totals and best mix → print table

Usage:
    python woolworths_optimizer.py "<address>" "<dish>" [--requery false]

Flags:
    --requery true   (default) Query the API and append new results
    --requery false  Skip API calls, optimise from existing CSV data only

Examples:
    python woolworths_optimizer.py "123 Queen Street, Auckland CBD" "spaghetti bolognese"
    python woolworths_optimizer.py "123 Queen Street, Auckland CBD" "spaghetti bolognese" --requery false

Defaults (no args):
    Address: 123 Queen Street, Auckland CBD, 1010
    Dish:    spaghetti bolognese

Output:
    - Terminal: summary table (total cost per store) + per-ingredient breakdown
    - CSV:      data/full_results.csv (appended per run)

Dependencies: woolworths_api.py (imported as module), pandas

Reference: Woolworths_API.md, scripts/combined/structure.txt
"""

import csv
import hashlib
import re
import sys
from datetime import datetime, date
from pathlib import Path

import pandas as pd

from woolworths_api import (
    create_session,
    set_store_context,
    search_products,
    get_nearby_stores,
    geocode,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
RESULTS_FILE = DATA_DIR / "full_results.csv"

CSV_COLUMNS = [
    "company",
    "store",
    "store_id",
    "search_ingredient",
    "returned_ingredient",
    "price",
    "quantity",
    "measurement_unit",
    "per_unit_quantity",
    "per_unit_price",
    "is_sale",
    "sku",
    "category1",
    "department",
    "datetime_created",
    "date_created",
    "pk_hash",
]

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
    """Return the ingredient list for a dish, or [dish_name] if unknown (treats it as a single ingredient)."""
    return DISH_INGREDIENTS.get(dish_name.lower().strip(), [dish_name])


def get_quantities(dish_name):
    """Return the quantity dict for a dish, or {} if unknown (no quantity info available)."""
    return DISH_QUANTITIES.get(dish_name.lower().strip(), {})


def parse_volume_size(volume_size, cup_measure=""):
    """Parse a Woolworths volumeSize string into (quantity, measurement_unit).

    Falls back to cup_measure (e.g. "1kg", "1L") when volume_size is missing,
    null, or doesn't contain a number.

    Examples:
        ("500g", "")            -> (500, "g")         # volumeSize has number
        ("", "1kg")             -> (1, "kg")          # fallback to cupMeasure
        ("null", "1L")          -> (1, "L")           # volumeSize is "null"
        ("2 pack", "")          -> (2, "pack")        # multi-word unit
        ("for frying", "500ml") -> (500, "ml")        # no number, use fallback
        ("", "")                -> (None, "")         # both empty
    """
    # --- Try volume_size first ---
    if volume_size and isinstance(volume_size, str) and volume_size.strip().lower() != "null":
        raw = volume_size.strip()

        # Pattern 1: "500g", "1L", "250ml" — number directly adjacent to unit
        match = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]+)$", raw)
        if match:
            qty = float(match.group(1))
            unit = match.group(2).lower()
            return int(qty) if qty == int(qty) else qty, unit

        # Pattern 2: "2 pack", "6 eggs" — number followed by space + unit
        match = re.match(r"^(\d+(?:\.\d+)?)\s+(.+)$", raw)
        if match:
            qty = float(match.group(1))
            unit = match.group(2).lower()
            return int(qty) if qty == int(qty) else qty, unit

    # --- Fall back to cup_measure (e.g. "1kg", "1L") Assumes that the price is per 1 cup (Edge case may fail?). ---
    if cup_measure and isinstance(cup_measure, str):
        raw = cup_measure.strip()

        # Pattern 1: "1kg", "1L" — number directly adjacent to unit
        match = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]+)$", raw)
        if match:
            qty = float(match.group(1))
            unit = match.group(2).lower()
            return int(qty) if qty == int(qty) else qty, unit

        # Pattern 2: "1 kg" — number + space + unit
        match = re.match(r"^(\d+(?:\.\d+)?)\s+(.+)$", raw)
        if match:
            qty = float(match.group(1))
            unit = match.group(2).lower()
            return int(qty) if qty == int(qty) else qty, unit

    return None, ""


def _compute_pk_hash(store_id, sku, date_created):
    """Compute a SHA-256 hash of the composite primary key."""
    raw = f"{store_id}|{sku}|{date_created}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_existing_hashes(results_file):
    """Load existing pk_hash values from the CSV.

    Returns set of hash strings.
    """
    hashes = set()
    if not results_file.exists():
        return hashes
    with open(results_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            h = row.get("pk_hash", "")
            if h:
                hashes.add(h)
    return hashes


def append_rows(rows):
    """Append rows to full_results.csv, skipping duplicate pk_hashes.

    Args:
        rows: list of dicts with CSV column values (must include pk_hash)

    Returns:
        (appended, skipped) counts
    """
    if not rows:
        return 0, 0

    existing_hashes = load_existing_hashes(RESULTS_FILE)
    appended = 0
    skipped = 0

    file_exists = RESULTS_FILE.exists() and RESULTS_FILE.stat().st_size > 0

    with open(RESULTS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            h = row["pk_hash"]
            if h in existing_hashes:
                skipped += 1
                continue
            writer.writerow(row)
            existing_hashes.add(h)
            appended += 1

    return appended, skipped


def build_row(company, store, store_id, search_ingredient, product, now):
    """Build a CSV row dict from a product search result.

    Args:
        company: retailer name (e.g. "Woolworths")
        store: store name
        store_id: store's pickupAddressId
        search_ingredient: the ingredient term we searched for
        product: dict from search_products() (sku, name, salePrice, cupListPrice,
                 volumeSize, cupMeasure, isSpecial, department)
        now: datetime object for timestamps

    Returns:
        dict matching CSV_COLUMNS
    """
    quantity, measurement_unit = parse_volume_size(
        product.get("volumeSize", ""), product.get("cupMeasure", "")
    )
    date_created = now.strftime("%Y-%m-%d")
    sku = product.get("sku", "")
    return {
        "company": company,
        "store": store,
        "store_id": store_id,
        "search_ingredient": search_ingredient,
        "returned_ingredient": product.get("name", ""),
        "price": product.get("salePrice", ""),
        "quantity": quantity if quantity is not None else "",
        "measurement_unit": measurement_unit,
        "per_unit_quantity": product.get("cupMeasure", ""),
        "per_unit_price": product.get("cupListPrice", ""),
        "is_sale": product.get("isSpecial", False),
        "sku": sku,
        "category1": "",
        "department": product.get("department", ""),
        "datetime_created": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date_created": date_created,
        "pk_hash": _compute_pk_hash(store_id, sku, date_created),
    }


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


def query_and_save(user_address, dish_name, requery, max_dist_km=2):
    """Phase 1: Query the API and append results to CSV.

    Args:
        user_address: NZ address to geocode
        dish_name: dish to search ingredients for
        requery: if False, skip API and read existing CSV
        max_dist_km: maximum store search radius in km (default 2)

    Returns True if data is available (newly queried or already in CSV).
    """
    if not requery:
        if RESULTS_FILE.exists():
            return True
        print("No existing results file — run with --requery true to query the API")
        return False

    user_lat, user_lon = geocode(user_address)
    if user_lat is None:
        print(f"Error: Could not geocode address '{user_address}'")
        return False

    print(f"Geocoding: {user_address}")
    print(f"           lat: {user_lat:.6f}  lon: {user_lon:.6f}")
    print()

    nearby = get_nearby_stores(user_lat, user_lon, max_dist_km=max_dist_km)
    if not nearby:
        print(f"Error: No Woolworths stores found within {max_dist_km} km")
        return False

    print(f"Found {len(nearby)} stores within {max_dist_km} km:")
    for s in nearby:
        print(f"  {s['name']} ({s['distance_km']} km)")

    ingredients = get_ingredients(dish_name)
    print(f"\nDish: {dish_name}")
    print(f"Ingredients: {', '.join(ingredients)}")

    now = datetime.now()
    new_rows = []

    for store in nearby:
        store_name = store["name"]
        pid = store["pickupAddressId"]
        print(f"\n--- Store: {store_name} (id={pid}, {store['distance_km']} km) ---")

        session = create_session()
        try:
            ctx = set_store_context(session, pid)
            print(f"  Context set: {ctx['method']}, fulfilmentStoreId={ctx['fulfilmentStoreId']}")
        except RuntimeError as e:
            print(f"  [WARN] {e} -- skipping store")
            continue

        for ing in ingredients:
            print(f"  Searching: {ing}")
            products = search_products(session, ing, food_only=True)
            priced = [p for p in products if p.get("salePrice") is not None]
            if priced:
                for prod in priced:
                    row = build_row("Woolworths", store_name, pid, ing, prod, now)
                    new_rows.append(row)
                print(f"    {len(priced)} results (best: ${min(p['salePrice'] for p in priced):.2f})")
            else:
                print("    Not found")

    if not new_rows:
        print("\nNo results collected from API")
        return False

    appended, skipped = append_rows(new_rows)
    print(f"\nAppended {appended} rows to {RESULTS_FILE.name} ({skipped} duplicates skipped)")
    return True


def optimise(dish_name):
    """Phase 2: Read today's results from CSV and print comparison table."""
    if not RESULTS_FILE.exists():
        print(f"No results file found: {RESULTS_FILE}")
        return

    df = pd.read_csv(RESULTS_FILE)
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

    Usage: python woolworths_optimizer.py "<address>" "<dish>" [--requery false] [--distance 5]
    Defaults to 123 Queen Street, Auckland CBD / spaghetti bolognese / requery true / distance 2km.
    """
    address = "123 Queen Street, Auckland CBD, 1010"
    dish = "spaghetti bolognese"
    requery = True
    max_dist_km = 2

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
