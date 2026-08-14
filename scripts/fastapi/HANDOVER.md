# FastAPI Integration Plan — NZ Meal Cost Optimiser

## Goal
A FastAPI backend that finds the cheapest supermarket for a dish by searching **all 3 companies concurrently** across nearby stores, with a basic frontend dashboard.

## Key Design Decisions

### 1. TRUE Parallelization — No Queueing
**We do NOT need queueing** because:
- **Each `requests.Session()` has its own cookie jar** — Woolworths sessions are isolated automatically
- **Nominatim geocoding runs once** per request (not during parallel searches)  
- **All 42-63 searches run concurrently** (3 companies × 3 stores × ~7 ingredients)

```python
# Safe — each gets its own session object with separate cookie jars:
session1 = woolworths_api.create_session()  # cookie jar A
set_store_context(session1, store1)        # dm-Pickup,f-123 in jar A

session2 = woolworths_api.create_session()  # cookie jar B
set_store_context(session2, store2)        # dm-Pickup,f-456 in jar B
# These run in parallel with zero conflicts
```

### 2. Session Isolation Pattern
```python
async def _fetch_ingredient(company, store_id, ingredient):
    if company == "Woolworths":
        session = woolworths_api.create_session()  # Fresh session per store
        woolworths_api.set_store_context(session, store_id)
        products = woolworths_api.search_products(session, ingredient)
        session.close()                             # Explicitly closed
    else:  # Foodstuffs (Pak'nSave/NewWorld)
        api = CompanyAPI()                          # JWT auth, reusable
        products = api.search_ingredient(store_id, ingredient)
```

### 3. Supabase Persistence — Optional
- Only for storing historical runs (not required for core flow)
- API works fully without it; writes are silently skipped if misconfigured

## Performance Results

**First full test: 42 concurrent searches completed in 61 seconds**
- Sequential would take ~10 minutes
- Geocoding: 3s (Nominatim rate limited)
- 42 API searches: ~56s (parallelized)
- Result: `$17.10 at New World Newmarket` (spaghetti bolognese, Auckland CBD)

## File Structure

```
scripts/fastapi/
├── main.py              # FastAPI app + async /optimise endpoint + frontend serving
├── core/
│   ├── __init__.py
│   ├── config.py        # Optional SUPABASE_* settings
│   └── paths.py         # sys.path bootstrap for legacy modules
├── static/
│   └── index.html       # Frontend dashboard (Vue-style plain HTML/JS)
├── .env                 # (optional) SUPABASE_URL + SUPABASE_SECRET_KEY
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
| Pak'nSave stores | Yes | JWT token, URL-path store IDs |
| New World stores | Yes | JWT token, URL-path store IDs |
| Woolworths stores | Yes | Fresh `requests.Session()` per store |
| All 3 companies | Yes | Independent API clients |
| Ingredients (per store) | Yes | No shared state between calls |

## What Was Removed (and Why)

- **`workers/` folder** — Queueing system for serialized processing. Removed because sessions are isolated naturally via `requests.Session()` per call.
- **`services/supabase_client.py`** — Supabase write client. Removed because persistence is optional and can be added to `main.py` later.
- **`seed_phase1.py`, `schema_phase1.sql`** — Database seeding scripts. Removed because we're starting with local storage; can add later if Supabase is used.
- **`models/` folder** — Pydantic request/response models. Consolidated into `main.py` for simplicity.
- **`routes/` folder** — Separate route files. Consolidated to single `main.py` since we only have 2 endpoints (`/optimise`, `/health`).

## Next Steps
1. ✅ Core FastAPI app with concurrent `/optimise` endpoint — **done**
2. ✅ Basic frontend at `http://127.0.0.1:8000/` — **done**
3. Deploy to **Google Cloud Run** (serverless containers):
   ```dockerfile
   # Add Dockerfile for easy deployment
   ```
4. Optional: Add Supabase persistence + historical price tracking
5. Optional: Add LLM endpoints for dish generation/filtering

## Google Cloud Run Deployment
- Create `Dockerfile` in `scripts/fastapi/`
- Deploy with: `gcloud run deploy --source .`
- Serverless scaling handles concurrency; each request is independent