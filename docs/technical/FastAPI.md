# FastAPI Architecture — `src/NZMealOptimiser/web/main.py`

## Overview

A FastAPI web server that turns the CLI optimiser into an HTTP API + browser dashboard. Users send a dish name and NZ address, the server concurrently searches all 3 supermarket brands across nearby stores, and returns a two-table result: (1) all raw product rows in `full_results.csv` format, and (2) a per-store cost comparison using quantity-scaled "used cost".

Runs are **background jobs**: `POST /optimise/jobs` returns a `job_id` immediately and the pipeline streams progress (phase, per-company store/product counters, per-search event log) via `GET /optimise/{job_id}` polling. The Vue dashboard renders this as brand progress tiles with SVG rings plus a live terminal-style backend console.

**Run with:**
```
.venv\Scripts\uvicorn NZMealOptimiser.web.main:app --host 0.0.0.0 --port 8000
```
Then open `http://127.0.0.1:8000/` for the Vue prod dashboard (`static/vue/index.html`), `http://127.0.0.1:8000/test` for the Vue sandbox (`static/vue/test.html`), or `http://127.0.0.1:8000/docs` for Swagger.

No manual path bootstrap is needed — the package is installed editable (`pip install -e .`) and all imports resolve from `NZMealOptimiser.*`.

**See also:** [CLI_vs_Dashboard.md](CLI_vs_Dashboard.md) for the canonical CLI↔Dashboard↔Endpoint equivalence table (22 tasks), and [Vue_Dashboard.md](Vue_Dashboard.md) for the per-component behaviour reference.

---

## Contents

- [Overview](#overview)
- [Imports & Bootstrap](#imports--bootstrap)
- [Thread Pool Setup](#thread-pool-setup)
- [Global Constants](#global-constants)
- [Job State (`JobState`)](#job-state-jobstate)
- [Pydantic Models](#pydantic-models)
- [API Endpoints](#api-endpoints)
- [Functions](#functions)
- [Concurrency Model](#concurrency-model)
- [Concurrency Pipeline Diagram](#concurrency-pipeline-diagram)
- [Data Flow Summary](#data-flow-summary)
- [Google Cloud Run Deployment](#google-cloud-run-deployment)

---

## Imports & Bootstrap

```python
# Illustrative — the real module imports ~20 names from NZMealOptimiser.*
# plus FastAPI / Pydantic / asyncio. The block below is the conceptual core.
from NZMealOptimiser import DATA_DIR
from NZMealOptimiser.llm.llm_utils import resolve_ingredients, parse_optimiser_columns
from NZMealOptimiser.pricing import optimiser_utils
from NZMealOptimiser.pricing.optimiser_utils import build_edge_row, build_woolworths_row
from NZMealOptimiser.pricing.paknsave_api import PaknSaveEdgeAPI, find_nearby_stores as ps_find_nearby
from NZMealOptimiser.pricing.newworld_api import NewWorldEdgeAPI, find_nearby_stores as nw_find_nearby
from NZMealOptimiser.pricing import woolworths_api
from NZMealOptimiser.web.config import settings
```

All modules come from the `src/NZMealOptimiser/` package (editable install — no path bootstrap). `resolve_ingredients` resolves dish names from the curated `dishes.json` (no LLM needed for the 21 curated dishes); `parse_optimiser_columns` computes proportional "used cost" by scaling recipe quantities against supermarket pack sizes. `settings` loads `.env` from the repo root.

---

## Thread Pool Setup

```python
class _ResizableThreadPool:
    """ThreadPoolExecutor that can be atomically swapped to a new size.

    Reads (``submit`` / ``max_workers``) take a snapshot of the current
    executor so callers never see a half-built replacement. Writes are
    serialised by ``self._lock`` so concurrent swaps can never interleave.
    """

    def __init__(self, initial_workers: int, max_ceiling: int) -> None:
        self._max_ceiling = max(1, int(max_ceiling))
        self._lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(int(initial_workers), self._max_ceiling)),
        )

    @property
    def max_workers(self) -> int: ...
    @property
    def executor(self) -> concurrent.futures.ThreadPoolExecutor: ...

    def set_max_workers(self, n: int) -> int:
        """Replace the executor; old one drains with ``wait=False``.

        NOTE: this method does NOT touch the asyncio default executor.
        It runs on a threadpool worker thread (where
        ``asyncio.get_running_loop()`` raises ``RuntimeError`` and any
        attempt to rebind silently no-ops). The async swap handler
        ``thread_pool_swap`` does the rebind itself, on the loop thread.
        See ``logs.md`` #67.
        """
        effective = max(1, min(int(n), self._max_ceiling))
        with self._lock:
            new = concurrent.futures.ThreadPoolExecutor(max_workers=effective)
            old = self._executor
            self._executor = new
        old.shutdown(wait=False)
        return effective


_THREAD_POOL = _ResizableThreadPool(
    initial_workers=WORKER_POOL_MIN,
    max_ceiling=WORKER_POOL_MAX,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.get_running_loop().set_default_executor(_THREAD_POOL.executor)
    yield
```

**Why this exists:** The API libraries (`woolworths_api`, `paknsave_api`, `newworld_api`) are all synchronous — they use `requests.Session` for HTTP calls. Without `asyncio.to_thread`, these calls block the event loop and all tasks execute one-by-one.

`asyncio.to_thread(func, *args)` runs `func` on a background thread from the pool (default 20 workers) while the event loop stays free. With 20 workers, up to 20 searches run in parallel — the rest queue and start as slots free up.

**Pool size — why 20:** With 20 workers, up to 20 searches run in parallel. Wall time ≈ `ceil(total_tasks / 20) × ~5s`. Going higher (e.g. 63 workers) gives diminishing returns and uses more memory.

**Configuring the size:** The thread pool is a live-adjustable slider in the Settings page, hardcoded to `[WORKER_POOL_MIN, WORKER_POOL_MAX] = [20, 40]` in steps of `WORKER_POOL_STEP = 5`. These are module-level constants in `main.py` — there is **no `.env` override** (by design: the safeguard was removed because an unset `.env` silently clamped the slider to a single point and made it undraggable). The Pydantic body only enforces `Field(ge=1)`; the slider ceiling and step are checked in the handler, so out-of-range or misaligned values are rejected with **400** by the handler, not the Pydantic model. To change the bounds, edit the constants in `main.py` and restart.

**Live resize semantics:** `ThreadPoolExecutor` cannot be resized in place, so `POST /system/thread-pool {max_workers: N}` runs `set_max_workers` (which atomically builds a new executor and drains the old one with `wait=False`, offloaded to a worker thread so the loop is never blocked) and then `asyncio.get_running_loop().set_default_executor(new)` on the loop thread to rebind the asyncio executor. A trivial warmup future is awaited before the response goes out so the new pool's worker threads are spun up before the next `asyncio.to_thread` lands. The swap is **rejected with 409** while any job is `status == "running"` so the gate guarantees there are no in-flight futures to strand. See `decision.md` #42 for the original rationale and `logs.md` #67 for the executor-rebind bug history that motivated the worker/loop split.

---

## Global Constants

| Variable | Purpose |
|---|---|
| `DATA_DIR` | Points to `project/data/` (dishes.json, store CSVs) — resolved in `src/NZMealOptimiser/__init__.py` |
| `TMP_DIR` | Scratchpad folder (`src/NZMealOptimiser/web/tmp/`), created if missing. Currently unused. |
| `STATIC_DIR` | Folder for the frontend (`src/NZMealOptimiser/web/static/`). Mounted at `/static`. |
| `BRANDS` | Dispatch dict mapping brand names to their API classes, find_nearby functions, and metadata. |
| `_THREAD_POOL` (a `_ResizableThreadPool` wrapper) | Thread pool for offloading blocking HTTP calls, initially 20 workers, live-resizable via `POST /system/thread-pool` over the hardcoded `[20, 40]` step-5 range. |
| `HARD_LIMITS` | Absolute server-side ceilings for the frontend's danger-zone overrides: `{max_distance_km: 50.0, max_stores_per_company: 20}` — enforced by `_enforce_hard_limits()` in `_new_job()` and `/stores/nearby` (400 beyond). |
| `TECH_DOCS` / `TECH_DOCS_DIR` | Whitelisted markdown manuals (`docs/technical/*.md`) served to the Documentation viewer; explicit name→title map so no arbitrary file read is possible. |
| `COMPANY_LABELS` / `COMPANY_CODES` | Display names ("Pak'nSave") and console tag codes ("PNS"/"NW"/"WW") per brand. |
| `JOBS` | `OrderedDict` registry of active/finished `JobState` objects, keyed by job id. Max `MAX_RETAINED_JOBS` (40); oldest *finished* jobs evicted first so running jobs are never dropped. |
| `_BACKGROUND_TASKS` | Strong-ref set holding pipeline tasks so `asyncio.create_task` results aren't garbage-collected mid-run. |

### `BRANDS` dispatch dict

```python
BRANDS = {
    "PaknSave":  { "api_class": PaknSaveEdgeAPI, "find_nearby": ps_find_nearby, ... },
    "NewWorld":  { "api_class": NewWorldEdgeAPI, "find_nearby": nw_find_nearby, ... },
    "Woolworths": { ... },  # No api_class — uses woolworths_api module functions directly
}
```

Used by `_execute_pipeline()` and `_fetch_foodstuffs_sync()` to look up which API client and store finder to use per brand. `company_id` is passed to `build_*_row` to label rows in the CSV format.

---

## Job State (`JobState`)

Mutable progress object created per optimisation request (`_new_job`). Key attributes: `id` (12-char hex), `req` (the `DishRequest`), `status`, `phase`, `started`/`finished` timestamps, `error_detail`/`error_status`, task counters (`total_tasks`/`done_tasks`/`products_found`), `company_progress` (per-brand `{label, code, stores_total, stores_done, products}`), `events` (append-only console log), the final `result`, and a `pipeline_cache` dict (populated when the run completes; see below).

**`pipeline_cache` shape** (read by every post-run endpoint — `reapply`, `filter_preview`, `ai_filter_preview`, `auto_cull_preview`, `update_ingredients`):

| Key | Type | Purpose |
|---|---|---|
| `rows` | `list[dict]` | All raw product rows from the run (CSV + enriched fields) |
| `search_terms` | `list[str]` | Resolved ingredient search terms |
| `ing_lookup` | `dict[str, dict]` | Per-term recipe metadata (quantity, unit, approx, filters) |
| `outcomes` | `dict[(company, store, term), dict]` | `ok` / `no_match` / `error` per store/term |
| `store_geo` | `dict[(company, store), dict]` | `{lat, lon, distance_km}` for the per-store summary |
| `companies` | `list[str]` | Brands that were searched (frozen at run time; never re-derived) |
| `dish_name` | `str` | Final display name after builder/custom overrides |
| `source` | `str` | `dish_source` value |
| `origin` | `dict` | `{lat, lon, source}` for the original run's origin |
| `regions` | `dict[str, str]` | `store_id → "NI"\|"SI"` for Edge-API Region cookies |
| `stores` | `list[dict]` | Original store set, kept so partial updates re-query the same stores |

`pipeline_cache` is **not** rebuilt by every post-run endpoint: reapply / filter_preview / ai_filter_preview / auto_cull_preview all read from it; only `update_ingredients` mutates it (advances `rows`/`search_terms`/`ing_lookup`/`outcomes` for added/removed/renamed terms, but `companies`/`dish_name`/`source`/`origin`/`regions`/`stores` stay frozen).

**Thread-safety model:** everything mutates inside the pipeline coroutine on the event-loop thread; snapshot reads run on that same loop, and search threads never touch the object (their results are consumed by `as_completed` on the loop) — so no locking is required.

---

## Pydantic Models

### `DishRequest` (input)
| Field | Type | Default | Description |
|---|---|---|---|
| `dish` | `str` | — | Dish name (e.g. "spaghetti bolognese") |
| `address` | `str` | — | NZ address or suburb for geocoding (ignored when GPS coords are supplied) |
| `distance_km` | `float` | `5.0` | Search radius around the address (hard ceiling 50 km — 400 beyond) |
| `max_stores_per_company` | `int` | `3` | Cap on stores checked per brand (hard ceiling 20 — 400 beyond) |
| `companies` | `list[str]` | `None` | Filter to specific brands; `None` = all 3 |
| `portions` | `int` | `4` | Number of servings (used for ingredient quantity resolution) |
| `latitude` | `float \| None` | `None` | Device GPS latitude — bypasses Nominatim when set |
| `longitude` | `float \| None` | `None` | Device GPS longitude — must accompany `latitude` |
| `custom_dish` | `CustomDish \| None` | `None` | Hand-built recipe from the dish builder (see below) |
| `ingredient_filters` | `dict[str, IngredientFilterSet] \| None` | `None` | Per-search-term product filters: `{term: {includes, excludes, brand_includes, brand_excludes}}`. **Title rules** — `includes` = EVERY keyword must fuzzy-match the returned title (AND semantics; Levenshtein word ratio ≤ 0.35, singular/plural aware, multi-word needs all words); `excludes` = none may match. **Brand rules** — `brand_includes` = ANY keyword fuzzy-matches the product brand (OR semantics; same Levenshtein matcher as title), `brand_excludes` = reject-on-match. **Pass order:** brand filters run first and take precedence over title filters — a brand rejection wins even when the title would also fail, and `filter_reason` records the winning failure. Failing rows get `valid_ingredient=False` + `filter_reason` and are skipped by store costs/winner (strictly — an empty result surfaces as a `filtered_out` store issue + placeholder row). Keywords capped 15/list (`MAX_FILTER_KEYWORDS = 15`), 40 chars (`MAX_FILTER_KEYWORD_LEN = 40`); beyond that → 400. Unknown terms are ignored with a console note. Works uniformly across preset/custom/shopping-list. |
| `exclude_non_food` | `bool` | `True` | When `False`, skips non-food category filtering across all three brands. `_new_job` always overwrites this from `load_llm_settings()` (default `True`) so the persisted Settings toggle wins over the request body on every run. |

GPS coordinates are validated against a rough NZ bounding box (`NZ_LAT_RANGE = (-47.6, -34.2)`, `NZ_LON_RANGE = (166.2, 178.9)`): out-of-bounds or half-specified coords fail with 400 before any search work starts.

### `IngredientFilterSet`

```python
class IngredientFilterSet(BaseModel):
    includes: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    brand_includes: list[str] = Field(default_factory=list)
    brand_excludes: list[str] = Field(default_factory=list)
```

Matchers live in `optimiser_utils.py`:

- `matches_ingredient_filters` / `contains_word` / `word_matches` / `levenshtein` — ported verbatim from `exploration/llm/validate_dish_filters.py`, so curated rules in `data/dish_filters.json` behave identically at runtime.
- `matches_brand_filters(brand, brand_includes, brand_excludes)` — same `contains_word` (Levenshtein word ratio ≤ 0.35, case-insensitive, partial-word) for parity with the title matcher, but **OR-semantics** for includes (any match passes) and reject-on-match for excludes. Brand fields are **user-set only** — never auto-populated by the LLM (`test_parse_filters_never_emits_brand_fields` regression guard) or `data/dish_filters.json`.

**Filter pass order:** brand filters run first and take precedence over title filters. A brand rejection wins even when the title would also fail. The `filter_reason` string preserves the winning failure (one of `"INCLUDE [...] missing"`, `"EXCLUDE hit: [...]"`, `"BRAND include missed (need one of [...])"`, `"BRAND exclude hit: [...]"`). See `_apply_ingredient_validity` in `main.py` and its docstring.

### `CustomDish` / `CustomIngredient` (dish builder input)

```python
class CustomIngredient(BaseModel):
    search_term: str
    quantity: float
    unit: str = ""
    approx_quantity: Optional[float] = None
    approx_unit: Optional[str] = None

class CustomDish(BaseModel):
    dish_name: str
    base_portions: int = 4
    ingredients: list[CustomIngredient]
    source_label: str = "custom"  # "custom" | "shopping_list" (validated)
```

When `custom_dish` is set it **replaces** the `dish`-name resolution path entirely:

1. `_validate_custom_dish()` — sync validation: non-empty name/ingredients, positive finite quantities, non-empty units, and `source_label ∈ CUSTOM_DISH_SOURCES` (`{"custom", "shopping_list"}`; anything else is a 400). Units are normalised through `normalise_unit()` (alias folding, e.g. `eggs` → `each`) at build time.
2. `_scale_ingredients_to_portions(dish_dict, req.portions)` — uniform scaling of every numeric quantity from `base_portions` to the requested `portions`. Applied to ALL sources (curated, LLM, custom); a no-op at default portions. Scaling happens per-request — presets are stored verbatim at their base portions.

**Shopping-list searches** (/test) reuse this exact path with zero backend-specific logic: the frontend submits `base_portions=1`, `portions=1`, `source_label="shopping_list"` and a fixed dish name `"Shopping list"` — so quantities are priced as-is with no portion scaling, and `dish_source` labels the results header chip.

### Master Pydantic-models index

Every Pydantic model in `main.py`, the endpoint it backs, and its fields. This is the single source of truth for the request/response contract — see the per-endpoint rows in [API Endpoints](#api-endpoints) for the HTTP-level semantics (status codes, headers, side effects).

| Model | Used by | Fields |
|---|---|---|
| `DishRequest` | `POST /optimise`, `POST /optimise/jobs` | see the [table above](#dishrequest-input) |
| `CustomDish` | `DishRequest.custom_dish`, `UpdateIngredientsRequest.custom_dish` | `dish_name: str`; `base_portions: int = 4`; `ingredients: list[CustomIngredient]`; `source_label: str = "custom"` (must be in `CUSTOM_DISH_SOURCES = {"custom", "shopping_list"}`; else 400) |
| `CustomIngredient` | inside `CustomDish.ingredients` | `search_term: str`; `quantity: float`; `unit: str = ""`; `approx_quantity: Optional[float] = None`; `approx_unit: Optional[str] = None` |
| `IngredientFilterSet` | inside `DishRequest.ingredient_filters` values | `includes: list[str] = []`; `excludes: list[str] = []`; `brand_includes: list[str] = []`; `brand_excludes: list[str] = []` (see the matcher section above) |
| `OptimisationResult` | `POST /optimise` (response), `JobState.snapshot().result` | see the [table below](#optimisationresult-output) |
| `JobCreated` | `POST /optimise/jobs` (response) | `job_id: str` (12-char hex) |
| `ReapplyFiltersRequest` | `POST /optimise/{id}/reapply` | `ingredient_filters: dict[str, IngredientFilterSet]` — full replace (any term not present is dropped) |
| `AiFilterRequest` | `POST /optimise/{id}/ai_filter_preview` | `instruction: str` (1..500 chars; empty/overlong → 400) |
| `AutoCullRequest` | `POST /optimise/{id}/auto_cull_preview` | `current_filters: dict[str, IngredientFilterSet] = {}` (defaults to `{}` when omitted) |
| `UpdateIngredientsRequest` | `POST /optimise/{id}/update_ingredients` | `custom_dish: CustomDish`; `ingredient_filters: Optional[dict[str, IngredientFilterSet]] = None` |
| `SaveDishRequest` | `POST /dishes/save` | `dish_name: str`; `base_portions: int = 4`; `ingredients: list[CustomIngredient]`; `notes: str = ""` (capped 100 chars) |
| `GenerateDishRequest` | `POST /dishes/generate` | `dish_name: str`; `base_portions: int = 4` |
| `ImportRecipeRequest` | `POST /dishes/import_text` | `recipe_text: str` (`Field(max_length=1000)`); `dish_name: str`; `base_portions: int = 4`; `notes: str = ""` (`Field(max_length=100)`) |
| `_ThreadPoolRequest` | `POST /system/thread-pool` | `max_workers: int = Field(ge=1)` (range + step checked in the handler → 400 out of `[20, 40]` or misaligned) |
| `_LLMSettingsRequest` | `PUT /llm/settings` | `ingredient_model: dict` (`{provider, model_id}`); `filter_model: dict`; `exclude_non_food: bool = True` (`LLMConfigError` → 400) |

### `OptimisationResult` (output)
| Field | Type | Description |
|---|---|---|
| `dish` | `str` | Resolved display name of the dish |
| `dish_source` | `str` | `"curated"`, `"custom"`, `"shopping_list"`, or `"llm"`/`"fallback"` — drives the results-header chip |
| `companies_checked` | `list[str]` | Which brands were searched |
| `rows` | `list[dict]` | All product result rows — 18 CSV columns + 9 enriched fields (LLM/scaling; not separate CSV columns) |
| `store_costs` | `list[dict]` | Per-store cost summary sorted complete-basket-first, then by total used cost |
| `timestamp` | `str` | ISO timestamp of when the result was generated |
| `duration_seconds` | `float` | Wall-clock duration of the pipeline run |
| `origin` | `dict \| None` | Search origin for the map: `{lat, lon, source}` where `source` is `"gps"` or `"geocoded"`; present even when zero stores matched |

### Row format (`rows[]`)
Each row dict matches `full_results.csv` columns:

| Column | Source |
|---|---|
| `company` | Brand label ("PaknSave", "NewWorld", "Woolworths") |
| `store` | Store name |
| `store_id` | Store UUID / extra1 |
| `search_ingredient` | Ingredient search term from dish |
| `returned_ingredient` | Product name from API |
| `price` | Total pack price in dollars |
| `quantity` | Pack quantity |
| `measurement_unit` | Pack unit (g, kg, ml, ea, etc.) |
| `per_unit_quantity` | Comparative price quantity |
| `per_unit_price` | Comparative price per unit |
| `is_sale` | Promotion flag |
| `sku` | Product SKU / productId |
| `department` | Department from API |
| `sub_department` | Sub-department / category1 |
| `datetime_created` | Timestamp |
| `date_created` | Date |
| `pk_hash` | SHA-256 of `store_id|sku|date_created` (16-char prefix) |
| `is_valid` | Empty (for LLM validation to fill in later) |
| `ingredient_quantity` | Recipe quantity needed (enriched from dishes.json) |
| `ingredient_measurement` | Recipe unit (enriched) |
| `ingredient_approx_quantity` | Approximate weight/volume for non-standard units (enriched) |
| `ingredient_approx_unit` | Approx unit ("g" or "ml") (enriched) |
| `used_price` | Proportional cost for the recipe amount (computed by `parse_optimiser_columns`) |
| `purchase_quantity` | Number of packs to buy (ceil) |
| `purchase_price` | Total cost for purchased packs |
| `scaling_ratio` | Recipe qty / pack qty (unit-normalized) |
| `status` | "ok", "approximate", or "incompatible_units" |
| `units_match` | True if recipe and pack units are in the same base category |
| `unit_approximate` | True if 1ml≈1g cross-category approximation was applied |
| `valid_ingredient` | `false` when the ingredient's include/exclude keyword filters reject this product title (absent/`true` = flows through the optimisation normally) |
| `filter_reason` | Why the row was rejected (`"INCLUDE [...] missing"` / `"EXCLUDE hit: [...]"` / `"BRAND include missed (need one of [...])"` / `"BRAND exclude hit: [...]"`); empty for valid rows |

### Store cost format (`store_costs[]`)
| Field | Description |
|---|---|
| `store` | Store name |
| `company` | Brand label |
| `total_used_cost` | Sum of cheapest valid `used_price` across all ingredients. Ingredients with no valid price contribute $0 — which is why `complete`, `issues`, and the ranking rule below exist |
| `ingredients_matched` | Number of ingredients with valid scaled prices |
| `ingredients_total` | Number of ingredients REQUESTED for the dish (not just those that returned rows) |
| `complete` | `true` when every requested ingredient has a valid scaled price at this store. Only complete baskets are directly comparable |
| `best_per_ingredient` | Detail list — one entry per REQUESTED ingredient per store: the cheapest product with a valid `used_price`, or a **placeholder row** when nothing usable exists. Placeholder rows fill only `search_ingredient` (+ "Recipe Needed" ≈ fallbacks), leave all product columns blank, and carry `status: "not_found"`; they add nothing to totals or match counts |
| `issues` | Unavailable ingredients for this store: `{search_ingredient, status: "error"\|"no_match"\|"incompatible_units"\|"filtered_out", detail}`. Kept alongside placeholder rows so the *reason* stays visible (`filtered_out` = every returned product was rejected by ingredient filters — respected strictly, never auto-relaxed) |
| `lat` / `lon` | Store coordinates (from the brand store CSVs) — consumed by the dashboard map pins |
| `distance_km` | Haversine distance from the resolved origin, rounded to 2 dp |

**Ranking:** stores are sorted **complete-basket-first, then by total_used_cost** — a partial basket can never outrank a complete one on a missing ingredient's $0. If no store is complete, all are partial and sort by cost among themselves (a fully-failed $0.00 store can sit above a 1-of-3 match). Stores where every search failed still get a card ($0.00, incomplete). Phase 4 is implemented in the pure helper `_build_store_costs(search_terms, ing_lookup, all_rows, outcomes, store_geo)` with `_placeholder_row(term, ing)`; candidates derive from the `outcomes` dict, so dead stores are included even with zero rows.

---

## API Endpoints

| Route | Method | Description |
|---|---|---|
| `/` | GET | Vue prod dashboard (`static/vue/index.html`) |
| `/test`, `/test/` | GET | App-shell workspace (`static/vue/test.html`) — left sidebar switching the optimiser dashboard (preset/custom/shopping-list recipes, CSV export), My Dishes, LLM Recipe Builder (paste-recipe flow), Documentation viewer and Settings |
| `/health` | GET | Health check → `{"status": "ok", "supabase_enabled": bool}` |
| `/system-info` | GET | Runtime facts for Settings → `{max_workers, slider_min, slider_max, slider_step, running_jobs, hard_limits, llm_providers}`. The three `slider_*` keys are hardcoded constants (20/40/5) so the Settings page renders a meaningful range. `running_jobs` lets the UI disable the Apply button when a job is in flight. |
| `/system/thread-pool` | POST | Atomically swap the search thread pool to `{"max_workers": N}`. Refused with **400** if N is outside `[slider_min, slider_max]` or doesn't align to `slider_step`. Refused with **409** if any job is `status == "running"` (in-flight executor swap can strand futures). Otherwise builds a new `ThreadPoolExecutor`, calls `old.shutdown(wait=False)`, rebinds the asyncio default executor, returns `{max_workers, running_jobs, changed}`. |
| `/system/running-jobs` | GET | Lightweight counter the Settings page polls every 2 s while the slider is open → `{count: N}` (only `status == "running"` jobs counted). |
| `/dishes` | GET | Dishes from `data/dishes.json` — curated presets plus saved builder dishes (`portion` key = base portions; `"source": "user"` marks builder-saved entries, absent = curated) |
| `/dishes/save` | POST | Upsert a builder dish as a preset in `data/dishes.json` (`SaveDishRequest{dish_name, base_portions, ingredients, notes}` — `notes` is optional user metadata capped at 100 chars and never reaches the optimiser). Validates via `_validate_custom_dish`, tags `"source": "user"`, writes atomically (tmp file + `os.replace`). Returns `{ok, key, updated, dishes_count}`. |
| `/dishes/generate` | POST | LLM-draft a custom dish (`GenerateDishRequest{dish_name, base_portions}`) — backs the dashboard's "Generate custom ingredients" button. Two sequential LLM calls in the thread pool via `NZMealOptimiser.llm.generation.generate_custom_dish`: Mistral ("medium") produces validated ingredient rows, Gemini flash-lite produces include/exclude keyword rules shaped like `data/dish_filters.json` entries. Returns `{dish_name, base_portions, source: "llm", ingredients, filters, warnings}` (~5-20 s). Ingredient failures are fatal: 400 blank name · 503 missing API key (`GenerationConfigError`) · 502 generation failed after retries. Filter-rule failures are soft — empty `filters` plus an entry in `warnings` |
| `/dishes/import_text` | POST | Draft ingredients + filter rules from pasted recipe text (`ImportRecipeRequest{recipe_text, dish_name, base_portions, notes}` — `recipe_text` capped at 1000 chars). Mistral call uses an injection-guarded `<<recipe_text>>` prompt; the model must answer `{"status": "ok", ...}` or `{"status": "rejected", "reason": ...}`. A rejection is returned as HTTP 200 with the reason (`{"status": "rejected", "reason": ..., "base_portions": N}`) so the UI can show a gentle notice instead of an error banner; only genuine pipeline failures map to 502/503 like `/dishes/generate`. On success returns the full LLM payload `{dish_name, base_portions, source, ingredients, filters, warnings, notes}` — ready for either `POST /dishes/save` (Save as preset) or the dashboard's `open-draft` handoff into the dish builder. |
| `/dishes/{key}` | DELETE | Remove a preset dish from `data/dishes.json` → `{ok, key, was_user, dishes_count}`; 404 on unknown keys. `was_user` mirrors the removed entry's `source` field (curated and user dishes are both deletable; the frontend warns extra-hard before removing curated recipes). |
| `/dish_filters` | GET | Curated include/exclude keyword presets from `data/dish_filters.json` (`{dish: {search_term: {includes, excludes}}}`, underscored metadata keys included); `{}` when the file is missing. Feeds the dashboard's product-filter seeding — user edits stay browser-side |
| `/llm/models` | GET | Cached model catalog from Mistral + Google providers (file-cached in `data/llm_models_cache.json`) + active selection from `data/llm_settings.json`. Seeds cache on first call. |
| `/llm/models/refresh` | POST | Re-fetches both providers, overwrites the catalog cache, returns the new catalog + active selection. Provider failures are isolated per provider (`{available, models, error}`), so a Mistral outage doesn't block the Google dropdown (and vice versa). Settings page "Refresh model list" button. |
| `/llm/settings` | GET | Returns the active LLM settings: `{ingredient_model: {provider, model_id}, filter_model: {provider, model_id}, exclude_non_food: bool}`. `exclude_non_food` rides along because `_new_job` overwrites it on every `DishRequest` from this same settings file. |
| `/llm/settings` | PUT | Persist LLM model selection (`_LLMSettingsRequest{ingredient_model: {provider, model_id}, filter_model: {provider, model_id}, exclude_non_food: bool}`). Validation: `provider` ∈ `{mistral, google}`, non-empty `model_id`; the `model_id` must exist in the cached catalog for that provider (so a typo can't silently break every future generation) — if the cache is empty for a provider (key missing, first deploy before a refresh), the write is still allowed. Writes `data/llm_settings.json` atomically (temp+replace). No server restart required: settings are read per request. `LLMConfigError` → **400**. |
| `/optimise/{job_id}/reapply` | POST | Post-run filter recalculation for a **completed** job: body `{"ingredient_filters": {term: {includes, excludes}}}` (full replace). Rebuilds validity flags + store costs + winner from the run's cached product rows via `_recompute_with_filters` (deep-copied — first-run cache stays untouched and deterministic), replaces `job.result`, logs a console event, returns the fresh `OptimisationResult`. No supermarket calls. 404 unknown job · 409 not-complete or no cached rows |
| `/optimise/{job_id}/filter_preview` | POST | Dry-run of pending filters against a **completed** job's cached rows — same body as reapply. Returns `{terms: {term: {total, matched}}, products: [{company, store, sku, search_ingredient, returned_ingredient, brand, quantity, measurement_unit, price, valid, reason}], unmatched_terms}` without recomputing store costs or touching `job.result`/cache. Powers the filter tuner's live "n/N matched" counters and matched/filtered pills (debounced client-side). 404/409 semantics identical to reapply |
| `/optimise/{job_id}/ai_filter_preview` | POST | Compile one universal free-text sentence into suggested keyword filters: body `{"instruction": "..."}` (1..500 chars). Builds a deduped `{Ingredient, Terms, Brands}` summary per search term from the cached rows (no word cap, fast Python `set()` — rows themselves are never sent to the LLM), then calls the configured filter model via `ai_filter_compiler.compile_ai_instruction` (injection-guarded `<<instruction>>` markers, single-word truncation + vocab-grounded warnings). Returns `{instruction, compiled_filters: {term: {includes, excludes, brand_*}}, warnings, summary, preview: {terms: {total, matched}, products: [...]}}` — a dry-run so the tuner can show "this would hide N products per ingredient" + chip diff before the user clicks Apply (apply is the existing `/reapply` with the merged filters). No mutation of `job.result`/`pipeline_cache`. 400 empty/overlong · 404 unknown job · 409 not-complete/no rows · 502 LLM JSON/validation failure · 503 missing API key |
| `/optimise/{job_id}/auto_cull_preview` | POST | Dish-wide auto-cull: body `{"current_filters": {term: {includes, excludes, brand_*}}}` (optional, defaults `{}`). Uses the run's dish name + deduped `{Ingredient, Terms, Brands}` summary (+ current filters as context) to ask the filter model via `ai_filter_compiler.compile_auto_cull_filters` for up to **15 `excludes` + 15 `brand_excludes` per ingredient**, most irrelevant first, grounded strictly to the vocab (unknown words dropped with a warning, truncated multi-word keywords reported). Returns `{dish, compiled_filters: {term: {excludes, brand_excludes}}, warnings, summary, preview: {terms: {total, matched}, products: [...]}}` where `preview` is the **additive** dry-run (`current ∪ suggestions`, capped 15/list, case-insensitive dedup) so both Summary and Filter tuner can show "N new keywords · matched/total" before Apply. No mutation of `job.result`/`pipeline_cache`. 404 unknown job · 409 not-complete/no rows · 502 LLM failure · 503 missing API key |
| `/optimise/{job_id}/update_ingredients` | POST | Partial refresh of a **completed** run after builder edits ("Update ingredient prices" button): body `{custom_dish: CustomDish, ingredient_filters}`. Server diffs the submitted recipe against the cached run (`_diff_run_ingredients`) — added/renamed terms are re-queried against the original run's exact store set (`pipeline_cache.stores`/`regions`; Edge APIs re-authenticated per company), removed terms' rows/outcomes are dropped. Quantity / unit / `approx_quantity` / `approx_unit` only edits trigger a pure rescale with zero network calls. Filters ride along untouched (never regenerated). Spliced rows go through `_enrich_and_scale_rows`, store costs/winner are rebuilt, and BOTH `job.result` and `job.pipeline_cache` advance (rows, search_terms, ing_lookup, outcomes) — but the original `companies`/`origin`/`regions`/`stores` are kept so further updates can re-query against the same store set. 400 blank recipe · 404 unknown job · 409 not-complete or no cached rows |
| `/tech-docs` | GET | List the whitelisted manuals → `[{name, title}]` |
| `/tech-docs/{name}` | GET | Serve one manual as raw markdown (`text/markdown`) for client-side rendering; whitelisted names only |
| `/geocode` | GET | `?address=...` → `{lat, lon, cached}` — standalone Nominatim lookup for the dashboard's resolve step (LRU-cached, NZ-bbox validated). Reserved for explicit "Resolve setup" submissions — **never** called per keystroke (Nominatim TOS forbids autocomplete). |
| `/geocode/autocomplete` | GET | `?q=&country_code=NZ&limit=8` → `{suggestions: [{display, lat, lon, type, postcode}], cached, source: "photon"}` — Photon-backed search-as-you-type for the dashboard's address dropdown. LRU-cached (200 entries, key = `country\|limit\|q.lower()`); server clamps `limit` to `_AUTOCOMPLETE_MAX_LIMIT = 12` (default `_AUTOCOMPLETE_DEFAULT_LIMIT = 8`); 400 on `len(q) < 2`; empty list (not 404) when Photon has no match or upstream fails — 5xx/timeout returns `{suggestions: [], cached: false}` so the dropdown renders "No matches yet — keep typing." rather than a 5xx. See decision log #68 for why Photon over Nominatim here. |
| `/geocode/reverse` | GET | `?lat&lon&provider=auto\|photon\|nominatim&limit=1` → `{label, lat, lon, cached, source, candidates}` — reverse-geocode a dropped pin to a street label. Default `provider=auto` → Photon (fast, no rate-limit sleep, cached per `(lat4,lon4,limit)`); `provider=nominatim` falls back to the authoritative OSM endpoint with the standard 1.1s sleep and `(lat5,lon5)` cache key. 400 on out-of-NZ coords; 502 on provider failure. Powers the dashboard's "click on map" location picker (decision #68). |
| `/stores/nearby` | GET | `?lat&lon&distance_km&companies=PaknSave,NewWorld,Woolworths&max_per_company` → `{origin: {lat, lon}, stores[]}` — preview of which stores a run would query. Pak'nSave + New World use local CSV + haversine (instant, no API calls); Woolworths calls `woolworths_api.get_nearby_stores` so its preview list comes from the live API. Enforces `HARD_LIMITS` (400 beyond, with a lower-bound `0 < distance_km`). |
| `/optimise` | POST | Legacy synchronous endpoint (classic dashboard) — accepts `DishRequest`, blocks until done, returns `OptimisationResult` |
| `/optimise/jobs` | POST | Queue an optimisation — accepts `DishRequest`, returns `{"job_id"}` immediately. Enforces `HARD_LIMITS` via `_new_job`. |
| `/optimise/{job_id}` | GET | Job snapshot: status, phase, elapsed, per-company progress, incremental events (`?events_since=N`), final `result` |
| `/docs` | GET | Swagger UI (FastAPI default) |
| `/static` | Mount | Serves `STATIC_DIR` |

### Geocoding providers (Photon + Nominatim, decision #68)

Three endpoints share the user-address → coordinates pipeline. They never overlap on the request path — the dashboard's two-step flow calls `/geocode` once per "Resolve setup" submit, `/geocode/autocomplete` once per 300 ms keystroke burst, and `/geocode/reverse` once per map-click or pin drag. All three run the upstream HTTP on a worker thread via `asyncio.to_thread` so the event loop stays responsive.

| Endpoint | Provider | Cache | When called | Why this provider |
|---|---|---|---|---|
| `/geocode` | Nominatim forward | `_GEOCODE_CACHE` (200 entries, key = lowercased address) | "Resolve setup" submit button, or `_resolve_origin` server-side when the request omits `latitude`/`longitude` | Authoritative forward geocode, slow (1.1s sleep) but rare |
| `/geocode/autocomplete` | Photon `photon.komoot.io/api/` | `_AUTOCOMPLETE_CACHE` (200, key = `country\|limit\|q.lower()`) | Debounced 300 ms after the address input changes (dashboard only) | Photon is the only free, no-API-key, **autocomplete-friendly** OSM geocoder; Nominatim TOS forbids browser autocomplete |
| `/geocode/reverse` | Photon default, Nominatim opt-in (`provider=nominatim`) | `_PHOTON_REVERSE_CACHE` (200, key = `limit\|round(lat,4),round(lon,4)`) or `_REVERSE_CACHE` (200, key = `round(lat,5),round(lon,5)`) | Map click + drag end (debounced label lookup) | Photon is fast (no sleep) and dense enough for urban NZ; Nominatim kept as a precise fallback for rural picks |

**Why Photon over Nominatim for autocomplete/reverse**: Nominatim's [usage policy](https://operations.osmfoundation.org/policies/nominatim/) explicitly bans browser autocomplete and rate-limits to 1 req/sec. The OSM community has multiple Photon deployments for exactly this use case (Komoot runs the public demo) — same OSM data, no API key, no credit card, and the demo's "fair use" is far looser than Nominatim's 1 req/sec. For the dashboard's interactive address field, that translates to ~0.3s perceived latency instead of a 1.1s minimum per keystroke.

**Cache design**: three independent `OrderedDict` LRUs (200 entries each) keyed on the request's distinct dimensions. `move_to_end` on hit keeps hot entries alive; `popitem(last=False)` evicts the oldest when full. Cache state is **per-process** — Cloud Run cold starts / new workers begin empty, and the LRU is not shared across instances. For Cloud Run this is fine: the dashboard is single-user-per-session, so the working set (last few addresses the user typed) is well under 200.

**Out-of-NZ guard**: every endpoint validates against `NZ_LAT_RANGE = (-47.6, -34.2)` and `NZ_LON_RANGE = (166.2, 178.9)` before consulting the cache or the upstream. A laptop in Sydney can't silently resolve an NZ address to a Sydney coordinate and have the request proceed. Forward-geocode also re-validates Nominatim's return (its `lat`/`lon` from a free-form NZ string can occasionally drift outside the box).

**Failure modes**:

| Failure | Response | UX impact |
|---|---|---|
| Photon upstream 5xx / timeout | `/geocode/autocomplete` returns `{suggestions: [], cached: false}` | Dropdown shows "No matches yet — keep typing." (200 OK, not 5xx) |
| Photon reverse, no features | `/geocode/reverse` returns **502** with "Photon could not reverse these coordinates — drop the pin closer to a road or address." | Map-pick logs a console warning; the user keeps their picked coords with a fallback label of "Pinned at lat, lon" |
| Nominatim reverse failure | `/geocode/reverse` returns **502** with "Nominatim could not reverse these coordinates." | Same UX as Photon failure |
| `len(q) < 2` on autocomplete | **400** with "Query must be at least 2 characters" | Debounce keeps the field from triggering on a single keystroke; the 400 is defensive |
| Coords outside NZ on reverse | **400** with "Coordinates are outside New Zealand — this service only covers NZ stores." | Map-pick logs an error banner and discards the click |

### Danger-zone hard ceilings

The frontend's overrides mode can unlock larger searches, but `_enforce_hard_limits()` caps every entry point at **50 km radius** and **20 stores/company** with a 400 beyond. The frontend additionally requires an explicit accept-risk confirmation before unlocking its inputs past the standard ranges (8 km / 5 stores) — see Vue_Dashboard.md → Behaviour notes.

### `POST /optimise/jobs` — Job-Based Endpoint

Accepts the same `DishRequest` body. Validates the company list synchronously (400 on unknown brands), registers a `JobState` in the `JOBS` registry (`OrderedDict`, max 40 retained; finished jobs evicted first), and spawns the pipeline via `asyncio.create_task` (strong-ref'd through `_BACKGROUND_TASKS`). Returns `{"job_id": "..."}` at once.

**curl example:**
```bash
curl -X POST "http://127.0.0.1:8000/optimise/jobs" \
  -H "Content-Type: application/json" \
  -d '{"dish": "spaghetti bolognese", "address": "Auckland CBD", "distance_km": 5, "portions": 4, "max_stores_per_company": 3}'
```

### `GET /optimise/{job_id}?events_since=-1` — Progress Snapshot

Returns a snapshot dict from `JobState.snapshot()`:

| Field | Description |
|---|---|
| `job_id` | The 12-char hex id (also the dict key in `JOBS`) |
| `dish` | Echo of the `DishRequest.dish` (the typed name — even when `custom_dish` overrides ingredient resolution) |
| `address` | Echo of the `DishRequest.address` (the geocoded address, regardless of whether the actual origin was GPS/picked) |
| `status` | `queued` → `running` → `complete` \| `error` |
| `phase` | Human-readable pipeline stage ("Geocoding address", "Searching 63 store × ingredient combos", …); terminal jobs end on "Completed" or "Failed" |
| `elapsed_seconds` | Server-computed seconds since start (rounded to 1 dp) |
| `total_tasks` / `done_tasks` | Store × ingredient search counters |
| `products_found` | Total product rows collected so far |
| `companies[]` | Per-brand: `{id, label, code, stores_total, stores_done, products}` (the same shape as `JobState.init_company`) |
| `events[]` / `next_cursor` | Console events with index > `events_since`; pass `next_cursor` back for incremental polling |
| `error_detail` | Set when `status=error` (HTTPException detail or `TypeName: message` for unexpected exceptions) |
| `result` | Full `OptimisationResult` once `status=complete` (otherwise `null`) |

Each event is `{i, t, kind, co, text}`: `t` = seconds since start, `co` = brand code (`PNS`/`NW`/`WW`) or null, `kind` ∈ `phase` \| `info` \| `ok` \| `warn` \| `err` \| `done`. Every search completion emits one event ("beef mince @ PAK'nSAVE Botany → 10 products"), as do auth steps, store discovery, scaling, and the winner announcement.

An HTTP middleware also logs every request's method/path/status/duration to the server log.

---

## Functions

### `_new_job(req) -> JobState` / `_run_job(job)`

`_new_job` validates companies and registers a fresh `JobState`. `_run_job` wraps the pipeline: sets `status`/`started`, catches any `HTTPException`/exception into `error_detail` + `error_status`, stamps `finished`, and emits a final console event. Both `/optimise` (sync) and `/optimise/jobs` funnel through it.

### `_execute_pipeline(job) -> OptimisationResult`

The core orchestrator. Runs in 4 phases, writing progress into `job` as it goes (`job.phase`, `job.log_event(...)`, per-company counters):

**Phase 1 — Resolve, Validate & Geocode (sequential)**
1. Resolves ingredients. If `custom_dish` is set: `_validate_custom_dish` (sync 400 on bad input, incl. unknown `source_label`) + `_scale_ingredients_to_portions` produce the recipe; `source_label` flows through to `dish_source` ("custom" or "shopping_list"). Otherwise `resolve_ingredients(dish, portions)` looks up `dishes.json` for curated lists, falls back to LLM generation when keyed, else uses the dish name as a single term. `dish_source` records which path ran.
2. **Unit hygiene pass**: every ingredient's `unit`/`approx_unit` is folded through `normalise_unit()` for all sources (e.g. `eggs` → `each`) so downstream scaling sees canonical units.
3. Calls `_resolve_origin(job)` to locate the search origin. If the request carries `latitude`/`longitude` (device GPS), those are validated against the NZ bounding box and used directly — **no Nominatim call**. Otherwise `optimiser_utils.geocode(address)` (Nominatim, rate-limited to 1 req/sec) runs once, before any concurrent work. The resolved `{lat, lon, source}` is carried through as the result's `origin`.

**Phase 2 — Build & Launch Tasks (concurrent)**
3. Authenticates ONE Edge API client per Foodstuffs company up front (`_make_authenticated_api`, offloaded via `asyncio.to_thread`) and shares it across all of that brand's searches — post-auth methods use plain `requests.post` with the cached JWT, so concurrent use is safe.
4. For each company: finds nearby stores (capped by `max_stores_per_company`), guards duplicate store names within a brand (400 on same-name/different-ID), initialises the per-company progress entry, and appends `(company, store_id, store_name, ingredient)` tuples to `metas`.
5. Wraps each meta in a coroutine that returns `(meta, rows, exception)`; consumes them with **`asyncio.as_completed`** so each finished search immediately updates `done_tasks`/`products_found`/per-store counters and emits a console event. Outcomes are recorded as `ok` / `no_match` / `error` in an `outcomes` dict.

**Phase 3 — Enrich & Scale (sequential)**
6. Enriches each row with `ingredient_quantity`, `ingredient_measurement`, `ingredient_approx_quantity`, `ingredient_approx_unit` from the resolved dish ingredients.
7. Runs `parse_optimiser_columns(row)` on each enriched row to compute `used_price` (proportional cost for the recipe amount), `purchase_quantity`, `purchase_price`, `scaling_ratio`, `status`, etc.

**Phase 4 — Build Store Cost Summary (sequential)**
8. `_build_store_costs()` (pure helper): groups rows by `(company, store name)`; picks the cheapest valid product per ingredient (preferring exact unit matches over approximations); inserts a `not_found` placeholder row for every requested ingredient with no usable product at that store; sums `used_price` per store; attaches failed/no-match/unit-incompatible searches as `issues`.
9. Ranks complete baskets first, then cheapest; logs the winner event and returns an `OptimisationResult` with `duration_seconds` and `dish_source`.

### `_fetch_ingredient(company, api, store_id, store_name, ingredient, region="", exclude_non_food: bool = True) -> list[dict]`

A thin async dispatcher that offloads blocking work to a background thread:

```python
async def _fetch_ingredient(company, api, store_id, store_name, ingredient, region="", exclude_non_food=True):
    if company == "Woolworths":
        return await asyncio.to_thread(_fetch_woolworths_sync, store_id, store_name, ingredient, exclude_non_food)
    return await asyncio.to_thread(_fetch_foodstuffs_sync, company, api, store_id, store_name, ingredient, region, exclude_non_food)
```

``api`` is the shared pre-authenticated Edge client for Foodstuffs brands (unused for Woolworths); ``region`` ("NI"/"SI" from the store CSVs) feeds the Edge API Region cookie. `exclude_non_food` is read from `load_llm_settings()` via `_new_job` and threaded through to every search. Each call runs on a background thread from the 20-worker pool and returns a list of CSV-format row dicts (all products, not just the cheapest).

### `_fetch_woolworths_sync(store_id, store_name, ingredient, exclude_non_food: bool = True) -> list[dict]`

Plain `def` (not async). Runs on a background thread. Returns ALL priced product rows:
- `woolworths_api.create_session()` — fresh `requests.Session` with baseline cookies
- `woolworths_api.set_store_context(session, store_id)` — inject `cw-lrkswrdjp` cookie
- `woolworths_api.search_products(session, ingredient, food_only=True, exclude_non_food=exclude_non_food, size=20)` — HTTP search
- For each priced product: `build_woolworths_row(...)` → adds to rows list
- Closes session in `finally`
- Returns `list[dict]` (all rows, in CSV_COLUMNS format)

**Session isolation pattern:** Each Woolworths search creates its own `requests.Session` (fresh cookie jar), because the server's `Set-Cookie` overwrites injected cookies on a reused session. Foodstuffs uses JWT tokens with URL-path store IDs — no session conflicts.

### `_fetch_foodstuffs_sync(company, api, store_id, store_name, ingredient, region="", exclude_non_food: bool = True) -> list[dict]`

Plain `def` (not async). Runs on a background thread. Reuses the shared, already-authenticated Edge API client for the company (created once per request in Phase 2). Returns ALL priced product rows:
- `api.search_ingredient(store_id, ingredient, region=region, exclude_non_food=exclude_non_food)` — two-pass Algolia pipeline → `(products, pass1_hits)`
- For each priced product: `build_edge_row(...)` (needs `pass1_hit` for category data) → adds to rows list
- Returns `list[dict]` (all rows, in CSV_COLUMNS format)

### Ingredient Resolution: `resolve_ingredients`

Skipped entirely when `custom_dish` is supplied (builder recipe used verbatim, scaled to portions). Otherwise resolution order:
1. **Curated JSON** — `data/dishes.json` lookup (21 dishes). Returns structured ingredients with `quantity`, `unit`, `search_term`, and optional `approx_quantity`/`approx_unit` for non-standard units (e.g. "1 can" → approx 400g).
2. **LLM generation** — If not curated and `MISTRAL_API_KEY` is set, calls Mistral. Only triggered for non-curated dishes.
3. **Fallback** — Uses dish name itself as a single search term.

### Quantity Scaling: `parse_optimiser_columns`

Imported from `NZMealOptimiser.llm.llm_utils`. Computes proportional ingredient costs:

| Condition | Purchase qty | Purchase price | Used price (proportional) |
|-----------|-------------|----------------|--------------------------|
| `ratio <= 1` | 1 pack | `pack_price` | `pack_price × ratio` |
| `ratio > 1` | `ceil(ratio)` packs | `pack_price × ceil(ratio)` | `pack_price × ratio` |
| Incompatible | 0 | None | None |

Units are normalised (weight→grams, volume→milliliters, count→count), with one-way alias folding via `normalise_unit()` (`UNIT_ALIASES`, e.g. `egg`/`eggs` → `each`) applied to recipe units, approx units, and pack units alike. Compound units like `x 375ml` are expanded. Cross-category (weight vs volume) uses 1ml≈1g approximation flagged via `unit_approximate=True`.

---

## Concurrency Model

Per-endpoint view of where parallelism is used and how state is isolated. Per-resource row at the bottom of this section is the older view kept for the resources it covers (the per-endpoint table above is canonical).

| Endpoint | Per-call work | Parallel? | Isolation |
|---|---|---|---|
| `POST /optimise/jobs` | Queue + spawn pipeline | n/a | Per-process `JOBS` dict; `MAX_RETAINED_JOBS=40` cap, finished-first eviction |
| `GET /optimise/{id}` | Read snapshot | n/a (loop thread) | Single-loop mutation; no lock |
| `POST /optimise/{id}/reapply` | Pure recompute from `pipeline_cache` | n/a | Read-only against the cache (deep-copied in `recompute_with_filters`) |
| `POST /optimise/{id}/filter_preview` | Pure recompute from `pipeline_cache` | n/a | Read-only |
| `POST /optimise/{id}/ai_filter_preview` | LLM call + dry-run | LLM is blocking; offloaded to thread | None required (LLM provider) |
| `POST /optimise/{id}/auto_cull_preview` | LLM call + dry-run | Same as above | Same as above |
| `POST /optimise/{id}/update_ingredients` | Partial re-query for added/renamed terms | Yes (thread pool) | Reuses the same shared Edge clients as the original run; fresh `requests.Session` per Woolworths search |
| `GET /geocode` | Nominatim forward | No (1 req/sec) | `_GEOCODE_CACHE` LRU (200) |
| `GET /geocode/autocomplete` | Photon `photon.komoot.io/api/` | No (per-keystroke, debounced 300 ms client-side) | `_AUTOCOMPLETE_CACHE` LRU (200) |
| `GET /geocode/reverse` | Photon default, Nominatim opt-in | No (per click/dragend) | `_PHOTON_REVERSE_CACHE` / `_REVERSE_CACHE` LRU (200) |
| `GET /stores/nearby` | Local CSV + haversine (PNS, NW) / `woolworths_api.get_nearby_stores` (WW) | No (instant) | Stateless |
| `POST /system/thread-pool` | Atomic executor swap | No (single short transaction) | 409 while any job is `status == "running"` |

Per-resource view (legacy summary, useful when reasoning about the search pool only):

| Resource | Parallel? | Isolation method |
|---|---|---|
| Pak'nSave stores | Yes (thread pool) | JWT token, URL-path store IDs |
| New World stores | Yes (thread pool) | JWT token, URL-path store IDs |
| Woolworths stores | Yes (thread pool) | Fresh `requests.Session()` per store (cookie jar) |
| All 3 companies | Yes | Independent API clients |
| Ingredients (per store) | Yes | No shared state between calls |
| Geocoding (Nominatim) | No (1 req/sec limit) | `_GEOCODE_CACHE` (200) LRU |
| Photon (autocomplete + reverse) | No (fast upstream, no sleep) | `_AUTOCOMPLETE_CACHE` / `_PHOTON_REVERSE_CACHE` (200) LRU |

## Concurrency Pipeline Diagram

```
POST /optimise/jobs  → {"job_id"}  (background task; poll GET /optimise/{id})
│
├── Phase 1: Resolve, validate, geocode, scale  (sequential)
│   ├── custom_dish? → _validate_custom_dish + _scale_ingredients_to_portions
│   │                  (skips curated + LLM resolution)
│   ├── resolve_ingredients("spaghetti bolognese") → 7 ingredients with quantities
│   ├── _scale_ingredients_to_portions(dish_dict, req.portions)  (no-op at default)
│   ├── _resolve_origin(job): GPS → use as-is, else Nominatim (1 req/sec)
│   └── outcome → {dish_name, search_terms, ing_lookup, origin}
│
├── Phase 2: Build & launch tasks  (sequential, instant)
│   ├── authenticate ONE PaknSaveEdgeAPI + ONE NewWorldEdgeAPI (shared per request)
│   ├── for company in [PaknSave, New World, Woolworths]:
│   │   ├── find_nearby_stores(lat, lon, radius_km=distance_km) → [StoreA, StoreB, ...]
│   │   └── metas += (company, store_id, store_name, ingredient) tuples
│   └── initialise per-company progress entries
│
├── Phase 3: Concurrent execution  (asyncio.as_completed + 20-worker thread pool)
│   ├── each finished search updates job counters + emits a console event
│   ├── _fetch_foodstuffs_sync(...) → build_edge_row() for each product
│   └── _fetch_woolworths_sync(...) → build_woolworths_row() for each product
│
└── Phase 4: Enrich, scale, build store costs  (sequential, CPU-bound)
    ├── _enrich_and_scale_rows: stamp ingredient quantities + filter validity
    │   + parse_optimiser_columns (used_price, purchase_qty, status, …)
    ├── _build_store_costs(search_terms, ing_lookup, rows, outcomes, store_geo)
    │   → placeholder rows for missing, rank complete-basket-first then by cost
    └── emit winner event → return OptimisationResult with duration_seconds + dish_source
```

### What each sync helper does internally

```
_fetch_woolworths_sync(store_id, store_name, ingredient)   [plain def, runs on thread]
├── session = woolworths_api.create_session()         ← fresh Session (cookie jar)
├── woolworths_api.set_store_context(session, sid)   ← inject cw-lrkswrdjp cookie
├── woolworths_api.search_products(session, ingredient)
├── for each priced product: build_woolworths_row(...) → CSV COLUMNS row
└── return list[dict]


_fetch_foodstuffs_sync(company, api, store_id, store_name, ingredient, region)   [plain def, runs on thread]
├── api = shared PaknSaveEdgeAPI/NewWorldEdgeAPI          ← authenticated ONCE per request
├── api.search_ingredient(store_id, ingredient, region)   ← two-pass Algolia pipeline → (products, pass1_hits)
├── for each priced product: build_edge_row(...)          → CSV COLUMNS row
└── return list[dict]
```

### Timing breakdown (typical)

| Phase | Time | Parallelized? |
|---|---|---|
| Ingredient resolution | <1s | No |
| Geocoding (Nominatim) | 1-3s | No (rate limit 1 req/sec) |
| Store lookup (×3 brands) | <0.1s | No (local CSV reads, fast) |
| API searches (20-thread pool) | ~15-25s | **Yes** — parallel searches capped at 20 via `asyncio.to_thread` (the per-query limit shared across all stores); results stream in per-search via `as_completed` |
| Row enrichment + scaling | <1s | No (CPU-bound, fast) |
| Store cost summary | <0.1s | No |
| **Total** | **~17-30s** | — |

Without thread offloading, all tasks run sequentially. With 20 threads, wall time ≈ `ceil(total_tasks / 20) × ~5s`.

**Example: spaghetti bolognese (7 ingredients) across 3 companies × 3 stores = 63 total searches**

- Geocoding: 1-3s (Nominatim rate limited, runs once)
- 63 API searches via 20-thread pool: wall time ≈ `ceil(63/20) × ~5s ≈ 20s`
- Sequential equivalent: ~5+ minutes (63 × ~5s each)
- Total wall time: ~22-30s

---

## Data Flow Summary

```
POST /optimise/jobs → {"job_id"}            GET /optimise/{id}?events_since=N (polled)
│                                            │
User Input                    API Processing                              Output
──────────                     ──────────────                             ──────
dish: "spaghetti..."          → dishes.json / LLM → 7 ingredients         snapshot / OptimisationResult
address: "Auckland CBD"       → Nominatim geocode                         ├─ status, phase, elapsed
distance_km: 5                → find nearby stores ×3 brands              ├─ per-company progress counters
max_stores: 3                 → shared Edge clients + as_completed()      ├─ events[] (console log)
portions: 4                   → build_*_row() per product                 ├─ rows (all product results)
                              → parse_optimiser_columns() scaling        └─ store_costs (per-store summary
                                → pick cheapest per ingredient per store      incl. issues) + duration_seconds
                                → sum used_price per store
```

Nothing is written to `full_results.csv` by default — the data is returned directly as JSON. The optional `_maybe_persist` function (not wired in) would write to Supabase if configured.

> **Removed modules:** Items removed during the app-shell rewrite (workers/, services/supabase_client.py, models/, routes/, custom price extraction, "best price per ingredient" logic) are documented in `docs/project\decision.md` §41, not here.

## Google Cloud Run Deployment

The `Dockerfile` at the repo root packages the app into a container. To deploy:

```bash
gcloud run deploy --source .
```

Serverless scaling handles concurrency; each request is independent.
