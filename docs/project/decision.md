# Key Decisions

## 1. Pak'nSave first, expand later

Chose Pak'nSave as initial target because their mobile API is accessible (no auth walls beyond guest token). Other NZ supermarkets (New World, Woolworths) can be added by replicating the API pattern for their platforms.

## 2. Foodstuffs mobile API over website scraping

The Pak'nSave website is a Next.js app on Vercel with Cloudflare protection and a .NET backend (`CommonApi`). Direct website scraping is blocked. The mobile API (`api-prod.prod.fsniwaikato.kiwi`) has no Cloudflare and accepts guest tokens — far more reliable.

## 3. cloudscraper for website requests, plain requests for API

`cloudscraper` is used when hitting `paknsave.co.nz` (Cloudflare-protected). The mobile API domain has no Cloudflare, so `cloudscraper` works but isn't strictly necessary there. Both scripts use `cloudscraper` for consistency.

## 4. Guest token auth (no user accounts)

No login required — guest token obtained via POST with `{"banner": "PNS"}`. Token lasts 30 min and is auto-refreshed. Avoids needing to handle user credentials.

## 5. First/most-relevant result, not cheapest

Product search returns results sorted by relevance. Taking the cheapest would return pet food or bulk items for queries like "beef mince". Using `products[0]` gives the most practical match.

## 6. Hand-curated ingredient lists

21 dishes with manually defined ingredient lists. No NLP/LLM parsing because:
- Keeps the prototype simple and deterministic
- Avoids API costs or model dependencies
- Ingredient queries need to be specific to Pak'nSave's product naming

## 7. 5 km search radius

Auckland CBD has only 1 Pak'nSave within 5 km. East Auckland (Botany/Manukau) has 3. The 5 km default balances convenience with store coverage. Adjustable via `MAX_DISTANCE_KM`.

## 8. Pak'nSave Store data from __NEXT_DATA__ (single fetch)

All store data is now obtained from a single fetch of the `/store-finder` page's `__NEXT_DATA__`:
- **`contentstackStores`**: maps URL paths to store GUIDs (60 stores)
- **`store_finder.regionStoreGroupings`**: provides store name, address, and latitude/longitude

The two datasets are joined on the shared `url` field. This eliminated the need for both the separate homepage fetch and the Nominatim geocoding step.

## 9. Nominatim for Pak'nSave Store geocoding (retired)

Geocoding is no longer needed — the `/store-finder` page's `__NEXT_DATA__` includes latitude/longitude directly from the `contactDetails` field, with higher precision than Nominatim returns. The Nominatim rate limit (1 req/sec), dedicated `User-Agent`, and `time.sleep` delay were all removed.

## 10. Jupyter notebook as primary interface

Chosen for easy experimentation — user can edit inputs and re-run cells without touching the terminal. CLI (`prototype.py`) available as alternative.

## 11. API-based Woolworths store discovery
Woolworths store locations are manually identified via a discovered JSON API (`https://api.cdx.nz/site-location/api/v1/sites`). This replaces manual HTML inspection and provides complete, structured, and filterable store data.

## 12. Automated store discovery
Store locations are fetched and converted to CSV automatically via the unified store pipeline (`tools/woolworths/woolworths_setup.py`, the successor to the retired `Get_woolworths_store_API_data.py`). This approach provides complete coverage and allows for automated filtering based on distance.

## 13. Playwright headed scraping over direct API for Woolworths

Initial testing of `GET /api/v1/products?target=search&search=milk` returned `400 Header is missing or is invalid.` — the documented endpoint is not usable without a verified authenticated session context. Playwright (headed Chromium) can load the public search results page and read rendered prices from Angular shadow DOM (`product-stamp-grid > div.product-entry`). Headless mode is unstable due to Akamai, so headed mode with `--disable-blink-features=AutomationControlled` is required. Successfully navigated to the Woolworths website and located the store selection dropdown.

**Update (resolved):** The `target=search` endpoint **does** work without authentication — the `400` was caused by a missing `x-requested-with: ??` header, not by missing session context. A single `GET /` seeds cookies, and the API can be called with `requests.Session`. Playwright is NOT needed at runtime for any API operation. The `cw-lrkswrdjp` cookie can be constructed from `extra1` in `woolworths_store_data.json` and injected into a `requests.Session` for per-store pricing. Playwright was only needed for the initial exploration/discovery phase.

## 14. Joined Woolworths store datasets via common ID

Successfully linked store names (from dropdown choices API) with latitude/longitude (from location API) using a common ID. This allows for accurate store identification and filtering by distance, resolving previous name-matching issues.

## 15. Direct Store Selection via URL
Chose to use `https://www.woolworths.co.nz/bookatimeslot/(hww-modal:change-pick-up-store)` to bypass complex dropdown navigation and directly trigger the store selection modal, enabling reliable automated store selection.

## 16. Jupyter/Windows Async Workaround
Use `subprocess.Popen` for scraping to bypass `NotImplementedError` in Jupyter's event loop (Windows Proactor policy conflict).

## 17. Robust Pathing
Use absolute path construction (`os.path.abspath`) with `__file__` or `os.getcwd()` for all file access, preventing `FileNotFoundError` in sub-processes.

## 18. Woolworths API `x-requested-with: ??` header

The `GET /api/v1/products?target=search` endpoint requires the literal header `x-requested-with: ??` (or any non-empty string including `XMLHttpRequest`). Without this header, all API calls return HTTP 400. Discovered via black-box probing of the `/api/v1` surface + existing github repositories. This header was the sole blocker that previously made the API appear unusable.

## 19. Woolworths per-store pricing — cookie injection, not query params

`fulfilmentStoreId` and `pickupStoreId` query parameters on `/api/v1/products` are accepted (HTTP 200) but **do not change prices**. Per-store pricing is controlled by the `cw-lrkswrdjp` cookie, which encodes `dm-Pickup,f-{fulfilmentStoreId},a-{areaId},s-{site}`. The cookie can be constructed from `extra1` in `woolworths_store_data.json` (verified 3/3 stores). Different stores return different prices (e.g., Greymouth Milk 3L = $7.15, Glenfield = $7.33). The optimiser must search each ingredient at each nearby store with a fresh session per store.

## 20. `cw-lrkswrdjp` is the sole per-store cookie

Of the 67 cookies captured from Playwright, only `cw-lrkswrdjp` carries store context. The other 66 cookies (session_state, RT, Akamai, analytics, ads) were systematically isolated and proven irrelevant — injecting them alone does not change pricing. The full 67-cookie jar produces the same result as injecting just `cw-lrkswrdjp`. This was verified in `explore_woolworths_api_part2.py` (session_state-only and RT-only tests) and `explore_woolworths_api_part3.py` (cookie-only injection).

## 21. `extra1` in `woolworths_store_data.json` = `fulfilmentStoreId`

The `extra1` field from the CDX store locator API (`api.cdx.nz`) is the `fulfilmentStoreId` used in the `cw-lrkswrdjp` cookie. Verified across 3 stores:

| Store | extra1 | fulfilmentStoreId (from cookie) | Match |
|-------|--------|--------------------------------|-------|
| Greymouth | 9009 | 9009 | [OK] |
| Glenfield | 9443 | 9443 | [OK] |
| Birkenhead | 9101 | 9101 | [OK] |

This means Playwright is NOT needed even for initial mapping capture — the cookie can be constructed for all 183 stores directly from the data file. The `extra2` field is the `pickupAddressId` (different number).

## 22. Fresh session required per store

The server's `Set-Cookie` response from `GET /` overwrites any injected `cw-lrkswrdjp` cookie when reusing a `requests.Session`. Tested by injecting cookies for 3 Auckland stores into the same session — only the first store's context was respected. Creating a fresh session (new `GET /`) for each store fixes this. This is implemented in `optimiser_utils.woolworths_querier` (via `woolworths_api.create_session`, called fresh per store).

## 23. `areaId` is optional in the cookie

The `a-{areaId}` field in `cw-lrkswrdjp` is not required for per-store pricing. Tested in `explore_woolworths_api_part3.py` Step 3c:
- `dm-Pickup,f-9009,a-0,s-38` works (areaId=0)
- `dm-Pickup,f-9009,a-224` works (no s-field)
- `dm-Pickup,f-9009` works (minimum viable)

The `areaId` is NOT available from any API endpoint and would require Playwright to capture per-store. Since it's optional, this is not a blocker.

## 24. `s-38` is constant across all tested stores

The `s-{site}` field in `cw-lrkswrdjp` is `38` for Greymouth, Glenfield, and Birkenhead. Safe to hardcode in cookie construction.

## 25. New World uses Foodstuffs mobile API with `banner: "MNW"`

New World is owned by Foodstuffs (same as Pak'nSave). The mobile API at `api-prod.prod.fsniwaikato.kiwi/prod` serves both banners — use `banner: "PNS"` for Pak'nSave and `banner: "MNW"` for New World. The User-Agent must match the banner: `PAKnSAVEApp/4.32.0` for Pak'nSave, `NewWorldApp/4.32.0` for New World. This means New World stores can be fetched with the same infrastructure as Pak'nSave, just with different banner and User-Agent values.

## 26. New World mobile API over Nominatim geocoding

The Foodstuffs mobile API (`GET /mobile/store/physical`) returns latitude/longitude directly for all 149 New World stores. This eliminates the need for Nominatim geocoding, which failed on 22 stores. The API also provides store UUIDs, banner info, click-and-collect/delivery flags, and opening hours — all in a single request. No rate limiting concerns.

## 27. New World Edge API — FULL product search works (Algolia-based)

The New World Edge API (`api-prod.newworld.co.nz/v1/edge/`) provides **complete functionality** for the meal cost optimiser:

### Store Listing
`GET /v1/edge/store` — Returns 148 stores with full details (id, name, address, coordinates, opening hours).

### Product Search — Two-Pass Pipeline
`POST /v1/edge/search/paginated/products` — Algolia-powered search with per-store pricing.

**Authentication**: Accepts JWT from either:
- Mobile API guest login (`api-prod.prod.fsniwaikato.kiwi/prod/mobile/user/login/guest`)
- Website session (`POST /api/user/get-current-user` on `www.newworld.co.nz` → cookie `fs-user-token`)

**Required headers**:
```
Authorization: Bearer {jwt}
access_token:  {jwt}
Origin:        https://www.newworld.co.nz
Referer:       https://www.newworld.co.nz/
```

**Required cookies for per-store pricing**:
```
eCom_STORE_ID: {store_id}
STORE_ID_V2:   {store_id}|False
Region:        NI (or SI)
```

**Request payload**:
```json
{
  "algoliaQuery": {"query": "milk"},
  "page": 0,
  "hitsPerPage": 20,
  "storeId": "{store_id}",
  "sortOrder": "PRICE_ASC"
}
```

**Valid sortOrder**: `PRICE_ASC`, `PRICE_DESC`

**Price extraction**:
- Regular: `singlePrice.price` (cents)
- Promo: `promotions[].rewardValue` where `bestPromotion: true` (cents)

### Categories
`GET /v1/edge/store/{store_id}/categories` — Returns category tree.

### Relevance Matching
**Algolia Index Endpoint**: `POST /v1/edge/search/products/query/index/products-index`

This is the **DEFAULT Algolia index** (relevance-sorted). Returns hits with `_highlightResult` containing `matchedWords` — explicit relevance matching!

```json
{
  "algoliaQuery": {"query": "beef mince"},
  "page": 0,
  "hitsPerPage": 20,
  "storeId": "{store_id}"
}
```

Response includes `_highlightResult`:
```json
{
  "_highlightResult": {
    "DisplayName": {"value": "NZ Premium <em>Beef</em> <em>Mince</em>", "matchedWords": ["beef", "mince"]},
    "category2AndBrand": {"value": "Beef <em>Mince</em> > Premium", "matchedWords": ["beef", "mince"]}
  }
}
```

All three indices (`products-index`, `products-index-popularity-asc`, `products-index-popularity-desc`) have identical `_highlightResult.matchedWords` — the only difference is sort order. `products-index` (relevance-sorted) is preferred for the two-pass pipeline since top hits match the query best.

### Two-Pass Pipeline

**Problem**: Paginated endpoint has per-store pricing but NO relevance sort. Algolia index has relevance but NO per-store pricing.

**Solution**: Two-pass pipeline using Algolia filter syntax:

```
PASS 1 (Relevance): POST /search/products/query/index/products-index
  → Returns hits with _highlightResult.matchedWords
  → Extract productID where matchedWords not empty

PASS 2 (Pricing): POST /search/paginated/products with filters
  → Filters: "productID:5101189-KGM-000 OR productID:5104350-KGM-000 ..."
  → Returns per-store singlePrice.price + promotions[].rewardValue
  → Sort: PRICE_ASC (cheapest at this store)
```

**Results for "beef mince" at Metro Auckland**:
- Pass 1: 40 hits, 40 with relevance matches
- Pass 2: 3 products with per-store pricing: $9.49, $13.49, $26.99

**Advantage over Mobile API**: Explicit relevance matching via `_highlightResult` (mobile API returns first result but no visibility into WHY it matched). Critical for ingredient search — avoids pet food matching "beef mince".

### Conclusion
**The Edge API CAN replace the mobile API** for New World:
- No dependency on mobile API endpoint
- Works with website JWT (more future-proof, same IdP: `online-customer`)
- Algolia search with explicit relevance matching + price sorting
- Per-store pricing via cookies + Algolia filters
- Promotional pricing included
- Categories endpoint available for navigation

See `exploration/newworld/` (`explore_edge_api*.py`, `check_two_pass_milk_metro.py`, `demo_geographic_price_compare.py`, `demo_full_optimiser_single_pass.py`) for working implementations.

## 28. New World store-finder page `__NEXT_DATA__` for URL slugs only

The New World store-finder page (`https://www.newworld.co.nz/store-finder`) `__NEXT_DATA__` JSON provides URL slugs for 150 stores. The JSON path is `data.props.pageProps.page.page_content.content_blocks[1].store_finder.regionStoreGroupings` → `northIsland`/`southIsland` → `groups` → `stores`. Each store has `title`, `url`, and `address`. This is used as a secondary data source to add URL slugs to the mobile API data (which provides coordinates and store IDs but no URLs).

## 29. Accept 7 New World stores without URLs

7 stores have name mismatches between the mobile API and the store-finder page (e.g., "Metro Auckland" vs "Metro Queen Street", macron differences for Tūrangi/Wanaka). Fuzzy string matching could resolve these but is not needed — URLs are only for linking to the website, not for the API-based optimiser. The 142 stores with URLs are sufficient.

## 30. New World `DISHES` dict reuses Pak'nSave's

The 21 dishes and their ingredient lists (now in dict format with quantity/unit/search_term) are identical between Pak'nSave and New World (both are NZ supermarkets with similar product ranges). The `DISHES` dict in `src/NZMealOptimiser/pricing/optimiser_utils.py` is shared by both — no duplicate definitions needed.

## 31. Playwright not needed for New World at runtime

The Foodstuffs mobile API provides all store data (coordinates, IDs, banner) without any browser automation. Product search will use `GET /mobile/ecomm-products/MNW/{store_id}/search?q={query}` — same pattern as Pak'nSave. No Playwright needed for any New World operation, consistent with the Woolworths approach.

## 32. Edge API Two-Pass Pipeline is the Recommended Production Path for New World

The two-pass pipeline on the Edge API is now the **recommended production architecture** for New World, superseding the mobile API approach:

| Aspect | Mobile API | Edge API (Two-Pass) |
|--------|------------|---------------------|
| Relevance matching | Implicit (first result) | Explicit `_highlightResult.matchedWords` |
| Per-store pricing | Native (storeId in URL) | Via cookies + Algolia filters |
| Price sorting | PriceAsc (limited) | PRICE_ASC, PRICE_DESC |
| Promotions | Included | Included |
| Auth | Mobile guest token | Website JWT OR mobile token |
| Dependency | Internal Foodstuffs API | Public website API (more stable) |
| Implementation complexity | Low | Medium (two passes) |
| Visibility into matches | None | Full (see matched fields) |

**Decision**: Use Edge API two-pass pipeline for new development. Keep mobile API as fallback. Update `NewWorld_prototype.py` to use Edge API in next iteration.

## 33. Pak'nSave Edge API Two-Pass Pipeline is the Recommended Production Path

The two-pass pipeline on the Edge API is now the **recommended production architecture** for Pak'nSave, superseding the mobile API approach — identical to New World:

| Aspect | Mobile API | Edge API (Two-Pass) |
|--------|------------|---------------------|
| Relevance matching | Implicit (first result) | Explicit `_highlightResult.matchedWords` |
| Per-store pricing | Native (storeId in URL) | Via cookies + Algolia filters |
| Price sorting | PriceAsc (limited) | PRICE_ASC, PRICE_DESC |
| Promotions | Included | Included |
| Auth | Mobile guest token | Website JWT OR mobile token |
| Dependency | Internal Foodstuffs API | Public website API (more stable) |
| Implementation complexity | Low | Medium (two passes) |
| Visibility into matches | None | Full (see matched fields) |
| Pet food filtering | Not available | Via `category1` in Pass 1 |

**Decision**: Use Edge API two-pass pipeline for new development. Keep mobile API as fallback. Update `PaknSave_prototype.py` to use Edge API in next iteration.

**Implementation**: `exploration/paknsave/demo_two_pass_pipeline.py` (full demo), `tools/paknsave/paknsave_optimiser_edge.py` (CLI optimiser)

## 34. Pet Food Filtering via `category1` Field

The Algolia relevance search returns pet food items (dog food, cat food) for queries like "beef mince" because the product names contain the search terms. The `category1` field in the Pass 1 response allows filtering out these items:

```python
pet_categories = {"Dog", "Cat", "Pet"}
product_ids = []
for hit in hits:
    hr = hit.get("_highlightResult", {})
    matched = [f for f, v in hr.items() if isinstance(v, dict) and v.get("matchedWords")]
    cat1 = hit.get("category1", [])
    if matched and not any(c in pet_categories for c in cat1):
        product_ids.append(hit["productID"])
```

**Decision**: Always filter by `category1` in Pass 1 to exclude pet food. This reduces relevance results but ensures only human food products are passed to Pass 2 for pricing.

**Verified**: Testing "beef mince" at PAK'nSAVE Botany — 40 hits reduced to 37 after filtering. Pet food items ("Indulge Beef Mince In Gravy Dog Food", "Mince With Beef In Gravy Cat Food") successfully excluded.

## 35. Region Cookie for South Island Stores

The `Region` cookie in the Edge API determines which store's price list is returned:
- `Region: "NI"` — North Island stores
- `Region: "SI"` — South Island stores

**Decision**: Use `Region: "NI"` for North Island stores (default) and `Region: "SI"` for South Island stores. This is determined by the store's `region` field from the store listing response.

**Note**: The mobile API does not require this cookie — it uses the store ID in the URL path to determine the region automatically. The Edge API requires explicit region context via cookies.

## 36. Edge API Returns 57 Stores vs Mobile API's 60

The Pak'nSave Edge API (`GET /v1/edge/store`) returns 57 stores, while the mobile API (`GET /mobile/store/physical`) returns 60 stores. The 3 missing stores are:

| Store Name | Store ID | City | Region | Coordinates |
|------------|----------|------|--------|-------------|
| **Wairau Road** | `002b83de-b79d-4228-a787-bd0765b6cb56` | Glenfield, Auckland | NI | -36.7789, 174.7440 |
| **Gisborne City** | `26c9c8bd-b7d8-4551-9fb0-350b829740a1` | Gisborne | NI | -38.6642, 178.0210 |
| **Levin** | `90302a32-84f3-492a-8c9a-10f5242c0448` | Levin | NI | -40.6226, 175.2877 |

**Testing**: All 3 stores return 0 products in Pass 2 (per-store pricing) despite having relevance matches in Pass 1. This confirms these stores are not configured for online ordering via the Edge API.

**Decision**: Use the Edge API store listing as the primary source (57 stores). The mobile API can be used as a fallback if more stores are needed. The 57 stores cover all major Pak'nSave locations nationwide.

**Note**: This is similar to the New World discrepancy (148 Edge API stores vs 149 mobile API stores).

**See also**: Log 34 in logs.md for verification details.

## 37. Cross-Brand API Comparison (Pak'nSave vs New World vs Woolworths)

| Feature | Pak'nSave | New World | Woolworths |
|---------|-----------|-----------|------------|
| Auth | Bearer token (guest login) | Bearer token (guest login) | Session cookies (no login) |
| Token/ session expiry | 30 min (auto-refreshable) | 30 min (auto-refreshable) | Indefinite (observed weeks) |
| Per-store pricing | Native (store ID in URL) | Native (store ID in URL) | Cookie injection (`cw-lrkswrdjp`) |
| Fresh session per store | Not required | Not required | Required (server resets cookies) |
| Product search | `POST` with JSON body | `POST` with JSON body | `GET` with query params |
| Prices in | Cents (integer) | Cents (integer) | Dollars (float) |
| Cloudflare | API: none, Website: Cloudflare | API: none, Website: Cloudflare | No Cloudflare on API |
| Store count | 60 (mobile) / 57 (Edge) | 149 (mobile) / 148 (Edge) | 183 (Woolworths NZ) |
| Auth complexity | Low (2 POST calls) | Low (2 POST calls) | Medium (cookie construction) |
| Banner value | `"PNS"` | `"MNW"` | N/A |
| User-Agent | `PAKnSAVEApp/4.32.0` | `NewWorldApp/4.32.0` | N/A |
| Relevance matching (mobile) | Implicit (first result) | Implicit (first result) | First result (no highlight) |
| Relevance matching (Edge) | Explicit `_highlightResult.matchedWords` | Explicit `_highlightResult.matchedWords` | N/A |
| Price sorting (mobile) | PriceAsc | PriceAsc | Not available |
| Price sorting (Edge) | PRICE_ASC, PRICE_DESC | PRICE_ASC, PRICE_DESC | Not applicable |
| Edge API two-pass pipeline | [OK] Working | [OK] Working | Not applicable |
| Pet food filtering | Via `category1` in Pass 1 | Via `category1` in Pass 1 | Not available |

The Edge API two-pass pipeline on both Pak'nSave and New World is the recommended production path. See decisions #32 and #33 for details.

---

## 38. Why the Mobile API is Preferred Over Website CommonApi

The Pak'nSave website at `www.paknsave.co.nz` exposes legacy `CommonApi` endpoints (website-only, require authenticated browser sessions, inconsistent JSON shapes). The project uses the Foodstuffs mobile API instead because:

1. **No session cookies required** — mobile API uses simple bearer token
2. **Consistent JSON format** — CommonApi responses vary by endpoint
3. **Per-store pricing** — mobile API returns prices per-store natively
4. **More data per product** — mobile API returns `productImageUrls`, `unitPrice`, `algoliaAnalytics`, `brand`, `availableInOnline`, flag fields

The specific CommonApi endpoints that were removed from `PaknSave_API.md` (no longer used by project code):

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/CommonApi/Store/GetStoreList` | POST | Returns store list with basic info |
| `/CommonApi/Store/ChangeStore?storeId={id}&clickSource=list` | POST | Sets store session cookie |
| `/CommonApi/Navigation/MegaMenu?v=&storeId={id}` | GET | Category navigation tree |
| `/CommonApi/Cart/Index` | GET | Cart state (requires authenticated session) |
| `/CommonApi/Product/GetBannerAd` | POST | Banner advertisements |
| `/CommonApi/Checkout/GetPreviousProductPurchases` | GET | Previous purchases |
| `/CommonApi/Checkout/GetAisleOfValueProducts` | GET | Aisle-of-value deals |
| `/CommonApi/Delivery/GetStoreCollectionPoints?id={id}` | GET | Collection point details |
| `/CommonApi/ShoppingLists/GetLists` | GET | Shopping lists |

## 39. Retire `pickupAddressId` (extra2) indirection for Woolworths

Historically the Woolworths optimiser resolved `extra1` (fulfilmentStoreId) from the
`extra2` (pickupAddressId) returned by `/api/v1/addresses/pickup-addresses`, via a
lookup table (`get_store_mapping()`, built from `woolworths_store_data.json`).

This indirection is **retired**. Store identity now keys directly on `extra1`
(fulfilmentStoreId) everywhere in the Woolworths pipeline:

- `woolworths_setup.fetch_store_data()` builds `data/woolworths_stores.csv` directly from
  CDX (`woolworths_store_data.json`), keyed on `id=extra1` (with `name, address,
  latitude, longitude`). The legacy `woolworths_store_choices.csv` (pickup-addresses
  API, keyed on extra2) is no longer consulted for store identity.
- `woolworths_api.get_nearby_stores()` reads `woolworths_stores.csv` and returns
  `store_id=extra1`. No extra2→extra1 lookup occurs.
- `woolworths_api.set_store_context(session, fulfilment_store_id)` takes extra1
  directly and builds the `cw-lrkswrdjp` cookie as `dm-Pickup,f-{extra1},s-38`.
- `optimiser_utils.woolworths_querier()` and `build_woolworths_row()` write
  `store_id=extra1` to `full_results.csv`.

`get_store_mapping()` and `_load_store_mapping()` have been **removed** from
`woolworths_api.py`. The `woolworths_search_demo.py` legacy mapping flow was also
removed (its `load_store_mapping()` function deleted). `fetch_store_choices()`
remains in `woolworths_setup.py`, marked legacy in its docstring — it still
regenerates `data/woolworths_store_choices.*` on ad-hoc invocation, but is not
called by `fetch_store_data()` or any optimiser code.

See §21 (`extra1` = `fulfilmentStoreId`) for why extra1 is the correct key, and
§22 (fresh session per store) which is unchanged.

## 40. src-layout package + editable install replaces path-bootstrap hacks

The repo was restructured from a scripts-centric layout (with ad-hoc
manual path bootstrap in `core/paths.py`) into an installable
**src-layout Python package**:

```
src/NZMealOptimiser/         # library code (importable everywhere)
├── pricing/                 # optimiser_utils.py, paknsave_api.py, newworld_api.py, woolworths_api.py
├── llm/                     # llm_client.py, llm_utils.py
└── web/                     # FastAPI app (main.py, config.py) + static/frontend
tools/                       # CLI layer (optimisers, setup, llm_validate, llm_interactive)
tests/                       # all test suites + fixtures
exploration/                 # Exploration scripts per brand
```

**Rationale:**
- Removal of path-bootstrap fragility — no manual path mutations, no
  import-time side effects from a retired `core/paths` module.
- A single `DATA_DIR` / `PROJECT_ROOT` contract, resolved once in
  `src/NZMealOptimiser/__init__.py`.
- Docker / CI simplicity — `gcloud run deploy --source .` with the Dockerfile
  at the repo root; `pip install -e .` for local dev.
- Package imports everywhere — `from NZMealOptimiser.pricing.optimiser_utils
  import ...` works from any module.

**Decision:** Install editable (`pip install -e .`, dev extras via
`pip install -e ".[dev]"`) and run CLIs via `python -m tools.<brand>.<module>`.
`tools/` is the CLI layer distinct from the `src/NZMealOptimiser/` library —
optimisers/setup/validation scripts thin-wrap the shared library helpers.

## 41. FastAPI app-shell consolidation (2026-08)

During the FastAPI app-shell build-out (the rewrite that introduced `/` + `/test` Vue trees + job-based `POST /optimise/jobs`), the following were deliberately removed from `main.py`:

- `workers/` folder — queueing system for serialized processing (sessions are now isolated naturally via fresh `requests.Session()` per call).
- `services/supabase_client.py` — Supabase write client (persistence is optional, can be re-added later).
- `seed_phase1.py`, `schema_phase1.sql` — database seeding files (we start with local storage).
- `models/` folder — Pydantic models (consolidated into `main.py`).
- `routes/` folder — separate route files (consolidated to single `main.py`).
- Custom price extraction — replaced with `build_edge_row` / `build_woolworths_row` to reuse the existing row format.
- "Best price per ingredient" logic — removed; the API now returns ALL product results, with quantity-scaled "used cost" computed via `parse_optimiser_columns`.

Context: the original docs (pre-rewrite) had been describing these as active modules. After consolidation, the listed items should not appear in any current `src/` or `tools/` tree — this entry exists so future readers don't try to re-add them.

## 42. Live-adjustable search thread pool (Settings slider, 2026-09)

The search thread pool was previously sized once at import time from `WEB_MAX_WORKERS` and required a server restart to change. Decision #42 replaces that with a live-adjustable slider exposed in the Settings → Advanced card.

**Architecture — `_ResizableThreadPool` wrapper:** `ThreadPoolExecutor` cannot be resized in place, so the underlying executor is wrapped in a small class that holds a `threading.Lock` and a single mutable reference. `set_max_workers(n)` builds a new executor under the lock, swaps the reference, drains the old one with `shutdown(wait=False)` outside the lock, and rebinds the asyncio default executor if a loop is running. Reads (`executor`, `max_workers`) take a snapshot of the current reference so callers never see a half-built replacement.

**Size configuration — hardcoded only, no `.env` override:**

| Setting | Source | Range | Edit |
|---|---|---|---|
| Slider bounds | `WORKER_POOL_MIN` / `MAX` / `STEP` (module constants in `main.py`) | 20 / 40 / 5 | Edit + restart |
| Live size | Slider value via `POST /system/thread-pool` | min..max in step multiples | Live |

The bounds are intentionally **not** exposed via `.env`. An earlier design wired `WEB_MAX_WORKERS` as a `.env` ceiling and clamped the slider to `[WORKER_POOL_MIN, min(WORKER_POOL_MAX, WEB_MAX_WORKERS)]`. The Pydantic default for `WEB_MAX_WORKERS` was 20 — the same as the slider min — so an unset `.env` silently clamped the slider to a single point (`min == max == 20`) and made it impossible to drag. The `.env` ceiling was removed so the slider is always 20–40 step 5 out of the box. If you ever need a different range, edit the constants in `main.py` and restart.

**Running-jobs gate (409 path):** The swap is refused with HTTP 409 if any `JobState.status == "running"` exists in `JOBS`. Rationale: an in-flight executor swap *can* strand a future on a draining executor (we use `shutdown(wait=False)` by design so the swap is fast). With the gate, the drain is a no-op guarantee rather than a race. The Settings page polls `GET /system/running-jobs` every 2 s so the Apply button auto-disables while a job is running and auto-re-enables when it finishes.

**UX choices:**
- Slider value is a `v-model` local preview, **not** auto-applied on `change`. The user has to hit an explicit "Apply N workers" button so dragging doesn't thrash the pool.
- Success state shows a green ✓ chip that auto-fades after 4 s.
- Failure (400/409) shows a red `mode-note` and resets the slider to the live pool size.
- One pool, three brands — no per-brand knob. Past 40 the supermarkets' own rate limits become the bottleneck, which is why the slider tops out at 40.

**Why not a per-job concurrency cap instead:** a single shared pool is simpler, doesn't require threading a knob through every `optimise/jobs` payload, and is the right knob for "this server feels slow" — the actual symptom.

## 43. Photon for address autocomplete + reverse-geocode (2026-09)

The dashboard's address field was a plain `<input>` with a `<datalist>` fed by the user's last 5 typed addresses; rural addresses got the wrong first hit, long queries needed full keystrokes, and there was no way to pick a location from the map.

**Why Photon over Nominatim for browser-facing geocoding:**
- **Nominatim's [usage policy](https://operations.osmfoundation.org/policies/nominatim/) explicitly bans browser autocomplete** and rate-limits to 1 req/sec. We respect this on the forward-lookup path (`/geocode` — 1.1s sleep in `optimiser_utils.geocode()`), but a per-keystroke dropdown would violate TOS and likely get the server IP blocked.
- **Photon** (`photon.komoot.io`) is the only free, no-API-key, no-credit-card, OSM-based geocoder built for search-as-you-type. Same OSM planet data, autocomplete-first indexing, "fair use" throttling on the public demo.
- All commercial options (Mapbox, Google Places, HERE, Geoapify, OpenCage production, geocode.maps.co) require either a credit-card signup or restrictive attribution. **The user explicitly doesn't want to pay** so those are off the table.
- Self-hosting Photon/Pelias with the LINZ NZ address dump is the long-term fallback if Photon's demo throttles us (it'd take ~5-10 GB RAM, ~20 GB disk, and ~2M LINZ address points). Not worth the ops cost at current user base.

**Architecture:**
- New endpoints in `main.py`: `GET /geocode/autocomplete` (Photon forward, LRU 200, key = `country|limit|q`) and `GET /geocode/reverse?provider=auto|photon|nominatim` (Photon default, Nominatim opt-in). All three LRUs are independent so cache pollution can't cross them.
- `provider=auto` defaults to Photon because its cache is 4-decimal (~11 m) and the 1.1s sleep isn't needed. The Nominatim path is kept for precision (5-decimal cache, ~1 m) and rural NZ where Photon's labels are sparser.
- New `AddressAutocomplete.vue` (debounced 300 ms, keyboard nav, click-outside dismiss, ✕ clear, ODbL attribution) replaces the `<datalist>`. Photon's selected suggestion's coords are used directly — no second Nominatim round-trip.
- `MapPanel.vue` gains a `pick-origin` event (map background click + origin-pin dragend) and a draggable origin pin with `cursor: grab`. The dashboard's `onPickOrigin()` sets `origin = {lat, lon, source: "picked"}` (third source alongside `'gps'` / `'geocoded'`), then debounce-reverses the coords so the address field gets a real label. A `_suppressAddressReset` counter incremented inside `onPickOrigin` and `onAddressSelect` keeps the address-input watch from wiping the just-set origin.

**Scope:** /test tree only (sandbox). Promotion to prod requires copying `AddressAutocomplete.vue` + the updated `MapPanel.vue` + `DashboardView.vue` from `src/test/components/` to `src/`, then `tools/frontend/promote_test_to_app.ps1` and rebuild.

**License:** Photon's data is ODbL — the dropdown footer must keep the `photon.komoot.io` + `openstreetmap.org/copyright` links.

**Open followup — `/geocode` still on Nominatim (deliberate, not a constraint):** Photon could obviously proxy the same forward-lookup, so why keep `/geocode` on Nominatim? Three reasons, in order of weight:

1. **LRU makes the 1.1 s sleep a one-time cost.** The cache is 200 entries keyed on lowercased address. The first cold-cache submit for a given address pays the 1.1 s, every subsequent submit hits the cache and is instant. Photon's "no sleep" only matters on the *first* submit per address per session — a one-shot cost, not per-keystroke.
2. **The "Resolve setup" submit is the authoritative one.** The autocomplete dropdown has already validated the address when the user picked a suggestion (Photon-sourced coords are in hand). The fallback case (user types a full address, doesn't pick a suggestion, clicks submit) is the one that actually calls `/geocode` — and for that case we want the most precise single-result label we can get. Nominatim's `display_name` strings are marginally fuller than Photon's, and its search index is tuned for exact-match rather than prefix-match.
3. **Separation of concerns as a feature.** Photon = "exploration" (keystroke search, map-pin reverse), Nominatim = "submission" (one deliberate click). If Photon's demo ever throttles or goes down, `/geocode` is unaffected and the user can still resolve an address by typing the full string. The reverse is also true: if Nominatim has an outage, autocomplete and map-pick still work.

**Migration path if the trade-off ever flips** (e.g. Nominatim uptime degrades, or we want to drop the 1.1 s entirely for UX):
- Swap `/geocode` to proxy Photon (drop the `time.sleep(1.1)` in the call path; LRU + NZ bbox guard stay). Single endpoint, two lines of code.
- Nominatim stays available as `provider=nominatim` on `/geocode/reverse` for the precision case.
- Watch the first-submit UX change: cold-cache addresses go from ~1.1 s to ~0.2 s, which on slow rural connections is the difference between a perceptible pause and a snappy form.

