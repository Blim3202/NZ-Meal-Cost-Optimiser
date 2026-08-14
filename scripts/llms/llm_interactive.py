"""
LLM-Integrated Interactive Dish Pipeline
=========================================
Full interactive CLI that combines LLM ingredient generation with the existing
supermarket optimisers (Pak'nSave Edge/Mobile, New World Edge/Mobile, Woolworths).

Flow:
    STEP 1: Collect inputs (address, distance, dish, portions, supermarkets)
    STEP 2: Resolve ingredients (curated set -> LLM -> fallback)
    STEP 3: Interactive review & refinement of the ingredient list
    STEP 4: Query selected optimisers with the dish dict
    STEP 5: Optimise & present per-brand comparison tables
    STEP 6: Apply quantity scaling via parse_optimiser_columns

    Usage:
        python -m scripts.llms.llm_interactive [OPTIONS]

    Options:
--dish "spaghetti bolognese"                # default: interactive prompt
    --portions 4                                # default 4
    --supermarkets "7"                         # numbers and/or names, default "7" (all)
    --regenerate            # force LLM even if dish is in curated set
    --requery false         # skip API calls, use existing CSV
    --non-interactive       # accept LLM output without review step
    --model medium          # model alias for LLM generation (small/medium/large)

Supermarket choices (numbers and/or names, comma-separated):
    1. Pak'nSave (Edge)                    2. New World (Edge)
    3. Woolworths                          4. Pak'nSave (Edge) + New World (Edge)
    5. New World (Edge) + Woolworths       6. Pak'nSave (Edge) + Woolworths
    7. Pak'nSave (Edge) + New World (Edge) + Woolworths
"""

import argparse
import csv
import math
import sys
from datetime import date
from pathlib import Path

# Add project root and scripts/combined to path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "combined"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "paknsave"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "newworld"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "woolworths"))

from optimiser_utils import (
    RESULTS_FILE,
    _resolve_dish_terms,
    foodstuffs_querier_edge,
    foodstuffs_querier_mobile,
    optimise,
    woolworths_querier,
)
from scripts.llms.llm_utils import resolve_ingredients, parse_optimiser_columns


# ─── Supermarket Registry ─────────────────────────────────────────────────

STORE_MENU = [
    ("Pak'nSave (Edge)", ["pns_edge"]),
    ("New World (Edge)", ["nw_edge"]),
    ("Woolworths", ["woolworths"]),
    ("Pak'nSave (Edge) + New World (Edge)", ["pns_edge", "nw_edge"]),
    ("New World (Edge) + Woolworths", ["nw_edge", "woolworths"]),
    ("Pak'nSave (Edge) + Woolworths", ["pns_edge", "woolworths"]),
    ("Pak'nSave (Edge) + New World (Edge) + Woolworths", ["pns_edge", "nw_edge", "woolworths"]),
]

ALL_SUPERMARKETS = {
    "pns_edge": ("PaknSave", "Pak'nSave"),
    "pns_mobile": ("PaknSave", "Pak'nSave"),
    "nw_edge": ("NewWorld", "New World"),
    "nw_mobile": ("NewWorld", "New World"),
    "woolworths": ("Woolworths", "Woolworths"),
}


def _resolve_supermarkets(raw):
    """Resolve a supermarket string (numbers and/or names) to backend keys.

    Examples: "7" -> all backends, "1" -> ["pns_edge"], "1,3" -> ["pns_edge", "woolworths"],
    "nw_edge" -> ["nw_edge"], "all" -> all backends.
    """
    raw = (raw or "").strip()
    if raw.lower() == "all":
        all_keys = []
        for _, keys in STORE_MENU:
            for k in keys:
                if k not in all_keys:
                    all_keys.append(k)
        return all_keys
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    keys = []
    for p in parts:
        if p.isdigit():
            idx = int(p)
            if 1 <= idx <= len(STORE_MENU):
                keys.extend(STORE_MENU[idx - 1][1])
            else:
                raise ValueError(f"Unknown supermarket number: {p}")
        elif p in ALL_SUPERMARKETS:
            keys.append(p)
        else:
            raise ValueError(f"Unknown supermarket: {p}")
    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _import_pns_edge():
    from paknsave_api import PaknSaveEdgeAPI, find_nearby_stores
    return PaknSaveEdgeAPI, find_nearby_stores


def _import_pns_mobile():
    from paknsave_api import PaknSaveMobileAPI, find_nearby_stores
    return PaknSaveMobileAPI, find_nearby_stores


def _import_nw_edge():
    from newworld_api import NewWorldEdgeAPI, find_nearby_stores
    return NewWorldEdgeAPI, find_nearby_stores


def _import_nw_mobile():
    from newworld_api import NewWorldMobileAPI, find_nearby_stores
    return NewWorldMobileAPI, find_nearby_stores


def _import_woolworths():
    import woolworths_api
    return woolworths_api


# ─── Step 1: Collect Inputs ───────────────────────────────────────────────

def collect_inputs(args):
    """Collect and resolve CLI args, prompting for missing values interactively."""
    address = args.address
    if not address:
        address = input("Address [123 Queen Street, Auckland CBD, 1010]: ").strip()
        if not address:
            address = "123 Queen Street, Auckland CBD, 1010"

    dish = args.dish
    if not dish:
        dish = input("Dish name [spaghetti bolognese]: ").strip()
        if not dish:
            dish = "spaghetti bolognese"

    portions = args.portions
    if portions is None and not args.non_interactive:
        raw = input("Portions [4]: ").strip()
        portions = int(raw) if raw else 4
    if portions is None:
        portions = 4

    distance = args.distance
    if distance is None and not args.non_interactive:
        raw = input("Distance km [5]: ").strip()
        distance = float(raw) if raw else 5.0
    if distance is None:
        distance = 5.0

    supermarkets = args.supermarkets
    if not supermarkets:
        if args.non_interactive:
            supermarkets = "7"
        else:
            print("\nSupermarket options:")
            for i, (label, _) in enumerate(STORE_MENU, 1):
                print(f"  {i}. {label}")
            raw = input("Supermarkets [7]: ").strip()
            supermarkets = raw if raw else "7"

    try:
        selected = _resolve_supermarkets(supermarkets)
    except ValueError as e:
        print(f"  [ERROR] {e}")
        print("  Valid choices (numbers and/or names, comma-separated):")
        for i, (label, _) in enumerate(STORE_MENU, 1):
            print(f"    {i}. {label}")
        sys.exit(1)

    return address, dish, portions, distance, selected


# ─── Step 2: Resolve Ingredients ──────────────────────────────────────────

def step2_resolve(dish_name, portions, regenerate, model_alias):
    """Resolve ingredients for the dish. Returns (dish_dict, source)."""
    print(f"\n{'='*60}")
    print(f"STEP 2: Resolving ingredients for '{dish_name}' ({portions} portions)")
    print(f"{'='*60}")

    dish_dict, source = resolve_ingredients(
        dish_name, portions=portions, regenerate=regenerate, model_alias=model_alias
    )

    print(f"  Source: [{source}]")
    print(f"  Dish: {dish_dict['dish_name']}")
    print(f"  Ingredients ({len(dish_dict['ingredients'])}):")
    for i, ing in enumerate(dish_dict["ingredients"], 1):
        if isinstance(ing, dict):
            qty = ing.get("quantity", "")
            unit = ing.get("unit", "")
            term = ing.get("search_term", "")
            approx = ""
            if ing.get("approx_quantity") and ing.get("approx_unit"):
                approx = f" (~{ing['approx_quantity']} {ing['approx_unit']})"
            print(f"    {i:2d}. {qty} {unit:6s}  [{term}]{approx}")
        else:
            print(f"    {i:2d}. {ing}")

    return dish_dict, source


# ─── Step 3: Interactive Review ───────────────────────────────────────────

def step3_review(dish_dict, args):
    """Interactively review and edit the ingredient list."""
    if args.non_interactive:
        print("\n  [non-interactive mode - skipping review]")
        return dish_dict

    print(f"\n{'='*60}")
    print("STEP 3: Review ingredients")
    print(f"{'='*60}")
    print("\nActions: [A]ccept all  [C]hange #N  [D]elete #N  [R]egenerate  [Q]uit")

    ingredients = dish_dict["ingredients"]
    # Work with a mutable list of dicts
    if ingredients and isinstance(ingredients[0], str):
        # Convert strings to dicts for uniform editing
        ingredients = [{"quantity": None, "unit": "", "search_term": s} for s in ingredients]
        dish_dict["ingredients"] = ingredients

    while True:
        _print_ingredient_table(ingredients)
        choice = input("\nAction [A]: ").strip().lower()

        if choice in ("", "a", "accept"):
            print("  Accepted all ingredients.")
            break
        elif choice in ("q", "quit"):
            print("  Quitting.")
            sys.exit(0)
        elif choice in ("r", "regenerate"):
            print("  Regenerating via LLM...")
            new_dish, _ = resolve_ingredients(
                dish_dict["dish_name"],
                portions=dish_dict["portion"],
                regenerate=True,
                model_alias=args.model,
            )
            if isinstance(new_dish["ingredients"][0], dict):
                ingredients = list(new_dish["ingredients"])
                dish_dict["ingredients"] = ingredients
            else:
                print("  [WARN] LLM regen returned non-dict ingredients — keeping current list")
        elif choice in ("c", "change"):
            raw = input("  Enter ingredient number to change: ").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(ingredients):
                idx = int(raw) - 1
                ing = ingredients[idx]
                approx_str = ""
                if ing.get("approx_quantity") and ing.get("approx_unit"):
                    approx_str = f" (~{ing['approx_quantity']} {ing['approx_unit']})"
                print(f"  Current: {ing['quantity']} {ing['unit']} [{ing['search_term']}]{approx_str}")
                new_qty = input(f"  New quantity [{ing['quantity']}]: ").strip()
                new_unit = input(f"  New unit [{ing['unit']}]: ").strip()
                new_term = input(f"  New search term [{ing['search_term']}]: ").strip()
                if new_qty:
                    try:
                        ing["quantity"] = float(new_qty)
                    except ValueError:
                        print("  [WARN] Invalid quantity — keeping unchanged")
                if new_unit:
                    ing["unit"] = new_unit
                if new_term:
                    ing["search_term"] = new_term
            else:
                print("  Invalid number.")
        elif choice in ("d", "delete"):
            raw = input("  Enter ingredient number to delete: ").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(ingredients):
                idx = int(raw) - 1
                removed = ingredients.pop(idx)
                print(f"  Removed: {removed}")
            else:
                print("  Invalid number.")
        else:
            print("  Unknown action. Try A, C, D, R, or Q.")

    return dish_dict


def _print_ingredient_table(ingredients):
    """Print a formatted ingredient table."""
    print()
    print(f"  {'#':>3s}  {'Ingredient':20s} {'Qty':>8s} {'Unit':>6s}  Search Term")
    print("  " + "---" + "  " + "-" * 20 + " " + "-" * 8 + " " + "-" * 6 + "  " + "-" * 20)
    for i, ing in enumerate(ingredients, 1):
        if isinstance(ing, dict):
            qty = str(ing.get("quantity", ""))
            unit = ing.get("unit", "")
            term = ing.get("search_term", "")
            approx = ""
            if ing.get("approx_quantity") and ing.get("approx_unit"):
                approx = f" (~{ing['approx_quantity']} {ing['approx_unit']})"
            print(f"  {i:>3d}  {qty:>8s} {unit:>6s}  {term}{approx}")
        else:
            print(f"  {i:>3d}  {ing}")


# ─── Step 4: Query Optimisers ─────────────────────────────────────────────

def step4_query(address, dish_dict, requery, distance, selected):
    """Query selected optimisers with the dish dict.

    Returns:
        set of store_ids that are within the distance radius (for Steps 5/6 filtering).
        Empty set if requery is false (no filtering will be applied).
    """
    dish_name, _ = _resolve_dish_terms(dish_dict)
    requery_bool = requery.lower() != "false" if isinstance(requery, str) else requery

    print(f"\n{'='*60}")
    print(f"STEP 4: Querying optimisers (requery={requery_bool})")
    print(f"{'='*60}")

    store_ids = set()

    for sm in selected:
        print(f"\n--- {sm} ---")
        try:
            if sm == "pns_edge":
                api_class, find_nearby = _import_pns_edge()
                foodstuffs_querier_edge(
                    api_class, find_nearby,
                    ALL_SUPERMARKETS[sm][0], ALL_SUPERMARKETS[sm][1],
                    address, dish_dict, requery_bool, max_dist_km=distance,
                )
                _collect_store_ids(store_ids, sm, address, distance)
            elif sm == "pns_mobile":
                api_class, find_nearby = _import_pns_mobile()
                foodstuffs_querier_mobile(
                    api_class, find_nearby,
                    ALL_SUPERMARKETS[sm][0], ALL_SUPERMARKETS[sm][1],
                    address, dish_dict, requery_bool, max_dist_km=distance,
                )
                _collect_store_ids(store_ids, sm, address, distance)
            elif sm == "nw_edge":
                api_class, find_nearby = _import_nw_edge()
                foodstuffs_querier_edge(
                    api_class, find_nearby,
                    ALL_SUPERMARKETS[sm][0], ALL_SUPERMARKETS[sm][1],
                    address, dish_dict, requery_bool, max_dist_km=distance,
                )
                _collect_store_ids(store_ids, sm, address, distance)
            elif sm == "nw_mobile":
                api_class, find_nearby = _import_nw_mobile()
                foodstuffs_querier_mobile(
                    api_class, find_nearby,
                    ALL_SUPERMARKETS[sm][0], ALL_SUPERMARKETS[sm][1],
                    address, dish_dict, requery_bool, max_dist_km=distance,
                )
                _collect_store_ids(store_ids, sm, address, distance)
            elif sm == "woolworths":
                api_module = _import_woolworths()
                woolworths_querier(
                    api_module,
                    ALL_SUPERMARKETS[sm][0], ALL_SUPERMARKETS[sm][1],
                    address, dish_dict, requery_bool, max_dist_km=distance,
                )
                _collect_store_ids(store_ids, sm, address, distance)
            else:
                print(f"  Unknown supermarket: {sm}")
        except Exception as e:
            print(f"  [ERROR] {sm}: {e}")

    if store_ids:
        print(f"\n  Collected {len(store_ids)} store_ids within {distance} km radius")

    return store_ids


# ─── Step 4b: Validate Query Results ─────────────────────────────────────────────────

def step4b_validate(dish_dict, do_validate, requery):
    """Validate today's query results via LLM.

    When do_validate and requery are both True, reads full_results.csv,
    filters to today's unvalidated rows matching the dish's search ingredients,
    sends them through ministral-3b-2512 in batches of 20, and writes
    is_valid back to CSV.

    If validation fails (e.g. rate-limited, API error), the function
    prints a warning and returns False so the caller can continue without
    is_valid filtering.

    Args:
        dish_dict: dish dict with ingredients
        do_validate: whether validation is enabled (--validate flag)
        requery: whether a fresh API query was performed

    Returns:
        bool: True if validation completed (or was skipped because no
              new rows exists).  False if validation failed — caller
              should fall back to not filtering by is_valid.
    """
    if not do_validate:
        print("\n  [skip validation — --no-validate]")
        return True

    if not requery:
        print("\n  [skip validation — requery=false, no new results to validate]")
        return True

    print(f"\n{'='*60}")
    print("STEP 4b: Validating query results via LLM")
    print(f"{'='*60}")

    dish_name, search_terms = _resolve_dish_terms(dish_dict)

    try:
        from scripts.llms.llm_validate import validate_dish_results
    except ImportError as e:
        print(f"  [WARN] Could not import validate_dish_results: {e}")
        print("  [WARN] Continuing without validation.")
        return False

    search_term_set = set(search_terms) if search_terms else set()

    result = validate_dish_results(
        dish_ingredients=search_term_set,
        model_alias="small",
        batch_size=20,
    )

    if result["error"] is not None:
        print(f"\n  [WARN] Validation failed: {result['error']}")
        print("  [WARN] Continuing without is_valid filtering.")
        return False

    if not result["validated"]:
        if result["total"] == 0:
            print(f"\n  No unvalidated rows found for today. Either results were")
            print(f"  already validated, or no query ran for this dish.")
            print(f"  Results will be shown without is_valid filtering.")
        return True

    print(f"\n  Validation complete: {result['valid']} valid, "
          f"{result['invalid']} invalid ({result['total']} total)")

    if result["valid"] == 0:
        print("  [WARN] Zero rows passed validation. Steps 5 & 6 will show")
        print("  [WARN] no results (all rows filtered out by is_valid=False).")

    return True


def _collect_store_ids(store_ids, sm, address, distance):
    """Call find_nearby_stores / get_nearby_stores to collect store_ids within distance."""
    from optimiser_utils import geocode

    user_lat, user_lon = geocode(address)
    if user_lat is None or user_lon is None:
        print(f"  [WARN] Could not geocode address for store_id collection")
        return

    if sm in ("pns_edge", "pns_mobile"):
        _api_class, find_nearby = _import_pns_edge()
    elif sm in ("nw_edge", "nw_mobile"):
        _api_class, find_nearby = _import_nw_edge()
    elif sm == "woolworths":
        api_module = _import_woolworths()
        nearby = api_module.get_nearby_stores(user_lat, user_lon, max_dist_km=distance)
        for s in nearby:
            store_ids.add(str(s["store_id"]))
        return
    else:
        return

    nearby = find_nearby(user_lat, user_lon, radius_km=distance)
    for s in nearby:
        store_ids.add(s["store_id"])


# ─── Step 5: Optimise ─────────────────────────────────────────────────────

def step5_optimise(dish_dict, selected, store_ids=None, require_valid=False):
    """Run optimise() for each brand used."""
    print(f"\n{'='*60}")
    print("STEP 5: Optimising & presenting results")
    print(f"{'='*60}")

    companies = set()
    for sm in selected:
        companies.add(ALL_SUPERMARKETS[sm][0])

    for company in sorted(companies):
        print(f"\n--- {company} ---")
        optimise(dish_dict, company=company, store_ids=store_ids, require_valid=require_valid)


# ─── Step 6: Apply Quantity Scaling ───────────────────────────────────────

def step6_scaling(dish_dict, selected, store_ids=None, require_valid=False):
    """Apply quantity scaling to today's CSV results and print scaled costs.

    Args:
        dish_dict: dish with ingredients
        selected: list of supermarket backend keys
        store_ids: optional set of store_ids within the distance radius;
                   if provided, only rows with matching store_id are considered
        require_valid: if True, only rows where is_valid == True are included.
                       Rows with is_valid == False or blank are excluded.
    """
    print(f"\n{'='*60}")
    print("STEP 6: Scaled Dish Cost Analysis")
    print(f"{'='*60}")

    today_str = date.today().strftime("%Y-%m-%d")

    # Build ingredient lookup from dish_dict (match search_term -> LLM qty/unit)
    ingredients_dict = {ing.get("search_term"): ing for ing in dish_dict.get("ingredients", []) if isinstance(ing, dict)}
    
    if not RESULTS_FILE.exists():
        print("  No results file found — nothing to scale.")
        return

    rows = []
    with open(RESULTS_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("date_created") == today_str:
                rows.append(row)

    # Filter to companies used
    company_names = set(ALL_SUPERMARKETS[sm][0] for sm in selected)
    
    # Filter to store_ids within distance radius (if provided)
    if store_ids:
        rows = [r for r in rows if r.get("store_id", "") in store_ids]

    # Filter by is_valid if require_valid is True
    if require_valid:
        rows = [r for r in rows if str(r.get("is_valid", "")).strip().lower() == "true"]
        if not rows:
            print(f"  No validated (is_valid=True) results for today ({today_str}).")
            print(f"  Run with --validate --requery true to query and validate.")
            return

    if not rows:
        print(f"  No results for today ({today_str})")
        return

    # Filter to companies used
    company_names = set(ALL_SUPERMARKETS[sm][0] for sm in selected)
    
    # Organize data: candidates[search_term][store] = [list of scaled_row_dicts]
    candidates = {}
    all_stores = set()

    for row in rows:
        company = row.get("company", "")
        if company not in company_names:
            continue

        search_term = row.get("search_ingredient", "")
        if search_term not in ingredients_dict:
            continue

        llm_info = ingredients_dict.get(search_term, {})
        enriched = dict(row)
        enriched["ingredient_quantity"] = llm_info.get("quantity", 0)
        enriched["ingredient_measurement"] = llm_info.get("unit", "")
        enriched["ingredient_approx_quantity"] = llm_info.get("approx_quantity")
        enriched["ingredient_approx_unit"] = llm_info.get("approx_unit")

        sr = parse_optimiser_columns(enriched)
        sr["store"] = row.get("store", "Unknown")
        sr["company"] = company
        sr["pack_price"] = float(row.get("price", 0)) if row.get("price") else 0

        if search_term not in candidates:
            candidates[search_term] = {}
        if sr["store"] not in candidates[search_term]:
            candidates[search_term][sr["store"]] = []
        candidates[search_term][sr["store"]].append(sr)
        all_stores.add(sr["store"])

    if not candidates:
        print("  No matching rows found for this dish today.")
        return

    # Pick the best per (search_term, store): prefer candidates with valid cost,
    # then pick lowest used_price (proportional cost for what the recipe needs).
    # Tie-break: prefer units_match=True (exact unit match over approximation).
    # Exclude incompatible-unit products (used_price = None).
    pivoted = {}
    for term, stores_data in candidates.items():
        pivoted[term] = {}
        for store, sr_list in stores_data.items():
            valid = [sr for sr in sr_list if sr["used_price"] is not None]
            if valid:
                best = min(valid, key=lambda s: (s["used_price"], 0 if s.get("units_match", False) else 1))
            else:
                best = min(sr_list, key=lambda s: (s["used_price"] is None, s["used_price"] if s["used_price"] is not None else float('inf')))
            pivoted[term][store] = best

    sorted_stores = sorted(list(all_stores))
    all_terms = list(ingredients_dict.keys())
    
    # Print Table
    # Column widths
    ing_width = 25
    store_width = 25

    header = f"{'Ingredient (Need)':{ing_width}s} "
    for s in sorted_stores:
        header += f"{s:{store_width}s} "
    header += f"{'Qty Purch':>10s} {'Qty Needed':>10s} {'Cost Used':>10s} {'Purch Cost':>10s}"

    print(f"\n{header}")
    print("-" * len(header))

    store_totals = {s: 0.0 for s in sorted_stores}

    for term in all_terms:
        stores_data = pivoted.get(term, {})
        # Find best store (lowest used_price = cheapest per-unit-of-recipe-amount)
        # Tie-break: prefer units_match=True (exact unit match over approximation)
        best_store = None
        min_key = float('inf')
        for s in sorted_stores:
            if s in stores_data:
                data = stores_data[s]
                cost = data["used_price"] if data["used_price"] is not None else float('inf')
                tie_break = 0 if data.get("units_match", False) else 1
                if (cost, tie_break) < (min_key, 0 if best_store is None else 1):
                    min_key = cost
                    best_store = s

        row_str = f"{term[:ing_width]:{ing_width}s} "
        for s in sorted_stores:
            if s in stores_data:
                data = stores_data[s]
                pack_q = data['pack_quantity']
                pack_qty_str = str(int(pack_q)) if float(pack_q).is_integer() else str(pack_q)
                pack_info = f"{pack_qty_str} {data['pack_unit']}".strip()
                product = data.get('returned_ingredient', '')[:14]
                if data['used_price'] is None:
                    cell = f"{'N/A':>6} | {product} ({pack_info})"
                else:
                    prefix = "~" if data.get("unit_approximate", False) else ""
                    cell = f"{prefix}${data['used_price']:>6.2f} | {product} ({pack_info})"
                if s == best_store:
                    row_str += f"\033[1m{cell:{store_width}}\033[0m "
                else:
                    row_str += f"{cell:{store_width}s} "
            else:
                row_str += f"{'N/A':{store_width}s} "

        # Best store metrics — highlight the store with lowest purchase_price
        if best_store and best_store in stores_data:
            best_data = stores_data[best_store]
            if best_data['used_price'] is not None:
                prefix = "~" if best_data.get("unit_approximate", False) else ""
                row_str += f"{best_data['purchase_quantity']:>10d} {best_data['ingredient_quantity']:>6.1f}{best_data['ingredient_measurement']:<4s} {prefix}${best_data['used_price']:>9.2f} {prefix}${best_data['purchase_price']:>9.2f}"
            else:
                row_str += f"{best_data['purchase_quantity']:>10d} {best_data['ingredient_quantity']:>6.1f}{best_data['ingredient_measurement']:<4s} {'N/A':>9s} {'N/A':>9s}"
        else:
            row_str += f"{'':>10s} {'':>10s} {'N/A':>10s} {'N/A':>10s}"

        print(row_str)

        # Add to totals (skip incompatible products with None cost)
        for s in sorted_stores:
            if s in stores_data and stores_data[s]["used_price"] is not None:
                store_totals[s] += stores_data[s]["used_price"]

    # Total Row (sum of used_price = proportional ingredient cost per store)
    total_row = f"{'TOTAL USED COST':{ing_width}s} "
    for s in sorted_stores:
        if store_totals[s] == 0:
            total_row += f"\033[1m{'N/A':>18s}\033[0m "
        else:
            total_row += f"\033[1m${store_totals[s]:>18.2f}\033[0m "
    print("-" * len(header))
    print(total_row)


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="LLM-Integrated Interactive Dish Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--address", default=None, help="NZ address")
    parser.add_argument("--distance", type=float, default=None, help="Search radius km (default 5)")
    parser.add_argument("--dish", default=None, help="Dish name")
    parser.add_argument("--portions", type=int, default=None, help="Number of servings (default 4)")
    parser.add_argument("--supermarkets", default=None, help="Numbers and/or names, comma-separated (1-7, default: 7): 1=Pak'nSave(Edge) 2=New World(Edge) 3=Woolworths 4=1+2 5=2+3 6=1+3 7=1+2+3")
    parser.add_argument("--regenerate", action="store_true", help="Force LLM even if dish is in curated set")
    parser.add_argument("--requery", default="true", help="Query the API (true/false, default: true)")
    parser.add_argument("--validate", dest="validate", action="store_true", default=True,
                        help="Validate query results via LLM and only use validated rows (default: on)")
    parser.add_argument("--no-validate", dest="validate", action="store_false",
                        help="Skip validation — use all query results regardless of is_valid")
    parser.add_argument("--non-interactive", action="store_true", help="Skip review step")
    parser.add_argument("--model", default="medium", choices=["small", "medium", "large"], help="LLM model alias (default: medium)")
    args = parser.parse_args()

    print("=" * 60)
    print("  NZ Meal Cost Optimiser - LLM-Integrated Pipeline")
    print("=" * 60)

    # Step 1: Collect inputs
    address, dish_name, portions, distance, selected = collect_inputs(args)

    print(f"\n  Address:     {address}")
    print(f"  Dish:        {dish_name}")
    print(f"  Portions:    {portions}")
    print(f"  Distance:    {distance} km")
    print(f"  Supermarkets: {selected}")
    print(f"  Regenerate:  {args.regenerate}")
    print(f"  Requery:     {args.requery}")
    print(f"  Validate:    {args.validate}")
    print(f"  Model:       {args.model}")

    requery_bool = args.requery.lower() != "false" if isinstance(args.requery, str) else args.requery

    # Step 2: Resolve ingredients
    dish_dict, source = step2_resolve(dish_name, portions, args.regenerate, args.model)

    # Step 3: Interactive review
    dish_dict = step3_review(dish_dict, args)

    # Step 4: Query optimisers (returns store_ids within distance radius)
    store_ids = step4_query(address, dish_dict, args.requery, distance, selected)

    # Step 4b: Validate query results via LLM
    validation_ok = step4b_validate(dish_dict, args.validate, requery_bool)

    # require_valid is True only when:
    # 1. args.validate is True (user wants validation)
    # 2. validation did NOT fail (step4b_validate returned True — either
    #    it succeeded, or was skipped because no new rows exist)
    # If validation failed (returned False), fall back to showing all rows.
    require_valid = args.validate and validation_ok

    # Step 5: Optimise & present results (filtered to nearby stores + is_valid)
    step5_optimise(dish_dict, selected, store_ids, require_valid=require_valid)

    # Step 6: Quantity scaling (filtered to nearby stores + is_valid)
    step6_scaling(dish_dict, selected, store_ids, require_valid=require_valid)

    print(f"\n{'='*60}")
    print("  Pipeline complete!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
