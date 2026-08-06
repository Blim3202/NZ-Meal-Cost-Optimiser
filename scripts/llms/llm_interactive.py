"""
LLM-Integrated Interactive Dish Pipeline
=========================================
Full interactive CLI that combines LLM ingredient generation with the existing
supermarket optimizers (Pak'nSave Edge/Mobile, New World Edge/Mobile, Woolworths).

Flow:
    STEP 1: Collect inputs (address, distance, dish, portions, supermarkets)
    STEP 2: Resolve ingredients (curated set -> LLM -> fallback)
    STEP 3: Interactive review & refinement of the ingredient list
    STEP 4: Query selected optimizers with the dish dict
    STEP 5: Optimise & present per-brand comparison tables
    STEP 6: Apply quantity scaling via parse_optimizer_columns

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

from optimizer_utils import (
    RESULTS_FILE,
    _resolve_dish,
    foodstuffs_optimizer_edge,
    foodstuffs_optimizer_mobile,
    optimise,
)
from scripts.llms.llm_utils import resolve_ingredients, parse_optimizer_columns


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
    from woolworths_api import create_session, set_store_context, search_products, get_nearby_stores
    from woolworths_optimizer import query_and_save
    return create_session, set_store_context, search_products, get_nearby_stores, query_and_save


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
            print(f"    {i:2d}. {qty} {unit:6s}  [{term}]")
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
                print(f"  Current: {ing['quantity']} {ing['unit']} [{ing['search_term']}]")
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
            print(f"  {i:>3d}  {qty:>8s} {unit:>6s}  {term}")
        else:
            print(f"  {i:>3d}  {ing}")


# ─── Step 4: Query Optimizers ─────────────────────────────────────────────

def step4_query(address, dish_dict, requery, distance, selected):
    """Query selected optimizers with the dish dict."""
    dish_name, _ = _resolve_dish(dish_dict)
    requery_bool = requery.lower() != "false" if isinstance(requery, str) else requery

    print(f"\n{'='*60}")
    print(f"STEP 4: Querying optimizers (requery={requery_bool})")
    print(f"{'='*60}")

    for sm in selected:
        print(f"\n--- {sm} ---")
        try:
            if sm == "pns_edge":
                api_class, find_nearby = _import_pns_edge()
                foodstuffs_optimizer_edge(
                    api_class, find_nearby,
                    ALL_SUPERMARKETS[sm][0], ALL_SUPERMARKETS[sm][1],
                    address, dish_dict, requery_bool, max_dist_km=distance,
                )
            elif sm == "pns_mobile":
                api_class, find_nearby = _import_pns_mobile()
                foodstuffs_optimizer_mobile(
                    api_class, find_nearby,
                    ALL_SUPERMARKETS[sm][0], ALL_SUPERMARKETS[sm][1],
                    address, dish_dict, requery_bool, max_dist_km=distance,
                )
            elif sm == "nw_edge":
                api_class, find_nearby = _import_nw_edge()
                foodstuffs_optimizer_edge(
                    api_class, find_nearby,
                    ALL_SUPERMARKETS[sm][0], ALL_SUPERMARKETS[sm][1],
                    address, dish_dict, requery_bool, max_dist_km=distance,
                )
            elif sm == "nw_mobile":
                api_class, find_nearby = _import_nw_mobile()
                foodstuffs_optimizer_mobile(
                    api_class, find_nearby,
                    ALL_SUPERMARKETS[sm][0], ALL_SUPERMARKETS[sm][1],
                    address, dish_dict, requery_bool, max_dist_km=distance,
                )
            elif sm == "woolworths":
                _create_session, _set_ctx, _search, _nearby, _query_save = _import_woolworths()
                _query_save(address, dish_dict, requery_bool, max_dist_km=distance)
            else:
                print(f"  Unknown supermarket: {sm}")
        except Exception as e:
            print(f"  [ERROR] {sm}: {e}")


# ─── Step 5: Optimise ─────────────────────────────────────────────────────

def step5_optimise(dish_dict, selected):
    """Run optimise() for each brand used."""
    print(f"\n{'='*60}")
    print("STEP 5: Optimising & presenting results")
    print(f"{'='*60}")

    companies = set()
    for sm in selected:
        companies.add(ALL_SUPERMARKETS[sm][0])

    for company in sorted(companies):
        print(f"\n--- {company} ---")
        optimise(dish_dict, company=company)


# ─── Step 6: Apply Quantity Scaling ───────────────────────────────────────

def step6_scaling(dish_dict, selected):
    """Apply quantity scaling to today's CSV results and print scaled costs."""
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

    if not rows:
        print(f"  No results for today ({today_str})")
        return

    # Filter to companies used
    company_names = set(ALL_SUPERMARKETS[sm][0] for sm in selected)
    
    # Organize data: pivoted[search_term][store] = scaled_row_dict
    pivoted = {}
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
        
        sr = parse_optimizer_columns(enriched)
        sr["store"] = row.get("store", "Unknown")
        sr["company"] = company
        sr["pack_price"] = float(row.get("price", 0)) if row.get("price") else 0
        
        if search_term not in pivoted:
            pivoted[search_term] = {}
        
        pivoted[search_term][sr["store"]] = sr
        all_stores.add(sr["store"])

    if not pivoted:
        print("  No matching rows found for this dish today.")
        return

    sorted_stores = sorted(list(all_stores))
    
    # Print Table
    # Column widths
    ing_width = 25
    store_width = 20
    
    header = f"{'Ingredient (Need)':{ing_width}s} "
    for s in sorted_stores:
        header += f"{s:{store_width}s} "
    header += f"{'Qty Purch':>10s} {'Qty Used':>10s} {'Cost Used':>10s} {'Purch Cost':>10s}"
    
    print(f"\n{header}")
    print("-" * len(header))
    
    store_totals = {s: 0.0 for s in sorted_stores}
    
    for term, stores_data in pivoted.items():
        # Find best store
        best_store = None
        min_cost = float('inf')
        for s in sorted_stores:
            if s in stores_data:
                cost = stores_data[s]["used_price"]
                if cost < min_cost:
                    min_cost = cost
                    best_store = s
                    
        # Row data
        row_str = f"{term[:ing_width]:{ing_width}s} "
        for s in sorted_stores:
            if s in stores_data:
                data = stores_data[s]
                # Format: $CostUsed ($Price/Unit)
                cell = f"${data['used_price']:>6.2f} (${data['pack_price']/(data['pack_quantity'] if data['pack_quantity'] else 1):.2f}/{data['pack_unit']})"
                if s == best_store:
                    row_str += f"\033[1m{cell:{store_width}s}\033[0m "
                else:
                    row_str += f"{cell:{store_width}s} "
            else:
                row_str += f"{'N/A':{store_width}s} "
        
        # Best store metrics
        best_data = stores_data[best_store]
        row_str += f"{best_data['purchase_quantity']:>10d} {best_data['ingredient_quantity']:>6.0f}{best_data['ingredient_measurement']:<4s} ${best_data['used_price']:>9.2f} ${best_data['purchase_price']:>9.2f}"
        
        print(row_str)
        
        # Add to totals
        for s in sorted_stores:
            if s in stores_data:
                store_totals[s] += stores_data[s]["used_price"]

    # Total Row
    total_row = f"{'TOTAL USED COST':{ing_width}s} "
    for s in sorted_stores:
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
    parser.add_argument("--non-interactive", action="store_true", help="Skip review step")
    parser.add_argument("--model", default="medium", choices=["small", "medium", "large"], help="LLM model alias (default: medium)")
    args = parser.parse_args()

    print("=" * 60)
    print("  NZ Meal Cost Optimizer - LLM-Integrated Pipeline")
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
    print(f"  Model:       {args.model}")

    # Step 2: Resolve ingredients
    dish_dict, source = step2_resolve(dish_name, portions, args.regenerate, args.model)

    # Step 3: Interactive review
    dish_dict = step3_review(dish_dict, args)

    # Step 4: Query optimizers
    step4_query(address, dish_dict, args.requery, distance, selected)

    # Step 5: Optimise
    step5_optimise(dish_dict, selected)

    # Step 6: Quantity scaling
    step6_scaling(dish_dict, selected)

    print(f"\n{'='*60}")
    print("  Pipeline complete!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
