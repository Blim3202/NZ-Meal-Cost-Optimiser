# New World Edge API Exploration Documentation

## Overview

This folder contains **14 exploration scripts** documenting the multi phase journey from initial Edge API probing to the discovery of a production-ready two-pass pipeline that combines relevance matching (Algolia) with per-store pricing.

**Key Outcome**: The Edge API **CAN fully replace** the Foodstuffs mobile API for New World — no dependency on internal mobile endpoint, uses public website JWT, explicit relevance matching via `_highlightResult`, per-store pricing via cookies + Algolia filters.

---

## Phase 1: Initial Edge API Probing — Store Listing Works, Product Search Missing

### `explore_edge_api1.py` - Initial Testing and Exploration

**Purpose**: First comprehensive test of the New World Edge API (`api-prod.newworld.co.nz/v1/edge/`).

**What it tests**:
1. **Mobile API token on Edge API** — Gets guest token from Foodstuffs mobile API (`banner: "MNW"`), tests if it works on Edge API endpoints
2. **Edge API store listing** — `GET /v1/edge/store/physical` with mobile token
3. **Product search endpoints** — Tests 8+ endpoint patterns (`/v1/edge/products/search`, `/v1/edge/ecomm-products/MNW/{storeId}/search`, `/v1/edge/store/{id}/products/search`, etc.)
4. **Comparison** — Edge API vs Mobile API store data

**Key Findings**:
- ✅ Edge store listing **WORKS** with mobile token (149 stores, same data as mobile API)
- ❌ All product search endpoints return **404**
- The `JWT-VerifyRetailEdgeToken` error is an Apigee gateway policy
- Mobile token works because both APIs share the same IdP (`online-customer`)

**Conclusion**: Edge API is NOT a viable alternative for product search at this stage. Mobile API remains the only working path.

---

### `explore_edge_api2.py` — Quick Product Search Enumeration

**Purpose**: Rapid test of additional product search endpoint patterns.

**What it tests**: Same 6 endpoints as explore_edge_api1 plus v2 variants, all with mobile token.

**Result**: All 404. Confirms no standard REST product search exists on Edge API.

---

### `explore_edge_api3.py` — Web Headers

**Purpose**: Test if web-like headers reveal product search.

**What it tests**:
- Edge API with browser headers (Origin, Referer, User-Agent)
- Website product search pages (`/search?q=milk`)
- Mobile API refresh token flow
- Additional mobile API endpoints (`/mobile/v1/products/category`, `/mobile/v1/upgrade`, etc.)

**Result**: No product search found.

---

### `explore_edge_api4.py` — Mobile API Deep Dive & Website Page Analysis

**Purpose**: Exhaustive mobile API endpoint check + Next.js page inspection.

**What it tests**:
- Mobile API refresh token
- Mobile API category/upgrade/error endpoints
- Website search page `__NEXT_DATA__` extraction
- GraphQL endpoint test
- API gateway on main domain (`/api/mobile/*`, `/api/v1/*`)

**Key Discovery**: Website uses Next.js with `__NEXT_DATA__` but product data is NOT pre-rendered — it's fetched via API at runtime.

---

### `explore_edge_api5.py` — Store Finder & Search Page Analysis

**Purpose**: Analyze `__NEXT_DATA__` from store-finder and search pages for API clues.

**What it tests**:
- Store finder page structure (`contentstackStores` + `regionStoreGroupings`)
- Product search page `__NEXT_DATA__` keys
- Homepage `__NEXT_DATA__`
- API gateway on main domain

**Result**: Store finder page structure documented (used in `fetch_stores.py`). No product search API visible in page props.

---

## Phase 2: Authentication Breakthrough — Website JWT Works

### `explore_edge_api6_auth.py` — **MAJOR BREAKTHROUGH**

**Purpose**: Test Edge API with **website session JWT** instead of mobile API token.

**What it discovers**:
1. **Website JWT flow**: `GET www.newworld.co.nz` → `POST /api/user/get-current-user` → `fs-user-token` cookie (JWT)
2. **Store listing**: `GET /v1/edge/store` works with website JWT (148 stores)
3. **Categories**: `GET /v1/edge/store/{id}/categories` works with JWT + store cookies
4. **Product search**: `POST /v1/edge/search/paginated/products` — **WORKS!** Returns per-store pricing!

**Key Discovery**: The product search endpoint is **`/v1/edge/search/paginated/products`** — an Algolia-powered endpoint, not a standard REST endpoint. It requires:
- Website JWT (`fs-user-token` cookie)
- Store context cookies: `eCom_STORE_ID`, `STORE_ID_V2`, `Region`
- Payload with `algoliaQuery`, `storeId`, `sortOrder`

**Payload format**:
```json
{
  "algoliaQuery": {"query": "milk"},
  "page": 0,
  "hitsPerPage": 20,
  "storeId": "store-uuid",
  "sortOrder": "PRICE_ASC"
}
```

**Valid sortOrder**: `PRICE_ASC`, `PRICE_DESC` (validated enum)
**Price extraction**: `singlePrice.price` (cents) + `promotions[].rewardValue` (promo cents)

---

## Phase 3: Algolia Index Discovery — Relevance Matching Exists!

### `explore_edge_api7_algolia_indices.py` — Index Enumeration

**Purpose**: Test multiple Algolia index endpoints for different sort orders.

**What it tests**: 12 index names based on common patterns:
- `products-index-popularity-asc` ✅ 200
- `products-index-popularity-desc` ✅ 200
- `products-index-relevance` ❌ 404
- `products-index-price-asc` ❌ 404
- `products-index-price-desc` ❌ 404
- `products-index-name-asc` ❌ 404
- `products-index-name-desc` ❌ 404
- `products-index-newest` ❌ 404
- `products-index-bestselling` ❌ 404
- `products-index-trending` ❌ 404
- `products-index` (default) ✅ 200
- `products` ❌ 404

**Only 3 indices return 200**: popularity-asc, popularity-desc, and the default `products-index`.

---

### `explore_edge_api8_indices_detailed.py` — Detailed Response Inspection

**Purpose**: Deep-dive into the 3 working indices to understand their structure.

**Key Finding**: **All 3 indices return identical `_highlightResult` structures with `matchedWords`** — the only difference is sort order.
- `products-index-popularity-asc`: HAS `_highlightResult` with `matchedWords`, sorted by popularity ASC
- `products-index-popularity-desc`: HAS `_highlightResult` with `matchedWords`, sorted by popularity DESC
- `products-index`: HAS `_highlightResult` with `matchedWords`, sorted by Algolia relevance (default)

---

### `explore_edge_api9_relevance.py` — **COMPREHENSIVE DOCUMENTATION**

**Purpose**: Complete exploration narrative + working two-pass pipeline implementation.

**Contains**:
- Full 6-phase discovery timeline (documented above)
- **Two-pass pipeline code**:
  - `algolia_relevance_search()` — PASS 1: Query `products-index` for relevance matches
  - `paginated_store_pricing()` — PASS 2: Query `paginated/products` with Algolia filters
  - `two_pass_search()` — Complete pipeline merging relevance + pricing
- Comparison: Mobile API vs Edge API pipelines
- Test runs for: milk, beef mince, bread, cheese

**The Two-Pass Pipeline**:

**PASS 1 — Relevance Matching** (`products-index`):
```
POST /v1/edge/search/products/query/index/products-index
Body: {"algoliaQuery": {"query": "beef mince"}, "page": 0, "hitsPerPage": 20, "storeId": "..."}
Returns: hits WITH _highlightResult.matchedWords showing which fields matched
Filter: Keep only hits where _highlightResult has non-empty matchedWords
Filter: Exclude non-food category1 values (NON_FOOD_CATEGORIES: 53 categories)
Extract: productID from matched hits
```

**PASS 2 — Per-Store Pricing** (`paginated/products` with filters):
```
POST /v1/edge/search/paginated/products
Body: {
  "algoliaQuery": {"query": "beef mince", "filters": "productID:xxx OR productID:yyy"},
  "page": 0, "hitsPerPage": 50, "storeId": "...", "sortOrder": "PRICE_ASC"
}
Returns: per-store singlePrice.price + promotions for ONLY the relevant products
```

**Bridge**: Algolia `filters` parameter accepts `productID:xxx OR productID:yyy` syntax!

---

## Phase 4: Focused Validation & Demo Scripts

### `test_milk_metro_relevance.py` — Focused Validation

**Purpose**: Single-query validation of the two-pass pipeline for "milk" at Metro Auckland.

**What it does**:
1. PASS 1: Search `products-index` for "milk" → 15 hits, all with relevance matches
2. PASS 2: Filter top 10 productIDs → get per-store pricing sorted by `PRICE_ASC`
3. Output: Clean table showing product, size, price, promo price at Metro Auckland

**Confirms**: Pipeline works end-to-end for a single ingredient.

---

### `test_website_jwt_edge.py` — Website JWT Integration Test

**Purpose**: Verify website JWT works for both store listing AND product search.

**What it tests**:
1. Get website JWT via `get-current-user`
2. Edge store listing with JWT
3. Product search with JWT + store cookies

**Confirms**: No mobile API token needed — website session is sufficient.

---

### `demo_edge_full_test.py` — Full Price Comparison Across Stores

**Purpose**: Geographic price comparison for specific products.

**What it does**:
- Gets JWT, fetches all stores
- Tests 6 geographically diverse stores
- Searches "standard milk 2L" at each
- Tests spaghetti bolognese ingredients at one store

**Confirms**: Per-store pricing works across stores (Te Puke vs Albany vs Metro Auckland show different prices).

---

### `demo_edge_optimizer.py` — Complete Optimizer Demo (Website Edge API)

**Purpose**: End-to-end meal cost optimizer using Edge API (single-pass, no relevance matching).

**What it does**:
- Gets website JWT
- Fetches all stores from Edge API
- Tests 5 dishes across first 5 stores
- Uses `paginated/products` directly (no relevance pass)
- Takes first result (like mobile API)

**Limitation**: No relevance matching — takes first result which may not be most relevant.

---

## Summary: Exploration Timeline & Key Discoveries

| Phase | Script(s) | Discovery |
|-------|-----------|-----------|
| 1 | explore_edge_api1-5 | Edge API has store listing, NO standard product search endpoints |
| 2 | explore_edge_api6_auth | **Website JWT works!** Product search = `/search/paginated/products` (Algolia) |
| 3 | explore_edge_api7-9 | **All 3 indices have `_highlightResult.matchedWords`**; `products-index` preferred (relevance sort) |
| 4 | test_*, demo_* | Two-pass pipeline validated; full optimizer demo working |
| 5 | explore_categories.py | **116 unique category1 values discovered** via 637 broad queries |
| 5 | paknsave_api.py, newworld_api.py, Foodstuffs_api.py | **NON_FOOD_CATEGORIES** blacklist (53 categories) applied in Pass 1 |

---

## Final Architecture: Edge API Two-Pass Pipeline (Production-Ready)

```
WEBSITE SESSION (no mobile API needed)
  1. GET https://www.newworld.co.nz (seed cookies)
  2. POST /api/user/get-current-user → fs-user-token cookie (JWT)

STORE LISTING
  3. GET /v1/edge/store (with JWT) → 148 stores with coords/IDs

FOR EACH INGREDIENT AT EACH STORE:
  PASS 1 — RELEVANCE (Algolia default index)
    POST /v1/edge/search/products/query/index/products-index
    Body: {"algoliaQuery": {"query": "beef mince"}, "storeId": "..."}
    → Extract productIDs where _highlightResult.matchedWords not empty
    → Filter out non-food category1 values (NON_FOOD_CATEGORIES: 53 categories)

  PASS 2 — PER-STORE PRICING (Paginated with filters)
    POST /v1/edge/search/paginated/products
    Body: {
      "algoliaQuery": {"query": "beef mince", "filters": "productID:xxx OR productID:yyy"},
      "storeId": "...", "sortOrder": "PRICE_ASC"
    }
    → Returns singlePrice.price (cents) + promotions[].rewardValue
    → Sorted by price at THIS store

COMPARE TOTALS → CHEAPEST STORE
```

---

## Advantages Over Mobile API

| Feature | Mobile API | Edge API (Two-Pass) |
|---------|------------|---------------------|
| Auth | Guest token (30 min, auto-refresh) | Website JWT (same IdP, more stable) |
| Dependency | Internal Foodstuffs API | Public website API |
| Relevance | Implicit (first result) | **Explicit `_highlightResult.matchedWords`** |
| Price sorting | PriceAsc only | `PRICE_ASC`, `PRICE_DESC` |
| Promotions | Included | Included (`rewardValue`) |
| Non-food filtering | Not available | **Available via `category1` in Pass 1 (53 categories)** |
| API stability | Unknown (internal) | Higher (public website backend) |

---

## Files in This Folder (Operational Order)

```
scripts/newworld/Exploration/
├── explore_edge_api1.py           # Phase 1: Initial probe — store listing works, product search 404
├── explore_edge_api2.py           # Phase 1: More product endpoint patterns
├── explore_edge_api3.py           # Phase 1: Web headers, CDX, mobile API deep dive
├── explore_edge_api4.py           # Phase 1: Mobile API endpoints + Next.js page analysis
├── explore_edge_api5.py           # Phase 1: Store-finder & search page __NEXT_DATA__
├── explore_edge_api6_auth.py      # Phase 2: BREAKTHROUGH — Website JWT + paginated/products works!
├── explore_edge_api7_algolia_indices.py  # Phase 3: Index enumeration (12 tested)
├── explore_edge_api8_indices_detailed.py # Phase 3: Detailed response inspection
├── explore_edge_api9_relevance.py # Phase 3: COMPREHENSIVE — Two-pass pipeline implementation
├── test_website_jwt_edge.py       # Phase 4: JWT integration validation
├── test_milk_metro_relevance.py   # Phase 4: Focused two-pass validation
├── demo_edge_optimizer.py         # Phase 4: Full optimizer demo (single-pass)
└── demo_edge_full_test.py         # Phase 4: Geographic price comparison
```

---

## Current Status

- **Edge API two-pass pipeline**: Fully implemented in `newworld_api.py` (production-ready)
- **Non-food category1 filtering**: `NON_FOOD_CATEGORIES` (53 categories) applied in Pass 1 across all Foodstuffs API modules
- **Category1 discovery**: `explore_categories.py` discovered 116 unique values via 637 broad queries
- **Demo scripts**: `newworld_search_demo.py` — standalone two-pass demo for New World Albany

The exploration is complete. The two-pass pipeline with category1 filtering is production-ready.