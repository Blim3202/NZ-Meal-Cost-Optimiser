# Pak'nSave Edge API Exploration Documentation

## Overview

This folder contains exploration scripts documenting the discovery and implementation of a **two-pass pipeline** for Pak'nSave product search using the public website JWT authentication. This pipeline replaces the mobile API dependency with the public website API, provides explicit relevance matching, and enables per-store pricing with price sorting.

**Key Outcome**: The Edge API **CAN fully replace** the Foodstuffs mobile API for Pak'nSave — no dependency on internal mobile endpoint, uses public website JWT, explicit relevance matching via `_highlightResult.matchedWords`, per-store pricing via cookies + Algolia filters.

---

## Phase 1: Initial Edge API Probing — Store Listing Works

### Website JWT Authentication (F12 Network Inspection)

**Purpose**: Capture the website authentication flow to obtain JWT token.

**Discovery**:
- `GET https://www.paknsave.co.nz` seeds cookies (Cloudflare, session)
- `POST https://www.paknsave.co.nz/api/user/get-current-user` returns `fs-user-token` cookie (JWT)
- Token payload: `{"banner": "PNS", "roles": ["ANONYMOUS"]}`
- Same IdP (`online-customer`) as New World and mobile API

### Store Listing Endpoint (F12 Network Inspection)

**Purpose**: Test Edge API store listing with website JWT.

**Endpoint**: `GET https://api-prod.paknsave.co.nz/v1/edge/store`

**Result**: HTTP 200 — Returns 57 stores with full metadata (id, name, address, lat/lon, services)

**Headers Required**:
```
Authorization: Bearer {fs-user-token}
access_token: {fs-user-token}
Origin: https://www.paknsave.co.nz
Referer: https://www.paknsave.co.nz/
```

---

## Phase 2: Algolia Index Discovery — Relevance Matching Exists!

### Index Enumeration (F12 Network Inspection)

**Purpose**: Test Algolia index endpoints for different sort orders.

**Indices Tested** (pattern: `products-index-*`):
| Index | Status | Sort | `_highlightResult.matchedWords` |
|-------|--------|------|--------------------------------|
| `products-index` | 200 | **Relevance (default)** | **YES** |
| `products-index-popularity-asc` | 200 | Popularity ASC | Has matches |
| `products-index-popularity-desc` | 200 | Popularity DESC | Has matches |

**Critical Discovery**: Unlike New World, **all three working indices have `_highlightResult.matchedWords` populated** for Pak'nSave. The default `products-index` is relevance-sorted and has the best matches.

### `products` — Raw Response Capture

**Purpose**: Capture full response structure for `products-index` relevance search.

**Key Response Fields** (per hit):
```json
{
  "productID": "5104350-KGM-000",
  "DisplayName": "NZ Beef Mince",
  "brand": "None",
  "averagePrice": 18.99,
  "category1": ["Beef", "Mince, Sausages & Meatballs"],
  "category2": ["Beef Mince & Stir Fry", "Mince"],
  "category3": null,
  "_highlightResult": {
    "DisplayName": {"value": "NZ <em>Beef</em> <em>Mince</em>", "matchedWords": ["beef", "mince"]},
    "category2AndBrand": {"value": "Beef <em>Mince</em> & Stir Fry", "matchedWords": ["beef", "mince"]}
  }
}
```

**Critical Fields for Relevance Filtering**:
- `_highlightResult.DisplayName.matchedWords` — query terms matched in product name
- `_highlightResult.category2AndBrand.matchedWords` — query terms matched in category
- `category1`, `category2`, `category3` — hierarchical categories for filtering non-food items

---

## Phase 3: Two-Pass Pipeline — Production Ready

### Architecture

```
WEBSITE SESSION (no mobile API needed)
  1. GET https://www.paknsave.co.nz (seed cookies)
  2. POST /api/user/get-current-user → fs-user-token cookie (JWT)

STORE LISTING
  3. GET /v1/edge/store (with JWT) → 57 stores with coords/IDs

FOR EACH INGREDIENT AT EACH STORE:
  PASS 1 — RELEVANCE (Algolia default index)
    POST /v1/edge/search/products/query/index/products-index
    Body: {"algoliaQuery": {"query": "beef mince"}, "page": 0, "hitsPerPage": 20, "storeId": "..."}
    → Extract productIDs where _highlightResult has non-empty matchedWords
    → Filter by category1 to exclude non-food items (NON_FOOD_CATEGORIES: 53 values)

  PASS 2 — PER-STORE PRICING (Paginated with filters)
    POST /v1/edge/search/paginated/products
    Body: {
      "algoliaQuery": {"query": "beef mince", "filters": "productID:xxx OR productID:yyy"},
      "page": 0, "hitsPerPage": 50, "storeId": "...", "sortOrder": "PRICE_ASC"
    }
    → Returns singlePrice.price (cents) + promotions[].rewardValue (promo cents)
    → Sorted by price at THIS store
```

### Endpoints

| Endpoint | Method | Auth | Cookies | Purpose |
|----------|--------|------|---------|---------|
| `/api/user/get-current-user` | POST | None | Session | Get JWT token |
| `/v1/edge/store` | GET | JWT | Optional | List all stores |
| `/v1/edge/search/products/query/index/products-index` | POST | JWT | Store context | Relevance search |
| `/v1/edge/search/paginated/products` | POST | JWT | Store context | Per-store pricing |

### Store Context Cookies (Required for Pricing)
```python
cookies = {
    "eCom_STORE_ID": store_id,
    "STORE_ID_V2": f"{store_id}|False",
    "Region": "NI"  # or "SI" for South Island
}
```

### Valid `sortOrder` Values (Paginated Endpoint)
- `PRICE_ASC` — Cheapest first [OK]
- `PRICE_DESC` — Most expensive first [OK]
- `RELEVANCE` [FAIL] (400 enum mismatch)
- `DEFAULT` [FAIL] (400 enum mismatch)

---

## Phase 4: Validation & Demo

### `demo_two_pass_pipeline.py` — Complete Proof of Concept

**Purpose**: End-to-end meal cost optimiser using two-pass pipeline.

**Features**:
- Website JWT authentication
- Geocoding via Nominatim
- Haversine distance filtering (5km radius)
- Two-pass search per ingredient per store (top 20 relevance → price sorted)
- Non-food category1 filtering (53 categories: pet, baby, household, health, etc.)
- Promotional price detection (`promotions[].rewardValue`)
- Cost comparison across nearby stores

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

**PASS 1 Detail** (beef mince):
```
Relevant product IDs found: 37 (after non-food category1 filtering)
  5104350-KGM-000  (NZ Beef Mince)
  5101189-KGM-000  (NZ Premium Beef Mince)
  5040757-EA-000   (Angus Beef Mince)
  5203717-EA-000   (Wagyu Beef Mince)
  ...
```

**PASS 2 Pricing** (sorted PRICE_ASC):
```
  $1.99  Gluten Free Sweet & Spicy Minced Beef Ready Sauce 120g (PROMO)
  $5.55  Beef Mince & Cheese Pie 200g (PROMO)
  $8.99  Beef Mince 340g
  $9.49  Pork & Beef Mince 380g
  $10.29 Beef Smash Burgers 400g (PROMO)
  $19.99 NZ Beef Mince kg
  $23.99 NZ Beef Prime Mince kg
  $26.99 NZ Premium Beef Mince kg
```

---

## Summary: Exploration Timeline & Key Discoveries

| Phase | Discovery |
|-------|-----------|
| 1 | Website JWT works for Edge API (`fs-user-token` from `get-current-user`) |
| 1 | Store listing: `GET /v1/edge/store` → 57 stores with lat/lon |
| 2 | Algolia index `products-index` returns relevance-sorted results with `_highlightResult.matchedWords` |
| 2 | Category fields (`category1`, `category2`, `category3`) available in Pass 1 for filtering |
| 3 | Paginated endpoint `/v1/edge/search/paginated/products` accepts Algolia `filters` parameter |
| 3 | Two-pass pipeline: Pass 1 gets relevant productIDs → Pass 2 gets per-store prices via filters |
| 3 | Non-food category1 filtering via `NON_FOOD_CATEGORIES` (53 values) in Pass 1 |
| 3 | Promotional pricing via `promotions[].rewardValue` |
| 4 | Full optimiser demo working across multiple stores for multi-ingredient dishes |

---

## Advantages Over Mobile API

| Feature | Mobile API | Edge API (Two-Pass) |
|---------|------------|---------------------|
| Auth | Guest token (30 min) | Website JWT (same IdP, more stable) |
| Dependency | Internal Foodstuffs API | Public website API |
| Relevance matching | Implicit (first result) | **Explicit `_highlightResult.matchedWords`** |
| Per-store pricing | Native (storeId in URL) | Via cookies + Algolia filters |
| Price sorting | `PriceAsc` | `PRICE_ASC`, `PRICE_DESC` |
| Promotions | Included | Included (`rewardValue`) |
| Non-food filtering | Not available | **Available via `category1` in Pass 1 (53 categories)** |

---

## Files in This Folder (Operational Order)

```
scripts/paknsave/Exploration/
├── Exploration.md                # This file
└── demo_two_pass_pipeline.py     # Complete optimiser proof of concept
```

---

## Next Steps

1. **Integrate into `PaknSave_prototype.py`** — Replace mobile API calls with Edge API two-pass pipeline
2. **Add South Island region support** — Region cookie `SI` for South Island stores
3. **Category-aware ingredient matching** — Use `category2`/`category3` for better filtering (e.g., "fresh" vs "frozen" vs "sauce")
4. **Performance optimisation** — Batch ingredient searches per store, cache JWT token
5. **Fallback to mobile API** — Keep mobile API as fallback if Edge API unavailable

---

## Credits

This exploration builds on the New World Edge API discovery documented in `scripts/newworld/Exploration/`. The two-pass architecture pattern is identical between the two banners since they share the same backend infrastructure (Apigee + Algolia).