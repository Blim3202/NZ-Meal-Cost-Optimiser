# Woolworths API Exploration Documentation

## Overview

This folder contains the **4-phase exploration** that discovered how to achieve per-store pricing on the Woolworths NZ API. The exploration was entirely black-box HTTP probing — no source code, no internal docs, no authenticated access.

**Final Achievement**: Per-store pricing via `cw-lrkswrdjp` cookie injection, constructed programmatically from `extra1` in `woolworths_store_data.json`. No Playwright needed at runtime.

---

## Phase 1: API Surface Discovery & Baseline Testing
### `explore_woolworths_api_part1.py`

**Goal**: Enumerate the `/api/v1` surface, understand the data model, and establish baseline global pricing.

**Key Tests**:
1. **Full catalogue browse** (`target=browse`) with sort options: relevance, `PriceAsc`, `PriceDesc`, `CUPAsc`
2. **dasFilter taxonomy discovery** — tested 6+ facet chain formats (Department, Aisle, Shelf) against the semicolon-delimited format
3. **Shell context** (`/api/v1/shell`) — extracted `context.fulfilment` object showing default `fulfilmentStoreId: 9171`
4. **Pickup addresses** (`/api/v1/addresses/pickup-addresses`) — enumerated all store records; confirmed NO bridge keys (`siteDataId`, `externalId`, etc.) exist
5. **Price comparison across `fulfilmentStoreId` query params** — **ZERO price changes** across 3 store IDs (baseline, 9171, 1225718). Concluded: **global pricing via query params**
6. **POST store-switch endpoints** — tested 9 endpoints with 3 payload variants (`storeId`, `pickupAddressId`, `fulfilmentStoreId`). **All 404**. No programmatic store switch via API.

**Critical Finding**: The API appeared to use **global pricing**. Per-store pricing (if it existed) was NOT accessible via query parameters.

---

## Phase 2: Cookie Injection Discovery
### `explore_woolworths_api_part2.py`

**Goal**: Test if browser-side store selection sets cookies that control pricing.

**Strategy**:
- **Step 1**: URL-param seeding — visit `?pickupStoreId=xxx` and check if API prices change. **FAILED** — prices identical.
   - **Step 2**: Playwright cookie capture — headed Chromium visits store-selection modal, selects Greymouth/Glenfield, captures full 67-cookie jar. Inject into `requests.Session` and test API.
   - **RESULT**: **PRICES DIFFER!** Greymouth Milk 3L = $7.15, Glenfield = $7.33. Per-store pricing CONFIRMED.
   - Cookie jars saved to `data/Exploration/woolworths/part2_cookies.json`
   - Cookie diff: 67 cookies captured, but which one(s) carry store context?
- **Step 2b**: Isolate `session_state` (Optimizely) cookie only. **FAILED** — both stores return $7.33.
- **Step 2c**: Isolate `RT` (Adobe Analytics) cookie only. **FAILED** — both stores return $7.33.
- **Step 3**: URL-param exploration on GET `/` with various params. **FAILED** — no price differences.

**Key Discovery**: Full Playwright cookie jar works. The store context is carried by cookies, not URL params. But 67 cookies is fragile — need to identify the minimal set.

---

## Phase 3: Cookie Deep-Dive & Minimal Set
### `explore_woolworths_api_part3.py`

**Goal**: Validate cookie jars via `/api/v1/shell` and isolate the single cookie that controls store context.

**Step 1**: Shell validation — inject full Playwright jars, call `/api/v1/shell`.
- **Greymouth**: `fulfilmentStoreId = 9009` (NOT 9171) ✅
- **Glenfield**: `fulfilmentStoreId = 9443` (NOT 9171) ✅
- Baseline (no cookies): `fulfilmentStoreId = 9171` (default)

**Step 2**: `fulfilmentStoreId` as query param (no cookies). **FAILED** — shell context stays at 9171, prices unchanged.

**Step 3**: `cw-lrkswrdjp` cookie analysis.
- **Greymouth**: `dm-Pickup,f-9009,a-224,s-38`
- **Glenfield**: `dm-Pickup,f-9443,a-440,s-38`
- Fields: `dm`=delivery method, `f`=fulfilmentStoreId (KEY), `a`=areaId, `s`=site (constant 38)

**Step 3b**: Inject `cw-lrkswrdjp` + `session_state` only.
- **Greymouth**: shell `fulfilmentStoreId = 9009` ✅, Milk 3L = $7.15 ✅
- **Glenfield**: shell `fulfilmentStoreId = 9443` ✅, Milk 3L = $7.33 ✅

**Step 3c**: Inject `cw-lrkswrdjp` ONLY (no `session_state`).
- **Both stores**: shell context correct, prices correct ✅

**Step 3c variant**: `dm-Pickup,f-9009,a-0,s-38` (areaId=0). **WORKS** ✅
**Step 3c variant**: `dm-Pickup,f-9009` (minimal). **WORKS** ✅

**Critical Findings**:
1. **`cw-lrkswrdjp` is the SOLE per-store cookie** — 66 other cookies irrelevant
2. **Format**: `dm-Pickup,f-{fulfilmentStoreId},s-38` (areaId optional, s-38 constant)
3. **`fulfilmentStoreId` ≠ `pickupAddressId`** — different internal IDs, no formulaic relationship
4. **`fulfilmentStoreId` NOT available from any API endpoint** — only in Playwright-captured cookie

---

## Phase 4: Programmatic Construction & Production Validation
### `explore_woolworths_api_part4.py`

**Goal**: Build the `cw-lrkswrdjp` cookie programmatically for ALL stores without Playwright at runtime.

**Breakthrough Discovery**: `extra1` in `woolworths_store_data.json` (from CDX API) **IS the `fulfilmentStoreId`**!

| Store | extra1 | cookie `f-` field | Match? |
|-------|--------|-------------------|--------|
| Greymouth | 9009 | 9009 | ✅ |
| Glenfield | 9443 | 9443 | ✅ |
| Birkenhead | 9101 | 9101 | ✅ |

**Steps**:
 1. **Step 1**: Playwright capture for 3 stores → parse `cw-lrkswrdjp` → extract `fulfilmentStoreId` + `areaId`
 2. **Step 2**: Validate `extra1` from `woolworths_store_data.json` matches captured `fulfilmentStoreId`
 3. **Step 3**: Construct cookies programmatically using `build_cw_lrkswrdjp(fsid, aid)`
 4. **Step 4**: Validate via `/api/v1/shell` — all 3 stores return correct `fulfilmentStoreId`
 5. **Step 5**: Validate via `/api/v1/products` — Greymouth $7.15 ✅, Glenfield $7.33 ✅
 6. **Step 6**: Compare constructed cookie vs full Playwright jar — **PRICES IDENTICAL** ✅

**Production Architecture**:
```python
# Load fulfilmentStoreId from woolworths_store_data.json (extra1 = fulfilmentStoreId)
store_map = {str(extra2): {"fulfilmentStoreId": extra1, ...} for site in data}

# For each store:
session = create_session()  # fresh session + GET /
cookie = f"dm-Pickup,f-{fulfilmentStoreId},s-38"
session.cookies.set("cw-lrkswrdjp", cookie, domain="www.woolworths.co.nz")
# Validate: shell.fulfilmentStoreId != 9171
# Search products — returns per-store pricing
```

**Critical Constraint**: **Fresh `requests.Session` per store** — server's `Set-Cookie` on `GET /` overwrites injected `cw-lrkswrdjp` on reused sessions.

---

## Exploration Timeline Summary

| Phase | Script | Duration | Key Discovery |
|-------|--------|----------|---------------|
| 1 | part1 | ~1 week | API surface mapped; global pricing via query params; no POST store-switch |
| 2 | part2 | ~3 days | **Per-store pricing EXISTS** via Playwright cookie injection ($7.15 vs $7.33) |
| 3 | part3 | ~2 days | **`cw-lrkswrdjp` is the ONLY cookie needed**; format decoded; areaId/s optional |
| 4 | part4 | ~2 days | **`extra1` = `fulfilmentStoreId`** in CDX data; programmatic construction works for all stores |

---

## Files in This Folder

```
scripts/woolworths/Exploration/
├── explore_woolworths_api_part1.py   # Phase 1: API enumeration, dasFilter, shell, pickup-addresses, price comparison
├── explore_woolworths_api_part2.py   # Phase 2: URL-param seeding → Playwright cookie capture → price validation
├── explore_woolworths_api_part3.py   # Phase 3: Shell validation, cw-lrkswrdjp deep-dive, minimal cookie isolation
├── explore_woolworths_api_part4.py   # Phase 4: Programmatic cookie construction, production validation
└── Exploration.md                    # This file
```

**Data outputs** (stored in `data/Exploration/woolworths/`):
- `part2_cookies.json` — Playwright-captured cookie jars (Greymouth, Glenfield, Baseline)

---

## Production Code (Not in Exploration Folder)

The exploration directly enabled these production modules:

| File | Purpose |
|------|---------|
| `../woolworths_api.py` | Cookie-based API module: `create_session()`, `set_store_context()`, `search_products()`, `find_cheapest()`, `get_nearby_stores()`, `geocode()` |
| `../woolworths_optimizer.py` | Thin CLI: delegates step 1 (geocode → nearby stores → fresh session per store → cookie injection → ingredient search) to `optimizer_utils.woolworths_querier`, then step 2 `optimise()` |
| `../Get_woolworths_store_API_data.py` | Fetches `woolworths_store_data.json` from CDX API (source of `extra1`/`extra2`) |
| `../Get_woolworths_store_choices.py` | Fetches pickup store list from `/api/v1/addresses/pickup-addresses` |
| `../Merge_woolworths_stores.py` | Joins choices + location data → `woolworths_stores.csv` |

---

## Key Gotchas Documented

1. **Fresh session per store** — reused session gets `cw-lrkswrdjp` overwritten by server's `Set-Cookie` on `GET /`
2. **`x-requested-with: ??` header mandatory** — omission returns HTTP 400
3. **Cookie domain must be `www.woolworths.co.nz`** (not `.woolworths.co.nz`)
4. **`extra1` = `fulfilmentStoreId`**, `extra2` = `pickupAddressId` — different numbers, no formula
5. **Playwright headless=False required** — site blocks headless Chromium
6. **21/21 products show price differences** between Greymouth and Glenfield — per-store pricing is real
7. **`s-38` is constant** across all tested stores — safe to hardcode
8. **`areaId` not in any API** — would need Playwright to capture, but optional

---

## Final Architecture

```
woolworths_store_data.json (CDX API)
    │
    ├── extra1 = fulfilmentStoreId  →  cw-lrkswrdjp "f-" field
    └── extra2 = pickupAddressId    →  lookup key
                    │
                    ▼
store_map: {pickupAddressId: {fulfilmentStoreId, name, lat, lon}}
                    │
                    ▼
FOR EACH nearby store:
    1. create_session()          # fresh requests.Session + GET /
    2. set_store_context(pid)    # inject cw-lrkswrdjp = f"dm-Pickup,f-{fsid},s-38"
    3. search_products(session, ingredient)
    4. find_cheapest() → per-store price
                    │
                    ▼
Aggregate → compare totals → cheapest store
```

**No Playwright at runtime. Pure `requests` + constructed cookie.**