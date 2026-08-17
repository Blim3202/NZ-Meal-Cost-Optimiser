# OpenCode — NZ Meal Cost Optimiser

Finds the cheapest Pak'nSave, New World, or Woolworths for a given dish by comparing ingredient prices across nearby stores (within 5 km of a NZ address).

## Setup

```powershell
.venv\Scripts\Activate.ps1
pip install -e .          # editable install (src-layout package)
pip install -e ".[dev]"   # dev extras (pytest)
```

Runtime pins still live in `requirements.txt`. No path-bootstrap hacks — imports resolve via the installed `NZMealOptimiser` package.

## Project Layout

```
opencode/
├── data/
│   ├── newworld_stores.csv                     # 148 stores (Edge, default) or 150 (Mobile): store_id, name, address, city, region, lat, lon, banner, click_and_collect, delivery
│   ├── paknsave_stores.csv                     # 57 stores (Edge, default) / 60 (store_finder): store_id, name, address, city, region, lat, lon, banner, click_and_collect, delivery
│   ├── paknsave_stores.json                    # Same data as CSV, JSON format
│   ├── woolworths_stores.csv                   # Merged Woolworths store list with lat/lon (keyed on extra1 = fulfilmentStoreId)
│   ├── woolworths_store_choices.csv            # Woolworths pickup location IDs (from pickup-addresses API, legacy/detached)
│   ├── woolworths_store_choices.json           # Same data as CSV, JSON format
│   ├── woolworths_store_data.csv               # Woolworths store details from CDX API
│   ├── woolworths_store_data.json              # Store details with extra1 (fulfilmentStoreId), extra2 (pickupAddressId)
│   ├── woolworths_latest_results.csv           # Last optimiser output for woolworths optimiser
│   ├── paknsave_latest_results.csv             # Last Edge optimiser output
│   ├── paknsave_mobile_latest_results.csv      # Last Mobile optimiser output
│   ├── observed_category1_newworld.json        # Category1 values from New World Algolia index
│   ├── observed_category1_paknsave.json        # Category1 values from Pak'nSave Algolia index
│   ├── dishes.json                             # 21 hand-curated dishes with structured ingredients
│   └── full_results.csv                        # Append-only results with pk_hash deduplication + is_valid column
├── src/NZMealOptimiser/
│   ├── __init__.py                             # PROJECT_ROOT + DATA_DIR resolved once (shared path contract)
│   ├── pricing/
│   │   ├── optimiser_utils.py                  # **Cross-brand helpers**: foodstuffs_querier_edge/mobile, woolworths_querier, build_edge_row/mobile_row/build_woolworths_row, parsing, geocoding, haversine, DISHES, get_ingredients, _resolve_dish_terms, _resolve_dish_data, _build_quantity_map, optimise(), append_rows, _compute_pk_hash
│   │   ├── paknsave_api.py                     # **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities
│   │   ├── newworld_api.py                     # **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities
│   │   └── woolworths_api.py                   # Cookie-based API module: session, store context, product search
│   ├── llm/
│   │   ├── llm_client.py                       # Mistral API client: rate limiting, JSON retries, model aliases
│   │   └── llm_utils.py                        # Ingredient resolution (curated JSON → LLM), dish parsing/validation, quantity scaling
│   └── web/
│       ├── main.py                             # FastAPI app: /optimise endpoint, /app (Vue) + /dishes, thread pool
│       ├── config.py                           # Supabase settings loaded from .env
│       ├── static/                             # index_old.html + generated Vue build (served at / and /app)
│       └── frontend/                           # Vue CLI dashboard source (npm run build → static/vue/)
├── tools/
│   ├── paknsave/                               # paknsave_setup.py, paknsave_optimiser_edge.py, paknsave_optimiser_mobile.py, paknsave_search_demo_*.py
│   ├── newworld/                               # newworld_setup.py, newworld_optimiser_edge.py, newworld_optimiser_mobile.py, newworld_search_demo_*.py
│   ├── woolworths/                             # woolworths_setup.py, woolworths_optimiser.py, woolworths_search_demo.py
│   ├── llm/                                    # llm_interactive.py, llm_validate.py
│   └── combined/                               # initialize_full_results.py
├── tests/                                      # test suites + fixtures per brand (paknsave/, newworld/, woolworths/, combined/)
├── exploration/                                # per-brand exploration scripts (paknsave/, newworld/, woolworths/, llm/)
├── docs/
│   ├── migration_plan.md                       # This migration handoff
│   ├── project/                                # decision.md, design.md, logs.md
│   └── technical/                              # PaknSave_API.md, NewWorld_API.md, Woolworths_API.md, LLM_Pipeline.md, FastAPI.md
├── unsure/
│   └── paths.py                                # Retired path bootstrap (kept only for history; no longer imported)
├── AGENTS.md                                   # This file
├── Dockerfile                                  # Container image for Google Cloud Run (repo root)
├── pyproject.toml                              # src-layout package metadata + deps
├── requirements.txt                            # Pinned dependencies
└── README.md                                   # Project readme
```

## File Contents

| File | Purpose |
|---|---|
| `docs/technical/PaknSave_API.md` | Foodstuffs Pak'nSave API docs — primary reference for shared Foodstuffs mobile API + Edge API structure; New World references this for common content |
| `docs/technical/NewWorld_API.md` | Foodstuffs New World API docs — shared structure referenced from PaknSave_API.md; New World-specific Edge API, dishes, store data sources |
| `docs/technical/Woolworths_API.md` | Full /api/v1 endpoint documentation |
| `docs/technical/LLM_Pipeline.md` | LLM ingredient generation, post-run validation, and quantity scaling pipeline |
| `docs/technical/FastAPI.md` | FastAPI web app architecture (endpoints, thread pool, scaling) |
| `docs/project/decision.md` | Key decisions and rationale (src-layout restructure = #40) |
| `docs/project/design.md` | Technical design (API, auth, pipeline) |
| `docs/project/logs.md` | Major errors and resolutions (src-layout restructure = #64) |
| `src/NZMealOptimiser/__init__.py` | Resolves `PROJECT_ROOT` and `DATA_DIR = PROJECT_ROOT / "data"` once for the whole package |
| `src/NZMealOptimiser/pricing/optimiser_utils.py` | **Cross-brand helpers**: foodstuffs_querier_edge/mobile, woolworths_querier, build_edge_row/mobile_row/build_woolworths_row, parsing, geocoding, haversine, DISHES, get_ingredients, _resolve_dish_terms, _resolve_dish_data, _build_quantity_map, optimise(), append_rows, _compute_pk_hash |
| `src/NZMealOptimiser/pricing/paknsave_api.py` | **Unified Pak'nSave API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities |
| `src/NZMealOptimiser/pricing/newworld_api.py` | **Unified New World API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities |
| `src/NZMealOptimiser/pricing/woolworths_api.py` | Cookie-based Woolworths API module. Session, store context, product search. Constructs `cw-lrkswrdjp` cookie from `extra1` in store data. No Playwright needed at runtime. |
| `src/NZMealOptimiser/llm/llm_client.py` | Mistral API client: model aliases (small/medium/large), rate limiting, JSON parsing with retries. |
| `src/NZMealOptimiser/llm/llm_utils.py` | Ingredient resolution (curated `dishes.json` → LLM → fallback), dish parsing/validation (`parse_and_validate`), and quantity scaling (`parse_optimiser_columns` with `approx_quantity`/`approx_unit` fallback for non-standard units). |
| `src/NZMealOptimiser/web/main.py` | FastAPI app + async `/optimise` endpoint + frontend serving. Runs via `uvicorn NZMealOptimiser.web.main:app`. |
| `src/NZMealOptimiser/web/frontend/` | Vue CLI dashboard source. Run `npm install` then `npm run build`; output is written to `src/NZMealOptimiser/web/static/vue/`. |
| `src/NZMealOptimiser/web/static/index_old.html` | Original vanilla dashboard, still served at `/`. |
| `src/NZMealOptimiser/web/static/vue/` | Generated Vue dashboard assets, served at `/app`; do not edit generated files directly. |
| `tools/paknsave/paknsave_setup.py` | **Unified store builder**: Edge (57 stores) + Mobile (60 stores) + store_finder (60 stores, paknsave only). Callable module + CLI with `source` param. |
| `tools/paknsave/paknsave_optimiser_edge.py` | **Edge API optimiser**: CLI with geocoding, 5km radius, two-pass search, unit-price selection. Thin wrapper over shared `foodstuffs_querier_edge` in `optimiser_utils.py`. |
| `tools/paknsave/paknsave_optimiser_mobile.py` | **Mobile API optimiser**: CLI with geocoding, 5km radius, single-pass search, unit-price selection. Thin wrapper over shared `foodstuffs_querier_mobile` in `optimiser_utils.py`. |
| `tools/newworld/newworld_setup.py` | **Unified store builder**: Edge API (148 stores), Mobile API (150 stores). Callable module + CLI with `source` param. Mirrors paknsave_setup.py structure. |
| `tools/newworld/newworld_optimiser_edge.py` | **Edge API optimiser**: CLI with geocoding, 5km radius, two-pass search, unit-price selection. Thin wrapper over shared `foodstuffs_querier_edge` in `optimiser_utils.py`. |
| `tools/newworld/newworld_optimiser_mobile.py` | **Mobile API optimiser**: CLI with geocoding, 5km radius, single-pass search, unit-price selection. Thin wrapper over shared `foodstuffs_querier_mobile` in `optimiser_utils.py`. |
| `tools/woolworths/woolworths_setup.py` | **Unified store pipeline**: fetch choices (legacy/detached), fetch data from CDX, build woolworths_stores.csv keyed on extra1. |
| `tools/woolworths/woolworths_optimiser.py` | **Thin CLI**: Step 1 query via shared `woolworths_querier` in `optimiser_utils.py`, then Step 2 `optimise()`. `--requery`/`--distance` flags, 5km default. |
| `tools/combined/initialize_full_results.py` | Creates data/full_results.csv with 18-column schema (17 + is_valid) + pk_hash for deduplication |
| `tools/llm/llm_validate.py` | Post-run validator: batches rows through `ministral-3b-2512`, writes `is_valid` back to `data/full_results.csv`. Skips already-validated rows. |
| `tools/llm/llm_interactive.py` | Interactive CLI: Step 1 inputs → Step 2 resolve ingredients → Step 3 review → Step 4 query optimisers → Step 5 optimise → Step 6 scaling (enriches CSV rows with `ingredient_approx_*` fields). |
| `data/woolworths_store_data.json` | Store details with `extra1` (=fulfilmentStoreId) and `extra2` (=pickupAddressId) |
| `requirements.txt` | Pinned deps. Core: `cloudscraper`, `requests`, `pandas`, `numpy`, `beautifulsoup4`, `playwright`, `jupyterlab`. |

## Key Gotchas

### Pak'nSave
- Guest API token expires after 30 min — auto-refreshed by the `PaknSaveAPI` class.
- Prices from the Pak'nSave API are in **cents** — divide by 100 for dollars.
- `PaknSaveAPI.get_stores()` returns `{"stores": [...]}`, not a bare list.
- Nominatim geocoding rate limit: 1 req/sec.
- **Edge API two-pass pipeline**: Uses website JWT (`fs-user-token` cookie) for auth — works.
- **Edge API pet food filtering**: Filter by `category1` to exclude `{"Dog", "Cat", "Pet"}` categories in Pass 1.
- **store_finder source**: Only valid for Pak'nSave (New World has no `contentstackStores` in `__NEXT_DATA__`).

### New World
- Uses the same Foodstuffs mobile API as Pak'nSave with `banner: "MNW"` and `User-Agent: NewWorldApp/4.32.0`. API client: `src/NZMealOptimiser/pricing/newworld_api.py`. Cross-brand helpers (parsing, geocoding, optimisers) live in `src/NZMealOptimiser/pricing/optimiser_utils.py`.
- Prices from the New World API are in **cents** — divide by 100 for dollars.
- All sources (Edge 148 / Mobile 150) provide coordinates and store IDs — no Nominatim geocoding needed.
- **Edge API two-pass pipeline**: Uses website JWT (`fs-user-token` cookie) for auth — works.
- **New World store setup**: `tools/newworld/newworld_setup.py` defaults to `source="edge"` (148 stores), with `source="mobile"` as the legacy fallback (150 stores). Mirrors `paknsave_setup.py` structure. NW has no `store_finder` source. Output CSV is 10 columns (`store_id, name, address, city, region, lat, lon, banner, click_and_collect, delivery`); the legacy `url` column is no longer produced — store identity is via `store_id` UUIDs.

### Woolworths
- **Canonical store_id = extra1 (fulfilmentStoreId)**: Store identity keys directly on `extra1` everywhere — `data/woolworths_stores.csv` (from CDX via `fetch_store_data()`), `full_results.csv` `store_id`, and the `cw-lrkswrdjp` cookie's `f-{extra1}` field. **The legacy `pickupAddressId` (extra2) → `extra1` mapping indirection is retired** (`get_store_mapping()` is marked legacy in `woolworths_api.py`; `fetch_store_data()` now reads CDX directly, filtering null-extra1 sites and shut-down stores). The `cw-lrkswrdjp` cookie therefore builds as `dm-Pickup,f-{extra1},s-38` with no lookup. See `docs/technical/Woolworths_API.md` section 8 for full detail.
- **extra1 collisions (§63 in logs.md)**: `extra1` is a *fulfilment store ID*, not a unique store identifier. 3 pairs of stores share extra1 (Nelson Junction/Motueka, Te Puke/Bureta Park, Bridge Street/Matamata). Only 3 of those 6 stores are reachable via the cookie.
- **Hardcoded exclusions**: `fetch_store_data()` skips `9285` (Te Atatu Woolworths, shut down 24/04/2025) and `9035` (Kaikohe Woolworths, shut down 15/02/2026) via `EXCLUDED_STORE_IDS`.
- **Fresh session required per store**: Reusing a `requests.Session` causes the server's `Set-Cookie` to overwrite the injected `cw-lrkswrdjp`. Create a new session (with `GET /`) for each store.
- **`extra1` != `extra2`**: `extra1` is the internal `fulfilmentStoreId` (cookie field); `extra2` is the legacy `pickupAddressId` (from the now-legacy `fetch_store_choices()`). Use `extra1` for the cookie and as `store_id`. (`fetch_store_choices()` code is kept but marked legacy in its docstring — it only regenerates `woolworths_store_choices.csv`.)
- **`areaId` is optional**: The cookie works with just `dm-Pickup,f-{extra1}`. The `a-` and `s-` fields are not required.
- **`s-38` is constant**: Confirmed across all tested stores. Safe to hardcode.
- **x-requested-with header mandatory**: Omitting it returns HTTP 400. The literal string `"??"` works.
- **Session seeding**: A single `GET /` with browser-like headers establishes cookies. No login needed for public endpoints.
- **Playwright headless=False required**: If you do use Playwright, the site blocks headless Chromium.
- Search returns first/most-relevant result per query, not cheapest (avoids pet food for "beef mince").
  - 21 dishes are hand-curated in `DISHES` (dict format with quantity/unit/search_term) loaded from `data/dishes.json` via `optimiser_utils.py`. LLM-backed dish generation available via `src/NZMealOptimiser/llm/llm_utils.py`.
  - Ingredients with non-standard units (`can`, `medium`, `fillets`, `bag`, `head`, etc.) carry `approx_quantity`/`approx_unit` (in g or ml) for fallback scaling in `parse_optimiser_columns` when the pack is sold by weight/volume.
- **`full_results.csv` is append-only**: New rows are added per run; duplicates detected via `pk_hash` (SHA-256 of `store_id|sku|date_created`). Avoid editing in Excel — blank rows corrupt the file.
- **`--distance` flag**: `--distance 5` sets search radius in km (default 2).
- **`is_valid` column**: `data/full_results.csv` includes an `is_valid` column (blank for new rows). The `llm_validate.py` script fills it in incrementally — it skips rows already marked True/False and only writes back to rows that are blank. Validation runs **after** optimisation as a separate step; it is not integrated into the optimiser at runtime.

## Running the CLIs

Editable install + package imports means all CLIs run via `python -m`:

```powershell
python -m tools.paknsave.paknsave_optimiser_edge "Botany Town Centre, Auckland" "spaghetti bolognese"
python -m tools.paknsave.paknsave_setup              # Edge API (default, 57 stores)
python -m tools.newworld.newworld_optimiser_edge "Botany Town Centre, Auckland" "spaghetti bolognese"
python -m tools.woolworths.woolworths_optimiser "123 Queen Street, Auckland" "spaghetti bolognese"
python -m tools.llm.llm_interactive
python -m tools.llm.llm_validate --max-rows 20 --batch-size 20
```

Web app:
```powershell
.venv\Scripts\uvicorn NZMealOptimiser.web.main:app --host 0.0.0.0 --port 8000
```

Tests: `python -m pytest tests` (from repo root).

## Woolworths Research Status

- **Per-store pricing CONFIRMED**: The `cw-lrkswrdjp` cookie controls store context. Different stores return different prices (e.g., Greymouth Milk 3L = $7.15, Glenfield = $7.33). 21/21 products show price differences between stores.
- **Playwright NOT needed at runtime**: The `cw-lrkswrdjp` cookie can be constructed from `extra1` in `woolworths_store_data.json` (verified 3/3 stores). No browser automation needed for product search or store switching.
- **`woolworths_api.py` module built and tested**: End-to-end pipeline working — geocode address, find nearby stores, inject per-store cookies, search products, compare costs. See `src/NZMealOptimiser/pricing/woolworths_api.py`.
- **Fresh session per store required**: The server's `Set-Cookie` response overwrites injected cookies on reused sessions. Each store needs a fresh `requests.Session`.
- **All 67 cookies unnecessary**: Only `cw-lrkswrdjp` carries store context. The other 66 cookies (session_state, RT, Akamai, analytics, ads) are not needed for API calls.
- **`areaId` not in any data source**: The `a-field` in the cookie is optional and would require Playwright to capture per-store. Not needed for per-store pricing.
- **Full API documentation**: `docs/technical/Woolworths_API.md` covers all endpoints, cookie architecture, and production usage.
- **`full_results.csv` pipeline working**: Two-phase query→optimise with append-only CSV, `pk_hash` dedup, `--requery`/`--distance` flags. Step 1 (`woolworths_querier`) and `build_woolworths_row` live in `src/NZMealOptimiser/pricing/optimiser_utils.py`; the CLI is `tools/woolworths/woolworths_optimiser.py`.

## New World Research Status

- **Per-store pricing CONFIRMED**: Native per-store pricing via store ID in URL path — no cookie tricks needed (unlike Woolworths). Different stores return different prices (e.g., beef mince: $9.49 at Shore City vs $26.99 at Metro Auckland).
- **Mobile API working**: `api-prod.prod.fsniwaikato.kiwi/prod` with `banner: "MNW"` and `User-Agent: NewWorldApp/4.32.0` returns 150 stores with coordinates and store IDs.
- **No Nominatim geocoding needed**: All 150 stores have coordinates from the mobile API — eliminates the 22 stores that were missing coordinates via Nominatim.
- **Store count difference (Edge vs Mobile)**: Edge returns 148 stores; Mobile returns 150. The 2 stores absent from Edge are `Foodie Mart` (35 Landing Drive, Mangere) and `New World Te Atatu` (575 Te Atatū Road, Te Atatū Peninsula). See `docs/technical/NewWorld_API.md` section 9.
- **New World Edge API two-pass pipeline**: Pass 1 uses Algolia `products-index` (relevance matching via `_highlightResult.matchedWords`); Pass 2 uses `paginated/products` with Algolia `filters` for per-store pricing. Pet food filtering via `category1` to exclude `Dog/Cat/Pet`. See `docs/technical/NewWorld_API.md` section 6 for full details.
- **Store listing**: `GET /v1/edge/store` — 148 stores (HTTP 200)
- **Categories**: `GET /v1/edge/store/{id}/categories` — works
- **Category1 exposed in Algolia hits**: enables category-based filtering (e.g., excluding pet food for "beef mince")
- **Auth**: Website JWT (from `POST /api/user/get-current-user` → `fs-user-token` cookie) OR mobile API token
- **Store context**: Cookies `eCom_STORE_ID`, `STORE_ID_V2`, `Region`
- **Sort**: `PRICE_ASC`, `PRICE_DESC`
- **Edge API can fully replace mobile API** — no dependency on Foodstuffs mobile endpoint
- **2 stores missing from Edge API**: `Foodie Mart` (35 Landing Drive, Mangere) and `New World Te Atatu` (575 Te Atatū Road, Te Atatū Peninsula) appear only in the Mobile API. Store identity is via Edge/mobile `store_id` UUIDs — website URLs are no longer used.
- **Store setup defaults to Edge**: `tools/newworld/newworld_setup.py` uses `source="edge"` (148 stores); `source="mobile"` is the legacy fallback (150 stores).
- **Store CSV schema (10 cols)**: `store_id, name, address, city, region, lat, lon, banner, click_and_collect, delivery`. The legacy `url` column is no longer produced — per-store identity/pricing comes from the Edge/mobile `store_id` UUIDs, not website URLs.
- **Two-pass pipeline implementation**: See `docs/technical/NewWorld_API.md` section 6 and `exploration/newworld/`.

## Pak'nSave Research Status

- **Per-store pricing CONFIRMED**: Native per-store pricing via store ID in URL path — no cookie tricks needed. Different stores return different prices.
- **Mobile API working**: `api-prod.prod.fsniwaikato.kiwi/prod` with `banner: "PNS"` and `User-Agent: PAKnSAVEApp/4.32.0` returns 60 stores with coordinates and store IDs.
- **Pak'nSave Edge API two-pass pipeline**: Pass 1 uses Algolia `products-index` (relevance sorted, `_highlightResult.matchedWords`); Pass 2 uses `paginated/products` with Algolia `filters` for per-store pricing. Pet food filtering via `category1` to exclude `Dog/Cat/Pet`. See `docs/technical/PaknSave_API.md` section 6 for full details.
- **Edge API can fully replace mobile API** — no dependency on Foodstuffs mobile endpoint
- **Unified production modules**: `paknsave_api.py` (both backends), `paknsave_optimiser_edge.py` (two-pass + unit-price), `paknsave_optimiser_mobile.py` (single-pass) — all are thin wrappers over shared helpers in `src/NZMealOptimiser/pricing/optimiser_utils.py`.
- store_finder is only valid for Pak'nSave
- See `docs/technical/PaknSave_API.md` section 9 for store setup details and `docs/technical/PaknSave_API.md` section 6 for the full Edge API endpoint reference.

## NZ Scope

All addresses, supermarkets, and data are New Zealand only. All three brands (Pak'nSave, New World, Woolworths NZ) are fully implemented.

## Git Rules

- **Always pause and ask for confirmation** before running `git push` or `git pull`. Never auto-execute these commands.

## File permission rules

- **Never access an external directory unless invoking skills**. All files runs must be in the project directory. Always access files from the project root, and never read files from the user directory.
