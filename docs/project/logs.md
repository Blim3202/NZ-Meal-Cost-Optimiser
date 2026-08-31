# Major Errors & Resolutions

## 1. Loose Garlic pricing ($40+/kg)

**Symptom**: Searching "garlic" returns "Loose Garlic" priced at $39.99/kg, making a single bulb appear extremely expensive.

**Cause**: The API returns per-kg pricing for loose items. The first result is loose garlic, not pre-packaged crushed garlic.

**Resolution**: Accept that some items have misleading per-kg pricing. The crushed garlic jar ($2.29) is a more practical result and sometimes appears instead. This is a known limitation.

## 2. PAKnSAVE store slug matching failures

**Symptom**: Some stores didn't match between the store-finder page slugs and the `__NEXT_DATA__` GUIDs.

**Cause**: Slug generation from store names doesn't always match the URL slugs on the website (e.g., apostrophes, "MINI" prefix, "-city" suffix).

**Resolution**: Hardcoded fallback mappings in `fetch_stores.py` for known mismatches (e.g., Henderson → "alderman-drive-henderson"). Not fully automated — manual verification needed for new stores.

## 3. Nominatim geocoding returning None

**Symptom**: `geocode()` returns `(None, None)` for some addresses.

**Cause**: Nominatim doesn't recognize the address format, or the address is too vague.

**Resolution**: The `fetch_stores.py` script has a fallback that tries `"Pak'nSave {name}, New Zealand"` as an alternative query. For user addresses, they need to provide a recognizable NZ address.

## 4. Woolworths `/api/v1/sites` and sibling endpoints return 404

**Symptom**: Attempted to enumerate Woolworths NZ stores via `/api/v1/sites`, `/api/v1/stores`, and `/api/store-finder`. All returned 404 or empty responses.

**Cause**: The Angular SPA store-finder is JavaScript-rendered; no public JSON API exists for a full store list.

**Resolution**: Abandoned public API enumeration. Switched to OpenStreetMap/Nominatim as store location source. Succeeded by Log 10 (Woolworths API Discovery).

## 5. Initial Woolworths keyword search insufficient

**Symptom**: Initial nationwide-only keyword queries (`Woolworths New Zealand`, `Countdown New Zealand`, etc.) returned ~50 stores, well below the expected ~180 NZ stores.

**Cause**: Many OSM entries are only tagged with local-area names and don't surface under broad national keywords.

**Resolution**: We are no longer using Nominatim for Woolworths store locations. Instead, we have extracted all (pickup location) stores through inspecting the HTML elements. This approach provides complete coverage of all NZ Woolworths stores. Succeeded by Log 10 (Woolworths API Discovery).

## 6. Woolworths store-finder URL pattern not yet integrated

**Symptom**: Internal numeric store IDs are visible in the Angular SPA store-finder URL pattern (`/store-finder/{id}/{city}/{slug}`), but there is no public API to map these to coordinates or names.

**Cause**: Internal IDs are client-side routing only; no JSON endpoint exposes the mapping.

**Resolution**: We are no longer using Nominatim for Woolworths store locations. Instead, we have extracted all (pickup location) stores through inspecting the HTML elements. This approach provides complete coverage of all NZ Woolworths stores. Succeeded by Log 10 (Woolworths API Discovery).

## 7. Woolworths direct product search API unusable (`400 Header is missing or is invalid.`)

**Symptom**: Calling `GET /api/v1/products?target=search&search=milk&inStockProductsOnly=false&size=24` from both outside the browser and via Playwright's `page.request` returns HTTP 400 with `{"message":"One or more errors occurred","errors":[{"field":"Header","message":"Header is missing or is invalid."}]}`.

**Cause**: The endpoint requires a non-empty `x-requested-with` header (any string, including `??` or `XMLHttpRequest`). The original testing omitted this header entirely, causing the 400. A single `GET /` to seed cookies is also sufficient — no Playwright session or authenticated state is needed.

**Resolution**: The API is fully functional with `requests.Session` when the `x-requested-with: ??` header is included. Playwright is NOT needed at runtime for any API operation. Per-store pricing is achieved via `cw-lrkswrdjp` cookie injection (see Log #16). Full endpoint documentation in `Woolworths_API.md`.

## 8. Headless Playwright blocked on Woolworths (`ERR_HTTP2_PROTOCOL_ERROR`)

**Symptom**: Running `page.goto("https://www.woolworths.co.nz/")` with `headless=True` and `--disable-blink-features=AutomationControlled` raised `net::ERR_HTTP2_PROTOCOL_ERROR`.

**Cause**: Site/Akamai blocks headless/automation fingerprints despite standard disguise arguments.

**Resolution**: Use headed mode with `headless=False` and standard user-agent/locale/timezone settings. Search and DOM extraction work reliably in this configuration.

## 9. Successful Woolworths Store Identification via Manual HTML Inspection

**Symptom**: Needed to obtain comprehensive Woolworths store locations for NZ to enable per-store pricing queries.

**Cause**: Previous Nominatim/OSM approach via stores_fetch.py was incomplete and required automation that wasn't yet implemented. Manual inspection approach was needed to identify all store locations.

**Resolution**: Successfully inspected Woolworths website HTML to identify all store locations. Determined that stores_fetch.py and woolworths_stores.csv can be deleted pending implementation of proper HTML element selection for automation. Successfully navigated to the store selection dropdown on the Woolworths website, ready to implement store selection functionality. Succeeded by Log 10 (Woolworths API Discovery).

## 10. Successful Woolworths Store Identification via API

**Symptom**: Needed a reliable, automated way to obtain comprehensive Woolworths store locations for NZ to enable per-store pricing queries.

**Cause**: Previous Nominatim/OSM approach was incomplete, and manual HTML inspection was unsustainable.

**Resolution**: Discovered the public Woolworths site-location API (`https://api.cdx.nz/site-location/api/v1/sites`). Implemented `scripts/woolworths/Extract_woolworths_API_JSON.py` to fetch, parse, and save this data to `data/woolworths_stores_API.json` and `data/woolworths_stores.csv`.

## 11. Breakthrough in Woolworths Store Identification and Data Joining

**Symptom**: Previous name-matching approach was unreliable for selecting stores within the dropdown.

**Cause**: Store names in dropdown choices didn't consistently match location API names.

**Resolution**: Successfully discovered that both datasets contain a common ID. Created `Get_woolworths_API_data.py`, `Get_woolworths_store_choices.py`, and `Merge_woolworths_stores.py` to fetch both sets and merge them into `data/woolworths_stores.csv`. This enables reliable store selection by ID.

## 12. Successful Automated Store Selection via URL

**Symptom**: Need reliable automated store selection to ensure pricing data reflects the correct user location.

**Cause**: Previous approaches (complex dropdown interactions) were fragile.

**Resolution**: Implemented `scripts/woolworths/ChangeStore.py` (now `exploration/woolworths/Playwright/demo_woolworths_change_store.py`) using direct navigation to the Woolworths store selection modal URL (`/bookatimeslot/(hww-modal:change-pick-up-store)`), which reliably allows programmatically setting the store context.

## 13. Jupyter `NotImplementedError` on Windows
**Symptom**: Playwright `async_playwright` failed in Jupyter notebook on Windows with `NotImplementedError` regarding subprocesses.
**Resolution**: Refactored the pipeline to offload the scraping to a standalone script (`scripts/woolworths/woolworths_optimiser.py`), triggered via `subprocess.Popen` from the notebook.

## 14. `FileNotFoundError` in Sub-modules
**Symptom**: `data/woolworths_stores.csv` wasn't found when running scripts via `subprocess` because the script CWD was different from the notebook CWD.
**Resolution**: Implemented robust absolute path construction in `woolworths_optimiser.py` using `os.path.abspath(os.path.dirname(__file__))`.

## 15. Woolworths API Exploration — Full `/api/v1` Surface Discovery

**Symptom**: Needed to determine if the Woolworths JSON API (`/api/v1/products`) could replace the Playwright DOM scraping layer for product price retrieval.

**Cause**: Previous testing (log #7) had concluded the API was unusable, but had not tested with the correct header or with a seeded session.

**Resolution**: Built `scripts/woolworths/explore_woolworths_api.py` and performed systematic black-box probing of the `/api/v1` surface. Key findings:
- `GET /api/v1/products?target=search` returns real product data with prices, just by seeding cookies with a single `GET /` — no login or Playwright required.
- `GET /api/v1/shell` returns the full navigation taxonomy and `context.fulfilment` object (default store: `fulfilmentStoreId: 9171`).
- `GET /api/v1/addresses/pickup-addresses` returns all pickup stores (only `id`, `name`, `address` keys — no bridge to lat/lon).
- `target=browse` with `dasFilter=Department;;<slug>;false` works for department-level filtering (14 departments, 100+ aisles mapped).
- Aisle-level `dasFilter` chaining is accepted but does not seem to narrow results.
- `fulfilmentStoreId`, `pickupStoreId`, and 9 other store-context parameters all return HTTP 200 but **do not change prices** — pricing appeared global at this stage.
- 19 POST store-switch endpoints all return 404 — no API path exists for programmatic store context changes.
- Full documentation written to `Woolworths_API.md`.

**Update**: Per-store pricing was later discovered via `cw-lrkswrdjp` cookie injection (see Logs #16-#20). The query-parameter approach was a dead end, but the cookie approach works.

## 16. Playwright Cookie Injection Produces Per-Store Pricing

**Symptom**: Needed to determine if per-store pricing exists at all, or if Woolworths truly uses a global price list.

**Cause**: Previous testing (Log #15) only tested query parameters, not cookie-based store context. The `cw-lrkswrdjp` cookie carries store context but was not tested.

**Resolution**: Built `explore_woolworths_api_part2.py`. Captured full Playwright cookie jars for Greymouth and Glenfield after selecting each store in the change-pick-up-store modal. Injected the full 67-cookie jar into `requests.Session` via `session.cookies.set()`. Searched "milk" at both stores:
- Greymouth: Woolworths Milk Standard 3L = **$7.15** [OK]
- Glenfield: Woolworths Milk Standard 3L = **$7.33** [OK]
- Price difference: $0.18 confirmed

Also tested URL-param seeding (`?pickupStoreId=764300`), session_state-only injection, and RT-only injection — all failed. Only the full cookie jar (or the `cw-lrkswrdjp` cookie specifically) works.

## 17. `cw-lrkswrdjp` Is the Sole Per-Store Cookie

**Symptom**: Needed to determine which of the 67 Playwright cookies controls store context, to avoid depending on the full jar.

**Cause**: The full 67-cookie jar works, but capturing and injecting all cookies is fragile and complex. Identifying the single required cookie would simplify the architecture.

**Resolution**: Built `explore_woolworths_api_part3.py`. Systematically isolated cookies:
- Injecting only `session_state` (Optimizely): both stores return $7.33 (wrong) [FAIL]
- Injecting only `RT` (Adobe Analytics): both stores return $7.33 (wrong) [FAIL]
- Injecting only `cw-lrkswrdjp`: both stores return correct prices ($7.15 / $7.33) [OK]

The `cw-lrkswrdjp` cookie format is `dm-Pickup,f-{fulfilmentStoreId},a-{areaId},s-{site}`. The `a-` and `s-` fields are optional — `dm-Pickup,f-{fulfilmentStoreId}` alone works.

## 18. Cookie Construction from `extra1` — No Playwright Needed

**Symptom**: Needed a way to construct `cw-lrkswrdjp` cookies for all 183 stores without running Playwright for each one.

**Cause**: The `fulfilmentStoreId` used in the cookie is NOT the same as `pickupAddressId` (the public store ID). These are different numbers with no formulaic relationship. Without a mapping, Playwright would be needed to capture each store's `fulfilmentStoreId`.

**Resolution**: Discovered that `extra1` in `woolworths_store_data.json` (fetched from CDX store locator API) IS the `fulfilmentStoreId`. Verified across 3 stores:
- Greymouth: extra1=9009, cookie f-field=9009 [OK]
- Glenfield: extra1=9443, cookie f-field=9443 [OK]
- Birkenhead: extra1=9101, cookie f-field=9101 [OK]

Cookie construction: `dm-Pickup,f-{extra1},s-38`. This works for all 183 stores without any Playwright.

## 19. Fresh Session Per Store Required

**Symptom**: When testing the cookie injection across multiple Auckland stores, all stores returned the same `fulfilmentStoreId` (9250) instead of their individual IDs.

**Cause**: The server's `Set-Cookie` response from `GET /` includes a `cw-lrkswrdjp` cookie with the default store. When `session.cookies.set()` is called to inject a different value, the next request triggers the server to overwrite it with its own value. The injected cookie is effectively ignored on reused sessions.

**Resolution**: Create a fresh `requests.Session` for each store. Each session gets its own `GET /` to seed cookies, then the `cw-lrkswrdjp` is injected before the server can overwrite it. Tested with 5 Auckland stores — all returned correct unique `fulfilmentStoreId`s (9250, 9045, 9500, 9405, 9544). Implemented in `woolworths_optimiser.py`.

## 20. End-to-End Optimiser Test — Per-Store Pricing Working

**Symptom**: Needed to verify the complete pipeline works: geocode, find stores, inject cookies, search products, compare costs.

**Cause**: After building `woolworths_api.py` and refactoring `woolworths_optimiser.py`, needed end-to-end validation.

**Resolution**: Ran optimiser with "123 Queen Street, Auckland CBD" and "spaghetti bolognese":
- Found 9 stores within 5 km with unique fulfilmentStoreIds
- Searched 7 ingredients at each store (63 API calls total)
- Per-store price differences visible:
  - Garlic: $2.50 (Newmarket) to $2.70 (most stores) — different products at different prices
  - Total cost: Newmarket $18.60 (cheapest), most others $18.80
  - Pipeline working: geocode → nearby stores → fresh session per store → cookie injection → product search → cost comparison
  - No Playwright needed at runtime — pure `requests` + constructed cookies

## 21. New World store-finder page `__NEXT_DATA__` structure changed

**Symptom**: The `fetch_stores.py` script for New World couldn't find `store_finder.regionStoreGroupings` in the `__NEXT_DATA__` JSON.

**Cause**: The `__NEXT_DATA__` structure changed from Pak'nSave's layout. New World's store-finder nests `store_finder` inside `page.page_content.content_blocks[1]` instead of at the top level of `pageProps`.

**Resolution**: Updated the JSON path to `data.props.pageProps.page.page_content.content_blocks[1].store_finder.regionStoreGroupings`. Verified the structure has `northIsland` and `southIsland` keys, each containing `groups` with `stores` arrays (each store has `title`, `url`, `address`).

## 22. New World Edge API — store listing works with mobile token, NO product search

**Symptom**: `GET https://api-prod.newworld.co.nz/v1/edge/store/physical` returned HTTP 401 with `{"fault":{"faultstring":"Failed to Resolve Variable : policy(JWT-VerifyRetailEdgeToken) variable(null)"}}` when tested without proper authentication.

**Cause**: The Edge API is behind an Apigee gateway with a `JWT-VerifyRetailEdgeToken` policy that validates JWT tokens. The error occurs when no valid JWT is provided.

**Discovery**: The Foodstuffs mobile API guest token (a JWT from `online-customer` IdP) **is accepted by the Edge API** when both headers are provided:
- `Authorization: Bearer {token}`
- `access_token: {token}`

The mobile token works because both APIs share the same IdP (`iss: "online-customer"`).

**However**: The Edge API has **NO product search endpoints** — all tested endpoints return 404:
- `/v1/edge/products/search`, `/v1/edge/products`, `/v1/edge/ecomm-products/*`, `/v1/edge/search`, `/v1/edge/categories`

**Resolution**: The Edge API cannot replace the mobile API for the meal cost optimiser. Store listing works, but product search (essential for per-store pricing) does not exist. Continue using the Foodstuffs mobile API (`api-prod.prod.fsniwaikato.kiwi/prod`) for all New World operations.

**Exploration scripts**: `exploration/newworld/explore_edge_api1.py` through `explore_edge_api5.py`
**Documentation**: `exploration/newworld/Exploration.md`

## 23. New World mobile API requires `NewWorldApp/4.32.0` User-Agent

**Symptom**: The Foodstuffs mobile API worked for Pak'nSave (`banner: "PNS"`) but failed for New World (`banner: "MNW"`) with the same `PAKnSAVEApp/4.32.0` User-Agent.

**Cause**: The mobile API validates the User-Agent against the banner. New World requests require `NewWorldApp/4.32.0` (analogous to `PAKnSAVEApp/4.32.0` for Pak'nSave).

**Resolution**: Used `User-Agent: NewWorldApp/4.32.0` for all New World API requests. Guest login: `POST /mobile/user/login/guest` with `json={"banner": "MNW"}`.

## 24. 22 New World stores missing coordinates via Nominatim

**Symptom**: The initial `fetch_stores.py` used Nominatim geocoding on store-finder page addresses. Of 150 stores, 22 were missing coordinates (Eastridge, Howick, Kumeu, Te Atatu, Victoria Park, Aokautere, Broadway, Foxton, Masterton, Brookfield, Mt Maunganui, Tūrangi, Karori, Newlands, Silverstream, Stokes Valley, Whitby, Bishopdale, Ferry Road, Ilam, Nelson City, Greymouth).

**Cause**: Nominatim could not resolve these addresses — either too vague, non-standard formatting, or missing from OSM data.

**Resolution**: Switched to the Foodstuffs mobile API (`GET /mobile/store/physical`) which provides latitude/longitude directly for all 149 stores. Eliminated the Nominatim geocoding step entirely.

## 25. 7 New World stores missing URLs (name mismatch between API and page)

**Symptom**: After merging mobile API data (149 stores with coordinates/IDs) with store-finder page data (150 stores with URLs), 7 stores had no URL match.

**Cause**: Store names differ between the mobile API and the store-finder page:
- "Foodie Mart" (API) — not on the page (different entity)
- "New World Metro Auckland" (API) vs "Metro Queen Street" (page)
- "New World Metro Willis St" (API) vs "Willis Street Metro" (page)
- "New World Mount Maunganui" (API) vs "Mt Maunganui" (page)
- "New World Shore City" (API) vs "Metro Shore City" (page)
- "New World Turangi" (API) vs "Tūrangi" (page — macron difference)
- "New World Wanaka" (API) vs "Wānaka" (page — macron difference)

**Resolution**: Accepted the 7 missing URLs. URLs are only used for linking to the store page on the website — not needed for the API-based optimiser. Could be fixed with fuzzy string matching (e.g., `fuzzywuzzy`) but is low priority.

## 26. New World store count discrepancy (149 API vs 150 page)

**Symptom**: The mobile API returns 149 stores; the store-finder page lists 150.

**Cause**: "Foodie Mart" (35 Landing Drive, Mangere) appears in the mobile API but not on the store-finder page. It may be a different entity or temporarily excluded from the page.

**Resolution**: Used the mobile API as the authoritative source (149 stores). The extra page store ("Te Atatu") is also not in the API. This store is set to open on 11/08/2026, suggesting that the API is currently filtered out or not populated yet for this store.

## 27. New World Edge API — Product search WORKS (Algolia-based)

**Symptom**: Initial Edge API exploration tested wrong endpoints (`/v1/edge/products/search`, `/v1/edge/ecomm-products/*`, etc.) — all returned 404.

**Discovery**: The website uses a different endpoint for product search:
- `POST /v1/edge/search/paginated/products` — Algolia-powered, returns 200 OK

**Working configuration**:
- **Auth**: Website JWT from `POST /api/user/get-current-user` → cookie `fs-user-token` (also works with mobile API token)
- **Store context**: Cookies `eCom_STORE_ID`, `STORE_ID_V2`, `Region`
- **Payload**: `{"algoliaQuery": {"query": "milk"}, "page": 0, "hitsPerPage": 20, "storeId": "...", "sortOrder": "PRICE_ASC"}`
- **Sort options**: `PRICE_ASC`, `PRICE_DESC`
- **Pricing**: `singlePrice.price` (cents) + `promotions[].rewardValue` (promo cents)

**Price differences confirmed**: Same query returns different prices at different stores (e.g., Standard Milk $4.92 at Te Puke vs $4.92 at Rototuna — for different products; Blue UHT Longlife Milk $1.89 vs $1.69).

**Conclusion**: The Edge API **CAN fully replace the mobile API** for New World:
- No dependency on Foodstuffs mobile API endpoint
- Works with standard website JWT (more future-proof)
- Algolia search with proper price sorting
- Per-store pricing via cookies
- Promotional pricing included

See `exploration/newworld/explore_edge_api6_auth.py`, `demo_geographic_price_compare.py`, `demo_full_optimiser_single_pass.py` for working implementations.

## 28. New World Edge API — Two-Pass Pipeline for Relevance + Per-Store Pricing

**Symptom**: The `/search/paginated/products` endpoint has per-store pricing but NO relevance sort (only `PRICE_ASC`/`PRICE_DESC`, returns 400 for `RELEVANCE`). The Algolia index endpoints (`products-index`, `products-index-popularity-asc/desc`) have relevance matching via `_highlightResult` but only `averagePrice` (cross-store), not per-store pricing.

**Exploration**:
- Tested 14+ Algolia index names via `/search/products/query/index/{index_name}`
- Only 3 indices exist and return 200:
  - `products-index` (default) — **HAS `_highlightResult` with `matchedWords`** — relevance sorted
  - `products-index-popularity-asc` — HAS `_highlightResult` with `matchedWords`, popularity sorted ASC
  - `products-index-popularity-desc` — HAS `_highlightResult` with `matchedWords`, popularity sorted DESC
- All other indices (`price-asc`, `price-desc`, `relevance`, `name-asc`, `name-desc`, `newest`, `bestselling`, `trending`) return 500 (verified 2026-08-04; previously 404)

**Breakthrough**: The paginated endpoint accepts Algolia `filters` parameter! Using `filters: "productID:xxx OR productID:yyy"` allows querying per-store pricing for SPECIFIC product IDs discovered in Pass 1.

**Two-Pass Pipeline**:
```
PASS 1 (Relevance): POST /search/products/query/index/products-index
  → Returns hits with _highlightResult.matchedWords showing exact field matches
  → Extract productID from hits where matchedWords not empty

PASS 2 (Pricing): POST /search/paginated/products with filters
  → Filters: "productID:5101189-KGM-000 OR productID:5104350-KGM-000 ..."
  → Returns per-store singlePrice.price + promotions[].rewardValue
  → Sort: PRICE_ASC (cheapest at this store)
```

**Results**: For "beef mince" at Metro Auckland:
- Pass 1: 40 hits, 40 with relevance matches (DisplayName, category2AndBrand)
- Pass 2: 3 products with per-store pricing: $9.49, $13.49, $26.99 (sorted by price)

**Advantage over Mobile API**: Explicit relevance matching via `_highlightResult` (mobile API returns first result but no visibility into WHY it matched). Superior for ingredient search where we must avoid pet food matching "beef mince".

See `exploration/newworld/explore_edge_api9_relevance.py` (comprehensive) and `check_two_pass_milk_metro.py` (focused test).

## 29. New World Edge API — Full Replacement Confirmed

**Summary**: The Edge API with the two-pass pipeline is now the **recommended production path** for New World:
- Store listing (148 stores via `/v1/edge/store`)
- Relevance matching (Algolia `products-index` with `_highlightResult`)
- Per-store pricing (paginated endpoint with Algolia filters)
- Price sorting (`PRICE_ASC`/`PRICE_DESC`)
- Promotions (`singlePrice.price` + `promotions[].rewardValue`)
- Auth via website JWT (same IdP as mobile, more stable)
- No Foodstuffs mobile API dependency
- Categories endpoint available for navigation

**Documentation**: `NewWorld_API.md` section 6 completely rewritten with full endpoint reference, payloads, and two-pass pipeline implementation.

**Scripts**: `edge_api_relevance_exploration.py`, `test_milk_metro_relevance.py`, `edge_optimiser_demo.py`

## 30. Pak'nSave Edge API — Store Listing Works with Website JWT

**Symptom**: Needed to determine if the Pak'nSave Edge API (`api-prod.paknsave.co.nz`) follows the same pattern as New World Edge API for the two-pass pipeline.

**Discovery**: The Pak'nSave website at `www.paknsave.co.nz` exposes the same Edge API architecture as New World:
- `GET https://api-prod.paknsave.co.nz/v1/edge/store` returns **57 stores** with full metadata (HTTP 200)
- Website JWT obtained via `GET https://www.paknsave.co.nz` → `POST /api/user/get-current-user` → `fs-user-token` cookie
- Same IdP (`online-customer`) as New World and mobile API
- Store context cookies: `eCom_STORE_ID`, `STORE_ID_V2`, `Region`

**Result**: The Edge API is viable for Pak'nSave — same authentication flow, same endpoint patterns.

**Exploration**: F12 Network sources inspected locally via browser developer tools. Found in get-current-user and store api endpoints.

## 31. Pak'nSave Edge API — Algolia Indices Have Relevance Matching

**Symptom**: Needed to confirm that `_highlightResult.matchedWords` exists in Pak'nSave Algolia indices for the two-pass pipeline.

**Discovery**: All three working Pak'nSave indices have `_highlightResult.matchedWords` populated (same as New World):
- `products-index` [OK] — Relevance sorted, HAS `matchedWords`
- `products-index-popularity-asc` [OK] — Popularity sorted, HAS `matchedWords`
- `products-index-popularity-desc` [OK] — Popularity sorted, HAS `matchedWords`

All other indices (`price-asc`, `price-desc`, `relevance`, `name-asc`, `name-desc`, `newest`, `bestselling`, `trending`) return 500 (verified 2026-08-04; previously 404).

**Key Insight**: The default `products-index` is still recommended for the two-pass pipeline because it's relevance-sorted (most relevant first), which is optimal for ingredient search.

**Exploration**: `scripts/paknsave/Exploration/products-index-popularity-asc`, `products`

## 32. Pak'nSave Edge API — Two-Pass Pipeline Works End-to-End

**Symptom**: Needed to confirm the complete two-pass pipeline works for Pak'nSave with the same Algolia filter syntax as New World.

**Discovery**: The full two-pass pipeline works identically to New World:
- **PASS 1**: `POST /v1/edge/search/products/query/index/products-index` with `{"algoliaQuery": {"query": "beef mince"}, "page": 0, "hitsPerPage": 20, "storeId": "..."}`
  - Returns 40 hits with `_highlightResult.matchedWords` showing which fields matched
  - Category fields (`category1`, `category2`, `category3`) available for filtering
  
- **PASS 2**: `POST /v1/edge/search/paginated/products` with Algolia `filters` parameter
  - `filters: "productID:5104350-KGM-000 OR productID:5101189-KGM-000 ..."`
  - Returns `singlePrice.price` (cents) + `promotions[].rewardValue` (promo cents)
  - Sort: `PRICE_ASC` (cheapest at this store)

**Results for "beef mince" at PAK'nSAVE Botany**:
- Pass 1: 40 hits, 40 with relevance matches
- Pass 2: 8 products with per-store pricing: $1.99 (sauce) → $26.99 (premium mince)

**Pet Food Filtering**: Category-based filtering via `category1` field:
- Exclude: `{"Dog", "Cat", "Pet"}`
- Example: "Indulge Beef Mince In Gravy Dog Food" has `category1: ["Dog"]` — filtered out

**Scripts**: `scripts/paknsave/Exploration/demo_two_pass_pipeline.py`, `test_two_pass_optimiser.py`

## 33. Pak'nSave Edge API — Pet Food Filtering via Category

**Symptom**: The two-pass pipeline returned pet food items (dog food, cat food) for queries like "beef mince" because the relevance search matched on product names containing "beef mince".

**Discovery**: The Algolia index returns `category1` field for each hit, which can be used to filter out pet food:
- `category1: ["Dog"]` — dog food
- `category1: ["Cat"]` — cat food
- `category1: ["Pet"]` — general pet products
- `category1: ["Beef", "Mince, Sausages & Meatballs"]` — human food [OK]

**Resolution**: In Pass 1, filter out hits where `category1` contains any of `{"Dog", "Cat", "Pet"}`. This reduces relevance results from 40 to ~37 for "beef mince" but removes all pet food items.

**Before filtering**:
```
5104350-KGM-000 - NZ Beef Mince (human food)
5333649-EA-000 - Indulge Beef Mince In Gravy Dog Food (pet food - excluded)
5289585-EA-000 - Mince With Beef In Gravy Cat Food (pet food - excluded)
```

**After filtering**:
```
5104350-KGM-000 - NZ Beef Mince (human food - included)
5101189-KGM-000 - NZ Premium Beef Mince (human food - included)
5040757-EA-000 - Angus Beef Mince (human food - included)
```

**Implemented in**: `scripts/paknsave/Exploration/test_two_pass_optimiser.py`, `demo_two_pass_pipeline.py`

## 34. Pak'nSave Edge API — 3 Missing Stores Identified

**Symptom**: Edge API returns 57 stores while mobile API returns 60 stores. Need to identify which stores are missing.

**Discovery**: The 3 missing stores are:
- **Wairau Road** (Glenfield, Auckland) — Store ID: `002b83de-b79d-4228-a787-bd0765b6cb56`
- **Gisborne City** (Gisborne) — Store ID: `26c9c8bd-b7d8-4551-9fb0-350b829740a1`
- **Levin** (Levin) — Store ID: `90302a32-84f3-492a-8c9a-10f5242c0448`

**Verification**: All 3 stores return 0 products in Pass 2 (per-store pricing) despite having relevance matches in Pass 1. This confirms these stores are not configured for online ordering via the Edge API.

**Resolution**: Use Edge API store listing as primary source (57 stores). Mobile API can be used as fallback if more stores are needed.

---

## 35. Woolworths Store Setup — Unified Pipeline & Full Pickup Coverage

**Symptom**: The `Get_woolworths_store_choices.py` script only fetched stores from area ID 494 ("All Pick up locations"), which contained only ~171 stores. Stores like **Woolworths Chartwell** only appeared in their regional area (area 302, Waikato) and were missing from the merged store list.

**Discovery**: The pickup-addresses API returns 19 `storeAreas` — area 494 ("All Pick up locations") is NOT comprehensive. Regional areas contain additional pickup points (17 stores total missing from area 494, including Chartwell, remote collection points like Paparoa Hall, Ruawai, Whangamomona Hall, etc.).

**Resolution**: Created `scripts/woolworths/woolworths_setup.py` — a unified pipeline that:
1. `fetch_store_choices()`: Iterates ALL 19 storeAreas, dedupes by `id` → 188 unique pickup locations
2. `fetch_store_data()`: Fetches 183 stores from CDX API with lat/lon + `extra1` (fulfilmentStoreId) / `extra2` (pickupAddressId)
3. `merge_stores(cleaned=True)`: Left-joins on `id` = `SiteDataID`, optionally drops rows without coordinates (default True)

Output: `woolworths_stores.csv` with 177 stores having coordinates (11 dropped).

`woolworths_setup.py` is now the single entry point.

**Key files**: `scripts/woolworths/woolworths_setup.py` (functions + `__main__`), `data/woolworths_store_choices.json` (19 areas), `data/woolworths_stores.csv` (177 cleaned stores).

---

## 36. Pak'nSave Store Setup — Unified Pipeline

**Symptom**: The legacy `scripts/paknsave/fetch_stores.py` was a one-shot script that scraped the store-finder page `__NEXT_DATA__` to build `paknsave_stores.csv`. It wasn't callable as a module and had no options for cleaning/validating the output.

**Resolution**: Created `scripts/paknsave/paknsave_setup.py` — a unified, callable pipeline module with two data sources:

1. `fetch_stores(source="store_finder", verbose=True)`: Fetches from store-finder page, extracts 60 stores with GUIDs, names, addresses, cities, regions (NI/SI), and lat/lon from `__NEXT_DATA__`. No geocoding needed — coordinates provided by page source. Saves CSV + JSON.
2. `fetch_stores(source="edge", verbose=True)`: Fetches 57 stores from Edge API using website JWT authentication. Same output format. 3 stores (Wairau Road, Gisborne City, Levin) not configured for Edge API ordering.
3. `clean_stores(df, cleaned=True, verbose=True)`: Drops rows without coordinates (optional, no-op for Pak'nSave since all stores have coords).
4. `run_full_setup(source="store_finder", cleaned=True, verbose=True)`: Runs complete pipeline. CLI entry point via `python -m scripts.paknsave.paknsave_setup [store_finder|edge]`.

Output: `data/paknsave_stores.csv` (60 stores from store_finder, 57 from edge, all with coordinates) and `data/paknsave_stores.json`.

**Key files**: `scripts/paknsave/paknsave_setup.py`, `data/paknsave_stores.csv`, `data/paknsave_stores.json`.

---

## 37. Pak'nSave Edge API — Unified API Module & Optimisers

**Symptom**: The two-pass pipeline worked in exploration scripts (`demo_two_pass_pipeline.py`, `test_two_pass_optimiser.py`) but wasn't packaged as reusable modules. The legacy `PaknSave_prototype.py` used the Mobile API directly without the two-pass relevance matching or unit-price selection.

**Resolution**: Created three production-ready modules:

1. **`scripts/paknsave/paknsave_api.py`** — Unified API client:
   - `PaknSaveAPI(backend="edge"|"mobile")` — unified interface, defaults to Edge
   - `PaknSaveEdgeAPI` — full two-pass pipeline: Pass 1 relevance (`products-index` with `_highlightResult.matchedWords`), pet food filtering via `category1`; Pass 2 per-store pricing (`paginated/products` with Algolia filters + `PRICE_ASC`)
   - `PaknSaveMobileAPI` — legacy single-pass fallback (guest token)
    - Shared utilities: `load_stores()`, `geocode()`, `find_nearby_stores()`, `get_ingredients()`, `haversine()`, `DISHES` (21 dishes, dict format)

2. **`scripts/paknsave/paknsave_optimiser_edge.py`** — Edge API optimiser:
   - Geocodes address → finds nearby stores (5km) → authenticates via website JWT
   - Two-pass search per ingredient per store
   - Picks cheapest by **unit price** (falls back to absolute price)
   - Outputs cost comparison table + itemized breakdown → saves `data/paknsave_latest_results.csv`

3. **`scripts/paknsave/paknsave_optimiser_mobile.py`** — Mobile API optimiser:
   - Same structure but uses Mobile API (single-pass, guest token)
   - Same unit-price selection logic
   - Saves `data/paknsave_mobile_latest_results.csv`

**Testing**: Both optimisers tested with "Botany Town Centre, Auckland" + "spaghetti bolognese":
- Edge API: 3 stores found, 7/7 ingredients matched, Highland Park cheapest at $11.23
- Mobile API: 3 stores found, 7/7 ingredients matched, Ormiston cheapest at $40.13

**Legacy**: `scripts/paknsave/PaknSave_prototype.py` archived (replaced by unified modules).

**Key files**: `scripts/paknsave/paknsave_api.py`, `paknsave_optimiser_edge.py`, `paknsave_optimiser_mobile.py`

---

## 38. Unified Foodstuffs API Module Created

**Summary**: Created `scripts/foodstuffs/` as a combined module for both Pak'nSave and New World, consolidating the brand-specific API, optimiser, and setup logic into a single unified package. The shared `Foodstuffs_api.py` handles brand-specific credentials (banner, User-Agent) and stores the two-pass pipeline logic in `Foodstuffs_optimiser_edge.py`.

**Files created**:
- `scripts/foodstuffs/Foodstuffs_api.py` — Unified API client for both brands. `FoodstuffsEdgeAPI(brand)`, `FoodstuffsMobileAPI(brand)` with brand-specific credentials. Includes shared utilities (`load_stores()`, `geocode()`, `find_nearby_stores()`, `get_ingredients()`, `haversine()`, `BRANDS` dict). [NOTE: `DISH_INGREDIENTS` has since been refactored to `DISHES` dict format]
- `scripts/foodstuffs/Foodstuffs_optimiser_edge.py` — Edge API two-pass optimiser CLI. Accepts `brand` argument (`paknsave` or `newworld`). Supports both source types.
- `scripts/foodstuffs/Foodstuffs_optimiser_mobile.py` — Mobile API fallback optimiser. Same CLI structure, single-pass search.
- `scripts/foodstuffs/Foodstuffs_setup.py` — Unified store builder pipeline. Supports `source=edge` (default) or `source=mobile` for both brands. store_finder only available for paknsave.

**Status update 2026-08-04**: `scripts/foodstuffs/` has since been deleted — the cross-brand optimiser and row-builder logic has been migrated to `scripts/combined/optimiser_utils.py`. See entry 44 below.

---

## 39. Store-Finder Method Limited to Pak'nSave Only

**Summary**: Removed store_finder as a valid source for New World. Only Pak'nSave's `__NEXT_DATA__` contains `contentstackStores` with store GUID mappings (`uid` → `store_id`). New World's `__NEXT_DATA__` has no `contentstackStores` — only `title`, `url`, `address` per store. Therefore, store_finder source only produces full store data (with IDs, coordinates) for Pak'nSave.

**Changes**:
- `Foodstuffs_setup.py`: `BRANDS["newworld"]["sources"]` = `["edge", "mobile"]` only (no `store_finder`)
- `BRANDS["paknsave"]["sources"]` = `["edge", "mobile", "store_finder"]`
- `fetch_stores()` validates source against `BRANDS[brand]["sources"]` — raises `ValueError` for invalid combinations
- `newworld_setup.py` updated to only support `edge` and `mobile` sources
- `PaknSave_API.md` section 9 and `NewWorld_API.md` section 8 updated to reflect this

---

## 40. Legacy Scripts Marked

The following scripts are now legacy and should not be used for new development:

| Legacy File | Replaced By |
|---|---|
| `scripts/paknsave/fetch_stores.py` | `scripts/paknsave/paknsave_setup.py` |
| `scripts/paknsave/PaknSave_prototype.py` | `scripts/paknsave/paknsave_api.py`, `paknsave_optimiser_edge.py`, `paknsave_optimiser_mobile.py` |
| `scripts/newworld/fetch_stores.py` | `scripts/newworld/newworld_setup.py` |
| `scripts/newworld/NewWorld_prototype.py` | `scripts/newworld/newworld_api.py`, new optimisers |
| `scripts/paknsave/PaknSave_prototype.py` | `scripts/paknsave/paknsave_api.py` |
| All `scripts/woolworths/Playwright/` scripts | `scripts/woolworths/woolworths_api.py` (cookie-based, no Playwright needed) |
| `scripts/woolworths/woolworths_scrape.py` | `scripts/woolworths/woolworths_api.py` |
| All `scripts/*/Exploration/` scripts | Archived — only `scripts/paknsave/Exploration/` retains the two-pass pipeline documentation |

**Key principle**: Only the unified `foodstuffs/` package and brand-specific `paknsave/` and `newworld/` packages should be used for production code.

**Status update 2026-08-04**: The `foodstuffs/` package referenced in the "Key principle"
line is no longer present. The same modules remain via the brand-specific packages
(`scripts/paknsave/`, `scripts/newworld/`) plus `scripts/combined/optimiser_utils.py`.

---

## 41. Woolworths — Non-Food Department Filtering (Client-Side)

**Symptom**: The meal cost optimiser was returning non-food items (pet food, toiletries, cleaning products) in search results for ingredient queries like "beef mince" or "milk". The `target=search` endpoint ignores `dasFilter` (server-side department filtering is only available on `target=browse`), so there is no API parameter to exclude non-food departments.

**Discovery**: Each product returned by `GET /api/v1/products?target=search` includes a `departments` array with `id` and `name` fields. The 14 Woolworths departments map to these IDs:

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

**Resolution**: Added `NON_FOOD_DEPARTMENT_IDS = {10, 11, 12, 13, 14}` and `is_food_department(product)` function to `woolworths_api.py`. The `search_products()` and `find_cheapest()` functions accept a `food_only=False` parameter. When `True`, products whose `departments[].id` intersects with the non-food set are excluded. Products with no department info are included (assumed food).

The optimiser (`woolworths_optimiser.py`) now calls `find_cheapest(session, ing, food_only=True)` for all ingredient searches.

**Note**: This is client-side filtering — the API itself does not support department filtering on `target=search`. The `dasFilter` parameter only works with `target=browse`.

**Files changed**: `scripts/woolworths/woolworths_api.py` (added constant, function, params), `scripts/woolworths/woolworths_optimiser.py` (pass `food_only=True`)

---

## 42. Foodstuffs — Category1 Non-Food Filtering (Client-Side, Edge API)

**Symptom**: The Pak'nSave and New World Edge API two-pass optimisers were returning non-food items in search results — pet food ("Dog", "Cat"), baby products ("Baby Formula", "Nappies & Changing"), household items ("Cleaning & Accessories", "Laundry"), personal care ("Bath, Shower & Soap", "Hair Care"), and more. These appeared in Pass 1 relevance matches because Algolia returns them for broad queries like "beef mince" or "milk".

**Discovery**: Ran `explore_categories.py` (637 broad search queries) against the Pak'nSave Edge API to discover all 116 unique `category1` values present in the Algolia products-index. Each value was logged with frequency counts and example products. The full list was saved to `data/observed_category1_paknsave.json`. New World shares the same Foodstuffs category taxonomy (same parent company), so the same blacklist applies to both brands.

**Resolution**: Created `NON_FOOD_CATEGORIES` — a set of 53 `category1` values to exclude from Pass 1 results. Covers:
- **Pet/Animal**: Dog, Cat, Pet Health & Accessories, Birds/Fish/Small Animals
- **Baby/Toddler**: Baby & Toddler Food, Baby Formula, Baby Wipes, Nappies & Changing, Nursing & Feeding
- **Household/Cleaning**: Cleaning & Accessories, Dishwashing, Bathroom & Toilet Cleaners, Kitchen Cleaners, Laundry, Food Wrap/Storage/Bags, Pest & Insect Control, Homewares
- **Health/Personal Care**: Bath/Shower/Soap, Dental & Oral Care, Deodorant, Hair Care, Make Up & Nail Care, Medical & First Aid, Period & Continence Care, Shaving, Skin Care, Tissues, Toilet Paper, Vitamins & Supplements
- **Other non-food**: Stationery & Entertainment, Clothing & Accessories, Garage & Outdoor, Batteries & Electrical

Alcoholic drinks (Red Wine, Beer, Cider, etc.) are currently **excluded from the blacklist** (commented out) — they are beverages, not cooking ingredients, but may be useful for recipe lookups in the future.

**Implementation**: The `pass1_relevance_search()` method in all three API modules now checks each hit's `category1` array against `NON_FOOD_CATEGORIES` and excludes matches before passing productIDs to Pass 2.

**Files changed**:
- `scripts/paknsave/paknsave_api.py` — added `NON_FOOD_CATEGORIES`, updated `pass1_relevance_search()`
- `scripts/newworld/newworld_api.py` — same changes
- `scripts/foodstuffs/Foodstuffs_api.py` — same changes (shared across both brands)

**Demo scripts created**:
- `scripts/paknsave/paknsave_search_demo.py` — standalone two-pass demo for PAK'nSAVE Albany
- `scripts/newworld/newworld_search_demo.py` — standalone two-pass demo for New World Albany

**Note on category1 vs categoryTrees**: Pass 2 (`paginated/products`) returns `categoryTrees` (nested navigation hierarchy with `level0`/`level1`/`level2`) instead of the flat `category1` array returned by Pass 1 (`products-index`). This means category1-based filtering only happens in Pass 1 — by the time products reach Pass 2, the `category1` field is empty. In the future, a second phase of filtering could be applied in Pass 2 using `categoryTrees` for more granular control (e.g., excluding specific sub-aisles like "Flavoured Milk" while keeping "Standard Milk"). This is an area for future exploration and has not been implemented.

---

## 43. Woolworths Optimiser — Shared CSV with Hash-Based Deduplication

**Symptom**: Each optimiser run saved results to a per-run CSV (`woolworths_results.csv`), requiring re-querying the API every time. No way to accumulate results across runs or compare prices across different query sessions.

**Resolution**: Restructured `woolworths_optimiser.py` into a two-phase pipeline (query → optimise) writing to a shared `data/full_results.csv`:

**Phase 1 (query)**: Geocode address → find nearby stores → search ingredients at each store → append all results to CSV (not just cheapest). Deduplication via `pk_hash` — a SHA-256 hash of `store_id|sku|date_created` (truncated to 16 hex chars). Duplicate PKs are skipped on insert.

**Phase 2 (optimise)**: Read today's results from CSV → group by (store, ingredient, date) → pick cheapest per ingredient → print comparison table.

**CLI flags**:
- `--requery false` — skip API, optimise from existing CSV data only
- `--distance 5` — set store search radius in km (default 2)

**Key design decisions**:
- Append-only CSV: new rows are added, never overwritten. PK hash enables dedup without loading all rows into memory (O(n) set lookup).
- `date_created` normalised to `yyyy-mm-dd` format. Old `dd/mm/yyyy` rows from legacy scripts cause hash mismatches — avoid editing CSV in Excel (blank rows corrupt the file).
- `parse_volume_size(volume_size, cup_measure="")` falls back to `cupMeasure` from API when `volumeSize` is missing/null. Returns `(quantity, measurement_unit)`.
- `search_products()` now returns all results (not just cheapest) with `cupMeasure`, `cupListPrice`, and `department` fields.
- Geocode results printed before store list: `Geocoding: <address>` / `lat: xxx  lon: xxx`.

**Files changed**: `scripts/woolworths/woolworths_optimiser.py`, `scripts/woolworths/woolworths_api.py`, `scripts/combined/initialize_full_results.py`

---

## 44. Foodstuffs folder deleted — cross-brand logic consolidated into optimiser_utils.py

**Date**: 2026-08-04

**Summary**: Deleted `scripts/foodstuffs/`. The cross-brand logic previously in that
folder was consolidated into `scripts/combined/optimiser_utils.py`. Brand-specific
optimisers (`scripts/paknsave/`, `scripts/newworld/`) are now thin CLI wrappers that
inject the brand API class and store-finder into the shared helpers.

**Moved to `scripts/combined/optimiser_utils.py`:**
- `foodstuffs_optimiser_edge` / `foodstuffs_optimiser_mobile` — full CLI runners
- `build_edge_row` / `build_mobile_row` — per-product CSV row builders
- `parse_foodstuffs_volume_size` / `parse_foodstuffs_mobile_unit` — size/price parsers
- `geocode`, `haversine`, `find_nearby_stores` — geo helpers
- `get_ingredients`, `_build_quantity_map`, `DISHES` — dish lookup (DISHES is dict format with quantity/unit/search_term)
- `optimise()`, `analyse_results()` — Phase 2 CSV readers
- `append_rows()`, `_compute_pk_hash()`, `load_existing_hashes()` — append-only CSV with SHA-256 dedup

**Behavioral fix**: The `optimise(dish, company=...)` filter is now correctly applied
in both brand optimisers (previously could blend PNS+NW rows from `full_results.csv`).
The `per_unit_price` field is now blank (not 0.0) when falsy.

---

## 58. Dish Format Refactored from String List to Dict

**Date**: 2026-08-06

Refactored the hardcoded dish format from a simple string-list mapping
(`DISH_INGREDIENTS = {"dish": ["ingredient1", ...]}`) to a structured dict
format matching LLM output (`DISHES = {"dish": {"dish_name": str, "portion": int,
"ingredients": [{quantity, unit, search_term}, ...]}}`).

**Changes:**
- `DISH_INGREDIENTS` (string list dict) → `DISHES` (structured dict with
  quantity/unit/search_term per ingredient) in `optimiser_utils.py`
- `DISH_QUANTITIES` (separate human-readable quantity dict) → removed;
  quantities now embedded in `DISHES` dict
- `get_ingredients(dish_name)` — now extracts search_terms from `DISHES` dict
- `get_quantities(dish_name)` — replaced by `_build_quantity_map(dish)` which
  resolves the quantity string from the `DISHES` dict
- `_resolve_dish_dict(dish)` — new helper that resolves a string dish name to
  its full `DISHES` dict, used by `_build_quantity_map`
- `analyse_results()` — updated to call `_build_quantity_map(dish)` instead of
  `get_quantities(dish_name)`
- Removed duplicate `DISH_INGREDIENTS` and `get_ingredients()` from
  `paknsave_api.py` and `newworld_api.py` — both now use the shared version
  from `optimiser_utils.py`
- `woolworths_optimiser.py` — removed `get_ingredients`/`get_quantities` imports
  (no longer needed; uses `_resolve_dish` directly)
- `ingredient_parser.py` — removed import of `DISH_INGREDIENTS`; legacy fallback
  now uses `DISHES` dict from `optimiser_utils.py`
- `init_dishes_json.py` — now seeds `dishes.json` from `DISHES` dict

**Backward compatibility**: `_resolve_dish()` still accepts both string dish
names and dict dishes. CLI optimisers pass strings, LLM pipeline passes dicts.

### Log #59 — Migrated DISHES dict from code to data/dishes.json

**Date**: 2026-08-06

Moved the `DISHES` dict from `scripts/combined/optimiser_utils.py` into
`data/dishes.json` (JSON file). The dict is now lazily loaded at module import
time via `_load_dishes()`. A `_reload_dishes()` helper is available for
refreshing after manual edits.

**Changes:**
- `optimiser_utils.py` — replaced hardcoded 275-line `DISHES` dict with
  `_load_dishes()` call + `DISHES = _load_dishes()` + `_reload_dishes()` helper
- `data/dishes.json` — now stores full structured dish data (dish_name,
  portion, ingredients with quantity/unit/search_term) instead of the old
  lightweight schema (search_terms + default_portions)
- `ingredient_parser.py` — updated `dish_to_json()` and `json_to_dish()` to
  read/write the new structured schema; `resolve_ingredients()` now checks only
  `dishes.json` (removed the redundant `DISHES` from `optimiser_utils` fallback)
- `init_dishes_json.py` — regenerated to output full structured format from
  the `DISHES` dict; preserved metadata fields (last_generated, generator_model)
- `llm-dish-pipeline.md` — updated to reflect that `dishes.json` now stores
  full structured format, eliminating the need for `_resolve_dish_dict`
  fallback at lookup time

## 60. New World Test Fixture Capture — Store Count Updated to 150

**Date**: 2026-08-11

**Symptom**: Documentation stated New World Mobile API returns 149 stores; live re-capture returned 150. The New World store-finder page (150) and mobile API (150) now agree on store count.

**Findings**:
- **Live store counts re-verified**:
  - Edge API (`GET /v1/edge/store`): 148 stores
  - Mobile API (`GET /mobile/store/physical`, banner=MNW): 150 stores
- The 2 stores present in Mobile but absent from Edge are:
  - `New World Te Atatu` (575 Te Atatū Road, Te Atatū Peninsula, Auckland 0610) — id `2d939bb7-ae26-4cc7-b930-d10e6a4de8a3`
  - `Foodie Mart` (35 Landing Drive, Mangere, Auckland 2022) — id `e89d6e45-f824-464a-8a69-c8028840c899`
- Previously documentation (see Log 26) described Te Atatu as "set to open on 11/08/2026" and absent from the API. As of this capture, **Te Atatu IS now present in the Mobile API** (no longer filtered out / not yet populated). Edge API remains at 148 (still missing both Te Atatu and Foodie Mart).

**Actions**:
- Regenerated `data/newworld_stores.csv`/`.json` with `source="edge"` (148 stores, default) and verified Mobile source captures 150.
- Added test suite under `scripts/newworld/tests/` (84 tests) with fixtures in `scripts/newworld/fixture/`, mirroring the Pak'nSave test structure. All assertions reference live-captured fixture data; no mock API responses (mock is used only for CLI argument dispatch, matching Pak'nSave's approach).
- Updated `NewWorld_API.md` store-count tables/notes and `AGENTS.md` New World sections to reflect 150 mobile stores and the Te Atatu/Foodie Mart absence from Edge.

**Resolution**: Documentation corrected. Edge API remains the default/authoritative source (148 stores). Mobile API (150 stores) is the legacy fallback with the most complete store set.

---

## 61. LLM Approx-Unit Fallback for Non-Standard Recipe Units

**Date**: 2026-08-11

**Symptom**: Ingredients with non-standard recipe units (`"1 can"`, `"1 medium onion"`, `"2 fillets"`) caused `parse_optimiser_columns` to return `status="incompatible_units"` with `used_price=None` whenever the supermarket pack was sold by weight/volume (e.g. `"500g"`), because `"can"`/`"medium"`/`"fillets"` normalize to unrecognized categories that don't match `"g"` or `"ml"`.

**Resolution**: Added `approx_quantity`/`approx_unit` metadata to recipe ingredients. When the incompatible-units branch fires, `parse_optimiser_columns` now falls back to the approx values (e.g. `"1 medium onion"` → approx `150g`) to compute a proportional cost:

1. **`llm_client.py`**: Updated `INGREDIENT_PROMPT` — instructs the LLM to include `approx_quantity` (in g or ml) and `approx_unit` for non-standard units ("1 can", "medium", "fillet", "bag", "head", etc.).
2. **`llm_utils.py`**: `ParsedIngredient` dataclass and `parse_and_validate` now normalize and pass through optional `approx_quantity`/`approx_unit` fields. `parse_optimiser_columns` reads them from the enriched row and uses them as a fallback in the incompatible-units branch — converting to a common base and checking category compatibility (including 1ml≈1g cross-category). Status is set to `"approximate"` and `used_price` computed normally.
3. **`llm_utils.py`**: Fixed `_VOLUME_UNITS_TO_ML` to include `"cups"` (plural) — previously only `"cup"` was recognized, causing "2 cups" to be incompatible.
4. **`llm_interactive.py`**: Step 6 enrichment now copies `ingredient_approx_quantity`/`ingredient_approx_unit` from the dish dict onto each CSV row before calling `parse_optimiser_columns`.
5. **`data/dishes.json`**: Populated approx values for all 21 dishes — every ingredient with a non-standard unit (can: 400g/400ml, medium onion: 150g, medium carrot: 60g, etc.) now carries approximate weight/volume metadata.
6. **`check_unit_approximation.py`**: Added 5 test cases covering approx fallback (matching category, cross-category, no-approx → incompatible, wrong-category → still incompatible).

**Key insight**: This is backward-compatible — ingredients without approx fields behave exactly as before (`status="incompatible_units"`, `used_price=None`). The approx fallback only activates when both the primary unit comparison fails AND approx fields are present.

## 62. Woolworths — Retired `pickupAddressId` (extra2) indirection; source stores from CDX extra1

**Date**: 2026-08-12

**Symptom**: The Woolworths optimiser bridged `pickupAddressId` (extra2) to
`fulfilmentStoreId` (extra1) via a runtime lookup table
(`get_store_mapping()`). This indirection was unnecessary — extra1 is available
directly from the CDX store-location API and is the only value the
`cw-lrkswrdjp` cookie requires (`dm-Pickup,f-{extra1},s-38`). The lookup also
forced `results.store_id` to be written as extra2 (pickupAddressId), requiring
extra normalization downstream (e.g. FastAPI worker store-id mapping) and
creating inconsistent store identity across the data files.

**Resolution**: Retired the extra2->extra1 indirection so the whole pipeline
keys directly on extra1:

- `woolworths_setup.fetch_store_data()` now builds `data/woolworths_stores.csv`
  directly from the CDX API, with `id = extra1` and columns `id, name, address,
  latitude, longitude`. The legacy left join against `woolworths_store_choices.csv`
  and the `merge_stores()` function are removed. Output is 183 CDX sites
  (177 after dropping the 4 null-extra1 + 2 shut-down excludes 9285, 9035),
  keyed on extra1.
- `woolworths_api.get_nearby_stores()` reads `woolworths_stores.csv` and
  returns `store_id = extra1` (plus `fulfilmentStoreId`, `lat`, `lon`,
  `distance_km`).
- `woolworths_api.set_store_context(session, fulfilment_store_id)` takes extra1
  directly, builds the cookie as `dm-Pickup,f-{fulfilment_store_id},s-38`, and
  validates via `/api/v1/shell`. No mapping lookup.
- `optimiser_utils.woolworths_optimiser()` and `build_woolworths_row()` write
  `store_id = extra1` to `full_results.csv`.
- Legacy functions `_load_store_mapping()`, `get_store_mapping()`, and
  `fetch_store_choices()` have been **removed** from `woolworths_api.py`.
  `fetch_store_choices()` code is retained in `woolworths_setup.py` (marked
  legacy) for ad-hoc regeneration only.

**Cookie unchanged**: the `cw-lrkswrdjp` format
(`dm-Pickup,f-{extra1},s-38`), the fresh-session-per-store requirement, and
the `areaId`/`s-38` optionality findings (Logs #16-#20) are all unchanged —
the only change is that extra1 is now read directly from the CDX-derived
store file rather than indirectly inferred from extra2 via a mapping table.

**Tests / fixtures**: regenerated the `woolworths_stores.csv`-equivalent test
fixture `fixture/stores_fixture.csv` (schema keyed on extra1, derived from
`store_data_example.json`); `TestGetNearbyStores` patches `STORE_CSV`;
`TestSetStoreContext` passes extra1 directly; `build_woolworths_row` tests
use `store_id="9290"` (extra1) + recompute `pk_hash`. The `TestLoadStoreMapping`
class (which tested the now-removed `_load_store_mapping`) has been removed.

## 63. Woolworths — extra1 collisions: 3 store pairs share fulfilmentStoreId, 2 stores hardcoded as shut down

**Date**: 2026-08-13

**Symptom**: When building `woolworths_stores.csv` from CDX, `extra1` (fulfilmentStoreId)
was used as the unique store key. Inspection revealed that **3 pairs of physically
different stores share the same extra1 value**:

| extra1 (fulfilmentStoreId) | Store A (extra2) | Store B (extra2) | CDX site.id A | CDX site.id B |
|---|---|---|---|---|
| 9290 | Nelson Junction Woolworths (4166071) | Motueka Woolworths (767216) | 9290 | 9495 |
| 9112 | Te Puke Woolworths (913417) | Bureta Park Woolworths (1175393) | 9448 | 9050 |
| 9511 | Bridge Street Woolworths (1207646) | Matamata Woolworths (911335) | 9033 | 9120 |

**Root cause**: `extra1` is a **fulfilment store ID**, not a unique pickup-location
identifier. The Woolworths API resolves `f-{extra1}` to a single `pickupAddressId`
(via the `/api/v1/shell` endpoint's `context.fulfilment.pickupAddressId` field).
Inspection confirmed:

- `f-9290` → shell returns `pickupAddressId=767216` → resolves to **Motueka** (not Nelson Junction)
- `f-9112` → shell returns `pickupAddressId=913417` → resolves to **Te Puke** (not Bureta Park)
- `f-9511` → shell returns `pickupAddressId=911335` → resolves to **Matamata** (not Bridge Street)

The "other" store in each pair (Nelson Junction, Bureta Park, Bridge Street) is
**not directly addressable via any cookie key**:
- `f-{extra2}` (pickupAddressId) is rejected by the shell (falls back to default 9171)
- `f-{site.id}` (CDX internal id) is rejected by the shell (falls back to 9171)

**Consequence**: Only **3 of the 6 stores** are effectively reached via extra1.
The other 3 (Nelson Junction, Bureta Park, Bridge Street) are **unreachable** —
they share their extra1 with a different physical store, and the API maps the
cookie to the first/most-prioritised pickup location for that fulfilment store.

**Live price verification** (search query "milk"):
- extra1=9290 resolves to Motueka: milk = $2.49
- extra1=9112 resolves to Te Puke: milk = $2.26
- extra1=9511 resolves to Matamata: milk = $2.26

All three returned different prices from each other, confirming the API does
isolate pricing by the cookie key — but only at the fulfilment-store granularity,
not the site granularity.

**Investigation method**: Scripts in `exploration/woolworths/`:
- `explore_extra1_collisions.py` — phases 1-5: CDX metadata dump, shell context
  inspection for extra1/extra2/site.id, live price queries across all key types

**Resolution**: extra1 remains the correct cookie key — there is no alternative
that works for all stores. The colliding pairs will continue to return the
price of whichever store the API maps the shared extra1 to. `fetch_store_data()`
(dedup by extra1) already drops the duplicates; the remaining store in each
pair is the one that the API actually resolves to.

**Hardcoded exclusions**: Two stores added to `EXCLUDED_STORE_IDS` in
`woolworths_setup.py`:

- `9285` (Te Atatu Woolworths, 583 Te Atatu Road): permanently shut down on
  24/04/2025. CDX still lists it but the physical store no longer exists.
  Not present in the legacy `store_choices` pipeline either.
- `9035` (Kaikohe Woolworths, 37 Station Road): permanently shut down on
  15/02/2026. CDX still lists it but the physical store no longer exists.
  Not present in the legacy `store_choices` pipeline either.

These are filtered in `fetch_store_data()` before writing `woolworths_stores.csv`,
so neither store appears in optimiser results.

## 64. Src-layout restructure + docs migration

**Date**: 2026-08-18

**Symptom**: The repo was a `scripts/`-centric layout that relied on ad-hoc
`sys.path` bootstrap (`scripts/fastapi/core/paths.py`) to import cross-brand
helpers. This was fragile — import order, relative paths, and interpreter state
could all break it, and it made Docker / CI / test setup awkward.

**Change**: Restructured into an installable **src-layout Python package**
(`pyproject.toml`, editable install via `pip install -e .`). All code moved via
`git mv` (staged, branch `feature_FastAPI`).

What moved (see §40 in `decision.md` for rationale):

| Old path | New path |
|---|---|
| `scripts/combined/optimiser_utils.py` | `src/NZMealOptimiser/pricing/optimiser_utils.py` |
| `scripts/combined/initialize_full_results.py` | `tools/combined/initialize_full_results.py` |
| `scripts/combined/tests/*` | `tests/combined/*` |
| `scripts/{paknsave,newworld}/*_api.py` | `src/NZMealOptimiser/pricing/{paknsave,newworld}_api.py` |
| `scripts/{paknsave,newworld}/*_setup.py`, `*_optimiser_*.py`, `*_search_demo_*.py` | `tools/{paknsave,newworld}/*.py` |
| `scripts/woolworths/woolworths_api.py` | `src/NZMealOptimiser/pricing/woolworths_api.py` |
| `scripts/woolworths/{woolworths_optimiser,woolworths_setup,woolworths_search_demo}.py` | `tools/woolworths/*.py` |
| `scripts/{paknsave,newworld,woolworths}/{tests,fixture}/*` | `tests/{paknsave,newworld,woolworths}/*` |
| `scripts/{paknsave,newworld,woolworths,llms}/Exploration/*` | `exploration/<brand>/*` |
| `scripts/woolworths/Playwright/*` | `exploration/woolworths/Playwright/*` (kept the `Playwright/` subfolder) |
| `scripts/llms/{llm_client,llm_utils}.py` | `src/NZMealOptimiser/llm/{llm_client,llm_utils}.py` |
| `scripts/llms/{llm_validate,llm_interactive}.py` | `tools/llm/{llm_validate,llm_interactive}.py` |
| `scripts/fastapi/main.py`, `scripts/fastapi/core/config.py` | `src/NZMealOptimiser/web/{main,config}.py` |
| `scripts/fastapi/core/paths.py` | `unsure/paths.py` (retired — no longer exists) |
| `scripts/fastapi/static/{index_old.html,vue/*}` | `src/NZMealOptimiser/web/static/{index_old.html,vue/*}` |
| `scripts/fastapi/frontend/*` | `src/NZMealOptimiser/web/frontend/*` |
| `scripts/fastapi/tmp/` | gone (unused scratchpad) |
| `data/Exploration/woolworths/part2_cookies.json` | `exploration/woolworths/data/part2_cookies.json` |
| `scripts/test/*` (permutation scripts) | `tests/combined/*` |

Also: `FastAPI_HANDOVER.md` absorbed into `docs/technical/FastAPI.md` then
deleted; `core/paths.py` retired to `unsure/`; `Dockerfile`/`pyproject.toml`/CI
(`.github/workflows/test.yml`) updated. Docs migrated under `docs/`:
`docs/project/` (decision.md, design.md, logs.md) and `docs/technical/`
(PaknSave_API.md, NewWorld_API.md, Woolworths_API.md, LLM_Pipeline.md, FastAPI.md).
`AGENTS.md` and `README.md` stay at the repo root and were updated to the new
layout. New `data/` path contract: `DATA_DIR = PROJECT_ROOT / "data"` resolved in
`src/NZMealOptimiser/__init__.py` — `data/` itself unchanged.

**Note on historical entries**: Paths mentioned in entries before this one (e.g.
`scripts/...`) predate the restructure and are left as-is — they are records of
what existed at the time. This entry marks the transition point.

## 65. AGENTS.md "Research Status" offload

**Symptom**: `AGENTS.md` had grown three verbose "Research Status" sections
(Woolworths, New World, Pak'nSave) totalling ~30 lines that duplicated the
"what works" prose already living in `docs/technical/{Woolworths,NewWorld,PaknSave}_API.md`.

**Resolution**: Collapsed the three blocks into a single "Confirmed Research"
checklist in `AGENTS.md` (~14 lines), referring out to the relevant API doc §N
for full detail. Historical narrative (store-count deltas, cookie experiments,
Playwright-vs-curl work) stays here and in `docs/technical/*.md` — these remain
the canonical record; `AGENTS.md` is the quick-reference. Per-brand CLI notes
(57/60/148/150 store counts, `s-38` constant, hardcoded `EXCLUDED_STORE_IDS`,
`x-requested-with` `"??"`) migrated into the per-brand API docs where they
belong; only the truly load-bearing gotchas stay in `AGENTS.md` "Key Gotchas".
The "Nominatim not needed" claim was qualified: Nominatim is **not** used for
store coordinates anymore (Foodstuffs APIs ship them), but **is** still used for
user-address geocoding (typed address → lat/lon for the 5 km radius), rate
limited 1 req/sec. See `FastAPI.md` §`_resolve_origin` and `optimiser_utils.py`
`geocode()`.


