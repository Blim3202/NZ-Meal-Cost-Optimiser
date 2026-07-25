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
│   ├── Exploration/
│   │   └── woolworths/                         # Exploration data files (part2_cookies.json). Full tree contents shortened.
│   ├── newworld_stores.csv                     # 149 stores: store_id (UUID), name, url, address, lat, lon, banner, click_and_collect, delivery
│   ├── paknsave_stores.csv                     # 57 stores (Edge API default) / 60 (store_finder): store_id (UUID), name, address, city, region, lat, lon
│   ├── paknsave_stores.json                    # Same data as CSV, JSON format
│   ├── woolworths_stores.csv                   # Merged Woolworths store list with lat/lon
│   ├── woolworths_store_choices.csv            # Woolworths pickup location IDs (from pickup-addresses API)
│   ├── woolworths_store_choices.json           # Same data as CSV, JSON format
│   ├── woolworths_store_data.csv               # Woolworths store details from CDX API
│   ├── woolworths_store_data.json              # Store details with extra1 (fulfilmentStoreId), extra2 (pickupAddressId)
│   ├── woolworths_latest_results.csv           # Last optimizer output for woolworths optimiser
│   ├── paknsave_latest_results.csv             # Last Edge optimizer output
│   └── paknsave_mobile_latest_results.csv      # Last Mobile optimizer output
├── notebooks/
│   ├── PaknSave_meal_cost_optimizer.ipynb      # 8-cell Jupyter prototype (run cell 6 with your inputs)
│   └── Woolworths_meal_cost_optimizer.ipynb    # Woolworths Jupyter pipeline
├── scripts/
│   ├── newworld/
│   │   ├── fetch_stores.py                     # One-shot: builds newworld_stores.csv from mobile API + store-finder page
│   │   ├── NewWorld_prototype.py               # CLI: python scripts/newworld/NewWorld_prototype.py "address" "dish"
│   │   └── Exploration/                        # API exploration scripts for Edge endpoint, relevance ordering, and two-pass product search method. Full tree contents shortened. See Exploration.md for details.
│   │       └── Exploration.md                  # Breakdown of exploration scripts in this subfolder.
│   ├── paknsave/
│   │   ├── paknsave_api.py                     # **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities
│   │   ├── paknsave_optimizer_edge.py          # **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection
│   │   ├── paknsave_optimizer_mobile.py        # **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection
│   │   ├── paknsave_setup.py                   # Unified store pipeline: fetches all 60 stores from store-finder (default) or 57 from Edge API. Callable module + CLI.
│   │   └── Exploration/                        # Edge API exploration: two-pass pipeline, relevance matching, per-store pricing. Full tree contents shortened.
│   │       └── Exploration.md                  # Complete exploration documentation (all phases + discoveries)
│   └── woolworths/
│       ├── woolworths_api.py                   # Cookie-based API module: session, store context, product search
│       ├── woolworths_optimizer.py             # API-based optimizer: geocode, stores, pricing, cost comparison
│       ├── woolworths_setup.py                 # Unified store pipeline: fetch choices, fetch data, merge (dedupes all storeAreas, 188 stores)
│       ├── Exploration/                        # API exploration scripts (black-box probing). Full tree contents shortened. See Exploration.md for details.
│       │   └── Exploration.md                  # Breakdown of exploration scripts in this subfolder.
│       └── Playwright/                         # Playwright-based scripts (legacy, not needed at runtime)
│           ├── woolworths_scrape.py            # Headed scraper for search results
│           └── ChangeStore.py                  # Store selection via modal URL
├── AGENTS.md                                   # This file
├── NewWorld_API.md                             # Foodstuffs mobile API documentation for New World (banner: MNW)
├── PaknSave_API.md                             # Foodstuffs mobile API documentation (full endpoints, auth, pricing)
├── Woolworths_API.md                           # Full /api/v1 endpoint documentation (1290+ lines)
├── design.md                                   # Technical design (API, auth, pipeline)
├── decision.md                                 # Key decisions and rationale
├── logs.md                                     # Major errors and resolutions
├── requirements.txt                            # Pinned dependencies
└── README.md                                   # Project readme
```

## File Contents

| File | Purpose |
|---|---|
| `NewWorld_API.md` | Foodstuffs mobile API documentation for New World (banner: MNW). Full endpoint reference with auth flow, per-store pricing, architecture, comparison vs Pak'nSave/Woolworths. Credits [Arefu](https://github.com/Arefu) (OpenAPI YAML in their [PaknSave repo](https://github.com/Arefu/PaknSave)). |
| `PaknSave_API.md` | Foodstuffs mobile API documentation. Full endpoint reference with auth flow, per-store pricing, architecture, comparison vs Woolworths. Includes Edge API two-pass pipeline documentation. Credits [Arefu](https://github.com/Arefu) (OpenAPI YAML in their [PaknSave repo](https://github.com/Arefu/PaknSave)). |
| `scripts/newworld/NewWorld_prototype.py` | CLI entry point. Contains `NewWorldAPI` class, `DISH_INGREDIENTS` map (21 dishes), geocoding, haversine, store search, price comparison. Uses `banner: "MNW"` and `User-Agent: NewWorldApp/4.32.0`. |
| `scripts/newworld/fetch_stores.py` | Data builder. Fetches 149 New World stores from mobile API (coordinates, store IDs, banner) and store-finder page (URL slugs). Saves to `data/newworld_stores.csv`. |
| `scripts/paknsave/paknsave_api.py` | **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities |
| `scripts/paknsave/paknsave_optimizer_edge.py` | **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection |
| `scripts/paknsave/paknsave_optimizer_mobile.py` | **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection |
| `scripts/paknsave/paknsave_setup.py` | **Unified store builder pipeline**: fetches stores from store-finder (60 stores) or Edge API (57 stores). Callable module + CLI with `source` param. Replaces fetch_stores.py. |
| `scripts/paknsave/Exploration/demo_two_pass_pipeline.py` | **Edge API two-pass optimizer**: Full pipeline with relevance matching (products-index), per-store pricing (paginated/products), pet food filtering (category1), promotional prices. |
| `scripts/paknsave/Exploration/test_two_pass_optimizer.py` | **Edge API two-pass CLI**: CLI wrapper for two-pass optimizer with geocoding, store filtering, 21 dishes, cost comparison. |
| `scripts/paknsave/Exploration/Exploration.md` | **Edge API exploration documentation**: All phases, discoveries, and breakthroughs for Pak'nSave Edge API two-pass pipeline. |
| `scripts/woolworths/woolworths_api.py` | Cookie-based Woolworths API module. `create_session()`, `set_store_context()`, `search_products()`, `find_cheapest()`, `get_nearby_stores()`, `geocode()`. Constructs `cw-lrkswrdjp` cookie from `extra1` in store data — no Playwright needed at runtime. |
| `scripts/woolworths/woolworths_optimizer.py` | API-based optimizer. Geocodes address, finds nearby stores, searches each ingredient at each store via API with per-store pricing, compares totals. 21 dishes supported. |
| `scripts/woolworths/woolworths_setup.py` | **Unified store pipeline**: fetches pickup locations (188 stores via all storeAreas), fetches store location data (183 stores from CDX API), merges on common ID. Outputs `woolworths_stores.csv` (177 stores with coordinates). Replaces legacy scripts. |
| `scripts/woolworths/woolworths_scrape.py` | Playwright headed scraper for search results (name, unit cost, actual price). Legacy — replaced by API-based approach. |
| `scripts/woolworths/ChangeStore.py` | Playwright store selection via modal URL. Reference implementation for browser-based store switching. |
| `scripts/woolworths/explore_woolworths_api_part{1-4}.py` | API exploration scripts. Phase 1: endpoint enumeration. Phase 2: cookie injection. Phase 3: cw-lrkswrdjp deep-dive. Phase 4: programmatic construction. |
| `notebooks/PaknSave_meal_cost_optimizer.ipynb` | Pak'nSave prototype. |
| `notebooks/Woolworths_meal_cost_optimizer.ipynb` | Woolworths pipeline, utilizes `woolworths_optimizer.py`. |
| `data/woolworths_store_data.json` | Store details with `extra1` (=fulfilmentStoreId) and `extra2` (=pickupAddressId). Key data source for cookie construction. |
| `requirements.txt` | Pinned deps. Core: `cloudscraper`, `requests`, `pandas`, `numpy`, `beautifulsoup4`, `playwright`, `jupyterlab`. |

## Key Gotchas

### Pak'nSave
- Guest API token expires after 30 min — auto-refreshed by the `PaknSaveAPI` class.
- Prices from the Pak'nSave API are in **cents** — divide by 100 for dollars.
- `PaknSaveAPI.get_stores()` returns `{"stores": [...]}`, not a bare list.
- Nominatim geocoding rate limit: 1 req/sec.
- **Edge API two-pass pipeline**: Uses website JWT (`fs-user-token` cookie) for auth — works.
- **Edge API pet food filtering**: Filter by `category1` to exclude `{"Dog", "Cat", "Pet"}` categories in Pass 1.

### New World
- Uses the same Foodstuffs mobile API as Pak'nSave with `banner: "MNW"` and `User-Agent: NewWorldApp/4.32.0`.
- Prices from the New World API are in **cents** — divide by 100 for dollars.
- 149 stores with coordinates and store IDs from the mobile API — no Nominatim geocoding needed.
- **Edge API two-pass pipeline**: Uses website JWT (`fs-user-token` cookie) for auth — works.
- 7 stores missing URLs due to name mismatches between API and store-finder page (e.g., "Metro Auckland" vs "Metro Queen Street", macron differences).

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
- 21 dishes are hand-curated in `DISH_INGREDIENTS` — no NLP/LLM parsing yet.

## Woolworths Research Status

- **Per-store pricing CONFIRMED**: The `cw-lrkswrdjp` cookie controls store context. Different stores return different prices (e.g., Greymouth Milk 3L = $7.15, Glenfield = $7.33). 21/21 products show price differences between stores.
- **Playwright NOT needed at runtime**: The `cw-lrkswrdjp` cookie can be constructed from `extra1` in `woolworths_store_data.json` (verified 3/3 stores). No browser automation needed for product search or store switching.
- **`woolworths_api.py` module built and tested**: End-to-end pipeline working — geocode address, find nearby stores, inject per-store cookies, search products, compare costs. See `scripts/woolworths/woolworths_api.py`.
- **Fresh session per store required**: The server's `Set-Cookie` response overwrites injected cookies on reused sessions. Each store needs a fresh `requests.Session`.
- **All 67 cookies unnecessary**: Only `cw-lrkswrdjp` carries store context. The other 66 cookies (session_state, RT, Akamai, analytics, ads) are not needed for API calls.
- **`areaId` not in any data source**: The `a-field` in the cookie is optional and would require Playwright to capture per-store. Not needed for per-store pricing.
- **Full API documentation**: `Woolworths_API.md` (1290+ lines) covers all endpoints, cookie architecture, and production usage.

## New World Research Status

- **Per-store pricing CONFIRMED**: Native per-store pricing via store ID in URL path — no cookie tricks needed (unlike Woolworths). Different stores return different prices (e.g., beef mince: $9.49 at Shore City vs $26.99 at Metro Auckland).
- **Mobile API working**: `api-prod.prod.fsniwaikato.kiwi/prod` with `banner: "MNW"` and `User-Agent: NewWorldApp/4.32.0` returns 149 stores with coordinates and store IDs.
- **No Nominatim geocoding needed**: All 149 stores have coordinates from the mobile API — eliminates the 22 stores that were missing coordinates via Nominatim.
- **New World Edge API — TWO-PASS PIPELINE WORKS**:
  - The Edge API does NOT have a single endpoint with both relevance matching AND per-store pricing. We discovered a **two-pass architecture**:
  
  **PASS 1 — Relevance Matching (Algolia Index):**
  - `POST /v1/edge/search/products/query/index/products-index` (the DEFAULT Algolia index)
  - Returns hits with `_highlightResult.matchedWords` — explicit relevance matching!
  - Fields matched: `DisplayName`, `category2AndBrand`, `category1`, `category2`, `brand`, etc.
  - Sort: Algolia default (relevance)
  - Price: `averagePrice` (cross-store, not per-store)
  
  **PASS 2 — Per-Store Pricing (Paginated Endpoint with Filters):**
  - `POST /v1/edge/search/paginated/products` with Algolia `filters` parameter
  - Filter syntax: `productID:xxx OR productID:yyy OR productID:zzz`
  - Returns `singlePrice.price` (cents) + `promotions[].rewardValue` (promo cents)
  - Sort: `PRICE_ASC`, `PRICE_DESC` (no RELEVANCE sort available)
  - Store context via cookies: `eCom_STORE_ID`, `STORE_ID_V2`, `Region`
  
  **Algolia Indices Tested (14+):**
  - `products-index` ✅ 200 — DEFAULT, relevance sorted, HAS `_highlightResult`
  - `products-index-popularity-asc` ✅ 200 — NO relevance matches, popularity ASC
  - `products-index-popularity-desc` ✅ 200 — NO relevance matches, popularity DESC
  - All others (`price-asc`, `price-desc`, `relevance`, `name-asc`, `name-desc`, `newest`, `bestselling`, `trending`) ❌ 404
  
  **Key Discovery**: Only the DEFAULT `products-index` has relevance matching via `_highlightResult`. The popularity indices have the field but it's EMPTY.
  
  **Bridge**: Pass 1 extracts `productID` from hits with non-empty `matchedWords`. Pass 2 uses Algolia `filters` to get per-store pricing for exactly those relevant products.
  
  **Advantage over Mobile API**: Explicit relevance matching (mobile API returns first result but no visibility into WHY it matched). Critical for avoiding pet food matching "beef mince".
  
- **Store listing**: `GET /v1/edge/store` — 148 stores (HTTP 200)
- **Categories**: `GET /v1/edge/store/{id}/categories` — works
- **Auth**: Website JWT (from `POST /api/user/get-current-user` → `fs-user-token` cookie) OR mobile API token
- **Store context**: Cookies `eCom_STORE_ID`, `STORE_ID_V2`, `Region`
- **Sort**: `PRICE_ASC`, `PRICE_DESC`
- **Edge API can fully replace mobile API** — no dependency on Foodstuffs mobile endpoint
- **7 stores missing URLs**: Name mismatches between API and store-finder page (e.g., "Metro Auckland" vs "Metro Queen Street", macron differences). URLs are only for website linking, not for the API optimizer.
- **Full API documentation**: `NewWorld_API.md` covers all endpoints, auth flow, per-store pricing, two-pass pipeline, and production usage.
- **`NewWorld_prototype.py` built and tested**: End-to-end pipeline working — geocode address, find nearby stores, search products, compare costs. 21 dishes supported.
- **Two-pass pipeline implementation**: `scripts/newworld/Exploration/explore_edge_api9_relevance.py` (comprehensive), `test_milk_metro_relevance.py` (focused test), `demo_edge_optimizer.py` (full optimizer demo).

## Pak'nSave Research Status

- **Per-store pricing CONFIRMED**: Native per-store pricing via store ID in URL path — no cookie tricks needed. Different stores return different prices.
- **Mobile API working**: `api-prod.prod.fsniwaikato.kiwi/prod` with `banner: "PNS"` and `User-Agent: PAKnSAVEApp/4.32.0` returns 60 stores with coordinates and store IDs.
- **Pak'nSave Edge API — TWO-PASS PIPELINE WORKS**:
  - Same architecture as New World Edge API (identical Foodstuffs backend)
  
  **PASS 1 — Relevance Matching (Algolia Index):**
  - `POST /v1/edge/search/products/query/index/products-index` (DEFAULT Algolia index)
  - Returns hits with `_highlightResult.matchedWords` — explicit relevance matching!
  - **Key Difference from New World**: ALL three working indices have `matchedWords` populated (not just the default)
  
  **PASS 2 — Per-Store Pricing (Paginated Endpoint with Filters):**
  - `POST /v1/edge/search/paginated/products` with Algolia `filters` parameter
  - Same syntax as New World: `productID:xxx OR productID:yyy`
  - Returns `singlePrice.price` (cents) + `promotions[].rewardValue` (promo cents)
  - Sort: `PRICE_ASC`, `PRICE_DESC`
  - Store context via cookies: `eCom_STORE_ID`, `STORE_ID_V2`, `Region`
  
  **Pet Food Filtering**: Filter by `category1` to exclude `{"Dog", "Cat", "Pet"}` categories in Pass 1. Critical for queries like "beef mince" which return pet food items.
  
- **Store listing**: `GET /v1/edge/store` — 57 stores (HTTP 200) — 3 fewer than mobile API's 60. Missing stores: Wairau Road (Glenfield), Gisborne City, Levin (not configured for Edge API ordering).
- **Auth**: Website JWT (from `POST /api/user/get-current-user` → `fs-user-token` cookie) OR mobile API token
- **Store context**: Cookies `eCom_STORE_ID`, `STORE_ID_V2`, `Region` (NI or SI for South Island)
- **Sort**: `PRICE_ASC`, `PRICE_DESC`
- **Edge API can fully replace mobile API** — no dependency on Foodstuffs mobile endpoint
- **Full API documentation**: `PaknSave_API.md` section 6 covers all endpoints, auth flow, per-store pricing, two-pass pipeline, and production usage.
- **Two-pass pipeline implementation**: `scripts/paknsave/Exploration/demo_two_pass_pipeline.py` (full demo), `test_two_pass_optimizer.py` (CLI optimizer), `Exploration.md` (full documentation).
- **Unified production modules**: 
  - `scripts/paknsave/paknsave_api.py` — unified API client (Edge default, Mobile fallback)
  - `scripts/paknsave/paknsave_optimizer_edge.py` — Edge API optimizer with unit-price selection
  - `scripts/paknsave/paknsave_optimizer_mobile.py` — Mobile API optimizer with unit-price selection

## NZ Scope

All addresses, supermarkets, and data are New Zealand only. First target: Pak'nSave, expanding to New World and Woolworths NZ.

## Git Rules

- **Always pause and ask for confirmation** before running `git push` or `git pull`. Never auto-execute these commands.

## File permission rules

- **Never access an external directory unless invoking skills**. All files runs must be in the project directory.
