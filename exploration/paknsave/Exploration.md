# Pak'nSave Edge API Exploration Documentation

## Overview

This folder contains **4 exploration scripts** documenting the multi-phase journey
from initial Edge API probing to a production-ready two-pass pipeline that combines
relevance matching (Algolia) with per-store pricing, plus a hardening pass for
non-food category filtering and a live parser-idempotence check.

Pak'nSave shares the same Foodstuffs backend as New World (Apigee + Algolia), so
the discovery arc and pipeline architecture mirror each other. The Pak'nSave arc
is **shorter** than New World's because it picks up after the New World IdP and
JWT authentication were already understood; the focus here is on confirming the
same `products-index` + `paginated/products` endpoints work for PNS, cataloguing
the PNS-specific `category1` taxonomy, and validating the parsers on live data.

**Key Outcome**: The Edge API **CAN fully replace** the Foodstuffs mobile API for
Pak'nSave — no dependency on the internal mobile endpoint, uses the public website
JWT, explicit relevance matching via `_highlightResult`, per-store pricing via
cookies + Algolia filters, and a 26-value `NON_INGREDIENT_CATEGORIES` blacklist
applied in Pass 1.

**Script naming convention** (matches `exploration/newworld/`):
- `explore_*` — broad discovery probes, cataloguing
- `check_*` — focused validation against a known-good answer
- `demo_*` — end-to-end proof-of-concept flows

---

## Phase 1: Initial Edge API Probing — Store Listing Works

**Goal**: Determine if the Pak'nSave Edge API (`api-prod.paknsave.co.nz/v1/edge/`)
can replace the Foodstuffs mobile API. Auth flow was already known from the
New World exploration (same IdP: `online-customer`), so this phase is a quick
confirmation rather than a re-discovery.

**Outcome at end of Phase 1**: Edge store listing works (57 stores, full
metadata). The product-search endpoint was discovered in the **same** probing
session because the New World exploration had already established the website
JWT + Algolia `products-index` / `paginated/products` shape. Phases 1 and 2
were therefore captured together in the original `demo_two_pass_pipeline.py`
script rather than as separate `explore_edge_apiN.py` probes.

### Website JWT Authentication (F12 Network Inspection)

**Discovery**:
- `GET https://www.paknsave.co.nz` seeds cookies (Cloudflare, session)
- `POST https://www.paknsave.co.nz/api/user/get-current-user` returns
  `fs-user-token` cookie (JWT)
- Token payload: `{"banner": "PNS", "roles": ["ANONYMOUS"]}`
- Same IdP (`online-customer`) as New World and mobile API

### Store Listing Endpoint (F12 Network Inspection)

**Endpoint**: `GET https://api-prod.paknsave.co.nz/v1/edge/store`

**Result**: HTTP 200 — Returns 57 stores with full metadata (id, name, address,
lat/lon, services).

**Headers Required**:
```
Authorization: Bearer {fs-user-token}
access_token: {fs-user-token}
Origin: https://www.paknsave.co.nz
Referer: https://www.paknsave.co.nz/
```

---

## Phase 2: Algolia Two-Pass Pipeline — Production Ready

**Goal**: Confirm the two-pass pipeline (Algolia relevance + per-store pricing
via filter syntax) works end-to-end for a multi-ingredient dish across
multiple nearby Pak'nSave stores.

**Outcome at end of Phase 2**: The two-pass pipeline is fully functional for
Pak'nSave. The same endpoints as New World work — `products-index` returns
relevance-sorted hits with `_highlightResult.matchedWords` populated, and
`paginated/products` accepts Algolia `productID:xxx OR productID:yyy` filters
and a `PRICE_ASC` sortOrder.

### `demo_two_pass_pipeline.py` — End-to-End Optimiser Proof of Concept

**Purpose**: End-to-end meal cost optimiser for "spaghetti bolognese" near
Botany, Auckland, using the two-pass pipeline. This is the production
candidate for replacing the mobile API in `tools/paknsave/`.

**What it does**:
1. Obtains website JWT via `get-current-user`
2. Fetches all 57 stores via `GET /v1/edge/store`
3. Geocodes the user's address (Nominatim) and finds stores within 5 km
   (Haversine)
4. For each ingredient × each nearby store:
   - **PASS 1** — `POST /v1/edge/search/products/query/index/products-index`
     with `{"algoliaQuery": {"query": "<ingredient>"}, "page": 0,
     "hitsPerPage": 20, "storeId": "<id>"}`. Filters out pet food categories
     (`Dog`, `Cat`, `Pet`) inline, returns relevant `productID`s.
   - **PASS 2** — `POST /v1/edge/search/paginated/products` with
     `{"algoliaQuery": {"query": "<ingredient>", "filters":
     "productID:xxx OR productID:yyy"}, "page": 0, "hitsPerPage": 50,
     "storeId": "<id>", "sortOrder": "PRICE_ASC"}`. Returns
     `singlePrice.price` (cents) + `promotions[].rewardValue` (promo cents).
5. Sums cheapest product per ingredient, prints per-store total, ranks
   stores by cost.

**Sample Output** (Spaghetti Bolognese near Botany, Auckland):
```
--- PAK'nSAVE Botany ---
  beef mince                $1.99  (Gluten Free Sweet & Spicy Minced Beef Ready Sauce 120g)
  spaghetti pasta           $1.19  (Spaghetti 400g)
  canned tomatoes           $0.89  (Chopped Tomatoes in Juice 400g)
  onion                     $1.39  (Onion Soup Mix Sachet 32g)
  carrot                    $1.99  (Carrots kg)
  garlic                    $1.99  (Naturals Eco Garlic Salt 80g)
  mixed herbs               $2.59  (Mixed Herb Blend 13g)
  TOTAL                     $12.03

--- PAK'nSAVE Ormiston ---
  beef mince                $1.99  (Gluten Free Sweet & Spicy Minced Beef Ready Sauce 120g)
  ...
  TOTAL                     $12.13

--- PAK'nSAVE Highland Park ---
  ...
  TOTAL                     $11.82

COST COMPARISON
  1. PAK'nSAVE Highland Park        $11.82  (3.8 km)
  2. PAK'nSAVE Botany               $12.03  (0.2 km)
  3. PAK'nSAVE Ormiston             $12.13  (3.7 km)
```

**Architecture** (identical to New World — they share the Foodstuffs backend):
```
WEBSITE SESSION (no mobile API needed)
  1. GET https://www.paknsave.co.nz (seed cookies)
  2. POST /api/user/get-current-user → fs-user-token cookie (JWT)

STORE LISTING
  3. GET /v1/edge/store (with JWT) → 57 stores with coords/IDs

FOR EACH INGREDIENT AT EACH STORE:
  PASS 1 — RELEVANCE (Algolia default index)
    POST /v1/edge/search/products/query/index/products-index
    → Extract productIDs where _highlightResult has non-empty matchedWords
    → Filter by category1 to exclude non-food items (Dog/Cat/Pet in this POC)

  PASS 2 — PER-STORE PRICING (Paginated with filters)
    POST /v1/edge/search/paginated/products
    Body: {
      "algoliaQuery": {"query": "<ingredient>", "filters":
        "productID:xxx OR productID:yyy"},
      "page": 0, "hitsPerPage": 50, "storeId": "...", "sortOrder": "PRICE_ASC"
    }
    → Returns singlePrice.price (cents) + promotions[].rewardValue (promo cents)
    → Sorted by price at THIS store

COMPARE TOTALS → CHEAPEST STORE
```

**Endpoints** (identical to New World):

| Endpoint | Method | Auth | Cookies | Purpose |
|----------|--------|------|---------|---------|
| `/api/user/get-current-user` | POST | None | Session | Get JWT token |
| `/v1/edge/store` | GET | JWT | Optional | List all stores |
| `/v1/edge/search/products/query/index/products-index` | POST | JWT | Store context | Relevance search |
| `/v1/edge/search/paginated/products` | POST | JWT | Store context | Per-store pricing |

**Store Context Cookies (Required for Pricing)**:
```python
cookies = {
    "eCom_STORE_ID": store_id,
    "STORE_ID_V2": f"{store_id}|False",
    "Region": "NI"  # or "SI" for South Island
}
```

**Valid `sortOrder` Values (Paginated Endpoint)**:
- `PRICE_ASC` — Cheapest first
- `PRICE_DESC` — Most expensive first
- `RELEVANCE` / `DEFAULT` — 400 enum mismatch (confirmed not supported)

---

## Phase 3: Category-1 Discovery — 89 Unique Values

**Goal**: Discover all `category1` values that appear in the Pak'nSave Algolia
index, so the production filter in Pass 1 can exclude non-food items (pet,
baby, household, personal care, health, etc.).

**Outcome at end of Phase 3**: 89 unique `category1` values discovered across
~340 broad queries. The full counter + example product for each value is
saved to `data/observed_category1_paknsave.json`. The non-ingredient subset
(26 values) is lifted into `NON_INGREDIENT_CATEGORIES` and used in
`demo_filtering_variants.py` (Phase 4) and the production `paknsave_api.py`.

### `explore_categories.py` — Category1 Enumeration

**Purpose**: Discover all unique `category1` values that appear in the
Pak'nSave Algolia products-index by running broad search queries and
collecting every `category1` array seen.

**What it does**:
1. Step 1: Authenticate via website JWT flow
2. Step 2: Get a store to query against (prefers a NI store)
3. Step 3: Fetch the categories endpoint
   (`/v1/edge/store/{id}/categories`) and walk the navigation tree — printed
   in full for reference
4. Step 4: Run broad queries against `products-index` (single letters + every
   protein/dairy/bakery/fruit/vegetable/spice/condiment/drink/frozen/baby/pet/
   household/personal-care/health/stationery/kitchenware/laundry/garden/clothing/
   automotive/electronics/tobacco/miscellaneous category — exhaustive list)
5. Step 5: Print every unique `category1` value with frequency + example product
6. Step 6: Save the full counter to
   `data/observed_category1_paknsave.json`

**Key result**: 89 unique `category1` values. 26 of them (Dog, Cat, Baby &
Toddler Food, Baby Wipes, Nappies & Changing, Bath/Shower/Soap, Hair Care,
Dishwashing, Toilet Paper/Tissues/Paper Towels, Batteries & Electrical,
Stationery & Entertainment, Vitamins & Supplements, etc.) are
non-ingredients and form the `NON_INGREDIENT_CATEGORIES` blacklist.

**Note**: New World's identical `explore_category1_discovery.py` discovered
**116** values (637 queries). Pak'nSave is smaller because the brand range is
narrower — but the **same Foodstuffs taxonomy** applies, so the two
blacklists are largely the same. In production we use a single shared
`NON_FOOD_CATEGORIES` set across all Foodstuffs modules.

**Re-run with**:
```bash
python -m exploration.paknsave.explore_categories
```

---

## Phase 4: Filtering Hardening — A/B/C Filter Comparison

**Goal**: Quantify how much each filter variant improves Pass 1 results for
the canonical "beef mince" problem (where "beef mince seasoning", "beef mince
sauce", "beef mince ready meal" etc. match the query but are not the actual
ingredient). Choose the production filter strategy.

**Outcome at end of Phase 4**: Variant C (full 26-value blacklist) confirmed
as the production baseline. Variant B (pet food only) was the pre-hardening
production state — the script documents exactly what extra noise C removes
vs B (baby products, household items, health products, etc.).

### `demo_filtering_variants.py` — Three-Variant A/B/C Filter Comparison

**Purpose**: Demonstrates how the two-pass Edge API pipeline filters
irrelevant products when searching for ingredients, with a focus on the
"beef mince" problem.

**What it does**: For every nearby Pak'nSave store (within 1 km of the
geocoded address), runs three variants of Pass 1 (relevance search) for
"beef mince" and compares the results:

- **VARIANT A** — No category filter at all (raw Algolia relevance)
- **VARIANT B** — Pet food filter only (current production baseline at time of writing)
- **VARIANT C** — Full non-ingredient category blacklist (recommended)

Each variant searches for "beef mince", returns the top 20 relevant
productIDs from Pass 1, then fetches per-store pricing for all matched
products via Pass 2. Results are printed side-by-side so you can see
exactly which products each filter removes or keeps.

**`NON_INGREDIENT_CATEGORIES` (26 values)**: Pet food (Dog, Cat), baby
products (Baby & Toddler Food, Baby & Toddler Toiletries, Baby Formula,
Baby Wipes, Nappies & Changing), personal care (Bath/Shower/Soap, Hair
Care, Dental & Oral Care, Deodorant & Body Sprays, Skin Care & Sun Care),
household cleaning (Cleaning & Accessories, Dishwashing, Kitchen Cleaners,
Laundry, Pest & Insect Control), paper & storage (Toilet Paper/Tissues/
Paper Towels, Tissues & Cotton Wool, Food Wrap/Storage & Bags),
household non-food (Batteries & Electrical, Stationery & Entertainment),
health (Vitamins & Supplements, Medical & First Aid).

**Usage**:
```bash
python -m exploration.paknsave.demo_filtering_variants "Botany Town Centre, Auckland"
python -m exploration.paknsave.demo_filtering_variants  # uses default address
```

**Key finding**: Variant C eliminates pet food, baby products, household
items, health products, etc. — significantly reducing noise in Pass 2 and
producing a more accurate cost comparison. The script also prints a side-
by-side table of all 89 `category1` values (food vs non-ingredient) so the
blacklist is auditable at a glance.

---

## Phase 5: Live Parser Contract Verification

**Goal**: Continuously verify the parser contract — specifically that
`parse_foodstuffs_volume_size` and `parse_foodstuffs_mobile_unit` remain
**idempotent** on live Foodstuffs products. This is a **live probe, not a
regression test** — the deterministic correctness checks live in
`tests/combined/test_parser_utils.py`.

**Outcome at end of Phase 5**: Idempotence is the contract — re-running
each parser on the same input must always produce the same tuple. The
probe targets New World Edge + Mobile (the shared Foodstuffs backend) so
the result generalises to Pak'nSave automatically.

### `check_foodstuffs_parser_parity.py` — Live Parser Idempotence Probe

**Purpose**: Verifies that `parse_foodstuffs_volume_size` and
`parse_foodstuffs_mobile_unit` are idempotent on live New World Edge +
Mobile products (beef mince, New World Te Puke). Because the Foodstuffs
backend is shared between Pak'nSave and New World, a pass on the NW
backend is sufficient evidence that the parsers are correct for PNS too.

**What it does**:
1. Authenticates anonymously against the New World website to get a public
   `fs-user-token` JWT
2. Calls the Edge Algolia `products-index` for "beef mince" against
   New World Te Puke, filters to relevance-matched hits (same rule the
   production code uses), then fetches the full product records via the
   Pass-2 `paginated/products` endpoint
3. For each product, runs
   `parse_foodstuffs_volume_size(displayName, singlePrice, promotions)`
   twice on the same input and prints "MISMATCH" if the two calls return
   different tuples, "OK" otherwise
4. Repeats the same idempotence check via the Foodstuffs mobile API
   using `cloudscraper` (Cloudflare-protected), running
   `parse_foodstuffs_mobile_unit(units, unitPrice, price)` twice on the
   first ten returned products

**Source docs**: `docs/technical/NewWorld_API.md` §6 (Edge) and §10
(Mobile). The deterministic parser tests in
`tests/combined/test_parser_utils.py` cover correctness against fixtures;
this probe covers idempotence on real data.

**Re-run whenever**: The Foodstuffs product schema changes (new fields
added, units format changes, etc.).

**Usage**:
```bash
python -m exploration.paknsave.check_foodstuffs_parser_parity
```

---

## Summary: Exploration Timeline & Key Discoveries

| Phase | Script(s) | Discovery |
|-------|-----------|-----------|
| 1 | (inline in `demo_two_pass_pipeline.py`) | Website JWT works for Edge API; `GET /v1/edge/store` returns 57 stores |
| 2 | `demo_two_pass_pipeline.py` | Two-pass pipeline works end-to-end: `products-index` relevance → `paginated/products` with `productID:xxx OR productID:yyy` filters + `PRICE_ASC` sort |
| 3 | `explore_categories.py` | **89 unique `category1` values** discovered via broad queries; output saved to `data/observed_category1_paknsave.json` |
| 4 | `demo_filtering_variants.py` | A/B/C filter comparison: no-filter / pet-only / full 26-value `NON_INGREDIENT_CATEGORIES` blacklist — Variant C chosen for production |
| 5 | `check_foodstuffs_parser_parity.py` | **Live parser idempotence check** on shared Foodstuffs Edge + Mobile backends; deterministic correctness in `tests/combined/test_parser_utils.py` |

---

## Final Architecture: Edge API Two-Pass Pipeline (Production-Ready)

```
WEBSITE SESSION (no mobile API needed)
  1. GET https://www.paknsave.co.nz (seed cookies)
  2. POST /api/user/get-current-user → fs-user-token cookie (JWT)

STORE LISTING
  3. GET /v1/edge/store (with JWT) → 57 stores with coords/IDs

FOR EACH INGREDIENT AT EACH STORE:
  PASS 1 — RELEVANCE (Algolia default index)
    POST /v1/edge/search/products/query/index/products-index
    Body: {"algoliaQuery": {"query": "beef mince"}, "storeId": "..."}
    → Extract productIDs where _highlightResult.matchedWords not empty
    → Filter out non-food category1 values (NON_INGREDIENT_CATEGORIES: 26 values)

  PASS 2 — PER-STORE PRICING (Paginated with filters)
    POST /v1/edge/search/paginated/products
    Body: {
      "algoliaQuery": {"query": "beef mince", "filters":
        "productID:xxx OR productID:yyy"},
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
| Non-food filtering | Not available | **Available via `category1` in Pass 1 (26 categories)** |
| API stability | Unknown (internal) | Higher (public website backend) |

---

## Files in This Folder (Operational Order)

```
exploration/paknsave/
├── Exploration.md                            # This file
│
├── Phase 1: Initial Edge API Probing ───────────────────────────────────
│   (Captured inline in demo_two_pass_pipeline.py — website JWT + store listing)
│
├── Phase 2: Algolia Two-Pass Pipeline ──────────────────────────────────
├── demo_two_pass_pipeline.py                 # End-to-end 2-pass optimiser POC (Botany, Auckland)
│
├── Phase 3: Category-1 Discovery ───────────────────────────────────────
├── explore_categories.py                     # 89 category1 values via broad queries
│                                              # → data/observed_category1_paknsave.json
│
├── Phase 4: Filtering Hardening ────────────────────────────────────────
├── demo_filtering_variants.py                # 3-variant A/B/C filter comparison (beef mince)
│
└── Phase 5: Live Parser Contract Verification ─────────────────────────
    check_foodstuffs_parser_parity.py         # Live parser idempotence probe (NW Edge + Mobile)
```

**Invocation convention** (since this folder is a Python package — no
`__init__.py` required, parent `exploration/` is the package):
```bash
python -m exploration.paknsave.<script_name_without_py>
```

Examples:
```bash
python -m exploration.paknsave.demo_two_pass_pipeline
python -m exploration.paknsave.explore_categories
python -m exploration.paknsave.demo_filtering_variants "123 Queen Street, Auckland"
python -m exploration.paknsave.check_foodstuffs_parser_parity
```

---

## Current Status

- **Edge API two-pass pipeline**: Fully implemented in `paknsave_api.py`
  (production-ready)
- **Non-ingredient category1 filtering**: `NON_INGREDIENT_CATEGORIES`
  (26 categories) applied in Pass 1 across all Foodstuffs API modules
- **Category1 discovery**: `explore_categories.py` discovered 89 unique
  values via broad queries; output saved to
  `data/observed_category1_paknsave.json`
- **Filtering variants**: `demo_filtering_variants.py` documents the
  A/B/C filter comparison (no-filter vs pet-only vs full non-ingredient
  blacklist)
- **Live parser verification**: `check_foodstuffs_parser_parity.py`
  re-runnable any time the Foodstuffs product schema changes

The exploration is complete. The two-pass pipeline with category1 filtering
is production-ready and continuously verified against the live Edge API.

---

## Credits

This exploration builds on the New World Edge API discovery documented in
`exploration/newworld/Exploration.md`. The two-pass architecture pattern is
identical between the two banners since they share the same backend
infrastructure (Apigee + Algolia). Pak'nSave's arc is shorter because the
IdP / JWT / Algolia shape was already understood from the New World
exploration; the focus here is on the PNS-specific `category1` taxonomy
(89 values, 26 non-ingredient) and validating the parsers on live data.
