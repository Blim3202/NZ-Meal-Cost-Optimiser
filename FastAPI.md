# FastAPI Architecture — `scripts/fastapi/main.py`

## Overview

A FastAPI web server that turns the CLI optimiser into an HTTP API + browser dashboard. Users send a dish name and NZ address, the server concurrently searches all 3 supermarket brands across nearby stores, and returns the cheapest option.

**Run with:**
```
.venv\Scripts\python scripts/fastapi/main.py
```
Then open `http://127.0.0.1:8000/` for the dashboard or `http://127.0.0.1:8000/docs` for Swagger.

---

## Imports & Bootstrap

```python
import core.paths              # Adds scripts/combined/, scripts/newworld/, etc. to sys.path
import optimiser_utils          # Shared helpers (geocode, get_ingredients, _resolve_dish_terms)
from paknsave_api import PaknSaveEdgeAPI, find_nearby_stores as ps_find_nearby
from newworld_api import NewWorldEdgeAPI, find_nearby_stores as nw_find_nearby
import woolworths_api
```

`core.paths` runs at import time and adds all `scripts/*/` directories to `sys.path` so the existing modules are importable without modifying them. No `async` changes were needed in any of the old code.

---

## Thread Pool Setup

```python
import concurrent.futures
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=20)

@app.on_event("startup")
async def _set_thread_pool():
    asyncio.get_event_loop().set_default_executor(_THREAD_POOL)
```

**Why this exists:** The API libraries (`woolworths_api`, `newworld_api`, `paknsave_api`) are all synchronous — they use `requests.Session` for blocking HTTP calls. Without `asyncio.to_thread`, these calls freeze the event loop and all tasks execute one-by-one.

`asyncio.to_thread(func, *args)` runs `func` on a background thread from the pool while the event loop stays free. With 20 workers, up to 20 searches run in parallel — the rest queue and start as slots free up.

---

## Global Constants

| Variable | Purpose |
|---|---|
| `DATA_DIR` | Points to `project/data/` (dishes.json, store CSVs) |
| `TMP_DIR` | Scratchpad folder (`scripts/fastapi/tmp/`), created if missing. Currently unused. |
| `STATIC_DIR` | Folder for the frontend (`scripts/fastapi/static/`). Mounted at `/static`. |
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

Used by `run_optimisation()` and `_fetch_foodstuffs_sync()` to look up which API client and store finder to use per brand. `company_id` and `logo` are currently unused (reserved for future UI work).

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

### `OptimisationResult` (output)
| Field | Type | Description |
|---|---|---|
| `dish` | `str` | Resolved display name of the dish |
| `companies_checked` | `list[str]` | Which brands were searched |
| `cheapest_store` | `str` | Name of the store with the lowest total |
| `cheapest_total` | `float` | Total cost of all ingredients at the cheapest store |
| `store_breakdown` | `list[dict]` | Every store sorted by total cost, with ingredient details |
| `ingredient_results` | `list[dict]` | Flat list of every successful ingredient fetch |
| `timestamp` | `str` | ISO timestamp of when the result was generated |

---

## API Endpoints

### `GET /` — Web Dashboard
Returns `static/index.html` via `FileResponse`. The browser loads a form, user fills in dish + address, clicks "Optimise", and the JS calls `POST /optimise` under the hood.

### `GET /health` — Health Check
Returns `{"status": "ok", "supabase_enabled": bool}`. Used by load balancers / Docker health checks.

### `POST /optimise` — Main Endpoint
Accepts a `DishRequest` body. Delegates everything to `run_optimisation()`. Returns an `OptimisationResult` as JSON. This is where all the concurrent work happens.

---

## Functions

### `run_optimisation(dish_name, address, distance_km, max_stores_per_company, companies) -> OptimisationResult`

The core orchestrator. Runs in 3 phases:

**Phase 1 — Resolve & Geocode (sequential)**
1. Calls `_resolve_dish_terms(dish_name)` to get the list of ingredient search terms from `dishes.json`.
2. Calls `optimiser_utils.geocode(address)` (Nominatim, rate-limited to 1 req/sec) to get lat/lon. Runs once — before any concurrent work.

**Phase 2 — Build & Launch Tasks (concurrent)**
3. For each company × nearby store × ingredient, appends a `_fetch_ingredient(...)` coroutine to the `tasks` list. Builds a parallel `task_metadata` list tracking `(company, store_id, store_name, ingredient)` for each task.
4. Calls `asyncio.gather(*tasks, return_exceptions=True)` — all tasks run concurrently. Exceptions are caught per-task, not fatal.

**Phase 3 — Consolidate Results (sequential)**
5. Iterates over `(task_metadata, raw_results)` pairs. Converts prices to dollars (Foodstuffs returns cents; Woolworths returns dollars). Builds:
   - `ingredient_results` — flat list of every successful fetch
   - `store_totals` — dict keyed by store name, accumulating `total_cost` and ingredient list. If the same ingredient appears at the same store (shouldn't happen, but handled), keeps the cheaper one.
6. Sorts `store_totals` by `total_cost` ascending.
7. Returns an `OptimisationResult` with the cheapest store at the top.

### `_fetch_ingredient(company, store_id, ingredient) -> Optional[dict]`

A thin async dispatcher that offloads blocking work to a background thread:

```python
async def _fetch_ingredient(company, store_id, ingredient):
    if company == "Woolworths":
        return await asyncio.to_thread(_fetch_woolworths_sync, store_id, ingredient)
    else:
        return await asyncio.to_thread(_fetch_foodstuffs_sync, company, store_id, ingredient)
```

Without `asyncio.to_thread`, the blocking HTTP calls inside `_fetch_woolworths_sync` / `_fetch_foodstuffs_sync` would freeze the event loop. All tasks would run one-by-one (~5+ minutes). With it, up to 20 tasks run in parallel — the rest queue. Wall time ≈ `ceil(total_tasks / 20) × ~5s`.

### `_fetch_woolworths_sync(store_id, ingredient) -> Optional[dict]`

Plain `def` (not async). Runs on a background thread. Contains:
- `woolworths_api.create_session()` — fresh `requests.Session` with baseline cookies
- `woolworths_api.set_store_context(session, store_id)` — inject per-store cookie
- `woolworths_api.search_products(session, ingredient, ...)` — HTTP search
- Picks cheapest product by `salePrice`
- Closes session in `finally`
- Returns `{"price": float (dollars), "unit_price": str, "pack_info": str}`

### `_fetch_foodstuffs_sync(company, store_id, ingredient) -> Optional[dict]`

Plain `def` (not async). Runs on a background thread. Contains:
- `PaknSaveEdgeAPI()` or `NewWorldEdgeAPI()` — new instance per call
- `api.authenticate()` — JWT token if missing
- `api.search_ingredient(store_id, ingredient)` — two-pass Algolia pipeline
- Picks cheapest product by `singlePrice.price`
- Returns `{"price": float (cents), "unit_price": str, "pack_info": str}`
- **Price is in cents** — `run_optimisation` divides by 100 later

### `_resolve_dish_terms(dish_input) -> tuple[str, list[str]]`

Thin wrapper that:
1. Calls `optimiser_utils.get_ingredients(dish_input)` to get the list of ingredient search terms.
2. Calls `optimiser_utils._resolve_dish_data(dish_input)` to get the display name.
3. Returns `(display_name, search_terms)`.

### `_maybe_persist(result)`

Optional — only runs if Supabase is configured. Writes the optimisation result to an `optimisation_runs` table. Currently **not called** from `run_optimisation()` (would need to be added). Fails silently.

### `_safe_json(obj)`

Serialises any object to a JSON string with `json.dumps(..., default=str)`. Used by `_maybe_persist`.

---

## Concurrency Pipeline Diagram

All tasks are submitted to `asyncio.gather()` and offloaded to the 20-worker thread pool via `asyncio.to_thread()`. The diagram below shows the full tree for an example config (3 companies, 3 stores each, 3 ingredients = 27 total tasks).

```
POST /optimise  (single HTTP request)
│
├── Phase 1: Sequential setup
│   ├── _resolve_dish_terms("spaghetti bolognese")
│   │   └── returns: ("Spaghetti Bolognese", ["beef mince", "spaghetti", "canned tomatoes"])
│   └── geocode("Auckland CBD")  [Nominatim, ~1-3s]
│       └── returns: (lat=-36.8485, lon=174.7633)
│
├── Phase 2: Build tasks (sequential, instant)
│   └── for company in [PaknSave, NewWorld, Woolworths]:
│       ├── find_nearby_stores(lat, lon, radius_km=5)
│       │   └── returns: [StoreA, StoreB, StoreC]  (capped to 3)
│       └── for store in [StoreA, StoreB, StoreC]:
│           └── for ingredient in ["beef mince", "spaghetti", "canned tomatoes"]:
│               └── tasks.append(_fetch_ingredient(...))
│
├── Phase 3: asyncio.gather()  ← ALL 27 TASKS SUBMITTED TO THREAD POOL
│   │   Each task calls asyncio.to_thread() → background thread pool (20 workers)
│   │   First 20 run immediately; remaining 7 queue and start as slots free up
│   │
│   ├── PaknSave (9 tasks)
│   │   ├── PS-Newmarket
│   │   │   ├── to_thread(_fetch_foodstuffs_sync, "PaknSave", "ps-nzm", "beef mince")     ─┐
│   │   │   ├── to_thread(_fetch_foodstuffs_sync, "PaknSave", "ps-nzm", "spaghetti")      ─┤── parallel
│   │   │   └── to_thread(_fetch_foodstuffs_sync, "PaknSave", "ps-nzm", "canned tomatoes") ─┘
│   │   ├── PS-SylviaPark
│   │   │   ├── to_thread(_fetch_foodstuffs_sync, "PaknSave", "ps-sp",  "beef mince")     ─┐
│   │   │   ├── to_thread(_fetch_foodstuffs_sync, "PaknSave", "ps-sp",  "spaghetti")      ─┤── parallel
│   │   │   └── to_thread(_fetch_foodstuffs_sync, "PaknSave", "ps-sp",  "canned tomatoes") ─┘
│   │   └── PS-Downtown
│   │       ├── to_thread(_fetch_foodstuffs_sync, "PaknSave", "ps-dt",  "beef mince")     ─┐
│   │       ├── to_thread(_fetch_foodstuffs_sync, "PaknSave", "ps-dt",  "spaghetti")      ─┤── parallel
│   │       └── to_thread(_fetch_foodstuffs_sync, "PaknSave", "ps-dt",  "canned tomatoes") ─┘
│   │
│   ├── NewWorld (9 tasks)
│   │   ├── NW-Newmarket
│   │   │   ├── to_thread(_fetch_foodstuffs_sync, "NewWorld", "nw-nzm", "beef mince")     ─┐
│   │   │   ├── to_thread(_fetch_foodstuffs_sync, "NewWorld", "nw-nzm", "spaghetti")      ─┤── parallel
│   │   │   └── to_thread(_fetch_foodstuffs_sync, "NewWorld", "nw-nzm", "canned tomatoes") ─┘
│   │   ├── NW-Ponsonby
│   │   │   ├── to_thread(_fetch_foodstuffs_sync, "NewWorld", "nw-pon", "beef mince")     ─┐
│   │   │   ├── to_thread(_fetch_foodstuffs_sync, "NewWorld", "nw-pon", "spaghetti")      ─┤── parallel
│   │   │   └── to_thread(_fetch_foodstuffs_sync, "NewWorld", "nw-pon", "canned tomatoes") ─┘
│   │   └── NW-Glenfield
│   │       ├── to_thread(_fetch_foodstuffs_sync, "NewWorld", "nw-glf", "beef mince")     ─┐
│   │       ├── to_thread(_fetch_foodstuffs_sync, "NewWorld", "nw-glf", "spaghetti")      ─┤── parallel
│   │       └── to_thread(_fetch_foodstuffs_sync, "NewWorld", "nw-glf", "canned tomatoes") ─┘
│   │
│   └── Woolworths (9 tasks)
│       ├── WW-Greymouth
│       │   ├── to_thread(_fetch_woolworths_sync, "ww-gry", "beef mince")     ─┐
│       │   ├── to_thread(_fetch_woolworths_sync, "ww-gry", "spaghetti")      ─┤── parallel
│       │   └── to_thread(_fetch_woolworths_sync, "ww-gry", "canned tomatoes") ─┘
│       ├── WW-Glenfield
│       │   ├── to_thread(_fetch_woolworths_sync, "ww-glf", "beef mince")     ─┐
│       │   ├── to_thread(_fetch_woolworths_sync, "ww-glf", "spaghetti")      ─┤── parallel
│       │   └── to_thread(_fetch_woolworths_sync, "ww-glf", "canned tomatoes") ─┘
│       └── WW-StLukes
│           ├── to_thread(_fetch_woolworths_sync, "ww-stl", "beef mince")     ─┐
│           ├── to_thread(_fetch_woolworths_sync, "ww-stl", "spaghetti")      ─┤── parallel
│           └── to_thread(_fetch_woolworths_sync, "ww-stl", "canned tomatoes") ─┘
│
│   All 27 tasks return Optional[dict] or Exception
│   Thread pool runs up to 20 at once; rest queue and start as slots free up
│
└── Phase 4: Consolidate (sequential)
    ├── Group results by store, sum costs
    ├── Sort stores by total_cost ascending
    └── Return OptimisationResult
```

### What each sync helper does internally

```
_fetch_woolworths_sync(store_id, ingredient)     [plain def, runs on thread]
├── session = woolworths_api.create_session()     ← fresh Session (cookie jar)
├── woolworths_api.set_store_context(session, sid) ← inject cw-lrkswrdjp cookie
├── woolworths_api.search_products(session, ingredient)
├── pick cheapest by salePrice
├── session.close()
└── return {"price": float (dollars), "unit_price": str, "pack_info": str}


_fetch_foodstuffs_sync(company, store_id, ingredient)   [plain def, runs on thread]
├── api = PaknSaveEdgeAPI() or NewWorldEdgeAPI()         ← new instance each time
├── api.authenticate()                                   ← JWT token (if expired)
├── api.search_ingredient(store_id, ingredient)          ← two-pass Algolia pipeline
├── pick cheapest by singlePrice.price
└── return {"price": float (cents), "unit_price": str, "pack_info": str}
```

### Timing breakdown (typical)

| Phase | Time | Parallelised? |
|---|---|---|
| Dish resolution | <1s | No |
| Geocoding (Nominatim) | 1-3s | No (rate limit 1 req/sec) |
| Store lookup (×3 brands) | <0.1s | No (local CSV reads, fast) |
| API searches (20-thread pool) | ~15-25s | **Yes** — runs in batches of 20 via `asyncio.to_thread` |
| Consolidation | <1s | No |
| **Total** | **~17-30s** | — |

Without thread offloading, all tasks run sequentially. With 20 threads, wall time ≈ `ceil(total_tasks / 20) × ~5s`. For 27 tasks: `ceil(27/20) × ~5s ≈ 10-15s`. For 63 tasks: `ceil(63/20) × ~5s ≈ 20-25s`.

---

## Data Flow Summary

```
User Input                    API Processing                     Output
─────────────                 ──────────────                     ──────
dish: "spaghetti bolognese"   → dishes.json lookup               OptimisationResult
address: "Auckland CBD"       → Nominatim geocode                  ├─ dish (display name)
distance_km: 5                → find nearby stores ×3 brands       ├─ cheapest_store
max_stores: 3                 → to_thread() searches (batches of 20) ├─ cheapest_total
companies: [all]              → pick cheapest per store             ├─ store_breakdown
                             → sort stores by total cost           ├─ ingredient_results
                                                                    └─ timestamp
```

Nothing is persisted by default. The optional `_maybe_persist` function (not wired in) would write to Supabase.
