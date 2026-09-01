"""
Shared optimiser Utilities
==========================
Common functions and constants for all retailer optimisers (Woolworths, Pak'nSave, New World).
Both optimisers write to the same data/full_results.csv with identical column structure.
"""

import csv
import hashlib
import math
import re
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

from NZMealOptimiser import DATA_DIR

RESULTS_FILE = DATA_DIR / "full_results.csv"

CSV_COLUMNS = [
    "company",
    "store",
    "store_id",
    "search_ingredient",
    "returned_ingredient",
    "brand",
    "price",
    "quantity",
    "measurement_unit",
    "per_unit_quantity",
    "per_unit_price",
    "is_sale",
    "sku",
    "department",
    "sub_department",
    "datetime_created",
    "date_created",
    "pk_hash",
    "is_valid",
]

BRAND_FALLBACKS = {
    "PaknSave": "Pak'nSave",
    "NewWorld": "New World",
    "Woolworths": "Woolworths",
}

DISHES_FILE = DATA_DIR / "dishes.json"


def _load_dishes() -> dict:
    import json
    with open(DISHES_FILE, "r") as f:
        return json.load(f)


DISHES = _load_dishes()


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    # Haversine formula: a = sin²(Δlat/2) + cos(lat1)·cos(lat2)·sin²(Δlon/2)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def geocode(address):
    """Geocode a NZ address via Nominatim. Returns (lat, lon) or (None, None)."""
    time.sleep(1.1)  # respect Nominatim rate limit (1 req/sec)
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            headers={"User-Agent": "NZMealCostOptimiser/1.0"},
            params={"q": address, "format": "json", "limit": 1},
            timeout=15,
        )
        if r.status_code == 200 and r.json():
            loc = r.json()[0]
            return float(loc["lat"]), float(loc["lon"])
    except Exception:
        pass
    return None, None


def get_ingredients(dish_name):
    """Get search-term ingredient list for a dish from the DISHES dict.

    Returns a list of search_term strings for the dish, or [dish_name]
    if the dish is not in the curated DISHES set.
    """
    dish_dict = DISHES.get(dish_name.lower().strip())
    if dish_dict:
        return [ing["search_term"] for ing in dish_dict["ingredients"]]
    return [dish_name]


def _build_quantity_map(dish):
    """Build a {search_term: quantity_string} map from a dish dict's ingredients.

    Args:
        dish: a string (dish name) or a dict with 'ingredients' list.

    Returns:
        dict mapping search_term -> "quantity unit" string (e.g. "500 g")
    """
    dish_dict = _resolve_dish_data(dish)
    quantities = {}
    for ing in dish_dict.get("ingredients", []):
        if isinstance(ing, dict):
            term = ing.get("search_term", "")
            qty = ing.get("quantity", "")
            unit = ing.get("unit", "")
            if term:
                base = f"{qty} {unit}".strip()
                approx_q = ing.get("approx_quantity")
                approx_u = ing.get("approx_unit")
                if approx_q and approx_u:
                    approx = f"{approx_q} {approx_u}".strip()
                    base = f"{base} (~{approx})" if base else f"~{approx}"
                quantities[term] = base
    return quantities


def _resolve_dish_data(dish):
    """Resolve a dish name (string) to a full dish dict from DISHES.

    Args:
        dish: a string (dish name) or a dict with 'dish_name' and 'ingredients'.

    Returns:
        A dish dict with keys: dish_name, portion, ingredients (list of
        {quantity, unit, search_term} dicts). If a string is passed and
        the dish is in DISHES, returns the curated dict. Otherwise wraps
        the string into a minimal dict.
    """
    if isinstance(dish, dict):
        return dish
    dish_key = dish.lower().strip() if isinstance(dish, str) else ""
    if dish_key in DISHES:
        return DISHES[dish_key]
    return {"dish_name": dish, "portion": 4, "ingredients": []}


def _resolve_dish_terms(dish):
    """Extract (dish_name, search_terms) from str or dict input.

    Args:
        dish:   either a string (dish name, resolved from DISHES) 
                or a dict with keys 'dish_name' and 'ingredients'.
    Returns:
        (dish_name: str, search_terms: list[str])
    Raises:
        ValueError: if dish input format is invalid.
    """
    if isinstance(dish, str):
        # Lookup string in curated dishes
        dish_key = dish.lower().strip()
        if dish_key in DISHES:
            return DISHES[dish_key]["dish_name"], get_ingredients(dish)
        raise ValueError(f"Dish string '{dish}' not found in registry.")

    if isinstance(dish, dict):
        # Validate required keys
        if "dish_name" not in dish or "ingredients" not in dish:
            raise ValueError("Dict dish must have 'dish_name' and 'ingredients' keys.")
        
        # Validate ingredients structure
        ingredients = dish["ingredients"]
        if not isinstance(ingredients, list) or not all(isinstance(i, dict) and "search_term" in i for i in ingredients):
            raise ValueError("Ingredients must be a list of dicts with a 'search_term' key.")  
        
        return dish["dish_name"], [i["search_term"] for i in ingredients]

    raise ValueError("Input must be a dish name (str) or a structured dish (dict).")


def parse_foodstuffs_volume_size(display_name, single_price, promotions):
    """Parse a Foodstuffs product into (quantity, measurement_unit, per_unit_quantity, per_unit_price).

    Uses measureDescription for per_unit_quantity when available (e.g. "100g", "1kg", "ea")
    instead of just the unit abbreviation.

    Args:
        display_name: product's displayName (e.g. "ea", "500g", "kg", "2l")
        single_price: singlePrice object from API response (dict with "price" and optional "comparativePrice")
        promotions: promotions list from API response (array of dicts)

    Returns:
        (quantity, measurement_unit, per_unit_quantity, per_unit_price)
        where per_unit_price is in dollars. Returns (None, "", "", "") on failure.

    Examples:
        # Carrot cake: displayName="1.4kg", comparativePrice with measureDescription="100g"
        ("1.4kg", {"price":3399, "comparativePrice":{"pricePerUnit":243,"unitQuantityUom":"g","measureDescription":"100g"}}, [])
        -> (1.4, "kg", "100g", 2.43)

        # Spring onions: displayName="ea", promotion with measureDescription="ea"
        ("ea", {"price":199}, [{"comparativePrice":{"pricePerUnit":167,"measureDescription":"ea"}}])
        -> (1, "ea", "ea", 1.67)

        # Carrots: displayName="kg", comparativePrice with measureDescription="1kg"
        ("kg", {"price":188, "comparativePrice":{"pricePerUnit":188,"unitQuantityUom":"kg","measureDescription":"1kg"}}, [])
        -> (1, "kg", "1kg", 1.88)
    """
    # 1. Parse displayName for quantity and unit
    quantity, measurement_unit = _parse_display_name(display_name)

    # 2. Find best comparativePrice (from promotions first, then singlePrice)
    #    Promotions comparativePrice takes priority (e.g. spring onions promo)
    comp = None
    if promotions:
        for p in promotions:
            if p.get("comparativePrice"):
                comp = p["comparativePrice"]
                break
    if not comp and single_price:
        comp = single_price.get("comparativePrice")

    # 3. Determine per_unit values
    #    Use measureDescription (e.g. "100g", "1kg") for per_unit_quantity when available
    #    Fall back to unitQuantityUom, then measurement_unit
    if comp:
        per_unit_qty = comp.get("measureDescription") or comp.get("unitQuantityUom") or measurement_unit
        price_per_unit = comp.get("pricePerUnit")
        per_unit_price = price_per_unit / 100.0 if price_per_unit is not None else 0
    else:
        # No comparativePrice — whole unit item (e.g. loose carrots with no pricePerUnit)
        per_unit_qty = measurement_unit
        per_unit_price = (single_price.get("price", 0) / 100.0) if single_price else 0

    return quantity, measurement_unit, per_unit_qty, per_unit_price


def parse_foodstuffs_mobile_unit(units, unit_price, price_cents=None):
    """Parse Foodstuffs Mobile API `units` and `unitPrice` strings.

    Combines the two splitting jobs for a mobile product into one helper so the
    caller gets (quantity, measurement_unit, per_unit_quantity, per_unit_price)
    in a single call — matching the edge pipeline's parse_foodstuffs_volume_size
    tuple.

    1) Units split (quantity + measurement_unit):
       The mobile `units` string packs the item count and the measure together,
       e.g. "3 x 31g", "500g", "2 pack", "ea". The leading numeric count becomes
       `quantity`; the remainder becomes `measurement_unit`.

       Edge case — sachet/pack like "3 x 31g":
           The integer before the 'x' is the pack/sachet count (→ quantity).
           The text including and after the 'x' becomes the measurement, with the
           space that sat between the count and the 'x' stripped ("x 31g").

    2) `unitPrice` (per_unit_quantity + per_unit_price):
       Splits on '/': per_unit_price is the value before the slash (dollar sign
       stripped), per_unit_quantity is the value after the slash.

        Fallback — no `unitPrice` but `units` has a numeric count (e.g. "1pk",
        "500g", "2 pack") or bare "ea": use `measurement_unit` as
        `per_unit_quantity` and mirror the item's own `price_cents` into
        `per_unit_price` so the per-unit columns never go blank.

    Examples:
        ("3 x 31g", "$26.99/1kg") -> (3, "x 31g", "1kg", 26.99)
        ("500g", "$18.99/kg")     -> (500, "g", "kg", 18.99)
        ("2 pack", "$3.49/ea")    -> (2, "pack", "ea", 3.49)
        ("1pk", "", 299)           -> (1, "pk", "pk", 2.99)  # no unitPrice, infer from price_cents
        ("ea", "", 250)           -> (1, "ea", "ea", 2.5)   # fallback, no unitPrice
        ("ea", "")                -> (1, "ea", "ea", 0)     # fallback, no price known
        ("", "")                  -> ("", "", "", 0)

    Args:
        units: Mobile API `units` field (e.g. "3 x 31g", "500g", "ea").
        unit_price: Mobile API `unitPrice` formatted string (e.g. "$26.99/1kg").
        price_cents: Item price in cents (from `product["price"]`), used for
            the fallback when `unitPrice` is missing so per_unit_price
            can mirror the item price.

    Returns:
        (quantity, measurement_unit, per_unit_quantity, per_unit_price).
        quantity is int/float when a count is found, else "" (keeps the CSV
        column blank, matching edge rows). per_unit_price is in dollars.
    """
    # Map a numeric count to int when whole, else keep float. Mirrors edge.
    def _clean(qty):
        return int(qty) if qty == int(qty) else qty

    # --- 1) Split `units` into quantity + measurement_unit ---
    quantity, measurement_unit = "", ""
    if units and isinstance(units, str):
        raw = units.strip()
        if raw and raw.lower() != "null":
            # Edge case: sachet/pack like "3 x 31g". Quantity = leading count;
            # measurement keeps the 'x' but strips the space before it.
            match = re.match(r"^(\d+(?:\.\d+)?)\s*[xX]\s*(\S.*)$", raw)
            if match:
                quantity = _clean(float(match.group(1)))
                measurement_unit = "x " + match.group(2).strip()
            # Pattern 1: "500g", "1L", "250ml" — number directly adjacent to unit
            elif (match := re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]+)$", raw)):
                quantity = _clean(float(match.group(1)))
                measurement_unit = match.group(2).lower()
            # Pattern 2: "2 pack", "6 eggs" — number followed by space + unit
            elif (match := re.match(r"^(\d+(?:\.\d+)?)\s+(.+)$", raw)):
                quantity = _clean(float(match.group(1)))
                measurement_unit = match.group(2).lower().strip()
            # Pattern 3: "ea", "kg", "L" — unit only, no count → default to 1
            elif re.match(r"^[a-zA-Z]+$", raw):
                quantity, measurement_unit = 1, raw.lower()

    # --- 2) Split `unit_price` into per_unit_quantity + per_unit_price ---
    per_unit_qty, per_unit_price = "", 0
    if unit_price and isinstance(unit_price, str):
        if "/" in unit_price:
            price_part, qty_part = unit_price.split("/", 1)
        else:
            price_part, qty_part = unit_price, ""

        price_part = price_part.replace("$", "").strip()
        try:
            per_unit_price = float(price_part)
        except ValueError:
            per_unit_price = 0
        per_unit_qty = qty_part.strip()

    # Fallback: no unitPrice but units has a numeric count → per-unit at item's own price.
    # Avoids blank per_unit columns (per_unit_price mirrors `price`).
    # Covers "1pk", "500g", "2 pack", bare "ea", etc.
    if not per_unit_qty and measurement_unit and price_cents is not None:
        per_unit_qty = measurement_unit
        per_unit_price = price_cents / 100.0

    return quantity, measurement_unit, per_unit_qty, per_unit_price


def parse_woolworths_volume_size(volume_size, cup_measure=""):
    """Parse a Woolworths volumeSize string into (quantity, measurement_unit).

    Falls back to cup_measure (e.g. "1kg", "1L") when volume_size is missing,
    null, or doesn't contain a number.

    Examples:
        ("500g", "")            -> (500, "g")         # volumeSize has number
        ("", "1kg")             -> (1, "kg")          # fallback to cupMeasure
        ("null", "1L")          -> (1, "l")           # volumeSize is "null"
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


def _parse_display_name(display_name):
    """Parse a Pak'nSave displayName string into (quantity, measurement_unit).

    Examples:
        "ea"   -> (1, "ea")
        "500g" -> (500, "g")
        "kg"   -> (1, "kg")
        "2l"   -> (2, "l")
        ""     -> (None, "")
    """
    if not display_name or not isinstance(display_name, str):
        return None, ""

    raw = display_name.strip()
    if not raw or raw.lower() == "null":
        return None, ""

    # Pattern 1: "500g", "1L", "2l" — number directly adjacent to unit
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

    # Pattern 3: "ea", "kg", "L" — unit only, no number → default to 1
    match = re.match(r"^([a-zA-Z]+)$", raw)
    if match:
        return 1, raw.lower()

    return None, ""


def _normalize_per_unit_qty(per_unit_qty):
    """Strip a redundant leading "1" from count-based per-unit quantities.

    Woolworths supplies cupMeasure values like "1ea" while Foodstuffs uses
    bare "ea"; normalising keeps the per_unit_quantity column consistent
    across retailers. Weight/volume measures ("1kg", "1L", "100g") carry a
    meaningful count and are left untouched. Empty/None returns "".
    """
    if not per_unit_qty or not isinstance(per_unit_qty, str):
        return ""
    match = re.match(r"^1\s*(ea|each)$", per_unit_qty.strip(), re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return per_unit_qty


def _normalize_brand(brand):
    """Capitalise the first character of a brand string ("anchor" -> "Anchor").

    Woolworths supplies lowercase brand slugs while Foodstuffs supplies
    proper-case names; normalising at row-build time keeps the brand column
    consistent across retailers. Empty/None values return "".
    """
    if not brand:
        return ""
    return brand[:1].upper() + brand[1:]


def _compute_pk_hash(store_id, sku, date_created):
    """Compute a SHA-256 hash of the composite primary key."""
    raw = f"{store_id}|{sku}|{date_created}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_existing_hashes(results_file=None):
    """Load existing pk_hash values from the CSV.

    Returns set of hash strings.
    """
    if results_file is None:
        results_file = RESULTS_FILE
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


def append_rows(rows, results_file=None):
    """Append rows to full_results.csv, skipping duplicate pk_hashes.

    Args:
        rows: list of dicts with CSV column values (must include pk_hash)
        results_file: optional override (default: RESULTS_FILE)

    Returns:
        (appended, skipped) counts
    """
    if not rows:
        return 0, 0

    if results_file is None:
        results_file = RESULTS_FILE

    existing_hashes = load_existing_hashes(results_file)
    appended = 0
    skipped = 0

    file_exists = results_file.exists() and results_file.stat().st_size > 0

    with open(results_file, "a", newline="", encoding="utf-8") as f:
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


def build_edge_row(company, store, store_id, search_ingredient, product, pass1_hit, now):
    """Build a CSV row dict from an Edge API product (Pak'nSave or New World).

    Args:
        company: retailer name (e.g. "PaknSave" or "NewWorld")
        store: store name
        store_id: store UUID
        search_ingredient: the ingredient term we searched for
        product: dict from Pass 2 (singlePrice, promotions, productId, etc.)
        pass1_hit: dict from Pass 1 (category0, category1, _highlightResult) or None
        now: datetime object for timestamps

    Returns:
        dict matching CSV_COLUMNS
    """
    sp = product.get("singlePrice", {})
    promotions = product.get("promotions") or []

    quantity, measurement_unit, per_unit_qty, per_unit_price = parse_foodstuffs_volume_size(
        product.get("displayName", ""),
        sp,
        promotions,
    )

    price_cents = sp.get("price")
    if promotions:
        best = promotions[0]
        reward = best.get("rewardValue")
        threshold = best.get("threshold")
        if reward is not None and threshold and threshold > 0:
            price_cents = reward / threshold

    price_dollars = round(price_cents / 100.0, 2) if price_cents is not None else ""

    cat0 = pass1_hit.get("category0", []) if pass1_hit else []
    cat1 = pass1_hit.get("category1", []) if pass1_hit else []
    dept_str = "|".join(cat0) if cat0 else ""
    cat1_str = "|".join(cat1) if cat1 else ""

    sku = product.get("productId", "")
    date_str = now.strftime("%Y-%m-%d")

    return {
        "company": company,
        "store": store,
        "store_id": store_id,
        "search_ingredient": search_ingredient,
        "returned_ingredient": product.get("name", ""),
        "brand": _normalize_brand(
            product.get("brand")
            or (pass1_hit or {}).get("brand")
            or BRAND_FALLBACKS.get(company, "")
        ),
        "price": price_dollars,
        "quantity": quantity if quantity is not None else "",
        "measurement_unit": measurement_unit,
        "per_unit_quantity": _normalize_per_unit_qty(per_unit_qty),
        "per_unit_price": per_unit_price if per_unit_price else "",
        "is_sale": bool(promotions),
        "sku": sku,
        "department": dept_str,
        "sub_department": cat1_str,
        "datetime_created": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date_created": date_str,
        "pk_hash": _compute_pk_hash(store_id, sku, date_str),
    }


def build_mobile_row(company, store, store_id, search_ingredient, product, now):
    """Build a CSV row dict from a Foodstuffs Mobile API product.

    Used by both Pak'nSave and New World — the two brand optimisers'
    `build_row` were byte-identical apart from the `company` label, so a
    single shared implementation replaces both.

    Mobile API field shape:
      - `units` packs the "count + measure" together (e.g. "3 x 31g"), and
        `unitPrice` is a formatted string (e.g. "$18.99/kg").
      - `parse_foodstuffs_mobile_unit` splits both in one call → quantity,
        measurement_unit, per_unit_quantity, per_unit_price. It handles the
        sachet/pack edge case "3 x 31g" → quantity=3, measurement_unit="x 31g",
        and the bare-"ea" fallback (no unitPrice) where per_unit_qty="ea" and
        per_unit_price mirrors the item's own price (passed as `price_cents`)
        so the per-unit columns aren't blank.
      - `categories` = [category1 (sub_department), category2 (subsub_department)].
        There is no department (category0) in the mobile response, so the
        `department` column is left blank. (Future: the department could be
        reverse-engineered from the sub_department via the store's category tree.)

    Args:
        company: retailer name (e.g. "PaknSave" or "NewWorld")
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
        "brand": _normalize_brand(product.get("brand") or BRAND_FALLBACKS.get(company, "")),
        "price": price_dollars,
        "quantity": quantity,
        "measurement_unit": measurement_unit,
        "per_unit_quantity": _normalize_per_unit_qty(per_unit_qty),
        "per_unit_price": per_unit_price if per_unit_price else "",
        "is_sale": False,
        "sku": sku,
        "department": department,
        "sub_department": sub_department,
        "datetime_created": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date_created": date_str,
        "pk_hash": _compute_pk_hash(store_id, sku, date_str),
    }


def build_woolworths_row(company, store, store_id, search_ingredient, product, now):
    """Build a CSV row dict from a Woolworths product search result.

    Args:
        company: retailer name (e.g. "Woolworths")
        store: store name
        store_id: store's canonical id = extra1 (fulfilmentStoreId), the same
                  value baked into the cw-lrkswrdjp cookie (`f-{store_id}`)
        search_ingredient: the ingredient term we searched for
        product: dict from search_products() (sku, name, brand, salePrice,
                 cupListPrice, volumeSize, cupMeasure, isSpecial, department)
        now: datetime object for timestamps

    Returns:
        dict matching CSV_COLUMNS
    """
    quantity, measurement_unit = parse_woolworths_volume_size(
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
        "brand": _normalize_brand(product.get("brand") or BRAND_FALLBACKS.get(company, "")),
        "price": product.get("salePrice", ""),
        "quantity": quantity if quantity is not None else "",
        "measurement_unit": measurement_unit,
        "per_unit_quantity": _normalize_per_unit_qty(product.get("cupMeasure", "")),
        "per_unit_price": product.get("cupListPrice", ""),
        "is_sale": product.get("isSpecial", False),
        "sku": sku,
        "department": product.get("department", ""),
        "sub_department": "",
        "datetime_created": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date_created": date_created,
        "pk_hash": _compute_pk_hash(store_id, sku, date_created),
    }


# ── Ingredient include/exclude keyword filters (data/dish_filters.json) ──────

def levenshtein(s1: str, s2: str) -> int:
    """Pure-python Levenshtein distance."""
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous[j + 1] + 1
            deletions = current[j] + 1
            substitutions = previous[j] + (c1 != c2)
            current.append(min(insertions, deletions, substitutions))
        previous = current
    return previous[-1]


def word_matches(haystack_word: str, needle_word: str, max_ratio: float = 0.35) -> bool:
    """True if two words fuzzy-match (Levenshtein ratio <= max_ratio, or exact).

    The ratio tolerance absorbs singular/plural and small spelling variants
    ("carrot" vs "carrots", "tomato" vs "tomatoes") without a stemmer.
    """
    if haystack_word == needle_word:
        return True
    d = levenshtein(haystack_word, needle_word)
    max_len = max(len(haystack_word), len(needle_word))
    if max_len == 0:
        return True
    return (d / max_len) <= max_ratio


def contains_word(haystack: str, needle: str) -> bool:
    """Multi-word aware fuzzy match of ``needle`` inside ``haystack``.

    For single words: any word in the haystack within ratio 0.35 passes.
    For multi-word needles: ALL words must fuzzy-match somewhere in the title.
    Apostrophes are stripped so "Pak'nSave" matches "Pak'nSave" and "paknsave".
    """
    def _norm(text: str) -> str:
        return text.lower().replace("'", "").replace("\u2019", "").replace("`", "")

    needle_norm = _norm(needle).strip()
    if not needle_norm:
        return True
    haystack_words = re.findall(r"[a-z]+", _norm(haystack))
    needle_words = re.findall(r"[a-z]+", needle_norm)
    if not needle_words:
        return True
    for n_word in needle_words:
        if not any(word_matches(hw, n_word) for hw in haystack_words):
            return False
    return True


def matches_ingredient_filters(returned_title: str, includes: list[str], excludes: list[str]) -> tuple[bool, str]:
    """Apply one ingredient's include/exclude keywords to a product title.

    Returns ``(passed, reason)``. A product passes when EVERY include keyword
    matches (AND semantics; vacuously true when no includes are set) AND no
    exclude keyword matches. Mirrors the exploration matcher so curated rules
    in dish_filters.json and user-edited rules behave identically at runtime.
    """
    if includes:
        missing = [inc for inc in includes if not contains_word(returned_title, inc)]
        if missing:
            return False, f"INCLUDE missing {missing}"
    matched_excludes = [exc for exc in excludes if contains_word(returned_title, exc)]
    if matched_excludes:
        return False, f"EXCLUDE hit: {matched_excludes}"
    return True, ""


def matches_brand_filters(brand: str, brand_includes: list[str], brand_excludes: list[str]) -> tuple[bool, str]:
    """Apply one ingredient's brand include/exclude keywords to a product brand.

    Returns ``(passed, reason)``. Unlike the title matcher (AND across includes),
    the brand include list uses OR semantics — a row passes when at least one
    include matches, mirroring how users think about brand preferences ("I want
    Pams OR Watties"). The exclude list still rejects on any match. Both
    lists reuse ``contains_word`` for consistency with the title matcher (same
    Levenshtein ratio <= 0.35 tolerance, case-insensitive, partial-word
    matches like "odd" ~ "The Odd Bunch").
    """
    if brand_includes:
        if not any(contains_word(brand, inc) for inc in brand_includes):
            return False, f"BRAND include missed (need one of {brand_includes})"
    matched_excludes = [exc for exc in brand_excludes if contains_word(brand, exc)]
    if matched_excludes:
        return False, f"BRAND exclude hit: {matched_excludes}"
    return True, ""


def foodstuffs_querier_edge(api_class, find_nearby_stores, company_id, company_name,
                            user_address, dish_name, requery, max_dist_km=5.0):
    """Phase 1 (query): shared Edge API pipeline for Pak'nSave and New World.

    Queries the Foodstuffs Edge API for product pricing across nearby stores and
    appends results to the CSV. The two brand CLIs (paknsave_optimiser_edge.py,
    newworld_optimiser_edge.py) are identical except for the API class, store
    finder, and company label.

    Args:
        api_class: the Edge API class to instantiate and authenticate
            (PaknSaveEdgeAPI or NewWorldEdgeAPI)
        find_nearby_stores: the API module's find_nearby_stores function
        company_id: CSV company value written to rows (e.g. "PaknSave", "NewWorld")
        company_name: display name for print lines (e.g. "Pak'nSave", "New World")
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
        print(f"Error: No {company_name} stores found within {max_dist_km} km")
        return False

    print(f"Found {len(nearby)} stores within {max_dist_km} km:")
    for s in nearby:
        print(f"  {s['name']:35s} {s['distance_km']:.1f} km")

    print("\nAuthenticating with Edge API (website JWT)...")
    api = api_class()
    api.authenticate()
    print("    Authenticated successfully")

    dish_name, ingredients = _resolve_dish_terms(dish_name)
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
                time.sleep(0.1)
                continue

            pass1_by_id = {h["productID"]: h for h in pass1_hits}

            priced = []
            for prod in products:
                row = build_edge_row(
                    company_id, store_name, store_id, ing,
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


def foodstuffs_querier_mobile(api_class, find_nearby_stores_fn, company_id, company_name,
                              user_address, dish_name, requery, max_dist_km=5.0):
    """Phase 1 (query): shared Mobile API pipeline for Pak'nSave and New World.

    Queries the Foodstuffs Mobile API for product pricing across nearby stores and
    appends results to the CSV. The two brand CLIs (paknsave_optimiser_mobile.py,
    newworld_optimiser_mobile.py) are identical except for the API class, store
    finder, and company label.

    Args:
        api_class: the Mobile API class to instantiate and authenticate
            (PaknSaveMobileAPI or NewWorldMobileAPI)
        find_nearby_stores_fn: the API module's find_nearby_stores function
        company_id: CSV company value written to rows (e.g. "PaknSave", "NewWorld")
        company_name: display name for print lines (e.g. "Pak'nSave", "New World")
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

    nearby = find_nearby_stores_fn(user_lat, user_lon, radius_km=max_dist_km)
    if not nearby:
        print(f"Error: No {company_name} stores found within {max_dist_km} km")
        return False

    print(f"Found {len(nearby)} stores within {max_dist_km} km:")
    for s in nearby:
        print(f"  {s['name']:35s} {s['distance_km']:.1f} km")

    print("\nAuthenticating with Mobile API (guest token)...")
    api = api_class()
    api._ensure_token()
    print("    Authenticated successfully")

    dish_name, ingredients = _resolve_dish_terms(dish_name)
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
                row = build_mobile_row(company_id, store_name, store_id, ing, prod, now)
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


def woolworths_querier(api, company_id, company_name, user_address, dish_input, requery,
                       max_dist_km=5.0):
    """Phase 1 (query): shared Woolworths pipeline — geocode, nearby stores, per-store search.

    Queries the Woolworths API for product pricing across nearby stores and appends
    results to the CSV. Mirrors foodstuffs_querier_edge/foodstuffs_querier_mobile
    for the other two brands: the shared query code lives here so
    woolworths_optimiser.py stays a thin CLI, and `optimise()` (Step 2) reads the
    CSV rows appended here.

    Store identity keys directly on extra1 (fulfilmentStoreId): get_nearby_stores()
    returns store_id=extra1, set_store_context(session, store_id) builds the
    cw-lrkswrdjp cookie as `dm-Pickup,f-{store_id},s-38`, and build_woolworths_row
    writes store_id=extra1 to full_results.csv. The legacy pickupAddressId(extra2)
    -> extra1 mapping indirection (get_store_mapping) has been removed.

    Args:
        api: the woolworths_api module (create_session, set_store_context,
             search_products, get_nearby_stores) — injected the same way
             `api_class` is for the Foodstuffs helpers
        company_id: CSV company value written to rows (e.g. "Woolworths")
        company_name: display name for print lines
        user_address: NZ address to geocode
        dish_input: dish name (str) or dict to search ingredients for
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
    if user_lat is None:
        print(f"Error: Could not geocode address '{user_address}'")
        return False

    print(f"Geocoding: {user_address}")
    print(f"           lat: {user_lat:.6f}  lon: {user_lon:.6f}")
    print()

    nearby = api.get_nearby_stores(user_lat, user_lon, max_dist_km=max_dist_km)
    if not nearby:
        print(f"Error: No {company_name} stores found within {max_dist_km} km")
        return False

    print(f"Found {len(nearby)} stores within {max_dist_km} km:")
    for s in nearby:
        print(f"  {s['name']} ({s['distance_km']} km)")

    dish_name, ingredients = _resolve_dish_terms(dish_input)
    print(f"\nDish: {dish_name}")
    print(f"Ingredients: {', '.join(ingredients)}")

    now = datetime.now()
    new_rows = []

    for store in nearby:
        store_name = store["name"]
        store_id = store["store_id"]
        print(f"\n--- Store: {store_name} (id={store_id}, {store['distance_km']} km) ---")

        session = api.create_session()
        try:
            ctx = api.set_store_context(session, store_id)
            print(f"  Context set: {ctx['method']}, fulfilmentStoreId={ctx['fulfilmentStoreId']}")
        except RuntimeError as e:
            print(f"  [WARN] {e} -- skipping store")
            continue

        for ing in ingredients:
            print(f"  Searching: {ing}")
            products = api.search_products(session, ing, food_only=True)
            priced = [p for p in products if p.get("salePrice") is not None]
            if priced:
                for prod in priced:
                    row = build_woolworths_row(company_id, store_name, store_id, ing, prod, now)
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


def analyse_results(df, ingredients, dish, company=None, store_ids=None):
    """Build per-store cost summary and per-ingredient comparison table.

    Args:
        df: DataFrame with columns matching CSV_COLUMNS
        ingredients: list of ingredient search terms for the dish
        dish: dish name (string) or dict for quantity lookup
        company: optional retailer name to filter rows (e.g. "PaknSave", "NewWorld", "Woolworths")
        store_ids: optional set of valid store_ids (from distance-radius filtering)
                   to restrict which stores are included

    Returns:
        (summary, table) where:
        - summary: DataFrame indexed by store with total_cost column, sorted cheapest first
        - table: DataFrame indexed by ingredient with per-store prices, best price/store, and TOTAL row
    """
    df = df.copy()
    if company:
        df = df[df["company"] == company]
    if store_ids:
        df = df[df["store_id"].isin(store_ids)]
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
    quantities = _build_quantity_map(dish)

    rows = []
    for ing in ingredients:
        row = {"Ingredient": ing, "Qty": quantities.get(ing, "-")}
        for sn in store_names:
            match = df[(df["search_ingredient"] == ing) & (df["store"] == sn)]
            if not match.empty:
                best_prod = match.loc[match["price"].idxmin()]
                qty = best_prod['quantity']
                unit = best_prod['measurement_unit']
                # Clean up float formatting (600.0 -> 600, 1.5 -> 1.5)
                if isinstance(qty, float) and qty.is_integer():
                    qty_str = str(int(qty))
                else:
                    qty_str = str(qty) if qty else ""
                unit_str = str(unit) if unit else ""
                pack_info = f" ({qty_str} {unit_str})".strip() if qty_str and unit_str else ""
                row[sn] = f"${best_prod['price']:.2f}{pack_info}"
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


def optimise(dish, company=None, store_ids=None, require_valid=False):
    """Phase 2: Read today's results from CSV and print comparison table.

    Args:
        dish: dish to optimise for — either a string (dish name,
              resolved from DISHES or used as a single search term) or a dict
              with keys 'dish_name' and 'ingredients'.
        company: optional retailer name to filter rows (e.g. "PaknSave", "NewWorld", "Woolworths")
        store_ids: optional set of valid store_ids (from distance-radius filtering)
                   to restrict which stores are included
        require_valid: if True, only rows where is_valid == True are included.
                       Rows with is_valid == False or blank (NaN) are excluded.
                       Default False preserves backward compatibility for
                       standalone CLI callers that don't run validation.
    """
    if not RESULTS_FILE.exists():
        print(f"No results file found: {RESULTS_FILE}")
        return

    df = pd.read_csv(RESULTS_FILE, encoding="utf-8")
    today_str = date.today().strftime("%Y-%m-%d")
    df_today = df[df["date_created"] == today_str]
    if company:
        df_today = df_today[df_today["company"] == company]
    if store_ids:
        df_today = df_today[df_today["store_id"].isin(store_ids)]

    if require_valid and "is_valid" in df_today.columns:
        # Only keep rows explicitly validated as True.
        # NaN / blank / False rows are all excluded.
        df_today = df_today[df_today["is_valid"].fillna(False) == True]

    if df_today.empty:
        print(f"No results found for today ({today_str})")
        return

    dish_name, ingredients = _resolve_dish_terms(dish)
    dish_ings = ingredients

    df_dish = df_today[df_today["search_ingredient"].isin(dish_ings)]

    if df_dish.empty:
        print(f"No results for dish '{dish_name}' ingredients in today's data")
        return

    summary, table = analyse_results(df_dish, dish_ings, dish, company=company, store_ids=store_ids)

    print("\n" + "=" * 70)
    print(f"TOTAL COST COMPARISON -- {dish_name.upper()}")
    print("=" * 70)
    print(summary.to_string())
    print("\n" + "=" * 70)
    print("PER-INGREDIENT BREAKDOWN")
    print("=" * 70)
    print(table.to_string())
