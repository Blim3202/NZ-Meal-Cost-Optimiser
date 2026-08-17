r"""FastAPI entrypoint for the NZ Meal Cost Optimiser.

Run:
    .venv\Scripts\uvicorn NZMealOptimiser.web.main:app --port 8000
or (with the package installed):
    python -m uvicorn NZMealOptimiser.web.main:app --port 8000

The /optimise endpoint runs all retailer searches via a thread pool
(20 workers). Each ingredient search is offloaded to a background thread
so the event loop stays free. The total number of concurrent searches
depends on the dish (3-7 ingredients), search radius, and how many stores
are found nearby. Tasks run in batches of 20, not all at once.

Woolworths sessions are isolated per-store (fresh session + cookie per store).
Nominatim geocode runs once per request (not parallelized).

Each search returns ALL product results (not just the cheapest), using the
same row format as data/full_results.csv (CSV_COLUMNS). Rows are enriched
with LLM ingredient quantities and run through parse_optimiser_columns to
compute proportional "used cost" — the actual cost of the amount needed
for the recipe, scaling between pack sizes and recipe quantities.

A per-store cost summary is also computed: for each store, the cheapest
valid product is picked per ingredient, and the proportional "used prices"
are summed to give a total meal cost at that store.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import concurrent.futures
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from NZMealOptimiser import DATA_DIR
from NZMealOptimiser.llm.llm_utils import resolve_ingredients, parse_optimiser_columns
from NZMealOptimiser.pricing import optimiser_utils
from NZMealOptimiser.pricing.optimiser_utils import build_edge_row, build_woolworths_row
from NZMealOptimiser.pricing.paknsave_api import PaknSaveEdgeAPI, find_nearby_stores as ps_find_nearby
from NZMealOptimiser.pricing.newworld_api import NewWorldEdgeAPI, find_nearby_stores as nw_find_nearby
from NZMealOptimiser.pricing import woolworths_api
from NZMealOptimiser.web.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("NZMealOptimiser.web.main")

TMP_DIR = Path(__file__).resolve().parent / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Per-brand dispatch config
BRANDS = {
    "PaknSave": {
        "api_class": PaknSaveEdgeAPI,
        "find_nearby": ps_find_nearby,
        "company_id": "PaknSave",
        "logo": "ps",
    },
    "NewWorld": {
        "api_class": NewWorldEdgeAPI,
        "find_nearby": nw_find_nearby,
        "company_id": "NewWorld",
        "logo": "nw",
    },
    "Woolworths": {
        "company_id": "Woolworths",
        "logo": "ww",
    },
}


# Increase asyncio's default thread pool from 5 to 20 workers.
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=20)


class DishRequest(BaseModel):
    dish: str
    address: str
    distance_km: float = 5.0
    max_stores_per_company: int = 3
    companies: Optional[list[str]] = None  # None = all 3
    portions: int = 4


class OptimisationResult(BaseModel):
    dish: str
    companies_checked: list[str]
    rows: list[dict]
    store_costs: list[dict]
    timestamp: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Set the default executor so asyncio.to_thread uses our 20-worker pool."""
    asyncio.get_event_loop().set_default_executor(_THREAD_POOL)
    yield


app = FastAPI(
    title="NZ Meal Cost Optimiser",
    description="Query Pak'nSave / New World / Woolworths prices concurrently to find the cheapest meal.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "supabase_enabled": settings.supabase_enabled}


@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index_old.html")


@app.get("/app")
@app.get("/app/")
def vue_app():
    return FileResponse(STATIC_DIR / "vue" / "index.html")


@app.get("/dishes")
def dishes() -> dict:
    """Expose curated dishes to the static Vue dashboard."""
    with open(DATA_DIR / "dishes.json", encoding="utf-8") as handle:
        return json.load(handle)


@app.post("/optimise", response_model=OptimisationResult)
async def optimise(req: DishRequest):
    return await run_optimisation(
        req.dish, req.address, req.distance_km,
        req.max_stores_per_company, req.companies, req.portions,
    )


async def run_optimisation(
    dish_name: str,
    address: str,
    distance_km: float = 5.0,
    max_stores_per_company: int = 3,
    companies: Optional[list[str]] = None,
    portions: int = 4,
) -> OptimisationResult:
    """Run concurrent fetch across all companies/stores/ingredients.

    Returns all product rows (same format as full_results.csv) plus a
    per-store cost breakdown using quantity-scaled "used cost".
    """
    start = time.time()

    # --- Phase 1: Resolve ingredients (curated first, LLM fallback) ---
    dish_dict, source = resolve_ingredients(dish_name, portions=portions)

    dish_name_resolved = dish_dict.get("dish_name", dish_name)
    ingredients = dish_dict.get("ingredients", [])

    # Normalize: ensure all ingredients are dicts with 'search_term'
    if ingredients and isinstance(ingredients[0], str):
        ingredients = [{"search_term": t} for t in ingredients]

    search_terms = [ing.get("search_term", "") for ing in ingredients]
    search_terms = [t for t in search_terms if t]
    ing_lookup = {ing["search_term"]: ing for ing in ingredients if isinstance(ing, dict) and "search_term" in ing}

    if not search_terms:
        raise HTTPException(status_code=400, detail=f"Could not resolve ingredients for dish '{dish_name}'")

    if companies is None:
        companies = list(BRANDS.keys())
    invalid = [c for c in companies if c not in BRANDS]
    if invalid:
        raise HTTPException(400, f"Unsupported company: {invalid}")

    log.info(
        "Optimising '%s' near '%s' (%.1f km), max %d stores per company, portions=%d (source=%s)",
        dish_name, address, distance_km, max_stores_per_company, portions, source,
    )

    # --- Phase 1b: Geocode ---
    user_lat, user_lon = optimiser_utils.geocode(address)
    if user_lat is None:
        raise HTTPException(status_code=400, detail=f"Could not geocode address '{address}'")
    log.info("Geocoded: lat=%.4f lon=%.4f", user_lat, user_lon)

    # --- Phase 2: Build concurrent tasks ---
    tasks = []
    task_metadata = []  # (company, store_id, store_name, ingredient)
    for company_name in companies:
        cfg = BRANDS[company_name]
        if company_name == "Woolworths":
            nearby = woolworths_api.get_nearby_stores(user_lat, user_lon, max_dist_km=distance_km)
        else:
            nearby = cfg["find_nearby"](user_lat, user_lon, radius_km=distance_km)
        nearby = nearby[:max_stores_per_company]
        for store in nearby:
            store_id = store["store_id"]
            store_name = store["name"]
            for ingredient in search_terms:
                tasks.append(_fetch_ingredient(company_name, store_id, store_name, ingredient))
                task_metadata.append((company_name, store_id, store_name, ingredient))

    log.info(
        "Launching %d concurrent searches across %d stores...",
        len(tasks), len({t[1] for t in task_metadata}),
    )
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    log.info("All searches completed in %.2fs", time.time() - start)

    # --- Phase 3: Collect all rows ---
    all_rows = []
    for (company, _sid, store_name, ingredient), result in zip(task_metadata, raw_results):
        if isinstance(result, Exception):
            log.warning("Error fetching %s@%s: %s", ingredient, store_name, result)
            continue
        if result:
            all_rows.extend(result)

    if not all_rows:
        return OptimisationResult(
            dish=dish_name_resolved,
            companies_checked=companies,
            rows=[],
            store_costs=[],
            timestamp=datetime.now().isoformat(),
        )

    # --- Phase 3b: Enrich rows with LLM ingredient quantities ---
    for row in all_rows:
        ing = ing_lookup.get(row.get("search_ingredient", ""), {})
        row["ingredient_quantity"] = ing.get("quantity") if ing.get("quantity") is not None else ""
        row["ingredient_measurement"] = ing.get("unit", "")
        row["ingredient_approx_quantity"] = ing.get("approx_quantity")
        row["ingredient_approx_unit"] = ing.get("approx_unit")
        row["is_valid"] = ""

    # --- Phase 3c: Run parse_optimiser_columns for quantity scaling ---
    for row in all_rows:
        try:
            scaled = parse_optimiser_columns(row)
            row["used_price"] = scaled.get("used_price")
            row["purchase_quantity"] = scaled.get("purchase_quantity")
            row["purchase_price"] = scaled.get("purchase_price")
            row["scaling_ratio"] = scaled.get("scaling_ratio")
            row["status"] = scaled.get("status")
            row["units_match"] = scaled.get("units_match")
            row["unit_approximate"] = scaled.get("unit_approximate")
            row["pack_price"] = float(row.get("price", 0)) if row.get("price") not in ("", None) else 0.0
        except Exception as e:
            log.warning("Scaling error for row sku=%s: %s", row.get("sku", "?"), e)
            row["used_price"] = None
            row["purchase_quantity"] = 0
            row["purchase_price"] = None
            row["scaling_ratio"] = None
            row["status"] = "error"
            row["units_match"] = False
            row["unit_approximate"] = False
            row["pack_price"] = float(row.get("price", 0)) if row.get("price") not in ("", None) else 0.0

    # --- Phase 4: Build per-store cost summary ---
    # For each (store, search_ingredient), pick the cheapest valid product
    # (preferring exact unit matches), then sum used_price across ingredients
    # per store to get the total "used cost" for that store.
    store_ingredients: dict[str, dict[str, list[dict]]] = {}
    for row in all_rows:
        store_name = row.get("store", "")
        term = row.get("search_ingredient", "")
        store_ingredients.setdefault(store_name, {}).setdefault(term, []).append(row)

    store_costs = []
    for store_name, ing_map in store_ingredients.items():
        total_used = 0.0
        valid_ing_count = 0
        best_per_ingredient = []
        company = ""
        for term, rows in ing_map.items():
            for r in rows:
                if r.get("company"):
                    company = r["company"]
                    break
            valid = [r for r in rows if r.get("used_price") is not None]
            if valid:
                best = min(
                    valid,
                    key=lambda r: (r["used_price"], 0 if r.get("units_match", False) else 1),
                )
                total_used += best["used_price"]
                valid_ing_count += 1
                best_per_ingredient.append({
                    "search_ingredient": term,
                    "returned_ingredient": best.get("returned_ingredient", ""),
                    "price": best.get("price", ""),
                    "ingredient_quantity": best.get("ingredient_quantity", ""),
                    "ingredient_measurement": best.get("ingredient_measurement", ""),
                    "ingredient_approx_quantity": best.get("ingredient_approx_quantity"),
                    "ingredient_approx_unit": best.get("ingredient_approx_unit"),
                    "quantity": best.get("quantity", ""),
                    "measurement_unit": best.get("measurement_unit", ""),
                    "used_price": round(best["used_price"], 2),
                    "purchase_quantity": best.get("purchase_quantity", 0),
                    "purchase_price": round(best["purchase_price"], 2) if best.get("purchase_price") is not None else None,
                    "status": best.get("status", ""),
                })
        store_costs.append({
            "store": store_name,
            "company": company,
            "total_used_cost": round(total_used, 2),
            "ingredients_matched": valid_ing_count,
            "ingredients_total": len(ing_map),
            "best_per_ingredient": best_per_ingredient,
        })

    store_costs.sort(key=lambda x: x["total_used_cost"])

    return OptimisationResult(
        dish=dish_name_resolved,
        companies_checked=companies,
        rows=all_rows,
        store_costs=store_costs,
        timestamp=datetime.now().isoformat(),
    )


def _fetch_woolworths_sync(store_id: str, store_name: str, ingredient: str) -> list[dict]:
    """Synchronous Woolworths search — called from a background thread.

    Creates a fresh session per call (cookie isolation), searches for the
    ingredient, and returns ALL priced product rows in CSV_COLUMNS format.
    Price is in dollars (already handled by build_woolworths_row).
    """
    session = woolworths_api.create_session()
    try:
        woolworths_api.set_store_context(session, store_id)
        products = woolworths_api.search_products(session, ingredient, food_only=True, size=20)
        if not products:
            return []
        now = datetime.now()
        rows = []
        for prod in products:
            if prod.get("salePrice") is not None:
                row = build_woolworths_row(
                    "Woolworths", store_name, store_id, ingredient, prod, now,
                )
                rows.append(row)
        return rows
    finally:
        session.close()


def _fetch_foodstuffs_sync(company: str, store_id: str, store_name: str, ingredient: str) -> list[dict]:
    """Synchronous Foodstuffs (Pak'nSave/New World) Edge search — called from a background thread.

    Creates a new API instance, authenticates if needed, runs the two-pass
    search, and returns ALL priced product rows in CSV_COLUMNS format.
    Price is in cents (build_edge_row handles the /100 conversion).
    """
    cfg = BRANDS[company]
    api = cfg["api_class"]()
    if not api.token:
        api.authenticate()
    region = "NI"
    now = datetime.now()
    rows = []
    try:
        products, pass1_hits = api.search_ingredient(store_id, ingredient, region=region)
        if not products:
            return rows
        pass1_by_id = {h["productID"]: h for h in pass1_hits}
        for prod in products:
            hit = pass1_by_id.get(prod.get("productId", ""))
            row = build_edge_row(
                cfg["company_id"], store_name, store_id, ingredient,
                prod, hit, now,
            )
            if row["price"] != "":
                rows.append(row)
        return rows
    finally:
        pass


async def _fetch_ingredient(company: str, store_id: str, store_name: str, ingredient: str) -> list[dict]:
    """Offload a blocking ingredient search to a background thread.

    Returns a list of CSV_COLUMNS-format row dicts (all products, not just
    the cheapest). ``asyncio.to_thread`` runs the sync function on a
    background thread from the pool (20 workers).
    """
    if company == "Woolworths":
        return await asyncio.to_thread(_fetch_woolworths_sync, store_id, store_name, ingredient)
    else:
        return await asyncio.to_thread(_fetch_foodstuffs_sync, company, store_id, store_name, ingredient)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
