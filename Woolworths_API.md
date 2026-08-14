# Woolworths NZ Backend API Documentation

**Backend origin:** `shop.countdown.co.nz` — the underlying platform is shared between
Woolworths NZ and Countdown NZ. All `/api/v1` calls therefore resolve to Countdown's
infrastructure while returning Woolworths NZ product data and pricing.

---

## 1. How This Documentation Was Discovered

Every finding in this document was produced by **black-box HTTP probing** — no source
code, no internal documentation, and no authenticated access was used. The process
followed these steps:

1. **Seeded a `requests.Session`** by issuing a single `GET https://www.woolworths.co.nz/`
   with browser-like headers. This established the cookies and session context the site
   expects. No login, no Playwright, no real user account was required for public data.

2. **Enumerated candidate endpoint paths** by guessing ~25 conventional REST paths under
   `/api/v1` (e.g., `stores`, `products`, `products/search`, `shelves`, `trolleys/my`,
   `addresses/pickup-addresses`, `store/finder`, etc.). Each was tested with
   `session.get()` and the status code + response body inspected.

3. **Probed `/api/v1/products` exhaustively:** called it with `target=search`,
   `target=browse`, every plausible `dasFilter` format, every plausible store-context
   parameter name (`storeId`, `pickupStoreId`, `fulfilmentStoreId`, `locationId`,
   `addressId`, `clickAndCollectStoreId`, etc.), both `GET` and `POST` methods, and
   various `size`/`page`/`sort` combinations.

4. **Compared prices across store contexts** to detect whether the API carries
   per-store pricing. Searched "milk" with 10 products under three different store
   parameters and diffed each SKU's `salePrice` field against a no-parameter baseline.
   Zero differences confirmed global pricing.

5. **Tested all store-switch endpoints** by sending `POST` requests with three payload
   variants (`{"storeId": ...}`, `{"pickupAddressId": ...}`, `{"fulfilmentStoreId": ...}`)
   to 19 plausible endpoint paths. Every response was 404 — confirming no public API
   path exists for programmatic store context changes.

6. **Captured the full `shell` response** by calling `GET /api/v1/shell` and dumping
   every top-level key, then drilling into `context.shopper`, `context.fulfilment`,
   `mainNavs`, `specials`, and product search settings.

7. **Built the complete dasFacet hierarchy** by iterating all 14 department slugs from
   `mainNavs[1].navigationItems[0].items`, calling `GET /api/v1/products?target=browse
   &dasFilter=Department;;<slug>;false&size=1` for each, and collecting the returned
   `dasFacets` array (aisles) for each department.

8. **Inspected every key on store records** from `GET /api/v1/addresses/pickup-addresses`
   by iterating all `storeAreas[].storeAddresses[]` and printing the full key list for
   each record. No bridge keys (e.g. `siteDataId`, `externalId`) were found.

---

## 2. Base URL and Host

```
Base URL:  https://www.woolworths.co.nz/api/v1
Backend:   shop.countdown.co.nz  (internal hostname visible in all error messages)
```

All endpoints listed below are relative to `/api/v1`.

---

## 3. Required Request Headers

Every call to `/api/v1` must include at minimum these headers. Omitting
`x-requested-with` causes an immediate HTTP 400 with body
`{"message":"One or more errors occurred","errors":[{"field":"Header",
"message":"Header is missing and is invalid."}]}`.

```
x-requested-with:  ??           <- literal string, not a placeholder
User-Agent:        Mozilla/5.0 (Windows NT 10.0; Win64; x64)
                    AppleWebKit/537.36 (KHTML, like Gecko)
                    Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0
Accept:            application/json, text/plain, */*
Accept-Language:   en-NZ,en;q=0.9
```

The `x-requested-with: ??` header value was discovered through existing github repos (https://github.com/neon-ninja/woolies). Both the literal string `"??"` and `"XMLHttpRequest"` return HTTP 200; an empty string or absent header returns HTTP 400. Any other non empty string appears to be accepted.

---

## 4. Session Seeding

A vanilla `requests.Session` with the headers above is sufficient. No cookies,
tokens, or login are required for public endpoints. A single call to the homepage
establishes the cookie jar:

```python
import requests

session = requests.Session()
session.headers.update({...headers from section 3...})
session.get("https://www.woolworths.co.nz/", timeout=10)   # seeds cookies
```

Cookies acquired this way remain valid for weeks (observed behaviour; no expiry
header was found in responses). This is sufficient to call all documented endpoints.

---

## 5. Confirmed Working Endpoints

### 5.1 `GET /api/v1/shell`

Returns the full navigation shell, context, and site configuration for the current
(unauthenticated) session. This is the primary source of the department and aisle
taxonomy used by `dasFilter`.

**HTTP 200** — no parameters required.

#### Response structure

Top-level keys and their types:

| Key | Type | Description |
|-----|------|-------------|
| `specials` | `list[dict]` | Special offer categories (13 items) |
| `dynamicHeaderLink` | `dict` | Currently-promoted link |
| `mainNavs` | `list[dict]` | Primary navigation blocks (6 items) |
| `browseBanners` | `list[dict]` | Currently empty (`list[0]`) |
| `specialsBanners` | `list[dict]` | Promotional banner links |
| `recipesBanners` | `list[dict]` | Currently empty |
| `fulfilmentMessages` | `dict` | Localised delivery/pickup slot strings |
| `fulfilmentTimeouts` | `dict` | Reservation timeout labels |
| `traderVersion` | `string` | Front-end app version (e.g. `v7.79.23.1`) |
| `footerLinks` | `dict` | Footer navigation |
| `disabledMessageTitleNames` | `list` | Currently 3 items |
| `productSearchSettings` | `dict` | Keys: `maximumPagesToAutoLoad`,
`thresholdToLoadMoreOnScroll` |
| `expressFulfilmentSettings` | `dict` | Express delivery/pickup fee structure |
| `deliverySubscriptionSettings` | `dict` | Subscription order minimums |
| `deliveryFees` | `list[dict]` | 3 tier rows with `orderValue`, `baseFee`,
`additionalPercentageFee`, `isFreeDelivery` |
| `isSuccessful` | `bool` | Always `true` |
| `rootUrl` | `string` | `http://shop.countdown.co.nz` |
| `context` | `dict` | Session context (see 5.1.1) |
| `messages` | `null` | Always `null` |
| `changeOrderCheck` | `null` | Always `null` |

#### 5.1.1 `context` sub-object

```
context: {
  shopper: { ... },            # see 5.1.2
  fulfilment: { ... },         # see 5.1.3
  enabledFeatures: list[106],  # scalar strings, feature-flag IDs
  shoppingListItems: list[0],  # empty for unauthenticated sessions
  basketTotals: null,          # always null without login
  advancedSettingsResponse: null
}
```

#### 5.1.2 `context.shopper` fields (unauthenticated session values)

| Field | Type | Observed value |
|-------|------|----------------|
| `firstName` | `string` | `null` |
| `isShopper` | `bool` | `false` |
| `isLoggedIn` | `bool` | `false` |
| `hasOnecard` | `bool` | `false` |
| `oneCardBalance` | `any` | `null` |
| `shopperIdHash` | `string` | `null` |
| `shopperScvId` | `string` | `""` |
| `sessionGroups` | `any` | `null` |
| `orderCount` | `int` | `null` |
| `isSupplyLimitOverrideShopper` | `bool` | `false` |
| `isPriorityShopper` | `bool` | `false` |
| `isChangingOrder` | `bool` | `false` |
| `changingOrderId` | `any` | `null` |
| `hasActiveDeliverySubscription` | `bool` | `false` |
| `isWPayDeliverySubscription` | `bool` | `false` |

No other shopper fields were present in the unauthenticated response.

#### 5.1.3 `context.fulfilment` fields

| Field | Type | Observed value | Description |
|-------|------|----------------|-------------|
| `address` | `string` | `"Glenfield"` | Suburb name (delivery area guess) |
| `selectedDate` | `string` | `null` | No slot selected |
| `selectedDateWithTZInfo` | `string` | `null` | — |
| `startTime` | `string` | `null` | Slot start window |
| `endTime` | `string` | `null` | Slot end window |
| `method` | `string` | `"Courier"` | `"Courier"` or `"Pickup"` |
| `cutOffTime` | `string` | `null` | Express cutoff |
| `isSlotToday` | `bool` | `false` | — |
| `isAddressInDeliveryZone` | `bool` | `true` | Whether delivery address is covered |
| `isDefaultDeliveryAddress` | `bool` | `false` | Is this the stored default? |
| `areaId` | `int` | `1242` | Geographic area identifier |
| `suburbId` | `int` | `0` | Always 0 in unauthenticated context |
| `pickupAddressId` | `int` | `0` | 0 = no pickup store selected |
| `fulfilmentStoreId` | `int` | `9171` | Default delivery-area store identifier |
| `perishableCode` | `string` | `"P"` | Perishable handling zone |
| `locker` | `any` | `null` | Locker selection (unused) |
| `expressFulfilment` | `dict` | See below | Express slot flags and fees |

`expressFulfilment` sub-keys:

| Key | Observed value |
|-----|----------------|
| `isExpressSlot` | `false` |
| `isFlexibleDeliverySlot` | `false` |
| `expressPickUpFee` | `null` |
| `expressDeliveryFee` | `null` |
| `flexibleDeliveryFee` | `null` |

**Critical distinction:** `fulfilmentStoreId: 9171` is a *delivery-area* store ID (for
courier fulfilment). It does **not** appear in the pickup-addresses store list (tested
by scanning 20+ store IDs — `9171` is absent). This ID belongs to the store's delivery ID.

#### 5.1.4 `mainNavs` structure

`mainNavs` is a list of 6 navigation blocks. The first five carry `navigationItems[]`,
each holding `items[]`. Each item carries navigation metadata and zero or more
`dasFacets` that describe its position in the facet tree.

Observed top-level `mainNavs` map:

| Index | Label | Items (first 3) |
|-------|-------|-----------------|
| 0 | *(unnamed)* | *no items present* |
| 1 | **Browse** | Fruit & Veg, Meat & Poultry, Fish & Seafood ... |
| 2 | **Specials & offers** | Specials & offers, Member Price, Boosts ... |
| 3 | **Favourites & lists** | Favourites, Past orders, Saved lists ... |
| 4 | **Recipes** | *no items present* |
| 5 | **Disney OOSHIES(TM)** | *no items present* |

Each Browse item has keys: `id`, `label`, `url` (e.g. `/shop/browse/meat-poultry`),
`dasFacets` (one element describing this department), `promoTiles`.

Each `dasFacets` entry on a Browse item:

| Key | Description |
|-----|-------------|
| `key` | Facet type, e.g. `"Department"` |
| `value` | Numeric string identifier, e.g. `"2"` |
| `name` | Human label, e.g. `"Meat & Poultry"` |
| `isBooleanValue` | `false` for all departments |
| `productCount` | Total products in this department |
| `shelfResponses` | Empty at the Browse level; populated on aisle-level responses |

### 5.2 `GET /api/v1/products`

The primary product catalogue endpoint. Accepts a large set of query parameters.

**HTTP 200** returns a JSON object with this shape:

```json
{
  "products": {
    "items":      [ /* product objects */ ],
    "totalItems": 10000
  },
  "dasFacets":   [ /* facet objects */ ],
  "sortOptions": [ /* sort option objects */ ],
  "currentPageSize":  24,
  "currentSortOption": "BrowseRelevance"
}
```

#### Parameters

| Parameter | Required | Values / type | Default | Description |
|-----------|----------|---------------|---------|-------------|
| `target` | Yes (mode) | `"search"` or `"browse"` | — | Switches between keyword search and full catalogue browse |
| `search` | Yes if target=search | `string` | — | Free-text product query |
| `dasFilter` | Yes for aisle/department filtering | `string` (see section 6) | — | Hierarchical facet filter; only valid with `target=browse` |
| `size` | No | `int` (1-120 tested; 120 unconfirmed) | `24` | Results per page |
| `page` | No | `int` (1-indexed) | `1` | Page number |
| `sort` | No (browse) | `PriceAsc`, `PriceDesc`, `CUPAsc`, `BrowseRelevance` | `BrowseRelevance` | Sort order |
| `inStockProductsOnly` | No | `"false"` or `"true"` | `"false"` | Exclude out-of-stock items |

`target=search` ignores `dasFilter` and `sort`. `target=browse` ignores `search`.

#### `sort` option values

| Value | Meaning |
|-------|---------|
| `BrowseRelevance` | Site's internal relevance ranking (no order guaranteed) |
| `PriceAsc` | Lowest price first |
| `PriceDesc` | Highest price first |
| `CUPAsc` | Lowest unit price (cost per kg/L/unit) first |

#### Product item schema (target=search and target=browse)

```json
{
  "type":           "Product",
  "name":           "woolworths nz beef mince grass fed 5% fat",
  "brand":          "woolworths nz",
  "slug":           "woolworths-nz-beef-mince-grass-fed-5-fat",
  "sku":            "42246",
  "barcode":        "9414742036509",
  "variety":        "standard",
  "unit":           "Each",
  "selectedPurchasingUnit": null,
  "price": {
    "originalPrice":       16.99,
    "salePrice":           16.99,
    "savePrice":           0.00,
    "savePercentage":      0.0,
    "canShowSavings":      true,
    "hasBonusPoints":      false,
    "isClubPrice":         false,
    "isSpecial":           false,
    "isNew":               false,
    "canShowOriginalPrice":true,
    "discount":            null,
    "total":               null,
    "isTargetedOffer":     false,
    "averagePricePerSingleUnit": null,
    "isBoostOffer":        false,
    "purchasingUnitPrice": null,
    "ordered":             null
  }
}
```

**Price fields of interest:**

| Field | Type | Meaning |
|-------|------|---------|
| `price.salePrice` | `float` | **Current selling price — use this for comparisons** |
| `price.originalPrice` | `float` | Price before any discount |
| `price.savePrice` | `float` | `originalPrice - salePrice` |
| `price.savePercentage` | `float` | Discount percentage |
| `price.isSpecial` | `bool` | `true` if on special (not club price) |
| `price.isClubPrice` | `bool` | `true` if member/club exclusive price |
| `price.isMemberPrice` | `bool`/`null` | `true` if Everyday Rewards member price; `null` when not logged in |

#### Pagination

`size` controls items per page; `page` (1-indexed) selects the page. The maximum tested
`size` is 120 (from the GitHub code sample). For "milk" at `size=10`, `page=2` returned
10 items and `totalItems=495`, confirming the page parameter is honoured and counts are
exact. There is no `nextPage` cursor — page numbers are predictable integers.

#### `dasFacets` format (search and browse responses)

Both `target=search` and `target=browse` responses include a `dasFacets` array at the
top level. Each element:

```json
{
  "key":              "Aisle",       // facet type: "Department", "Aisle", "Brand", ...
  "value":            "88",          // numeric string identifier
  "name":             "Beef",        // human label
  "productCount":     103,
  "isBooleanValue":   false,
  "shelfResponses": [                // empty at top level; populated in dept responses
    { "id": 541, "label": "Steak", "url": "steak" },
    ...
  ]
}
```

At the top-level browse (no `dasFilter`), `dasFacets` contains all 14 departments.
When `dasFilter=Department;;meat-poultry;false` is applied, `dasFacets` is replaced by
the aisles within that department (12 aisles for Meat & Poultry).

### 5.3 `GET /api/v1/addresses/pickup-addresses`

Returns all click-and-collect pickup store locations.

**HTTP 200** — no parameters required.

#### Response structure

```json
{
  "storeAreas": [
    {
      "id":   494,
      "name": "All Pick up locations",
      "storeAddresses": [
        {
          "id":     1225718,
          "name":   " Woolworths Northlands",
          "address": "cnr Main North & Sawyers Arms Roads,Northlands Click and Collect,8051,Northlands Click and Collect"
        },
        ...
      ]
    },
    ...
  ]
}
```

**Store record schema (confirmed across 20+ stores):**

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | Store identifier — this is the value used in `ChangeStore.py` button clicks |
| `name` | `string` | Store name (leading space present on some records) |
| `address` | `string` | Full address string; first comma-delimited segment is the street/suburb |
| *(no other keys)* | | `siteDataId`, `externalId`, `siteCode` are all absent |

The `storeAreas` array contains delivery-zone groupings. Area `id=494` with
`name="All Pick up locations"` is the catch-all group containing every pickup store.
This is the group selected in `ChangeStore.py` and `Get_woolworths_store_choices.py`.

---

## 6. DasFilter Syntax and Complete Taxonomy

### 6.1 Format

`dasFilter` accepts a semicolon-delimited string encoding a hierarchical facet path.
Each facet group has the form:

```
{key};;{value};{isBoolean}
```

Multiple facets are AND-chained simply by concatenation:

```
Department;;meat-poultry;false;Aisle;;88;false
```

| Segment | Meaning |
|---------|---------|
| `Department` | Facet type key (from `dasFacets[].key`) |
| `;;` | Delimiter between key, value, and boolean |
| `meat-poultry` | Facet value — for Departments, this is the URL slug from Browse |
| `false` | Boolean flag (`true`/`false`); observed as `false` for all departments and aisles |

**Valid key types observed in `dasFacets`:**

| Key | Value format | Example |
|-----|-------------|---------|
| `Department` | URL slug | `meat-poultry`, `pantry`, `fridge-deli` |
| `Aisle` | Numeric string | `88`, `89`, `116` |
| Subsequent levels | Not confirmed | shelf-level keys not tested |

**Confirmed working filters:**

| dasFilter value | Result |
|----------------|--------|
| *(absent)* | Full 10,000-product catalogue |
| `Department;;meat-poultry;false` | 624 products, aisles returned |
| `Department;;pantry;false` | 6,566 products |
| `Department;;fruit-veg;false` | 722 products |
| `Department;;meat-poultry;false;Aisle;;88;false` | Accepted (HTTP 200) but **does NOT narrow** from the parent department (still 624 items) |
| `2;;1;false` (raw numeric dept key) | Accepted but **ignored** (returns full catalogue) |

**Not working:** Shelf-level filtering (`Shelf;;541;false`) returns `totalItems=-1`
and zero items. Aisle-level chaining beyond the department produces no further
narrowing regardless of format tried.

### 6.2 Complete Department and Aisle Map

All counts are from `target=browse&dasFilter=Department;;<slug>;false&size=1`
as of the exploration date. `shelfResponses` is `[]` (empty) at the department
level for all departments — shelf data is not exposed via the API without additional
context that was not discovered.

#### Fruit & Veg (slug: `fruit-veg`) — 722 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 116 | Fruit | 128 |
| 117 | Vegetables | 276 |
| 118 | Prepared Fruit & Veg | 48 |
| 119 | Fresh Salad & Herbs | 159 |
| 120 | In Season | 33 |
| 121 | Organic | 22 |
| 122 | The Odd Bunch | 14 |
| 123 | Shop Fresh Deals | 42 |

#### Meat & Poultry (slug: `meat-poultry`) — 624 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 88 | Beef | 103 |
| 89 | Chicken & Poultry | 123 |
| 90 | Lamb | 53 |
| 91 | Pork | 71 |
| 92 | Venison & Game | 3 |
| 93 | Mince & Patties | 26 |
| 94 | Sausages | 61 |
| 95 | BBQ Meat | 105 |
| 96 | Roast Meat | 31 |
| 98 | Offal & Bones | 3 |
| 99 | Plant Based Alternatives | 9 |
| 100 | 3 for $20 | 36 |

#### Fish & Seafood (slug: `fish-seafood`) — 113 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 130 | Fish | 5 |
| 131 | Salmon | 49 |
| 132 | Prawns & Seafood | 45 |
| 133 | 3 for $20 | 14 |

#### Fridge & Deli (slug: `fridge-deli`) — 2,821 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 26 | Eggs, Butter & Spreads | 149 |
| 27 | Milk | 222 |
| 28 | Cheese | 791 |
| 29 | Yoghurt & Desserts | 271 |
| 30 | Cream & Custard | 42 |
| 31 | Juice & Drinks | 112 |
| 32 | Deli Meats & Seafood | 310 |
| 33 | Prepared Meals & Sides | 589 |
| 34 | Deli Salads | 41 |
| 35 | Pasta, Pizza & Pastry | 75 |
| 36 | Dips, Hummus & Nibbles | 191 |
| 37 | Vegan & Vegetarian | 19 |
| 38 | 3 for $12 Deli | 9 |

#### Bakery (slug: `bakery`) — 706 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 16 | Bakery In Store | 179 |
| 17 | Sliced & Packaged Bread | 107 |
| 18 | Buns, Rolls & Bread Sticks | 58 |
| 19 | Wraps, Pita & Pizza Bases | 72 |
| 20 | Pastries, Croissants & Biscuits | 47 |
| 21 | Cakes, Muffins & Desserts | 165 |
| 22 | Bagels, Crumpets & Pancakes | 51 |
| 23 | Gluten Free | 14 |
| 24 | Low Carb & Keto | 13 |

#### Frozen (slug: `frozen`) — 997 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 78 | Frozen Vegetables | 131 |
| 79 | Frozen Meat | 70 |
| 80 | Frozen Meat Alternatives | 24 |
| 81 | Frozen Seafood | 98 |
| 82 | Frozen Fruit & Drink | 45 |
| 83 | Frozen Meals & Snacks | 198 |
| 84 | Pizza, Pastry & Bread | 48 |
| 85 | Ice Cream & Sorbet | 326 |
| 86 | Frozen Desserts | 55 |
| 87 | Ice | 2 |

#### Pantry (slug: `pantry`) — 6,566 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 59 | Snacks & Sweets | 1,866 |
| 60 | Biscuits & Crackers | 502 |
| 61 | Tinned Foods & Packets | 568 |
| 62 | Baking | 473 |
| 63 | Cereals & Spreads | 445 |
| 64 | Sauces & Pastes | 698 |
| 65 | Pasta, Noodles & Grains | 402 |
| 66 | Herbs, Spices & Stock | 349 |
| 67 | Oil, Vinegar & Condiments | 458 |
| 68 | Meal Kits | 183 |
| 69 | International Foods | 336 |
| 70 | Eggs | 25 |
| 71 | Desserts | 152 |
| 72 | Long Life Milk | 78 |
| 73 | Bulk Foods | 31 |

#### Beer & Wine (slug: `beer-wine`) — 1,557 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 134 | Beer | 199 |
| 135 | Craft Beer | 96 |
| 136 | Cider | 50 |
| 137 | Champagne & Sparkling Wine | 109 |
| 138 | Red Wine | 416 |
| 139 | White Wine | 397 |
| 140 | Rose Wine | 108 |
| 141 | Moscato & Sweet Wine | 25 |
| 142 | Cask Wine | 17 |
| 143 | Mini Wine Bottles & Cans | 48 |
| 144 | Organic Wine | 14 |
| 145 | Seltzer & Alcoholic Kombucha | 6 |
| 146 | Lower Alcohol | 21 |
| 147 | Non Alcoholic | 51 |

#### Drinks (slug: `drinks`) — 1,683 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 39 | Coffee | 473 |
| 40 | Tea & Milk Drinks | 349 |
| 41 | Soft Drinks & Sports Drinks | 362 |
| 42 | Juice & Cordial | 323 |
| 43 | Water | 137 |
| 44 | Chilled Juice & Drinks | 39 |

#### Health & Body (slug: `health-body`) — 3,968 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 101 | Bath, Shower & Soap | 254 |
| 102 | Hair Care | 782 |
| 103 | Dental & Oral Care | 219 |
| 104 | Deodorant & Body Sprays | 166 |
| 105 | Skin Care & Sun Care | 778 |
| 106 | Eye & Ear Care | 51 |
| 107 | Shaving & Hair Removal | 123 |
| 108 | Make Up & Nail Care | 356 |
| 109 | Tissues & Cotton Wool | 50 |
| 110 | Period & Continence Care | 200 |
| 111 | Medical & First Aid | 290 |
| 112 | Vitamins & Supplements | 435 |
| 113 | Sports Nutrition & Weight Management | 216 |
| 115 | Contraception & Pregnancy | 48 |

#### Household (slug: `household`) — 2,189 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 45 | Bathroom | 92 |
| 46 | Kitchen | 431 |
| 47 | Laundry | 190 |
| 48 | Cleaning | 398 |
| 49 | Pest Control | 69 |
| 50 | Homewares | 57 |
| 51 | Bags | 62 |
| 52 | Clothing & Accessories | 153 |
| 54 | Garden & Garage | 97 |
| 55 | Hardware & Electrical | 249 |
| 56 | Entertainment & Gifts | 205 |
| 57 | Magazines & Stationery | 186 |

#### Baby & Child (slug: `baby-child`) — 655 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 125 | Nappies & Wipes | 207 |
| 126 | Baby Food | 199 |
| 127 | Formula | 62 |
| 128 | Bottles, Toys & Accessories | 181 |
| 129 | For Mum | 6 |

#### Pet (slug: `pet`) — 602 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 74 | Cats | 278 |
| 75 | Dogs | 224 |
| 76 | Birds, Fish & Small Animals | 25 |
| 77 | Pet Health & Accessories | 75 |

#### Back to School (slug: `back-to-school`) — 1,264 products

| Aisle ID | Name | Product count |
|----------|------|--------------|
| 148 | Breakfast Ideas | 196 |
| 149 | Lunchbox Ideas | 444 |
| 150 | Snacks Ideas | 334 |
| 151 | Multipacks | 158 |
| 152 | School Essentials | 132 |

**Total catalogue product count at time of exploration: 22,512 products** (sum of all
department counts; each product appears in exactly one aisle).

---

## 7. Endpoints Tested That Do NOT Work

The following paths were probed and confirmed non-functional. They are listed here
to prevent redundant investigation.

### 7.1 GET endpoints returning 404

| Path | Error body |
|------|-----------|
| `/api/v1/stores` | `No HTTP resource was found ... 'shop.countdown.co.nz/api/v1/stores'` |
| `/api/v1/store` | 404 |
| `/api/v1/store/finder` | 404 |
| `/api/v1/store-location` | 404 |
| `/api/v1/pickup-locations` | 404 |
| `/api/v1/addresses/find-store` | 404 |
| `/api/v1/product/{sku}` | 404 (path tried as `/api/v1/product/282768`) |
| `/api/v1/products/search` | 404 (distinct from `/api/v1/products?target=search`) |
| `/api/v1/shelves` | 404 |
| `/api/v1/shelf` | 404 |
| `/api/v1/categories` | 404 |
| `/api/v1/trolleys/active` | 404 |
| `/api/v1/trolleys` | 404 |
| `/api/v1/session/current` | 404 |
| `/api/v1/user/current` | 404 |
| `/api/v1/delivery-slots` | 404 |
| `/api/v1/bookatimeslot` | 404 |
| `/api/v1/click-and-collect` | 404 |
| `/api/v1/specials` | 404 |
| `/api/v1/member-prices` | 404 |
| `/api/v1/catalogs` | 404 |
| `/api/v1/store-products` | 404 |
| `/api/v1/session` | 404 (returns generic "Ooops" error) |

### 7.2 GET endpoints returning 401

| Path | Notes |
|------|-------|
| `/api/v1/trolleys/my` | Requires authenticated shopper session |

### 7.3 POST endpoints (all return 404)

Tested with payloads `{"storeId": <id>}`, `{"pickupAddressId": <id>}`, and
`{"fulfilmentStoreId": <id>}`:

| Path |
|------|
| `/api/v1/addresses/set-store` |
| `/api/v1/addresses/set-pickup-store` |
| `/api/v1/addresses/set-default-store` |
| `/api/v1/addresses/selected-store` |
| `/api/v1/addresses/change-store` |
| `/api/v1/addresses/my` |
| `/api/v1/addresses/current` |
| `/api/v1/addresses/pickup-address` |
| `/api/v1/addresses/pickup-addresses` |
| `/api/v1/store/context` |
| `/api/v1/store/current` |
| `/api/v1/store/set` |
| `/api/v1/store/selected` |
| `/api/v1/fulfilment/store` |
| `/api/v1/fulfilment/selected-store` |

No public API endpoint was found that accepts a store change instruction and
returns HTTP 200 or 204. Store context is set exclusively by browser cookies
acquired through navigation of the Woolworths web application.

### 7.4 `target=search` returning 400 (missing header)

`GET /api/v1/products?target=search&search=milk` returns HTTP 400 when the
`x-requested-with` header is absent or empty. This is not a broken endpoint — it is
a header-validation gate that all API calls must pass.

### 7.5 `target=browse` with aisle-level or shelf-level `dasFilter`

Adding an `Aisle` component to `dasFilter` is accepted (HTTP 200) but does not
narrow results:

```
target=browse&dasFilter=Department;;meat-poultry;false;Aisle;;88;false
-> HTTP 200  totalItems=624  (same as department-only filter)
```

The raw numeric format also does not work:

```
target=browse&dasFilter=2;;1;false
-> HTTP 200  totalItems=10000  (full catalogue, filter ignored)
```

Shelf-level targeting returns zero results:

```
target=browse&dasFilter=Department;;meat-poultry;false;Aisle;;88;false;Shelf;;541;false
-> HTTP 200  totalItems=10000  (filter ignored)
```

---

## 8. Per-Store Pricing — Full Findings

### 8.1 Initial Finding: Global Pricing via Query Parameters

The `fulfilmentStoreId`, `pickupStoreId`, and 8 other store-context query parameters
on `/api/v1/products` are accepted without error (HTTP 200) but produce **ZERO price
changes**.

#### Test methodology

1. Called `GET /api/v1/products?target=search&search=milk&size=10` with no store
   parameter -> collected 10 products with their `sku` and `salePrice`.
2. Called the same endpoint adding `fulfilmentStoreId=9171` (the default delivery
   store from `context.fulfilment`) -> compared every returned SKU price against
   the baseline. **Zero changes.**
3. Called the same endpoint adding `fulfilmentStoreId=1225718` (a pickup store,
   Woolworths Northlands, from the pickup-addresses list) -> **zero changes.**

#### Parameters tested (all accepted, none effective)

`fulfilmentStoreId`, `pickupStoreId`, `clickAndCollectStoreId`, `collectionStoreId`,
`deliveryStoreId`, `storeCode`, `storeExternalReference`, `locationId`, `addressId`,
`store`, `fulfilmentType`.

Initial conclusion: Woolworths NZ uses a **global price list** across all stores for
the catalogue API. Per-store pricing differences (if any) are applied at the checkout /
fulfilment layer, not at product-search time.

**This conclusion was later found to be incomplete** — see sections 8.2-8.10.

### 8.2 Discovery: Playwright Cookie Injection Changes Prices

When Playwright captures cookies after selecting a store in the change-pick-up-store
modal, and those cookies are injected into `requests.Session`, `/api/v1/products`
returns **DIFFERENT per-store prices**.

#### Known price differential used for validation

| Store | pickupAddressId | Woolworths Milk Standard 3L salePrice |
|-------|-----------------|--------------------------------------|
| Greymouth | 764300 | $7.15 |
| Glenfield | 1190273 | $7.33 |

#### Tests

- Full 67-cookie jar injection: [OK] confirmed working ($7.15 / $7.33)
- Tested in `explore_woolworths_api_part2.py` Step 2

### 8.3 Discovery: URL-Param Seeding Does NOT Work

Visiting `https://www.woolworths.co.nz/?pickupStoreId=764300` does **NOT** set cookies
that change API prices. The store context is set exclusively by browser-side JavaScript,
not URL parameters. The server does not translate URL params into cookies.

Tested in `explore_woolworths_api_part2.py` Step 1.

### 8.4 Cookie Analysis — Which Cookies Matter

#### Full cookie jar breakdown (67 cookies from Greymouth capture)

| Domain | # Cookies | Example names | Required? |
|--------|-----------|---------------|-----------|
| `.woolworths.co.nz` | ~30 | AKA_A2, rxVisitor, dtSa, dtPC, _abck, ak_bmsc, utag_main_* | Most NOT required individually |
| `.www.woolworths.co.nz` | 1 | RT (Adobe Analytics ECID) | NOT required |
| `www.woolworths.co.nz` | ~15 | cw-ssuflow, agaCORS, aga, ASP.NET_SessionId, XSRF-TOKEN, cw-lrkswrdjp | cw-lrkswrdjp IS required |
| `.doubleclick.net` | 1 | IDE | NOT required |
| `.adnxs.com` | 2 | uuid2, XANDR_PANID | NOT required |
| `.tealiumiq.com` | 3 | tcs.google_gid, tcs.google_cver, TAPID | NOT required |
| `.rubiconproject.com` | 4 | audit_p, khaos, khaos_p, audit | NOT required |
| `.casalemedia.com` | 3 | CMID, CMPS, CMPRO | NOT required |
| `.pubmatic.com` | 2 | KRTBCOOKIE_377, PugT | NOT required |
| `.bidswitch.net` | 2 | tuuid, c | NOT required |
| `.adsrvr.org` | 2 | TDID, TDCPM | NOT required |
| `.optimizely.com` | 1 | session_state (cdn.optimizely.com) | NOT required |
| `a21125881217.cdn.optimizely.com` | 1 | session_state | NOT required |
| `.kampyle.com` | 4 | kampyle_userid, kampyleUserSession, etc. | NOT required |
| `.woolworths.co.nz` | 1 | _fbp, _ga, _ga_*, _gcl_au | NOT required |

#### Tests proving which cookies are NOT required

- session_state cookie only: both stores return $7.33 (wrong) [FAIL] — tested in `explore_woolworths_api_part2.py` Step 2b
- RT cookie only: both stores return $7.33 (wrong) [FAIL] — tested in `explore_woolworths_api_part2.py` Step 2c
- RT + session_state together: not sufficient on their own [FAIL]
- All 67 cookies injected: works ($7.15 / $7.33) [OK] — tested in `explore_woolworths_api_part2.py` Step 2

#### The crucial cookie: cw-lrkswrdjp

Injecting ONLY this 1 cookie (no session_state, no RT, no other Playwright cookies)
correctly sets the store context. Confirmed in `explore_woolworths_api_part3.py` Step 3b
and 3c. This is the **ONLY cookie required for per-store pricing**.

### 8.5 The cw-lrkswrdjp Cookie — Structure and Construction

#### Format

```
dm-Pickup,f-9009,a-224,s-38    (Greymouth)
dm-Pickup,f-9443,a-440,s-38    (Glenfield)
dm-Pickup,f-9101,a-720,s-38    (Birkenhead)
```

#### Field definitions

| Field | Prefix | Meaning | Example | Required? |
|-------|--------|---------|---------|-----------|
| dm | dm- | Delivery method | Pickup | YES (always "Pickup" for pickup stores) |
| f | f- | fulfilmentStoreId (internal) | 9009 | YES — this is the key field |
| a | a- | areaId (internal fulfilment area) | 224 | NO — cookie works without it |
| s | s- | Site/segment constant | 38 | NO — cookie works without it, confirmed constant across all tested stores |

#### Minimum viable cookie

`dm-Pickup,f-{fulfilmentStoreId}` is sufficient. The a- and s- fields are optional.

Tested in `explore_woolworths_api_part3.py` Step 3c: injecting
`cw-lrkswrdjp=dm-Pickup,f-9009,a-0,s-38` and `cw-lrkswrdjp=dm-Pickup,f-9009,a-224`
both correctly set the shell context.

#### How fulfilmentStoreId differs from pickupAddressId

- **pickupAddressId**: the public store ID visible in `/api/v1/addresses/pickup-addresses`
  (e.g., 764300 for Greymouth)
- **fulfilmentStoreId**: an internal ID used by the cookie (e.g., 9009 for Greymouth)
- These are DIFFERENT numbers with no formulaic relationship
- fulfilmentStoreId is NOT available as is from any known API endpoint

#### Where fulfilmentStoreId IS available: woolworths_store_data.json

The `extra1` field in `data/woolworths_store_data.json` (fetched from the Woolworths
store locator API) IS the fulfilmentStoreId:

| Store | extra1 | fulfilmentStoreId | Match? |
|-------|--------|-------------------|--------|
| Greymouth | 9009 | 9009 | [OK] |
| Glenfield | 9443 | 9443 | [OK] |
| Birkenhead | 9101 | 9101 | [OK] |

Verified across all 3 known stores with 100% accuracy.

The `extra2` field is the pickupAddressId:

| Store | extra2 | pickupAddressId | Match? |
|-------|--------|-----------------|--------|
| Greymouth | 764300 | 764300 | [OK] |
| Glenfield | 1190273 | 1190273 | [OK] |
| Birkenhead | 2124460 | 2124460 | [OK] |

Note: extra1 does NOT always equal site.id (only 38 out of 183 stores match). extra1
is the correct fulfilmentStoreId.

**Important: extra1 collisions** — extra1 is a *fulfilment store ID*, not a unique
pickup-location identifier. Three pairs of physically different Woolworths stores
share the same extra1 value:

| extra1 | Store A | Store A extra2 | Store B | Store B extra2 | Resolves to (via /shell pickupAddressId) |
|--------|---------|----------------|---------|----------------|------------------------------------------|
| 9290 | Nelson Junction (33 Cadillac Way, Nelson) | 4166071 | Motueka (108 High St) | 767216 | Motueka |
| 9112 | Te Puke (Cnr Queen & Boucher St) | 913417 | Bureta Park (44-50 Bureta Rd) | 1175393 | Te Puke |
| 9511 | Bridge Street (Hamilton) | 1207646 | Matamata (Cnr Arawa & Gouk Sts) | 911335 | Matamata |

When the cookie `f-{extra1}` is injected, the /shell endpoint returns a single
`pickupAddressId` that matches **one** of the two stores' extra2 values. The
"other" store in each pair is **not addressable** via any cookie key (extra2
and site.id are both rejected by the shell). This means only 3 of the 6 stores
are effectively reachable; the remaining 3 always return the prices of their
fulfilment partner. Verified via `scripts/woolworths/exploration/explore_extra1_collisions.py`
(Phase 5: /shell context validation). See `logs.md` §63 for the full investigation.

**Pipeline note**: the optimizer no longer bridges extra2->extra1 at runtime.
`woolworths_setup.fetch_store_data()` builds `data/woolworths_stores.csv` with
`id=extra1` directly from CDX, `get_nearby_stores()` returns that `id` as
`store_id`, and `set_store_context(session, store_id)` builds the cookie as
`dm-Pickup,f-{extra1},s-38`. The `extra2` value (pickupAddressId) is
informational only — the legacy `get_store_mapping()` helper in `woolworths_api.py`
has been removed.

### 8.6 Cookie Lifespan and Expiry

- session_state cookies expire when browser closes (session scope)
- First-party `.woolworths.co.nz` cookies appear session-scoped or short-lived
  (1-4 hours observed)
- The cw-lrkswrdjp cookie itself may be longer-lived since it's a simple encoded value
- `/api/v1/shell` can validate cookie freshness: if fulfilmentStoreId == 9171 (default),
  cookies have expired or were not injected

### 8.7 Why Other Cookies Are Not Needed

The 66 other cookies in the full jar fall into these categories:

1. **Security/bot-detection cookies** (AKA_A2, _abck, ak_bmsc, bm_sz): These are
   Akamai Bot Manager cookies. They validate that the request comes from a real browser.
   However, they are NOT required for API calls — the API returns correct data with just
   the x-requested-with header and a standard User-Agent. These cookies are only needed
   if Akamai starts blocking requests (which it hasn't for the /api/v1 endpoints).

2. **Analytics/tracking cookies** (rxVisitor, dtSa, dtPC, dtCookie, dtid, rxvt,
   utag_main_*, _fbp, _ga, _gcl_au): These are Dynatrace, Tealium, and Google Analytics
   cookies. They track user behaviour for analytics purposes. They have NO effect on
   store context or pricing.

3. **Third-party ad cookies** (IDE, uuid2, XANDR_PANID, TDID, TDCPM, audit_p, khaos,
   CMID, CMPS, CMPRO, KRTBCOOKIE_377, PugT, tuuid, c): These are advertising network
   cookies (Google, AppNexus, Rubicon, PubMatic, etc.). They are assigned probabilistically
   and are completely irrelevant to store context.

4. **Adobe Analytics** (RT on .www.woolworths.co.nz): This is the Adobe ECID (Experience
   Cloud ID) cookie. It's a persistent browser identifier but is NOT store-specific.
   Testing proved it does not affect pricing.

5. **Optimizely** (session_state): A/B testing session cookie. Not store-specific.

6. **Session/security** (ASP.NET_SessionId, XSRF-TOKEN, aga, agaCORS, cw-ssuflow,
   cw-arjshtsw, cw-laie, cw-lrkswrdjp): These are server-side session tokens. Most are
   set by the server on the initial GET /. Only cw-lrkswrdjp carries store context.

7. **Kampyle** (kampyle_userid, kampyleUserSession, etc.): Feedback/UX analytics.
   Irrelevant.

### 8.8 Playwright — When It IS and IS NOT Required

#### NOT required (just requests + constructed cookie)

- Product price searches: construct cw-lrkswrdjp from extra1 (the canonical store_id), inject, call /api/v1/products
- Store context validation: call /api/v1/shell after injection, check fulfilmentStoreId
- All read-only operations on the API

#### IS required (one-time only)

- Initial mapping capture: Playwright must visit the store-selection modal for each store
  to extract the cw-lrkswrdjp cookie value. This captures the fulfilmentStoreId (extra1)
  and areaId (a-field).
- **HOWEVER**: the fulfilmentStoreId is already available in woolworths_store_data.json as
  extra1, so Playwright is NOT needed even for initial capture — `fetch_store_data()` reads CDX
  directly and keys the store list on extra1. The legacy `woolworths_store_choices.csv`
  (pickupAddressId) is no longer the source of store identity for the cookie.
- The areaId (a-field) is NOT in any data source and would require Playwright to capture.
  But since it's optional, this is not a blocker.

#### Architecture implication

With the extra1 mapping from woolworths_store_data.json, we can construct cw-lrkswrdjp
cookies for all 183 stores without any Playwright:

```python
cookie_val = f"dm-Pickup,f-{extra1},s-38"
```

**Caveat**: As of 2026-08-13, 3 pairs of stores share extra1 (see §8.5 "Important:
extra1 collisions"). Only 3 of those 6 stores are reachable via the cookie.
The other 3 are silently collapsed into their fulfilment partner.

### 8.9 Validation: Constructed Cookie Produces Per-Store Pricing

Testing in `explore_woolworths_api_part4.py` confirmed:

- 3/3 stores: constructed cookie correctly sets /api/v1/shell context [OK]
- 21/21 milk products: constructed cookie produces different prices between Greymouth
  and Glenfield [OK]
- Key prices: SKU 282768 (Woolworths Milk Standard 3L): Greymouth $7.15, Glenfield $7.33
  (+$0.18)
- Constructed cookie is equivalent to full 67-cookie Playwright jar

### 8.10 Cookie Construction — Minimal vs Full

| Cookie value | Works for context? | Works for pricing? | Notes |
|-------------|-------------------|-------------------|-------|
| `dm-Pickup,f-9009` | [OK] YES | [OK] YES | Minimum viable |
| `dm-Pickup,f-9009,a-224` | [OK] YES | [OK] YES | With areaId |
| `dm-Pickup,f-9009,a-224,s-38` | [OK] YES | [OK] YES | Full cookie |
| `dm-Pickup,f-9009,a-0,s-38` | [OK] YES | [OK] YES | areaId=0 works |
| `dm-Pickup,f-764300,a-224,s-38` | [FAIL] NO (default 9171) | [FAIL] NO | pickupAddressId as f-field does NOT work |
| *(no cookie)* | [FAIL] NO (default 9171) | [FAIL] NO | Baseline |

### 8.11 Fresh Session Per Store (Required)

**The server's `Set-Cookie` response from `GET /` overwrites any injected
`cw-lrkswrdjp` cookie when reusing a `requests.Session`.**

Tested by injecting cookies for Metro Auckland (f-9250), Auckland City (f-9045),
and Ponsonby (f-9500) into the same session:
- First store (Metro Auckland): shell returns fulfilmentStoreId=9250 [OK]
- Second store (Auckland City): shell STILL returns 9250 [FAIL] — cookie was overwritten
- Third store (Ponsonby): shell STILL returns 9250 [FAIL] — cookie was overwritten

**Root cause:** The `GET /` response includes `Set-Cookie: cw-lrkswrdjp=...` with the
default store. When `session.cookies.set()` is called to inject a different value, the
next `GET /` (or any request that triggers a cookie refresh) overwrites it with the
server's value.

**Fix:** Create a fresh `requests.Session` for each store:
```python
for store in nearby_stores:
    session = create_session()       # new session + GET /
    set_store_context(session, pid)  # inject cookie (not yet overwritten)
    search_products(session, ...)    # works correctly
```

**Verified:** Fresh sessions correctly return per-store fulfilmentStoreIds:
- Metro Auckland: 9250 [OK]
- Auckland City: 9045 [OK]
- Ponsonby: 9500 [OK]
- Newmarket: 9405 [OK]
- Mount Eden: 9544 [OK]

---

## 9. Store ID Mapping [LEGACY - indirection retired]

> **Status**: Retained for historical reference only. The optimizer no longer
> bridges `pickupAddressId`->`fulfilmentStoreId` via a mapping table. Store identity
> now keys directly on `extra1` (fulfilmentStoreId) sourced from CDX. See section 15.3
> (`fetch_store_data()` builds `woolworths_stores.csv` keyed on extra1) and `decision.md`
> section 28.

### 9.1 Three ID Types

| ID Type | Source | Example (Greymouth) | Where found |
|---------|--------|---------------------|-------------|
| pickupAddressId (extra2) | `/api/v1/addresses/pickup-addresses` | 764300 | `storeAddresses[].id` |
| fulfilmentStoreId (extra1) | woolworths_store_data.json | 9009 | `siteDetail[].site.extra1` |
| site.id | woolworths_store_data.json | 9469 | `siteDetail[].site.id` |

### 9.2 Mapping Table (3 stores verified via Playwright)

| Store | pickupAddressId | fulfilmentStoreId (extra1) | areaId (from cookie) | site.id |
|-------|-----------------|---------------------------|---------------------|---------|
| Greymouth | 764300 | 9009 | 224 | 9469 |
| Glenfield | 1190273 | 9443 | 440 | 9163 |
| Birkenhead | 2124460 | 9101 | 720 | 9145 |

**Note**: this mapping existed to translate `pickupAddressId`->`extra1` for cookie
construction. It is no longer needed — the optimizer sources extra1 directly from
CDX and uses it both as `store_id` and in the `cw-lrkswrdjp` cookie.

### 9.3 How the (Legacy) Mapping Was Built

1. Load `woolworths_store_data.json`
2. For each siteDetail, extract: name, extra1 (fulfilmentStoreId), extra2 (pickupAddressId)
3. Cross-reference with `woolworths_store_choices.csv` to get store names
4. Save as a unified mapping: `pickupAddressId -> {fulfilmentStoreId, name}`
5. Cookie construction: `dm-Pickup,f-{extra1},s-38`

### 9.4 Data Sources for Store Data

| File | Content | Source |
|------|---------|--------|
| woolworths_store_data.json | Site details incl. extra1 (fulfilmentStoreId) + extra2 (pickupAddressId) + lat/lon | woolworths_setup.py - `fetch_store_data()` (CDX API) |
| woolworths_store_choices.csv | [LEGACY] pickup locations keyed on extra2 (pickupAddressId) | woolworths_setup.py - `fetch_store_choices()` (pickup-addresses API) - not consulted by optimizer |
| woolworths_stores.csv | **Canonical** store list keyed on `id`=extra1 (fulfilmentStoreId) + lat/lon + name + address | woolworths_setup.py - `fetch_store_data()` (reads CDX directly) |

---

## 10. Production Architecture

### 10.1 How to Get Per-Store Prices (No Playwright Required)

```python
import csv, requests

# 1. Load the canonical store list (keyed on extra1 / fulfilmentStoreId)
#    Generated by woolworths_setup.fetch_store_data() from CDX data.
stores = []
with open('data/woolworths_stores.csv') as f:
    for row in csv.DictReader(f):
        if row['latitude'] and row['longitude']:
            stores.append({
                'store_id': row['id'],          # extra1 (fulfilmentStoreId) — canonical
                'name': row['name'],
                'lat': float(row['latitude']),
                'lon': float(row['longitude']),
            })

# 2. Set store context — keys directly on extra1 (no mapping table needed)
def set_store_context(session, fulfilment_store_id):
    """Inject cw-lrkswrdjp cookie for the given store (id = extra1)."""
    fsid = str(fulfilment_store_id)
    cookie_val = f'dm-Pickup,f-{fsid},s-38'
    session.cookies.set('cw-lrkswrdjp', cookie_val,
                        domain='www.woolworths.co.nz', path='/')

    # Validate via shell endpoint — check it is not the default store 9171
    resp = session.get('https://www.woolworths.co.nz/api/v1/shell', timeout=15)
    fulf = resp.json().get('context', {}).get('fulfilment', {})
    if fulf.get('fulfilmentStoreId') == 9171:
        raise RuntimeError('Cookie not accepted — store context not set')
    return {
        'fulfilmentStoreId': fulf.get('fulfilmentStoreId'),
        'method': fulf.get('method'),
    }

# 3. Search for products
def search_products(session, query, size=20, food_only=False):
    """Search products with current store context.

    Returns list of dicts: sku, name, salePrice, originalPrice, isSpecial,
    unitPrice, volumeSize, cupMeasure, cupListPrice, url, imageUrl, department.
    """
    resp = session.get(
        'https://www.woolworths.co.nz/api/v1/products',
        params={'target': 'search', 'search': query, 'size': size},
        timeout=15,
    )
    data = resp.json()
    items = data.get('products', {}).get('items', [])
    results = []
    for item in items:
        if food_only and not is_food_department(item):
            continue
        price_info = item.get('price', {})
        size_info = item.get('size', {})
        departments = item.get('departments', [])
        dept_name = departments[0].get('name', '') if departments else ''
        results.append({
            'sku': item.get('sku'),
            'name': item.get('name', ''),
            'salePrice': price_info.get('salePrice'),
            'originalPrice': price_info.get('originalPrice'),
            'isSpecial': price_info.get('isSpecial', False),
            'unitPrice': size_info.get('cupPrice', ''),
            'volumeSize': size_info.get('volumeSize', ''),
            'cupMeasure': size_info.get('cupMeasure', ''),
            'cupListPrice': size_info.get('cupListPrice', ''),
            'url': item.get('url', ''),
            'imageUrl': item.get('imageUrl', ''),
            'department': dept_name,
        })
    return results

# 4. Usage — store_id IS extra1 (fulfilmentStoreId); e.g. 9290 for Nelson Junction
session = requests.Session()
session.headers.update({
    'x-requested-with': '??',
    'User-Agent': 'Mozilla/5.0 ...',
    'Accept': 'application/json, text/plain, */*',
})
session.get('https://www.woolworths.co.nz/', timeout=15)  # seed cookies

# Nelson Junction Woolworths: extra1 = 9290 (NOT the legacy pickupAddressId 4166071)
ctx = set_store_context(session, fulfilment_store_id=9290)
print(f"fulfilmentStoreId={ctx['fulfilmentStoreId']}")

items = search_products(session, 'milk', food_only=True)
for item in items:
    print(f"${item['salePrice']} — {item['name']}")
```

### 10.2 Architecture Diagram

```
woolworths_store_data.json   (CDX API, source of extra1 + lat/lon)
  |
  v
fetch_store_data()  ->  woolworths_stores.csv   (id = extra1, canonical store_id)
  |   (filters: null extra1, EXCLUDED_STORE_IDS [9285, 9035])
  v
FOR EACH nearby store (store_id = extra1):
  1. create_session()          # fresh requests.Session + GET / to seed cookies
  2. set_store_context(session, store_id):      # store_id IS extra1 — no lookup
       cookie = f"dm-Pickup,f-{store_id},s-38"
       session.cookies.set("cw-lrkswrdjp", cookie)
  3. /api/v1/shell -> validate fulfilmentStoreId != 9171
  4. /api/v1/products?target=search&search=<ingredient>
  5. item["price"]["salePrice"] -> per-store price  -> build_woolworths_row(store_id=extra1)
```

**CRITICAL: A fresh session must be created for each store.** The server's `Set-Cookie`
response from `GET /` overwrites any injected `cw-lrkswrdjp` cookie on a reused session.
See section 8.11 for details.

### 10.3 When Playwright IS Still Needed

Playwright is NOT needed for any API operation. It is only needed if you want to:

1. Scrape the actual website (not the API) for data not available via /api/v1
2. Perform actions that require a real browser (e.g., adding to trolley, checkout)
3. Access authenticated endpoints (e.g., /api/v1/trolleys/my)

For the meal cost optimizer, the API + constructed cookies are sufficient.

### 10.4 Fresh Session Per Store (Required)

**The server's `Set-Cookie` response from `GET /` overwrites any injected
`cw-lrkswrdjp` cookie when reusing a `requests.Session`.** This means:

- Creating one session and switching stores by re-injecting the cookie does NOT work
- The shell will continue returning the first store's `fulfilmentStoreId` regardless
- A fresh session (new `GET /`) must be created for each store

**Tested and confirmed:** Fresh sessions correctly return per-store fulfilmentStoreIds
(9250, 9045, 9500 for Auckland stores). Reused sessions always return the first
store's ID.

**Implementation in `optimizer_utils.woolworths_querier`** (the CLI
`woolworths_optimizer.py` passes the `woolworths_api` module as the `api` param):
```python
for store in nearby:
    store_name = store["name"]
    store_id = store["store_id"]   # = extra1 (fulfilmentStoreId) directly
    session = api.create_session()       # fresh session per store
    try:
        ctx = api.set_store_context(session, store_id)   # keys on extra1 directly
        products = api.search_products(session, ing, food_only=True)
    except RuntimeError as e:
        print(f"  [WARN] {e} -- skipping store")
        continue
```

### 10.5 Cookie Refresh Strategy

The cw-lrkswrdjp cookie is a simple encoded value — it does not expire on its own.
However, other session cookies (ASP.NET_SessionId, XSRF-TOKEN, etc.) do expire.
Strategy:

1. Create a fresh session per store (GET / to seed baseline cookies)
2. Inject cw-lrkswrdjp (sets store context)
3. If /api/v1/shell returns fulfilmentStoreId=9171, the cookie was not accepted
4. The cookie value itself is static and does not need refreshing

---

## 11. Summary of API Capabilities

| Capability | Available via API? | Method |
|-----------|-------------------|--------|
| Search products by keyword | [OK] Yes | `GET /api/v1/products?target=search&search=<term>` |
| Browse full catalogue (10K items) | [OK] Yes | `GET /api/v1/products?target=browse` |
| Filter by department | [OK] Yes (partial) | `target=browse&dasFilter=Department;;<slug>;false` |
| Filter by aisle | [WARN] Accepted but ignored | — |
| Filter by shelf | [FAIL] No | — |
| Sort by price (asc/desc) | [OK] Yes | `sort=PriceAsc` / `sort=PriceDesc` |
| Sort by unit price | [OK] Yes | `sort=CUPAsc` |
| Get per-store pricing | [OK] YES | Inject cw-lrkswrdjp cookie (constructed from extra1) |
| Programmatically change store | [OK] YES | Set cw-lrkswrdjp cookie — no POST endpoint needed |
| Get all pickup stores | [OK] Yes | `GET /api/v1/addresses/pickup-addresses` |
| Get site navigation taxonomy | [OK] Yes | `GET /api/v1/shell` |
| Get session fulfilment context | [OK] Yes | `context.fulfilment` inside `/api/v1/shell` |
| View trolley / cart | [FAIL] No (unauthenticated) | 401 |
| Get delivery slot availability | [FAIL] No | 404 |

---

## 12. Key Gotchas

1. **Prices are NOT global** — the initial finding of "global pricing" was wrong. Prices
   ARE per-store, but only when the correct cookie (cw-lrkswrdjp) is set. Query
   parameters alone do not change prices.
2. **fulfilmentStoreId != pickupAddressId** — these are different numbers. The optimizer
   keys directly on `extra1` (fulfilmentStoreId) from CDX; the `cw-lrkswrdjp` cookie uses
   `f-{extra1}`. The legacy `pickupAddressId` (extra2) no longer drives the pipeline.
3. **x-requested-with header is mandatory** — omitting it returns HTTP 400. The literal
   string "??" works.
4. **session.get(BASE_URL) must be called first** — seeds baseline cookies that the
   API expects.
5. **Cookie domain must be correct** — set cw-lrkswrdjp on domain
   "www.woolworths.co.nz" (not ".woolworths.co.nz").
6. **areaId is optional** — the cookie works with just
   `dm-Pickup,f-{fulfilmentStoreId}`. The a- and s- fields are not required.
7. **s-38 is constant** — confirmed across Greymouth, Glenfield, and Birkenhead. Safe
   to hardcode.
8. **Playwright headless=False required** — if you do use Playwright, the site blocks
   headless Chromium.
9. **Nominatim geocoding rate limit** — 1 req/sec for address lookups.
10. **Store names have leading spaces** — some records in pickup-addresses have leading
    spaces in the name field.
11. **Fresh session required per store** — reusing a `requests.Session` causes the
    server's `Set-Cookie` response to overwrite the injected `cw-lrkswrdjp` cookie.
    Create a new session (with `GET /`) for each store.
12. **`target=search` ignores `dasFilter`** — department/aisle filtering only works
    with `target=browse`. For search, filter client-side using the `departments[].id`
    field on each product (see section 13).

---

## 13. Client-Side Department Filtering

### 13.1 The Problem

The `target=search` endpoint **ignores `dasFilter`** (section 5.2). There is no
API parameter to restrict search results to food departments only. Non-food items
(Health & Body, Household, Baby & Child, Pet, Back to School) can appear in
ingredient search results (e.g., pet food matching "beef mince").

### 13.2 Solution: Filter by `departments[].id`

Each product returned by `GET /api/v1/products?target=search` includes a
`departments` array:

```json
"departments": [{"id": 4, "name": "Fridge & Deli"}]
```

The 14 Woolworths department IDs (from `/api/v1/shell` → `mainNavs[1]`):

| Dept ID | Name | Food? |
|---------|------|-------|
| 1 | Fruit & Veg | Yes |
| 2 | Meat & Poultry | Yes |
| 3 | Fish & Seafood | Yes |
| 4 | Fridge & Deli | Yes |
| 5 | Bakery | Yes |
| 6 | Frozen | Yes |
| 7 | Pantry | Yes |
| 8 | Beer & Wine | Yes |
| 9 | Drinks | Yes |
| 10 | Health & Body | **No** |
| 11 | Household | **No** |
| 12 | Baby & Child | **No** |
| 13 | Pet | **No** |
| 14 | Back to School | **No** |

**Non-food IDs**: `{10, 11, 12, 13, 14}`

### 13.3 Implementation in `woolworths_api.py`

```python
NON_FOOD_DEPARTMENT_IDS = {10, 11, 12, 13, 14}

def is_food_department(product):
    """Check if a product is in a food department.

    Products with no department info are included (assumed food).
    """
    depts = product.get("departments", [])
    if not depts:
        return True
    dept_ids = {d.get("id") for d in depts if "id" in d}
    return not dept_ids.intersection(NON_FOOD_DEPARTMENT_IDS)
```

`search_products()` accepts `food_only=False`. When `True`,
products failing `is_food_department()` are excluded from results.

### 13.4 Usage

```python
# Food-only search (excludes Health & Body, Household, Baby & Child, Pet, Back to School)
items = search_products(session, "beef mince", size=10, food_only=True)

# Unfiltered (includes all departments — default)
items = search_products(session, "milk", size=10)
```

### 13.5 Limitations

- **Client-side only**: The API does not support department filtering on
  `target=search`. Filtering happens after results are returned.
- **Extra API calls**: To guarantee N food-only results, the caller may need to
  request more than N items from the API and filter down.
- **`target=browse` supports `dasFilter`**: If department-level filtering is
  needed without keyword search, use `target=browse&dasFilter=Department;;<slug>;false`
  instead (but this does not support free-text search).

---

## 14. Exploration Scripts

| Script | Phase | Purpose |
|--------|-------|---------|
| explore_woolworths_api_part1.py | Phase 1 | Black-box API probing, endpoint enumeration, dasFilter taxonomy |
| explore_woolworths_api_part2.py | Phase 2 | URL-param seeding test, Playwright cookie capture/injection, cookie diff, session_state/RT isolation |
| explore_woolworths_api_part3.py | Phase 3 | /api/v1/shell validation, fulfilmentStoreId query param test, cw-lrkswrdjp deep-dive (3b: cookie-only injection, 3c: minimal cookie) |
| explore_woolworths_api_part4.py | Phase 4 | Programmatic cookie construction, mapping capture, price validation (21/21 products), constructed vs full jar comparison |

---

## 15. Woolworths Store Setup Process (Unified Pipeline)

### 15.1 The Problem: Incomplete Pickup Store Coverage

The `GET /api/v1/addresses/pickup-addresses` endpoint returns 19 `storeAreas`. 
Area `id=494` ("All Pick up locations") contains only **171 stores**. 
Regional areas (e.g., area 302 "Waikato") contain additional pickup points that are **NOT** in area 494.

This was relevant to the **legacy** merge pipeline (which joined choices.id=pickupAddressId with CDX SiteDataID=extra2). **Store identity is now sourced directly from CDX via extra1 (fulfilmentStoreId)** — see §15.3. The pickup-addresses API / `fetch_store_choices()` is retained only for historical reference and is no longer consulted by the optimizer.

**Missing stores** from area 494 include:
- Woolworths Chartwell (area 302, Waikato)
- Remote collection points: Paparoa Hall, Ruawai, Whangamomona Hall, Makahu Hall, EXPRESS PU Spotswood, etc. (17 total)

### 15.2 Solution: Unified Pipeline (`woolworths_setup.py`)

A single module `scripts/woolworths/woolworths_setup.py` with the main pipeline
function + `run_full_setup()`:

```python
from scripts.woolworths.woolworths_setup import (
    fetch_store_data,      # Fetches CDX data + builds woolworths_stores.csv (keyed on extra1)
    fetch_store_choices,   # [LEGACY] regenerates data/woolworths_store_choices.* ; not consulted by optimizer
    run_full_setup         # Runs fetch_store_data() only (legacy choices detached)
)
```

### 15.3 Pipeline Details

**`fetch_store_choices()` — [LEGACY, detached]**
- Fetches `GET /api/v1/addresses/pickup-addresses`
- Iterates ALL 19 `storeAreas` (not just area 494)
- Dedupes by `id` (pickupAddressId / extra2)
- Output: `data/woolworths_store_choices.csv` (188 rows: id, name, address)
- **Not called by the main pipeline** — store identity now comes from CDX via
  `fetch_store_data()`. Retained as a standalone function so it can be invoked
  ad-hoc to regenerate the legacy files. See `woolworths_setup.py` module
  docstring for details.

**`fetch_store_data(cleaned=True)` — the unified store builder**
- Fetches `GET https://api.cdx.nz/site-location/api/v1/sites` (183 sites)
- Writes `data/woolworths_store_data.json` (raw CDX response, unchanged)
- Builds the cleaned store list, applying two filters:
  1. **Skip sites with extra1 = "null"** (literal string emitted by CDX for
     3 Auckland Metro stores + 1 other — these have no usable fulfilmentStoreId)
  2. **Skip sites in `EXCLUDED_STORE_IDS`** — hardcoded shut-down stores that
     CDX still lists:
     - `9285` (Te Atatu Woolworths): shut down 24/04/2025
     - `9035` (Kaikohe Woolworths): shut down 15/02/2026
- Writes `data/woolworths_stores.csv` with schema:
  `id, name, address, latitude, longitude` where **`id` = `extra1`**
  (fulfilmentStoreId) — the canonical store identity.
- `cleaned=True` (default) also drops rows with non-numeric/blank lat or lon.
- Output: **177 stores** (183 CDX sites − 4 null-extra1 − 2 shut-down)
- `data/woolworths_store_data.csv` (the intermediate wide CSV) is **no longer
  produced** — the full store data is contained in the JSON, and the optimizer
  only needs the 5-column `woolworths_stores.csv`.

**Note on extra1 collisions**: extra1 is a *fulfilment store ID* — 3 pairs of
physically different stores share the same extra1 (Nelson Junction/Motueka,
Te Puke/Bureta Park, Bridge Street/Matamata). See §8.5 ("Important: extra1
collisions") and `logs.md` §63 for details. Only 3 of the 6 are reachable via
the cookie; the other 3 are silently dropped (they share extra1 with a
different physical store).

### 15.4 Key Files

| File | Rows | Description |
|------|------|-------------|
| `data/woolworths_store_choices.csv` | 188 | [LEGACY, detached] All pickup locations (deduped across 19 areas), keyed on extra2. Not produced by the main pipeline; can be regenerated by calling `fetch_store_choices()` directly. |
| `data/woolworths_store_data.json` | 183 | Raw CDX store data with lat/lon + extra1 (fulfilmentStoreId) + extra2 (pickupAddressId). Source for woolworths_stores.csv. |
| `data/woolworths_stores.csv` | 177 | **Canonical** store list keyed on `id`=extra1 (fulfilmentStoreId) + lat/lon + name + address. Built by `fetch_store_data()`. 183 CDX sites minus 4 null-extra1 minus 2 shut-down stores. |

> **`data/woolworths_store_data.csv` is no longer produced.** Previously a
> 9-column intermediate CSV (Store Name, Suburb, Address, Postcode, State,
> SiteDataID, latitude, longitude, Key Facilities). The full store data lives in
> the JSON; only the 5-column `woolworths_stores.csv` is needed downstream.

### 15.5 CLI Usage

```powershell
# Full pipeline (produces both woolworths_store_data.json + woolworths_stores.csv)
python scripts/woolworths/woolworths_setup.py

# Individual steps
python -c "from scripts.woolworths.woolworths_setup import fetch_store_data; fetch_store_data(cleaned=True)"
python -c "from scripts.woolworths.woolworths_setup import fetch_store_choices; fetch_store_choices()"  # legacy only
```

---

## 16. Files and Data Sources

| File | Purpose |
|------|---------|
| Woolworths_API.md | This document |
| AGENTS.md | Project overview and file structure |
| scripts/woolworths/woolworths_api.py | Cookie-based API module: session creation, store context injection, product search, nearby stores |
| scripts/woolworths/woolworths_optimizer.py | **Thin CLI**: Step 1 query via shared `woolworths_querier` in `optimizer_utils.py`, then Step 2 `optimise()`. Supports `--requery`, `--distance` flags, 5km default |
 | scripts/woolworths/woolworths_setup.py | Unified store pipeline: `fetch_store_data()` fetches CDX data (177 stores after filtering) and builds `woolworths_stores.csv` keyed on extra1 (fulfilmentStoreId); filters out shut-down stores (9285, 9035) and null-extra1 sites. `fetch_store_choices()` [LEGACY, detached] regenerates `woolworths_store_choices.*`. |
| scripts/woolworths/exploration/explore_extra1_collisions.py | Phase 7: investigation of extra1 collision pairs (9112, 9290, 9511) — shell context inspection, live price queries across extra1/extra2/site.id keys |
| scripts/combined/initialize_full_results.py | Creates `data/full_results.csv` with 17-column structure including `pk_hash` for deduplication |
| scripts/woolworths/Exploration/explore_woolworths_api_part1.py | Phase 1: black-box API probing, endpoint enumeration, dasFilter taxonomy |
| scripts/woolworths/Exploration/explore_woolworths_api_part2.py | Phase 2: URL-param seeding test, Playwright cookie capture/injection, cookie diff |
| scripts/woolworths/Exploration/explore_woolworths_api_part3.py | Phase 3: shell validation, cw-lrkswrdjp deep-dive (cookie-only injection, minimal cookie) |
| scripts/woolworths/Exploration/explore_woolworths_api_part4.py | Phase 4: programmatic cookie construction, mapping capture, price validation |
| scripts/woolworths/Playwright/ChangeStore.py | Playwright store selection via modal (reference implementation) |
| data/woolworths_store_data.json | [Source] CDX store details with extra1 (fulfilmentStoreId) and extra2 (pickupAddressId) + lat/lon — 183 sites (4 excluded for null extra1, 2 hardcoded as shut-down) |
| data/woolworths_store_choices.csv | [LEGACY, detached] pickup-addresses API output keyed on extra2 (pickupAddressId) — not consulted by optimizer; can be regenerated via `fetch_store_choices()` |
| data/woolworths_stores.csv | [Canonical] 177 stores (183 CDX − 4 null-extra1 − 2 shut-down) keyed on `id`=extra1 (fulfilmentStoreId) + lat/lon + name + address. Built by `fetch_store_data()`. |
| data/full_results.csv | Shared append-only CSV with all search results (pk_hash for dedup) |
| data/Exploration/woolworths/part2_cookies.json | Playwright-captured full cookie jars (Greymouth, Glenfield, baseline) |
