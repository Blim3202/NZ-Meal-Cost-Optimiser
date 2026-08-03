# Pak'nSave / Foodstuffs North Island Mobile API Documentation

**API origin:** `api-prod.prod.fsniwaikato.kiwi` — despite the "FSNI" (Foodstuffs North
Island) domain name, this API covers **all Pak'nSave stores nationwide** including
both North Island (47 stores) and South Island (13 stores). It also works for
New World with `banner: "MNW"`.

[Confirmed working]: Dunedin, Invercargill,
Queenstown, Christchurch-area stores (Riccarton, Hornby, Moorhouse, Papanui,
Rangiora, Rolleston, Wainoni), Timaru, Blenheim, and Richmond all return valid
per-store pricing through the mobile API.

---

## 1. Overview

The Pak'nSave mobile API was first publicly documented by **[Arefu](https://github.com/Arefu)**
through reverse engineering the Foodstuffs Android app. Key sources:

- **[Foodstuffs PNS&NW Android App OpenAPI.yaml](https://github.com/Arefu/PaknSave/blob/main/_docs/Foodstuffs%20PNS%26NW%20Android%20App%20OpenAPI.yaml)** —
  Full OpenAPI 3.0.4 spec of the Foodstuffs North Island API, covering auth, stores,
  product search, cart, categories, and previous purchases.
- **[PaknSave.txt](https://gist.github.com/Arefu/b12d83a5dffb6573a1b1907044ad8de4)** —
  Early endpoint enumeration including the legacy `CommonApi` web endpoints and a
  PowerShell PoC for store listing and product exports.
- **[Arefu's GitHub profile](https://github.com/Arefu)** — Additional research on
  Foodstuffs API internals.

This document builds on Arefu's discovery to document every confirmed endpoint,
parameter, response shape, and edge case encountered during integration into this
project's meal cost optimizer. Where responses differ between the OpenAPI spec and
observed behaviour, both are noted.

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
User-Agent:    PAKnSAVEApp/4.32.0
Content-Type:  application/json
```

### 3.2 Authenticated Endpoints

After obtaining an `access_token`, all subsequent requests need both:

```
Authorization:  Bearer {token}
access_token:   {token}
User-Agent:     PAKnSAVEApp/4.32.0
Content-Type:   application/json
```

**Note:** The `access_token` header is duplicated intentionally — the API inspects
both `Authorization` and the custom `access_token` header. Omitting either can
cause 401 errors.

---

## 4. Mobile Authentication Flow

### 4.1 Guest Login

Pak'nSave uses a simple bearer-token auth model. No user account, no password,
no OAuth — just a `POST` with a banner identifier:

```
POST /mobile/user/login/guest
```

#### Request body

```json
{"banner": "PNS"}
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

The `PaknSaveMobileAPI` class auto-authenticates on first use (`_ensure_token`) and
caches the token in memory. Token expiry is 30 minutes; `_ensure_token()` is called on
every API call and is a no-op once a token is set. For long-running sessions, the
`refresh_token` endpoint (section 4.2) can be used.

### 4.2 Token Refresh

```
POST /mobile/v1/users/login/refreshtoken
```

#### Request headers

```
User-Agent: PAKnSAVEApp/4.32.0
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

The refresh token approach is not currently used by this project — a new guest
login is issued instead when the token expires (which is simpler and avoids
refresh-token lifecycle management).

---

## 5. Confirmed Working Endpoints

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
      "id": "65defcf2-bc15-490e-a84f-1f13b769cd22",
      "name": "PAK'nSAVE Albany",
      "banner": "PNS",
      "address": "33 Don McKinnon Drive, Albany, Auckland 0632",
      "clickAndCollect": true,
      "delivery": true,
      "latitude": -36.738224,
      "longitude": 174.712257,
      "openingHours": [ ... ],
      "phone": "09-415 8225",
      "localPhone": "09-415 8225",
      "linkDetails": { ... },
      "physicalStoreCode": "PN01",
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
| `name` | `string` | Full store name, e.g. `"PAK'nSAVE Albany"` |
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

60 stores are currently returned for `banner="PNS"`. Each store has a UUID-style
`id` (e.g., `65defcf2-bc15-490e-a84f-1f13b769cd22`).

#### Usage in this project

Two API modules are available:
- **Unified** `scripts/foodstuffs/Foodstuffs_api.py` — brand-agnostic (Pak'nSave + New World).
- **Pak'nSave-specific** `scripts/paknsave/paknsave_api.py` — `PaknSaveAPI(backend="edge"|"mobile")`.

See **section 10** for the full production module/optimizer usage.

### 5.2 `POST /mobile/ecomm-products/{banner}/{storeId}/search?q={query}`

The mobile product search endpoint. Returns relevant products for a given query at a
specific store, **with per-store pricing**.

**HTTP 200** — requires auth headers.

#### Path parameters

| Parameter | Type | Example |
|-----------|------|---------|
| `banner` | `string` | `"PNS"` |
| `storeId` | `string` (UUID) | `"65defcf2-bc15-490e-a84f-1f13b769cd22"` |

#### Query parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | `string` | (required) | Search query, e.g. `"beef mince"` |
| `hitsPerPage` | `int` | `100` | Max products per page. **Honored** — confirmed: `5`→5 products, `20`→20 products returned (see Pagination). |

The `sortOrder`, `searchingTobacco`, and `disableAdsOverride` params are *not used* by
this project (the optimizer always relies on the default relevance ordering and only
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
  "totalHits": 25,
  "hitsPerPage": 20,
  "numberOfPages": 2,
  "page": 1,
  "products": [
    {
      "productId": "5101189-KGM-000",
      "brand": "Pak'nSave",
      "name": "NZ Premium Beef Mince",
      "units": "kg",
      "categories": ["Beef", "Beef Mince & Stir Fry"],
      "price": 2699,
      "unitPrice": "$26.99/1kg",
      "productImageUrls": {
        "100": "https://...",
        "200": "https://...",
        "400": "https://...",
        "500": "https://..."
      },
      "availableInStore": true,
      "availableInOnline": true,
      "tobaccoFlag": false,
      "liquorFlag": false,
      "saleType": "WEIGHT",
      "algoliaAnalytics": {
        "searchQueryID": "abc123",
        "searchPosition": 1
      },
      "boughtBefore": false,
      "variableWeight": {
        "averageWeight": 0,
        "minOrderQuantity": 300,
        "stepSize": 100,
        "stepUnitOfMeasure": "g"
      }
    },
    ...
  ],
  "filters": {
    "Deals": {},
    "Dietary & lifestyle": {},
    "Categories": {
      "Beef Mince & Stir Fry": 7,
      "Beef Patties & Meatballs": 13,
      ...
    },
    "Brands": {
      "Pak'nSave": 5,
      ...
    }
  }
}
```

> **Confirmed live:** the response is a **wrapped dict** (not a bare array). The container
> keys are `tobaccoFiltered`, `totalHits`, `hitsPerPage`, `numberOfPages`, `page`,
> `products`, and `filters`. The production code defensively accepts either shape, but the
> wrapped form is what the API actually returns.

#### Product fields

| Field | Type | Notes |
|-------|------|-------|
| `productId` | `string` | Unique product identifier (SKU, e.g. `"5101189-KGM-000"`) |
| `name` | `string` | Product display name |
| `brand` | `string` | Brand name (e.g. `"Pams"`, `"Value"`) |
| `price` | `integer` | **Price in cents** — divide by 100 for dollars |
| `units` | `string` | Pack count + measure combined, e.g. `"500g"`, `"2l"`, `"12pk"`, `"3 x 80g"`, `"8 x 12g"`, bare `"ea"` — see section on parsing |
| `unitPrice` | `string` | Formatted unit price string, e.g. `"$26.99/1kg"`, `"$0.65/10g"`, `"$0.34/100g"`. **May be `null`** for bare-`"ea"` items |
| `categories` | `array[2]` | Exactly 2 elements: `[0]` = category1 (sub_department), `[1]` = category2 — **not** a hierarchical path |
| `saleType` | `string` | `"WEIGHT"` (scaled, sold by weight) or `"UNITS"` (fixed pack) |
| `availableInOnline` | `bool` | Can be ordered online |
| `availableInStore` | `bool` | In stock at this store |
| `tobaccoFlag` | `bool` | Is a tobacco product |
| `liquorFlag` | `bool` | Is an alcohol product |
| `variableWeight` | `object` | Present for `saleType: "WEIGHT"` items (min order qty, step size) |

#### Price handling

**Critical: prices are in cents.** Always divide `price` by 100:

```python
price_dollars = product["price"] / 100
```

#### Per-store pricing

Each `{storeId}` returns independent prices for the same product. For example,
searching "standard milk" at Botany vs Ormiston may return different `price`
values for the same `productId`. This is the foundation of the meal cost optimizer.

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

The optimizer splits the mobile product into
`(quantity, measurement_unit, per_unit_quantity, per_unit_price)` in one call via
`parse_paknsave_mobile_unit(units, unitPrice, price_cents)`:

- `units` packs count + measure together, e.g. `"3 x 80g"` → `quantity=3`,
  `measurement_unit="x 80g"`; `"500g"` → `(500, "g")`; `"ea"` → `(1, "ea")`.
- `unitPrice` splits on `/`: `"$26.99/1kg"` → `per_unit_quantity="1kg"`,
  `per_unit_price=26.99` (dollar sign stripped, cents→dollars).
- **Bare-`"ea"` fallback**: when `units="ea"` and `unitPrice` is `null`, set
  `per_unit_quantity="ea"` and mirror the item's own `price` into
  `per_unit_price` — avoids blank per-unit columns.

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

The mobile endpoint's sort parameter is not used by this project. The optimizer relies
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

```json
{
  "tobaccoFiltered": false,
  "totalHits": 50,
  "hitsPerPage": 20,
  "numberOfPages": 3,
  "page": 1,
  "products": [
    {
      "productId": "...",
      "brand": "Pams",
      "name": "NZ Beef Mince",
      "units": "kg",
      "price": 1499,
      "unitPrice": "$14.99/kg",
      ...
      "saleType": "special",
      "algoliaAnalytics": { ... }
    }
  ],
  "filters": {
    "Deals": { "Super Specials": 20, "Weekly Specials": 30 },
    "Dietary & lifestyle": { ... },
    "Categories": { ... },
    "Brands": { ... }
  }
}
```

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

## 6. Pak'nSave Edge API (Website Backend)

The Pak'nSave website at `www.paknsave.co.nz` exposes an Edge API at
`api-prod.paknsave.co.nz`. This API uses Apigee gateway with JWT verification —
identical architecture to New World's Edge API.

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
User-Agent:    Mozilla/5.0... (browser) OR PAKnSAVEApp/4.32.0 (mobile)
Origin:        https://www.paknsave.co.nz
Referer:       https://www.paknsave.co.nz/
```

**Store context cookies (REQUIRED for per-store pricing):**
```
eCom_STORE_ID: {store_id}
STORE_ID_V2:   {store_id}|False
Region:        NI  (or SI for South Island)
```

---

### 6.2 Edge Store Listing

**Endpoint**: `GET https://api-prod.paknsave.co.nz/v1/edge/store`

**Status**: [OK] **Works (HTTP 200)** with valid JWT.

**Returns**: 57 stores with full details (id, name, address, coordinates, opening hours, services).

**Note**: Returns 57 stores vs 60 from mobile API. The 3 missing stores [Wairau Road, Gisborne City, Levin] are due to private, in-store only pricing.

---

### 6.3 Product Search — TWO-PASS ARCHITECTURE

**TL;DR**: The Edge API does NOT have a single endpoint that provides both relevance matching AND per-store pricing. We discovered a **two-pass pipeline** that combines the best of both endpoints — identical to the New World Edge API.

#### The Problem

| Endpoint | Relevance Matching | Per-Store Pricing |
|----------|-------------------|-------------------|
| `products-index` (Algolia) | [OK] Has `_highlightResult` with `matchedWords` | [NO] Only `averagePrice` (cross-store) |
| `products-index-popularity-asc/desc` | [OK] Has `matchedWords` (popularity sorted) | [NO] Only `averagePrice` |
| `/search/paginated/products` | [NO] No `RELEVANCE` sort (400 enum mismatch) | [OK] Full per-store pricing |

#### The Solution: Two-Pass Pipeline

**PASS 1 — Relevance Matching (Algolia Index)**
```
POST https://api-prod.paknsave.co.nz/v1/edge/search/products/query/index/products-index
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
      "productID": "5104350-KGM-000",
      "DisplayName": "NZ Beef Mince",
      "brand": "None",
      "averagePrice": 18.99,
      "category1": ["Beef", "Mince, Sausages & Meatballs"],
      "category2": ["Beef Mince & Stir Fry", "Mince"],
      "_highlightResult": {
        "DisplayName": {"value": "NZ <em>Beef</em> <em>Mince</em>", "matchedWords": ["beef", "mince"]},
        "category2AndBrand": {"value": "Beef <em>Mince</em> & Stir Fry", "matchedWords": ["beef", "mince"]}
      }
    }
  ]
}
```

**Key**: Extract `productID` from hits where `_highlightResult` has non-empty `matchedWords`.

**PASS 2 — Per-Store Pricing (Paginated Endpoint with Filters)**
```
POST https://api-prod.paknsave.co.nz/v1/edge/search/paginated/products
```

Payload (using Algolia filter syntax):
```json
{
  "algoliaQuery": {
    "query": "beef mince",
    "filters": "productID:5104350-KGM-000 OR productID:5101189-KGM-000 OR productID:5040757-EA-000"
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
      "productId": "5104350-KGM-000",
      "name": "NZ Beef Mince",
      "displayName": "kg",
      "brand": "None",
      "singlePrice": {"price": 1899, "comparativePrice": {"pricePerUnit": 1899, "unitQuantity": 1, "unitQuantityUom": "kg", "measureDescription": "1kg"}},
      "promotions": null,
      "availability": ["IN_STORE", "ONLINE"]
    }
  ]
}
```

**Price extraction:**
- Regular price (cents): `singlePrice.price`
- Promotional price (cents): `promotions[].rewardValue` where `bestPromotion: true`
- Unit price: `singlePrice.comparativePrice.pricePerUnit` (cents per unit, against the
  `measureDescription` base — e.g. `"1kg"`, `"100g"`)
- `promotions` is **`null`** when a product has no promo (not always `[]`)

---

### 6.4 Algolia Indices — What Exists vs What Doesn't

We tested multiple index names based on New World patterns. Only THREE return HTTP 200:

| Index Name | Status | Sort Order | `_highlightResult.matchedWords` | Use Case |
|------------|--------|------------|--------------------------------|----------|
| `products-index` | [OK] 200 | **Relevance (Algolia default)** | [OK] **YES** — has `matchedWords` | **PASS 1: Relevance matching** |
| `products-index-popularity-asc` | [OK] 200 | Popularity ascending | [OK] Has matches (popularity sorted) | Browsing (least popular first) |
| `products-index-popularity-desc` | [OK] 200 | Popularity descending | [OK] Has matches (popularity sorted) | Browsing (most popular first) |
| `products-index-price-asc` | [NO] 404 | — | — | Does not exist |
| `products-index-price-desc` | [NO] 404 | — | — | Does not exist |
| `products-index-relevance` | [NO] 404 | — | — | Does not exist |
| `products-index-name-asc` | [NO] 404 | — | — | Does not exist |
| `products-index-name-desc` | [NO] 404 | — | — | Does not exist |
| `products-index-newest` | [NO] 404 | — | — | Does not exist |
| `products-index-bestselling` | [NO] 404 | — | — | Does not exist |
| `products-index-trending` | [NO] 404 | — | — | Does not exist |

**Key Discovery**: All three working Pak'nSave indices have `_highlightResult.matchedWords` populated (same as New World). The default `products-index` is relevance-sorted and has the best relevance matching.

**Recommended index**: `products-index` (default, relevance-sorted)

---

### 6.5 Paginated Search Endpoint — Full Capabilities

**Endpoint**: `POST https://api-prod.paknsave.co.nz/v1/edge/search/paginated/products`

**Authentication**: Website JWT (fs-user-token cookie) OR mobile API token

**Required Cookies** (per-store context):
```python
cookies = {
    "eCom_STORE_ID": store_id,
    "STORE_ID_V2": f"{store_id}|False",
    "Region": "NI"  # or "SI" for South Island
}
```

**Valid `sortOrder` values** (tested, validated enum):
- `PRICE_ASC` — Cheapest first at this store [OK]
- `PRICE_DESC` — Most expensive first [OK]

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
| `productId` | string | SKU, matches `productID` from Algolia index (e.g. `"5101189-KGM-000"`) |
| `name` | string | Product name |
| `displayName` | string | Size/variant (e.g. `"2l"`, `"340g"`, `"120g"`) — used for quantity/measurement parsing |
| `brand` | string | Brand name |
| `singlePrice.price` | int | Regular price in cents |
| `singlePrice.comparativePrice` | object | Unit pricing info: `pricePerUnit` (cents), `unitQuantityUom`, `measureDescription` (e.g. `"100g"`, `"1L"`) |
| `promotions` | array **or `null`** | Promo objects with `rewardValue` (cents), `threshold`, `bestPromotion`, `comparativePrice`. **Often `null`** when no promo |
| `availability` | array | `["IN_STORE", "ONLINE"]` etc. |
| `categoryTrees` | array | Category info for the product |
| `algoliaAnalytics.searchPosition` | int | Position in sorted results |

**Price extraction:**
- Regular price (cents): `singlePrice.price`
- Promotional price (cents): `promotions[].rewardValue` where `bestPromotion: true`
- Unit price (cents per unit): `singlePrice.comparativePrice.pricePerUnit` — note the
  base quantity can be 100g/10g/1L (see `measureDescription`), so convert with that.

---

### 6.6 Categories Endpoint

**Endpoint**: `GET https://api-prod.paknsave.co.nz/v1/edge/store/{store_id}/categories`

**Status**: [OK] **Works (HTTP 200)** with valid JWT + store cookies.

**Returns**: Category tree for store navigation.

---

### 6.7 Comparison: Mobile API vs Edge API (Two-Pass)

| Feature | Mobile API | Edge API (Two-Pass) |
|---------|------------|---------------------|
| Auth | Guest login POST | Website session OR mobile token |
| Store listing | [OK] 60 stores | [OK] 57 stores |
| Product search | [OK] Single call | [OK] Two-pass (relevance + pricing) |
| Relevance matching | Implicit (relevance ordering) | [OK] Explicit `_highlightResult.matchedWords` |
| Per-store pricing | [OK] Native (storeId in URL) | [OK] Via cookies + Algolia filters |
| Price format | Cents in response | Cents in `singlePrice.price` |
| Promotions | Included | Included in `promotions[]` |
| Sort | Relevance (default) | `PRICE_ASC`, `PRICE_DESC` only |
| Pagination | `hitsPerPage` query param (default 100) | Algolia page/hitsPerPage |
| Token source | Mobile API only | Mobile API OR website |
| Dependency | Internal mobile API | Public website API (more stable) |
| Pet food filtering | [OK] Via `categories[0]` (category1) | [OK] Via `category1` in Pass 1 |

---

### 6.8 Two-Pass Pipeline Summary

```
PASS 1  products-index (relevance)  → filter hits by matchedWords AND category1 ∉ NON_FOOD
        → collect productIDs
PASS 2  paginated/products (filters="productID:a OR productID:b ...", PRICE_ASC)
        → per-store priced products
```

Full flow (including parsing into CSV rows) is in **section 8 (Data Query & Parsing
Pipeline)**. Reference implementation: `scripts/paknsave/paknsave_api.py`
(`PaknSaveEdgeAPI.pass1_relevance_search_hits` / `pass2_per_store_pricing`).

---

### 6.9 Why This Matters for the Meal Cost Optimizer

**Without relevance matching**: Searching "beef mince" could return pet food, pies, or unrelated products first.

**With two-pass pipeline**:
1. Algolia finds ACTUALLY RELEVANT products (beef mince, not cat food)
2. Paginated endpoint gets EXACT per-store prices for those relevant products
3. Sort by `PRICE_ASC` to find cheapest at that store

**Advantage over Mobile API**: Explicit relevance matching via `_highlightResult.matchedWords`.
The mobile API also supports food filtering via `categories[0]` and relevance ordering, but
the Edge API exposes *why* a match occurred (matched words), which is more robust for
ambiguous ingredient queries like "beef mince".

---

### 6.10 Exploration Timeline & Breakthroughs

| Phase | What We Tried | Result | Breakthrough |
|-------|---------------|--------|--------------|
| 1 | Website JWT via `get-current-user` | [OK] 200 | JWT obtained from `fs-user-token` cookie |
| 2 | Store listing `GET /v1/edge/store` | [OK] 200 | 57 stores with coords/IDs |
| 3 | Algolia index `products-index` | [OK] 200 | **Relevance matching via `_highlightResult`** |
| 4 | Algolia popularity indices | [OK] 200 | Also have `matchedWords` (unlike New World) |
| 5 | Paginated `/search/paginated/products` | [OK] 200 | Per-store pricing works |
| 6 | Algolia `filters` parameter | [OK] Works | **Bridge between relevance + pricing** |
| 7 | Two-pass pipeline | [OK] End-to-end | **Production-ready solution** |
| 8 | Category-based pet food filtering | [OK] Works | `category1` excludes Dog/Cat/Pet |

---

### 6.11 Conclusion

**The Edge API CAN fully replace the mobile API** for the meal cost optimizer:

1. [OK] Store listing works (57 stores)
2. [OK] Product search works via two-pass pipeline
3. [OK] Explicit relevance matching via `_highlightResult`
4. [OK] Per-store pricing via cookies + Algolia filters
5. [OK] Promotional pricing included
6. [OK] Works with website JWT (no mobile API dependency)
7. [OK] More future-proof (public website API)
8. [OK] Pet food filtering via `category1` in Pass 1

**Advantages of Edge API over Mobile API:**
- No dependency on Foodstuffs mobile API endpoint
- Explicit relevance matching (matched words, not just ordering) — mobile relies on ordering
- Algolia-powered search with proper price sorting
- Works with standard browser JWT (same IdP: `online-customer`)
- Categories endpoint available for navigation
- Pet food filtering via `category1` field

**Implementation Reference**: `scripts/paknsave/Exploration/demo_two_pass_pipeline.py`
**Full Exploration Details**: `scripts/paknsave/Exploration/Exploration.md`

---

## 7. Per-Store Pricing

### 7.1 How It Works

The Pak'nSave API provides **true per-store pricing**. Each store has its own price
list for every product identified by its unique `productId` (SKU). When you search
"beef mince" at store A vs store B, the prices returned are that store's current prices.

Per-store context is carried differently by each backend:
- **Mobile API** — store context is in the URL path: `POST /mobile/ecomm-products/PNS/{storeId}/search?q=...`. No extra cookies needed.
- **Edge API** — store context is in cookies (`eCom_STORE_ID`, `STORE_ID_V2`, `Region`) plus an Algolia `filters` for targeted pricing.

This is in contrast to Woolworths, which needs `cw-lrkswrdjp` cookie injection per store.

### 7.2 Observed Price Variation

Price differences between nearby stores are common. For example, a search for
"standard milk" across Botany, Ormiston, and Highland Park Pak'nSave stores showed:

| Store | Milk 3L Price |
|-------|--------------|
| Botany | $7.25 |
| Ormiston | $6.78 |
| Highland Park | $7.25 |

Differences of $0.10-$0.50 per item between nearby stores are typical. Distant
stores (e.g., Auckland vs Christchurch) can show larger differences.

### 7.3 Why This Matters

The meal cost optimizer finds the cheapest total for an entire recipe by searching
each ingredient at each nearby store and comparing totals. Without per-store pricing,
this comparison would be meaningless.

---

## 8. Data Query & Parsing Pipeline

This section shows how the production code queries the two backends and parses the
responses into CSV rows. Both backends follow the same skeleton:

```
geocode(address) → find_nearby_stores(lat, lon, 5km)
→ for each store, for each ingredient:  search_ingredient (edge) / search_products (mobile)
→ build_row(product[, pass1_hit]) → append_rows() → data/full_results.csv
→ Phase 2: optimise() reads today's rows → per-store totals + per-ingredient breakdown
```

### 8.1 Edge API (two-pass) — `PaknSaveEdgeAPI`

Two separate calls per ingredient per store, bridged by Algolia `filters`:

```
Pass 1  POST /v1/edge/search/products/query/index/products-index
        payload: {"algoliaQuery":{"query":ingredient}, "page":0, "hitsPerPage":20, "storeId":id}
        → hits with _highlightResult.matchedWords; keep productID where matched
          AND category1 not in NON_FOOD_CATEGORIES  (pet/baby/household excluded)

Pass 2  POST /v1/edge/search/paginated/products
        payload: {"algoliaQuery":{"query":ingredient,"filters":"productID:a OR productID:b ..."},
                  "page":0, "hitsPerPage":50, "storeId":id, "sortOrder":"PRICE_ASC"}
        → products with per-store singlePrice + promotions
```

Then `build_row` calls `parse_paknsave_volume_size(displayName, singlePrice, promotions)`
to get `(quantity, measurement_unit, per_unit_quantity, per_unit_price)` from the
`comparativePrice.measureDescription` (e.g. `"1kg"`, `"100g"`). Department/sub_department
come from the Pass 1 hit's `category0` / `category1`.

### 8.2 Mobile API (single-pass) — `PaknSaveMobileAPI`

One call per ingredient per store:

```
POST /mobile/ecomm-products/PNS/{storeId}/search?q={ingredient}&hitsPerPage=20
→ bare-or-wrapped products; _is_food_product() keeps rows where categories[0]
  (category1) not in NON_FOOD_CATEGORIES
```

Then `build_row` calls `parse_paknsave_mobile_unit(units, unitPrice, price_cents)` to get
`(quantity, measurement_unit, per_unit_quantity, per_unit_price)`. `units` packs
count + measure (`"3 x 80g"`, `"500g"`, `"ea"`); `unitPrice` splits on `/`
(`"$26.99/1kg"` → qty `1kg`, price `26.99`). Bare `"ea"` with no `unitPrice` falls back
to `per_unit_quantity="ea"` and mirrors the item `price`.

### 8.3 Shared CSV schema (`data/full_results.csv`)

Both backends write to the same `full_results.csv` with 17 columns. `pk_hash`
(SHA-256 of `store_id|sku|date_created`) deduplicates appended rows.

| Column | Edge source | Mobile source |
|--------|-------------|---------------|
| `quantity` / `measurement_unit` | `displayName` via `parse_paknsave_volume_size` | `units` via `parse_paknsave_mobile_unit` |
| `per_unit_quantity` / `per_unit_price` | `comparativePrice.measureDescription` / `pricePerUnit` | `unitPrice` split (or price for bare-`ea`) |
| `department` | Pass 1 `category0` | *(empty — mobile has no category0)* |
| `sub_department` | Pass 1 `category1` | `categories[0]` |
| `price` | promo `rewardValue` else `singlePrice.price` (cents) | `price` (cents) |

---

## 9. Store Data Sources

The canonical store pipeline is the **unified** `scripts/foodstuffs/Foodstuffs_setup.py`
(a cross-brand module with `brand="paknsave"`). The legacy Pak'nSave-only
`scripts/paknsave/paknsave_setup.py` mirrors it and is still functional. Both support
three sources via a `source` parameter (validated per brand — `store_finder` raises
`ValueError` for New World).

```python
from scripts.foodstuffs.Foodstuffs_setup import fetch_stores, clean_stores, run_full_setup
run_full_setup(brand="paknsave")                     # default: Edge API, 57 stores
run_full_setup(brand="paknsave", source="store_finder")  # 60 stores
run_full_setup(brand="paknsave", source="mobile")        # legacy, 60 stores
df = fetch_stores(brand="paknsave", source="edge")       # 57 stores
df = clean_stores(df, cleaned=True)                      # drop NaN coords (no-op for Pak'nSave)
```

| Source | Stores | Method | Auth | Notes |
|--------|--------|--------|------|-------|
| **Edge API** (default) | 57 | `GET /v1/edge/store` | `fs-user-token` from `get-current-user` | 3 stores missing (Wairau Road, Gisborne City, Levin) |
| **Mobile API** (legacy) | 60 | guest login + `GET /mobile/store/physical` | guest token + `PAKnSAVEApp/4.32.0` UA | Complete set |
| **Store-finder page** | 60 | `GET /store-finder` → `__NEXT_DATA__` | none (cloudscraper) | `contentstackStores` GUIDs + `regionStoreGroupings` coords |

**No geocoding required** — all sources provide lat/lon directly.

Outputs: `data/paknsave_stores.csv` and `data/paknsave_stores.json` (57 / 60 rows each).

CLI: `python -m scripts.paknsave.paknsave_setup [edge|mobile|store_finder]`.

---

## 10. Production Architecture & Optimizers

### 10.1 Unified API Module (`paknsave_api.py`)

| Backend | Auth | Pipeline | Use Case |
|---------|------|----------|----------|
| **Edge API** (default) | Website JWT (`fs-user-token`) | Two-pass (relevance + per-store pricing) | Production — explicit relevance, pet food filtering, PRICE_ASC sort |
| **Mobile API** (fallback) | Guest token (30 min) | Single-pass (relevance only) | Fallback — simpler, no per-store price sort |

```python
from scripts.paknsave.paknsave_api import PaknSaveAPI, PaknSaveEdgeAPI, PaknSaveMobileAPI
api = PaknSaveAPI(backend="edge")             # or "mobile"
products, hits = api.search_ingredient(store_id, "beef mince")
edge = PaknSaveEdgeAPI(); edge.authenticate()
pids = edge.pass1_relevance_search(store_id, "beef mince")
products = edge.pass2_per_store_pricing(store_id, "beef mince", pids)
```

### 10.2 Optimizers

Both optimizers are **two-phase**: Phase 1 queries the API and appends to
`full_results.csv`; Phase 2 reads today's rows and prints a comparison.

**Edge** (`scripts/paknsave/paknsave_optimizer_edge.py`):
1. Geocode address → lat/lon
2. Load stores → filter by haversine distance (`--distance N`, default 5km)
3. Authenticate with Edge API (website JWT)
4. Per nearby store, per ingredient: two-pass search (Pass 1 relevance + category1
   non-food filter; Pass 2 per-store pricing + `PRICE_ASC`)
5. `build_row` → `parse_paknsave_volume_size` → append to CSV
6. Phase 2: cheapest per ingredient per store → totals + breakdown
   → saves `data/paknsave_latest_results.csv`

**Mobile** (`scripts/paknsave/paknsave_optimizer_mobile.py`):
Same skeleton, single-pass (guest token), `_is_food_product()` filter on
`categories[0]`, `parse_paknsave_mobile_unit` for parsing
→ saves `data/paknsave_mobile_latest_results.csv`.

Shared flags for both: `--requery true|false` (default true) and `--distance N`.
Both use `data/full_results.csv` as the append-only, deduped result store.

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

Dishes are defined in `DISH_INGREDIENTS` in `scripts/paknsave/paknsave_api.py`.
Unknown dish names fall through — the dish name itself becomes the single search query.

---

## 12. CLI Usage

**Edge API Optimizer (Production — two-pass):**
```powershell
python scripts/paknsave/paknsave_optimizer_edge.py "Botany Town Centre, Auckland" "spaghetti bolognese"
```

**Mobile API Optimizer (Fallback — single-pass):**
```powershell
python scripts/paknsave/paknsave_optimizer_mobile.py "Botany Town Centre, Auckland" "spaghetti bolognese"
```

| Argument | Default | Description |
|----------|---------|-------------|
| `address` | `"Botany Town Centre, Auckland"` | NZ address to geocode |
| `dish` | `"spaghetti bolognese"` | Dish name from the supported list |
| `--requery` | `true` | `false` to skip API and optimise from existing CSV |
| `--distance` | `5` | Store search radius in km |

Output: per-store itemised prices, total cost comparison, and the cheapest store.
Raw rows are appended to `data/full_results.csv`; per-run results saved to
`data/paknsave_latest_results.csv` (Edge) or `data/paknsave_mobile_latest_results.csv` (Mobile).

---

## 13. Store Setup

See **section 9 (Store Data Sources)** — the canonical pipeline
(`foodstuffs/Foodstuffs_setup.py` with `brand="paknsave"`, or the legacy
`paknsave_setup.py`) produces `data/paknsave_stores.csv` / `.json`.

**Legacy scripts:** `scripts/paknsave/fetch_stores.py` is **deprecated** — use
`paknsave_setup.py` `fetch_stores()` instead.

---

**Credits:** Authored by [Arefu](https://github.com/Arefu) through reverse engineering the Foodstuffs Android app. Full OpenAPI spec in their [PaknSave repo](https://github.com/Arefu/PaknSave).