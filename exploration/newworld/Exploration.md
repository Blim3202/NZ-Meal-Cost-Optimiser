# New World Edge API Exploration Documentation

## Overview

This folder contains **19 exploration scripts** documenting the multi-phase journey
from initial Edge API probing to a production-ready two-pass pipeline that combines
relevance matching (Algolia) with per-store pricing, plus a hardening pass for
non-food category filtering.

**Key Outcome**: The Edge API **CAN fully replace** the Foodstuffs mobile API for
New World — no dependency on the internal mobile endpoint, uses the public website
JWT, explicit relevance matching via `_highlightResult`, per-store pricing via
cookies + Algolia filters, and a 53-category `NON_FOOD_CATEGORIES` blacklist
applied in Pass 1.

**Script naming convention** (established alongside `exploration/paknsave/`):
- `explore_*` — broad discovery probes, endpoint enumeration, cataloguing
- `check_*` — focused validation against a known-good answer
- `demo_*` — end-to-end proof-of-concept flows
- `newworld_highlight_permutations.py` — named-after-purpose live API contract
  verification probe (referenced by name in `AGENTS.md` and
  `docs/technical/CLI_vs_Dashboard.md`)

---

## Phase 1: Initial Edge API Probing — Store Listing Works, Product Search Missing

**Goal**: Determine if the New World Edge API (`api-prod.newworld.co.nz/v1/edge/`)
can replace the Foodstuffs mobile API. Tested with the mobile API guest token
(since both APIs share the same IdP: `online-customer`).

**Outcome at end of Phase 1**: Edge store listing works (149 stores, same data as
mobile). All 8+ product-search endpoint patterns return 404. The
`JWT-VerifyRetailEdgeToken` error is an Apigee policy. Mobile API remains the
only working path for product search.

### `explore_edge_api1.py` — First Comprehensive Test

**Purpose**: First probe of the New World Edge API with mobile-API token.

**What it tests**:
1. Mobile API token (decoded JWT payload) used against Edge API store listing
2. Edge API store listing with/without various auth headers
3. Eight product-search endpoint patterns (`/v1/edge/products/search`,
   `/v1/edge/ecomm-products/MNW/{storeId}/search`, `/v1/edge/store/{id}/products/search`,
   etc.) with both GET and POST
4. Direct comparison of Edge API vs Mobile API store data (149 stores on each,
   same IDs / coordinates)
5. Mobile API product search still works (control test)

**Key findings**:
- Edge store listing WORKS with mobile token (149 stores, same data)
- All product search endpoints return 404
- The mobile token works because both APIs share the same IdP

### `explore_edge_api2.py` — Quick Product Search Enumeration

**Purpose**: Rapid retry of additional endpoint patterns plus v2 variants.

**What it tests**: Same 6 endpoints as `explore_edge_api1` plus v2 variants, all
with mobile token.

**Result**: All 404. Confirms no standard REST product search exists on Edge API.

### `explore_edge_api3.py` — Web Headers & Refresh Token

**Purpose**: Test if web-like headers reveal product search + bonus mobile API
endpoint probe.

**What it tests**:
- Edge API with browser headers (Origin, Referer, User-Agent)
- Website product search pages (`/search?q=milk`)
- Mobile API refresh token flow (`/mobile/v1/users/login/refreshtoken`)
- Additional mobile API endpoints (`/mobile/v1/products/category`,
  `/mobile/v1/upgrade`, `/mobile/v1/error`, `/mobile/v1/users/profile`)

**Result**: No product search found. Confirms mobile API is the only path.

### `explore_edge_api4.py` — Mobile API Deep Dive & Next.js Page Analysis

**Purpose**: Exhaustive mobile API endpoint check + Next.js page inspection.

**What it tests**:
- Mobile API refresh token (revisited)
- Mobile API category/upgrade/error endpoints (revisited)
- Website search page `__NEXT_DATA__` extraction
- GraphQL endpoint probe (`/api/graphql`)
- API gateway on main domain (`/api/mobile/*`, `/api/v1/*`)

**Key discovery**: Website uses Next.js with `__NEXT_DATA__` but product data
is NOT pre-rendered — it's fetched via API at runtime.

### `explore_edge_api5.py` — Store Finder & Search Page Analysis

**Purpose**: Analyse `__NEXT_DATA__` from store-finder, search, and homepage
pages for API clues.

**What it tests**:
- Store-finder page structure (`contentstackStores` + `regionStoreGroupings`)
- Product-search page `__NEXT_DATA__` keys
- Homepage `__NEXT_DATA__` keys
- API gateway on main domain

**Result**: Store-finder page structure documented (used later in `fetch_stores.py`).
No product-search API visible in page props.

---

## Phase 2: Authentication Breakthrough — Website JWT Works

**Outcome at end of Phase 2**: The product search endpoint is
`/v1/edge/search/paginated/products` — an Algolia-powered endpoint, not a standard
REST endpoint. It requires the website JWT (`fs-user-token` cookie) + store context
cookies (`eCom_STORE_ID`, `STORE_ID_V2`, `Region`).

### `explore_edge_api6_auth.py` — **MAJOR BREAKTHROUGH**

**Purpose**: Test Edge API with **website session JWT** instead of mobile API token.

**What it discovers**:
1. **Website JWT flow**: `GET www.newworld.co.nz` →
   `POST /api/user/get-current-user` → `fs-user-token` cookie (JWT)
2. **Store listing**: `GET /v1/edge/store` works with website JWT (148 stores)
3. **Categories**: `GET /v1/edge/store/{id}/categories` works with JWT + store cookies
4. **Product search**: `POST /v1/edge/search/paginated/products` — **WORKS!**
   Returns per-store pricing!

**Key discovery**: The product search endpoint is `/v1/edge/search/paginated/products`
— an Algolia-powered endpoint, not a standard REST endpoint. It requires:
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

**Price comparison across 3 real stores** (Metro Auckland, Albany, Birkenhead) at
end of script confirms per-store prices differ.

---

## Phase 3: Algolia Index Discovery — Relevance Matching Exists

**Goal**: Find an Algolia index that exposes `_highlightResult.matchedWords` so we
can do explicit relevance matching (instead of blindly taking the first result).

**Outcome at end of Phase 3**: Three indices return 200. All three carry identical
`_highlightResult` structures. `products-index` (default — sorted by Algolia
relevance) is preferred. The two-pass pipeline is fully implemented.

### `explore_edge_api7_algolia_indices.py` — Index Enumeration

**Purpose**: Test multiple Algolia index endpoints for different sort orders.

**What it tests**: 12 index names based on common patterns:
- `products-index-popularity-asc` ✅ 200
- `products-index-popularity-desc` ✅ 200
- `products-index-relevance` ❌ 500
- `products-index-price-asc` ❌ 500
- `products-index-price-desc` ❌ 500
- `products-index-name-asc` ❌ 500
- `products-index-name-desc` ❌ 500
- `products-index-newest` ❌ 500
- `products-index-bestselling` ❌ 500
- `products-index-trending` ❌ 500
- `products-index` (default) ✅ 200
- `products` ❌ 404

**Only 3 indices return 200**: popularity-asc, popularity-desc, and the default
`products-index`.

### `explore_edge_api8_indices_detailed.py` — Detailed Response Inspection

**Purpose**: Deep-dive into the 3 working indices to understand their structure.

**Key finding**: **All 3 indices return identical `_highlightResult` structures
with `matchedWords`** — the only difference is sort order.
- `products-index-popularity-asc`: HAS `_highlightResult` with `matchedWords`,
  sorted by popularity ASC
- `products-index-popularity-desc`: HAS `_highlightResult` with `matchedWords`,
  sorted by popularity DESC
- `products-index`: HAS `_highlightResult` with `matchedWords`, sorted by Algolia
  relevance (default)

### `explore_edge_api9_relevance.py` — **COMPREHENSIVE DOCUMENTATION**

**Purpose**: Complete exploration narrative + working two-pass pipeline
implementation. This is the canonical reference for the production pipeline.

**Contains**:
- Full 6-phase discovery timeline (documented above)
- **Two-pass pipeline code**:
  - `algolia_relevance_search()` — PASS 1: Query `products-index` for relevance
    matches
  - `paginated_store_pricing()` — PASS 2: Query `paginated/products` with Algolia
    filters
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

**Bridge**: Algolia `filters` parameter accepts `productID:xxx OR productID:yyy`
syntax!

### `check_highlight_result_compare.py` — 3-Index Side-by-Side Comparison

**Purpose**: Dumps the first hit from each of the 3 working indices side-by-side
to see exactly what differs (nothing in `_highlightResult` structure, only sort
order and field values).

**What it shows**: Per-index dump of `productID`, `DisplayName`, `brand`,
`averagePrice`, `popularity`, `category0/1/2`, and per-field breakdown of
`_highlightResult.matchedWords` + `value`.

**Confirms**: All 3 indices have identical `_highlightResult` schema; only
`popularity` field varies (pop-asc vs pop-desc), not `products-index` (relevance).

---

## Phase 4: Focused Validation & Multi-Store Demos

**Goal**: Confirm the two-pass pipeline works end-to-end for single queries and
across multiple stores.

**Outcome at end of Phase 4**: Pipeline validated. Per-store pricing differs as
expected. Single-pass optimiser demo confirms the full meal-cost flow works
without relevance matching (the pre-two-pass baseline).

### `check_website_jwt_edge_integration.py` — JWT Integration Test

**Purpose**: Verify website JWT works for both store listing AND product search.

**What it tests**:
1. Get website JWT via `get-current-user`
2. Edge store listing with JWT (148 stores)
3. Product search with JWT + store cookies (returns priced products)

**Confirms**: No mobile API token needed — website session is sufficient.

### `check_two_pass_milk_metro.py` — Focused Two-Pass Validation

**Purpose**: Single-query validation of the two-pass pipeline for "milk" at Metro
Auckland.

**What it does**:
1. PASS 1: Search `products-index` for "milk" → 15 hits, all with relevance matches
2. PASS 2: Filter top 10 productIDs → get per-store pricing sorted by `PRICE_ASC`
3. Output: Clean table showing product, size, price, promo price at Metro Auckland

**Confirms**: Pipeline works end-to-end for a single ingredient.

### `demo_geographic_price_compare.py` — Full Price Comparison Across Stores

**Purpose**: Geographic price comparison for specific products.

**What it does**:
- Gets JWT, fetches all stores
- Tests 6 geographically diverse stores (Te Puke, Albany, Birkenhead, Metro
  Auckland, Wellington City, Christchurch Central)
- Searches "standard milk 2L" at each
- Tests spaghetti bolognese ingredients at one store

**Confirms**: Per-store pricing works across stores (Te Puke vs Albany vs Metro
Auckland show different prices).

### `demo_full_optimiser_single_pass.py` — Complete Optimiser Demo (Website Edge API)

**Purpose**: End-to-end meal cost optimiser using Edge API (single-pass, no
relevance matching). This is the pre-two-pass baseline — demonstrates the full
flow works before introducing the relevance-matching complexity.

**What it does**:
- Gets website JWT
- Fetches all stores from Edge API
- Tests "spaghetti bolognese" ingredients across first 5 stores
- Uses `paginated/products` directly (no relevance pass) and takes the first
  result (like the mobile API did)

**Limitation**: No relevance matching — takes first result which may not be the
most relevant product. Mitigated later by the two-pass pipeline (Phase 3) and
filtering (Phase 5).

---

## Phase 5: Category-1 Discovery & Filtering Hardening

**Goal**: Discover all `category1` values that appear in the New World Algolia
index, then construct a non-ingredient blacklist to apply in Pass 1.

**Outcome at end of Phase 5**: 116 unique `category1` values discovered via 637
broad queries. 53 of them (Dog, Cat, Pet, Baby, Household, etc.) are in
`NON_FOOD_CATEGORIES` and applied in Pass 1 across all Foodstuffs modules.

### `explore_category1_discovery.py` — Category1 Enumeration

**Purpose**: Discover all unique `category1` values that appear in the New World
Algolia products-index by running 637 broad search queries and collecting every
`category1` array seen.

**What it does**:
1. Step 1: Authenticate via website JWT flow
2. Step 2: Get a store to query against
3. Step 3: Fetch categories endpoint (`/v1/edge/store/{id}/categories`) and
   recursively walk the navigation tree
4. Step 4: Run 637 broad queries against `products-index` (single letters, every
   protein/dairy/bakery/fruit/vegetable/spice/condiment/drink/frozen/baby/pet/
   household/personal-care/health/stationery/kitchenware/laundry/garden/clothing/
   automotive/electronics/tobacco/miscellaneous category — exhaustive list)
5. Step 5: Print every unique `category1` value with frequency + example product
6. Step 6: Print every unique `category1` combination seen (array values)
7. Output: `data/observed_category1_newworld.json` with the full counter

**Key result**: 116 unique `category1` values. 53 of them are non-ingredient
(pet, baby, household, personal care, health, etc.) and form the
`NON_FOOD_CATEGORIES` blacklist.

**Re-run with**:
```bash
python -m exploration.newworld.explore_category1_discovery
```

### `demo_filtering_variants.py` — Three-Variant A/B/C Filter Comparison

**Purpose**: Demonstrates how the two-pass Edge API pipeline filters irrelevant
products when searching for ingredients, with a focus on the "beef mince" problem
(where "beef mince seasoning" or similar products match the query but are not the
actual ingredient).

**What it does**: For every nearby New World store (within 1 km of the geocoded
address), runs three variants of Pass 1 (relevance search) for "beef mince" and
compares the results:

- **VARIANT A** — No category filter at all (raw Algolia relevance)
- **VARIANT B** — Pet food filter only (current production baseline)
- **VARIANT C** — Full non-ingredient category blacklist (recommended)

Each variant searches for "beef mince", returns the top 20 relevant productIDs
from Pass 1, then fetches per-store pricing for all matched products via Pass 2.
Results are printed side-by-side so you can see exactly which products each
filter removes or keeps.

**Usage**:
```bash
python -m exploration.newworld.demo_filtering_variants "123 Queen Street, Auckland CBD, 1010"
python -m exploration.newworld.demo_filtering_variants  # uses default address
```

**Key finding**: Variant C eliminates pet food, baby products, household items,
health products, etc. — significantly reducing noise in Pass 2 and producing a
more accurate cost comparison.

### `check_two_pass_beef_mince_albany.py` — Standalone Two-Pass Probe

**Purpose**: Standalone two-pass probe for "beef mince" at New World Albany, with
the production `NON_FOOD_CATEGORIES` filter (53 values) already applied in Pass 1.

**What it does**:
1. Authenticate via website JWT
2. Run Pass 1 with `NON_FOOD_CATEGORIES` filter → get filtered productIDs
3. Save raw hits to `data/newworld_hits.json` (for inspection / debugging)

**Use case**: A focused, runnable probe for a known-problematic query that
exercises the full production filter logic outside of the optimiser pipeline.

---

## Phase 6: Live API Contract Verification

**Goal**: Continuously verify the `NewWorld_API.md` §6.3-§6.8 claims about
`_highlightResult`, `matchedWords`, and the dead indices. This is a **live probe,
not a regression test** — re-run it when the New World Edge Algolia contract
changes to confirm the documented claims still hold.

### `newworld_highlight_permutations.py` — Live Verification Probe

**Purpose**: Verifies the following documented claims (`NewWorld_API.md` §6.3 /
§6.4 / §6.8):

1. `products-index` returns HTTP 200 and carries `_highlightResult`
2. `_highlightResult` field values expose `value`, `matchLevel`, `matchedWords`
3. Relevance hits have non-empty `matchedWords`; no-match queries do not (probe
   query: `"zzzqqq"`)
4. `matchedWords` tokens are generally derivable from the query (Algolia may add
   taxonomy/brand tokens not literally in the query)
5. `<em>` emphasis markers appear in `value` wherever `matchedWords` is non-empty
6. The 8 "dead" indices (price-asc/desc, relevance, name-asc/desc, newest,
   bestselling, trending) return HTTP 500 as documented in section 6.4
7. Pass 2 `paginated/products` returns pricing only — products carry no
   `_highlightResult`

**Production filter alignment**: The production filter in
`NZMealOptimiser/pricing/newworld_api.py` only inspects SCALAR dict values of
`_highlightResult` — array fields like `category1`/`category2` are
lists-of-dicts and are skipped. This script therefore records each hit's matches
under two lenses:
- **"scalar match"** — would the production filter flag this hit?
- **"any match"** — does ANY field (incl. list fields) hold a match?

The full JSON response is printed for every probe, except the
store-availability fields `inStoreAvailable`, `onlineAvailable`, and `stores`,
whose values are redacted with "TRUNCATED FOR TEST" so the rest of the payload
stays readable.

**Usage**:
```bash
python -m exploration.newworld.newworld_highlight_permutations
```

**Re-run whenever**: The New World Edge Algolia contract changes (new fields
added, dead indices come back online, etc.).

---

## Summary: Exploration Timeline & Key Discoveries

| Phase | Script(s) | Discovery |
|-------|-----------|-----------|
| 1 | `explore_edge_api1-5` | Edge API has store listing, NO standard product search endpoints |
| 2 | `explore_edge_api6_auth` | **Website JWT works!** Product search = `/search/paginated/products` (Algolia) |
| 3 | `explore_edge_api7-9`, `check_highlight_result_compare` | **All 3 indices have `_highlightResult.matchedWords`**; `products-index` preferred (relevance sort) |
| 4 | `check_*`, `demo_*` | Two-pass pipeline validated; full optimiser demo working across stores |
| 5 | `explore_category1_discovery`, `demo_filtering_variants`, `check_two_pass_beef_mince_albany` | **116 unique category1 values discovered** via 637 broad queries; 53 added to `NON_FOOD_CATEGORIES` |
| 6 | `newworld_highlight_permutations.py` | **Live API contract verification** — re-confirms `NewWorld_API.md` §6.3-§6.8 claims |

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
exploration/newworld/
├── Exploration.md                             # This file
│
├── Phase 1: Initial Edge API Probing ──────────────────────────────────
├── explore_edge_api1.py                       # First probe — store listing works, product search 404
├── explore_edge_api2.py                       # More product endpoint patterns (all 404)
├── explore_edge_api3.py                       # Web headers + refresh token + bonus endpoints
├── explore_edge_api4.py                       # Mobile API deep-dive + Next.js __NEXT_DATA__
├── explore_edge_api5.py                       # Store-finder / search-page __NEXT_DATA__
│
├── Phase 2: Authentication Breakthrough ──────────────────────────────
├── explore_edge_api6_auth.py                  # BREAKTHROUGH — Website JWT + paginated/products works!
│
├── Phase 3: Algolia Index Discovery & Two-Pass Pipeline ──────────────
├── explore_edge_api7_algolia_indices.py       # 12-index enumeration
├── explore_edge_api8_indices_detailed.py      # Detailed response inspection of the 3 working indices
├── explore_edge_api9_relevance.py             # COMPREHENSIVE — Two-pass pipeline implementation
├── check_highlight_result_compare.py          # 3-index side-by-side _highlightResult dump
│
├── Phase 4: Focused Validation & Multi-Store Demos ───────────────────
├── check_website_jwt_edge_integration.py      # JWT works for stores + search
├── check_two_pass_milk_metro.py               # Focused two-pass validation (single query)
├── demo_geographic_price_compare.py           # 6-store geographic price comparison
├── demo_full_optimiser_single_pass.py         # Full optimiser demo (single-pass, no relevance)
│
├── Phase 5: Category-1 Discovery & Filtering Hardening ───────────────
├── explore_category1_discovery.py             # 116 category1 values via 637 broad queries
├── demo_filtering_variants.py                 # 3-variant filter comparison (no-filter / pet-only / full)
├── check_two_pass_beef_mince_albany.py        # Standalone two-pass probe (beef mince @ Albany)
│
└── Phase 6: Live API Contract Verification ───────────────────────────
└── newworld_highlight_permutations.py         # Live probe — re-confirms NewWorld_API.md §6.3-§6.8
```

**Invocation convention** (since this folder is a Python package):
```bash
python -m exploration.newworld.<script_name_without_py>
```

Examples:
```bash
python -m exploration.newworld.explore_edge_api6_auth
python -m exploration.newworld.explore_edge_api9_relevance
python -m exploration.newworld.explore_category1_discovery
python -m exploration.newworld.demo_filtering_variants "123 Queen Street, Auckland"
python -m exploration.newworld.newworld_highlight_permutations
```

---

## Current Status

- **Edge API two-pass pipeline**: Fully implemented in `newworld_api.py`
  (production-ready)
- **Non-food category1 filtering**: `NON_FOOD_CATEGORIES` (53 categories) applied
  in Pass 1 across all Foodstuffs API modules
- **Category1 discovery**: `explore_category1_discovery.py` discovered 116 unique
  values via 637 broad queries; output saved to
  `data/observed_category1_newworld.json`
- **Live contract verification**: `newworld_highlight_permutations.py` re-runnable
  any time the Edge API contract changes
- **Filtering variants**: `demo_filtering_variants.py` documents the
  A/B/C filter comparison (no-filter vs pet-only vs full non-ingredient blacklist)

The exploration is complete. The two-pass pipeline with category1 filtering is
production-ready and continuously verified against the live Edge API.
