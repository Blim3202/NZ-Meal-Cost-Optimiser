r"""FastAPI entrypoint for the NZ Meal Cost Optimiser.

Run:
    .venv\Scripts\uvicorn NZMealOptimiser.web.main:app --port 8000
or (with the package installed):
    python -m uvicorn NZMealOptimiser.web.main:app --port 8000

Optimisations run as background jobs so clients can watch live progress:

    POST /optimise/jobs   -> {"job_id": "..."}  queues the run, returns at once
    GET  /optimise/{id}?events_since=N -> snapshot with status, current phase,
        elapsed seconds, per-company progress (stores done / products found),
        the incremental event log (cursor-based), and the final result.

Frontends:
    GET /       classic dashboard (index_old.html)
    GET /app    Vue dashboard (static/vue/index.html, single-page entry)
    GET /test   Vue dish-builder dashboard (static/vue/test.html, second
                multi-page entry) — adds preset/custom recipe modes, a full
                ingredient editor (add/remove/edit rows, canonical units with
                alias normalisation, approx fallbacks) and "Save as preset".

Dish sources:
    1. req.custom_dish  — explicit builder recipe; validated + unit-normalised,
       quantities scaled from its base_portions to the requested portions.
    2. resolve_ingredients() — curated dishes.json → LLM → fallback. Curated
       and LLM recipes are portion-scaled by the same helper, so the Portions
       control is honoured uniformly across every source.

Both job paths share one pipeline. Searches are offloaded to a thread pool
(20 workers) via asyncio.to_thread; results are consumed with
asyncio.as_completed so progress updates stream in per-search rather than
per-batch. POST /optimise remains as a synchronous endpoint for the classic
dashboard. An HTTP middleware logs every request's method/path/status/duration.

Woolworths sessions are isolated per-store (fresh session + cookie per store).
Foodstuffs (Pak'nSave/New World) Edge clients are authenticated ONCE per
company per request and shared across all their searches. Nominatim geocode
runs once per request (not parallelized).

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

from collections import OrderedDict, defaultdict
from contextlib import asynccontextmanager
import asyncio
import concurrent.futures
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from NZMealOptimiser import DATA_DIR
from NZMealOptimiser.llm.llm_utils import (
    normalise_unit,
    resolve_ingredients,
    parse_optimiser_columns,
)
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


COMPANY_LABELS = {"PaknSave": "Pak'nSave", "NewWorld": "New World", "Woolworths": "Woolworths"}
COMPANY_CODES = {"PaknSave": "PNS", "NewWorld": "NW", "Woolworths": "WW"}
MAX_RETAINED_JOBS = 40


class JobState:
    """Mutable progress state for one optimisation request.

    All mutation happens inside the pipeline coroutine on the event-loop
    thread; snapshot reads (GET /optimise/{job_id}) run on that same loop,
    so no locking is required. The search threads themselves never touch
    this object — their results are consumed by as_completed on the loop.
    """

    def __init__(self, req: DishRequest):
        self.id = uuid.uuid4().hex[:12]
        self.req = req
        self.status = "queued"  # queued -> running -> complete | error
        self.phase = "Queued"
        self.created = time.time()
        self.started: Optional[float] = None
        self.finished: Optional[float] = None
        self.error_detail: Optional[str] = None
        self.error_status = 500
        self.total_tasks = 0
        self.done_tasks = 0
        self.products_found = 0
        self.company_progress: dict[str, dict] = {}
        self.events: list[dict] = []
        self.result: Optional["OptimisationResult"] = None

    def start(self) -> None:
        self.status = "running"
        self.started = time.time()

    def log_event(self, kind: str, text: str, company: Optional[str] = None) -> None:
        """Append an event for the live console. kind: phase|info|ok|warn|err|done."""
        elapsed = round(time.time() - (self.started or self.created), 1)
        self.events.append({
            "i": len(self.events),
            "t": elapsed,
            "kind": kind,
            "co": COMPANY_CODES.get(company) if company else None,
            "text": text,
        })

    def init_company(self, name: str) -> None:
        if name not in self.company_progress:
            self.company_progress[name] = {
                "id": name,
                "label": COMPANY_LABELS.get(name, name),
                "code": COMPANY_CODES.get(name, "?"),
                "stores_total": 0,
                "stores_done": 0,
                "products": 0,
            }

    def snapshot(self, events_since: int = -1) -> dict:
        end = self.finished or time.time()
        return {
            "job_id": self.id,
            "dish": self.req.dish,
            "address": self.req.address,
            "status": self.status,
            "phase": self.phase,
            "error_detail": self.error_detail,
            "elapsed_seconds": round(end - (self.started or self.created), 1),
            "total_tasks": self.total_tasks,
            "done_tasks": self.done_tasks,
            "products_found": self.products_found,
            "companies": [dict(v) for v in self.company_progress.values()],
            "next_cursor": len(self.events) - 1,
            "events": [e for e in self.events if e["i"] > events_since],
            "result": self.result.model_dump() if self.result is not None else None,
        }


JOBS: "OrderedDict[str, JobState]" = OrderedDict()
_BACKGROUND_TASKS: set = set()


def _register_job(job: JobState) -> None:
    JOBS[job.id] = job
    while len(JOBS) > MAX_RETAINED_JOBS:
        for job_id, j in list(JOBS.items()):
            if j.status in ("complete", "error"):
                del JOBS[job_id]
                break
        else:
            break


# Increase asyncio's default thread pool from 5 to 20 workers.
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=20)


class CustomIngredient(BaseModel):
    search_term: str
    quantity: float
    unit: str = ""
    approx_quantity: Optional[float] = None
    approx_unit: Optional[str] = None


class CustomDish(BaseModel):
    """A hand-built recipe; quantities are expressed at ``base_portions``."""

    dish_name: str
    base_portions: int = 4
    ingredients: list[CustomIngredient]


class DishRequest(BaseModel):
    dish: str
    address: str
    distance_km: float = 5.0
    max_stores_per_company: int = 3
    companies: Optional[list[str]] = None  # None = all 3
    portions: int = 4
    latitude: Optional[float] = None  # device GPS: bypasses Nominatim when set
    longitude: Optional[float] = None
    # Explicit recipe (from the /test dish builder). When set, ingredient
    # resolution is bypassed entirely — no curated lookup, no LLM call.
    custom_dish: Optional[CustomDish] = None


def _clean_custom_ingredients(ingredients: list[CustomIngredient]) -> list[dict]:
    """Normalise builder rows into curated-schema dicts.

    Strips search terms, normalises units through UNIT_ALIASES ("pk" ->
    "pack", "ea" -> "each"), drops empty approx fields, and rejects blank or
    duplicate terms (case-insensitive) with a 400.
    """
    seen: set[str] = set()
    cleaned: list[dict] = []
    for ing in ingredients:
        term = ing.search_term.strip()
        if not term:
            raise HTTPException(400, "Every ingredient needs a non-empty search term")
        key = term.lower()
        if key in seen:
            raise HTTPException(400, f"Duplicate ingredient '{term}' — merge or rename it")
        seen.add(key)
        entry: dict = {
            "quantity": float(ing.quantity),
            "unit": normalise_unit(ing.unit),
            "search_term": term,
        }
        if ing.approx_quantity is not None:
            entry["approx_quantity"] = float(ing.approx_quantity)
            entry["approx_unit"] = normalise_unit(ing.approx_unit or "")
        cleaned.append(entry)
    return cleaned


def _validate_custom_dish(custom: CustomDish) -> tuple[str, int, list[dict]]:
    """Validate a builder dish and return (dish_name, base_portions, ingredients)."""
    name = custom.dish_name.strip()
    if not name:
        raise HTTPException(400, "The dish needs a name")
    base = int(custom.base_portions) if custom.base_portions else 4
    base = max(1, min(base, 24))
    if not custom.ingredients:
        raise HTTPException(400, f"Custom dish '{name}' needs at least one ingredient")
    return name, base, _clean_custom_ingredients(custom.ingredients)


def _scale_ingredients_to_portions(dish_dict: dict, target_portions: int) -> dict:
    """Scale numeric ingredient quantities from the recipe's base portions to
    ``target_portions``.

    Applied uniformly to every source (curated / LLM / custom) so the
    Portions control is meaningful everywhere; a no-op when they already
    match. String-form legacy ingredients pass through untouched.
    """
    target = max(1, int(target_portions))
    raw_base = dish_dict.get("portion")
    try:
        base = max(1, int(raw_base))
    except (TypeError, ValueError):
        base = target
    dish_dict["portion"] = target
    if base == target:
        return dish_dict
    factor = target / base
    scaled: list = []
    for ing in dish_dict.get("ingredients", []):
        if isinstance(ing, dict):
            ing = dict(ing)
            for key in ("quantity", "approx_quantity"):
                value = ing.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    ing[key] = round(value * factor, 3)
        scaled.append(ing)
    dish_dict["ingredients"] = scaled
    dish_dict["_scale_factor"] = factor
    return dish_dict


# Rough bounding box of New Zealand (incl. Chathams margin). GPS coords
# outside it are rejected so a laptop in Sydney can't silently query Auckland.
NZ_LAT_RANGE = (-47.6, -34.2)
NZ_LON_RANGE = (166.2, 178.9)


def _resolve_origin(job: JobState) -> tuple[float, float, str]:
    """Return (lat, lon, source) for the search origin.

    Uses device GPS coordinates when the request carries them; otherwise
    falls back to Nominatim geocoding of the address string. Raises
    HTTPException on invalid/out-of-NZ coords or a failed geocode.
    """
    req = job.req
    has_gps = req.latitude is not None or req.longitude is not None
    if has_gps:
        if req.latitude is None or req.longitude is None:
            raise HTTPException(400, "latitude and longitude must be provided together")
        lat, lon = float(req.latitude), float(req.longitude)
        if not (NZ_LAT_RANGE[0] <= lat <= NZ_LAT_RANGE[1] and NZ_LON_RANGE[0] <= lon <= NZ_LON_RANGE[1]):
            raise HTTPException(
                400,
                f"GPS location ({lat:.4f}, {lon:.4f}) is outside New Zealand — "
                "this service only covers NZ stores.",
            )
        job.phase = "Locating origin"
        job.log_event("ok", f"Using device GPS location ({lat:.4f}, {lon:.4f})")
        return lat, lon, "gps"
    job.phase = "Geocoding address"
    job.log_event("info", f"Geocoding '{req.address}'…")
    lat, lon = optimiser_utils.geocode(req.address)
    if lat is None:
        raise HTTPException(status_code=400, detail=f"Could not geocode address '{req.address}'")
    job.log_event("ok", f"Geocoded to {lat:.4f}, {lon:.4f}")
    return float(lat), float(lon), "geocoded"


class OptimisationResult(BaseModel):
    dish: str
    companies_checked: list[str]
    rows: list[dict]
    store_costs: list[dict]
    timestamp: str
    duration_seconds: float = 0.0
    origin: Optional[dict] = None  # {lat, lon, source} reference point for the map
    dish_source: str = ""  # "curated" | "custom" — drives the results-header chip


class JobCreated(BaseModel):
    job_id: str


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


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every HTTP request's method, path, status and duration (observability)."""
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("Unhandled error: %s %s", request.method, request.url.path)
        raise
    log.info(
        "%s %s -> %d (%.0f ms)",
        request.method, request.url.path, response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


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


@app.get("/test")
@app.get("/test/")
def test_vue_app():
    """Dish-builder dashboard (multi-page Vue entry: static/vue/test.html)."""
    return FileResponse(STATIC_DIR / "vue" / "test.html")


@app.get("/dishes")
def dishes() -> dict:
    """Expose curated dishes to the static Vue dashboard."""
    with open(DATA_DIR / "dishes.json", encoding="utf-8") as handle:
        return json.load(handle)


class SaveDishRequest(BaseModel):
    """Upsert payload for the dish builder's "Save as preset" button.

    Stored verbatim at its base portions — run-time scaling to the requested
    portions happens per-request in _scale_ingredients_to_portions.
    """

    dish_name: str
    base_portions: int = 4
    ingredients: list[CustomIngredient]


def _load_dishes_file() -> dict:
    path = DATA_DIR / "dishes.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write_dishes_file(data: dict) -> None:
    """Atomic write (temp file + os.replace) so a crash can't corrupt the file."""
    path = DATA_DIR / "dishes.json"
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    tmp.replace(path)


@app.post("/dishes/save")
async def save_dish(req: SaveDishRequest) -> dict:
    """Upsert a builder recipe into data/dishes.json as a preset."""
    name, base_portions, ingredients = _validate_custom_dish(
        CustomDish(
            dish_name=req.dish_name,
            base_portions=req.base_portions,
            ingredients=req.ingredients,
        )
    )
    key = name.lower()
    data = await asyncio.to_thread(_load_dishes_file)
    existed = key in data
    data[key] = {
        "dish_name": name,
        "portion": base_portions,
        "ingredients": ingredients,
    }
    await asyncio.to_thread(_write_dishes_file, data)
    log.info("Saved preset dish '%s' (%s)", name, "updated" if existed else "new")
    return {"ok": True, "key": key, "updated": existed, "dishes_count": len(data)}


_GEOCODE_CACHE: OrderedDict[str, tuple[float, float]] = OrderedDict()
_GEOCODE_CACHE_MAX = 200


@app.get("/geocode")
async def geocode_endpoint(address: str):
    """Resolve one address to coordinates without starting a run.

    Backs the dashboard's two-step flow: "Resolve setup" validates the dish +
    location here, then "Compare prices" submits the run with the resolved
    coords (which also short-circuits _resolve_origin). Nominatim is
    rate-limited (~1 req/sec) and sleeps ~1.1s per uncached call, so results
    are memoised in a small LRU cache and lookups run in the thread pool.
    """
    addr = address.strip()
    if len(addr) < 3:
        raise HTTPException(400, "Address is too short")
    key = addr.lower()
    hit = _GEOCODE_CACHE.get(key)
    if hit is not None:
        _GEOCODE_CACHE.move_to_end(key)
        return {"lat": hit[0], "lon": hit[1], "cached": True}
    lat, lon = await asyncio.to_thread(optimiser_utils.geocode, addr)
    if lat is None:
        raise HTTPException(400, f"Could not geocode address '{addr}'")
    if not (NZ_LAT_RANGE[0] <= lat <= NZ_LAT_RANGE[1] and NZ_LON_RANGE[0] <= lon <= NZ_LON_RANGE[1]):
        raise HTTPException(
            400,
            f"'{addr}' resolves outside New Zealand — this service only covers NZ stores.",
        )
    _GEOCODE_CACHE[key] = (float(lat), float(lon))
    while len(_GEOCODE_CACHE) > _GEOCODE_CACHE_MAX:
        _GEOCODE_CACHE.popitem(last=False)
    return {"lat": float(lat), "lon": float(lon), "cached": False}


@app.get("/stores/nearby")
async def stores_nearby(
    lat: float,
    lon: float,
    distance_km: float = 5.0,
    companies: Optional[str] = None,
    max_per_company: int = 3,
):
    """Preview which stores a run would query, without starting one.

    Backs the dashboard's resolve step: after the origin is verified, the map
    plots the closest stores per selected brand (same helpers and cap as
    Phase 2 of the pipeline). Pure local-CSV + haversine — no supermarket API
    calls, so it is instant and rate-limit-free.
    """
    if not (NZ_LAT_RANGE[0] <= lat <= NZ_LAT_RANGE[1] and NZ_LON_RANGE[0] <= lon <= NZ_LON_RANGE[1]):
        raise HTTPException(
            400,
            f"Location ({lat:.4f}, {lon:.4f}) is outside New Zealand — this service only covers NZ stores.",
        )
    requested = [c.strip() for c in companies.split(",")] if companies else list(BRANDS)
    requested = [c for c in requested if c in BRANDS]
    if not requested:
        raise HTTPException(400, "No valid companies requested")
    cap = max(1, min(int(max_per_company), 10))
    stores: list[dict] = []
    for name in requested:
        cfg = BRANDS[name]
        if name == "Woolworths":
            nearby = await asyncio.to_thread(woolworths_api.get_nearby_stores, lat, lon, distance_km)
        else:
            nearby = await asyncio.to_thread(cfg["find_nearby"], lat, lon, distance_km)
        for store in nearby[:cap]:
            stores.append({
                "company": name,
                "store": store["name"],
                "lat": store.get("lat", store.get("latitude")),
                "lon": store.get("lon", store.get("longitude")),
                "distance_km": round(float(store.get("distance_km", 0.0)), 2),
            })
    return {"origin": {"lat": lat, "lon": lon}, "stores": stores}


@app.post("/optimise", response_model=OptimisationResult)
async def optimise(req: DishRequest):
    """Legacy synchronous endpoint (classic dashboard): runs the pipeline inline."""
    job = _new_job(req)
    await _run_job(job)
    if job.status == "error":
        raise HTTPException(job.error_status, job.error_detail)
    assert job.result is not None
    return job.result


@app.post("/optimise/jobs", response_model=JobCreated)
async def create_optimisation_job(req: DishRequest):
    """Queue an optimisation and return immediately with its pollable job id."""
    job = _new_job(req)
    task = asyncio.create_task(_run_job(job))
    _BACKGROUND_TASKS.add(task)  # strong ref so the task isn't GC'd mid-run
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return JobCreated(job_id=job.id)


@app.get("/optimise/{job_id}")
def optimise_job_snapshot(job_id: str, events_since: int = -1) -> dict:
    """Progress snapshot for a job. Pass events_since=<next_cursor> to get
    only new console events; ``result`` appears once status is complete."""
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"Unknown job '{job_id}'")
    return job.snapshot(events_since)


def _new_job(req: DishRequest) -> JobState:
    if req.companies is not None:
        invalid = [c for c in req.companies if c not in BRANDS]
        if invalid:
            raise HTTPException(400, f"Unsupported company: {invalid}")
    # Reject broken builder recipes up front so clients get an immediate 400
    # instead of discovering them mid-run.
    if req.custom_dish is not None:
        _validate_custom_dish(req.custom_dish)
    job = JobState(req)
    _register_job(job)
    return job


async def _run_job(job: JobState) -> None:
    job.start()
    try:
        job.result = await _execute_pipeline(job)
        job.status = "complete"
        job.phase = "Completed"
    except HTTPException as exc:
        job.status = "error"
        job.error_detail = str(exc.detail)
        job.error_status = exc.status_code
        job.phase = "Failed"
    except Exception as exc:  # noqa: BLE001 — surface anything to the client
        log.exception("Job %s failed", job.id)
        job.status = "error"
        job.error_detail = f"{type(exc).__name__}: {exc}"
        job.error_status = 500
        job.phase = "Failed"
    finally:
        job.finished = time.time()
        job.log_event(
            "done" if job.status == "complete" else "err",
            f"Job {job.status}" + (f": {job.error_detail}" if job.error_detail else ""),
        )


async def _execute_pipeline(job: JobState) -> OptimisationResult:
    """Run concurrent fetch across all companies/stores/ingredients.

    Returns all product rows (same format as full_results.csv) plus a
    per-store cost breakdown using quantity-scaled "used cost". Progress
    (phase changes, per-search outcomes, per-company counters) is written
    into ``job`` as the run unfolds.
    """
    req = job.req
    dish_name = req.dish
    start = time.time()

    # --- Phase 1: Resolve ingredients (custom builder → curated → LLM) ---
    job.phase = "Resolving ingredients"
    if req.custom_dish is not None:
        base_name, base_portions, custom_ingredients = _validate_custom_dish(req.custom_dish)
        dish_dict = {
            "dish_name": base_name,
            "portion": base_portions,
            "ingredients": custom_ingredients,
        }
        source = "custom"
        dish_name = base_name
        job.log_event(
            "phase",
            f"Building custom dish '{base_name}' ({len(custom_ingredients)} ingredients "
            f"@ {base_portions} portions)",
        )
        job.log_event("ok", f"Custom recipe accepted: {', '.join(i['search_term'] for i in custom_ingredients)}")
    else:
        job.log_event("phase", f"Resolving ingredients for '{dish_name}'")
        dish_dict, source = resolve_ingredients(dish_name, portions=req.portions)

    # Uniform portions scaling: quantities are defined at the recipe's base
    # portions and rescaled to the requested count (no-op when equal).
    try:
        recipe_base = max(1, int(dish_dict.get("portion")))
    except (TypeError, ValueError):
        recipe_base = req.portions
    dish_dict = _scale_ingredients_to_portions(dish_dict, req.portions)
    scale_factor = dish_dict.pop("_scale_factor", 1.0)
    if scale_factor != 1.0:
        job.log_event(
            "info",
            f"Scaled quantities ×{scale_factor:g} for {req.portions} portions "
            f"(recipe base {recipe_base})",
        )

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
    job.log_event("ok", f"{len(search_terms)} ingredients resolved ({source}): {', '.join(search_terms)}")

    companies = req.companies or list(BRANDS.keys())

    log.info(
        "Job %s: optimising '%s' near '%s' (%.1f km), max %d stores/company, portions=%d (%s)",
        job.id, dish_name, req.address, req.distance_km, req.max_stores_per_company, req.portions, source,
    )

    # --- Phase 1b: Locate origin (device GPS or Nominatim geocode) ---
    user_lat, user_lon, origin_source = _resolve_origin(job)
    origin = {"lat": user_lat, "lon": user_lon, "source": origin_source}

    # --- Phase 2: Build concurrent tasks ---
    # Authenticate ONE Edge API client per Foodstuffs company up front and
    # share it across all of that company's searches. Post-auth methods use
    # plain requests.post with the cached JWT, so concurrent use across the
    # thread pool is safe (the Session is only touched during authenticate()).
    job.phase = "Connecting to supermarkets"
    api_instances: dict[str, object] = {}
    for company_name in companies:
        cfg = BRANDS[company_name]
        if "api_class" in cfg:
            job.log_event("info", "Authenticating Edge API…", company_name)
            api_instances[company_name] = await asyncio.to_thread(
                _make_authenticated_api, cfg["api_class"]
            )
            job.log_event("ok", "Authenticated", company_name)

    job.phase = "Finding nearby stores"
    metas: list[tuple[str, str, str, str]] = []  # (company, store_id, store_name, ingredient)
    regions: dict[tuple[str, str], str] = {}  # (company, store_id) -> NI/SI
    store_geo: dict[tuple[str, str], dict] = {}  # (company, store_name) -> map pin data
    for company_name in companies:
        cfg = BRANDS[company_name]
        job.init_company(company_name)
        prog = job.company_progress[company_name]
        if company_name == "Woolworths":
            nearby = woolworths_api.get_nearby_stores(user_lat, user_lon, max_dist_km=req.distance_km)
        else:
            nearby = cfg["find_nearby"](user_lat, user_lon, radius_km=req.distance_km)
        nearby = nearby[:req.max_stores_per_company]

        # Store summaries are grouped by (company, store name) in Phase 4.
        # Two different stores sharing a name within one brand would merge
        # into a single card with a combined total. Names embed locations so
        # this is unlikely — fail fast with a clear error rather than emit a
        # misleading summary.
        seen_names: dict[str, str] = {}
        for store in nearby:
            prior_id = seen_names.get(store["name"])
            if prior_id and prior_id != store["store_id"]:
                raise HTTPException(
                    400,
                    f"Two {company_name} stores share the name '{store['name']}' "
                    f"({prior_id} vs {store['store_id']}); cannot disambiguate.",
                )
            seen_names[store["name"]] = store["store_id"]

        prog["stores_total"] = len(nearby)
        for store in nearby:
            store_id = store["store_id"]
            store_name = store["name"]
            regions[(company_name, store_id)] = store.get("region", "")
            # Foodstuffs CSVs use latitude/longitude; Woolworths uses lat/lon.
            store_geo[(company_name, store_name)] = {
                "lat": store.get("lat", store.get("latitude")),
                "lon": store.get("lon", store.get("longitude")),
                "distance_km": round(float(store.get("distance_km", 0.0)), 2),
            }
            for ingredient in search_terms:
                metas.append((company_name, store_id, store_name, ingredient))
        if nearby:
            job.log_event("ok", f"{len(nearby)} store(s) within {req.distance_km:g} km", company_name)
        else:
            job.log_event("warn", f"No stores within {req.distance_km:g} km", company_name)

    job.total_tasks = len(metas)
    job.phase = f"Searching {len(metas)} store × ingredient combos"
    job.log_event(
        "phase",
        f"Searching {len(metas)} combos across "
        f"{sum(p['stores_total'] for p in job.company_progress.values())} stores…",
    )

    async def _run_one(meta):
        company, store_id, store_name, ingredient = meta
        try:
            rows = await _fetch_ingredient(
                company, api_instances.get(company), store_id, store_name,
                ingredient, regions.get((company, store_id), ""),
            )
            return meta, rows, None
        except Exception as exc:  # noqa: BLE001 — recorded as a failed search
            return meta, [], exc

    all_rows: list[dict] = []
    outcomes: dict[tuple, dict] = {}  # meta -> {status, products, detail}
    done_per_store: dict[tuple, int] = defaultdict(int)
    for fut in asyncio.as_completed([_run_one(m) for m in metas]):
        meta, rows, exc = await fut
        company, _sid, store_name, ingredient = meta
        prog = job.company_progress[company]
        job.done_tasks += 1
        if exc is not None:
            outcomes[meta] = {"status": "error", "products": 0, "detail": f"{type(exc).__name__}: {exc}"}
            log.warning("Error fetching %s@%s: %s", ingredient, store_name, exc)
            job.log_event("err", f"{ingredient} @ {store_name} — {outcomes[meta]['detail']}", company)
        elif not rows:
            outcomes[meta] = {"status": "no_match", "products": 0, "detail": "no products returned"}
            job.log_event("warn", f"{ingredient} @ {store_name} — no results", company)
        else:
            outcomes[meta] = {"status": "ok", "products": len(rows), "detail": ""}
            job.products_found += len(rows)
            prog["products"] += len(rows)
            all_rows.extend(rows)
            job.log_event("ok", f"{ingredient} @ {store_name} → {len(rows)} products", company)
        store_key = (company, _sid)
        done_per_store[store_key] += 1
        if done_per_store[store_key] == len(search_terms):
            prog["stores_done"] += 1

    log.info("All searches completed in %.2fs", time.time() - start)

    if not all_rows:
        return OptimisationResult(
            dish=dish_name_resolved,
            companies_checked=companies,
            rows=[],
            store_costs=[],
            timestamp=datetime.now().isoformat(),
            duration_seconds=round(time.time() - start, 2),
            origin=origin,
            dish_source=source,
        )

    # --- Phase 3b: Enrich rows with LLM ingredient quantities ---
    job.phase = "Scaling quantities"
    job.log_event("phase", f"Computing scaled used-costs for {len(all_rows)} products")
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
    # per store to get the total "used cost" for that store. Three honesty
    # guarantees:
    #   1. failed/no-match searches AND ingredients whose every product is
    #      unit-incompatible (e.g. recipe needs 6 eggs; store sells per egg)
    #      are attached to the store as "issues",
    #   2. ingredients_total is the REQUESTED ingredient count, not the count
    #      that happened to return rows,
    #   3. stores are ranked complete-basket-first, then by total cost — a
    #      partial basket can never win on a missing ingredient's $0.
    issues_by_store: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for (company, _sid, store_name, ingredient), oc in outcomes.items():
        if oc["status"] != "ok":
            issues_by_store[(company, store_name)].append({
                "search_ingredient": ingredient,
                "status": oc["status"],
                "detail": oc["detail"],
            })

    # Group rows by (company, store name). Same-name/different-ID collisions
    # between stores of one brand are rejected up front in Phase 2, so this
    # grouping cannot silently merge two distinct stores.
    store_ingredients: dict[tuple[str, str], dict[str, list[dict]]] = {}
    for row in all_rows:
        group_key = (row.get("company", ""), row.get("store", ""))
        term = row.get("search_ingredient", "")
        store_ingredients.setdefault(group_key, {}).setdefault(term, []).append(row)

    store_costs = []
    for (company, store_name), ing_map in store_ingredients.items():
        total_used = 0.0
        best_per_ingredient = []
        for term, rows in ing_map.items():
            valid = [r for r in rows if r.get("used_price") is not None]
            if valid:
                best = min(
                    valid,
                    key=lambda r: (r["used_price"], 0 if r.get("units_match", False) else 1),
                )
                total_used += best["used_price"]
                best_per_ingredient.append({
                    "search_ingredient": term,
                    "returned_ingredient": best.get("returned_ingredient", ""),
                    "brand": best.get("brand", ""),
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
            else:
                # Products came back but none could be scaled to the recipe's
                # units — the ingredient costs the store $0 right now, which
                # must be visible, not folded into a too-cheap total.
                issues_by_store[(company, store_name)].append({
                    "search_ingredient": term,
                    "status": "incompatible_units",
                    "detail": f"{len(rows)} product(s) returned; none sold in units compatible with the recipe",
                })
        store_issues = issues_by_store.get((company, store_name), [])
        geo = store_geo.get((company, store_name), {})
        store_costs.append({
            "store": store_name,
            "company": company,
            "total_used_cost": round(total_used, 2),
            "ingredients_matched": len(best_per_ingredient),
            "ingredients_total": len(search_terms),
            "complete": len(best_per_ingredient) == len(search_terms),
            "best_per_ingredient": best_per_ingredient,
            "issues": store_issues,
            "lat": geo.get("lat"),
            "lon": geo.get("lon"),
            "distance_km": geo.get("distance_km"),
        })

    # Complete baskets first (truthful comparison set), then cheapest.
    store_costs.sort(key=lambda x: (not x["complete"], x["total_used_cost"]))

    if store_costs:
        best = store_costs[0]
        job.log_event(
            "done",
            f"Winner: {best['store']} ({COMPANY_LABELS.get(best['company'], best['company'])}) "
            f"at ${best['total_used_cost']:.2f}",
        )
    duration = round(time.time() - start, 2)
    log.info("Job %s complete in %.2fs: %d products, %d stores", job.id, duration, len(all_rows), len(store_costs))

    return OptimisationResult(
        dish=dish_name_resolved,
        companies_checked=companies,
        rows=all_rows,
        store_costs=store_costs,
        timestamp=datetime.now().isoformat(),
        duration_seconds=duration,
        origin=origin,
        dish_source=source,
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


def _make_authenticated_api(api_class):
    """Create an Edge API client and authenticate it (blocking — run in a thread).

    Called once per Foodstuffs company per request; the returned instance is
    shared across all of that company's store/ingredient searches.
    """
    api = api_class()
    if not api.token:
        api.authenticate()
    return api


def _fetch_foodstuffs_sync(
    company: str, api, store_id: str, store_name: str, ingredient: str, region: str = "",
) -> list[dict]:
    """Synchronous Foodstuffs (Pak'nSave/New World) Edge search — called from a background thread.

    Reuses the shared, already-authenticated Edge API client for the company
    (created once per request) and runs the two-pass search, returning ALL
    priced product rows in CSV_COLUMNS format. Price is in cents
    (build_edge_row handles the /100 conversion). ``region`` comes from the
    store CSV ("NI"/"SI") and feeds the Region cookie, matching the CLI
    optimisers in optimiser_utils.py.
    """
    cfg = BRANDS[company]
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


async def _fetch_ingredient(
    company: str, api, store_id: str, store_name: str, ingredient: str, region: str = "",
) -> list[dict]:
    """Offload a blocking ingredient search to a background thread.

    Returns a list of CSV_COLUMNS-format row dicts (all products, not just
    the cheapest). ``asyncio.to_thread`` runs the sync function on a
    background thread from the pool (20 workers). ``api`` is the shared,
    pre-authenticated Edge API client for Foodstuffs companies (unused for
    Woolworths); ``region`` feeds the Edge API Region cookie.
    """
    if company == "Woolworths":
        return await asyncio.to_thread(_fetch_woolworths_sync, store_id, store_name, ingredient)
    else:
        return await asyncio.to_thread(_fetch_foodstuffs_sync, company, api, store_id, store_name, ingredient, region)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
