# Woolworths API Exploration Documentation

## Overview

This folder contains **6 exploration scripts (`explore_*`) + a `Playwright/`
subfolder** containing the Playwright-based demos (`demo_*`), documenting the
multi-phase, entirely black-box journey from initial `/api/v1` probing to a
production-ready cookie-based per-store pricing path. No source code, no internal docs,
and no authenticated access were used — everything below was discovered by careful HTTP
probing against `www.woolworths.co.nz`.

**Key Outcome**: Per-store pricing on the Woolworths NZ API is achieved by injecting a
single constructed cookie (`cw-lrkswrdjp`) into a **fresh `requests.Session`** per
store. The cookie is built programmatically from `extra1` in `woolworths_store_data.json`
(CDX API), which **is** the internal `fulfilmentStoreId`. **No Playwright is needed at
runtime.**

**Known caveat**: `extra1` is a *fulfilment* store ID and is **not unique** — 3 pairs of
physically different stores share an `extra1`, and only 3 of those 6 stores are
reachable via the cookie. See `docs/technical/Woolworths_API.md` §8 and `docs/project/logs.md` §63.

**Script naming convention** (established alongside `exploration/paknsave/` and
`exploration/newworld/`):
- `explore_*` — broad discovery probes, endpoint enumeration, cataloguing
- `check_*` — focused validation against a known-good answer
- `demo_*` — end-to-end proof-of-concept flows / reference implementations
- The `_partN` suffix on `explore_woolworths_api_part{1..4}` encodes the sequential,
  data-dependent discovery order (`part3` consumes `part2`'s cookie jar; `part4` builds
  on `part3`'s cookie format).
- All Playwright-based demos live in the `Playwright/` subfolder
  (`Playwright/demo_*`).

**Data outputs** live in `exploration/woolworths/data/`:
- `part2_cookies.json` — Playwright-captured full cookie jars (Greymouth, Glenfield,
  Baseline). Generated at runtime by `explore_woolworths_api_part2.py`.
- `store_id_mapping.json` — (optional) `pickupAddressId → fulfilmentStoreId/areaId`
  mapping written by `explore_woolworths_api_part4.py`.

---

## Phase 1: Initial API Probing — Global Pricing Appears; No Programmatic Store Switch
### `explore_woolworths_api_part1.py`

**Goal**: Enumerate the `/api/v1` surface, understand the data model, and establish a
baseline for pricing behaviour.

**Key Tests**:
1. **Full catalogue browse** (`target=browse`) with sort options: relevance,
   `PriceAsc`, `PriceDesc`, `CUPAsc`
2. **dasFilter taxonomy discovery** — tested 6+ facet chain formats (Department, Aisle,
   Shelf) against the semicolon-delimited format
3. **Shell context** (`/api/v1/shell`) — extracted `context.fulfilment` object showing
   default `fulfilmentStoreId: 9171`
4. **Pickup addresses** (`/api/v1/addresses/pickup-addresses`) — enumerated all store
   records; confirmed **NO bridge keys** (`siteDataId`, `externalId`, etc.) exist
5. **Price comparison across `fulfilmentStoreId` query params** — **ZERO price changes**
   across 3 store IDs (baseline, `9171`, `1225718`). Concluded: **global pricing via
   query params**
6. **POST store-switch endpoints** — tested 9 endpoints with 3 payload variants
   (`storeId`, `pickupAddressId`, `fulfilmentStoreId`). **All 404**. No programmatic
   store switch via API.

**Critical Finding**: The API appeared to use **global pricing**. Per-store pricing (if
it existed) was NOT accessible via query parameters, and there was no REST endpoint to
switch the active store. The pricing signal must live elsewhere.

---

## Phase 2: Cookie Injection Discovery — Per-Store Pricing Exists, Carried by Cookies
### `explore_woolworths_api_part2.py`

**Goal**: Test if browser-side store selection sets cookies that control pricing.

**Strategy**:
- **Step 1**: URL-param seeding — visit `?pickupStoreId=xxx` and check if API prices
  change. **FAILED** — prices identical.
- **Step 2**: Playwright cookie capture — headed Chromium visits the store-selection
  modal, selects Greymouth / Glenfield, captures the full 67-cookie jar. Inject into a
  `requests.Session` and test the API.
  - **RESULT**: **PRICES DIFFER!** Greymouth Milk 3L = $7.15, Glenfield = $7.33.
    Per-store pricing **CONFIRMED**.
  - Cookie jars saved to `data/part2_cookies.json`.
  - Cookie diff: 67 cookies captured, but which one(s) carry store context?
- **Step 2b**: Isolate `session_state` (Optimizely) cookie only. **FAILED** — both
  stores return $7.33.
- **Step 2c**: Isolate `RT` (Adobe Analytics) cookie only. **FAILED** — both stores
  return $7.33.
- **Step 3**: URL-param exploration on GET `/` with various params. **FAILED** — no
  price differences.

**Key Discovery**: The full Playwright cookie jar works. The store context is carried by
**cookies, not URL params**. But 67 cookies is fragile — the minimal required set had to
be identified.

### `explore_woolworths_api_part3.py`

**Goal**: Validate cookie jars via `/api/v1/shell` and isolate the single cookie that
controls store context.

- **Step 1**: Shell validation — inject full Playwright jars, call `/api/v1/shell`.
  - Greymouth: `fulfilmentStoreId = 9009` (NOT 9171) ✅
  - Glenfield: `fulfilmentStoreId = 9443` (NOT 9171) ✅
  - Baseline (no cookies): `fulfilmentStoreId = 9171` (default)
- **Step 2**: `fulfilmentStoreId` as query param (no cookies). **FAILED** — shell
  context stays at 9171, prices unchanged.
- **Step 3**: `cw-lrkswrdjp` cookie analysis.
  - Greymouth: `dm-Pickup,f-9009,a-224,s-38`
  - Glenfield: `dm-Pickup,f-9443,a-440,s-38`
  - Fields: `dm`=delivery method, `f`=fulfilmentStoreId (**KEY**), `a`=areaId,
    `s`=site (constant 38)
- **Step 3b**: Inject `cw-lrkswrdjp` + `session_state` only.
  - Greymouth: shell `fulfilmentStoreId = 9009` ✅, Milk 3L = $7.15 ✅
  - Glenfield: shell `fulfilmentStoreId = 9443` ✅, Milk 3L = $7.33 ✅
- **Step 3c**: Inject `cw-lrkswrdjp` ONLY (no `session_state`).
  - Both stores: shell context correct, prices correct ✅
- **Step 3c variant**: `dm-Pickup,f-9009,a-0,s-38` (areaId=0). **WORKS** ✅
- **Step 3c variant**: `dm-Pickup,f-9009` (minimal). **WORKS** ✅

**Critical Findings**:
1. **`cw-lrkswrdjp` is the SOLE per-store cookie** — the other 66 cookies are irrelevant
2. **Format**: `dm-Pickup,f-{fulfilmentStoreId},s-38` (areaId optional, `s-38` constant)
3. **`fulfilmentStoreId` ≠ `pickupAddressId`** — different internal IDs, no formulaic
   relationship
4. **`fulfilmentStoreId` NOT available from any API endpoint** — only seen in the
   Playwright-captured cookie

### `explore_woolworths_api_part4.py`

**Goal**: Build the `cw-lrkswrdjp` cookie programmatically for ALL stores without
Playwright at runtime.

**Breakthrough Discovery**: `extra1` in `woolworths_store_data.json` (from the CDX API)
**IS the `fulfilmentStoreId`**!

| Store | extra1 | cookie `f-` field | Match? |
|-------|--------|-------------------|--------|
| Greymouth | 9009 | 9009 | ✅ |
| Glenfield | 9443 | 9443 | ✅ |
| Birkenhead | 9101 | 9101 | ✅ |

**Steps**:
1. **Step 1**: Playwright capture for 3 stores → parse `cw-lrkswrdjp` → extract
   `fulfilmentStoreId` + `areaId`
2. **Step 2**: Validate `extra1` from `woolworths_store_data.json` matches the captured
   `fulfilmentStoreId`
3. **Step 3**: Construct cookies programmatically using `build_cw_lrkswrdjp(fsid, aid)`
4. **Step 4**: Validate via `/api/v1/shell` — all 3 stores return the correct
   `fulfilmentStoreId`
5. **Step 5**: Validate via `/api/v1/products` — Greymouth $7.15 ✅, Glenfield $7.33 ✅
6. **Step 6**: Compare constructed cookie vs full Playwright jar — **PRICES IDENTICAL** ✅

**Critical Constraint**: **Fresh `requests.Session` per store** — the server's
`Set-Cookie` on `GET /` overwrites an injected `cw-lrkswrdjp` on a reused session.

---

## Phase 3: extra1 Collision Investigation — Fulfilment IDs are Not Unique
### `explore_extra1_collisions.py`
### `explore_extra1_deepdive.py`

**Background**: While validating production pricing, it was discovered that 3 pairs of
physically different stores share the same `extra1` (fulfilment) value in the CDX data.
This threatens the assumption that `extra1` uniquely identifies a store for pricing.

**Colliding pairs**:
| extra1 | Store A | Store B |
|--------|---------|---------|
| 9290 | Nelson Junction (extra2=4166071, site.id=9290) | Motueka (extra2=767216, site.id=9495) |
| 9112 | Te Puke (extra2=913417, site.id=9448) | Bureta Park (extra2=1175393, site.id=9050) |
| 9511 | Bridge Street (extra2=1207646, site.id=9033) | Matamata (extra2=911335, site.id=9120) |

**`explore_extra1_collisions.py`** — for each colliding pair:
1. Loads BOTH stores' full CDX metadata (all extra fields, site.id, etc.)
2. Queries the live API with each store's `extra1` as the cookie key (current hypothesis)
3. ALSO queries with `extra2` (pickupAddressId) and `site.id` as alternative keying
   strategies
4. Compares prices for a fixed query ("milk") across all three keying strategies

**`explore_extra1_deepdive.py`** — digs further:
1. Checks all extra fields (extra1–extra15) in CDX for both stores
2. Queries the shell endpoint with `extra1` and dumps the FULL JSON (looking for
   disambiguating storeName/address/city/region)
3. Queries a product search and dumps the full product response for store-specific
   metadata

**Findings** (full investigation in `docs/project/logs.md` §63):
- **Only 3 of the 6 colliding stores are reachable** via the `cw-lrkswrdjp` cookie.
- The unreachable store of each pair silently returns its **fulfilment partner's**
  prices rather than erroring.
- This means `extra1` is a *fulfilment* store ID, not a unique physical-store key.
- Practical impact: the affected pairs (Nelson Junction/Motueka, Te Puke/Bureta Park,
  Bridge Street/Matamata) may report one store's prices for the other. This is a known
  limitation of the cookie-based approach, documented in `Woolworths_API.md` §8.

---

## Phase 4: Department Taxonomy & Playwright Reference Demos
### `demo_woolworths_departments.py` (top level)
### `Playwright/demo_woolworths_scrape.py`
### `Playwright/demo_woolworths_change_store.py`

**Goal**: Retain self-contained, runnable references for the product taxonomy and the
original Playwright store-selection / scraping flows that predated the cookie-injection
API path. All Playwright-dependent scripts live in the `Playwright/` subfolder; the
taxonomy walkthrough (pure `requests`) lives at the top level alongside the `explore_*`
probes.

### `demo_woolworths_departments.py`

Prints the full Woolworths product taxonomy — 14 top-level departments and their aisle
sub-departments — fetched live from the API:
1. `GET /api/v1/shell` — extracts department slugs from `mainNavs[1]` (Browse)
2. For each department, `GET /api/v1/products?target=browse&dasFilter=Department;;<slug>;false&size=1`
   — the response `dasFacets[]` contains the aisle-level breakdown

```
Department Name  (/slug, N products)
  [aisle_id]  Aisle Name                          (N products)
```

Usage: `python -m exploration.woolworths.demo_woolworths_departments`

### `Playwright/demo_woolworths_scrape.py`

Headed-Chromium (`Playwright/demo_*`) DOM scrape of Woolworths search results. Before
the cookie-injection path was proven, this extracted product title / unit price / price
directly from rendered `product-stamp-grid` entries (with `.product-entry` selectors).
Now retained as a reference for how the rendered search page is structured; it is **not**
the production path.

Usage: `python -m exploration.woolworths.Playwright.demo_woolworths_scrape`

### `Playwright/demo_woolworths_change_store.py`

Playwright reference for programmatically selecting a store via the change-pick-up-store
modal. Navigates directly to `/bookatimeslot/(hww-modal:change-pick-up-store)`, uses the
"All Pick up locations" area dropdown, selects a target store (Woolworths Birkenhead),
and saves rendered HTML snapshots to `.Temp/`. The resulting cookie state (including
`cw-lrkswrdjp`) is the starting point used by the `explore_woolworths_api_part2.py`
capture flow.

Usage: `python -m exploration.woolworths.Playwright.demo_woolworths_change_store`

---

## Exploration Timeline Summary

| Phase | Script | Key Discovery |
|-------|--------|---------------|
| 1 | `explore_woolworths_api_part1` | API surface mapped; appeared to use global pricing via query params; no POST store-switch; no bridge keys in pickup-addresses |
| 2 | `explore_woolworths_api_part2` | **Per-store pricing EXISTS** via Playwright cookie injection ($7.15 vs $7.33); URL-params and isolated session_state/RT fail |
| 2 | `explore_woolworths_api_part3` | **`cw-lrkswrdjp` is the ONLY cookie needed**; format decoded `dm-Pickup,f-{f},a-{a},s-38`; a-/s- optional |
| 2 | `explore_woolworths_api_part4` | **`extra1` = `fulfilmentStoreId`** in CDX data; programmatic construction works for all stores; 21/21 products differ |
| 3 | `explore_extra1_collisions`, `explore_extra1_deepdive` | **3 collision pairs share `extra1`**; only 3 of 6 stores reachable; partners silently share prices |
| 4 | `demo_woolworths_departments` | 14-department / aisle taxonomy enumeration from `/shell` + `dasFilter` |
| 4 | `Playwright/demo_woolworths_scrape`, `Playwright/demo_woolworths_change_store` | Playwright store-selection + DOM-scrape references (pre-cookie path) |

---

## Files in This Folder (Operational Order)

```
exploration/woolworths/
├── Exploration.md                             # This file
├── data/                                      # Runtime-generated data outputs
│   ├── part2_cookies.json                     # Playwright jars (Greymouth, Glenfield, Baseline) — from part2
│   └── store_id_mapping.json                  # pickupAddressId → fulfilmentStoreId/areaId — from part4
│
├── Phase 1: Initial API Probing ──────────────────────────────────
├── explore_woolworths_api_part1.py            # Endpoint enumeration, dasFilter, shell, pickup-addresses, price comparison
│
├── Phase 2: Cookie Injection Discovery ───────────────────────────
├── explore_woolworths_api_part2.py            # URL-param seeding FAILS → Playwright cookie capture → per-store pricing CONFIRMED
├── explore_woolworths_api_part3.py            # Shell validation + cw-lrkswrdjp isolated as SOLE cookie (format decoded)
├── explore_woolworths_api_part4.py            # extra1 = fulfilmentStoreId; programmatic cookie construction; 21/21 validated
│
├── Phase 3: extra1 Collision Investigation ───────────────────────
├── explore_extra1_collisions.py               # Colliding pairs (9290/9112/9511); 3-key comparison over live API
├── explore_extra1_deepdive.py                 # Full CDX + shell + product dumps for collision disambiguation
│
└── Phase 4: Department Taxonomy & Playwright Reference ───────────
    ├── demo_woolworths_departments.py           # 14-department / aisle taxonomy walkthrough (pure requests)
    └── Playwright/
        ├── demo_woolworths_scrape.py            # Headed-Chromium DOM scrape reference (pre-cookie path)
        └── demo_woolworths_change_store.py      # Modal store-selection reference (cw-lrkswrdjp source)
```

---

## Invocation Convention

Since `exploration/` is treated as a Python package, all scripts run via `python -m`.
Playwright scripts need the `playwright` dependency installed and a headed Chromium
(no `headless=False` workaround for the store-selection flow).

```bash
python -m exploration.woolworths.explore_woolworths_api_part1
python -m exploration.woolworths.explore_woolworths_api_part2    # generates data/part2_cookies.json
python -m exploration.woolworths.explore_woolworths_api_part3    # consumes data/part2_cookies.json
python -m exploration.woolworths.explore_woolworths_api_part4    # generates data/store_id_mapping.json
python -m exploration.woolworths.explore_extra1_collisions
python -m exploration.woolworths.explore_extra1_deepdive
python -m exploration.woolworths.demo_woolworths_departments
python -m exploration.woolworths.Playwright.demo_woolworths_scrape
python -m exploration.woolworths.Playwright.demo_woolworths_change_store
```

---

## Production Code (Not in Exploration Folder)

The exploration directly enabled these production modules:

| File | Purpose |
|------|---------|
| `src/NZMealOptimiser/pricing/woolworths_api.py` | Cookie-based API module: `create_session()`, `set_store_context()`, `search_products()`, `find_cheapest()`, `get_nearby_stores()`, `geocode()` |
| `tools/woolworths/woolworths_optimiser.py` | Thin CLI: delegates step 1 (geocode → nearby stores → fresh session per store → cookie injection → ingredient search) to `optimiser_utils.woolworths_querier`, then step 2 `optimise()` |
| `tools/woolworths/woolworths_setup.py` | Fetches `woolworths_store_data.json` from CDX API (source of `extra1`/`extra2`) and builds `woolworths_stores.csv` |

---

## Key Gotchas Documented

1. **Fresh session per store** — a reused session gets its `cw-lrkswrdjp` overwritten by
   the server's `Set-Cookie` on `GET /`
2. **`x-requested-with: ??` header mandatory** — omission returns HTTP 400
3. **Cookie domain must be `www.woolworths.co.nz`** (not `.woolworths.co.nz`)
4. **`extra1` = `fulfilmentStoreId`**, `extra2` = `pickupAddressId` — different numbers,
   no formula
5. **Playwright `headless=False` required** — the site blocks headless Chromium
6. **21/21 products show price differences** between Greymouth and Glenfield — per-store
   pricing is real
7. **`s-38` is constant** across all tested stores — safe to hardcode
8. **`areaId` not in any API** — would need Playwright to capture, but optional
9. **`extra1` is not unique** — 3 collision pairs (9290/9112/9511); only 3 of 6 stores
   reachable via the cookie (see `Woolworths_API.md` §8, `logs.md` §63)

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

---

## Current Status

The exploration is **complete**. The cookie-based per-store pricing path is
production-ready and implemented in `woolworths_api.py` + `optimiser_utils.py`
(`woolworths_querier`). It is continuously referenced in `Woolworths_API.md` §8–§10,
`decision.md`, and `logs.md` §63.

The only known limitation is the `extra1` collision caveat (3 unreachable stores out of
the affected pairs), which is documented and accepted — see `Woolworths_API.md` §8 and
`logs.md` §63.
