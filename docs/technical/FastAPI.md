# FastAPI Architecture — `src/NZMealOptimiser/web/main.py`

## Overview

A FastAPI web server that turns the CLI optimiser into an HTTP API + browser dashboard. Users send a dish name and NZ address, the server concurrently searches all 3 supermarket brands across nearby stores, and returns a two-table result: (1) all raw product rows in `full_results.csv` format, and (2) a per-store cost comparison using quantity-scaled "used cost".

**Run with:**
```
.venv\Scripts\uvicorn NZMealOptimiser.web.main:app --host 0.0.0.0 --port 8000
```
Then open `http://127.0.0.1:8000/` for the dashboard, `http://127.0.0.1:8000/app` for the Vue dashboard, or `http://127.0.0.1:8000/docs` for Swagger.

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
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=20)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.get_event_loop().set_default_executor(_THREAD_POOL)
    yield
```

**Why this exists:** The API libraries (`woolworths_api`, `paknsave_api`, `newworld_api`) are all synchronous — they use `requests.Session` for HTTP calls. Without `asyncio.to_thread`, these calls block the event loop and all tasks execute one-by-one.

`asyncio.to_thread(func, *args)` runs `func` on a background thread from the pool (20 workers) while the event loop stays free. With 20 workers, up to 20 searches run in parallel — the rest queue and start as slots free up.

**Pool size — why 20:** With 20 workers, up to 20 searches run in parallel. Wall time ≈ `ceil(total_tasks / 20) × ~5s`. Going higher (e.g. 63 workers) gives diminishing returns and uses more memory.

---

## Global Constants

| Variable | Purpose |
|---|---|
| `DATA_DIR` | Points to `project/data/` (dishes.json, store CSVs) — resolved in `src/NZMealOptimiser/__init__.py` |
| `TMP_DIR` | Scratchpad folder (`src/NZMealOptimiser/web/tmp/`), created if missing. Currently unused. |
| `STATIC_DIR` | Folder for the frontend (`src/NZMealOptimiser/web/static/`). Mounted at `/static`. |
| `BRANDS` | Dispatch dict mapping brand names to their API classes, find_nearby functions, and metadata. |
| `_THREAD_POOL` | 20-worker thread pool for offloading blocking HTTP calls. |

### `BRANDS` dispatch dict

```python
BRANDS = {
    "PaknSave":  { "api_class": PaknSaveEdgeAPI, "find_nearby": ps_find_nearby, ... },
    "NewWorld":  { "api_class": NewWorldEdgeAPI, "find_nearby": nw_find_nearby, ... },
    "Woolworths": { ... },  # No api_class — uses woolworths_api module functions directly
}
```

Used by `run_optimisation()` and `_fetch_foodstuffs_sync()` to look up which API client and store finder to use per brand. `company_id` is passed to `build_*_row` to label rows in the CSV format.

---

## Pydantic Models

### `DishRequest` (input)
| Field | Type | Default | Description |
|---|---|---|---|
| `dish` | `str` | — | Dish name (e.g. "spaghetti bolognese") |
| `address` | `str` | — | NZ address or suburb for geocoding |
| `distance_km` | `float` | `5.0` | Search radius around the address |
| `max_stores_per_company` | `int` | `3` | Cap on stores checked per brand |
| `companies` | `list[str]` | `None` | Filter to specific brands; `None` = all 3 |
| `portions` | `int` | `4` | Number of servings (used for ingredient quantity resolution) |

### `OptimisationResult` (output)
| Field | Type | Description |
|---|---|---|
| `dish` | `str` | Resolved display name of the dish |
| `companies_checked` | `list[str]` | Which brands were searched |
| `rows` | `list[dict]` | All product result rows in CSV_COLUMNS format (18 fields per row) |
| `store_costs` | `list[dict]` | Per-store cost summary sorted by total used cost (cheapest first) |
| `timestamp` | `str` | ISO timestamp of when the result was generated |

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
| `total_used_cost` | Sum of cheapest valid `used_price` across all ingredients |
| `ingredients_matched` | Number of ingredients with valid scaled prices |
| `ingredients_total` | Total ingredients searched |
| `best_per_ingredient` | Detail list: for each ingredient, the cheapest product with used_price, purchase qty, etc. |

---

## API Endpoints

| Route | Method | Description |
|---|---|---|
| `/` | GET | Legacy vanilla dashboard (`static/index_old.html`) |
| `/app`, `/app/` | GET | Vue dashboard (`static/vue/index.html`) |
| `/health` | GET | Health check → `{"status": "ok", "supabase_enabled": bool}` |
| `/dishes` | GET | Curated dishes from `data/dishes.json` (for the Vue dashboard) |
| `/optimise` | POST | Main endpoint — accepts `DishRequest`, returns `OptimisationResult` |
| `/docs` | GET | Swagger UI (FastAPI default) |
| `/static` | Mount | Serves `STATIC_DIR` |

### `POST /optimise` — Main Endpoint

Accepts a `DishRequest` body. Delegates to `run_optimisation()`. Returns an `OptimisationResult` as JSON.

**curl example:**
```bash
curl -X POST "http://127.0.0.1:8000/optimise" \
  -H "Content-Type: application/json" \
  -d '{"dish": "spaghetti bolognese", "address": "Auckland CBD", "distance_km": 5, "portions": 4, "max_stores_per_company": 3}'
```

---

## Functions

### `run_optimisation(dish_name, address, distance_km, max_stores_per_company, companies, portions) -> OptimisationResult`

The core orchestrator. Runs in 4 phases:

**Phase 1 — Resolve & Geocode (sequential)**
1. Calls `resolve_ingredients(dish_name, portions)` which looks up `dishes.json` for curated ingredient lists (with quantities, units, and approx fallbacks for non-standard units). Falls back to LLM generation if not curated and an API key is available; otherwise uses the dish name as a single search term.
2. Calls `optimiser_utils.geocode(address)` (Nominatim, rate-limited to 1 req/sec) to get lat/lon. Runs once — before any concurrent work.

**Phase 2 — Build & Launch Tasks (concurrent)**
3. For each company × nearby store × ingredient, appends a `_fetch_ingredient(...)` coroutine to the `tasks` list. Builds a parallel `task_metadata` list tracking `(company, store_id, store_name, ingredient)`.
4. Calls `asyncio.gather(*tasks, return_exceptions=True)` — all tasks run concurrently via the 20-worker thread pool. Exceptions are caught per-task, not fatal.

**Phase 3 — Collect, Enrich & Scale (sequential)**
5. Flattens all task results into `all_rows` (list of `build_*_row` dicts — full CSV_COLUMNS format, 17 fields).
6. Enriches each row with `ingredient_quantity`, `ingredient_measurement`, `ingredient_approx_quantity`, `ingredient_approx_unit` from the resolved dish ingredients.
7. Runs `parse_optimiser_columns(row)` on each enriched row to compute `used_price` (proportional cost for the recipe amount), `purchase_quantity`, `purchase_price`, `scaling_ratio`, `status`, etc.

**Phase 4 — Build Store Cost Summary (sequential)**
8. For each store, picks the cheapest valid product per ingredient (preferring exact unit matches over approximations).
9. Sums `used_price` across all ingredients per store.
10. Sorts stores by total used cost ascending.
11. Returns an `OptimisationResult` with `rows` (all raw rows) and `store_costs` (summary).

### `_fetch_ingredient(company, store_id, store_name, ingredient) -> list[dict]`

A thin async dispatcher that offloads blocking work to a background thread:

```python
async def _fetch_ingredient(company, store_id, store_name, ingredient):
    if company == "Woolworths":
        return await asyncio.to_thread(_fetch_woolworths_sync, store_id, store_name, ingredient)
    else:
        return await asyncio.to_thread(_fetch_foodstuffs_sync, company, store_id, store_name, ingredient)
```

Each call runs on a background thread from the 20-worker pool. Returns a list of CSV-format row dicts (all products, not just the cheapest).

### `_fetch_woolworths_sync(store_id, store_name, ingredient) -> list[dict]`

Plain `def` (not async). Runs on a background thread. Returns ALL priced product rows:
- `woolworths_api.create_session()` — fresh `requests.Session` with baseline cookies
- `woolworths_api.set_store_context(session, store_id)` — inject `cw-lrkswrdjp` cookie
- `woolworths_api.search_products(session, ingredient, food_only=True, size=20)` — HTTP search
- For each priced product: `build_woolworths_row(...)` → adds to rows list
- Closes session in `finally`
- Returns `list[dict]` (all rows, in CSV_COLUMNS format)

**Session isolation pattern:** Each Woolworths search creates its own `requests.Session` (fresh cookie jar), because the server's `Set-Cookie` overwrites injected cookies on a reused session. Foodstuffs uses JWT tokens with URL-path store IDs — no session conflicts.

### `_fetch_foodstuffs_sync(company, store_id, store_name, ingredient) -> list[dict]`

Plain `def` (not async). Runs on a background thread. Returns ALL priced product rows:
- `PaknSaveEdgeAPI()` or `NewWorldEdgeAPI()` — new instance per call
- `api.authenticate()` — JWT token (if not cached)
- `api.search_ingredient(store_id, ingredient, region)` — two-pass Algolia pipeline → `(products, pass1_hits)`
- For each priced product: `build_edge_row(...)` (needs `pass1_hit` for category data) → adds to rows list
- Returns `list[dict]` (all rows, in CSV_COLUMNS format)

### Ingredient Resolution: `resolve_ingredients`

Imported from `NZMealOptimiser.llm.llm_utils`. Resolution order:
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

Units are normalised (weight→grams, volume→milliliters, count→count). Compound units like `x 375ml` are expanded. Cross-category (weight vs volume) uses 1ml≈1g approximation flagged via `unit_approximate=True`.

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
POST /optimise  (single HTTP request)
│
├── Phase 1: Sequential setup
│   ├── resolve_ingredients("spaghetti bolognese") → 7 ingredients with quantities
│   └── geocode("Auckland CBD")  [Nominatim, ~1-3s]
│
├── Phase 2: Build tasks (sequential, instant)
│   └── for company in [PaknSave, NewWorld, Woolworths]:
│       ├── find_nearby_stores(lat, lon, radius_km=5) → [StoreA, StoreB, StoreC]
│       └── for store in [StoreA, StoreB, StoreC]:
│           └── for ingredient in ["beef mince", ...]:
│               └── tasks.append(_fetch_ingredient(...))
│
├── Phase 3: asyncio.gather() → 20-worker thread pool
│   ├── _fetch_foodstuffs_sync(...) → build_edge_row() for each product
│   └── _fetch_woolworths_sync(...) → build_woolworths_row() for each product
│   All return list[dict] of CSV_COLUMNS rows
│
├── Phase 3b: Enrich rows with ingredient quantities from dishes.json
│
├── Phase 3c: parse_optimiser_columns(row) → used_price, purchase_qty, status
│
└── Phase 4: Store cost summary (cheapest per ingredient per store, summed)
```

### What each sync helper does internally

```
_fetch_woolworths_sync(store_id, store_name, ingredient)   [plain def, runs on thread]
├── session = woolworths_api.create_session()         ← fresh Session (cookie jar)
├── woolworths_api.set_store_context(session, sid)   ← inject cw-lrkswrdjp cookie
├── woolworths_api.search_products(session, ingredient)
├── for each priced product: build_woolworths_row(...) → CSV COLUMNS row
└── return list[dict]


_fetch_foodstuffs_sync(company, store_id, store_name, ingredient)   [plain def, runs on thread]
├── api = PaknSaveEdgeAPI() or NewWorldEdgeAPI()       ← new instance each call
├── api.authenticate()                                  ← JWT token (if missing)
├── api.search_ingredient(store_id, ingredient)        ← two-pass Algolia pipeline → (products, pass1_hits)
├── for each priced product: build_edge_row(...)      → CSV COLUMNS row
└── return list[dict]
```

### Timing breakdown (typical)

| Phase | Time | Parallelized? |
|---|---|---|
| Ingredient resolution | <1s | No |
| Geocoding (Nominatim) | 1-3s | No (rate limit 1 req/sec) |
| Store lookup (×3 brands) | <0.1s | No (local CSV reads, fast) |
| API searches (20-thread pool) | ~15-25s | **Yes** — runs in batches of 20 via `asyncio.to_thread` |
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
User Input                    API Processing                              Output
──────────                     ──────────────                             ──────
dish: "spaghetti..."          → dishes.json / LLM → 7 ingredients         OptimisationResult
address: "Auckland CBD"       → Nominatim geocode                          ├─ dish (display name)
distance_km: 5                → find nearby stores ×3 brands                ├─ companies_checked
max_stores: 3                 → to_thread() searches (batches of 20)       ├─ rows (all product results)
portions: 4                   → build_*_row() per product                  ├─ store_costs (per-store summary)
                                → parse_optimiser_columns() scaling        └─ timestamp
                                → pick cheapest per ingredient per store
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
