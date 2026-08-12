# FastAPI Integration Plan — NZ Meal Cost Optimizer

## Goal
Create a dashboard-connected backend that lets users query supermarket ingredient prices on demand, call LLMs to build/filter dishes, validate results, and manage changes. Use Supabase (PostgreSQL) for persistent storage. Keep existing CLI/notebook scripts intact; FastAPI is a thin wrapper + queued worker layer.

## Context — Files to Read / Understand Before Production
- `AGENTS.md` (full project layout, conventions, gotchas)
- `scripts/combined/optimizer_utils.py` (core pipeline: `optimise()`, `append_rows()`, `build_edge_row()`, `build_mobile_row()`, `analyze_results()`)
- `scripts/woolworths/woolworths_api.py` (cookie injection `cw-lrkswrdjp`, session isolation requirement)
- `scripts/newworld/newworld_api.py` (`NewWorldEdgeAPI` JWT auth, two-pass pipeline; `NewWorldMobileAPI` token auth)
- `scripts/paknsave/paknsave_api.py` (`PaknSaveEdgeAPI` / `PaknSaveMobileAPI`)
- `scripts/llms/llm_utils.py` (`parse_and_validate`, quantity scaling, dish parsing)
- `scripts/llms/llm_client.py` (`Mistral` client, rate limits, retries)
- `scripts/llms/llm_validate.py` (post-run `is_valid` writer)
- `scripts/llms/llm_interactive.py` (interactive CLI flow reference)
- `data/dishes.json` (Top ~5 dishes - curated dishes structure)
- `data/full_results.csv` (Top ~10 rows - current result storage — append-only with `pk_hash`)
- `data/newworld_stores.csv`, `data/paknsave_stores.csv`, `data/woolworths_store_data.json` (store data sources)

## User Confirmed Decisions
- Persistence: **Supabase cloud** (not local files only)
- Blocking/queued approach: **Happy for queued/sequential processes**; async clients only if data-independent (current scripts are blocking, so queued/sequential preferred)
- Dashboard: **API only for now** (FastAPI `/docs` auto docs); frontend deferred
- LLM pipeline steps: **Generate dishes, Filter ingredients, Post-run validate, Quantity scaling**; will expand LLM section once backend + Supabase is formalized

## Challenges & Watch-Outs
1. **Cookie / session isolation**: `woolworths_api.py` requires fresh `requests.Session` per store (`cw-lrkswrdjp` cookie). Reusing sessions causes `Set-Cookie` overwrite and pricing errors. `NewWorldEdgeAPI` holds JWT (`fs-user-token`) per instance.
2. **Synchronous blocking clients**: `requests`, `cloudscraper`, `requests.Session` are blocking. Concurrent FastAPI endpoints without isolation = cookie/token collisions and server freeze.
3. **Supabase migration**: `full_results.csv` is append-only with `pk_hash` dedup; Supabase `results` table must enforce `UNIQUE(pk_hash)` and handle concurrent writes safely (use queued worker with single writer, or `ON CONFLICT`).
4. **Store identity**: Edge/mobile APIs use UUID `store_id`; Woolworths uses `extra1` (fulfilmentStoreId, numeric string). `stores.store_id` is TEXT to accommodate both directly (no UUID5 encoding). The Woolworths optimizer uses `extra1` directly as the `cw-lrkswrdjp` cookie's `f-{fulfilmentStoreId}` value.
5. **Geocoding rate limit**: `optimizer_utils.geocode()` uses Nominatim at 1 req/sec. Must not be called concurrently without delay.
6. **LLM rate limits**: `llm_client.py` has rate limiting and retries. Concurrent LLM calls need queuing.
7. **Script preservation**: Existing CLI/notebook scripts (`newworld_optimizer_edge.py`, etc.) must remain functional. FastAPI does not replace them; it wraps them.

## Proposed Architecture
```
Dashboard (deferred) → FastAPI (Uvicorn) → Supabase (PostgreSQL)
                                  ↓
                           Queued Worker (Celery / Queue + worker thread)
                                  ↓
                           Fresh API session per job → Optimizer scripts
                                  ↓
                           LLM pipeline (generate / filter / validate / scale)
                                  ↓
                           Writes results → Supabase (results, jobs, dishes)
```

## Implementation Phases (Sequential — Complete Before Next)

### Phase 1: Supabase Storage Setup
- [ ] Create Supabase project.
- [ ] Design and apply schema (see Schema section below).
- [ ] Write seed script to migrate existing store CSVs (`newworld_stores.csv`, `paknsave_stores.csv`, `woolworths_store_data.json`) into `stores` table.
- [ ] Write seed script to migrate `data/dishes.json` into `dishes` table.
- [ ] Define `results` table with `UNIQUE(pk_hash)` constraint.
- [ ] Define `jobs` table for queued processing tracking.
- [ ] Update `optimizer_utils.py` (or create wrapper) to write to Supabase instead of CSV, or keep CSV as local backup.
- [ ] Verify `store_id` normalization across brands.

### Phase 2: Queued / Blocking Worker Design  ✅ (in progress — implemented below)
- [x] **Queuing mechanism chosen**: Python `queue.Queue` + a single background daemon **worker thread** (stdlib only, no Redis/Celery broker). Rationale: simplest, most widely understood, zero external deps; a *single* worker thread trivially serialises every hazard identified in §Challenges (cookie/token isolation, Nominatim 1 req/sec, LLM rate limits). Horizontal scaling (Celery + Redis) deferred as a future swap-in, not needed now.
- [x] **File**: `scripts/fastapi/workers/optimizer_worker.py` — drains a `queue.Queue[Job]`, dispatches by brand, creates a fresh API session/client per store, writes rows via the chosen `ResultWriter`, runs Phase-2 `analyze_results`, updates `jobs.status` + `result_ref`.
- [x] **Cookie isolation per job**: each job instantiates its own `NewWorldEdgeAPI()` / `PaknSaveEdgeAPI()` (JWT/Token held per-instance) and the Woolworths path calls `create_session()` **inside** the per-store loop — never shared across jobs or stores. Single-threaded worker makes this safe by construction.
- [x] **Geocoding rate limit respected**: worker is single-threaded + calls the existing `geocode()` (which already sleeps 1.1s). No coordination layer needed.
- [x] **Blocking worker does not block FastAPI endpoint threads**: FastAPI endpoints only *enqueue* (non-blocking `queue.Queue.put`) and *read* `jobs` rows; all blocking API/LLM work happens in the dedicated worker thread. Endpoints return immediately with a `job_id`.
- [x] **Dual-mode writer seam**: `optimizer_utils.append_rows` is swapped per-job for the chosen `ResultWriter.write_rows` (in a `try/finally`, restored afterwards) so **existing CLI/notebook scripts remain 100% untouched**. Phase-2 comparison calls the shared `analyze_results(df, …)` on rows fetched from the writer (not the CSV-reading `optimise`), so both Supabase and local-temp modes read correctly.
- [x] **Store-id normalization**: `workers/store_registry.py` builds `pickup_address_id → fulfilmentStoreId` for Woolworths (from Supabase `stores` table or fallback `data/woolworths_store_data.json` + CSVs); the writer normalizes Woolworths `results.store_id` to `extra1` before insert (Foodstuffs passed through). See §Store-ID semantics.

### Phase 3: FastAPI Skeleton
- [ ] Create `scripts/fastapi/main.py` (FastAPI app instance).
- [ ] Create `scripts/fastapi/models/` — Pydantic request/response models (`OptimizerRequest`, `DishGenerateRequest`, `IngredientFilterRequest`, `JobStatusResponse`).
- [ ] Create `scripts/fastapi/routes/`:
  - `jobs.py` (`POST /jobs/optimize`, `GET /jobs/{job_id}`)
  - `dishes.py` (`POST /dishes/generate`, `GET /dishes`)
  - `ingredients.py` (`POST /ingredients/filter`, `POST /ingredients/scale`)
  - `results.py` (`GET /results` with filters)
  - `stores.py` (`GET /stores/nearby`)
  - `validate.py` (`POST /results/validate` — batch `is_valid` update)
- [ ] Configure CORS, middleware if needed.
- [ ] Add environment config (`.env`) for Supabase URL + keys (`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`).
- [ ] Ensure `fastapi[standard]` (Uvicorn, Pydantic, Starlette) is in `requirements.txt` without breaking existing dependencies.

### Phase 4: LLM Integration Endpoints
- [ ] Wrap `llm_utils.parse_and_validate()` → `POST /ingredients/filter`
- [ ] Wrap `llm_client` + dish generation → `POST /dishes/generate`
- [ ] Wrap `llm_validate.py` batch logic → `POST /results/validate`
- [ ] Wrap quantity scaling (`parse_optimizer_columns`) → `POST /ingredients/scale`
- [ ] Ensure rate limits (`llm_client`) are respected; queued model handles this naturally (one LLM call at a time per worker, or batch with delays).

### Phase 5: Supabase Integration (Read/Write)
- [x] Add `supabase-py` dependency.  ✅
- [x] Create `scripts/fastapi/services/supabase_client.py` (singleton connection manager).  ✅
- [x] Optimizer wrapper writes to Supabase via the dual-mode `ResultWriter` (per-job `append_rows` seam → `ON CONFLICT (pk_hash) DO NOTHING`). CSV preserved as local fallback.  ✅
- [ ] Create query endpoints (`GET /results`) using Supabase `.table().select()`.  ⬜ (Phase 3)
- [ ] `jobs` table read/update from worker — `jobs.status` set to `queued`/`running`/`done`/`failed` + `result_ref`/`error_message` from the worker.  ✅ (Phase 2)

### Phase 6: Testing & Validation
- [ ] Unit test FastAPI endpoints with `TestClient`.
- [ ] Verify cookie isolation: run concurrent `POST /jobs/optimize` and confirm no price contamination between stores.
- [ ] Verify Supabase `UNIQUE(pk_hash)` prevents duplicates.
- [ ] Test LLM endpoints with mock/dummy inputs.
- [ ] Confirm existing CLI (`paknsave_optimizer_edge.py`, etc.) still works independently.

## Detailed Schema (Supabase / PostgreSQL)
 
### `stores`
- `store_id` TEXT PRIMARY KEY (UUID strings for Foodstuffs; numeric string for Woolworths `extra1`/fulfilmentStoreId — canonical across `stores` + cookie + normalized `results.store_id`)
- `brand` TEXT (`PaknSave` | `NewWorld` | `Woolworths`)
- `name` TEXT
- `address` TEXT
- `lat` FLOAT
- `lon` FLOAT
- `added_at` TIMESTAMP DEFAULT now()
- `pickup_address_id` TEXT NULL — Woolworths `extra2`/pickupAddressId (NULL for Foodstuffs). Lets the worker map `results.store_id` (normalized to `extra1`) back to the pickupAddressId needed for `set_store_context()`. Populated by `seed_phase1.py` and the Phase 2 `StoreRegistry`.

### `dishes`
- `dish_name` TEXT PRIMARY KEY
- `portion` INT DEFAULT 4
- `ingredients` JSONB (array of `{search_term, quantity, unit, approx_quantity?, approx_unit?}`)
- `added_at` TIMESTAMP DEFAULT now()

### `results`
- `company` TEXT
- `store` TEXT (store display name — mirror of the `store` column in `full_results.csv`, added so `results` parity with the CSV schema is 1:1)
- `store_id` TEXT, indexed `store_id_idx` (see "Store-ID semantics" below — NOT a hard `REFERENCES` FK to avoid insert failures from the Woolworths extra1/extra2 mismatch; joins to `stores` rely on normalized store_id, see §Store-ID semantics)
- `search_ingredient` TEXT
- `returned_ingredient` TEXT
- `price` NUMERIC(10,2)
- `quantity` NUMERIC
- `measurement_unit` TEXT
- `per_unit_quantity` TEXT
- `per_unit_price` NUMERIC(10,2)
- `is_sale` BOOL DEFAULT FALSE
- `sku` TEXT
- `department` TEXT
- `sub_department` TEXT
- `datetime_created` TIMESTAMP
- `date_created` DATE
- `pk_hash` TEXT UNIQUE
- `is_valid` BOOL DEFAULT NULL
- `added_at` TIMESTAMP DEFAULT now()

#### Store-ID semantics (cross-brand)
- **Foodstuffs (Pak'nSave / New World)**: `store_id` is the UUID emitted by the Edge/Mobile API and used verbatim in the API URL path. It is the same value in `stores.store_id` and `results.store_id` → joins hold, `pk_hash = SHA256(store_id|sku|date_created)` is consistent.
- **Woolworths**: two distinct IDs exist in `data/woolworths_store_data.json`:
  - `extra1` = `fulfilmentStoreId` (numeric string) — this is the canonical `stores.store_id` (seeded by `seed_phase1.py`) AND the value baked into the `cw-lrkswrdjp` cookie (`dm-Pickup,f-{fulfilmentStoreId}`).
  - `extra2` = `pickupAddressId` (numeric string) — the key returned by `woolworths_api.get_nearby_stores()` and passed to `set_store_context()` for cookie injection.
  - The legacy CLI (`optimizer_utils.build_woolworths_row`) stores **pickupAddressId** as `results.store_id`. For Supabase this would NOT join to `stores.store_id` (= extra1) and would break a hard FK. **Resolution (Phase 2 worker)**: the worker's `StoreRegistry` supplies a `pickup_address_id → fulfilmentStoreId` map; the writer **normalizes** Woolworths `results.store_id` to `fulfilmentStoreId` (extra1) before insert, so results join to `stores` and the cookie path (`set_store_context(pid)`) is unchanged (it still needs pickupAddressId). Foodstuffs store_id is passed through unchanged. The `pk_hash` is computed upstream in `build_*_row` and is NOT altered by normalization. **Recommendation**: do NOT add a hard `REFERENCES stores(store_id)` FK on `results`; use a plain indexed `store_id` so a missing/legacy store never aborts a worker job. (Deferred to Phase 5 to optionally backfill + tighten to FK once all store_ids are normalized.)

  - The legacy CLI (`optimizer_utils.build_woolworths_row`) stores **pickupAddressId** as `results.store_id`. For Supabase this would NOT join to `stores.store_id` (= extra1) and would break a hard FK. **Resolution (Phase 2 worker)**: the worker's `StoreRegistry` supplies a `pickup_address_id -> fulfilmentStoreId` map; the writer **normalizes** Woolworths `results.store_id` to `fulfilmentStoreId` (extra1) before insert, so results join to `stores` and the cookie path (`set_store_context(pid)`) is unchanged (it still needs pickupAddressId). Foodstuffs store_id is passed through unchanged. The `pk_hash` is computed upstream in `build_*_row` and is NOT altered by normalization. **Recommendation**: do NOT add a hard `REFERENCES stores(store_id)` FK on `results`; use a plain indexed `store_id` so a missing/legacy store never aborts a worker job. (Deferred to Phase 5 to optionally backfill + tighten to FK once all store_ids are normalized.)

### `jobs`
- `job_id` UUID PRIMARY KEY DEFAULT gen_random_uuid()
- `type` TEXT (`optimize` | `generate_dish` | `filter_ingredients` | `validate_results` | `scale_quantity`)
- `params` JSONB (request payload)
- `status` TEXT (`queued` | `running` | `done` | `failed`)
- `result_ref` TEXT (optional path/URL to result)
- `error_message` TEXT
- `created_at` TIMESTAMP DEFAULT now()
- `updated_at` TIMESTAMP DEFAULT now()

## File Structure (Target) — Do Not Create Until Confirmed)
```
scripts/fastapi/
├── main.py                  # FastAPI app instance + lifespan events
├── core/
│   ├── config.py             # Env vars, Supabase URL/key
│   └── dependencies.py       # Shared deps (Supabase client, auth if needed)
├── models/
│   ├── optimizer.py          # Pydantic request/response for optimizer
│   ├── dishes.py             # Dish generate/filter models
│   ├── ingredients.py        # Ingredient filter/scale models
│   ├── results.py            # Results query/validate models
│   └── jobs.py               # Job status/request models
├── routes/
│   ├── jobs.py
│   ├── dishes.py
│   ├── ingredients.py
│   ├── results.py
│   ├── stores.py
│   ├── validate.py
│   └── health.py
├── services/
│   ├── supabase_client.py    # Singleton Supabase connection
│   ├── optimizer_service.py  # Wrap optimizer_utils + queued writer
│   └── llm_service.py        # Wrap llm_client + llm_utils
├── workers/
│   ├── optimizer_worker.py   # Queued worker (Celery or Queue)
│   └── llm_worker.py         # LLM queued worker (optional)
└── HANDOVER.md               # This file (updated as progress is made)
```

## Things to Watch Out For (Reminders for Future Chats)
- **Plan mode constraint**: This file (`HANDOVER.md`) is the only file modified in this session. Source files (`optimizer_utils.py`, `woolworths_api.py`, etc.) must NOT be edited until user exits plan mode.
- **Cookie isolation**: Never reuse `requests.Session` across concurrent optimizer jobs. Always create new session inside worker.
- **Geocoding rate limit**: `geocode()` sleeps 1.1 sec. Multi-threaded workers will violate this unless coordinated.
- **LLM rate limits**: `llm_client.py` has retries and rate limits. Concurrent LLM endpoints must use queuing or sequential execution.
- **CSV backward compatibility**: Keep `full_results.csv` as backup until Supabase is fully verified. Dual-write is acceptable during transition.
- **Supabase auth**: If using `service_role` key, ensure it is not exposed in frontend/dashboard. Use `anon` or RLS policies if needed later.
- **Stretch goals deferred**: Real-time dashboard frontend, WebSockets for job updates, multi-tenant user accounts, automated price-change alerts, A/B testing optimizer strategies.

## Stretch Goals (Post-Production)
- [ ] Real-time dashboard frontend (React / Vue) connected to `/results` endpoint
- [ ] WebSocket or Server-Sent Events (`/ws/job/{job_id}`) for live job status updates
- [ ] User authentication (Supabase Auth) and multi-tenant isolation (`results` filtered by `user_id`)
- [ ] Scheduled automated optimization runs (cron / Supabase Edge Functions) that write daily results
- [ ] Price-change alert system (`new_result` vs `old_result` comparison triggers notification)
- [ ] Expand LLM pipeline: ingredient substitution suggestions, dietary filter integration (vegan/gluten-free), automatic unit price comparison optimization
- [ ] Containerize (`Docker`) and deploy to cloud (Render / Railway / FastAPI Cloud / GCP)

## Checklist / Progress Tracker
- [x] HANDOVER.md created (this file) — ✅
- [x] Plan mode acknowledged and respected — ✅
- [x] User confirmed Supabase + queued model + LLM steps + API-only dashboard — ✅
- [x] Phase 1: Supabase storage setup complete. Schema in `public` (tables: `stores`, `dishes`, `results`, `jobs` with `pgcrypto` extension). `.env` with `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`. `core/config.py` + `services/supabase_client.py` written. Seed script (`seed_phase1.py`) populated: **382 stores** (148 NW + 57 PS + 177 WW) + **21 dishes**. `store_id` is TEXT (UUIDs for Foodstuffs, numeric string for Woolworths `extra1`), directly usable in API cookie injection. 6 duplicate Woolworths entries deduped via `extra1` collision detection. — ✅
- [x] Phase 2: Queued worker architecture. `queue.Queue` + single background daemon thread (stdlib, no Redis). `workers/optimizer_worker.py` drains jobs, fresh API session per store, dual-mode `ResultWriter` (Supabase upsert vs local-temp CSV) via per-job `append_rows` seam (restored in `try/finally` → existing CLI untouched). `StoreRegistry` normalizes Woolworths `extra1`/`extra2` `store_id`s. Phase-2 `analyze_results` reused on writer-fetched rows. `jobs.status` lifecycle. — ✅
- [ ] Phase 3: FastAPI skeleton (`main.py`, `routes/`, `models/`) — ⬜ (minimal `main.py` + `routes/jobs` + `routes/health` + `models/jobs.py` will be created NOW to make Phase 2 runnable end-to-end; full route set deferred to Phase 3)
- [ ] Phase 4: LLM endpoints implemented — ⬜
- [x] Phase 5: Supabase read/write integration — read/query endpoints (`GET /results`) deferred to Phase 3; **write path + jobs lifecycle done in Phase 2**. — ✅ (write) / ⬜ (read endpoints)
- [ ] Phase 6: Testing + cookie isolation verification — ⬜
- [ ] Phase 7: Documentation (`README.md` update, endpoint docs) — ⬜

## Session End Notes
- Phase 1 complete and verified. Tables live, seeded, and queryable.
- Phase 2 DONE in this session: worker infra + dual-mode writer + minimal FastAPI surface to enqueue/query jobs. Queued model is `queue.Queue` + single daemon thread (no Redis). Celery alternative retained as a future swap-in.
- **Schema change applied**: `results.store` column added (2nd) for CSV parity; Woolworths store-id normalization (extra1 canonical) handled by worker `StoreRegistry` rather than a hard `REFERENCES` FK (avoids insert aborts on legacy pickupAddressId rows). `stores.pickup_address_id` column added for the reverse map.
- `.env` must have real keys for Supabase mode. With no/missing keys the app boots in local-only fallback (loads `data/*.csv` + `dishes.json`, writes to a session temp CSV).
- Next session: Phase 3 full route set (dishes/ingredients/results/stores/validate) + `GET /results` + Phase 6 testing (cookie isolation, pk_hash dedup).
- Existing CLI scripts (`paknsave_optimizer_edge.py`, `newworld_optimizer_mobile.py`, `woolworths_optimizer.py`, etc.) are **untouched** — the worker reaches them via the public `foodstuffs_optimizer_edge` / `foodstuffs_optimizer_mobile` / `woolworths_optimizer` (shared, in `optimizer_utils.py`) entry points and a per-job `append_rows` seam.

## One-Shot Prompt for Future Chat / Production Start
When a new chat begins or production is confirmed, provide this context:

```
Project: NZ Meal Cost Optimizer (OpenCode)
Mode: Exit plan mode; begin implementation.
Read first: AGENTS.md, scripts/fastapi/HANDOVER.md, scripts/combined/optimizer_utils.py, scripts/woolworths/woolworths_api.py, scripts/newworld/newworld_api.py, scripts/paknsave/paknsave_api.py, scripts/llms/llm_utils.py.
Goal: Implement FastAPI backend with Supabase persistence and queued/sequential optimizer/LLM workers. Keep CLI scripts intact.

Confirmed architecture: Supabase cloud DB (public schema); queued/sequential blocking worker (`queue.Queue` + single daemon thread, stdlib only — no Redis); FastAPI thin wrapper; LLM endpoints (generate, filter, validate, scale) queued behind the same single worker; dashboard deferred (API only).

Challenges to manage: Session/cookie isolation per job — each job gets its own API client instance (`NewWorldEdgeAPI`/`PaknSaveEdgeAPI` hold JWT/Token per-instance; Woolworths `create_session()` is called inside the per-store loop, never reused). Geocoding rate limits (1 req/sec — single-threaded worker respects this automatically). LLM rate limits (same single worker serializes them). `store_id` is TEXT across brands (UUID for Foodstuffs; Woolworths `extra1` canonical + `extra2` lookup). CSV backward compatibility: the worker uses a per-job `append_rows` seam → dual-mode writer, so existing CLI/notebook scripts are 100% untouched.

Target files (Phase 1+2): scripts/fastapi/core/, services/, workers/ (store_registry.py, result_writer.py, job_queue.py, optimizer_worker.py), main.py, models/jobs.py, routes/jobs.py, routes/health.py.

Target tables: stores (+ `pickup_address_id` for Woolies reverse-map), dishes, results (UNIQUE pk_hash, plain indexed `store_id` — not a hard FK, normalized to Woolies extra1 by the writer), jobs — all in `public` schema.

Phase 1 deliverables ready: schema_phase1.sql, seed_phase1.py, core/config.py, services/supabase_client.py, .env. Phase 2 deliverables ready: workers/ dual-mode writer + job queue + optimizer_worker; minimal main.py + routes/jobs + routes/health + models/jobs for an end-to-end runnable enqueue→worker→status cycle (Supabase mode or local-temp fallback when `.env` keys missing). Phase 3+ (full route set, LLM endpoints, GET /results, testing) follows next.
```

## References
- `AGENTS.md`
- `scripts/combined/optimizer_utils.py`
- `scripts/woolworths/woolworths_api.py`
- `scripts/newworld/newworld_api.py`
- `scripts/paknsave/paknsave_api.py`
- `scripts/llms/llm_utils.py`, `llm_client.py`, `llm_validate.py`, `llm_interactive.py`
- `data/dishes.json`
- FastAPI docs: https://fastapi.tiangolo.com/
- Supabase docs: https://supabase.com/docs

## Git Rules

- **Always pause and ask for confirmation** before running `git push` or `git pull`. Never auto-execute these commands.

## File permission rules

- **Never access an external directory unless invoking skills**. All files runs must be in the project directory. Always access files from the project root, and never read files from the user directory.