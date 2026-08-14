# FastAPI Integration Plan — NZ Meal Cost Optimiser

## Goal
A FastAPI backend that finds the cheapest supermarket for a dish by searching **all 3 companies concurrently** across nearby stores, with a basic frontend dashboard.

## Key Design Decisions

### 1. Parallelisation — Thread Pool
The underlying API libraries (`woolworths_api`, `newworld_api`, `paknsave_api`) are all **synchronous** — they use `requests.Session` for HTTP calls. If called directly from an `async def`, they block the event loop and all tasks run sequentially.

**Solution:** `asyncio.to_thread()` offloads each blocking search to a background thread from a 20-worker thread pool. The event loop stays free to schedule tasks. With 20 workers, up to 20 searches run in parallel — the rest queue and start as slots free up.

```python
# Before: blocking the event loop
async def _fetch_ingredient(company, store_id, ingredient):
    products = woolworths_api.search_products(...)  # blocks for 2-3s
    # Event loop frozen. Nothing else can run.

# After: offloaded to a background thread
async def _fetch_ingredient(company, store_id, ingredient):
    return await asyncio.to_thread(_fetch_woolworths_sync, store_id, ingredient)
    # Event loop free. Other tasks run in parallel.
```

### 2. Session Isolation Pattern
Each Woolworths search creates its own `requests.Session` (fresh cookie jar). Foodstuffs uses JWT tokens with URL-path store IDs — no session conflicts.

```python
def _fetch_woolworths_sync(store_id, ingredient):
    session = woolworths_api.create_session()  # fresh cookie jar
    woolworths_api.set_store_context(session, store_id)
    products = woolworths_api.search_products(session, ingredient)
    session.close()
```

### 3. Supabase Persistence — Optional
- `_maybe_persist()` is defined but **not wired in** to `run_optimisation()` — no writes happen at runtime
- Would need to be called explicitly (e.g. `await _maybe_persist(result)`) after returning the result to enable it

## Performance Results

**Example: spaghetti bolognese (7 ingredients) across 3 companies × 3 stores = 63 total searches**
- Geocoding: 1-3s (Nominatim rate limited, runs once)
- 63 API searches via 20-thread pool: tasks queue and run in batches of 20. Wall time ≈ `ceil(63/20) × ~5s ≈ 20-25s`
- Sequential equivalent: ~5+ minutes (63 × ~5s each)
- Total wall time: ~22-30s depending on dish, radius, and network

## File Structure

```
scripts/fastapi/
├── main.py              # FastAPI app + async /optimise endpoint + frontend serving
├── Dockerfile           # Container image for Google Cloud Run deployment
├── HANDOVER.md          # This file
├── core/
│   ├── __init__.py
│   ├── config.py        # Optional SUPABASE_* settings
│   └── paths.py         # sys.path bootstrap for legacy modules
├── static/
│   └── index.html       # Frontend dashboard (plain HTML/JS)
└── tmp/                 # Scratchpad folder (currently unused)
```

## Usage

```bash
# Start server
.venv\Scripts\uvicorn main:app --app-dir "scripts/fastapi" --port 8000

# Then open http://127.0.0.1:8000/ in browser
# Or use Swagger UI at http://127.0.0.1:8000/docs
```

**API call:**
```bash
curl -X POST "http://127.0.0.1:8000/optimise" \
  -H "Content-Type: application/json" \
  -d '{"dish": "spaghetti bolognese", "address": "Auckland CBD", "distance_km": 5.0}'
```

## Concurrency Model

| Component | Parallel | Isolation Method |
|-----------|----------|-----------------|
| Geocoding (Nominatim) | No (1 req/sec limit) | Single call before searches |
| Pak'nSave stores | Yes (20-thread pool) | JWT token, URL-path store IDs |
| New World stores | Yes (20-thread pool) | JWT token, URL-path store IDs |
| Woolworths stores | Yes (20-thread pool) | Fresh `requests.Session()` per store |
| All 3 companies | Yes | Independent API clients |
| Ingredients (per store) | Yes | No shared state between calls |

### Thread Pool Configuration

- **Pool size:** 20 workers (up from Python's default of 5)
- **Why 20:** With 20 workers, up to 20 searches run in parallel. The rest queue and start as slots free up. Wall time ≈ `ceil(total_tasks / 20) × ~5s`. Going higher (e.g. 63 workers) gives diminishing returns and uses more memory.
- **Set via:** `concurrent.futures.ThreadPoolExecutor(max_workers=20)` at module import, wired to the event loop at startup via `app.on_event("startup")`.

## What Was Removed (and Why)

- **`workers/` folder** — Queueing system for serialized processing. Removed because sessions are isolated naturally via `requests.Session()` per call.
- **`services/supabase_client.py`** — Supabase write client. Removed because persistence is optional and can be added to `main.py` later.
- **`seed_phase1.py`, `schema_phase1.sql`** — Database seeding scripts. Removed because we're starting with local storage; can add later if Supabase is used.
- **`models/` folder** — Pydantic request/response models. Consolidated into `main.py` for simplicity.
- **`routes/` folder** — Separate route files. Consolidated to single `main.py` since we only have 2 endpoints (`/optimise`, `/health`).

## Next Steps
1. ✅ Core FastAPI app with concurrent `/optimise` endpoint — **done**
2. ✅ Basic frontend at `http://127.0.0.1:8000/` — **done**
3. ✅ Dockerfile for Google Cloud Run deployment — **done**
4. ✅ Thread pool concurrency fix (asyncio.to_thread) — **done**
5. Optional: Wire in `_maybe_persist()` for Supabase historical price tracking
6. Optional: Add LLM endpoints for dish generation/filtering

## Google Cloud Run Deployment

The `Dockerfile` in `scripts/fastapi/` packages the app into a container. To deploy:

```bash
gcloud run deploy --source scripts/fastapi/
```

Serverless scaling handles concurrency; each request is independent.
