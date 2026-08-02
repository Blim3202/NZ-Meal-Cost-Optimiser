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
│   ├── newworld_stores.csv                     # 148 stores (Edge) or 149 (Mobile): store_id (UUID), name, url, address, city, region, lat, lon, banner, click_and_collect, delivery
│   ├── paknsave_stores.csv                     # 57 stores (Edge API default) / 60 (store_finder): store_id (UUID), name, address, city, region, lat, lon
│   ├── paknsave_stores.json                    # Same data as CSV, JSON format
│   ├── woolworths_stores.csv                   # Merged Woolworths store list with lat/lon
│   ├── woolworths_store_choices.csv            # Woolworths pickup location IDs (from pickup-addresses API)
│   ├── woolworths_store_choices.json           # Same data as CSV, JSON format
│   ├── woolworths_store_data.csv               # Woolworths store details from CDX API
│   ├── woolworths_store_data.json              # Store details with extra1 (fulfilmentStoreId), extra2 (pickupAddressId)
│   ├── woolworths_latest_results.csv           # Last optimizer output for woolworths optimiser
│   ├── paknsave_latest_results.csv             # Last Edge optimizer output
│   ├── paknsave_mobile_latest_results.csv      # Last Mobile optimizer output
│   ├── observed_category1_newworld.json         # Category1 values from New World Algolia index (explore_categories.py output)
│   └── observed_category1_paknsave.json         # Category1 values from Pak'nSave Algolia index (explore_categories.py output)
├── notebooks/
│   ├── PaknSave_meal_cost_optimizer.ipynb      # 8-cell Jupyter prototype (run cell 6 with your inputs)
│   └── Woolworths_meal_cost_optimizer.ipynb    # Woolworths Jupyter pipeline
├── scripts/
│   ├── foodstuffs/
│   │   ├── Foodstuffs_api.py                   # **Unified API module** for both brands (Pak'nSave + New World)
│   │   ├── Foodstuffs_optimizer_edge.py         # **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection
│   │   ├── Foodstuffs_optimizer_mobile.py       # **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection
│   │   └── Foodstuffs_setup.py                  # **Unified store builder pipeline**: Edge (148/57 stores) + Mobile (149/60 stores) + store_finder (paknsave only, 60 stores). Callable module + CLI with `source` param.
│   ├── newworld/
│   │   ├── newworld_setup.py                   # **Unified store builder pipeline**: Edge API (148 stores), Mobile API (149 stores). Callable module + CLI with `source` param. Mirrors paknsave_setup.py structure.
│   │   ├── newworld_api.py                     # **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities
│   │   ├── newworld_optimizer_edge.py           # **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection
│   │   ├── newworld_optimizer_mobile.py         # **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection
│   │   ├── Exploration/                         # API exploration scripts (legacy). See Exploration.md for details.
│   ├── paknsave/
│   │   ├── paknsave_api.py                     # **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities
│   │   ├── paknsave_optimizer_edge.py           # **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection
│   │   ├── paknsave_optimizer_mobile.py         # **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection
│   │   ├── paknsave_setup.py                    # Unified store pipeline: Edge (57 stores) + Mobile (60 stores) + store_finder (60 stores, paknsave only). Callable module + CLI with `source` param.
│   │   ├── Exploration/                         # Complete exploration documentation (all phases + discoveries)
│   └── woolworths/
│       ├── woolworths_api.py                    # Cookie-based API module: session, store context, product search
│       ├── woolworths_optimizer.py              # Two-phase optimizer: query API → save to full_results.csv → optimise from CSV. Supports --requery, --distance flags.
│       ├── woolworths_setup.py                  # Unified store pipeline: fetch choices, fetch data, merge (188 stores → 177 with coords)
│       ├── Exploration/                         # API exploration scripts. See Exploration.md for details.
│       ├── Playwright/                          # Playwright-based scripts (legacy, not needed at runtime)
│       │   ├── woolworths_scrape.py             # Headed scraper for search results
│       │   └── ChangeStore.py                   # Store selection via modal URL
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
| `NewWorld_API.md` | Foodstuffs New World API docs — shared structure referenced from PaknSave_API.md; New World-specific Edge API, dishes, store data sources |
| `PaknSave_API.md` | Foodstuffs Pak'nSave API docs — primary reference for shared Foodstuffs mobile API + Edge API structure; New World references this for common content |
| `scripts/foodstuffs/Foodstuffs_setup.py` | **Unified store builder pipeline**: Edge (148/57 stores) + Mobile (149/60 stores) + store_finder (paknsave only, 60 stores). Callable module + CLI with `source` param. |
| `scripts/foodstuffs/Foodstuffs_api.py` | **Unified API module** for both brands. `FoodstuffsEdgeAPI(brand)`, `FoodstuffsMobileAPI(brand)` with brand-specific credentials. Shared utilities included. |
| `scripts/foodstuffs/Foodstuffs_optimizer_edge.py` | **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection. Accepts `brand` argument. |
| `scripts/foodstuffs/Foodstuffs_optimizer_mobile.py` | **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection. Accepts `brand` argument. |
| `scripts/newworld/newworld_setup.py` | **Unified store builder**: Edge API (148 stores), Mobile API (149 stores). Callable module + CLI with `source` param. Mirrors paknsave_setup.py structure. |
| `scripts/newworld/newworld_api.py` | **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities |
| `scripts/newworld/newworld_optimizer_edge.py` | **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection |
| `scripts/newworld/newworld_optimizer_mobile.py` | **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection |
| `scripts/paknsave/paknsave_setup.py` | **Unified store builder**: Edge (57 stores) + Mobile (60 stores) + store_finder (60 stores, paknsave only). Callable module + CLI with `source` param. |
| `scripts/paknsave/paknsave_api.py` | **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities |
| `scripts/paknsave/paknsave_optimizer_edge.py` | **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection |
| `scripts/paknsave/paknsave_optimizer_mobile.py` | **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection |
| `scripts/woolworths/woolworths_setup.py` | **Unified store pipeline**: fetch choices, fetch data, merge (188 stores → 177 with coords). Replaces legacy scripts. |
| `scripts/woolworths/woolworths_api.py` | Cookie-based Woolworths API module. Session, store context, product search. Constructs `cw-lrkswrdjp` cookie from `extra1` in store data. No Playwright needed at runtime. |
| `scripts/combined/initialize_full_results.py` | Creates `data/full_results.csv` with 17-column structure including `pk_hash` for deduplication. |
| `notebooks/PaknSave_meal_cost_optimizer.ipynb` | Pak'nSave prototype |
| `notebooks/Woolworths_meal_cost_optimizer.ipynb` | Woolworths pipeline, utilizes `woolworths_optimizer.py` |
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
- Uses the same Foodstuffs mobile API as Pak'nSave with `banner: "MNW"` and `User-Agent: NewWorldApp/4.32.0`. Uses the unified `scripts/foodstuffs/Foodstuffs_api.py` module for both brands.
- Prices from the New World API are in **cents** — divide by 100 for dollars.
- 149 stores with coordinates and store IDs from the mobile API — no Nominatim geocoding needed.
- **Edge API two-pass pipeline**: Uses website JWT (`fs-user-token` cookie) for auth — works.
- 7 stores missing URLs due to name mismatches between API and store-finder page (e.g., "Metro Auckland" vs "Metro Queen Street", macron differences). URLs are only for website linking, not for the API optimizer.
- **New World store setup**: `scripts/newworld/newworld_setup.py` supports two sources: `edge` (148 stores), `mobile` (149 stores, legacy). Mirrors `paknsave_setup.py` structure. store_finder is only valid for `paknsave`.

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
- **`full_results.csv` is append-only**: New rows are added per run; duplicates detected via `pk_hash` (SHA-256 of `store_id|sku|date_created`). Avoid editing in Excel — blank rows corrupt the file.
- **`--distance` flag**: `--distance 5` sets search radius in km (default 2).

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
- **Mobile API working**: `api-prod.prod.fsniwaikato.kiwi/prod` with `banner: "MNW"` and `User-Agent: NewWorldApp/4.32.0` returns 149 stores with coordinates and store IDs.
- **No Nominatim geocoding needed**: All 149 stores have coordinates from the mobile API — eliminates the 22 stores that were missing coordinates via Nominatim.
- **New World Edge API two-pass pipeline**: Pass 1 uses Algolia `products-index` (relevance matching via `_highlightResult.matchedWords`); Pass 2 uses `paginated/products` with Algolia `filters` for per-store pricing. Pet food filtering via `category1` to exclude `Dog/Cat/Pet`. See `NewWorld_API.md` section 6 for full details.
- **Store listing**: `GET /v1/edge/store` — 148 stores (HTTP 200)
- **Categories**: `GET /v1/edge/store/{id}/categories` — works
- **Category1 exposed in Algolia hits**: enables category-based filtering (e.g., excluding pet food for "beef mince")
- **Auth**: Website JWT (from `POST /api/user/get-current-user` → `fs-user-token` cookie) OR mobile API token
- **Store context**: Cookies `eCom_STORE_ID`, `STORE_ID_V2`, `Region`
- **Sort**: `PRICE_ASC`, `PRICE_DESC`
- **Edge API can fully replace mobile API** — no dependency on Foodstuffs mobile endpoint
- **7 stores missing URLs**: Name mismatches (URLs only for website linking).
- **Two-pass pipeline implementation**: See `NewWorld_API.md` section 6 and `scripts/newworld/Exploration/`.

## Pak'nSave Research Status

- **Per-store pricing CONFIRMED**: Native per-store pricing via store ID in URL path — no cookie tricks needed. Different stores return different prices.
- **Mobile API working**: `api-prod.prod.fsniwaikato.kiwi/prod` with `banner: "PNS"` and `User-Agent: PAKnSAVEApp/4.32.0` returns 60 stores with coordinates and store IDs.
- **Pak'nSave Edge API two-pass pipeline**: Pass 1 uses Algolia `products-index` (relevance sorted, `_highlightResult.matchedWords`); Pass 2 uses `paginated/products` with Algolia `filters` for per-store pricing. Pet food filtering via `category1` to exclude `Dog/Cat/Pet`. See `PaknSave_API.md` section 6 for full details.
- **Edge API can fully replace mobile API** — no dependency on Foodstuffs mobile endpoint
- **Unified production modules**: `paknsave_api.py` (both backends), `paknsave_optimizer_edge.py` (two-pass + unit-price), `paknsave_optimizer_mobile.py` (single-pass)
- store_finder is only valid for Pak'nSave
- See `PaknSave_API.md` section 9 for store setup details and `PaknSave_API.md` section 6 for the full Edge API endpoint reference.

## NZ Scope

All addresses, supermarkets, and data are New Zealand only. First target: Pak'nSave, expanding to New World and Woolworths NZ.

## Git Rules

- **Always pause and ask for confirmation** before running `git push` or `git pull`. Never auto-execute these commands.

## File permission rules

- **Never access an external directory unless invoking skills**. All files runs must be in the project directory. Always access files from the project root, and never read files from the user directory.
