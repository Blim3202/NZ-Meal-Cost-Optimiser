# NZ Meal Cost Optimizer

Finds the cheapest Pak'nSave, New World, or Woolworths for a given dish by comparing ingredient prices across nearby stores (within 5 km of a NZ address).

## How It Works

1. Geocode address to lat/lon (Nominatim)
2. Filter stores within 5 km (Haversine)
3. Map dish to ingredients (21 hand-curated dishes, see Dish Coverage below)
4. Search each ingredient at each store via API
5. Compare totals, display cheapest

## Supported Stores

| Store | Backends | Stores | Per-Store Pricing | Status |
|-------|----------|--------|-------------------|--------|
| Pak'nSave | Edge API (two-pass), Mobile API (single-pass) | 57 Edge / 60 Mobile / 60 store_finder | Yes | Active |
| New World | Edge API (two-pass), Mobile API (single-pass) | 148 Edge / 150 Mobile | Yes | Active |
| Woolworths | REST API (cookie injection) | 177 with coords | Yes | Active |

- Pak'nSave and New World share a unified Foodstuffs backend (`scripts/combined/optimizer_utils.py` + brand-specific API modules)
- Woolworths uses cookie-based store context injected per-store (no shared backend)
- New World stores have coordinates from the mobile API — no Nominatim geocoding needed for store lookup
- Pak'nSave Edge API requires pet food filtering via `category1` (exclude Dog/Cat/Pet) in Pass 1

## Quick Start

```powershell
# Setup
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run optimizer (Pak'nSave Edge API — two-pass with unit-price selection)
python scripts/paknsave/paknsave_optimizer_edge.py "Botany Town Centre, Auckland" "spaghetti bolognese"

# Run optimizer (New World Edge API — two-pass with unit-price selection)
python scripts/newworld/newworld_optimizer_edge.py "Botany Town Centre, Auckland" "spaghetti bolognese"

# Run optimizer (Woolworths — cookie-based per-store pricing)
python scripts/woolworths/woolworths_optimizer.py "Botany Town Centre, Auckland" "spaghetti bolognese"
```

## Architecture

### Pak'nSave / New World (Foodstuffs Backend)

Both brands use the same Foodstuffs API structure with two backends:

**Edge API (two-pass pipeline):**
```
GET website → POST get-current-user → JWT token (fs-user-token cookie)
  → FOR EACH store:
    → FOR EACH ingredient:
      PASS 1: POST /search/products/query/index/products-index (Algolia)
        → Extract productIDs with relevance matches
      PASS 2: POST /search/paginated/products (with Algolia filters)
        → Returns per-store pricing, unit prices
```

**Mobile API (single-pass pipeline):**
```
GET /v1/edge/store → store list with coordinates
  → FOR EACH store:
    → FOR EACH ingredient:
      POST /v1/edge/search (single request with store context)
        → Returns per-store pricing directly
```

### Woolworths (Cookie-Based)

```
GET / → session cookies
  → Construct cw-lrkswrdjp cookie from store data (extra1 = fulfilmentStoreId)
  → FOR EACH store:
    → Fresh session per store (required — Set-Cookie overwrites injected cookies)
    → Search /api/v1/products?target=search
```

## Project Structure

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
│   ├── woolworths_latest_results.csv           # Last optimizer output for Woolworths
│   ├── paknsave_latest_results.csv             # Last Edge optimizer output
│   ├── paknsave_mobile_latest_results.csv      # Last Mobile optimizer output
│   ├── observed_category1_newworld.json         # Category1 values from New World Algolia index
│   ├── observed_category1_paknsave.json         # Category1 values from Pak'nSave Algolia index
│   ├── dishes.json                              # 21 hand-curated dishes with structured ingredients
│   └── full_results.csv                         # Append-only results with pk_hash deduplication + is_valid column
├── notebooks/
│   ├── PaknSave_meal_cost_optimizer.ipynb      # Pak'nSave Jupyter prototype (8 cells, run cell 6 with inputs)
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
│   │   └── Exploration/                         # API exploration scripts (legacy)
│   ├── paknsave/
│   │   ├── paknsave_api.py                     # **Unified API module**: Edge API (two-pass) + Mobile API (single-pass) with shared utilities
│   │   ├── paknsave_optimizer_edge.py           # **Edge API optimizer**: CLI with geocoding, 5km radius, two-pass search, unit-price selection
│   │   ├── paknsave_optimizer_mobile.py         # **Mobile API optimizer**: CLI with geocoding, 5km radius, single-pass search, unit-price selection
│   │   ├── paknsave_setup.py                    # **Unified store builder**: Edge (57 stores) + Mobile (60 stores) + store_finder (60 stores, Pak'nSave only). Callable module + CLI with `source` param.
│   │   └── Exploration/                         # API exploration scripts (legacy)
│   ├── woolworths/
│   │   ├── woolworths_api.py                    # Cookie-based API module: session, store context, product search
│   │   ├── woolworths_optimizer.py              # API-based optimizer: geocode, stores, pricing, cost comparison
│   │   ├── woolworths_setup.py                  # **Unified store pipeline**: fetch choices, fetch data, merge (188 stores → 177 with coords). Replaces legacy scripts.
│   │   ├── Exploration/                         # API exploration scripts (legacy)
│   │   ├── Fixture/                             # Test fixtures (legacy)
│   │   ├── Playwright/                          # Playwright-based scripts (legacy, not needed at runtime)
│   │   └── tests/                               # Unit tests (legacy)
│   └── llms/
│       ├── llm_client.py                        # Mistral API client with rate limiting + JSON retries
│       ├── llm_utils.py                         # Ingredient resolution (curated → LLM), parsing, quantity scaling
│       ├── llm_validate.py                      # Post-run search-result validation (is_valid column)
│       └── llm_interactive.py                   # Interactive CLI: ingredients → query → optimise → scale
├── AGENTS.md                                   # Agent instructions and project reference
├── NewWorld_API.md                             # New World API documentation (cross-references PaknSave_API.md)
├── PaknSave_API.md                             # Pak'nSave API documentation (primary reference)
├── Woolworths_API.md                           # Full /api/v1 endpoint documentation (1360+ lines)
├── decision.md                                 # Key decisions and rationale (includes cross-brand comparison + CommonApi endpoint list)
├── design.md                                   # Technical design (API, auth, pipeline)
├── logs.md                                     # Major errors and resolutions
├── requirements.txt                            # Pinned dependencies
└── README.md                                   # This file
```

## Dish Coverage

21 hand-curated dishes with mapped ingredients:

| Dish | Ingredients |
|------|-------------|
| Spaghetti Bolognese | beef mince, spaghetti pasta, canned tomatoes, onion, carrot, garlic, mixed herbs |
| Butter Chicken | chicken thigh/breast, butter chicken sauce, rice, cream, onion |
| Chicken Stir Fry | chicken breast, stir fry vegetables, soy sauce, rice noodles |
| Beef Stir Fry | beef strips, stir fry vegetables, soy sauce, rice noodles |
| Fish and Chips | fish fillet, potato, oil |
| Roast Lamb | lamb roast, potato, carrot, broccoli, stock |
| Chicken Curry | chicken thigh, curry paste, coconut milk, rice, onion |
| Beef Curry | diced beef, curry paste, coconut milk, rice, onion |
| Nachos | beef mince, tortilla chips, cheese, beans, sour cream |
| Pumpkin Soup | pumpkin, onion, cream, stock, bread |
| Tacos | beef mince, taco shells, lettuce, tomato, cheese, sour cream |
| Lamb Chops | lamb chops, potato, mint sauce, mixed vegetables |
| Lasagne | beef mince, lasagne sheets, cheese, canned tomatoes, milk, butter, flour |
| Shepherd's Pie | beef mince, potato, carrot, peas, stock |
| Pizza | pizza base, pizza sauce, cheese, pepperoni |
| Veggie Stir Fry | stir fry vegetables, tofu, soy sauce, rice noodles, garlic |
| Frittata | eggs, potato, onion, cheese, milk |
| Pancakes | flour, eggs, milk, sugar, butter |
| Chicken Soup | chicken breast, carrot, onion, celery, stock, pasta |
| Tomato Pasta | pasta, canned tomatoes, garlic, olive oil, mixed herbs, cheese |
| Chicken Katsu | chicken breast, flour, eggs, bread, rice, katsu sauce |

## API Reference

### Pak'nSave Edge API

- **Base URL**: `https://api-prod.paknsave.co.nz/v1/edge`
- **Auth**: Website JWT (`fs-user-token` cookie)
- **Store context**: `eCom_STORE_ID`, `STORE_ID_V2`, `Region` cookies
- **Endpoints**: See `PaknSave_API.md` section 6

### New World Edge API

- **Base URL**: `https://api-prod.newworld.co.nz/v1/edge`
- **Auth**: Website JWT (`fs-user-token` cookie)
- **Store context**: `eCom_STORE_ID`, `STORE_ID_V2`, `Region` cookies
- **Endpoints**: See `NewWorld_API.md` section 6

### Woolworths API

- **Base URL**: `https://www.woolworths.co.nz`
- **Auth**: Session cookies (no login required)
- **Store context**: `cw-lrkswrdjp` cookie (constructed from store data, `extra1` = fulfilmentStoreId)
- **Endpoints**: See `Woolworths_API.md`

## Documentation

| Doc | Purpose |
|-----|---------|
| `AGENTS.md` | Agent instructions: setup, project layout, key gotchas, research status |
| `PaknSave_API.md` | Primary API reference for Pak'nSave (shared Foodstuffs structure + Pak'nSave-specific endpoints) |
| `NewWorld_API.md` | New World-specific API reference (cross-references PaknSave_API.md for shared structure) |
| `Woolworths_API.md` | Full Woolworths `/api/v1` endpoint documentation (cookie architecture, per-store pricing) |
| `decision.md` | Key design decisions, cross-brand comparison table, CommonApi rationale |
| `design.md` | Technical design (API, auth, pipeline) |
| `logs.md` | Major errors and resolutions |
| `LLM_Pipeline.md` | LLM ingredient generation, validation, and quantity scaling pipeline |

## Limitations

- **Unit sizes**: Prices shown for full units (e.g., whole kg of mince) — unit-price selection available in Edge optimizers
- **Garlic pricing**: Loose garlic is per-kg ($40+); crushed garlic jar ($2-3) returned instead
- **Store density**: Auckland CBD has 1 store within 5 km; East Auckland has 3
- **Woolworths sessions**: Each store requires a fresh `requests.Session` (Set-Cookie overwrites injected cookies)
- **Search relevance**: Generic terms may return unrelated products; be specific with ingredient names
- **Pak'nSave Nominatim rate limit**: 1 request/second
- **Pak'nSave store_finder**: Only valid for Pak'nSave (New World has no `contentstackStores` in `__NEXT_DATA__`)
- **New World 7 missing URLs**: Name mismatches between API and store-finder page (e.g., "Metro Auckland" vs "Metro Queen Street", macron differences)

## Disclaimer

This is an experimental, personal project. Not affiliated with or endorsed by Pak'nSave, New World, Woolworths, or any supermarket chain. Functionality depends on API stability; endpoints may change without notice. Pricing data is in cents — divide by 100 for dollars (Pak'nSave and New World APIs only).
