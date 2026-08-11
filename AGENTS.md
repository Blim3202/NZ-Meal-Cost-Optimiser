# OpenCode — NZ Meal Cost Optimizer

Finds the cheapest Pak'nSave, New World, or Woolworths for a given dish by comparing ingredient prices across nearby stores (within 5 km of a NZ address).

## Setup

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Project Layout

```
opencode/
├── data/
│   ├── newworld_stores.csv                     # 148 stores (Edge, default) or 150 (Mobile): store_id, name, address, city, region, lat, lon, banner, click_and_collect, delivery
│   ├── paknsave_stores.csv                     # 57 stores (Edge, default) / 60 (store_finder): store_id, name, address, city, region, lat, lon, banner, click_and_collect, delivery
│   ├── paknsave_stores.json                    # Same data as CSV, JSON format
│   ├── woolworths_stores.csv                   # Merged Woolworths store list with lat/lon
│   ├── woolworths_store_choices.csv            # Woolworths pickup location IDs (from pickup-addresses API)
│   ├── woolworths_store_choices.json           # Same data as CSV, JSON format
│   ├── woolworths_store_data.csv               # Woolworths store details from CDX API
│   ├── woolworths_store_data.json              # Store details with extra1 (fulfilmentStoreId), extra2 (pickupAddressId)
│   ├── woolworths_latest_results.csv           # Last optimizer output for woolworths optimiser
│   ├── paknsave_latest_results.csv             # Last Edge optimizer output
│   ├── paknsave_mobile_latest_results.csv      # Last Mobile optimizer output
│   ├── observed_category1_newworld.json         # Category1 values from New World Algolia index
│   ├── observed_category1_paknsave.json         # Category1 values from Pak'nSave Algolia index
│   ├── dishes.json                              # 21 hand-curated dishes with structured ingredients
│   └── full_results.csv                         # Append-only results with pk_hash deduplication + is_valid column
├── notebooks/
│   ├── PaknSave_meal_cost_optimizer.ipynb      # 8-cell Jupyter prototype (run cell 6 with your inputs)
│   └── Woolworths_meal_cost_optimizer.ipynb    # Woolworths Jupyter pipeline
├── scripts/
│   ├── combined/
│   │   ├── optimizer_utils.py                  # **Cross-brand helpers**: foodstuffs_optimizer_edge/mobile, build_edge_row/mobile_row, parsing, geocoding, haversine, DISHES, get_ingredients, _resolve_dish, _build_quantity_map, optimise(), append_rows, _compute_pk_hash
│   │   └── initialize_full_results.py          # Creates data/full_results.csv with 18-column schema (17 + is_valid) + pk_hash
│   ├── newworld/
│   │   ├── newworld_setup.py                   # **Unified store builder**: Edge API (148 stores), Mobile API (150 stores). Callable module + CLI with `source` param.
│   │   ├── newworld_api.py                     # **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities
│   │   ├── newworld_optimizer_edge.py           # **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection
│   │   ├── newworld_optimizer_mobile.py         # **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection
│   │   └── Exploration/                         # Legacy API exploration scripts (collapsed)
│   ├── paknsave/
│   │   ├── paknsave_api.py                     # **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities
│   │   ├── paknsave_optimizer_edge.py           # **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection
│   │   ├── paknsave_optimizer_mobile.py         # **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection
│   │   ├── paknsave_setup.py                    # Unified store pipeline: Edge (57) + Mobile (60) + store_finder (60, paknsave only)
│   │   └── Exploration/                         # Legacy API exploration scripts (collapsed)
│   ├── woolworths/
│   │   ├── woolworths_api.py                    # Cookie-based API module: session, store context, product search
│   │   ├── woolworths_optimizer.py              # Two-phase optimizer: query API → save to full_results.csv → optimise from CSV
│   │   ├── woolworths_setup.py                  # Unified store pipeline: fetch choices, fetch data, merge (188 → 177 with coords)
│   │   ├── Exploration/                         # Legacy API exploration scripts (collapsed)
│   │   ├── Fixture/                             # Test fixtures (collapsed)
│   │   ├── Playwright/                          # Legacy Playwright scripts (not needed at runtime, collapsed)
│   │   └── tests/                               # Unit tests (collapsed)
│   ├── llms/
│   │   ├── llm_client.py                        # Mistral API client: rate limiting, JSON retries, model aliases
│   │   ├── llm_utils.py                         # Ingredient resolution (curated JSON → LLM), dish parsing/validation, quantity scaling
│   │   ├── llm_validate.py                      # Post-run search-result validator (writes is_valid to full_results.csv)
│   │   ├── llm_interactive.py                   # Interactive CLI: ingredients → query → optimise → scale → validate
│   │   ├── Exploration/                         # LLM exploration scripts (collapsed)
│   │   └── tests/                               # LLM unit tests (collapsed)
│   └── test/                                    # Cross-brand sanity checks (collapsed)
├── AGENTS.md                                   # This file
├── NewWorld_API.md                             # Foodstuffs mobile API documentation for New World (banner: MNW)
├── PaknSave_API.md                             # Foodstuffs mobile API documentation (full endpoints, auth, pricing)
├── Woolworths_API.md                           # Full /api/v1 endpoint documentation (1290+ lines)
├── design.md                                   # Technical design (API, auth, pipeline)
├── decision.md                                 # Key decisions and rationale
├── logs.md                                     # Major errors and resolutions
├── LLM_Pipeline.md                             # LLM ingredient generation, validation, and quantity scaling pipeline
├── requirements.txt                            # Pinned dependencies
└── README.md                                   # Project readme
```

## File Contents

| File | Purpose |
|---|---|
| `NewWorld_API.md` | Foodstuffs New World API docs — shared structure referenced from PaknSave_API.md; New World-specific Edge API, dishes, store data sources |
| `PaknSave_API.md` | Foodstuffs Pak'nSave API docs — primary reference for shared Foodstuffs mobile API + Edge API structure; New World references this for common content |
| `scripts/combined/optimizer_utils.py` | **Cross-brand helpers**: foodstuffs_optimizer_edge/mobile, build_edge_row/mobile_row, parsing, geocoding, haversine, DISHES, get_ingredients, _resolve_dish, _build_quantity_map, optimise(), append_rows, _compute_pk_hash |
| `scripts/combined/initialize_full_results.py` | Creates data/full_results.csv with 18-column schema (17 + is_valid) + pk_hash for deduplication |
| `scripts/newworld/newworld_setup.py` | **Unified store builder**: Edge API (148 stores), Mobile API (150 stores). Callable module + CLI with `source` param. Mirrors paknsave_setup.py structure. |
| `scripts/newworld/newworld_api.py` | **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities |
| `scripts/newworld/newworld_optimizer_edge.py` | **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection. Thin wrapper over shared `foodstuffs_optimizer_edge` in `optimizer_utils.py`. |
| `scripts/newworld/newworld_optimizer_mobile.py` | **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection. Thin wrapper over shared `foodstuffs_optimizer_mobile` in `optimizer_utils.py`. |
| `scripts/paknsave/paknsave_setup.py` | **Unified store builder**: Edge (57 stores) + Mobile (60 stores) + store_finder (60 stores, paknsave only). Callable module + CLI with `source` param. |
| `scripts/paknsave/paknsave_api.py` | **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities |
| `scripts/paknsave/paknsave_optimizer_edge.py` | **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection. Thin wrapper over shared `foodstuffs_optimizer_edge` in `optimizer_utils.py`. |
| `scripts/paknsave/paknsave_optimizer_mobile.py` | **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection. Thin wrapper over shared `foodstuffs_optimizer_mobile` in `optimizer_utils.py`. |
| `scripts/woolworths/woolworths_setup.py` | **Unified store pipeline**: fetch choices, fetch data, merge (188 stores → 177 with coords). Replaces legacy scripts. |
| `scripts/woolworths/woolworths_api.py` | Cookie-based Woolworths API module. Session, store context, product search. Constructs `cw-lrkswrdjp` cookie from `extra1` in store data. No Playwright needed at runtime. |
| `notebooks/PaknSave_meal_cost_optimizer.ipynb` | Pak'nSave prototype |
| `notebooks/Woolworths_meal_cost_optimizer.ipynb` | Woolworths pipeline, utilizes `woolworths_optimizer.py` |
| `data/woolworths_store_data.json` | Store details with `extra1` (=fulfilmentStoreId) and `extra2` (=pickupAddressId) |
| `requirements.txt` | Pinned deps. Core: `cloudscraper`, `requests`, `pandas`, `numpy`, `beautifulsoup4`, `playwright`, `jupyterlab`. |
| `LLM_Pipeline.md` | LLM ingredient generation, post-run validation, and quantity scaling pipeline (see `scripts/llms/`). |
| `scripts/llms/llm_client.py` | Mistral API client: model aliases (small/medium/large), rate limiting, JSON parsing with retries. |
| `scripts/llms/llm_utils.py` | Ingredient resolution (curated `dishes.json` → LLM → fallback), dish parsing/validation (`parse_and_validate`), and quantity scaling (`parse_optimizer_columns` with `approx_quantity`/`approx_unit` fallback for non-standard units). |
| `scripts/llms/llm_validate.py` | Post-run validator: batches rows through `ministral-3b-2512`, writes `is_valid` back to `data/full_results.csv`. Skips already-validated rows. |
| `scripts/llms/llm_interactive.py` | Interactive CLI: Step 1 inputs → Step 2 resolve ingredients → Step 3 review → Step 4 query optimizers → Step 5 optimise → Step 6 scaling (enriches CSV rows with `ingredient_approx_*` fields). |

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
- Uses the same Foodstuffs mobile API as Pak'nSave with `banner: "MNW"` and `User-Agent: NewWorldApp/4.32.0`. API client: `scripts/newworld/newworld_api.py`. Cross-brand helpers (parsing, geocoding, optimizers) live in `scripts/combined/optimizer_utils.py`.
- Prices from the New World API are in **cents** — divide by 100 for dollars.
- All sources (Edge 148 / Mobile 150) provide coordinates and store IDs — no Nominatism geocoding needed.
- **Edge API two-pass pipeline**: Uses website JWT (`fs-user-token` cookie) for auth — works.
- **New World store setup**: `scripts/newworld/newworld_setup.py` defaults to `source="edge"` (148 stores), with `source="mobile"` as the legacy fallback (150 stores). Mirrors `paknsave_setup.py` structure. NW has no `store_finder` source. Output CSV is 10 columns (`store_id, name, address, city, region, lat, lon, banner, click_and_collect, delivery`); the legacy `url` column is no longer produced — store identity is via `store_id` UUIDs.

### Woolworths
- **Per-store pricing via cookie injection**: The `cw-lrkswrdjp` cookie controls store context. Construct it as `dm-Pickup,f-{fulfilmentStoreId},s-38` where `fulfilmentStoreId` = `extra1` from `woolworths_store_data.json`. See `Woolworths_API.md` section 8 for full details.
- **Fresh session required per store**: Reusing a `requests.Session` causes the server's `Set-Cookie` to overwrite the injected `cw-lrkswrdjp`. Create a new session (with `GET /`) for each store.
- **`fulfilmentStoreId` != `pickupAddressId`**: These are different numbers. Use `extra1` from `woolworths_store_data.json` for the cookie.
- **`areaId` is optional**: The cookie works with just `dm-Pickup,f-{fulfilmentStoreId}`. The `a-` and `s-` fields are not required.
- **`s-38` is constant**: Confirmed across all tested stores. Safe to hardcode.
- **x-requested-with header mandatory**: Omitting it returns HTTP 400. The literal string `"??"` works.
- **Session seeding**: A single `GET /` with browser-like headers establishes cookies. No login needed for public endpoints.
- **Playwright headless=False required**: If you do use Playwright, the site blocks headless Chromium.
- Search returns first/most-relevant result per query, not cheapest (avoids pet food for "beef mince").
  - 21 dishes are hand-curated in `DISHES` (dict format with quantity/unit/search_term) loaded from `data/dishes.json` via `optimizer_utils.py`. LLM-backed dish generation available via `scripts/llms/llm_utils.py`.
  - Ingredients with non-standard units (`can`, `medium`, `fillets`, `bag`, `head`, etc.) carry `approx_quantity`/`approx_unit` (in g or ml) for fallback scaling in `parse_optimizer_columns` when the pack is sold by weight/volume.
- **`full_results.csv` is append-only**: New rows are added per run; duplicates detected via `pk_hash` (SHA-256 of `store_id|sku|date_created`). Avoid editing in Excel — blank rows corrupt the file.
- **`-distance` flag**: `--distance 5` sets search radius in km (default 2).
- **`is_valid` column**: `data/full_results.csv` includes an `is_valid` column (blank for new rows). The `llm_validate.py` script fills it in incrementally — it skips rows already marked True/False and only writes back to rows that are blank. Validation runs **after** optimization as a separate step; it is not integrated into the optimizer at runtime.

## Woolworths Research Status

- **Per-store pricing CONFIRMED**: The `cw-lrkswrdjp` cookie controls store context. Different stores return different prices (e.g., Greymouth Milk 3L = $7.15, Glenfield = $7.33). 21/21 products show price differences between stores.
- **Playwright NOT needed at runtime**: The `cw-lrkswrdjp` cookie can be constructed from `extra1` in `woolworths_store_data.json` (verified 3/3 stores). No browser automation needed for product search or store switching.
- **`woolworths_api.py` module built and tested**: End-to-end pipeline working — geocode address, find nearby stores, inject per-store cookies, search products, compare costs. See `scripts/woolworths/woolworths_api.py`.
- **Fresh session per store required**: The server's `Set-Cookie` response overwrites injected cookies on reused sessions. Each store needs a fresh `requests.Session`.
- **All 67 cookies unnecessary**: Only `cw-lrkswrdjp` carries store context. The other 66 cookies (session_state, RT, Akamai, analytics, ads) are not needed for API calls.
- **`areaId` not in any data source**: The `a-field` in the cookie is optional and would require Playwright to capture per-store. Not needed for per-store pricing.
- **Full API documentation**: `Woolworths_API.md` (1290+ lines) covers all endpoints, cookie architecture, and production usage.
- **`full_results.csv` pipeline working**: Two-phase query→optimise with append-only CSV, `pk_hash` dedup, `--requery`/`--distance` flags. See `scripts/woolworths/woolworths_optimizer.py`.

## New World Research Status

- **Per-store pricing CONFIRMED**: Native per-store pricing via store ID in URL path — no cookie tricks needed (unlike Woolworths). Different stores return different prices (e.g., beef mince: $9.49 at Shore City vs $26.99 at Metro Auckland).
- **Mobile API working**: `api-prod.prod.fsniwaikato.kiwi/prod` with `banner: "MNW"` and `User-Agent: NewWorldApp/4.32.0` returns 150 stores with coordinates and store IDs.
- **No Nominatim geocoding needed**: All 150 stores have coordinates from the mobile API — eliminates the 22 stores that were missing coordinates via Nominatim.
- **Store count difference (Edge vs Mobile)**: Edge returns 148 stores; Mobile returns 150. The 2 stores absent from Edge are `Foodie Mart` (35 Landing Drive, Mangere) and `New World Te Atatu` (575 Te Atatū Road, Te Atatū Peninsula). See `NewWorld_API.md` section 9.
- **New World Edge API two-pass pipeline**: Pass 1 uses Algolia `products-index` (relevance matching via `_highlightResult.matchedWords`); Pass 2 uses `paginated/products` with Algolia `filters` for per-store pricing. Pet food filtering via `category1` to exclude `Dog/Cat/Pet`. See `NewWorld_API.md` section 6 for full details.
- **Store listing**: `GET /v1/edge/store` — 148 stores (HTTP 200)
- **Categories**: `GET /v1/edge/store/{id}/categories` — works
- **Category1 exposed in Algolia hits**: enables category-based filtering (e.g., excluding pet food for "beef mince")
- **Auth**: Website JWT (from `POST /api/user/get-current-user` → `fs-user-token` cookie) OR mobile API token
- **Store context**: Cookies `eCom_STORE_ID`, `STORE_ID_V2`, `Region`
- **Sort**: `PRICE_ASC`, `PRICE_DESC`
- **Edge API can fully replace mobile API** — no dependency on Foodstuffs mobile endpoint
- **2 stores missing from Edge API**: `Foodie Mart` (35 Landing Drive, Mangere) and `New World Te Atatu` (575 Te Atatū Road, Te Atatū Peninsula) appear only in the Mobile API. Store identity is via Edge/mobile `store_id` UUIDs — website URLs are no longer used.
- **Store setup defaults to Edge**: `newworld_setup.py` uses `source="edge"` (148 stores); `source="mobile"` is the legacy fallback (150 stores).
- **Store CSV schema (10 cols)**: `store_id, name, address, city, region, lat, lon, banner, click_and_collect, delivery`. The legacy `url` column is no longer produced — per-store identity/pricing comes from the Edge/mobile `store_id` UUIDs, not website URLs.
- **Two-pass pipeline implementation**: See `NewWorld_API.md` section 6 and `scripts/newworld/Exploration/`.

## Pak'nSave Research Status

- **Per-store pricing CONFIRMED**: Native per-store pricing via store ID in URL path — no cookie tricks needed. Different stores return different prices.
- **Mobile API working**: `api-prod.prod.fsniwaikato.kiwi/prod` with `banner: "PNS"` and `User-Agent: PAKnSAVEApp/4.32.0` returns 60 stores with coordinates and store IDs.
- **Pak'nSave Edge API two-pass pipeline**: Pass 1 uses Algolia `products-index` (relevance sorted, `_highlightResult.matchedWords`); Pass 2 uses `paginated/products` with Algolia `filters` for per-store pricing. Pet food filtering via `category1` to exclude `Dog/Cat/Pet`. See `PaknSave_API.md` section 6 for full details.
- **Edge API can fully replace mobile API** — no dependency on Foodstuffs mobile endpoint
- **Unified production modules**: `paknsave_api.py` (both backends), `paknsave_optimizer_edge.py` (two-pass + unit-price), `paknsave_optimizer_mobile.py` (single-pass) — all are thin wrappers over shared helpers in `scripts/combined/optimizer_utils.py`.
- store_finder is only valid for Pak'nSave
- See `PaknSave_API.md` section 9 for store setup details and `PaknSave_API.md` section 6 for the full Edge API endpoint reference.

## NZ Scope

All addresses, supermarkets, and data are New Zealand only. All three brands (Pak'nSave, New World, Woolworths NZ) are fully implemented.

## Git Rules

- **Always pause and ask for confirmation** before running `git push` or `git pull`. Never auto-execute these commands.

## File permission rules

- **Never access an external directory unless invoking skills**. All files runs must be in the project directory. Always access files from the project root, and never read files from the user directory.
