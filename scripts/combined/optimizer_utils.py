"""
Shared Optimizer Utilities
==========================
Common functions and constants for all retailer optimizers (Woolworths, Pak'nSave, New World).
Both optimizers write to the same data/full_results.csv with identical column structure.
"""

import csv
import hashlib
import math
import re
import time
from pathlib import Path

import requests

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
    "department",
    "sub_department",
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
    """Return the ingredient list for a dish, or [dish_name] if unknown."""
    return DISH_INGREDIENTS.get(dish_name.lower().strip(), [dish_name])


def get_quantities(dish_name):
    """Return the quantity dict for a dish, or {} if unknown."""
    return DISH_QUANTITIES.get(dish_name.lower().strip(), {})


def parse_woolworths_volume_size(volume_size, cup_measure=""):
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


def parse_paknsave_volume_size(display_name, single_price, promotions):
    """Parse a Pak'nSave product into (quantity, measurement_unit, per_unit_quantity, per_unit_price).

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


def parse_paknsave_mobile_unit(units, unit_price, price_cents=None):
    """Parse Pak'nSave Mobile API `units` and `unitPrice` strings.

    Combines the two splitting jobs for a mobile product into one helper so the
    caller gets (quantity, measurement_unit, per_unit_quantity, per_unit_price)
    in a single call — matching the edge pipeline's parse_paknsave_volume_size
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

       Fallback — bare "ea" with no `unitPrice`:
           Some single-each items expose only `units` of "ea" and no unitPrice
           string, which would otherwise leave per_unit_quantity/per_unit_price
           blank. Treat the item as being sold per each: per_unit_quantity
           becomes "ea" and per_unit_price mirrors the item's own price (from
           `price_cents`), so the per-unit columns never go empty.

    Examples:
        ("3 x 31g", "$26.99/1kg") -> (3, "x 31g", "1kg", 26.99)
        ("500g", "$18.99/kg")     -> (500, "g", "kg", 18.99)
        ("2 pack", "$3.49/ea")    -> (2, "pack", "ea", 3.49)
        ("ea", "", 250)           -> (1, "ea", "ea", 2.5)   # fallback
        ("ea", "")                -> (1, "ea", "", 0)        # fallback, no price known
        ("", "")                  -> ("", "", "", 0)

    Args:
        units: Mobile API `units` field (e.g. "3 x 31g", "500g", "ea").
        unit_price: Mobile API `unitPrice` formatted string (e.g. "$26.99/1kg").
        price_cents: Item price in cents (from `product["price"]`), used only for
            the bare-"ea" fallback so per_unit_price can mirror the item price.

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

    # Fallback: bare "ea" with no unitPrice → per-each at the item's own price.
    # Avoids blank per_unit columns (per_unit_price mirrors `price`).
    if not per_unit_qty and units and isinstance(units, str) and units.strip().lower() == "ea":
        per_unit_qty = "ea"
        if price_cents is not None:
            per_unit_price = price_cents / 100.0

    return quantity, measurement_unit, per_unit_qty, per_unit_price


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
            headers={"User-Agent": "NZMealCostOptimizer/1.0"},
            params={"q": address, "format": "json", "limit": 1},
            timeout=15,
        )
        if r.status_code == 200 and r.json():
            loc = r.json()[0]
            return float(loc["lat"]), float(loc["lon"])
    except Exception:
        pass
    return None, None
