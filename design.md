# Technical Design

## Architecture Overview

```
User input (address + dish)
  → Geocode address to lat/lon
  → Haversine filter (stores within 5 km)
  → Dish name → ingredient list (DISH_INGREDIENTS map)
  → Foodstuffs Edge API (default): two-pass search per ingredient at each nearby store
    → PASS 1: Relevance via Algolia products-index (matchedWords + pet food filtering)
    → PASS 2: Per-store pricing via paginated/products (Algolia filters + PRICE_ASC)
  → (Fallback: Mobile API single-pass)
  → Aggregate prices, compare totals, display cheapest
```

## Pak'nSave API Modules

### 1. `paknsave_api.py` — Unified API Client

Supports two backends:

| Backend | Class | Auth | Pipeline |
|---------|-------|------|----------|
| **Edge API** (default) | `PaknSaveEdgeAPI` | Website JWT (`fs-user-token`) | Two-pass: relevance + per-store pricing |
| **Mobile API** (fallback) | `PaknSaveMobileAPI` | Guest token (30 min) | Single-pass |

Unified interface via `PaknSaveAPI(backend="edge"|"mobile")`.

**Core methods:**
- `api.search_ingredient(store_id, ingredient)` — returns enriched product list
- `api.get_stores()` — returns store list
- `PknSaveEdgeAPI.pass1_relevance_search()` — PASS 1: productIDs with matchedWords
- `PknSaveEdgeAPI.pass2_per_store_pricing()` — PASS 2: per-store prices sorted PRICE_ASC
- `PknSaveEdgeAPI.extract_price()` — price in dollars (promo if available)
- `PknSaveEdgeAPI.extract_unit_price()` — unit price string (e.g., "$19.99/kg")

**Shared utilities:**
- `geocode(address)` — Nominatim (rate limited)
- `haversine(lat1, lon1, lat2, lon2)` — distance in km
- `load_stores()` — from `data/paknsave_stores.csv`
- `find_nearby_stores(lat, lon, radius_km=5)` — filtered & sorted
- `get_ingredients(dish_name)` — 21-dish ingredient map

### 2. `paknsave_optimizer_edge.py` — Edge API Optimizer (Production)

```bash
python scripts/paknsave/paknsave_optimizer_edge.py "Botany Town Centre, Auckland" "spaghetti bolognese"
```

**Pipeline:**
1. Geocode address → lat/lon
2. Load stores from CSV → haversine filter (5km)
3. Authenticate Edge API (website JWT)
4. For each nearby store:
   - For each ingredient:
     - PASS 1: `products-index` relevance search → filter pet food (`category1`)
     - PASS 2: `paginated/products` with Algolia filters + `PRICE_ASC`
   - Pick cheapest by **unit price** (fallback: absolute price)
5. Output: cost comparison + itemized breakdown → `data/paknsave_latest_results.csv`

### 3. `paknsave_optimizer_mobile.py` — Mobile API Optimizer (Fallback)

```bash
python scripts/paknsave/paknsave_optimizer_mobile.py "Botany Town Centre, Auckland" "spaghetti bolognese"
```

Same structure but uses Mobile API (single-pass, guest token). No per-store price sort — returns first result. Same unit-price selection logic.

---

## Foodstuffs Mobile API (Legacy / Fallback)

Base URL: `https://api-prod.prod.fsniwaikato.kiwi/prod`

### PAKnSAVE Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/mobile/user/login/guest` | POST | Guest auth. Body: `{"banner": "PNS"}` |
| `/mobile/store/physical` | GET | List all 60 stores (needs auth headers) |
| `/mobile/ecomm-products/PNS/{storeId}/search?q={query}` | POST | Search products. Body: `[]` |

### PAKnSAVE Auth Flow

1. POST to `/mobile/user/login/guest` with `{"banner": "PNS"}` and `User-Agent: PAKnSAVEApp/4.32.0`
2. Response contains `access_token` (valid 1800s / 30 min)
3. All subsequent requests need both headers:
   - `Authorization: Bearer {token}`
   - `access_token: {token}`
4. Token is auto-refreshed by `PaknSaveAPI._ensure_token()` when expired

### PAKnSAVE Product Search Response

```json
{
  "totalHits": 10,
  "page": 1,
  "numberOfPages": 1,
  "products": [
    {
      "name": "NZ Beef Mince",
      "brand": "Pams",
      "price": 1899,        // cents
      "units": "kg",
      "productId": "...",
      "categories": [...],
      "productImageUrls": [...]
    }
  ]
}
```

- **Prices are in cents** — divide by 100 for display.
- Results sorted by relevance, not price. Always take `products[0]` (most relevant).
- `cloudscraper` is NOT needed for API calls — no Cloudflare on the API domain.

### PAKnSAVE Store Data Sources

1. **Mobile API** (`/mobile/store/physical`): 60 stores, precise coords, accurate names. Returns `{"stores": [...]}`.
2. **CSV fallback** (`data/paknsave_stores.csv`): pre-built from `/store-finder` page's `__NEXT_DATA__`. Same `store_id` UUIDs as API.
3. **Build process** (`scripts/paknsave/paknsave_setup.py`): unified callable module with two sources:
   - `fetch_stores(source="store_finder")`: extracts `contentstackStores` (GUIDs) and `store_finder.regionStoreGroupings` (names, addresses, coordinates) — joined on the shared `url` field → 60 stores.
   - `fetch_stores(source="edge")`: GET website JWT → `fs-user-token` cookie → GET `/v1/edge/store` → 57 stores with coords (3 stores not on Edge API).

## Store Building Pipeline

```
paknsave_setup.py (unified)
  → fetch_stores(source="store_finder"):  # 60 stores
      GET www.paknsave.co.nz/store-finder → parse __NEXT_DATA__
      → Extract contentstackStores: url → store_id (GUID) map
      → Extract store_finder.regionStoreGroupings: title, address, lat/lon per store
      → Join on url field → DataFrame → data/paknsave_stores.csv
      → Returns 60 stores (all have coordinates, no cleaning needed)
  → fetch_stores(source="edge"):         # 57 stores
      GET website JWT via get-current-user → fs-user-token cookie
      → GET /v1/edge/store with JWT + Origin headers
      → Returns 57 stores with coords (3 stores not on Edge API)
  → clean_stores(cleaned=True):
      Drops rows without lat/lon (no-op for both sources — all have coords)
      → Saves paknsave_stores.csv / paknsave_stores.json
```

CLI:
```
python -m scripts.paknsave.paknsave_setup [store_finder|edge]
```

Module:
```python
from scripts.paknsave.paknsave_setup import fetch_stores, run_full_setup

# Store-finder (60 stores)
run_full_setup(source="store_finder")

# Edge API (default, 57 stores)
run_full_setup(source="edge")

# Or use fetch_stores directly
df = fetch_stores(source="edge")
```

### Pak'nSave Unified API Module (`paknsave_api.py`)

A unified, callable API client supporting two backends:

| Backend | Auth | Pipeline | Use Case |
|---------|------|----------|----------|
| **Edge API** (default) | Website JWT (`fs-user-token`) | Two-pass (relevance + per-store pricing) | Production — explicit relevance, pet food filtering, PRICE_ASC sort |
| **Mobile API** (fallback) | Guest token (30 min) | Single-pass (relevance only) | Fallback — simpler, no per-store price sort |

```python
from scripts.paknsave.paknsave_api import (
    PaknSaveAPI,
    PaknSaveEdgeAPI,
    PaknSaveMobileAPI,
    load_stores,
    geocode,
    find_nearby_stores,
    get_ingredients,
    haversine,
)

# Default: Edge API (two-pass)
api = PaknSaveAPI(backend="edge")
api.client.authenticate()  # website JWT

# Fallback: Mobile API (single-pass)
api = PaknSaveAPI(backend="mobile")

# Search ingredient at store
products = api.search_ingredient(store_id, "beef mince")

# Low-level Edge API (two-pass manually)
edge = PaknSaveEdgeAPI()
edge.authenticate()
product_ids = edge.pass1_relevance_search(store_id, "beef mince")
products = edge.pass2_per_store_pricing(store_id, "beef mince", product_ids)

# Utility functions
stores = load_stores()                    # from data/paknsave_stores.csv
lat, lon = geocode("Botany, Auckland")
nearby = find_nearby_stores(lat, lon, 5)  # within 5km
ingredients = get_ingredients("spaghetti bolognese")
```

**Core Classes:**
- `PaknSaveAPI` — Unified interface, selects backend
- `PaknSaveEdgeAPI` — Full two-pass pipeline with pet food filtering
- `PaknSaveMobileAPI` — Legacy single-pass mobile API

### Pak'nSave Optimizers

#### Edge API Optimizer (`paknsave_optimizer_edge.py`)

```bash
python scripts/paknsave/paknsave_optimizer_edge.py "Botany Town Centre, Auckland" "spaghetti bolognese"
```

**Pipeline:**
1. Geocode address → lat/lon
2. Load stores from `paknsave_stores.csv` → filter by haversine distance (5km)
3. Authenticate with Edge API (website JWT)
4. For each nearby store, two-pass search per ingredient:
   - PASS 1: Relevance via `products-index` + `_highlightResult.matchedWords`
   - PASS 2: Per-store pricing via `paginated/products` + Algolia filters + `PRICE_ASC`
   - Pet food filtering via `category1` exclusion (`Dog`, `Cat`, `Pet`)
5. Pick cheapest by **unit price** (falls back to absolute price)
6. Output: cost comparison table + itemized breakdown → saves `data/paknsave_latest_results.csv`

#### Mobile API Optimizer (`paknsave_optimizer_mobile.py`)

```bash
python scripts/paknsave/paknsave_optimizer_mobile.py "Botany Town Centre, Auckland" "spaghetti bolognese"
```

**Pipeline:** Same as Edge but uses Mobile API (single-pass, guest token). No per-store price sort — returns first (most relevant) result. Same unit-price selection logic. Saves `data/paknsave_mobile_latest_results.csv`.

---

## Pak'nSave Edge API Architecture (Recommended)

### How It Works

```
User input (address + dish)
  → Geocode address to lat/lon (Nominatim)
  → Haversine filter (stores within 5 km from paknsave_stores.csv)
  → Dish name → ingredient list (DISH_INGREDIENTS map, 21 dishes)
  → Get website JWT via get-current-user → fs-user-token cookie
  → FOR EACH nearby store:
      → FOR EACH ingredient:
          PASS 1 — Relevance (Algolia products-index):
            POST /v1/edge/search/products/query/index/products-index
            Body: {"algoliaQuery": {"query": "beef mince"}, "page": 0, "hitsPerPage": 20, "storeId": "..."}
            → Extract productIDs where _highlightResult has non-empty matchedWords
            → Filter by category1 to exclude pet food (Dog, Cat, Pet)
          
          PASS 2 — Per-Store Pricing (Paginated with filters):
            POST /v1/edge/search/paginated/products
            Body: {"algoliaQuery": {"query": "beef mince", "filters": "productID:xxx OR productID:yyy"}, "sortOrder": "PRICE_ASC"}
            → Returns singlePrice.price (cents) + promotions[].rewardValue
            → Sorted by price at THIS store
  → Aggregate prices, compare totals, display cheapest
```

### Edge API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/user/get-current-user` | POST | Get website JWT (fs-user-token cookie) |
| `/v1/edge/store` | GET | List all 57 stores (needs JWT + Origin headers) |
| `/v1/edge/search/products/query/index/products-index` | POST | **Relevance search (Algolia)** — Pass 1 |
| `/v1/edge/search/paginated/products` | POST | **Per-store pricing** — Pass 2 |
| `/v1/edge/store/{store_id}/categories` | GET | Category tree for store |

### Edge API Auth Flow

1. `GET https://www.paknsave.co.nz` — seed cookies (Cloudflare, session)
2. `POST https://www.paknsave.co.nz/api/user/get-current-user` — returns `fs-user-token` cookie (JWT)
3. All subsequent Edge API requests need both headers:
   - `Authorization: Bearer {token}`
   - `access_token: {token}`
4. Plus Origin/Referer headers:
   - `Origin: https://www.paknsave.co.nz`
   - `Referer: https://www.paknsave.co.nz/`

### Store Context Cookies

```python
cookies = {
    "eCom_STORE_ID": store_id,
    "STORE_ID_V2": f"{store_id}|False",
    "Region": "NI"  # or "SI" for South Island
}
```

### Two-Pass Pipeline Code

```python
def two_pass_search(token, store_id, query, max_relevance=20):
    """
    Complete two-pass pipeline: Relevance -> Per-Store Pricing
    """
    EDGE_BASE = "https://api-prod.paknsave.co.nz/v1/edge"
    WEB_BASE = "https://www.paknsave.co.nz"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0",
    }
    cookies = {
        "eCom_STORE_ID": store_id,
        "STORE_ID_V2": f"{store_id}|False",
        "Region": "NI",
    }
    
    # PASS 1: Relevance matching
    url1 = f"{EDGE_BASE}/search/products/query/index/products-index"
    payload1 = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": max_relevance,
        "storeId": store_id
    }
    r1 = requests.post(url1, headers=headers, json=payload1, cookies=cookies)
    hits = r1.json().get("hits", [])
    
    # Extract productIDs with relevance matches (exclude pet food)
    pet_categories = {"Dog", "Cat", "Pet"}
    product_ids = []
    for hit in hits:
        hr = hit.get("_highlightResult", {})
        matched = [f for f, v in hr.items() if isinstance(v, dict) and v.get("matchedWords")]
        cat1 = hit.get("category1", [])
        if matched and not any(c in pet_categories for c in cat1):
            product_ids.append(hit["productID"])
    
    # PASS 2: Per-store pricing with Algolia filters
    url2 = f"{EDGE_BASE}/search/paginated/products"
    filter_str = " OR ".join([f"productID:{pid}" for pid in product_ids])
    payload2 = {
        "algoliaQuery": {"query": query, "filters": filter_str},
        "page": 0,
        "hitsPerPage": 50,
        "storeId": store_id,
        "sortOrder": "PRICE_ASC"
    }
    r2 = requests.post(url2, headers=headers, json=payload2, cookies=cookies)
    return r2.json().get("products", [])
```

### Key Constraints

- **Two-pass required**: No single endpoint gives both relevance + per-store pricing
- **Pet food filtering**: Must filter by `category1` in Pass 1 to exclude Dog/Cat/Pet
- **Fresh JWT required**: Website JWT expires after ~30 minutes
- **Region cookie**: Use "NI" for North Island, "SI" for South Island
- **Prices in cents**: Divide `singlePrice.price` by 100 for dollars

### Edge API vs Mobile API

| Feature | Mobile API | Edge API (Two-Pass) |
|---------|------------|---------------------|
| Relevance matching | Implicit (first result) | Explicit `_highlightResult.matchedWords` |
| Per-store pricing | Native (storeId in URL) | Via cookies + Algolia filters |
| Price sorting | PriceAsc only | PRICE_ASC, PRICE_DESC |
| Promotions | Included | Included (`rewardValue`) |
| Auth | Mobile guest token | Website JWT OR mobile token |
| Dependency | Internal Foodstuffs API | Public website API (more stable) |
| Pet food filtering | Not available | Via `category1` in Pass 1 |

## New World Edge API Architecture

### How It Works

```
User input (address + dish)
  → Geocode address to lat/lon (Nominatim)
  → Haversine filter (stores within 5 km from newworld_stores.csv)
  → Dish name → ingredient list (DISH_INGREDIENTS map, 21 dishes)
  → Get website JWT via get-current-user → fs-user-token cookie
  → FOR EACH nearby store:
      → FOR EACH ingredient:
          PASS 1 — Relevance (Algolia products-index):
            POST /v1/edge/search/products/query/index/products-index
            Body: {"algoliaQuery": {"query": "beef mince"}, "page": 0, "hitsPerPage": 20, "storeId": "..."}
            → Extract productIDs where _highlightResult has non-empty matchedWords
            → NO pet food filtering needed (only default index has relevance)
          
          PASS 2 — Per-Store Pricing (Paginated with filters):
            POST /v1/edge/search/paginated/products
            Body: {"algoliaQuery": {"query": "beef mince", "filters": "productID:xxx OR productID:yyy"}, "sortOrder": "PRICE_ASC"}
            → Returns singlePrice.price (cents) + promotions[].rewardValue
            → Sorted by price at THIS store
  → Aggregate prices, compare totals, display cheapest
```

### New World Edge API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/user/get-current-user` | POST | Get website JWT (fs-user-token cookie) |
| `/v1/edge/store` | GET | List all 148 stores (needs JWT + Origin headers) |
| `/v1/edge/search/products/query/index/products-index` | POST | **Relevance search (Algolia)** — Pass 1 |
| `/v1/edge/search/paginated/products` | POST | **Per-store pricing** — Pass 2 |
| `/v1/edge/store/{store_id}/categories` | GET | Category tree for store |

### New World Edge API Auth Flow

1. `GET https://www.newworld.co.nz` — seed cookies (Cloudflare, session)
2. `POST https://www.newworld.co.nz/api/user/get-current-user` — returns `fs-user-token` cookie (JWT)
3. All subsequent Edge API requests need both headers:
   - `Authorization: Bearer {token}`
   - `access_token: {token}`
4. Plus Origin/Referer headers:
   - `Origin: https://www.newworld.co.nz`
   - `Referer: https://www.newworld.co.nz/`

### New World Store Context Cookies

```python
cookies = {
    "eCom_STORE_ID": store_id,
    "STORE_ID_V2": f"{store_id}|False",
    "Region": "NI"  # or "SI" for South Island
}
```

### New World Two-Pass Pipeline Code

```python
def newworld_two_pass_search(token, store_id, query, max_relevance=20):
    """
    Complete two-pass pipeline: Relevance -> Per-Store Pricing
    """
    EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"
    WEB_BASE = "https://www.newworld.co.nz"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0",
    }
    cookies = {
        "eCom_STORE_ID": store_id,
        "STORE_ID_V2": f"{store_id}|False",
        "Region": "NI",
    }
    
    # PASS 1: Relevance matching
    url1 = f"{EDGE_BASE}/search/products/query/index/products-index"
    payload1 = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": max_relevance,
        "storeId": store_id
    }
    r1 = requests.post(url1, headers=headers, json=payload1, cookies=cookies)
    hits = r1.json().get("hits", [])
    
    # Extract productIDs with relevance matches
    # NOTE: New World only has relevance in default index, no pet food filtering needed
    product_ids = []
    for hit in hits:
        hr = hit.get("_highlightResult", {})
        if any(isinstance(v, dict) and v.get("matchedWords") for v in hr.values()):
            product_ids.append(hit["productID"])
    
    # PASS 2: Per-store pricing with Algolia filters
    url2 = f"{EDGE_BASE}/search/paginated/products"
    filter_str = " OR ".join([f"productID:{pid}" for pid in product_ids])
    payload2 = {
        "algoliaQuery": {"query": query, "filters": filter_str},
        "page": 0,
        "hitsPerPage": 50,
        "storeId": store_id,
        "sortOrder": "PRICE_ASC"
    }
    r2 = requests.post(url2, headers=headers, json=payload2, cookies=cookies)
    return r2.json().get("products", [])
```

### New World Key Constraints

- **Two-pass required**: No single endpoint gives both relevance + per-store pricing
- **NO pet food filtering needed**: Only the default `products-index` has relevance matching (unlike Pak'nSave where all 3 indices have matches)
- **Fresh JWT required**: Website JWT expires after ~30 minutes
- **Region cookie**: Use "NI" for North Island, "SI" for South Island
- **Prices in cents**: Divide `singlePrice.price` by 100 for dollars
- **148 stores vs 149 mobile API**: 1 store missing from Edge API (name mismatch)

### New World Edge API vs Mobile API

| Feature | Mobile API | Edge API (Two-Pass) |
|---------|------------|---------------------|
| Relevance matching | Implicit (first result) | Explicit `_highlightResult.matchedWords` |
| Per-store pricing | Native (storeId in URL) | Via cookies + Algolia filters |
| Price sorting | PriceAsc only | PRICE_ASC, PRICE_DESC |
| Promotions | Included | Included (`rewardValue`) |
| Auth | Mobile guest token | Website JWT OR mobile token |
| Dependency | Internal Foodstuffs API | Public website API (more stable) |
| Pet food filtering | Not available | Not needed (only default index has relevance) |
| Store count | 149 stores | 148 stores (1 missing) |

### New World vs Pak'nSave Edge API

| Feature | New World | Pak'nSave |
|---------|-----------|-----------|
| Edge API domain | `api-prod.newworld.co.nz` | `api-prod.paknsave.co.nz` |
| Website domain | `www.newworld.co.nz` | `www.paknsave.co.nz` |
| Store count | 148 stores | 57 stores |
| Pet food filtering | Not needed | Required via `category1` |
| Relevance indices | Only `products-index` | All 3 indices have matches |
| Mobile API banner | `MNW` | `PNS` |
| User-Agent (mobile) | `NewWorldApp/4.32.0` | `PAKnSAVEApp/4.32.0` |
| Missing stores | 1 (name mismatch) | 3 (not configured for Edge API) |

## Store Distance

- Haversine formula calculates great-circle distance between user lat/lon and each store's coordinates
- Default radius: 5 km
- Stores sorted by distance ascending

## Ingredient Mapping

- `DISH_INGREDIENTS` dict in `scripts/prototype.py` (and notebook cell 4)
- 21 dishes, each mapping to a list of search query strings
- Unknown dishes fall through: the dish name itself becomes the single search query
- No NLP/LLM parsing — entirely hand-curated

### Supported Dishes (21)

| Dish | Ingredients |
|---|---|
| spaghetti bolognese | beef mince, spaghetti pasta, canned tomatoes, onion, carrot, garlic, mixed herbs |
| chicken stir fry | chicken breast, stir fry vegetables, soy sauce, rice noodles |
| beef stir fry | beef strips, stir fry vegetables, soy sauce, rice noodles |
| roast lamb | lamb roast, potato, carrot, broccoli, stock |
| chicken curry | chicken thigh, curry paste, coconut milk, rice, onion |
| beef curry | diced beef, curry paste, coconut milk, rice, onion |
| fish and chips | fish fillet, potato, oil |
| nachos | beef mince, tortilla chips, cheese, beans, sour cream |
| pumpkin soup | pumpkin, onion, cream, stock, bread |
| tacos | beef mince, taco shells, lettuce, tomato, cheese, sour cream |
| lamb chops | lamb chops, potato, mint sauce |
| butter chicken | chicken thigh, butter chicken sauce, rice, cream |
| lasagne | beef mince, lasagne sheets, cheese, canned tomatoes, milk, butter, flour |
| shepherd's pie | beef mince, potato, carrot, peas, stock |
| pizza | pizza base, pizza sauce, cheese, pepperoni |
| vegie stir fry | stir fry vegetables, tofu, soy sauce, rice noodles, garlic |
| frittata | eggs, potato, onion, cheese, milk |
| pancakes | flour, eggs, milk, sugar, butter |
| chicken soup | chicken breast, carrot, onion, celery, stock, pasta |
| tomato pasta | pasta, canned tomatoes, garlic, olive oil, mixed herbs, cheese |
| chicken katsu | chicken breast, flour, eggs, bread, rice, katsu sauce |

To add a dish: edit `DISH_INGREDIENTS` in `scripts/paknsave/paknsave_api.py` (or notebook cell 4).

## CLI Usage

**Edge API Optimizer (Production — two-pass, relevance + price sort):**
```powershell
python scripts/paknsave/paknsave_optimizer_edge.py "Botany Town Centre, Auckland" "spaghetti bolognese"
```

**Mobile API Optimizer (Fallback — single-pass):**
```powershell
python scripts/paknsave/paknsave_optimizer_mobile.py "Botany Town Centre, Auckland" "spaghetti bolognese"
```

Args: `[address] [dish name]`. Defaults to "Botany Town Centre, Auckland" and "spaghetti bolognese".

**Store Setup Pipeline:**
```powershell
python -m scripts.paknsave.paknsave_setup              # Edge API (default, 57 stores)
python -m scripts.paknsave.paknsave_setup store_finder  # Store-finder page (60 stores)
```

## Woolworths API Architecture

### How It Works

```
User input (address + dish)
  → Geocode address to lat/lon (Nominatim)
  → Haversine filter (stores within 5 km from woolworths_store_data.json)
  → Dish name → ingredient list (DISH_INGREDIENTS map, 21 dishes)
  → FOR EACH nearby store:
      → Create fresh requests.Session + GET / to seed cookies
      → Inject cw-lrkswrdjp cookie (constructed from extra1)
      → Validate via /api/v1/shell (fulfilmentStoreId != 9171)
      → Search each ingredient via /api/v1/products?target=search
      → Collect per-store prices
  → Aggregate prices, compare totals, display cheapest
```

### Woolworths API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/shell` | GET | Navigation taxonomy, session context, fulfilment details |
| `/api/v1/products?target=search&search=<term>` | GET | Product search with prices |
| `/api/v1/products?target=browse&dasFilter=Department;;<slug>;false` | GET | Browse by department |
| `/api/v1/addresses/pickup-addresses` | GET | All pickup stores (id, name, address) |

### Required Headers

```
x-requested-with:  ??           <- literal string, not a placeholder
User-Agent:        Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...
Accept:            application/json, text/plain, */*
```

### Cookie-Based Store Context

The `cw-lrkswrdjp` cookie controls per-store pricing:
```
dm-Pickup,f-{fulfilmentStoreId},a-{areaId},s-38
```

- `fulfilmentStoreId` = `extra1` from `woolworths_store_data.json` (NOT the same as `pickupAddressId`)
- `areaId` is optional (cookie works without it)
- `s-38` is constant across all stores

### woolworths_api.py Module

```python
from woolworths_api import create_session, set_store_context, search_products, find_cheapest, get_nearby_stores, geocode

# Geocode address
lat, lon = geocode("123 Queen Street, Auckland")

# Find nearby stores
stores = get_nearby_stores(lat, lon, max_dist_km=5)

# Search with per-store pricing
for store in stores:
    session = create_session()  # fresh session per store (required!)
    set_store_context(session, store["pickupAddressId"])
    cheapest = find_cheapest(session, "beef mince")
    print(f"{store['name']}: ${cheapest['salePrice']}")
```

### Key Constraints

- **Fresh session per store**: The server's `Set-Cookie` response overwrites injected cookies on reused sessions
- **No login required**: Public API endpoints work with unauthenticated sessions
- **Search returns relevance, not cheapest**: Take first result for practical matches
- **21 hand-curated dishes**: No NLP/LLM parsing yet

### Woolworths Store Setup Pipeline

```
woolworths_setup.py (unified)
  → fetch_store_choices():
      GET /api/v1/addresses/pickup-addresses
      → Iterate ALL 19 storeAreas, dedupe by id
      → Returns 188 unique pickup locations (includes stores only in regional areas, e.g. Chartwell)
      → Saves woolworths_store_choices.csv/json
  → fetch_store_data():
      GET https://api.cdx.nz/site-location/api/v1/sites
      → 183 stores with lat/lon, extra1 (fulfilmentStoreId), extra2 (pickupAddressId)
      → Saves woolworths_store_data.csv/json
  → merge_stores(cleaned=True):
      Left join choices.id = data.SiteDataID
      → 188 merged stores (177 with lat/lon, 11 dropped)
      → Saves woolworths_stores.csv
```

## Notebook Usage

| Cells | What to do |
|---|---|
| 1–4 | **Setup** — run once. Loads dependencies, API client, geocoding helpers, ingredient list. |
| 5 | *Markdown instructions* — read only. |
| 6 | **Main run cell**. Edit `USER_ADDRESS` and `DISH_NAME` at the top, then run. |
| 7 | Displays cheapest store's itemised list in a formatted table. |

### Example

```
USER_ADDRESS = "Botany Town Centre, Auckland 2013"
DISH_NAME = "spaghetti bolognese"
```

Output:
- 3 stores found within 5 km (Botany, Highland Park, Ormiston)
- 7 ingredients searched at each store
- Cheapest: PAK'nSAVE Botany at $29.03

## Known Limitations

- **Unit sizes**: Prices shown for full units (e.g., whole kg of mince). A recipe may use less, so your actual cost is lower.
- **Garlic pricing**: Loose garlic is per-kg ($40+). Crushed garlic jar ($2–3) is more practical and sometimes returned instead.
- **Store density**: Auckland CBD has 1 store within 5 km. East Auckland (Botany/Manukau) has 3.
- **Woolworths fresh session per store**: Each nearby store requires a separate `requests.Session` — cannot reuse one session across stores.
- **Woolworths search relevance**: Generic terms like "garlic" or "mixed herbs" may return unrelated products (e.g., gravy mix for "herbs"). Ingredient queries need to be specific.
- **Woolworths per-store pricing differences are small for nearby stores**: Auckland stores show $0.00-$0.20 differences per ingredient. Differences are larger for distant stores (e.g., Greymouth vs Glenfield: $0.18 for 3L milk).
