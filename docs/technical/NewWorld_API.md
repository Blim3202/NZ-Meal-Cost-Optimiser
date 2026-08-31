# New World / Foodstuffs North Island Mobile API Documentation

**API origin:** `api-prod.prod.fsniwaikato.kiwi` — despite the "FSNI" (Foodstuffs North
Island) domain name, this API covers **all New World stores nationwide** including
both North Island (101 stores) and South Island (48 stores). It also works for
Pak'nSave with `banner: "PNS"`.

---

## Contents

- [1. Overview](#1-overview)
- [2. Base URL and Host](#2-base-url-and-host)
- [3. Required Request Headers](#3-required-request-headers)
- [4. Authentication Flow](#4-authentication-flow)
- [5. Confirmed Working Endpoints (Mobile API)](#5-confirmed-working-endpoints-mobile-api)
- [6. New World Edge API (Website Backend)](#6-new-world-edge-api-website-backend)
- [7. Per-Store Pricing](#7-per-store-pricing)
- [8. Data Query & Parsing Pipeline](#8-data-query--parsing-pipeline)
- [9. Store Data Sources](#9-store-data-sources)
- [10. Production Architecture & Optimisers](#10-production-architecture--optimisers)
- [11. Supported Dishes (21)](#11-supported-dishes-21)
- [12. CLI Usage](#12-cli-usage)
- [13. Appendix: Full Edge API Endpoint Reference](#13-appendix-full-edge-api-endpoint-reference)

---

## 1. Overview

The New World mobile API at `api-prod.prod.fsniwaikato.kiwi` shares the same structure as the Pak'nSave API — the only differences are the `banner` value (`"MNW"` vs `"PNS"`) and the `User-Agent` header (`NewWorldApp/4.32.0` vs `PAKnSAVEApp/4.32.0`). See [PaknSave_API.md](PaknSave_API.md) for the full shared API documentation (auth flow, mobile endpoints, Edge API, two-pass pipeline). This document covers New World-specific differences only.

**Credits:** Authored by [Arefu](https://github.com/Arefu) through reverse engineering the Foodstuffs Android app. Full OpenAPI spec in their [PaknSave repo](https://github.com/Arefu/PaknSave).

---

## 2. Base URL and Host

Identical to [PaknSave_API.md §2](PaknSave_API.md) — same `api-prod.prod.fsniwaikato.kiwi/prod` base, same pre-prod/QA hosts, same `fsniwaikato.kiwi` backend.

---

## 3. Required Request Headers

Identical to [PaknSave_API.md §3](PaknSave_API.md), except `User-Agent: NewWorldApp/4.32.0` instead of `PAKnSAVEApp/4.32.0`. Both `Authorization: Bearer {token}` and `access_token: {token}` headers are still required (omitting either returns 401).

---

## 4. Authentication Flow

Identical to [PaknSave_API.md §4](PaknSave_API.md), except the guest login body is `{"banner": "MNW"}` instead of `{"banner": "PNS"}`. The `expires_in: 1800` (30 min) TTL and the "token never auto-refreshed" gotcha are identical — see [PaknSave_API.md §4.1](PaknSave_API.md) for the full flow, response shape, and refresh-endpoint details.

---

## 5. Confirmed Working Endpoints (Mobile API)

### 5.1 `GET /mobile/store/physical`

Returns all physical stores for the banner encoded in the access token. This is the
primary source of store metadata: names, precise coordinates, addresses, opening hours,
and service flags.

**HTTP 200** — requires auth headers.

#### Response structure

Returns an object with a single `"stores"` key containing an array:

```json
{
  "stores": [
    {
      "id": "773ad0a0-024e-46c5-a94b-df1cf86d25cc",
      "name": "New World Albany",
      "banner": "MNW",
      "address": "219 Don McKinnon Drive, Albany, Auckland 0632",
      "clickAndCollect": true,
      "delivery": true,
      "latitude": -36.728207,
      "longitude": 174.710519,
      "openingHours": [ ... ],
      "phone": "09-441 8838",
      "localPhone": "09-441 8838",
      "linkDetails": { ... },
      "physicalStoreCode": "NW01",
      "region": "NI",
      "salesOrgId": "20",
      "onboardingMode": false,
      "defaultCollectType": "CONCIERGE",
      "expressTimeslots": true,
      "expressProductLimit": 35,
      "onlineActive": true,
      "physicalActive": true,
      "servicesAndFacilities": [ ... ],
      "physicalAddress": { ... },
      "deliverySubscriptionProperties": { ... }
    },
    ...
  ]
}
```

#### Key fields

| Field | Type | Notes |
|-------|------|-------|
| `id` | `string` (UUID) | Store identifier — used in all product/search endpoints |
| `name` | `string` | Full store name, e.g. `"New World Albany"` |
| `banner` | `string` | `"PNS"` or `"MNW"` |
| `address` | `string` | Full street address |
| `latitude` | `float` | Precise store latitude (not geocoded) |
| `longitude` | `float` | Precise store longitude (not geocoded) |
| `clickAndCollect` | `bool` | Supports click & collect |
| `delivery` | `bool` | Supports home delivery |
| `onlineActive` | `bool` | Available for online ordering |
| `physicalActive` | `bool` | Physical store open |
| `region` | `string` | `"NI"` (North Island) or `"SI"` (South Island) |
| `salesOrgId` | `string` | Sales organisation identifier |
| `defaultCollectType` | `string` | `"CONCIERGE"`, `"COUNTER"`, or `"LOCKER"` |
| `openingHours` | `array` | Daily opening/closing times |
| `physicalAddress` | `object` | Structured address fields (streetName, cityName, regionName, etc.) |

#### Store count

150 stores are returned for `banner="MNW"` via the mobile endpoint (148 via Edge).
The mobile-only stores are `Foodie Mart` (35 Landing Drive, Mangere) and
`New World Te Atatu` (575 Te Atatū Road, Te Atatū Peninsula) — both absent from
the Edge API. Each store has a UUID-style `id` (e.g., `773ad0a0-024e-46c5-a94b-df1cf86d25cc`).

#### Usage in this project

```python
from NZMealOptimiser.pricing.newworld_api import NewWorldMobileAPI
api = NewWorldMobileAPI()
stores = api.get_stores()  # returns {id: store_dict}
```

The canonical store CSV (`data/newworld_stores.csv`, 10 columns: `store_id, name, address,
city, region, latitude, longitude, banner, click_and_collect, delivery`) is built by
`tools/newworld/newworld_setup.py`, which **defaults to the Edge API** (see
section 9). The `url` column used by the legacy store-finder join is no longer produced.

### 5.2-5.5 Mobile product search / specials / categories

**All four subsections are identical to [PaknSave_API.md §5.2-5.5](PaknSave_API.md)** — same path format `POST /mobile/ecomm-products/MNW/{storeId}/search?q=...` (banner `"MNW"` instead of `"PNS"`), same query parameters (`q` + `hitsPerPage=20`), same empty-array request body, same wrapped-dict response with `products`/`tobaccoFiltered`/`totalHits`/`filters` (also accepts bare array defensively), same price-in-cents semantics (`price / 100`), same `categories[]` mapping (`[0]` = category1, no category0), same `parse_foodstuffs_mobile_unit()` 4-tuple parsing, same `units` fallback when `unitPrice` is null. The only NW-specific deltas:

- **`units` vocabulary** for NW: `"kg"`, `"L"`, `"400g"`, `"12pk"`, `"each"`, `"1pk"` (vs PNS's `"ea"`/numeric-prefix forms). The shared normaliser `parse_foodstuffs_mobile_unit` handles both.
- **`saleType`** for NW: `"standard"`, `"special"`, `"club"` (vs PNS's `"WEIGHT"` / `"UNITS"`).
- **Known deal types** ("Super Specials", "Weekly Specials") are identical to PNS.

For full request/response shapes, the `parse_foodstuffs_mobile_unit` algorithm, the categories 3-level nesting, and the browse-by-category-path variant — see [PaknSave_API.md §5.2-5.5](PaknSave_API.md).

### 5.3 `POST /mobile/ecomm-products/{banner}/{storeId}/specials`

Identical to [PaknSave_API.md §5.3](PaknSave_API.md) — same path, same deal-type filters ("Super Specials", "Weekly Specials"), same response format. Banner is `"MNW"`.

### 5.4 `GET /mobile/v1/products/category`

Identical to [PaknSave_API.md §5.4](PaknSave_API.md) — same query parameters, same 3-level category tree response. Banner is `"MNW"`.

### 5.5 `GET /mobile/v1/products/category` (Browse by category path)

Identical to [PaknSave_API.md §5.5](PaknSave_API.md) — same `cat0`/`cat1`/`cat2` query parameters, same product-array response. Banner is `"MNW"`.

---

## 6. New World Edge API (Website Backend)

The New World website at `www.newworld.co.nz` exposes an Edge API at
`api-prod.newworld.co.nz`. This API uses Apigee gateway with JWT verification.

### 6.1-6.6 Authentication, store listing, two-pass pipeline, Algolia indices, paginated endpoint, categories

**All of §6.1 through §6.6 is structurally identical to [PaknSave_API.md §6.1-6.6](PaknSave_API.md)** — same `Authorization: Bearer` + `access_token` header pair, same `eCom_STORE_ID` / `STORE_ID_V2` / `Region` per-store cookies, same `POST /api/user/get-current-user` → `fs-user-token` cookie flow, same two-pass Algolia architecture, same 3 working Algolia indices (`products-index`, `-popularity-asc`, `-popularity-desc`) + 8 returning HTTP 500, same valid `sortOrder` values (`PRICE_ASC`, `PRICE_DESC`) and invalid enum values (`RELEVANCE` / `RELEVANCY` / `DEFAULT` / `BEST_MATCH` → HTTP 400), same `productID:xxx OR productID:yyy` Algolia filter syntax, same `_highlightResult.matchedWords` extraction, same `singlePrice.price` (cents) + `promotions[].rewardValue` (where `bestPromotion: true`) pricing, same `comparativePrice.pricePerUnit` / `unitQuantityUom` for unit pricing, same `promotions` is `null` (not `[]`) when no promo, same `category1` (in Pass 1) and `categories[0]` (mobile) pet-food filtering via `NON_FOOD_CATEGORIES` (53 values, single source in `optimiser_utils.py`).

The only NW-specific deltas in §6.1-6.6 are:
- **Base URL**: `https://api-prod.newworld.co.nz/v1/edge` (vs `https://api-prod.paknsave.co.nz/v1/edge`).
- **Origin / Referer headers**: `https://www.newworld.co.nz` / `https://www.newworld.co.nz/`.
- **Store count** (see §6.2 below).

For full request/response shapes, the two-pass pipeline narrative, the complete Algolia index table with 500-vs-404 status notes (verified 2026-08-04), and the Paginated Search response schema — see [PaknSave_API.md §6.1-6.6](PaknSave_API.md).

### 6.2 Store Listing (NW-specific delta)

**Endpoint**: `GET https://api-prod.newworld.co.nz/v1/edge/store`

**Status**: [OK] **Works (HTTP 200)** with valid JWT.

**Returns**: 148 stores with full details (id, name, address, coordinates, opening hours, services).

**Note**: Returns 148 stores vs 150 from mobile API. The two stores missing from Edge are `Foodie Mart` (35 Landing Drive, Mangere — an in-house Foodstuffs location) and `New World Te Atatu` (575 Te Atatū Road, Te Atatū Peninsula). Both appear in the mobile API response but not the Edge API, so Edge is the smaller set.

### 6.7-6.11 Mobile-vs-Edge comparison, pipeline summary, conclusion

**All of §6.7 through §6.11 is structurally identical to [PaknSave_API.md §6.7-6.11](PaknSave_API.md)** — same Mobile-vs-Edge feature comparison table (only the store counts differ: 148/150 for NW vs 57/60 for PNS), same Two-Pass Pipeline Summary block, same "Why This Matters" narrative, same "Conclusion" advantages list, same "Exploration Timeline & Breakthroughs" table. The NW-specific deltas:

- **Store counts**: Edge 148 / Mobile 150 (vs PNS's Edge 57 / Mobile 60).
- **Reference implementation**: `src/NZMealOptimiser/pricing/newworld_api.py` (`NewWorldEdgeAPI` + `NewWorldMobileAPI`) + shared `src/NZMealOptimiser/pricing/optimiser_utils.py` (`foodstuffs_querier_edge` / `foodstuffs_querier_mobile`).
- **CLI entry points**: `tools/newworld/newworld_optimiser_edge.py` (production default) + `tools/newworld/newworld_optimiser_mobile.py` (fallback).

For the full feature comparison, pipeline summary, advantages table, and exploration timeline — see [PaknSave_API.md §6.7-6.11](PaknSave_API.md).

### 6.12 Exploration Scripts & Discoveries

The complete two-pass pipeline + website JWT discovery for New World was built through **14 exploration scripts** spanning a 5-phase timeline. All scripts live in [`exploration/newworld/`](../../exploration/newworld/) and are executable via `python -m exploration.newworld.<script>`.

| Phase | Script(s) | What was discovered | Why it mattered |
|-------|-----------|---------------------|-----------------|
| 1 | `explore_edge_api1.py` through `explore_edge_api5.py` | Edge API has store listing (`GET /v1/edge/store`) but NO standard REST product search endpoints — 8+ endpoint patterns all 404 (e.g. `/v1/edge/products/search`, `/v1/edge/ecomm-products/MNW/{storeId}/search`, `/v1/edge/store/{id}/products/search`) | Initially concluded Edge was not viable for product search; pivoted to mobile API |
| 2 | `explore_edge_api6_auth.py` | **BREAKTHROUGH**: `POST /api/user/get-current-user` returns `fs-user-token` cookie (JWT); with this, `POST /v1/edge/search/paginated/products` works for per-store pricing (with `eCom_STORE_ID`, `STORE_ID_V2`, `Region` cookies) | Discovered the website JWT flow + the Algolia-powered product search endpoint that the mobile API never exposed |
| 3 | `explore_edge_api7-9.py` | 12 Algolia index names tested — only 3 return 200 (`products-index`, `-popularity-asc`, `-popularity-desc`); all 3 have identical `_highlightResult.matchedWords` structure; only sort order differs | Found the relevance-matching layer; `products-index` (default) is preferred (relevance-sorted) |
| 4 | `test_*.py` / `demo_*.py` | Two-pass pipeline validated end-to-end for milk, beef mince, bread, cheese at multiple Auckland stores; per-store prices confirmed different (e.g. Shore City $9.49 vs Metro Auckland $26.99 beef mince) | Production-ready pipeline; the price-variation evidence (§7.2) validated the entire meal-cost-optimizer premise |
| 5 | `explore_categories.py` | 116 unique `category1` values discovered via 637 broad queries; 53 of them (`Dog`, `Cat`, `Pet`, `Baby`, `Household`, etc.) added to `NON_FOOD_CATEGORIES` and applied in Pass 1 across all Foodstuffs modules | Non-food category1 filtering eliminates pet food matching "beef mince" |

**Key outcomes that drove project architecture:**

1. **The Edge API fully replaces the mobile API** — same IdP (`online-customer`), 148 Edge stores (vs 150 mobile — 2 mobile-only stores: Foodie Mart + New World Te Atatu), per-store pricing via cookies + Algolia filters, and explicit relevance matching via `_highlightResult.matchedWords` (vs the mobile API's implicit "first result is best" ordering).
2. **Algolia `filters` parameter bridges relevance and pricing** — Pass 1's `productID`s become Pass 2's `productID:xxx OR productID:yyy` filter, sorted by `PRICE_ASC`.
3. **The Edge pipeline is the production default** — the legacy mobile backend (`PaknSaveAPI(backend="mobile")`, `newworld_optimiser_mobile.py`) is retained only as a fallback if the Edge API is unavailable.

**Full phase-by-phase exploration narrative** (with code snippets, response samples, decision log, and the complete advantages-over-mobile-API table): [`exploration/newworld/Exploration.md`](../../exploration/newworld/Exploration.md) (336 lines).

---

## 7. Per-Store Pricing

### 7.1 How It Works

The New World mobile API provides **true per-store pricing**. Each store has its own
price list for every product identified by its unique `productId`. When you search
for "beef mince" at store A vs store B, the prices returned are that store's current
prices.

This is in contrast to the Woolworths API, which requires cookie injection for
per-store pricing — New World (like Pak'nSave) encodes the store context directly
in the URL path:

```
POST /mobile/ecomm-products/MNW/{storeId}/search?q=beef+mince
```

No special headers, cookies, or session setup beyond the bearer token is needed.

### 7.2 Observed Price Variation

Price differences between nearby stores are common. For example, a search for
"spaghetti bolognese" ingredients across 13 Auckland stores showed:

| Store | Total Cost | Distance |
|-------|-----------|----------|
| New World Shore City | $23.53 | 7.4 km |
| New World Metro Auckland | $49.13 | 0.9 km |
| New World Newmarket | $63.63 | 2.3 km |
| New World Milford | $63.63 | 9.1 km |
| New World Birkenhead | $78.03 | 6.6 km |
| New World Stonefields | $86.63 | 7.3 km |

Differences of $0.10-$0.50 per item between nearby stores are typical. For example:
- Beef mince: $9.49 (Shore City) vs $26.99 (Metro Auckland)
- Garlic: $4.49 (Shore City) vs $52.99 (Stonefields)

**Note: this simple calculation has differences due to per-store availability rather than per-store pricing.**

### 7.3 Why This Matters

The meal cost optimiser finds the cheapest total for an entire recipe by searching
each ingredient at each nearby store and comparing totals. Without per-store pricing,
this comparison would be meaningless.

---

## 8. Data Query & Parsing Pipeline

> **Default backend: Edge API (two-pass).** The unified API client `NewWorldAPI(backend="edge")` and the production CLI optimiser (`newworld_optimiser_edge.py`) default to the Edge backend. The mobile backend (`backend="mobile"`, `newworld_optimiser_mobile.py`) is the legacy fallback.

Identical to [PaknSave_API.md §8](PaknSave_API.md) — same shared helpers (`foodstuffs_querier_edge`, `foodstuffs_querier_mobile`, `build_edge_row`, `build_mobile_row`, `parse_foodstuffs_volume_size`, `parse_foodstuffs_mobile_unit`), same 18-column CSV schema, same skeleton (`geocode → find_nearby_stores → search per store per ingredient → build_row → append_rows → optimise()`). NW-specific deltas: the Edge class is `NewWorldEdgeAPI` (not `PaknSaveEdgeAPI`); the banner path is `MNW` not `PNS`; the CLI wrapper is `tools/newworld/newworld_optimiser_edge.py`. For full code samples and the Edge-vs-Mobile source-column mapping table see [PaknSave_API.md §8.1-8.3](PaknSave_API.md).

---

## 9. Store Data Sources

**Default source: Edge API.** `tools/newworld/newworld_setup.py` defaults to
`source="edge"` (148 stores) — the store builder, like the query layer, is Edge-first.
Edge and mobile are the only sources; New World has no store-finder pipeline (unlike
Pak'nSave).

```python
from tools.newworld.newworld_setup import fetch_stores, clean_stores, run_full_setup
run_full_setup()                  # default: edge → 148 stores
run_full_setup(source="edge")     # 148 stores
run_full_setup(source="mobile")   # 150 stores (legacy fallback)

df = fetch_stores(source="edge")
df = clean_stores(df, cleaned=True)   # drop stores without coordinates (no-op for NW)
```

| Source | Stores | Method | Auth | Notes |
|--------|--------|--------|------|-------|
| **Edge API** (default) | 148 | `GET /v1/edge/store` | `fs-user-token` from `get-current-user` | 2 stores missing from mobile (Foodie Mart, Te Atatu) |
| **Mobile API** (legacy fallback) | 150 | guest login + `GET /mobile/store/physical` | guest token + `NewWorldApp/4.32.0` UA | Most complete set |

**No geocoding required** — all sources provide lat/lon directly.

**Output schema** — `data/newworld_stores.csv` / `.json` (148 or 150 rows) with 10
columns (`store_id, name, address, city, region, latitude, longitude, banner,
click_and_collect, delivery`). The old store-builder flow joined website store-finder
URL slugs onto store rows; the URL column is **no longer produced** — per-store
identity and pricing come from the Edge/mobile `store_id` UUIDs via the authentication
pipeline, not website URLs.

CLI: `python -m tools.newworld.newworld_setup [--source edge|mobile] [--cleaned true|false]`
(defaults: `--source edge --cleaned true`).

### 9.1 Primary: Edge API (`GET /v1/edge/store`)

148 stores with precise coordinates, store IDs, and service flags (banner,
click-and-collect, delivery). This is the default source and the recommended starting
point.

### 9.2 Mobile API (legacy)

150 stores via guest login + `GET /mobile/store/physical`. Returns the same 10-column
schema (filtered to `banner="MNW"`). Use only as a fallback. The 2 extra stores
(Foodie Mart and New World Te Atatu) are not available via Edge.

### 9.3 CSV (`data/newworld_stores.csv`)

Pre-built by `newworld_setup.py` (see build pipeline below), with the `store_id`
UUIDs, name, address, lat, lon, and service flags for all stores:

```csv
store_id,name,address,city,region,latitude,longitude,banner,click_and_collect,delivery
773ad0a0-...,New World Albany,"219 Don McKinnon Drive...",Auckland,NI,-36.728207,174.710519,MNW,True,True
```

### 9.4 Build Pipeline (`tools/newworld/newworld_setup.py`)

```
newworld_setup.py
  → source="edge" (default): POST /api/user/get-current-user → fs-user-token cookie
                             → GET /v1/edge/store → 148 stores with UUID, name, address, lat/lon, banner, services
   → (or source="mobile"): POST /mobile/user/login/guest (banner: "MNW")
                           → GET /mobile/store/physical → 150 stores, filter banner=MNW
  → clean_stores(df) drop NaN coords
  → DataFrame → data/newworld_stores.csv / newworld_stores.json
```

No store-finder parsing, no name-joining — coordinates and store IDs come directly from
the Edge/mobile API.

---

## 10. Production Architecture & Optimisers

**All of §10 is structurally identical to [PaknSave_API.md §10](PaknSave_API.md)** — same two-phase optimiser skeleton (Phase 1 queries the API and appends to `full_results.csv`, Phase 2 reads today's rows and prints a comparison), same shared helpers (`foodstuffs_querier_edge`, `foodstuffs_querier_mobile`, `build_edge_row`, `build_mobile_row`), same unified `NewWorldAPI(backend="edge"|"mobile")` module, same Mobile-vs-Edge feature comparison, same Mobile-API + Edge-API two-pass architecture diagrams, same ingredient search strategy (first / most relevant result, 21 curated dishes from `data/dishes.json`). The NW-specific deltas:

| NW-specific item | Value |
|---|---|
| API class | `NewWorldEdgeAPI` / `NewWorldMobileAPI` (`src/NZMealOptimiser/pricing/newworld_api.py`) |
| CLI Edge entry | `tools/newworld/newworld_optimiser_edge.py` (production default) |
| CLI Mobile entry | `tools/newworld/newworld_optimiser_mobile.py` (fallback) |
| `load_stores` import | `from tools.newworld.newworld_setup import load_stores` |
| Per-run CSV (Edge) | `data/newworld_latest_results.csv` |
| Per-run CSV (Mobile) | `data/newworld_mobile_latest_results.csv` |
| Default dish example | `"spaghetti bolognese"` |
| Default address example | `"Botany Town Centre, Auckland"` |

For the full code samples (mobile `search_products` snippet, the per-store-per-ingredient loop, the `foodstuffs_querier_edge` 4-line wrapper, the unified module table, the optimisers table, the architecture diagrams) see [PaknSave_API.md §10.1-10.7](PaknSave_API.md).

---

## 11. Supported Dishes (21)

**Identical 21 dishes as [PaknSave_API.md §11](PaknSave_API.md)** — same curated list (spaghetti bolognese, chicken stir fry, beef stir fry, roast lamb, chicken curry, …, chicken katsu). The full table is in [PaknSave_API.md §11](PaknSave_API.md); the canonical source is `data/dishes.json` (shared across both Foodstuffs banners, loaded via `get_ingredients()` in `src/NZMealOptimiser/pricing/optimiser_utils.py`). LLM-backed dish generation available via `src/NZMealOptimiser/llm/llm_utils.py`. Unknown dish names fall through — the dish name itself becomes the single search query (same behaviour as Pak'nSave).

---

## 12. CLI Usage

**Edge API Optimiser (Production — two-pass, default):**
```powershell
python -m tools.newworld.newworld_optimiser_edge "Botany Town Centre, Auckland" "spaghetti bolognese"
```

**Mobile API Optimiser (Fallback — single-pass):**
```powershell
python -m tools.newworld.newworld_optimiser_mobile "Botany Town Centre, Auckland" "spaghetti bolognese"
```

**Identical CLI flags to [PaknSave_API.md §12](PaknSave_API.md)** — same `address` / `dish` positionals, same `--requery true|false` (default true), same `--distance N` (default 5 km). The only deltas: default `address` is `"Botany Town Centre, Auckland"` (vs PNS's `"588 Chapel Road, East Tāmaki, Auckland 2016"`) and the per-run CSV outputs are `data/newworld_latest_results.csv` / `data/newworld_mobile_latest_results.csv` (vs PNS's `paknsave_*`). See [PaknSave_API.md §12](PaknSave_API.md) for the full flag table.

---

## 13. Appendix: Full Edge API Endpoint Reference

Identical to [PaknSave_API.md §13](PaknSave_API.md) — same 6 endpoints (`/store`, `/store/{id}/categories`, three Algolia index endpoints, `/search/paginated/products`), same Algolia index payload schema, same paginated search payload with `productID:xxx OR productID:yyy` filters and `PRICE_ASC` / `PRICE_DESC` sortOrder, same price extraction code (regular `singlePrice.price` in cents, promo `promotions[].rewardValue` where `bestPromotion: true`, unit price `comparativePrice.pricePerUnit` / `unitQuantityUom`). The only change vs PaknSave_API.md §13 is the base URL:

- Pak'nSave: `https://api-prod.paknsave.co.nz/v1/edge`
- New World: `https://api-prod.newworld.co.nz/v1/edge`

For the complete reference (base configuration block, endpoint table, Algolia index payload, paginated search payload, sortOrder values, response price extraction code) see [PaknSave_API.md §13](PaknSave_API.md) — the New World base URL above is the only delta.

Note: `promotions` is **`null`** (not always `[]`) when a product has no promo (same as Pak'nSave).