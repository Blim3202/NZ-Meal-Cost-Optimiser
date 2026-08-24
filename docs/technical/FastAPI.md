# FastAPI Architecture — `src/NZMealOptimiser/web/main.py`

## Overview

A FastAPI web server that turns the CLI optimiser into an HTTP API + browser dashboard. Users send a dish name and NZ address, the server concurrently searches all 3 supermarket brands across nearby stores, and returns a two-table result: (1) all raw product rows in `full_results.csv` format, and (2) a per-store cost comparison using quantity-scaled "used cost".

Runs are **background jobs**: `POST /optimise/jobs` returns a `job_id` immediately and the pipeline streams progress (phase, per-company store/product counters, per-search event log) via `GET /optimise/{job_id}` polling. The Vue dashboard renders this as brand progress tiles with SVG rings plus a live terminal-style backend console.

**Run with:**
```
.venv\Scripts\uvicorn NZMealOptimiser.web.main:app --host 0.0.0.0 --port 8000
```
Then open `http://127.0.0.1:8000/` for the classic dashboard, `http://127.0.0.1:8000/app` for the Vue dashboard, `http://127.0.0.1:8000/test` for the app-shell workspace (optimiser dashboard, My Dishes, LLM Recipe Builder stub, Documentation viewer, Settings), or `http://127.0.0.1:8000/docs` for Swagger.

No manual path bootstrap is needed — the package is installed editable (`pip install -e .`) and all imports resolve from `NZMealOptimiser.*`.

---

## Imports & Bootstrap

```python
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
import concurrent.futures
EFFECTIVE_MAX_WORKERS = max(1, min(int(settings.WEB_MAX_WORKERS), 64))
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=EFFECTIVE_MAX_WORKERS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.get_event_loop().set_default_executor(_THREAD_POOL)
    yield
```

**Why this exists:** The API libraries (`woolworths_api`, `paknsave_api`, `newworld_api`) are all synchronous — they use `requests.Session` for HTTP calls. Without `asyncio.to_thread`, these calls block the event loop and all tasks execute one-by-one.

`asyncio.to_thread(func, *args)` runs `func` on a background thread from the pool (default 20 workers) while the event loop stays free. With 20 workers, up to 20 searches run in parallel — the rest queue and start as slots free up.

**Pool size — why 20:** With 20 workers, up to 20 searches run in parallel. Wall time ≈ `ceil(total_tasks / 20) × ~5s`. Going higher (e.g. 63 workers) gives diminishing returns and uses more memory.

**Configuring the size:** `WEB_MAX_WORKERS` (`.env` or env var, default 20, clamped 1–64) is read once at import time. `ThreadPoolExecutor` cannot be resized live, so changes require a server restart — a live-resize endpoint was considered and deliberately deferred (see Vue_Dashboard.md → Future plans). `GET /system-info` reports both the configured and effective values so the Settings page can show "restart required" honestly.

---

## Global Constants

| Variable | Purpose |
|---|---|
| `DATA_DIR` | Points to `project/data/` (dishes.json, store CSVs) — resolved in `src/NZMealOptimiser/__init__.py` |
| `TMP_DIR` | Scratchpad folder (`src/NZMealOptimiser/web/tmp/`), created if missing. Currently unused. |
| `STATIC_DIR` | Folder for the frontend (`src/NZMealOptimiser/web/static/`). Mounted at `/static`. |
| `BRANDS` | Dispatch dict mapping brand names to their API classes, find_nearby functions, and metadata. |
| `_THREAD_POOL` / `EFFECTIVE_MAX_WORKERS` | Thread pool for offloading blocking HTTP calls, sized from `settings.WEB_MAX_WORKERS` (default 20). |
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

Mutable progress object created per optimisation request (`_new_job`). Key attributes: `id` (12-char hex), `req` (the `DishRequest`), `status`, `phase`, `started`/`finished` timestamps, `error_detail`/`error_status`, task counters (`total_tasks`/`done_tasks`/`products_found`), `company_progress` (per-brand `{label, code, stores_total, stores_done, products}`), `events` (append-only console log), and the final `result`.

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

GPS coordinates are validated against a rough NZ bounding box (`NZ_LAT_RANGE = (-47.6, -34.2)`, `NZ_LON_RANGE = (166.2, 178.9)`): out-of-bounds or half-specified coords fail with 400 before any search work starts.

### `CustomDish` / `CustomIngredient` (dish builder input)

```python
class CustomIngredient(BaseModel):
    ingredient: str; quantity: float; unit: str
    search_term: Optional[str] = None
    approx_quantity: Optional[float] = None; approx_unit: Optional[str] = None

class CustomDish(BaseModel):
    name: str = ""; base_portions: int = 4; ingredients: list[CustomIngredient]
    source_label: str = "custom"  # "custom" | "shopping_list" (validated)
```

When `custom_dish` is set it **replaces** the `dish`-name resolution path entirely:

1. `_validate_custom_dish()` — sync validation: non-empty name/ingredients, positive finite quantities, non-empty units, and `source_label ∈ CUSTOM_DISH_SOURCES` (`{"custom", "shopping_list"}`; anything else is a 400). Units are normalised through `normalise_unit()` (alias folding, e.g. `eggs` → `each`) at build time.
2. `_scale_ingredients_to_portions(dish_dict, req.portions)` — uniform scaling of every numeric quantity from `base_portions` to the requested `portions`. Applied to ALL sources (curated, LLM, custom); a no-op at default portions. Scaling happens per-request — presets are stored verbatim at their base portions.

**Shopping-list searches** (/test) reuse this exact path with zero backend-specific logic: the frontend submits `base_portions=1`, `portions=1`, `source_label="shopping_list"` and a fixed dish name `"Shopping list"` — so quantities are priced as-is with no portion scaling, and `dish_source` labels the results header chip.

### `OptimisationResult` (output)
| Field | Type | Description |
|---|---|---|
| `dish` | `str` | Resolved display name of the dish |
| `dish_source` | `str` | `"curated"`, `"custom"`, `"shopping_list"`, or `"llm"`/`"fallback"` — drives the results-header chip |
| `companies_checked` | `list[str]` | Which brands were searched |
| `rows` | `list[dict]` | All product result rows in CSV_COLUMNS format (18 fields per row) |
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
| `issues` | Unavailable ingredients for this store: `{search_ingredient, status: "error"\|"no_match"\|"incompatible_units", detail}`. Kept alongside placeholder rows so the *reason* stays visible |
| `lat` / `lon` | Store coordinates (from the brand store CSVs) — consumed by the dashboard map pins |
| `distance_km` | Haversine distance from the resolved origin, rounded to 2 dp |

**Ranking:** stores are sorted **complete-basket-first, then by total_used_cost** — a partial basket can never outrank a complete one on a missing ingredient's $0. If no store is complete, all are partial and sort by cost among themselves (a fully-failed $0.00 store can sit above a 1-of-3 match). Stores where every search failed still get a card ($0.00, incomplete). Phase 4 is implemented in the pure helper `_build_store_costs(search_terms, ing_lookup, all_rows, outcomes, store_geo)` with `_placeholder_row(term, ing)`; candidates derive from the `outcomes` dict, so dead stores are included even with zero rows.

---

## API Endpoints

| Route | Method | Description |
|---|---|---|
| `/` | GET | Legacy vanilla dashboard (`static/index_old.html`) |
| `/app`, `/app/` | GET | Vue dashboard (`static/vue/index.html`) |
| `/test`, `/test/` | GET | App-shell workspace (`static/vue/test.html`) — left sidebar switching the optimiser dashboard (custom recipes/shopping lists, CSV export), My Dishes, LLM Recipe Builder stub, Documentation viewer and Settings |
| `/health` | GET | Health check → `{"status": "ok", "supabase_enabled": bool}` |
| `/system-info` | GET | Runtime facts for Settings → `{max_workers, configured_workers, hard_limits}` |
| `/dishes` | GET | Dishes from `data/dishes.json` — curated presets plus saved builder dishes (`portion` key = base portions; `"source": "user"` marks builder-saved entries, absent = curated) |
| `/dishes/save` | POST | Upsert a builder dish as a preset in `data/dishes.json` (`SaveDishRequest{name, base_portions, ingredients}`); validates via `_validate_custom_dish`, tags `"source": "user"`, writes atomically (tmp file + `os.replace`) |
| `/dishes/{key}` | DELETE | Remove a preset dish from `data/dishes.json` → `{ok, was_user, dishes_count}`; 404 on unknown keys |
| `/tech-docs` | GET | List the whitelisted manuals → `[{name, title}]` |
| `/tech-docs/{name}` | GET | Serve one manual as raw markdown (`text/markdown`) for client-side rendering; whitelisted names only |
| `/geocode` | GET | `?address=...` → `{lat, lon, cached}` — standalone Nominatim lookup for the dashboard's resolve step (LRU-cached, NZ-bbox validated) |
| `/stores/nearby` | GET | `?lat&lon&distance_km&companies=PaknSave,NewWorld,Woolworths&max_per_company` → `{origin, stores[]}` — preview of which stores a run would query (local CSV + haversine, same helpers/cap as pipeline Phase 2, no supermarket API calls). Enforces `HARD_LIMITS`. |
| `/optimise` | POST | Legacy synchronous endpoint (classic dashboard) — accepts `DishRequest`, blocks until done, returns `OptimisationResult` |
| `/optimise/jobs` | POST | Queue an optimisation — accepts `DishRequest`, returns `{"job_id"}` immediately. Enforces `HARD_LIMITS` via `_new_job`. |
| `/optimise/{job_id}` | GET | Job snapshot: status, phase, elapsed, per-company progress, incremental events (`?events_since=N`), final `result` |
| `/docs` | GET | Swagger UI (FastAPI default) |
| `/static` | Mount | Serves `STATIC_DIR` |

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

Returns a snapshot dict:

| Field | Description |
|---|---|
| `status` | `queued` → `running` → `complete` \| `error` |
| `phase` | Human-readable pipeline stage ("Geocoding address", "Searching 63 store × ingredient combos", …); terminal jobs end on "Completed" or "Failed" |
| `elapsed_seconds` | Server-computed seconds since start |
| `total_tasks` / `done_tasks` | Store × ingredient search counters |
| `products_found` | Total product rows collected so far |
| `companies[]` | Per-brand: `{id, label, code, stores_total, stores_done, products}` |
| `events[]` / `next_cursor` | Console events with index > `events_since`; pass `next_cursor` back for incremental polling |
| `error_detail` | Set when `status=error` |
| `result` | Full `OptimisationResult` once `status=complete` |

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

### `_fetch_ingredient(company, api, store_id, store_name, ingredient, region="") -> list[dict]`

A thin async dispatcher that offloads blocking work to a background thread:

```python
async def _fetch_ingredient(company, api, store_id, store_name, ingredient, region=""):
    if company == "Woolworths":
        return await asyncio.to_thread(_fetch_woolworths_sync, store_id, store_name, ingredient)
    return await asyncio.to_thread(_fetch_foodstuffs_sync, company, api, store_id, store_name, ingredient, region)
```

``api`` is the shared pre-authenticated Edge client for Foodstuffs brands (unused for Woolworths); ``region`` ("NI"/"SI" from the store CSVs) feeds the Edge API Region cookie. Each call runs on a background thread from the 20-worker pool and returns a list of CSV-format row dicts (all products, not just the cheapest).

### `_fetch_woolworths_sync(store_id, store_name, ingredient) -> list[dict]`

Plain `def` (not async). Runs on a background thread. Returns ALL priced product rows:
- `woolworths_api.create_session()` — fresh `requests.Session` with baseline cookies
- `woolworths_api.set_store_context(session, store_id)` — inject `cw-lrkswrdjp` cookie
- `woolworths_api.search_products(session, ingredient, food_only=True, size=20)` — HTTP search
- For each priced product: `build_woolworths_row(...)` → adds to rows list
- Closes session in `finally`
- Returns `list[dict]` (all rows, in CSV_COLUMNS format)

**Session isolation pattern:** Each Woolworths search creates its own `requests.Session` (fresh cookie jar), because the server's `Set-Cookie` overwrites injected cookies on a reused session. Foodstuffs uses JWT tokens with URL-path store IDs — no session conflicts.

### `_fetch_foodstuffs_sync(company, api, store_id, store_name, ingredient, region="") -> list[dict]`

Plain `def` (not async). Runs on a background thread. Reuses the shared, already-authenticated Edge API client for the company (created once per request in Phase 2). Returns ALL priced product rows:
- `api.search_ingredient(store_id, ingredient, region)` — two-pass Algolia pipeline → `(products, pass1_hits)`
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

| Component | Parallel | Isolation Method |
|-----------|----------|-----------------|
| Geocoding (Nominatim) | No (1 req/sec limit) | Single call before searches |
| Pak'nSave stores | Yes (20-thread pool) | JWT token, URL-path store IDs |
| New World stores | Yes (20-thread pool) | JWT token, URL-path store IDs |
| Woolworths stores | Yes (20-thread pool) | Fresh `requests.Session()` per store |
| All 3 companies | Yes | Independent API clients |
| Ingredients (per store) | Yes | No shared state between calls |

## Concurrency Pipeline Diagram

```
POST /optimise/jobs  → {"job_id"}  (background task; poll GET /optimise/{id})
│
├── Phase 1: Sequential setup
│   ├── custom_dish? → validate + scale to portions   (skips resolution)
│   ├── resolve_ingredients("spaghetti bolognese") → 7 ingredients with quantities
│   └── geocode("Auckland CBD")  [Nominatim, ~1-3s]
│
├── Phase 2: Shared Edge clients + task list (sequential, instant)
│   ├── authenticate ONE PaknSaveEdgeAPI + ONE NewWorldEdgeAPI (shared per request)
│   └── for company in [PaknSave, NewWorld, Woolworths]:
│       ├── find_nearby_stores(lat, lon, radius_km=5) → [StoreA, StoreB, StoreC]
│       └── metas += (company, store_id, store_name, ingredient) tuples
│
├── Phase 2b: asyncio.as_completed() → 20-worker thread pool
│   ├── each finished search updates job counters + emits a console event
│   ├── _fetch_foodstuffs_sync(...) → build_edge_row() for each product
│   └── _fetch_woolworths_sync(...) → build_woolworths_row() for each product
│
├── Phase 3b: Enrich rows with ingredient quantities from dishes.json
│
├── Phase 3c: parse_optimiser_columns(row) → used_price, purchase_qty, status
│
└── Phase 4: Store cost summary (cheapest per ingredient per store, summed,
    failed searches attached as issues)
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

---

## What Was Removed (and Why)

- **`workers/` folder** — Queueing system for serialized processing. Removed because sessions are isolated naturally via `requests.Session()` per call.
- **`services/supabase_client.py`** — Supabase write client. Removed because persistence is optional and can be added to `main.py` later.
- **`seed_phase1.py`, `schema_phase1.sql`** — Database seeding files. Removed because we start with local storage; can add later if Supabase is used.
- **`models/` folder** — Pydantic request/response models. Consolidated into `main.py` for simplicity.
- **`routes/` folder** — Separate route files. Consolidated to single `main.py` since we only have 2 endpoints (`/optimise`, `/health`).
- **Custom price extraction** — Replaced with `build_edge_row` / `build_woolworths_row` to reuse the existing row format from the CLI optimisers.
- **"Best price per ingredient" logic** — Removed; the API now returns ALL product results, with quantity-scaled "used cost" computed via `parse_optimiser_columns`.

## Google Cloud Run Deployment

The `Dockerfile` at the repo root packages the app into a container. To deploy:

```bash
gcloud run deploy --source .
```

Serverless scaling handles concurrency; each request is independent.
