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

The `PaknSaveAPI` class in this project automatically refreshes expired tokens:

```python
class PaknSaveAPI:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self._token = None

    def _ensure_token(self):
        if self._token:
            return
        r = self.scraper.post(
            f"{BASE}/mobile/user/login/guest",
            json={"banner": "PNS"},
            headers={"User-Agent": "PAKnSAVEApp/4.32.0", "Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._auth = {
            "Authorization": f"Bearer {self._token}",
            "access_token": self._token,
            "User-Agent": "PAKnSAVEApp/4.32.0",
            "Content-Type": "application/json",
        }
```

The token expiry is 30 minutes. `_ensure_token()` is called on every API call —
if the token is already set, the call is a no-op. For long-running sessions, the
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

The unified `Foodstuffs_api.py` module provides brand-agnostic access for both Pak'nSave and New World. For Pak'nSave specifically, the dedicated `paknsave_api.py` module is also available.

Using the unified Foodstuffs API (recommended):

```python
from scripts.foodstuffs.Foodstuffs_api import FoodstuffsEdgeAPI, FoodstuffsMobileAPI

# Edge API (two-pass relevance + per-store pricing)
api = FoodstuffsEdgeAPI("paknsave")
stores = api.get_stores()  # returns {id: store_dict}
products = api.search_products(store_id, "beef mince")  # uses two-pass pipeline
```

Using the Pak'nSave-specific API:

```python
from scripts.paknsave.paknsave_api import PaknSaveAPI

api = PaknSaveAPI(backend="edge")  # or "mobile" for fallback
stores = api.get_stores()  # returns {id: store_dict}
```

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
| `sortOrder` | `string` | (relevance) | Sort by relevance or price |
| `searchingTobacco` | `bool` | `false` | If the search is for tobacco products |
| `disableAdsOverride` | `bool` | `false` | Disable ad insertion in results |

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

#### Product fields

| Field | Type | Notes |
|-------|------|-------|
| `productId` | `string` (UUID) | Unique product identifier across all stores |
| `name` | `string` | Product display name |
| `brand` | `string` | Brand name (e.g. `"Pams"`, `"Value"`) |
| `price` | `integer` | **Price in cents** — divide by 100 for dollars |
| `units` | `string` | Unit of sale: `"kg"`, `"L"`, `"400g"`, `"12pk"`, `"each"` |
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
searching "standard milk" at Botany vs Ormiston may return different `price`
values for the same `productId`. This is the foundation of the meal cost optimizer.

#### Pagination

| Field | Description |
|-------|-------------|
| `page` | Current page (1-indexed) |
| `hitsPerPage` | Items per page (default 20) |
| `numberOfPages` | Total page count |
| `totalHits` | Total matching products |

All results are returned in a single page for typical ingredient searches
(which usually return 1-20 results).

#### Specifying sort order

Add `sortOrder` to the query string:

```
POST .../search?q=beef+mince&sortOrder=PriceAsc
```

`sortOrder` values are not fully documented but known to accept `"PriceAsc"`.

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

Response includes `_highlightResult` with `matchedWords`:
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
      "singlePrice": {"price": 1899, "comparativePrice": {"pricePerUnit": 1899, "unitQuantityUom": "kg"}},
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

**Key Discovery**: Unlike New World, **all three working Pak'nSave indices have `_highlightResult.matchedWords` populated**. The default `products-index` is relevance-sorted and has the best relevance matching.

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
| `productId` | string | Matches `productID` from Algolia index |
| `name` | string | Product name |
| `displayName` | string | Size/variant (e.g., "2l", "340g") |
| `brand` | string | Brand name |
| `singlePrice.price` | int | Regular price in cents |
| `singlePrice.comparativePrice` | object | Unit pricing info |
| `promotions[]` | array | Promo objects with `rewardValue` (cents) |
| `availability` | array | `["IN_STORE", "ONLINE"]` etc. |
| `algoliaAnalytics.searchPosition` | int | Position in sorted results |

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
| Relevance matching | Implicit (first result) | [OK] Explicit `_highlightResult.matchedWords` |
| Per-store pricing | [OK] Native (storeId in URL) | [OK] Via cookies + Algolia filters |
| Price format | Cents in response | Cents in `singlePrice.price` |
| Promotions | Included | Included in `promotions[]` |
| Sort | Relevance (default), PriceAsc | `PRICE_ASC`, `PRICE_DESC` only |
| Pagination | Offset/limit | Algolia page/hitsPerPage |
| Token source | Mobile API only | Mobile API OR website |
| Dependency | Internal mobile API | Public website API (more stable) |
| Pet food filtering | Not available | [OK] Via `category1` in Pass 1 |

---

### 6.8 Two-Pass Pipeline Implementation

```python
def two_pass_search(token, query, store_id, max_relevance=20, sort_order="PRICE_ASC"):
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
        "sortOrder": sort_order
    }
    r2 = requests.post(url2, headers=headers, json=payload2, cookies=cookies)
    return r2.json().get("products", [])
```

---

### 6.9 Why This Matters for the Meal Cost Optimizer

**Without relevance matching**: Searching "beef mince" could return pet food, pies, or unrelated products first.

**With two-pass pipeline**:
1. Algolia finds ACTUALLY RELEVANT products (beef mince, not cat food)
2. Paginated endpoint gets EXACT per-store prices for those relevant products
3. Sort by `PRICE_ASC` to find cheapest at that store

**Advantage over Mobile API**: Explicit relevance matching via `_highlightResult.matchedWords` — the mobile API returns the first result but provides no visibility into WHY it matched. This is critical for avoiding pet food matching "beef mince".

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
- Explicit relevance matching (not just "first result")
- Algolia-powered search with proper price sorting
- Works with standard browser JWT (same IdP: `online-customer`)
- Categories endpoint available for navigation
- Pet food filtering via `category1` field

**Implementation Reference**: `scripts/paknsave/Exploration/demo_two_pass_pipeline.py`
**Full Exploration Details**: `scripts/paknsave/Exploration/Exploration.md`

---

## 7. Per-Store Pricing

### 8.1 How It Works

The Pak'nSave mobile API provides **true per-store pricing**. Each store has its own
price list for every product identified by its unique `productId`. When you search
for "beef mince" at store A vs store B, the prices returned are that store's current
prices.

This is in contrast to the Woolworths API, which requires cookie injection for
per-store pricing — Pak'nSave encodes the store context directly in the URL path:

```
POST /mobile/ecomm-products/PNS/{storeId}/search?q=beef+mince
```

No special headers, cookies, or session setup beyond the bearer token is needed.

### 8.2 Observed Price Variation

Price differences between nearby stores are common. For example, a search for
"standard milk" across Botany, Ormiston, and Highland Park Pak'nSave stores showed:

| Store | Milk 3L Price |
|-------|--------------|
| Botany | $7.25 |
| Ormiston | $6.78 |
| Highland Park | $7.25 |

Differences of $0.10-$0.50 per item between nearby stores are typical. Distant
stores (e.g., Auckland vs Christchurch) can show larger differences.

### 8.3 Why This Matters

The meal cost optimizer finds the cheapest total for an entire recipe by searching
each ingredient at each nearby store and comparing totals. Without per-store pricing,
this comparison would be meaningless.

---

## 8. Store Data Sources

### 8.1 Unified Store Setup Pipeline (`paknsave_setup.py`)

The **canonical store pipeline** is `scripts/paknsave/paknsave_setup.py` — a callable module with three data sources and a clean/merge step:

```python
from scripts.paknsave.paknsave_setup import (
    fetch_stores,        # Step 1: fetch from Edge API (default), Mobile API, or store-finder
    clean_stores,        # Step 2: drop rows without coordinates (no-op for Pak'nSave)
    run_full_setup       # Run full pipeline end-to-end
)

# Full pipeline (default: Edge API, 57 stores)
run_full_setup()

# Full pipeline (store-finder page, 60 stores)
run_full_setup(source="store_finder")

# Full pipeline (legacy Mobile API, 60 stores)
run_full_setup(source="mobile")

# Individual steps
df = fetch_stores(source="edge")      # 57 stores from Edge API
df = fetch_stores(source="store_finder")  # 60 stores from __NEXT_DATA__
df = fetch_stores(source="mobile")     # 60 stores from Mobile API
df = clean_stores(df, cleaned=True)   # Drop NaN coords (no-op for Pak'nSave)
```

**CLI:**
```bash
python -m scripts.paknsave.paknsave_setup           # Edge API (default, 57 stores)
python -m scripts.paknsave.paknsave_setup store_finder  # Store-finder page (60 stores)
python -m scripts.paknsave.paknsave_setup mobile        # Mobile API (legacy, 60 stores)
```

### 9.2 Data Sources Compared

| Source | Stores | Method | Auth | Notes |
|--------|--------|--------|------|-------|
| **Edge API** (default) | 57 | `GET /v1/edge/store` with website JWT | `fs-user-token` from `get-current-user` | 3 stores missing (not configured for Edge ordering: Wairau Road, Gisborne City, Levin) |
| **Mobile API** (legacy) | 60 | `POST /mobile/user/login/guest` + `GET /mobile/store/physical` | Guest token + `PAKnSAVEApp/4.32.0` UA | Complete set; same data as store-finder but via API |
| **Store-finder page** | 60 | `GET /store-finder` → parse `__NEXT_DATA__` | None (cloudscraper) | Complete set; uses `contentstackStores` (GUIDs) + `regionStoreGroupings` (coords) |

**No geocoding required** — all sources provide latitude/longitude directly.

### 9.3 Pipeline Steps

The canonical store pipeline is `scripts/foodstuffs/Foodstuffs_setup.py` — a callable module supporting both brands with `source` parameter validation:

```python
from scripts.foodstuffs.Foodstuffs_setup import fetch_stores, clean_stores, run_full_setup

# Full pipeline for Pak'nSave (default: Edge API, 57 stores)
run_full_setup(brand="paknsave")

# Full pipeline for Pak'nSave (store-finder, 60 stores)
run_full_setup(brand="paknsave", source="store_finder")

# Full pipeline for Pak'nSave (legacy Mobile API, 60 stores)
run_full_setup(brand="paknsave", source="mobile")

# Individual steps
df = fetch_stores(brand="paknsave", source="edge")      # 57 stores from Edge API
df = fetch_stores(brand="paknsave", source="store_finder")  # 60 stores from __NEXT_DATA__
df = fetch_stores(brand="paknsave", source="mobile")     # 60 stores from Mobile API
df = clean_stores(df, cleaned=True)   # Drop NaN coords (no-op for Pak'nSave)
```

`Foodstuffs_setup.py` validates the `source` against `BRANDS[brand]["sources"]` — raises `ValueError` for invalid combinations (e.g., `store_finder` for `"newworld"`).

The legacy `paknsave_setup.py` (`python -m scripts.paknsave.paknsave_setup [edge|mobile|store_finder]`) is still functional and mirrors this structure.

| File | Rows | Description |
|------|------|-------------|
| `data/paknsave_stores.csv` | 57 / 60 | Store GUID, name, address, city, region (NI/SI), lat, lon |
| `data/paknsave_stores.json` | 57 / 60 | Same data, JSON format |

---

## 9. Production Architecture

### 9.1 Pak'nSave Unified API Module (`paknsave_api.py`)

A unified, callable API client supporting **two backends**:

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

### 9.2 Optimizers

#### 10.2.1 Edge API Optimizer (`paknsave_optimizer_edge.py`)

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
6. Output: cost comparison table + itemized breakdown → saves to `data/paknsave_latest_results.csv`

#### 10.2.2 Mobile API Optimizer (`paknsave_optimizer_mobile.py`)

```bash
python scripts/paknsave/paknsave_optimizer_mobile.py "Botany Town Centre, Auckland" "spaghetti bolognese"
```

**Pipeline:** Same as Edge but uses Mobile API (single-pass, guest token). No per-store price sort — returns first (most relevant) result. Same unit-price selection logic.

---

## 10. Supported Dishes (21)

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

Dishes are defined in `DISH_INGREDIENTS` in `scripts/paknsave/paknsave_api.py`
and the Pak'nSave notebook (cell 4). Unknown dish names fall through — the dish name
itself becomes the single search query.

---

## 11. CLI Usage

**Edge API Optimizer (Production — two-pass, relevance + price sort):**
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

Output: per-store itemised prices, total cost comparison, and the cheapest store.
Results saved to `data/paknsave_latest_results.csv` (Edge) or `data/paknsave_mobile_latest_results.csv` (Mobile).

---

## 12. Pak'nSave Store Setup

### Unified Pipeline (`paknsave_setup.py`)

A single module `scripts/paknsave/paknsave_setup.py` with callable functions + CLI, supporting **three data sources**:

```python
from scripts.paknsave.paknsave_setup import fetch_stores, clean_stores, run_full_setup

# Full pipeline (default: edge, 57 stores from Edge API)
run_full_setup()

# Full pipeline (store_finder, 60 stores from store-finder page)
run_full_setup(source="store_finder")

# Full pipeline (legacy Mobile API, 60 stores)
run_full_setup(source="mobile")

# Individual steps
fetch_stores(source="edge")
fetch_stores(source="mobile")
fetch_stores(source="store_finder")
clean_stores(cleaned=True)  # drops rows without lat/lon (no-op for Pak'nSave)
```

### Pipeline Details

**Step 1: `fetch_stores(source="edge"|"store_finder")`**

| Source | Stores | Method | Notes |
|--------|--------|--------|-------|
| `edge` (default) | 57 | `GET /v1/edge/store` with website JWT | Uses website JWT (`fs-user-token`) from `get-current-user`. Returns stores with coords. 3 stores missing (not on Edge API). |
| `store_finder` | 60 | `GET /store-finder` → parse `__NEXT_DATA__` | Extracts `contentstackStores` (GUIDs) + `store_finder.regionStoreGroupings` (coords). Joins on URL. |

**No geocoding needed** — both sources provide coordinates directly.

**Output**: `data/paknsave_stores.csv`, `data/paknsave_stores.json`

**Step 2: `clean_stores(cleaned=True)`**
- Optional: drops rows where latitude/longitude are NaN
- `cleaned=True` (default): drops missing coords
- `cleaned=False`: keeps all rows
- For Pak'nSave: **all stores have coordinates** — this is a no-op

**Step 3: `run_full_setup(source="edge", cleaned=True)`**
- Runs both steps, overwrites final CSV/JSON
- CLI: `python -m scripts.paknsave.paknsave_setup [edge|mobile|store_finder]`

### Key Files

| File | Rows | Description |
|------|------|-------------|
| `data/paknsave_stores.csv` | 57 / 60 | Store GUID, name, address, city, region (NI/SI), lat, lon |
| `data/paknsave_stores.json` | 57 / 60 | Same data, JSON format |

### CLI Usage

```powershell
# Full pipeline (default: edge, 57 stores)
python -m scripts.paknsave.paknsave_setup

# Full pipeline (store_finder, 60 stores)
python -m scripts.paknsave.paknsave_setup store_finder

# Full pipeline (legacy Mobile API, 60 stores)
python -m scripts.paknsave.paknsave_setup mobile

# Individual steps
python -c "from scripts.paknsave.paknsave_setup import fetch_stores; fetch_stores(source='edge')"
python -c "from scripts.paknsave.paknsave_setup import fetch_stores; fetch_stores(source='mobile')"
python -c "from scripts.paknsave.paknsave_setup import clean_stores; clean_stores(cleaned=False)"
```

### Legacy Scripts

| Script | Status | Replacement |
|--------|--------|-------------|
| `scripts/paknsave/fetch_stores.py` | **Deprecated** | `paknsave_setup.py` `fetch_stores()` |





---

**Credits:** Authored by [Arefu](https://github.com/Arefu) through reverse engineering the Foodstuffs Android app. Full OpenAPI spec in their [PaknSave repo](https://github.com/Arefu/PaknSave).