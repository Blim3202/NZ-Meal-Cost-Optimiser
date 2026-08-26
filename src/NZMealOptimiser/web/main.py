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
                multi-page entry) — app shell with a left sidebar switching
                between: optimiser dashboard (preset/custom/shopping-list
                modes + full ingredient editor), My Dishes, the LLM Recipe
                Builder (paste an ingredient list -> LLM breakdown), a
                Documentation viewer and a multi-section Settings page.

Supporting endpoints:
    GET  /system-info        effective thread-pool size + danger-zone caps
    GET  /tech-docs[/{name}] whitelisted markdown manuals for the docs page
    POST /dishes/import_text paste recipe text -> LLM ingredient breakdown
                             ({"status": "rejected"} on non-recipe/injection)
    DELETE /dishes/{key}     remove a preset dish

Dish sources:
    1. req.custom_dish  — explicit builder recipe; validated + unit-normalised,
       quantities scaled from its base_portions to the requested portions.
       Also carries the /test "Shopping list" mode: the frontend submits it as
       a custom dish with base_portions=1 and portions=1 (so scaling is a
       no-op) plus source_label="shopping_list", which flows through to
       OptimisationResult.dish_source for the results-header chip.
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
import copy
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
from pydantic import BaseModel, Field

from NZMealOptimiser import DATA_DIR, PROJECT_ROOT
from NZMealOptimiser.llm.llm_utils import (
    normalise_unit,
    resolve_ingredients,
    parse_optimiser_columns,
)
from NZMealOptimiser.llm.generation import (
    GenerationConfigError,
    GenerationError,
    RecipeRejectedError,
    generate_custom_dish,
    generate_custom_dish_from_text,
)
from NZMealOptimiser.pricing import optimiser_utils
from NZMealOptimiser.pricing.optimiser_utils import (
    build_edge_row,
    build_woolworths_row,
    matches_ingredient_filters,
)
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
CUSTOM_DISH_SOURCES = {"custom", "shopping_list"}
MAX_RETAINED_JOBS = 40

# Server-side hard ceilings for the danger-zone overrides. The frontend can
# unlock larger search radii / store caps, but never past these — they bound
# the load one run can place on the supermarket APIs.
HARD_LIMITS = {"max_distance_km": 50.0, "max_stores_per_company": 20}


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
        # Completed runs keep their raw product rows + pipeline context here so
        # POST /optimise/{id}/reapply can recalculate store costs with edited
        # ingredient filters without re-querying any supermarket.
        self.pipeline_cache: Optional[dict] = None

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


# Background search pool. Sized from WEB_MAX_WORKERS (default 20) at import
# time — ThreadPoolExecutor can't be resized live, so changes need a restart.
EFFECTIVE_MAX_WORKERS = max(1, min(int(settings.WEB_MAX_WORKERS), 64))
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=EFFECTIVE_MAX_WORKERS)


def _enforce_hard_limits(distance_km: float, max_stores_per_company: int) -> None:
    """Reject requests beyond the danger-zone ceilings (see HARD_LIMITS).

    The frontend normally constrains these inputs; the unlocked "overrides"
    mode may send larger values, but never past these absolute caps.
    """
    if not (0 < float(distance_km) <= HARD_LIMITS["max_distance_km"]):
        raise HTTPException(
            400,
            f"distance_km must be between 0 and {HARD_LIMITS['max_distance_km']:g} km",
        )
    if not (1 <= int(max_stores_per_company) <= HARD_LIMITS["max_stores_per_company"]):
        raise HTTPException(
            400,
            f"max_stores_per_company must be between 1 and {HARD_LIMITS['max_stores_per_company']}",
        )


class CustomIngredient(BaseModel):
    search_term: str
    quantity: float
    unit: str = ""
    approx_quantity: Optional[float] = None
    approx_unit: Optional[str] = None


class IngredientFilterSet(BaseModel):
    """Per-search-term include/exclude keywords for product-title filtering.

    ``includes`` — EVERY keyword must fuzzy-match the returned product title
    (AND semantics; Levenshtein word ratio <= 0.35, singular/plural aware;
    multi-word keywords need every word matched). ``excludes`` — no keyword
    may match. Rows that fail get ``valid_ingredient=False`` and are skipped
    by the store-cost/winner computation (strictly — an over-eager filter can
    empty a search, which is surfaced as a store issue rather than
    auto-relaxed).
    """

    includes: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)


MAX_FILTER_KEYWORDS = 8  # per include/exclude list, per search term
MAX_FILTER_KEYWORD_LEN = 40  # characters per keyword


def _clean_filter_keywords(words: list[str], kind: str, term: str) -> list[str]:
    """Trim/dedupe one keyword list, rejecting oversized input with a 400."""
    cleaned: list[str] = []
    for word in list(words)[:MAX_FILTER_KEYWORDS]:
        text = str(word).strip()
        if not text:
            continue
        if len(text) > MAX_FILTER_KEYWORD_LEN:
            raise HTTPException(
                400,
                f"'{term}' {kind} keyword is too long (max {MAX_FILTER_KEYWORD_LEN} chars)",
            )
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def _clean_ingredient_filters(
    raw: Optional[dict[str, IngredientFilterSet]],
) -> dict[str, dict[str, list[str]]]:
    """Validate + normalise request-level ingredient filters.

    Returns ``{search_term: {"includes": [...], "excludes": [...]}}``, dropping
    empty sets entirely so a blank entry never filters anything.
    """
    cleaned: dict[str, dict[str, list[str]]] = {}
    for term, filter_set in (raw or {}).items():
        key = str(term).strip()
        if not key:
            continue
        entry = {
            "includes": _clean_filter_keywords(filter_set.includes, "include", key),
            "excludes": _clean_filter_keywords(filter_set.excludes, "exclude", key),
        }
        if entry["includes"] or entry["excludes"]:
            cleaned[key] = entry
    return cleaned


def _merge_request_filters(
    ing_lookup: dict[str, dict], ingredient_filters: dict[str, dict]
) -> tuple[int, list[str]]:
    """Attach validated filters onto resolved ingredients (case-insensitive on
    the search term). Returns ``(matched_count, unmatched_terms)`` so callers
    can report terms whose ingredient vanished between resolve and submit."""
    lowered = {key.lower(): key for key in ing_lookup}
    matched = 0
    unmatched: list[str] = []
    for term, filters in ingredient_filters.items():
        target = lowered.get(term.lower())
        if target is None:
            unmatched.append(term)
            continue
        ing_lookup[target]["includes"] = list(filters["includes"])
        ing_lookup[target]["excludes"] = list(filters["excludes"])
        matched += 1
    return matched, unmatched


def _apply_ingredient_validity(rows: list[dict], ing_lookup: dict[str, dict]) -> int:
    """Stamp ``valid_ingredient`` / ``filter_reason`` on each row in place from
    its search term's include/exclude filters. Terms without filters are always
    valid. Returns the number of rejected rows."""
    rejected = 0
    for row in rows:
        ing = ing_lookup.get(row.get("search_ingredient", ""), {})
        includes = ing.get("includes") or []
        excludes = ing.get("excludes") or []
        if includes or excludes:
            ok, reason = matches_ingredient_filters(
                row.get("returned_ingredient", ""), includes, excludes
            )
            row["valid_ingredient"] = ok
            row["filter_reason"] = "" if ok else reason
            if not ok:
                rejected += 1
        else:
            row["valid_ingredient"] = True
            row["filter_reason"] = ""
    return rejected


def _enrich_and_scale_rows(rows: list[dict], ing_lookup: dict[str, dict]) -> int:
    """Shared row post-processing for the main pipeline and the partial
    ingredient update (Phases 3b/3b+/3c): stamp each row's ingredient
    quantities, include/exclude filter validity, and parse_optimiser_columns
    quantity scaling — all in place. Returns the number of filter-rejected
    rows so callers can surface it.
    """
    for row in rows:
        ing = ing_lookup.get(row.get("search_ingredient", ""), {})
        row["ingredient_quantity"] = ing.get("quantity") if ing.get("quantity") is not None else ""
        row["ingredient_measurement"] = ing.get("unit", "")
        row["ingredient_approx_quantity"] = ing.get("approx_quantity")
        row["ingredient_approx_unit"] = ing.get("approx_unit")
        row["is_valid"] = ""

    rejected_rows = _apply_ingredient_validity(rows, ing_lookup)

    for row in rows:
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
        except Exception as e:  # noqa: BLE001 — a bad row must not sink the run
            log.warning("Scaling error for row sku=%s: %s", row.get("sku", "?"), e)
            row["used_price"] = None
            row["purchase_quantity"] = 0
            row["purchase_price"] = None
            row["scaling_ratio"] = None
            row["status"] = "error"
            row["units_match"] = False
            row["unit_approximate"] = False
            row["pack_price"] = float(row.get("price", 0)) if row.get("price") not in ("", None) else 0.0
    return rejected_rows


class CustomDish(BaseModel):
    """A hand-built recipe; quantities are expressed at ``base_portions``.

    ``source_label`` is carried through to ``OptimisationResult.dish_source``
    ("custom" = dish-builder recipe, "shopping_list" = the /test shopping-list
    search). It only drives the results-header chip — ingredient resolution
    and scaling are identical for both.
    """

    dish_name: str
    base_portions: int = 4
    ingredients: list[CustomIngredient]
    source_label: str = "custom"


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
    # Optional per-ingredient product-title filters keyed by search term:
    # {"beef mince": {"includes": ["mince"], "excludes": ["pork", ...]}}.
    # Applied uniformly to every brand's returned rows; failing rows are
    # flagged valid_ingredient=False and excluded from store costs/winner
    # selection (they stay visible in the results table, marked invalid).
    ingredient_filters: Optional[dict[str, IngredientFilterSet]] = None


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
    if custom.source_label not in CUSTOM_DISH_SOURCES:
        raise HTTPException(400, f"Unsupported dish source '{custom.source_label}'")
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


@app.get("/system-info")
def system_info() -> dict:
    """Runtime facts for the settings page: effective thread-pool size and
    the server-side danger-zone ceilings. Worker changes need a restart, so
    both the configured and effective values are reported."""
    return {
        "max_workers": EFFECTIVE_MAX_WORKERS,
        "configured_workers": int(settings.WEB_MAX_WORKERS),
        "hard_limits": HARD_LIMITS,
    }


# Whitelisted markdown manuals served to the /test Documentation viewer.
# Kept explicit (name -> title) so no arbitrary file read is possible.
TECH_DOCS = {
    "FastAPI.md": "FastAPI backend",
    "LLM_Pipeline.md": "LLM pipeline",
    "NewWorld_API.md": "New World API",
    "PaknSave_API.md": "Pak'nSave API",
    "Vue_Dashboard.md": "Vue dashboard",
    "Woolworths_API.md": "Woolworths API",
}
TECH_DOCS_DIR = PROJECT_ROOT / "docs" / "technical"


@app.get("/tech-docs")
def tech_docs_list() -> list[dict]:
    """List the available technical manuals for the docs viewer."""
    return [{"name": name, "title": title} for name, title in TECH_DOCS.items()]


@app.get("/tech-docs/{name}")
def tech_doc_file(name: str):
    """Serve one whitelisted manual as raw markdown (rendered client-side)."""
    if name not in TECH_DOCS:
        raise HTTPException(404, f"Unknown document '{name}'")
    path = TECH_DOCS_DIR / name
    if not path.exists():
        raise HTTPException(404, f"Document '{name}' is missing from the repository")
    return FileResponse(path, media_type="text/markdown; charset=utf-8")


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


@app.get("/dish_filters")
def dish_filter_presets() -> dict:
    """Ingredient-level include/exclude preset rules from data/dish_filters.json.

    Lets the dashboards pre-seed each curated dish's per-ingredient filters.
    Users may edit or delete the seeded keywords freely, but those edits live
    in their browser (localStorage) — this file stays the clean curated
    baseline. Underscored metadata keys ("_comment", "_matching") pass
    through so clients can show the matching semantics.
    """
    path = DATA_DIR / "dish_filters.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class SaveDishRequest(BaseModel):
    """Upsert payload for the dish builder's "Save as preset" button.

    Stored verbatim at its base portions — run-time scaling to the requested
    portions happens per-request in _scale_ingredients_to_portions. ``notes``
    is optional user metadata (source site, reminders) capped at 100 chars;
    it never reaches the optimiser.
    """

    dish_name: str
    base_portions: int = 4
    ingredients: list[CustomIngredient]
    notes: str = ""


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
    entry = {
        "dish_name": name,
        "portion": base_portions,
        "ingredients": ingredients,
        "source": "user",
    }
    notes = req.notes.strip()[:100]
    if notes:
        entry["notes"] = notes
    data[key] = entry
    await asyncio.to_thread(_write_dishes_file, data)
    log.info("Saved preset dish '%s' (%s)", name, "updated" if existed else "new")
    return {"ok": True, "key": key, "updated": existed, "dishes_count": len(data)}


@app.delete("/dishes/{key}")
async def delete_dish(key: str) -> dict:
    """Remove a preset dish from data/dishes.json.

    Curated dishes (no ``source`` field) and user-saved ones are both
    deletable — the frontend warns extra-hard before removing curated
    recipes. The write is the same atomic temp+replace used by save.
    """
    data = await asyncio.to_thread(_load_dishes_file)
    if key not in data:
        raise HTTPException(404, f"Unknown dish '{key}'")
    removed = data.pop(key)
    await asyncio.to_thread(_write_dishes_file, data)
    log.info("Deleted preset dish '%s'", key)
    return {"ok": True, "key": key, "was_user": removed.get("source") == "user", "dishes_count": len(data)}


class GenerateDishRequest(BaseModel):
    """Body for POST /dishes/generate — an LLM-drafted custom recipe."""

    dish_name: str
    base_portions: int = 4


@app.post("/dishes/generate")
async def generate_dish(req: GenerateDishRequest) -> dict:
    """Draft a custom dish's ingredients + product-filter rules via LLM.

    Backs the /test dashboard's "Generate custom ingredients" button.
    Ingredients come from Mistral (LLMClient "medium" alias); include/exclude
    keyword rules come from Gemini flash-lite over the generated search terms,
    shaped exactly like data/dish_filters.json entries so they can be seeded
    into the dashboard's per-scope filter editor. Runs in the thread pool —
    two sequential LLM calls, typically ~5-20 s total.

    Ingredient-generation failures are fatal (502 after retries exhausted,
    503 when an API key is missing). Filter-rule failures are soft: the
    response carries empty rules plus a warning entry instead of erroring.
    """
    name = req.dish_name.strip()
    if not name:
        raise HTTPException(400, "The dish needs a name before generating")
    base = max(1, min(int(req.base_portions) or 4, 24))
    try:
        payload = await asyncio.to_thread(generate_custom_dish, name, base)
    except GenerationConfigError as exc:
        raise HTTPException(503, str(exc))
    except GenerationError as exc:
        raise HTTPException(502, str(exc))
    log.info(
        "Generated custom dish '%s': %d ingredients, %d filter rule(s), %d warning(s)",
        name, len(payload["ingredients"]), len(payload["filters"]), len(payload["warnings"]),
    )
    return payload


class ImportRecipeRequest(BaseModel):
    """Body for POST /dishes/import_text — pasted recipe text -> LLM breakdown.

    ``recipe_text`` is capped at 1000 chars (Pydantic 422s beyond that) to keep
    prompts small and discourage pasting whole pages. ``notes`` is NOT part of
    extraction — it rides along so the Recipe Builder can hand a complete
    draft to the dashboard builder in one shot.
    """

    recipe_text: str = Field(max_length=1000)
    dish_name: str
    base_portions: int = 4
    notes: str = Field(default="", max_length=100)


@app.post("/dishes/import_text")
async def import_recipe_text(req: ImportRecipeRequest) -> dict:
    """Draft ingredients + product-filter rules from pasted recipe text.

    Backs the /test dashboard's LLM Recipe Builder page. The Mistral call uses
    an injection-guarded prompt: the pasted text is wrapped in << >> and the
    model must answer either {"status": "ok", ...} or {"status": "rejected",
    "reason": ...}. A rejection is returned as HTTP 200 with the reason so the
    UI can show a gentle notice instead of an error banner; only genuine
    pipeline failures map to 502/503 like /dishes/generate.
    """
    text = req.recipe_text.strip()
    if not text:
        raise HTTPException(400, "Paste the recipe's ingredient list first")
    name = req.dish_name.strip()
    if not name:
        raise HTTPException(400, "The dish needs a name before importing")
    base = max(1, min(int(req.base_portions) or 4, 24))
    notes = req.notes.strip()[:100]
    try:
        payload = await asyncio.to_thread(
            generate_custom_dish_from_text, text, name, base,
        )
    except GenerationConfigError as exc:
        raise HTTPException(503, str(exc))
    except GenerationError as exc:
        raise HTTPException(502, str(exc))
    if payload.get("status") == "rejected":
        log.info("Rejected pasted recipe for '%s': %s", name, payload.get("reason"))
        return {**payload, "base_portions": base}
    payload["notes"] = notes
    log.info(
        "Imported custom dish '%s' from pasted text: %d ingredients, %d filter rule(s), %d warning(s)",
        name, len(payload["ingredients"]), len(payload["filters"]), len(payload["warnings"]),
    )
    return payload


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
    _enforce_hard_limits(distance_km, max_per_company)
    cap = max(1, int(max_per_company))
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


class ReapplyFiltersRequest(BaseModel):
    """Body for the post-run filter reapply endpoint — same shape as
    DishRequest.ingredient_filters."""

    ingredient_filters: dict[str, IngredientFilterSet] = Field(default_factory=dict)


def _recompute_with_filters(job: JobState, ingredient_filters: dict[str, dict]) -> OptimisationResult:
    """Rebuild validity flags + store costs from a completed run's cached
    products using freshly supplied filters (pure computation, no API calls).

    Works on deep copies so the cached first-run state stays untouched — every
    reapply is deterministic relative to the original fetch. The recomputed
    result also replaces ``job.result`` so later GET snapshots agree.
    """
    cache = job.pipeline_cache
    assert cache is not None
    rows = copy.deepcopy(cache["rows"])
    ing_lookup = copy.deepcopy(cache["ing_lookup"])
    matched_terms, unmatched_terms = _merge_request_filters(ing_lookup, ingredient_filters)
    rejected_rows = _apply_ingredient_validity(rows, ing_lookup)
    store_costs = _build_store_costs(
        cache["search_terms"], ing_lookup, rows,
        cache["outcomes"], cache["store_geo"],
    )
    result = OptimisationResult(
        dish=cache["dish_name"],
        companies_checked=cache["companies"],
        rows=rows,
        store_costs=store_costs,
        timestamp=datetime.now().isoformat(),
        duration_seconds=0.0,
        origin=cache["origin"],
        dish_source=cache["source"],
    )
    job.result = result
    note = f"Filters reapplied on {matched_terms} term(s): {rejected_rows} product(s) excluded"
    if unmatched_terms:
        note += f" · unknown terms ignored: {', '.join(unmatched_terms)}"
    if store_costs:
        best = store_costs[0]
        note += f" · winner {best['store']} ${best['total_used_cost']:.2f}"
    job.log_event("ok", note)
    return result


@app.post("/optimise/{job_id}/reapply", response_model=OptimisationResult)
async def reapply_optimisation(job_id: str, req: ReapplyFiltersRequest):
    """Recalculate a completed run's ingredient validity, store costs and
    winner using edited include/exclude filters.

    Reuses the cached product rows from the original run — no supermarket
    queries. Body: ``{"ingredient_filters": {term: {includes, excludes}}}``;
    terms absent from the body keep no filters at all (a full replace, so the
    client sends its entire current editor state each time).
    """
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"Unknown job '{job_id}'")
    if job.status != "complete":
        raise HTTPException(409, f"Job '{job_id}' has not completed (status: {job.status})")
    if not job.pipeline_cache or not job.pipeline_cache.get("rows"):
        raise HTTPException(409, f"Job '{job_id}' has no cached products to re-filter")
    filters = _clean_ingredient_filters(req.ingredient_filters)
    result = await asyncio.to_thread(_recompute_with_filters, job, filters)
    log.info(
        "Job %s reapplied filters (%d terms) -> %d rows, %d stores",
        job_id, len(filters), len(result.rows), len(result.store_costs),
    )
    return result


@app.post("/optimise/{job_id}/filter_preview")
def filter_preview(job_id: str, req: ReapplyFiltersRequest) -> dict:
    """Dry-run ingredient filters against a completed run's cached products.

    Returns the per-term match counts and per-product validity that a reapply
    WOULD produce — without recomputing store costs or touching ``job.result``
    / ``pipeline_cache``. Powers the filter tuner's live "n/N matched" counters
    and matched/filtered pills while keywords are being edited.

    Response shape::

        {"terms": {term: {"total": int, "matched": int}},
         "products": [{company, store, sku, search_ingredient, returned_ingredient,
                       brand, quantity, measurement_unit, price, valid, reason}],
          "unmatched_terms": [...]}
    """
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"Unknown job '{job_id}'")
    if job.status != "complete":
        raise HTTPException(409, f"Job '{job_id}' has not completed (status: {job.status})")
    if not job.pipeline_cache or not job.pipeline_cache.get("rows"):
        raise HTTPException(409, f"Job '{job_id}' has no cached products to preview against")

    cache = job.pipeline_cache
    rows = copy.deepcopy(cache["rows"])
    ing_lookup = copy.deepcopy(cache["ing_lookup"])
    _matched_terms, unmatched_terms = _merge_request_filters(
        ing_lookup, _clean_ingredient_filters(req.ingredient_filters)
    )
    _apply_ingredient_validity(rows, ing_lookup)

    counts: dict[str, dict[str, int]] = {}
    products = []
    for row in rows:
        term = row.get("search_ingredient", "")
        entry = counts.setdefault(term, {"total": 0, "matched": 0})
        entry["total"] += 1
        valid = row.get("valid_ingredient") is not False
        if valid:
            entry["matched"] += 1
        products.append({
            "company": row.get("company", ""),
            "store": row.get("store", ""),
            "sku": row.get("sku", ""),
            "search_ingredient": term,
            "returned_ingredient": row.get("returned_ingredient", ""),
            "brand": row.get("brand", ""),
            "quantity": row.get("quantity", ""),
            "measurement_unit": row.get("measurement_unit", ""),
            "price": row.get("price", ""),
            "valid": valid,
            "reason": "" if valid else (row.get("filter_reason") or ""),
        })

    return {
        "terms": counts,
        "products": products,
        "unmatched_terms": unmatched_terms,
    }


class UpdateIngredientsRequest(BaseModel):
    """Body for POST /optimise/{job_id}/update_ingredients — the edited
    builder recipe plus the client's full (never regenerated) filter state."""

    custom_dish: CustomDish
    ingredient_filters: dict[str, IngredientFilterSet] = Field(default_factory=dict)


def _diff_run_ingredients(
    cache: dict, new_ing_lookup: dict[str, dict]
) -> dict:
    """Compare a submitted builder recipe against a completed run's cached
    ingredients (pure — no network, no mutation).

    Returns ``{"added", "removed", "kept", "qty_changed"}`` where the first
    three are search-term lists and ``qty_changed`` lists kept terms whose
    quantity/unit/approx fields differ (those need a pure rescale, never a
    re-query). Matching is case-insensitive on term text.
    """
    old_terms = list(cache.get("search_terms", []))
    old_by_lower = {t.lower(): t for t in old_terms}
    old_lookup = cache.get("ing_lookup", {})
    new_terms = list(new_ing_lookup)
    new_lower = {t.lower() for t in new_terms}

    added = [t for t in new_terms if t.lower() not in old_by_lower]
    removed = [t for t in old_terms if t.lower() not in new_lower]
    kept = [t for t in new_terms if t.lower() in old_by_lower]

    def _sig(ing: dict) -> tuple:
        return (
            ing.get("quantity"), ing.get("unit"),
            ing.get("approx_quantity"), ing.get("approx_unit"),
        )

    qty_changed = [
        t for t in kept if _sig(old_lookup.get(old_by_lower[t.lower()], {})) != _sig(new_ing_lookup[t])
    ]
    return {"added": added, "removed": removed, "kept": kept, "qty_changed": qty_changed}


def _stores_from_cache_rows(rows: list[dict]) -> list[tuple[str, str, str]]:
    """Fallback store snapshot for caches written before ``stores``/``regions``
    were cached: derive ordered unique (company, store_id, store_name) tuples
    from the product rows themselves."""
    seen: list[tuple[str, str, str]] = []
    found: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row.get("company", ""), row.get("store_id", ""), row.get("store", ""))
        if key not in found:
            found.add(key)
            seen.append(key)
    return seen


async def _update_job_ingredients(job: JobState, req: UpdateIngredientsRequest) -> OptimisationResult:
    """Partially refresh a completed run after builder edits.

    Only ADDED/RENAMED search terms hit the supermarket APIs — each is
    queried against the exact stores of the original run. Removed terms have
    their rows dropped; quantity/unit-only edits trigger a pure rescale.
    Filters ride along from the client untouched (rules are never
    regenerated). On success ``job.result`` AND ``job.pipeline_cache`` are
    advanced so later previews/reapplies operate on fresh data.
    """
    cache = job.pipeline_cache
    assert cache is not None
    start = time.time()

    # Validate + portion-scale the edited recipe exactly like a full run,
    # but against the ORIGINAL request's portions/companies/distance.
    base_name, base_portions, custom_ingredients = _validate_custom_dish(req.custom_dish)
    dish_dict = {
        "dish_name": base_name,
        "portion": base_portions,
        "ingredients": custom_ingredients,
    }
    dish_dict = _scale_ingredients_to_portions(dish_dict, job.req.portions)
    dish_dict.pop("_scale_factor", None)
    ingredients = dish_dict.get("ingredients", [])
    for ing in ingredients:
        if isinstance(ing, dict):
            if ing.get("unit"):
                ing["unit"] = normalise_unit(ing["unit"])
            if ing.get("approx_unit"):
                ing["approx_unit"] = normalise_unit(ing["approx_unit"])
    new_ing_lookup = {
        ing["search_term"]: ing for ing in ingredients
        if isinstance(ing, dict) and "search_term" in ing
    }
    new_search_terms = [t for t in (i.get("search_term", "") for i in ingredients) if t]
    if not new_search_terms:
        raise HTTPException(400, "The updated recipe needs at least one ingredient")

    # Attach the client's full filter state — unknown terms reported, never fatal.
    matched_filter_terms, unmatched_terms = _merge_request_filters(
        new_ing_lookup, _clean_ingredient_filters(req.ingredient_filters)
    )

    diff = _diff_run_ingredients(cache, new_ing_lookup)
    added_terms = diff["added"]
    removed_lower = {t.lower() for t in diff["removed"]}
    run_stores = cache.get("stores") or _stores_from_cache_rows(cache["rows"])
    regions = cache.get("regions", {})

    # --- Re-query ONLY the added/renamed terms across the cached stores ----
    fetched_rows: list[dict] = []
    new_outcomes: dict[tuple, dict] = {}
    if added_terms:
        job.phase = f"Re-searching {len(added_terms)} changed ingredient(s)"
        job.log_event(
            "phase",
            f"Re-searching '{' ,'.join(added_terms)}' across "
            f"{len(run_stores)} cached store(s)…",
        )
        api_instances: dict[str, object] = {}
        for company_name in sorted({s[0] for s in run_stores}):
            cfg = BRANDS[company_name]
            if "api_class" in cfg:
                job.log_event("info", "Authenticating Edge API…", company_name)
                api_instances[company_name] = await asyncio.to_thread(
                    _make_authenticated_api, cfg["api_class"]
                )
                job.log_event("ok", "Authenticated", company_name)

        metas = [
            (company, store_id, store_name, term)
            for (company, store_id, store_name) in run_stores
            for term in added_terms
        ]

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

        for fut in asyncio.as_completed([_run_one(m) for m in metas]):
            meta, rows, exc = await fut
            company, _sid, store_name, ingredient = meta
            if exc is not None:
                new_outcomes[meta] = {"status": "error", "products": 0, "detail": f"{type(exc).__name__}: {exc}"}
                log.warning("Error fetching %s@%s during update: %s", ingredient, store_name, exc)
                job.log_event("err", f"{ingredient} @ {store_name} — {new_outcomes[meta]['detail']}", company)
            elif not rows:
                new_outcomes[meta] = {"status": "no_match", "products": 0, "detail": "no products returned"}
                job.log_event("warn", f"{ingredient} @ {store_name} — no results", company)
            else:
                new_outcomes[meta] = {"status": "ok", "products": len(rows), "detail": ""}
                fetched_rows.extend(rows)
                job.log_event("ok", f"{ingredient} @ {store_name} → {len(rows)} products", company)

    # --- Splice cached + fetched rows, then re-enrich/rescale everything ---
    rows = [r for r in cache["rows"] if r.get("search_ingredient", "").lower() not in removed_lower]
    rows.extend(fetched_rows)
    rejected_rows = _enrich_and_scale_rows(rows, new_ing_lookup)

    outcomes = {
        key: value for key, value in cache["outcomes"].items()
        if key[3].lower() not in removed_lower
    }
    outcomes.update(new_outcomes)

    store_costs = _build_store_costs(
        new_search_terms, new_ing_lookup, rows, outcomes, cache["store_geo"],
    )
    result = OptimisationResult(
        dish=cache["dish_name"],
        companies_checked=cache["companies"],
        rows=rows,
        store_costs=store_costs,
        timestamp=datetime.now().isoformat(),
        duration_seconds=round(time.time() - start, 2),
        origin=cache["origin"],
        dish_source=cache["source"],
    )

    # Advance the cached state so filter_preview / later reapplies / further
    # partial updates all see the refreshed recipe.
    cache["rows"] = rows
    cache["search_terms"] = new_search_terms
    cache["ing_lookup"] = new_ing_lookup
    cache["outcomes"] = outcomes
    job.result = result

    parts = []
    if added_terms:
        parts.append(f"queried {len(added_terms)} new term(s)")
    if diff["removed"]:
        parts.append(f"dropped {len(diff['removed'])} term(s)")
    if diff["qty_changed"]:
        parts.append(f"rescaled {len(diff['qty_changed'])} term(s)")
    note = f"Ingredients updated ({', '.join(parts) or 'no changes'}) · filters active on {matched_filter_terms} term(s)"
    if unmatched_terms:
        note += f" · unknown filter terms ignored: {', '.join(unmatched_terms)}"
    if rejected_rows:
        note += f" · {rejected_rows} product(s) excluded by filters"
    if store_costs:
        best = store_costs[0]
        note += f" · winner {best['store']} ${best['total_used_cost']:.2f}"
    job.log_event("ok", note)
    log.info(
        "Job %s updated ingredients (+%d/-%d/~%d) -> %d rows, %d stores",
        job.id, len(added_terms), len(diff["removed"]), len(diff["qty_changed"]),
        len(rows), len(store_costs),
    )
    return result


@app.post("/optimise/{job_id}/update_ingredients", response_model=OptimisationResult)
async def update_job_ingredients(job_id: str, req: UpdateIngredientsRequest):
    """Re-query only the changed ingredients of a completed run ("Update
    ingredient prices" button).

    Body carries the full edited builder recipe plus the client's current
    include/exclude filter state (rules are NEVER regenerated here). Added or
    renamed search terms are re-queried against the original run's stores;
    removed terms drop out of the comparison; quantity/unit-only edits just
    recalculate costs with zero network calls.

    The client serialises updates per job (like /reapply); concurrent calls
    on one job are rejected only by the same completeness guards.
    """
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"Unknown job '{job_id}'")
    if job.status != "complete":
        raise HTTPException(409, f"Job '{job_id}' has not completed (status: {job.status})")
    if not job.pipeline_cache or not job.pipeline_cache.get("rows"):
        raise HTTPException(409, f"Job '{job_id}' has no cached products to update")
    result = await _update_job_ingredients(job, req)
    return result


def _new_job(req: DishRequest) -> JobState:
    _enforce_hard_limits(req.distance_km, req.max_stores_per_company)
    if req.companies is not None:
        invalid = [c for c in req.companies if c not in BRANDS]
        if invalid:
            raise HTTPException(400, f"Unsupported company: {invalid}")
    # Reject broken builder recipes up front so clients get an immediate 400
    # instead of discovering them mid-run.
    if req.custom_dish is not None:
        _validate_custom_dish(req.custom_dish)
    # Same for ingredient filters (oversized/invalid keyword lists).
    _clean_ingredient_filters(req.ingredient_filters)
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


def _placeholder_row(term: str, ing: dict) -> dict:
    """Blank comparison-table row for an ingredient with nothing usable.

    Carries the recipe requirement ("Recipe Needed" stays informative — e.g.
    "1 pack (~200 g)") and a ``not_found`` status; every product column stays
    blank so gaps are visually obvious. Contributes nothing to totals and
    never counts toward ingredients_matched/complete.
    """
    return {
        "search_ingredient": term,
        "returned_ingredient": "",
        "brand": "",
        "price": "",
        "ingredient_quantity": ing.get("quantity", ""),
        "ingredient_measurement": ing.get("unit", ""),
        "ingredient_approx_quantity": ing.get("approx_quantity"),
        "ingredient_approx_unit": ing.get("approx_unit"),
        "quantity": "",
        "measurement_unit": "",
        "used_price": None,
        "purchase_quantity": 0,
        "purchase_price": None,
        "status": "not_found",
    }


def _build_store_costs(
    search_terms: list[str],
    ing_lookup: dict[str, dict],
    all_rows: list[dict],
    outcomes: dict[tuple, dict],
    store_geo: dict[tuple[str, str], dict],
) -> list[dict]:
    """Build the per-store cost summary (Phase 4 of the pipeline).

    For each (store, search_ingredient), pick the cheapest valid product
    (preferring exact unit matches), then sum used_price across ingredients
    per store to get the total "used cost" for that store. Honesty guarantees:

        1. failed/no-match searches AND ingredients whose every product is
           unit-incompatible (e.g. recipe needs 6 eggs; store sells per egg)
           are attached to the store as "issues",
        2. they ALSO appear in best_per_ingredient as a placeholder row
           (status ``not_found``, product columns blank) so missing
           ingredients are visible directly in the comparison table,
        3. ingredients_total is the REQUESTED ingredient count, and stores
            that returned no rows at all still get a card ($0.00, incomplete),
        4. stores are ranked complete-basket-first, then by total cost — a
            partial basket can never win on a missing ingredient's $0,
        5. rows flagged valid_ingredient=False (ingredient include/exclude
            keyword filters) are skipped even when priced; if that empties an
            ingredient entirely the store gets a "filtered_out" issue plus
            the same blank placeholder — filters are respected strictly.

     Pure function: no job/event side effects, trivially unit-testable.
     """
    # Issue entries (amber banner): failed/no-match searches AND all-incompatible ones.
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

    # Every (company, store) that took part in the run gets a card — even a
    # store whose every search failed (all-placeholder, $0.00, incomplete).
    candidates = sorted({(company, store_name) for (company, _sid, store_name, _term) in outcomes})

    store_costs = []
    for company, store_name in candidates:
        ing_map = store_ingredients.get((company, store_name), {})
        total_used = 0.0
        matched = 0
        best_per_ingredient = []
        # Requested order, so tables read consistently across stores.
        for term in search_terms:
            rows = ing_map.get(term) or []
            filtered_n = sum(1 for r in rows if r.get("valid_ingredient") is False)
            # valid_ingredient=False rows are skipped by the optimisation even
            # when priced; absent flag (older rows) counts as valid.
            valid = [
                r for r in rows
                if r.get("used_price") is not None and r.get("valid_ingredient") is not False
            ]
            if valid:
                best = min(
                    valid,
                    key=lambda r: (r["used_price"], 0 if r.get("units_match", False) else 1),
                )
                total_used += best["used_price"]
                matched += 1
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
                # Products came back but none survived — either every one was
                # rejected by ingredient filters (strictly respected, never
                # auto-relaxed), or the remainder could not be scaled to the
                # recipe's units. Record why on the issues banner AND surface a
                # blank placeholder row; the ingredient costs the store $0
                # right now, which must be visible, not folded into a too-cheap
                # total.
                if rows:
                    if filtered_n and filtered_n == len(rows):
                        issues_by_store[(company, store_name)].append({
                            "search_ingredient": term,
                            "status": "filtered_out",
                            "detail": f"{filtered_n} product(s) rejected by ingredient filters",
                        })
                    else:
                        detail = f"{len(rows)} product(s) returned; none sold in units compatible with the recipe"
                        if filtered_n:
                            detail += f" ({filtered_n} rejected by ingredient filters)"
                        issues_by_store[(company, store_name)].append({
                            "search_ingredient": term,
                            "status": "incompatible_units",
                            "detail": detail,
                        })
                best_per_ingredient.append(_placeholder_row(term, ing_lookup.get(term) or {}))
        store_issues = issues_by_store.get((company, store_name), [])
        geo = store_geo.get((company, store_name), {})
        store_costs.append({
            "store": store_name,
            "company": company,
            "total_used_cost": round(total_used, 2),
            "ingredients_matched": matched,
            "ingredients_total": len(search_terms),
            "complete": matched == len(search_terms),
            "best_per_ingredient": best_per_ingredient,
            "issues": store_issues,
            "lat": geo.get("lat"),
            "lon": geo.get("lon"),
            "distance_km": geo.get("distance_km"),
        })

    # Complete baskets first (truthful comparison set), then cheapest.
    store_costs.sort(key=lambda x: (not x["complete"], x["total_used_cost"]))
    return store_costs


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
        source = req.custom_dish.source_label
        dish_name = base_name
        kind_label = "shopping list" if source == "shopping_list" else "custom dish"
        job.log_event(
            "phase",
            f"Building {kind_label} '{base_name}' ({len(custom_ingredients)} ingredients "
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

    # Unit hygiene: fold aliases once for every source ("eggs" -> "each",
    # "pk" -> "pack") so scaling sees count-vs-count matches and result
    # tables display canonical units. Legacy string rows pass through.
    for ing in ingredients:
        if isinstance(ing, dict):
            if ing.get("unit"):
                ing["unit"] = normalise_unit(ing["unit"])
            if ing.get("approx_unit"):
                ing["approx_unit"] = normalise_unit(ing["approx_unit"])

    # Normalize: ensure all ingredients are dicts with 'search_term'
    if ingredients and isinstance(ingredients[0], str):
        ingredients = [{"search_term": t} for t in ingredients]

    search_terms = [ing.get("search_term", "") for ing in ingredients]
    search_terms = [t for t in search_terms if t]
    ing_lookup = {ing["search_term"]: ing for ing in ingredients if isinstance(ing, dict) and "search_term" in ing}

    if not search_terms:
        raise HTTPException(status_code=400, detail=f"Could not resolve ingredients for dish '{dish_name}'")
    job.log_event("ok", f"{len(search_terms)} ingredients resolved ({source}): {', '.join(search_terms)}")

    # Attach user-supplied include/exclude product filters to their resolved
    # ingredients (single mechanism across preset / custom / shopping list).
    request_filters = _clean_ingredient_filters(req.ingredient_filters)
    if request_filters:
        matched_terms, unmatched_terms = _merge_request_filters(ing_lookup, request_filters)
        note = f"Product filters active on {matched_terms} search term(s)"
        if unmatched_terms:
            note += f" · ignored unknown terms: {', '.join(unmatched_terms)}"
        job.log_event("info", note)

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
    run_stores: list[tuple[str, str, str]] = []  # ordered (company, store_id, store_name)
    regions: dict[tuple[str, str], str] = {}  # (company, store_id) -> NI/SI
    store_geo: dict[tuple[str, str], dict] = {}  # (company, store_name) -> map pin data
    for company_name in companies:
        cfg = BRANDS[company_name]
        if company_name == "Woolworths":
            nearby = woolworths_api.get_nearby_stores(user_lat, user_lon, max_dist_km=req.distance_km)
        else:
            nearby = cfg["find_nearby"](user_lat, user_lon, radius_km=req.distance_km)
        nearby = nearby[:req.max_stores_per_company]
        if not nearby:
            job.log_event("warn", f"No stores within {req.distance_km:g} km", company_name)
            continue
        # Only brands with stores in range enter company_progress, so the
        # live progress tracker never shows a stuck idle tile for a brand
        # that has nothing to query.
        job.init_company(company_name)
        prog = job.company_progress[company_name]

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
            run_stores.append((company_name, store_id, store_name))
            regions[(company_name, store_id)] = store.get("region", "")
            # Foodstuffs CSVs use latitude/longitude; Woolworths uses lat/lon.
            store_geo[(company_name, store_name)] = {
                "lat": store.get("lat", store.get("latitude")),
                "lon": store.get("lon", store.get("longitude")),
                "distance_km": round(float(store.get("distance_km", 0.0)), 2),
            }
            for ingredient in search_terms:
                metas.append((company_name, store_id, store_name, ingredient))
        job.log_event("ok", f"{len(nearby)} store(s) within {req.distance_km:g} km", company_name)

    if not metas:
        raise HTTPException(
            400,
            f"No stores found within {req.distance_km:g} km — try increasing "
            "the distance or selecting more supermarkets.",
        )

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

    # --- Phases 3b/3b+/3c: enrich, validity-stamp and scale every row ---
    # Every row is scaled regardless (cheap, pure) so a later "reapply" /
    # partial ingredient update can recompute validity from cached rows
    # without re-scaling; invalid rows are excluded from store costs by
    # _build_store_costs, not here.
    job.phase = "Scaling quantities"
    job.log_event("phase", f"Computing scaled used-costs for {len(all_rows)} products")
    rejected_rows = _enrich_and_scale_rows(all_rows, ing_lookup)
    if rejected_rows:
        job.log_event(
            "warn",
            f"{rejected_rows} product(s) failed ingredient filters — excluded from store costs",
        )

    # --- Phase 4: Build per-store cost summary (see _build_store_costs) ---
    store_costs = _build_store_costs(search_terms, ing_lookup, all_rows, outcomes, store_geo)

    if store_costs:
        best = store_costs[0]
        job.log_event(
            "done",
            f"Winner: {best['store']} ({COMPANY_LABELS.get(best['company'], best['company'])}) "
            f"at ${best['total_used_cost']:.2f}",
        )
    duration = round(time.time() - start, 2)
    log.info("Job %s complete in %.2fs: %d products, %d stores", job.id, duration, len(all_rows), len(store_costs))

    # Keep the run's products + context so POST /optimise/{id}/reapply can
    # recalculate costs with edited filters without hitting the APIs again,
    # and POST /optimise/{id}/update_ingredients can re-query only changed
    # ingredients against this exact store set.
    job.pipeline_cache = {
        "rows": all_rows,
        "search_terms": search_terms,
        "ing_lookup": ing_lookup,
        "outcomes": outcomes,
        "store_geo": store_geo,
        "companies": companies,
        "dish_name": dish_name_resolved,
        "source": source,
        "origin": origin,
        "regions": regions,      # (company, store_id) -> NI/SI for the Edge cookie
        "stores": run_stores,    # ordered (company, store_id, store_name)
    }

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
