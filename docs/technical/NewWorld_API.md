# New World / Foodstuffs North Island Mobile API Documentation

**API origin:** `api-prod.prod.fsniwaikato.kiwi` — despite the "FSNI" (Foodstuffs North
Island) domain name, this API covers **all New World stores nationwide** including
both North Island (101 stores) and South Island (48 stores). It also works for
Pak'nSave with `banner: "PNS"`.

---

## 1. Overview

The New World mobile API at `api-prod.prod.fsniwaikato.kiwi` shares the same structure as the Pak'nSave API — the only differences are the `banner` value (`"MNW"` vs `"PNS"`) and the `User-Agent` header (`NewWorldApp/4.32.0` vs `PAKnSAVEApp/4.32.0`). See [PaknSave_API.md](PaknSave_API.md) for the full shared API documentation (auth flow, mobile endpoints, Edge API, two-pass pipeline). This document covers New World-specific differences only.

**Credits:** Authored by [Arefu](https://github.com/Arefu) through reverse engineering the Foodstuffs Android app. Full OpenAPI spec in their [PaknSave repo](https://github.com/Arefu/PaknSave).

---

## 2. Base URL and Host

```
Base URL:   https://api-prod.prod.fsniwaikato.kiwi/prod
Pre-prod:   https://api-preprod.test.fsniwaikato.kiwi
QA:         https://api-qa.test.fsniwaikato.kiwi
Backend:    fsniwaikato.kiwi  (Foodstuffs North Island)
```

All endpoints below are relative to `/prod`.

---

## 3. Required Request Headers

### 3.1 Authentication Endpoint

The guest login endpoint requires only:

```
User-Agent:    NewWorldApp/4.32.0
Content-Type:  application/json
```

### 3.2 Authenticated Endpoints

After obtaining an `access_token`, all subsequent requests need both:

```
Authorization:  Bearer {token}
access_token:   {token}
User-Agent:     NewWorldApp/4.32.0
Content-Type:   application/json
```

**Note:** The `access_token` header is duplicated intentionally — the API inspects
both `Authorization` and the custom `access_token` header. Omitting either can
cause 401 errors.

---

## 4. Authentication Flow

### 4.1 Guest Login

New World uses a simple bearer-token auth model, identical to Pak'nSave. No user
account, no password, no OAuth — just a `POST` with a banner identifier:

```
POST /mobile/user/login/guest
```

#### Request body

```json
{"banner": "MNW"}
```

`banner` values:

| Value | Brand |
|-------|-------|
| `"PNS"` | Pak'nSave |
| `"MNW"` | New World |

If the body is omitted entirely, a New World token is returned by default.

#### Response (HTTP 200)

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "bearer",
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "expires_in": 1800,
  "scope": "openid email profile phone all offline_access"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `access_token` | `string` | JWT bearer token, valid for 1800 seconds (30 minutes) |
| `refresh_token` | `string` | Used to obtain a new access_token without re-logging in |
| `expires_in` | `int` | Token TTL in seconds |
| `scope` | `string` | Rights granted to this token |

#### Token auto-refresh

**No automatic refresh in production code.** Guest login returns `expires_in: 1800` (30 min)
but `NewWorldMobileAPI._ensure_token()` discards it — the token is cached once and is a
permanent no-op thereafter, so it is **never refreshed**; a stale token 401s after 30 min
and only a new `NewWorldMobileAPI()` recovers. The `/refreshtoken` endpoint (4.2) is
confirmed working in `Exploration/explore_edge_api3.py` but **not wired into** the client.
Edge's `fs-user-token` JWT also expires ~30 min (design.md "Fresh JWT required"), but
`NewWorldEdgeAPI` reads only the cookie *value* (never its Max-Age) and `authenticate()`
runs **once per run** (optimiser_utils.py:761, not per store) — no per-store re-auth, no
retry on expiry.

### 4.2 Token Refresh

```
POST /mobile/v1/users/login/refreshtoken
```

#### Request headers

```
User-Agent: NewWorldApp/4.32.0
```

#### Request body

```json
{"refresh_token": "eyJhbGciOiJSUzI1NiIs..."}
```

#### Response (HTTP 200)

```json
{
  "accessToken": "eyJhbGciOiJSUzI1NiIs...",
  "refreshToken": "eyJhbGciOiJSUzI1NiIs..."
}
```

#### Response (HTTP 401 — expired/invalid)

```json
{
  "fields": null,
  "status": 401,
  "message": "Refresh token expired or invalid",
  "code": "NOT_SUPPORTED"
}
```

The refresh token approach is not currently used by this project.

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

### 5.2 `POST /mobile/ecomm-products/{banner}/{storeId}/search?q={query}`

The primary product search endpoint. Returns relevant products for a given query at a
specific store, **with per-store pricing**.

**HTTP 200** — requires auth headers.

#### Path parameters

| Parameter | Type | Example |
|-----------|------|---------|
| `banner` | `string` | `"MNW"` |
| `storeId` | `string` (UUID) | `"773ad0a0-024e-46c5-a94b-df1cf86d25cc"` |

#### Query parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | `string` | (required) | Search query, e.g. `"beef mince"` |
| `hitsPerPage` | `int` | `100` | Max products per page. **Honored** — confirmed: `5`→5 products, `20`→20 products returned (see Pagination). Production always sends `20`. |
| `sortOrder` | `string` | (relevance) | Sort by relevance or price (not used by production) |
| `searchingTobacco` | `bool` | `false` | If the search is for tobacco products (not used by production) |
| `disableAdsOverride` | `bool` | `false` | Disable ad insertion in results (not used by production) |

The `sortOrder`, `searchingTobacco`, and `disableAdsOverride` params are *not used* by
this project (the optimiser always relies on the default relevance ordering and only
sends `q` + `hitsPerPage`).

#### Request body

Send an empty JSON array:

```json
[]
```

The body is required but can be empty — it's used internally for filter state
(e.g., dietary/lifestyle filters). An empty array means "no filters".

#### Response structure

```json
{
  "tobaccoFiltered": false,
  "totalHits": 10,
  "hitsPerPage": 20,
  "numberOfPages": 1,
  "page": 1,
  "products": [
    {
      "productId": "c9b5f8e2-...",
      "brand": "Pams",
      "name": "NZ Beef Mince",
      "units": "kg",
      "categories": ["Meat & Poultry", "Beef", "Mince"],
      "price": 1899,
      "unitPrice": "$18.99/kg",
      "productImageUrls": {
        "100": "https://...",
        "200": "https://...",
        "400": "https://...",
        "500": "https://..."
      },
      "decalCode": "club",
      "decalImageUrl": "https://...",
      "availableInStore": true,
      "availableInOnline": true,
      "tobaccoFlag": false,
      "liquorFlag": false,
      "saleType": "standard",
      "algoliaAnalytics": {
        "searchQueryID": "abc123",
        "searchPosition": 1
      },
      "boughtBefore": false,
      "badgeSmallUrl": null,
      "badgeMediumUrl": null,
      "badgeLargeUrl": null
    },
    ...
  ],
  "filters": {
    "Deals": {},
    "Dietary & lifestyle": {},
    "Categories": {
      "Meat & Poultry": 175,
      "Beef": 42,
      ...
    },
    "Brands": {
      "Pams": 5,
      ...
    }
  }
}
 ```
#### Response shape (Mobile API)

The mobile search endpoint returns either a **bare JSON array** of products or a
**wrapped dict** with a `"products"` key. The production code in
`newworld_api.py` (and the shared `optimiser_utils.py` helpers) handles both shapes
defensively:

```python
data = r.json()
products = data if isinstance(data, list) else data.get("products", [])
```

#### Product fields

| Field | Type | Notes |
|-------|------|-------|
| `productId` | `string` (UUID) | Unique product identifier across all stores |
| `name` | `string` | Product display name |
| `brand` | `string` | Brand name (e.g. `"Pams"`, `"Value"`) |
| `price` | `integer` | **Price in cents** — divide by 100 for dollars |
| `units` | `string` | Unit of sale: `"kg"`, `"L"`, `"400g"`, `"12pk"`, `"each"`, `"1pk"`. When `unitPrice` is missing/null and `units` has a numeric prefix (e.g. `"1pk"`), the optimiser infers per-unit pricing from the item's own `price` — `per_unit_quantity` becomes the `measurement_unit` (e.g. `"pk"`) and `per_unit_price` mirrors the item price. |
| `unitPrice` | `string` | Formatted unit price string, e.g. `"$18.99/kg"` |
| `categories` | `array[string]` | Hierarchical category path, e.g. `["Meat & Poultry", "Beef", "Mince"]` |
| `availableInOnline` | `bool` | Can be ordered online |
| `availableInStore` | `bool` | In stock at this store |
| `saleType` | `string` | `"standard"`, `"special"`, `"club"` |
| `tobaccoFlag` | `bool` | Is a tobacco product |
| `liquorFlag` | `bool` | Is an alcohol product |

#### Price handling

**Critical: prices are in cents.** Always divide `price` by 100:

```python
price_dollars = product["price"] / 100
```

#### Per-store pricing

Each `{storeId}` returns independent prices for the same product. For example,
searching "standard milk" at New World Albany vs New World Newmarket may return
different `price` values for the same `productId`. This is the foundation of the
meal cost optimiser.

#### `categories` mapping & non-food filtering

The mobile `categories` array has exactly 2 elements and is **not** the 3-level
hierarchical path. Mapping to the CSV columns:

| Index | Meaning | CSV column |
|-------|---------|------------|
| `categories[0]` | category1 | `sub_department` |
| `categories[1]` | category2 | (not stored) |

There is **no department (category0)** field in the mobile product — `department`
is left blank for mobile rows. Non-food filtering checks **only** `categories[0]`
(category1) against the shared `NON_FOOD_CATEGORIES` set — e.g. `["Dog", "Wet Dog
Food"]` is filtered out because `categories[0]` is `"Dog"`. A product with an empty
`categories` array is treated as food.

#### Mobile parsing (`units` + `unitPrice` → 4-tuple)

The optimiser splits the mobile product into
`(quantity, measurement_unit, per_unit_quantity, per_unit_price)` in one call via
`parse_foodstuffs_mobile_unit(units, unitPrice, price_cents)`:

- `units` packs count + measure together, e.g. `"3 x 80g"` → `quantity=3`,
  `measurement_unit="x 80g"`; `"500g"` → `(500, "g")`; `"ea"` → `(1, "ea")`.
- `unitPrice` splits on `/`: `"$26.99/1kg"` → `per_unit_quantity="1kg"`,
  `per_unit_price=26.99` (dollar sign stripped, cents→dollars).
- **Bare-`"ea"` and numeric-prefix fallback**: when `unitPrice` is `null` or missing but `units` has a numeric count (e.g. `"1pk"`, `"500g"`, `"2 pack"`) or is bare `"ea"`, set `per_unit_quantity` to the `measurement_unit` (e.g. `"pk"`, `"g"`, `"pack"`, `"ea"`) and mirror the item's own `price` (from `price_cents`) into `per_unit_price` — avoids blank per-unit columns.

#### Pagination

| Field | Description |
|-------|-------------|
| `page` | Current page (1-indexed) |
| `hitsPerPage` | Items per page — **default 100** unless a `hitsPerPage` query param is sent |
| `numberOfPages` | Total page count |
| `totalHits` | Total matching products (across all pages) |

`hitsPerPage` is honored: sending it caps the returned `products` length without
affecting `totalHits`. Default is `100` (larger than the typical result count, so most
ingredient searches return in a single page).


#### Specifying sort order

The mobile endpoint's sort parameter is not used by this project. The optimiser relies
on the default relevance ordering (returns the most-relevant results first) and only
sends `q` + `hitsPerPage`.

### 5.3 `POST /mobile/ecomm-products/{banner}/{storeId}/specials`

Returns products currently on special at a specific store. Supports filtering by
deal category.

**HTTP 200** — requires auth headers.

#### Path parameters

| Parameter | Type | Notes |
|-----------|------|-------|
| `banner` | `string` | `"PNS"` or `"MNW"` |
| `storeId` | `string` (UUID) | Store identifier |

#### Query parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `sortOrder` | `string` | Sort order for results |

#### Request body

An array of filter objects. Each object has a `title` (filter group name) and
`items` (array of filter values). An empty array returns all specials:

```json
[]
```

To filter by deal category:

```json
[
  {
    "title": "Deals",
    "items": ["Super Specials"]
  }
]
```

#### Response structure

Same product array format as search/specials.

#### Known deal types (observed)

| Filter value | Description |
|-------------|-------------|
| `"Super Specials"` | Deep-discount limited-time deals |
| `"Weekly Specials"` | Standard weekly catalogue specials |

### 5.4 `GET /mobile/v1/products/category`

Returns the hierarchical product category tree for a specific store.

**HTTP 200** — requires auth headers.

#### Query parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `storeId` | `string` (UUID) | Store identifier |
| `banner` | `string` | `"PNS"` or `"MNW"` |
| `region` | `string` | Region code (e.g. `"NI"`) |

#### Response structure

```json
[
  {
    "name": "Meat & Poultry",
    "code": "delicounter",
    "appContent": { ... },
    "children": [
      {
        "name": "Beef",
        "code": null,
        "appContent": { ... },
        "children": [
          {
            "name": "Mince",
            "code": null
          }
        ]
      }
    ]
  }
]
```

Categories are nested three levels deep. Each node has:
- `name`: display name
- `code`: optional category code (present for top-level "aisle" categories)
- `appContent`: optional promotional content (panel with title, image, product)
- `children`: subcategories (same structure)

### 5.5 `GET /mobile/v1/products/category` (Browse by category path)

Returns products for a specific category path within a store.

**HTTP 200** — requires auth headers.

#### Path parameters

| Parameter | Type |
|-----------|------|
| `banner` | `string` |
| `storeId` | `string` (UUID) |

#### Query parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `cat0` | `string` | Top-level category name |
| `cat1` | `string` | Second-level category name (optional) |
| `cat2` | `string` | Third-level category name (optional) |
| `sortOrder` | `string` | Sort order |

#### Response structure

Same product array format as search/specials.

---

## 6. New World Edge API (Website Backend)

The New World website at `www.newworld.co.nz` exposes an Edge API at
`api-prod.newworld.co.nz`. This API uses Apigee gateway with JWT verification.

### 6.1 Authentication

The Edge API accepts JWT tokens from the **same IdP** (`online-customer`) as the mobile API.
Two ways to obtain a valid JWT:

| Method | Endpoint | Token Location |
|--------|----------|----------------|
| Mobile API guest login | `POST /mobile/user/login/guest` (mobile API) | Response body `access_token` |
| Website session | `POST /api/user/get-current-user` (website) | Cookie `fs-user-token` |

**Required headers for all Edge API calls:**
```
Authorization: Bearer {jwt_token}
access_token:  {jwt_token}
User-Agent:    Mozilla/5.0... (browser) OR NewWorldApp/4.32.0 (mobile)
Origin:        https://www.newworld.co.nz
Referer:       https://www.newworld.co.nz/
```

**Store context cookies (REQUIRED for per-store pricing):**
```
eCom_STORE_ID: {store_id}
STORE_ID_V2:   {store_id}|False
Region:        NI  (or SI for South Island)
```

---

### 6.2 Store Listing

**Endpoint**: `GET https://api-prod.newworld.co.nz/v1/edge/store`

**Status**: [OK] **Works (HTTP 200)** with valid JWT.

**Returns**: 148 stores with full details (id, name, address, coordinates, opening hours, services).

**Note**: Returns 148 stores vs 150 from mobile API. The two stores missing from
Edge are `Foodie Mart` (35 Landing Drive, Mangere — an in-house Foodstuffs location)
and `New World Te Atatu` (575 Te Atatū Road, Te Atatū Peninsula). Both appear in
the mobile API response but not the Edge API, so Edge is the smaller set.

---

### 6.3 Product Search — TWO-PASS ARCHITECTURE

**TL;DR**: The Edge API does NOT have a single endpoint that provides both relevance matching AND per-store pricing. We discovered a **two-pass pipeline** that combines the best of both endpoints.

#### The Problem We Faced

| Endpoint | Relevance Matching | Per-Store Pricing |
|----------|-------------------|-------------------|
| `products-index` (Algolia) | [OK] Has `_highlightResult` with `matchedWords` | [NO] Only `averagePrice` (cross-store) |
| `products-index-popularity-asc/desc` | [OK] Has `_highlightResult` with `matchedWords` | [NO] Only `averagePrice` |
| `/search/paginated/products` | [NO] No `RELEVANCE` sort (400 enum mismatch) | [OK] Full per-store pricing |

#### The Solution: Two-Pass Pipeline

**PASS 1 — Relevance Matching (Algolia Index)**
```
POST https://api-prod.newworld.co.nz/v1/edge/search/products/query/index/products-index
```

Payload:
```json
{
  "algoliaQuery": {"query": "beef mince"},
  "page": 0,
  "hitsPerPage": 20,
  "storeId": "{store_id}"
}
```

Full response truncated. Response includes `_highlightResult` with `matchedWords`:
```json
{
  "hits": [
    {
      "productID": "5101189-KGM-000",
      "DisplayName": "NZ Premium Beef Mince",
      "brand": "None",
      "averagePrice": 18.99,
      "category1": ["Beef", "Mince, Sausages & Meatballs"],
      "category2": ["Beef Mince & Stir Fry", "Mince"],
      "_highlightResult": {
        "DisplayName": {"value": "NZ Premium <em>Beef</em> <em>Mince</em>", "matchedWords": ["beef", "mince"]},
        "category2AndBrand": {"value": "Beef <em>Mince</em> > Premium", "matchedWords": ["beef", "mince"]}
      }
    }
  ]
}
```

**Key**: Extract `productID` from hits where `_highlightResult` has non-empty `matchedWords`.

**PASS 2 — Per-Store Pricing (Paginated Endpoint with Filters)**
```
POST https://api-prod.newworld.co.nz/v1/edge/search/paginated/products
```

Payload (using Algolia filter syntax):
```json
{
  "algoliaQuery": {
    "query": "beef mince",
    "filters": "productID:5101189-KGM-000 OR productID:5104350-KGM-000 OR productID:5122727-KGM-000"
  },
  "page": 0,
  "hitsPerPage": 50,
  "storeId": "{store_id}",
  "sortOrder": "PRICE_ASC"
}
```

Response with per-store pricing:
```json
{
  "products": [
    {
      "productId": "5349090-EA-000",
      "name": "Beef Mince",
      "displayName": "340g",
      "brand": "Hellers",
      "singlePrice": {"price": 949, "comparativePrice": {"pricePerUnit": 2791, "unitQuantityUom": "kg"}},
      "promotions": [],
      "availability": ["IN_STORE", "ONLINE"]
    }
  ]
}
```

**Price extraction:**
- Regular price (cents): `singlePrice.price`
- Promotional price (cents): `promotions[].rewardValue` where `bestPromotion: true`
- Unit price: `singlePrice.comparativePrice.pricePerUnit` (cents per unit)
- `promotions` is **`null`** when a product has no promo (not always `[]`)

---

### 6.4 Algolia Indices — What Exists vs What Doesn't

We probed 14+ index names. Only THREE return HTTP 200:

| Index Name | Status | Sort Order | `_highlightResult` | Use Case |
|------------|--------|------------|-------------------|----------|
| `products-index` | [OK] 200 | **Relevance (Algolia default)** | [OK] YES — has `matchedWords` | **PASS 1: Relevance matching** |
| `products-index-popularity-asc` | [OK] 200 | Popularity ascending | [OK] YES — has `matchedWords` | Browsing (least popular first) |
| `products-index-popularity-desc` | [OK] 200 | Popularity descending | [OK] YES — has `matchedWords` | Browsing (most popular first) |
| `products-index-price-asc` | [NO] 500 | — | — | Does not exist |
| `products-index-price-desc` | [NO] 500 | — | — | Does not exist |
| `products-index-relevance` | [NO] 500 | — | — | Does not exist |
| `products-index-name-asc` | [NO] 500 | — | — | Does not exist |
| `products-index-name-desc` | [NO] 500 | — | — | Does not exist |
| `products-index-newest` | [NO] 500 | — | — | Does not exist |
| `products-index-bestselling` | [NO] 500 | — | — | Does not exist |
| `products-index-trending` | [NO] 500 | — | — | Does not exist |

> **Status note (verified 2026-08-04)**: These eight indices do not exist and
> return an error — the Edge API now responds with **`HTTP 500`
> (`{"code":"InternalServer","message":""}`)**, not `404` as previously
> documented. They cannot be used for search.

**Key Discovery**: All three indices return identical `_highlightResult` with `matchedWords` — the only difference is sort order. `products-index` (relevance-sorted) is preferred for the two-pass pipeline since top hits match the query best.

---

### 6.5 Paginated Search Endpoint — Full Capabilities

**Endpoint**: `POST https://api-prod.newworld.co.nz/v1/edge/search/paginated/products`

**Authentication**: Website JWT (fs-user-token cookie) OR mobile API token

**Required Cookies** (per-store context):
```python
cookies = {
    "eCom_STORE_ID": store_id,
    "STORE_ID_V2": f"{store_id}|False",
    "Region": "NI" # or "SI" for South Island
}
```

**Valid `sortOrder` values** (tested, validated enum):
- `PRICE_ASC` — Cheapest first at this store
- `PRICE_DESC` — Most expensive first

**Invalid `sortOrder` values** (return HTTP 400 enum mismatch):
- `RELEVANCE` [NO]
- `RELEVANCY` [NO]
- `DEFAULT` [NO]
- `BEST_MATCH` [NO]

**Algolia Filter Syntax** (confirmed working):
```json
"algoliaQuery": {
  "query": "milk",
  "filters": "productID:5201479-EA-000 OR productID:5201490-EA-000 OR productID:5201487-EA-000"
}
```

Supports: `OR`, `AND`, field:value syntax. Full Algolia filter syntax works.

**Response Structure:**
```json
{
  "products": [...],
  "totalHits": 34,
  "page": 0,
  "totalPages": 1,
  "hitsPerPage": 50,
  "algoliaSearchResult": {},
  "tobaccoProducts": []
}
```

**Product Fields:**
| Field | Type | Notes |
|-------|------|-------|
| `productId` | string | Matches `productID` from Algolia index |
| `name` | string | Product name |
| `displayName` | string | Size/variant (e.g., "2l", "340g") |
| `brand` | string | Brand name |
| `singlePrice.price` | int | Regular price in cents |
| `singlePrice.comparativePrice` | object | Unit pricing info |
| `promotions[]` | array | Promo objects with `rewardValue` (cents) |
| `availability` | array | `["IN_STORE", "ONLINE"]` etc. |
| `algoliaAnalytics.searchPosition` | int | Position in sorted results |

**Price extraction:**
- Regular price (cents): `singlePrice.price`
- Promotional price (cents): `promotions[].rewardValue` where `bestPromotion: true`
- Unit price (cents per unit): `singlePrice.comparativePrice.pricePerUnit` — note the
  base quantity can be 100g/10g/1L (see `measureDescription`), so convert with that.

---

### 6.6 Categories Endpoint

**Endpoint**: `GET https://api-prod.newworld.co.nz/v1/edge/store/{store_id}/categories`

**Status**: [OK] **Works (HTTP 200)** with valid JWT + store cookies.

**Returns**: Category tree for store navigation.

---

### 6.7 Comparison: Mobile API vs Edge API (Two-Pass)

| Feature | Mobile API | Edge API (Two-Pass) |
|---------|------------|---------------------|
| Auth | Guest login POST | Website session OR mobile token |
| Store listing | [OK] 150 stores | [OK] 148 stores |
| Product search | [OK] Single call | [OK] Two-pass (relevance + pricing) |
| Relevance matching | Implicit (relevance ordering) | [OK] Explicit `_highlightResult.matchedWords` |
| Per-store pricing | [OK] Native (storeId in URL) | [OK] Via cookies + Algolia filters |
| Price format | Cents in response | Cents in `singlePrice.price` |
| Promotions | Included | Included in `promotions[]` |
| Sort | Relevance (default), PriceAsc | `PRICE_ASC`, `PRICE_DESC` only |
| Pagination | `hitsPerPage` query param (default 100) | Algolia page/hitsPerPage |
| Token source | Mobile API only | Mobile API OR website |
| Dependency | Internal mobile API | Public website API (more stable) |
| Pet food filtering | [OK] Via `categories[0]` (category1) | [OK] Via `category1` in Pass 1 |

---

### 6.8 Two-Pass Pipeline Summary

```
PASS 1  POST /v1/edge/search/products/query/index/products-index
        payload: {"algoliaQuery":{"query":ingredient}, "page":0, "hitsPerPage":20, "storeId":id}
        → hits with _highlightResult.matchedWords; keep productID where matched
          AND category1 not in NON_FOOD_CATEGORIES

PASS 2  POST /v1/edge/search/paginated/products
        payload: {"algoliaQuery":{"query":ingredient,"filters":"productID:a OR productID:b ..."},
                  "page":0, "hitsPerPage":50, "storeId":id, "sortOrder":"PRICE_ASC"}
        → products with per-store singlePrice + promotions
```
The complete production pipeline is implemented by the shared helper
`foodstuffs_querier_edge` in `src/NZMealOptimiser/pricing/optimiser_utils.py`, which the
New World Edge optimiser (`newworld_optimiser_edge.py`) calls with the
`NewWorldEdgeAPI` class and `find_nearby_stores`. Each brand's API class mirrors the
same two-pass structure:

Reference implementation: `src/NZMealOptimiser/pricing/newworld_api.py` —
`NewWorldEdgeAPI.pass1_relevance_search_hits` / `pass2_per_store_pricing`.

---

### 6.9 Why This Matters for the Meal Cost Optimiser

**Without relevance matching**: Searching "beef mince" could return pet food, pies, or unrelated products first.

**With two-pass pipeline**: 
1. Algolia finds ACTUALLY RELEVANT products (beef mince, not cat food)
2. Paginated endpoint gets EXACT per-store prices for those relevant products
3. Sort by `PRICE_ASC` to find cheapest at that store

This method seems to be superior to the mobile API in terms of search relevancy and should be more robust than the version-dependant mobile API endpoint which could break at any point.

---

### 6.10 Exploration Timeline & Breakthroughs

| Phase | What We Tried | Result | Breakthrough |
|-------|---------------|--------|--------------|
| 1 | Mobile API endpoints | All worked | Baseline established |
| 2 | Edge API `/v1/edge/store/physical` | [OK] 200 with JWT | Store listing works |
| 3 | Edge API `/v1/edge/products/search` | [NO] 404 | Wrong endpoint |
| 4 | Edge API `/v1/edge/ecomm-products/*` | [NO] 404 | Legacy paths dead |
| 5 | Browser DevTools capture | Found `products-index-popularity-asc` | **Algolia index pattern discovered** |
| 6 | Tested 14+ index names | Only 3 work (200) | `products-index` = relevance |
| 7 | Tested `/search/paginated/products` | [OK] 200 with cookies | Per-store pricing works |
| 8 | Tried `sortOrder: RELEVANCE` | [NO] 400 enum mismatch | No relevance sort on pricing endpoint |
| 9 | Tried Algolia `filters` parameter | [OK] Works! | **Bridge between relevance + pricing** |
| 10 | Two-pass pipeline | [OK] End-to-end working | **Production-ready solution** |

---

### 6.11 Conclusion

**The Edge API CAN fully replace the mobile API** for the meal cost optimiser:

1. [OK] Store listing works (148 stores)
2. [OK] Product search works via two-pass pipeline
3. [OK] Explicit relevance matching via `_highlightResult`
4. [OK] Per-store pricing via cookies + Algolia filters
5. [OK] Promotional pricing included
6. [OK] Works with website JWT (no mobile API dependency)
7. [OK] More future-proof (public website API)
8. [OK] Pet food filtering via `category1` in Pass 1 (exclude `{"Dog", "Cat", "Pet"}` categories)

**Advantages of Edge API over Mobile API:**
- No dependency on Foodstuffs mobile API endpoint
- Explicit relevance matching (not just "first result")
- Algolia-powered search with proper price sorting
- Works with standard browser JWT (same IdP: `online-customer`)
- Categories endpoint available for navigation

**Implementation Reference**: `src/NZMealOptimiser/pricing/newworld_api.py` (`NewWorldEdgeAPI`) + `src/NZMealOptimiser/pricing/optimiser_utils.py` (`foodstuffs_querier_edge`)
**Full Exploration Details**: `exploration/newworld/Exploration.md`

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

> **Default backend: Edge API (two-pass).** The unified API client
> `NewWorldAPI(backend="edge")` and the production CLI optimiser
> (`newworld_optimiser_edge.py`) default to the Edge backend. The mobile backend
> (`backend="mobile"`, `newworld_optimiser_mobile.py`) is the legacy fallback.

This section shows how the production code queries the two backends and parses the
responses into CSV rows. Both backends follow the same skeleton (shared by Pak'nSave;
see [PaknSave_API.md §8](PaknSave_API.md) for the parallel implementation):

```
geocode(address) → find_nearby_stores(lat, lon, radius_km)
→ for each store, for each ingredient:  search_ingredient (edge) / search_products (mobile)
→ build_row(product[, pass1_hit]) → append_rows() → data/full_results.csv
→ Phase 2: optimise() reads today's rows → per-store totals + per-ingredient breakdown
```

### 8.1 Edge API (two-pass) — `NewWorldEdgeAPI`

Two calls per ingredient per store, bridged by Algolia `filters` (identical structure to
Pak'nSave — see [PaknSave_API.md §6.3](PaknSave_API.md)):

```
Pass 1  POST /v1/edge/search/products/query/index/products-index
        payload: {"algoliaQuery":{"query":ingredient}, "page":0, "hitsPerPage":20, "storeId":id}
        → hits with _highlightResult.matchedWords; keep productID where matched
          AND category1 not in NON_FOOD_CATEGORIES  (Dog/Cat/Pet excluded)

Pass 2  POST /v1/edge/search/paginated/products
        payload: {"algoliaQuery":{"query":ingredient,"filters":"productID:a OR productID:b ..."},
                  "page":0, "hitsPerPage":50, "storeId":id, "sortOrder":"PRICE_ASC"}
        → products with per-store singlePrice + promotions
```

`build_row` then calls `parse_foodstuffs_volume_size(displayName, singlePrice, promotions)`
to get `(quantity, measurement_unit, per_unit_quantity, per_unit_price)` from the
`comparativePrice.measureDescription` (e.g. `"100g"`, `"1L"`).

### 8.2 Mobile API (single-pass) — `NewWorldMobileAPI`

One call per ingredient per store:

```
POST /mobile/ecomm-products/MNW/{storeId}/search?q={ingredient}&hitsPerPage=20
→ bare-or-wrapped products; _is_food_product() keeps rows where categories[0]
  (category1) not in NON_FOOD_CATEGORIES
```

`build_row` calls `parse_foodstuffs_mobile_unit(units, unitPrice, price_cents)` to get
`(quantity, measurement_unit, per_unit_quantity, per_unit_price)`. `units` packs
count + measure (`"3 x 80g"`, `"500g"`, `"1pk"`, `"each"`); `unitPrice` splits on `/`
(`"$18.99/kg"` → qty `1kg`, price `18.99`). When `unitPrice` is missing/null and `units`
has a numeric prefix, per-unit pricing is inferred from the item's own `price`.

### 8.3 Shared CSV schema (`data/full_results.csv`)

Both backends write to the same `full_results.csv` with 17 columns. `pk_hash`
(SHA-256 of `store_id|sku|date_created`) deduplicates appended rows.

| Column | Edge source | Mobile source |
|--------|-------------|---------------|
| `quantity` / `measurement_unit` | `displayName` via `parse_foodstuffs_volume_size` | `units` via `parse_foodstuffs_mobile_unit` |
| `per_unit_quantity` / `per_unit_price` | `comparativePrice.measureDescription` / `pricePerUnit` | `unitPrice` split (or `price` for bare-`ea`) |
| `department` | Pass 1 `category0` | *(empty — mobile has no category0)* |
| `sub_department` | Pass 1 `category1` | `categories[0]` |
| `price` | promo `rewardValue` else `singlePrice.price` (cents) | `price` (cents) |

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

### 10.1 How to Search Products by Store (Mobile API)

```python
from NZMealOptimiser.pricing.newworld_api import NewWorldMobileAPI

api = NewWorldMobileAPI()
api._ensure_token()

results = api.search_products(store_id, "beef mince")
products = results or []
for p in products:
    print(p["name"], p["price"] / 100)   # price in cents
```

`NewWorldMobileAPI` handles auth (guest token, 30-min expiry), headers, and the
`POST /mobile/ecomm-products/MNW/{storeId}/search?q=...` call.

### 10.2 How to Find Nearby Stores and Compare Prices

```python
from NZMealOptimiser.pricing.optimiser_utils import geocode, find_nearby_stores, DISHES
from tools.newworld.newworld_setup import load_stores
from NZMealOptimiser.pricing.newworld_api import NewWorldMobileAPI

stores = load_stores(source="edge")   # DataFrame with store_id, lat, lon, etc.
user_lat, user_lon = geocode("Botany Town Centre, Auckland")
nearby = find_nearby_stores(user_lat, user_lon, stores, radius_km=5)

api = NewWorldMobileAPI()
dish_dict = DISHES["spaghetti bolognese"]
for _, store in nearby.iterrows():
    total = 0.0
    print(f"--- {store['name']} ---")
    for ing in dish_dict["ingredients"]:
        products = api.search_products(store["store_id"], ing["search_term"]) or []
        if products:
            price = NewWorldMobileAPI.extract_price(products[0])
            if price is not None:
                print(f"  {ing['search_term']:25s} ${price:.2f}")
                total += price
        else:
            print(f"  {ing:25s}  NOT FOUND")
    print(f"  {'TOTAL':25s} ${total:.2f}\n")
```

### 10.3 Edge API Two-Pass Pipeline (Production — default)

```python
from NZMealOptimiser.pricing.optimiser_utils import foodstuffs_querier_edge
from NZMealOptimiser.pricing.newworld_api import NewWorldEdgeAPI, find_nearby_stores

foodstuffs_querier_edge(
    api_class=NewWorldEdgeAPI,
    find_nearby_stores_fn=find_nearby_stores,
    company_id="NewWorld",
    company_name="New World",
    user_address="Botany Town Centre, Auckland",
    dish_name="spaghetti bolognese",
)
```

This is the full two-phase pipeline: geocode → find stores → Pass 1 (Algolia relevance
+ `category1` non-food filter) → Pass 2 (per-store pricing + `PRICE_ASC`) → build CSV
rows → Phase 2 (per-ingredient cheapest → totals + breakdown). The shared helper
`foodstuffs_querier_edge` in `src/NZMealOptimiser/pricing/optimiser_utils.py` implements the
complete loop; the CLI wrapper `newworld_optimiser_edge.py` just calls it with brand
params.

### 10.4 Unified API Module (`newworld_api.py`)

| Backend | Auth | Pipeline | Use Case |
|---------|------|----------|----------|
| **Edge API** (default) | Website JWT (`fs-user-token`) | Two-pass (relevance + per-store pricing) | Production — explicit relevance, pet food filtering, `PRICE_ASC` sort |
| **Mobile API** (fallback) | Guest token (30 min) | Single-pass (relevance only) | Fallback — simpler, no per-store price sort |

```python
from NZMealOptimiser.pricing.newworld_api import NewWorldAPI, NewWorldEdgeAPI, NewWorldMobileAPI
api = NewWorldAPI(backend="edge")           # or "mobile"
products, hits = api.search_ingredient(store_id, "beef mince")
edge = NewWorldEdgeAPI(); edge.authenticate()
pids = edge.pass1_relevance_search(store_id, "beef mince")
products = edge.pass2_per_store_pricing(store_id, "beef mince", pids)
```

### 10.5 Optimisers

Both optimisers are **two-phase**: Phase 1 queries the API and appends to
`full_results.csv`; Phase 2 reads today's rows and prints a comparison. Both are thin
wrappers that inject the brand API class and store-finder function (`find_nearby_stores`) into the shared helpers
`foodstuffs_querier_edge` / `foodstuffs_querier_mobile` in
`src/NZMealOptimiser/pricing/optimiser_utils.py`.

**Edge** (`tools/newworld/newworld_optimiser_edge.py` — **production, default**):
two-pass (relevance + per-store pricing, `PRICE_ASC`), `parse_foodstuffs_volume_size`
→ saves `data/newworld_latest_results.csv`.

**Mobile** (`tools/newworld/newworld_optimiser_mobile.py` — fallback): single-pass
(guest token), `_is_food_product()` filter on `categories[0]`,
`parse_foodstuffs_mobile_unit` → saves `data/newworld_mobile_latest_results.csv`.

Shared flags: `--requery true|false` (default true), `--distance N` (default 5 km).

### 10.6 Ingredient Search Strategy

The optimiser takes the **first (most relevant)** result per query. This avoids
irrelevant bulk items that might appear at lower prices (e.g., pet food for
"beef mince"). 21 dishes are hand-curated in `DISHES` (dict format with
quantity/unit/search_term) loaded from `data/dishes.json` via
`src/NZMealOptimiser/pricing/optimiser_utils.py`. LLM-backed dish generation available
via `src/NZMealOptimiser/llm/llm_utils.py`.

### 10.7 Architecture Diagrams

**Mobile API pipeline:**
```
newworld_stores.csv  (148/150 stores with store_id, name, lat, lon, ...)
   |
   +---> haversine filter (user address → lat/lon → nearby stores within 5 km)
   |
   v
FOR EACH nearby store:
  1. NewWorldMobileAPI.search_products(store_id, ingredient)
  2. price = product["price"] / 100
  3. Sum across all ingredients
   |
   v
Compare totals → cheapest store
```

**Edge API two-pass pipeline (production):**
```
newworld_stores.csv  (148 stores with store_id, name, lat, lon, ...)
   |
   +---> haversine filter (user address → lat/lon → nearby stores within 5 km)
   |
   v
FOR EACH nearby store:
  PASS 1: POST /v1/edge/search/products/query/index/products-index
    → Get productIDs with _highlightResult.matchedWords
    → Filter by category1 ∉ NON_FOOD_CATEGORIES
  PASS 2: POST /v1/edge/search/paginated/products with filters + PRICE_ASC
    → Get per-store singlePrice + promotions for matched products
   |
   v
Compare totals → cheapest store
```

Shared helpers (`foodstuffs_querier_edge`, `foodstuffs_querier_mobile`,
`build_edge_row`, `build_mobile_row`) live in `src/NZMealOptimiser/pricing/optimiser_utils.py`.
CLI entry points are thin wrappers: `tools/newworld/newworld_optimiser_edge.py`
and `tools/newworld/newworld_optimiser_mobile.py`.

---

## 11. Supported Dishes (21)

| Dish | Ingredients |
|------|------------|
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
| lamb chops | lamb chops, potato, mint sauce, mixed vegetables |
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

Dishes are defined in `DISHES` (dict format with quantity/unit/search_term) loaded
from `data/dishes.json` via `src/NZMealOptimiser/pricing/optimiser_utils.py` (via `get_ingredients()`; identical
ingredient lists for both Pak'nSave and New World).
`newworld_api.py` no longer re-exports — use the shared module directly.
Unknown dish names fall through — the dish name itself becomes the single search query.

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

| Argument | Default | Description |
|----------|---------|-------------|
| `address` | `"Botany Town Centre, Auckland"` | NZ address to geocode |
| `dish` | `"spaghetti bolognese"` | Dish name from the supported list |
| `--requery` | `true` | `false` to skip API and optimise from existing CSV |
| `--distance` | `5` | Store search radius in km |

The Edge optimiser is the **production default** (two-pass relevance + per-store
pricing, pet-food filtering, `PRICE_ASC` sort). Use the mobile optimiser only as a
fallback when the Edge API is unavailable. Raw rows are appended to `data/full_results.csv`;
per-run results saved to `data/newworld_latest_results.csv` (Edge) or
`data/newworld_mobile_latest_results.csv` (Mobile).

---

## 13. Appendix: Full Edge API Endpoint Reference
### 13.1 Base Configuration
```
Base URL: https://api-prod.newworld.co.nz/v1/edge
Auth:     JWT (mobile token OR website fs-user-token cookie)
Headers:  Authorization: Bearer {jwt}, access_token: {jwt}
          Origin: https://www.newworld.co.nz
          Referer: https://www.newworld.co.nz/
Cookies:  eCom_STORE_ID, STORE_ID_V2, Region (for per-store pricing)
```

### 13.2 Endpoints

| Method | Endpoint | Auth | Cookies | Purpose |
|--------|----------|------|---------|---------|
| GET | `/store` | JWT | Optional | List all 148 stores |
| GET | `/store/{id}/categories` | JWT | Required | Category tree for store |
| POST | `/search/products/query/index/products-index` | JWT | Required | **Relevance search (Algolia)** |
| POST | `/search/products/query/index/products-index-popularity-asc` | JWT | Required | Popularity browse (ASC) |
| POST | `/search/products/query/index/products-index-popularity-desc` | JWT | Required | Popularity browse (DESC) |
| POST | `/search/paginated/products` | JWT | Required | **Per-store pricing + sort** |

### 13.3 Algolia Index Payload (all index endpoints)
```json
{
  "algoliaQuery": {"query": "search term"},
  "page": 0,
  "hitsPerPage": 20,
  "storeId": "store-uuid"
}
```

### 13.4 Paginated Search Payload
```json
{
  "algoliaQuery": {
    "query": "search term",
    "filters": "productID:xxx OR productID:yyy"
  },
  "page": 0,
  "hitsPerPage": 50,
  "storeId": "store-uuid",
  "sortOrder": "PRICE_ASC"
}
```

### 13.5 Valid `sortOrder` Values
| Value | Description |
|-------|-------------|
| `PRICE_ASC` | Cheapest first at this store |
| `PRICE_DESC` | Most expensive first |

Invalid values (`RELEVANCE`, `RELEVANCY`, `DEFAULT`, `BEST_MATCH`) return HTTP 400.

### 13.6 Response Price Extraction
```python
# Regular price (cents → dollars)
price = product["singlePrice"]["price"] / 100

# Promotional price (dollars) — if available
promo = product["promotions"][0]["rewardValue"] / 100 if product["promotions"] else None

# Use promo price if present, else regular
final_price = promo if promo is not None else price

# Unit price (cents per unit)
unit_price_cents = product["singlePrice"]["comparativePrice"]["pricePerUnit"]
unit_uom = product["singlePrice"]["comparativePrice"]["unitQuantityUom"]
```

Note: `promotions` is **`null`** (not always `[]`) when a product has no promo.