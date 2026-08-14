r"""FastAPI entrypoint for the NZ Meal Cost Optimiser.

Run:
    .venv\Scripts\python scripts/fastapi/main.py
or:
    .venv\Scripts\uvicorn main:app --app-dir scripts/fastapi --port 8000

The /optimise endpoint runs all retailer searches concurrently — up to 3
companies x 3 stores x ~6 ingredients = 54 concurrent HTTP requests.
Woolworths sessions are isolated per-store (fresh session + cookie per store).
Nominatim geocode runs once per request (not parallelized).
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import core.paths  # noqa: F401  (bootstrap sys.path for legacy modules)
import optimiser_utils
from core.config import settings
from optimiser_utils import analyse_results, get_ingredients
from paknsave_api import PaknSaveEdgeAPI, find_nearby_stores as ps_find_nearby
from newworld_api import NewWorldEdgeAPI, find_nearby_stores as nw_find_nearby
import woolworths_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fastapi.main")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
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


class DishRequest(BaseModel):
    dish: str
    address: str
    distance_km: float = 5.0
    max_stores_per_company: int = 3
    companies: Optional[list[str]] = None  # None = all 3


class IngredientResult(BaseModel):
    ingredient: str
    store: str
    company: str
    price: float
    unit_price: str
    quantity: str
    found: bool


class OptimisationResult(BaseModel):
    dish: str
    companies_checked: list[str]
    cheapest_store: str
    cheapest_total: float
    store_breakdown: list[dict]
    ingredient_results: list[dict]
    timestamp: str


app = FastAPI(
    title="NZ Meal Cost Optimiser",
    description="Query Pak'nSave / New World / Woolworths prices concurrently to find the cheapest meal.",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "supabase_enabled": settings.supabase_enabled}


@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/optimise", response_model=OptimisationResult)
async def optimise(req: DishRequest):
    return await run_optimisation(req.dish, req.address, req.distance_km, req.max_stores_per_company, req.companies)


async def run_optimisation(dish_name: str, address: str, distance_km: float = 5.0,
                          max_stores_per_company: int = 3, companies: Optional[list[str]] = None) -> OptimisationResult:
    """Run concurrent fetch across all companies/stores/ingredients.

    Returns a structured comparison of the cheapest store for the dish.
    """
    start = time.time()
    dish_name_resolved, search_terms = _resolve_dish_terms(dish_name)
    if not search_terms:
        raise HTTPException(status_code=400, detail=f"Dish '{dish_name}' not found in dishes.json")

    if companies is None:
        companies = list(BRANDS.keys())
    invalid = [c for c in companies if c not in BRANDS]
    if invalid:
        raise HTTPException(400, f"Unsupported company: {invalid}")

    log.info("Optimising '%s' near '%s' (%.1f km), max %d stores per company",
             dish_name, address, distance_km, max_stores_per_company)

    # Single geocoding call
    user_lat, user_lon = optimiser_utils.geocode(address)
    if user_lat is None:
        raise HTTPException(status_code=400, detail=f"Could not geocode address '{address}'")
    log.info("Geocoded: lat=%.4f lon=%.4f", user_lat, user_lon)

    # Build concurrent tasks: 3 companies x 3 stores x 6 ingredients
    tasks = []
    task_metadata = []  # (company, store_id, store_name, ingredient)
    for company_name in companies:
        cfg = BRANDS[company_name]
        nearby = cfg["find_nearby"](user_lat, user_lon, radius_km=distance_km) if company_name != "Woolworths" else \
                   woolworths_api.get_nearby_stores(user_lat, user_lon, max_dist_km=distance_km)
        nearby = nearby[:max_stores_per_company]
        for store in nearby:
            store_id = store["store_id"]
            store_name = store["name"]
            for ingredient in search_terms:
                tasks.append(_fetch_ingredient(company_name, store_id, ingredient))
                task_metadata.append((company_name, store_id, store_name, ingredient))

    log.info("Launching %d concurrent searches across %d stores...", len(tasks), len({t[1] for t in task_metadata}))
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    log.info("All searches completed in %.2fs", time.time() - start)

    # Consolidate results
    store_totals = {}  # store_name -> {company, total_cost, ingredients_detail}
    ingredient_results = []

    for (company, sid, store_name, ingredient), result in zip(task_metadata, raw_results):
        if isinstance(result, Exception):
            log.warning("Error fetching %s@%s: %s", ingredient, store_name, result)
            continue
        if result and result.get("price") is not None:
            row = {
                "company": company,
                "store": store_name,
                "ingredient": ingredient,
                "price": result["price"] / 100.0 if company != "Woolworths" else result["price"],
                "unit_price": result.get("unit_price", ""),
                "quantity": result.get("pack_info", ""),
            }
            ingredient_results.append(row)
            if store_name not in store_totals:
                store_totals[store_name] = {"company": company, "total_cost": 0.0, "ingredients": []}
            # Track best price per ingredient per store for the summary
            store_entry = store_totals[store_name]
            existing_ing = next((i for i in store_entry["ingredients"] if i["ingredient"] == ingredient), None)
            if existing_ing is None:
                store_entry["total_cost"] += row["price"]
                store_entry["ingredients"].append(row)
            elif row["price"] < existing_ing["price"]:
                store_entry["total_cost"] -= existing_ing["price"]
                store_entry["total_cost"] += row["price"]
                existing_ing.update(row)

    # Sort stores by total cost
    breakdown = sorted(store_totals.items(), key=lambda x: x[1]["total_cost"])
    cheapest_name, cheapest_data = breakdown[0] if breakdown else ("No results", None)

    return OptimisationResult(
        dish=dish_name_resolved,
        companies_checked=companies,
        cheapest_store=cheapest_name,
        cheapest_total=round(cheapest_data["total_cost"], 2) if cheapest_data else 0.0,
        store_breakdown=[{"store": s, "company": d["company"], "total_cost": round(d["total_cost"], 2),
                          "ingredients": d["ingredients"]} for s, d in breakdown],
        ingredient_results=ingredient_results,
        timestamp=datetime.now().isoformat(),
    )


async def _fetch_ingredient(company: str, store_id: str, ingredient: str) -> Optional[dict]:
    """Fetch a single ingredient for a single store. Runs concurrently.

    Each call creates its own session/API instance — no shared state.
    """
    if company == "Woolworths":
        # Fresh session per store (cookie isolation is per-Session object)
        session = woolworths_api.create_session()
        try:
            woolworths_api.set_store_context(session, store_id)
            products = woolworths_api.search_products(session, ingredient, food_only=True, size=10)
            priced = [p for p in products if p.get("salePrice") is not None]
            if not priced:
                return None
            best = min(priced, key=lambda p: p["salePrice"])
            return {
                "price": best["salePrice"],
                "unit_price": best.get("cupListPrice", ""),
                "pack_info": f"{best.get('volumeSize', '')}",
            }
        finally:
            session.close()

    # Foodstuffs (Pak'nSave/NewWorld) — Edge API, JWT auth, no per-store sessions
    cfg = BRANDS[company]
    api = cfg["api_class"]()
    await asyncio.sleep(0)  # yield to event loop — auth may block
    if not api.token:
        api.authenticate()
    region = "NI"
    try:
        products, pass1_hits = api.search_ingredient(store_id, ingredient, region=region)
        if not products:
            return None
        # Pick cheapest by unit price
        priced = [p for p in products if p.get("singlePrice", {}).get("price") is not None]
        if not priced:
            return None
        best = min(priced, key=lambda p: p["singlePrice"]["price"])
        sp = best.get("singlePrice", {})
        comp = best.get("promotions", [{}])[0].get("comparativePrice") if best.get("promotions") else None
        comp = comp or sp.get("comparativePrice", {})
        return {
            "price": sp["price"],
            "unit_price": comp.get("measureDescription", "") if comp else "",
            "pack_info": best.get("displayName", ""),
        }
    finally:
        # No session to close for Foodstuffs — token is reusable
        pass


def _resolve_dish_terms(dish_input: str) -> tuple[str, list[str]]:
    """Resolve dish name and return (display_name, search_terms)."""
    search_terms = get_ingredients(dish_input)
    dish_dict = optimiser_utils._resolve_dish_data(dish_input)
    display_name = dish_dict.get("dish_name", dish_input)
    return display_name, search_terms


# --- optional Supabase persistence (not required for core functionality) ---
async def _maybe_persist(result: OptimisationResult):
    if settings.supabase_enabled:
        try:
            from services.supabase_client import get_supabase
            sb = get_supabase()
            sb.from_("optimisation_runs").insert({
                "dish": result.dish,
                "address": result.store_breakdown,
                "companies": result.companies_checked,
                "result": _safe_json(result),
                "created_at": result.timestamp,
            }).execute()
        except Exception as e:
            log.warning("Supabase write failed (non-fatal): %s", e)


def _safe_json(obj) -> str:
    import json
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        return str(obj)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
