# Vue Dashboard — `src/NZMealOptimiser/web/frontend/`

## Overview

A single-page Vue 3 app that drives the optimiser: form input → **resolve setup** (verify dish + location) → live job progress → results (store comparison + product tables), with an OpenStreetMap view of the searched stores, an ingredient preview card, an always-on pipeline console, and a device-GPS option that bypasses Nominatim geocoding. It is the only consumer of the job-based API (`POST /optimise/jobs` / `GET /optimise/{id}`); see `FastAPI.md` for the backend contract.

Built with Vue CLI 5, no router, no state library. Two components: `App.vue` (all state, one `setup()`) and `components/MapPanel.vue` (Leaflet map, props in / events out). Styling lives entirely in `styles.css` (SFCs have no `<style>` block).

---

## Build & Toolchain

| Item | Value |
|---|---|
| Framework | Vue 3.5 (Composition API), core-js 3 |
| Map | Leaflet 1.9.4 (+ OSM raster tiles, no API key) |
| Bundler | `@vue/cli-service` 5 (`npm run build`) |
| Source | `frontend/src/` (`main.js`, `App.vue`, `components/MapPanel.vue`, `styles.css`) |
| Output | `frontend/../static/vue/` — i.e. `src/NZMealOptimiser/web/static/vue/` |
| Public path | `/static/vue/` (set in `vue.config.js`; assets only resolve when served by uvicorn, not `file://`) |

**Workflow:** edit `src/` → `npm run build` → commit generated `static/vue/`. Never hand-edit files under `static/vue/`.

`main.js` is three lines: create the app, mount it, import `styles.css`. ESLint config lives inline in `package.json` (`no-console: warn`, vue3-essential rules).

---

## State Model (`setup()` in App.vue)

### Form & results (pre-existing)
- `form` — reactive `{ dish, address, distance_km, portions, max_stores_per_company, companies[] }`, bound to the search panel; `companies` pre-checked for all 3 brands.
- `dishes` — fetched from `GET /dishes` on mount; keeps `{key, label, ingredients[]}` per dish (ingredients feed the preview card).
- `result` — the final `OptimisationResult` (drives both result panels).
- `addressHistory` — last 5 addresses persisted in `localStorage["meal-addresses"]`.
- `expandedStores` — Set of expanded store-card keys. `storeSort` orders the store-comparison panel.
- **Filter bar** — `excluded` (per-column Sets of deselected categorical values; empty Set = column unfiltered), `textFilters` (`returned_ingredient`/`sku` substrings), `numSortKey`/`numSortDir`, and `openFilter` (which popover is open). See "All-results filter bar" below.

### Two-step resolve (setup → compare)
- `origin` — ref `{lat, lon, source: "gps"|"geocoded"}` set by the resolve step; `resolving` while the `/geocode` round-trip is in flight; `resolved` = `!!origin`; `readyToCompare` = resolved && not stale.
- The submit button is **dual-use**: "Resolve setup" (amber) until dish + location are verified, then "Compare prices" (green `.is-ready`). Disabled until `canResolve` (`dish && (gps || address)`); `actionHint` explains what's missing.
- `resolveSetup()` — GPS lock → origin immediately; otherwise `GET /geocode?address=…` (server-side Nominatim + LRU cache). Failure surfaces in the error banner.
- **Stale detection**: a watcher on a settings signature (`dish|address|portions|max_stores|distance|companies`) marks `staleNotice` when anything changes after a successful resolve. The button flips back to "Resolve setup", an amber `.notice-banner` appears ("Parameters changed — check to resolve settings"), and the console gains a matching `[SYS]` warn line — while the map and recipe previews stay live.
- **Store preview**: on resolve success (and whenever distance/companies/max-stores change while an origin exists) the app calls `GET /stores/nearby` into `previewStores` — the same stores, cap, and ordering pipeline Phase 2 will query. Pins show brand colours + distances with a "Price preview" tooltip line; real `store_costs` take over once a run completes. Clearing the origin clears the preview.
- `dishIngredients` — computed from the selected dish's curated ingredients; rendered in the ingredient-preview card and always live. This card is the future hook for LLM-resolved ingredients + approval (see Roadmap #1).

### GPS & map
- `gps` — ref holding `{lat, lon}` when a device location is locked, else `null`; `gpsBusy` while `navigator.geolocation` is in flight. Locking disables the address input (and its `required`) and shows a dismissible green chip with the coordinates.
- `mapOrigin` — computed: resolved `origin` first, else the run's `result.origin` fallback.
- `mapStores` — `result.store_costs` filtered to entries with coords; `winnerKey` — key of the cheapest store (★ pin); both feed `MapPanel`.
- Client-side NZ bounding-box check (`NZ_BOUNDS`) mirrors the server's so an obviously-outside device fails fast without a round-trip.

### Live job object
```js
const job = reactive({ id, status, phase, companies[], events[],
                       total_tasks, done_tasks, products_found,
                       error_detail, elapsed });
let cursor = -1;      // last event index received from the snapshot API
let pollTimer;        // setTimeout handle for the next poll
let tickTimer;        // setInterval handle for the local elapsed ticker
let pollRun = 0;      // monotonically increasing run token
```

Derived computeds: `jobVisible` (`status !== 'idle'` → shows/hides the whole live area), `jobRunning` (`queued|running`), `overallPct` (`done/total`), `elapsedDisplay`.

Module constants: `POLL_MS = 700`, `RING_CIRCUMFERENCE = 2π·20` (matches the SVG ring geometry below), `CAT_COLUMNS` + `catLabels` (the five categorical filter columns).

---

## Run Lifecycle

1. **`primaryAction()`** — the dual-use submit: if `resolved`, calls `runOptimise()`; otherwise `resolveSetup()`. **`runOptimise()`** clears `error`/`result`, resets `job`, bumps `pollRun` (a stale-loop guard: any in-flight poll from a previous run sees a token mismatch and exits), POSTs the form to `/optimise/jobs`, stores `job.id`, starts the local ticker, then kicks off `poll(run)`. A failed POST (e.g. unknown company → sync 400) surfaces `detail` in the error banner. The payload always includes `latitude`/`longitude` from the resolved origin (so the backend skips Nominatim); GPS runs replace `address` with `"Device GPS location"`. Typed addresses still update `addressHistory`; GPS runs don't.
2. **Ticker** — every 250 ms adds `+0.25` to `job.elapsed` while `jobRunning`, so the timer moves smoothly between server polls. Snapshots converge it via `Math.max(local, server)`.
3. **`poll(run)`** — sequential loop (no overlapping fetches): GETs `/optimise/{id}?events_since={cursor}`, calls `applySnapshot`, re-arms itself with `setTimeout(POLL_MS)` until status is terminal. Transient network errors are swallowed and retried; only a token mismatch or terminal status ends the loop.
4. **`applySnapshot(d)`** — assigns counters/phase/status, replaces `job.companies` wholesale once non-empty (stores are discovered mid-run, so the tiles appear progressively), appends new events and advances `cursor`, captures `error_detail`, and assigns `d.result` to `result` the moment it appears (results render while the console keeps streaming).
5. **`finishJob()`** — stops timers, clears `loading`; on `status === 'error'` promotes `error_detail` into the banner.

There is no SSE/WebSocket yet — polling was chosen deliberately (works through every proxy, no server changes beyond the snapshot endpoint). The cursor parameter keeps payloads tiny regardless of event volume.

---

## Progress Visualisations

### Overall bar
`width = overallPct%` on a gradient fill with a CSS width transition. Before store discovery (`total_tasks === 0`) the bar gets an `.indeterminate` shimmer: an absolutely-positioned pseudo-element swept left→right by the shared `slide-strip` keyframes.

### Brand tiles
One card per company. Brand identity comes from a single custom property (`--brand` set by `.tile-paknsave|-newworld|-woolworths`) applied as a **4px left accent border** plus the ring stroke and shimmer underline — so the company reads as coloured while the completion tick stays colour-neutral (ink stroke).

The ring is an SVG circle (`r=20`, `stroke-width=5`) rotated −90°:

```js
strokeDashoffset = RING_CIRCUMFERENCE * (1 - stores_done/stores_total)
```

with `stroke-dasharray: 125.66` (circumference) and a CSS transition on `stroke-dashoffset` — fraction updates animate as a smooth sweep. Three visual states:
- **unknown** (`stores_total` falsy): `.ring-idle` swaps to a dashed segment spinning continuously (indeterminate).
- **running**: partial arc + a brand-coloured shimmer line along the tile bottom (`.is-running::after`).
- **complete**: full circle + neutral ink check path (`M15.5 24.5l6 6 11-12.5`).

Product counts use `font-variant-numeric: tabular-nums` so digits don't jitter as counters tick.

### Terminal console
Dark panel (`#0e161d`) with a mac-style header (traffic-light dots + uppercase title + live event count). **Always visible** and unconditionally pinned to the bottom: `terminalEl` refs the `.terminal-body` div (the actual scroll container — NOT the outer `.terminal` section), and a watcher on `consoleLines.length` runs `scrollTerminal()` on every change, which sets `el.scrollTop = el.scrollHeight` after `nextTick()`. Every printed line jumps the view to the newest output; there is no user-scroll override.

Content = `feed` + `job.events` (`consoleLines`). `feed` is an append-only event log of setup activity — there are no persistent status lines; each state change prints once:

| Event | Tag | Kind | Trigger |
|---|---|---|---|
| dashboard online | `SYS` | phase | once on mount |
| recipe refreshed · dish · N searches | `DISH` | ok/warn | dish selection changes |
| gps locked / gps cleared / address changed | `LOC` | ok/warn | location source changes |
| geocoded "addr" → lat, lon | `LOC` | ok | resolve success |
| location refreshed · N stores in range · R km | `LOC` | ok | store preview fetched (resolve + distance/company/max changes) |
| settings resolved — ready to compare | `SYS` | ok | resolve success |
| parameters changed — check to resolve settings | `SYS` | warn | settings edited after resolve |

Feed lines are timestamped with the **system clock (`HH:MM`)**; run events keep server-relative `[+12.4s]` stamps:

| Piece | Class | Notes |
|---|---|---|
| Timestamp | `.t-time` | `HH:MM` for feed lines, `+s.s` for run events; tabular-nums, right-aligned |
| Tag chip | `.t-tag tag-pns/nw/ww/sys/dish/loc` | Brand-coloured pills; SYS/DISH/LOC have their own muted tones |
| Message | `.t-text` | Coloured by kind: `.t-phase` white bold, `.t-warn` amber, `.t-err` red, `.t-done` green bold |

The scrollbar is themed to match the terminal (WebKit `::-webkit-scrollbar` + Firefox `scrollbar-color`: dark track `#0c141b`, slate thumb `#2f4457`). While running, a blinking caret line (`steps(1)` keyframe animation) sits under the stream.

---

## Map (`components/MapPanel.vue`) & GPS

The home screen is **one 2×2 rectangle** (`.home-grid`, collapses to a single column below 1080 px) built with `grid-template-areas`:

```
┌──────────────────────────┬──────────────────────┐
│ form   (search panel)    │ recipe (ingredients) │
├──────────────────────────┼──────────────────────┤
│ terminal (pipeline log)  │ map   (nearby stores)│
└──────────────────────────┴──────────────────────┘
```

All four cards stretch to fill their cells. The console starts skinny (fits its boot lines, `min-height: 96px`) and extends vertically as events stream, capping at 420px with internal scroll; the map fills the rest of its row (`flex: 1`, `min-height: 340px`), so the block stays rectangular while it grows. Live progress remains a separate thin full-width strip that only appears while a job exists.

### Leaflet usage
- Plain imperative Leaflet 1.9.4 inside `setup()` — no Vue wrapper library. Init happens in `onMounted`, `map.remove()` in `onBeforeUnmount`; a `ResizeObserver` on the container calls `invalidateSize()` (covers the responsive column collapse, which otherwise leaves grey tiles).
- Tiles: standard OSM raster tiles with the required attribution; default view centred on NZ (`[-41.2, 172.8], z5`).
- **Pins are `L.divIcon`s**, not image markers — brand colour comes from `BRAND_COLORS` inline styles (single source shared with the legend), and this sidesteps Leaflet's classic webpack broken-icon problem. The cheapest store gets a larger ★ pin; the origin gets a dark diamond with a CSS `pulse-ring` animation.
- Hover tooltips show store name, company, distance, total used cost and an unresolved-search warning line; HTML-escaped via a small `escapeHtml` helper.
- A dashed `L.circle` shows the search radius around the origin; it tracks the Distance dropdown live via a `radiusKm` watcher.
- On any data change the map refits: `fitBounds(points).pad(0.25)` capped at zoom 14, or `setView` when only one point exists.

### Interactions
- Clicking a pin emits `select-store({company, store})`; App expands that store card (if collapsed) and smooth-scrolls it into view — the card anchor is `` id="store-card-{key}" ``.
- "Use my location" → `getCurrentPosition` (high accuracy, 10 s timeout); success locks `gps`, permission denial / timeout / outside-NZ all degrade gracefully to the typed-address flow with an explanatory banner message.
- While idle the map shows NZ-wide with a hint pill ("Run a comparison to plot nearby stores"); locking GPS previews your position immediately.

---

## Results Rendering

- **Store cards**: ranked list sorted by `total_used_cost` (or name/company via `storeSort`). Key = `` `${company}-${store}` `` — matches the backend's `(company, store_name)` grouping guarantee (same-name collisions are rejected server-side). Expand/collapse toggles membership in `expandedStores`.
- **Issue surfacing**: if `store.issues` is non-empty, the collapsed row shows `⚠ n failed` and the expanded detail opens with an amber note listing each unresolved term and its status (`error`/`no_match`) — so a cheap total with missing ingredients is visible at a glance.
- **All-results filter bar** (replaces the old company/price dropdowns). Default ordering is `company → store → search_ingredient` (alphabetical, multi-key):
  - *Categorical popovers* — Company, Store, Search term, Brand, Status. Each is a button + absolutely-positioned checkbox list built from `catOptions` (unique sorted values observed in `result.rows`). Checking/unchecking toggles membership in `excluded[column]`; the button shows a live `shown/total` counter that turns amber while filtered. Popovers close on any outside click (document-level listener) but survive clicks inside via `@click.stop` on the wrapper.
  - *Text lookups* — case-insensitive substring inputs for returned product name and SKU (`textFilters`).
  - *Numeric sort* — dropdown for Price / Purchase qty / Purchase cost with an asc↔desc direction toggle; "default" falls back to the alphabetical multi-key order. Filters apply first, then sorting, inside one `filteredRows` computed (always on an array copy).
  - State resets at the start of every run via `resetFilters()`.
- **Product table**: row key includes sku + ingredient to stay unique.
- **Formatters**: `money` (blank-safe `$x.xx`), `usedPrice`/`unitPrice` prefix `~` when `status === 'approximate'`, `recipe()` composes quantity + unit + optional approx fallback ("1 can (~400 g)"), `pack()` joins pack size fields.

---

## Backend Contract (summary)

| Call | When | Response used for |
|---|---|---|
| `GET /dishes` | on mount | Dish dropdown + ingredient preview |
| `GET /geocode?address=…` | "Resolve setup" click (non-GPS) | `{lat, lon, cached}` — verifies the address before comparing |
| `GET /stores/nearby?lat&lon&distance_km&companies&max_per_company` | resolve success + distance/company/max changes while resolved | `{origin, stores[]}` — pre-run map preview pins (capped like the run) |
| `POST /optimise/jobs` | "Compare prices" submit | `{ job_id }` |
| `GET /optimise/{id}?events_since=N` | every ~700 ms | Snapshot: status/phase/counters/companies/events/result |
| `GET /health` | — (manual) | Liveness check |

Event shape: `{i, t, kind, co, text}` where `i` is the global index matched against `events_since`, `co` ∈ `PNS|NW|WW|null`, `kind` ∈ `phase|info|ok|warn|err|done`. Full field reference in `FastAPI.md`.

---

## Gotchas

- **Always rebuild** after editing `frontend/src/` — uvicorn serves only the compiled bundle.
- `publicPath` is absolute (`/static/vue/`) → the built page must be reached through the FastAPI server at `/app`, never opened from disk.
- Polls intentionally survive transient failures; a persistent 404 means the job id was evicted (only possible after 40 newer jobs have finished) or the server restarted — there's no resume, just start a new run.
- `pollRun` token matters: without it, a slow poll from run N could interleave with run N+1's reset and resurrect old timers.
- Keep `no-console` clean — debug leftovers will trip lint warnings on build.
- Leaflet needs `invalidateSize()` after its container changes size (grid collapse, tab switches) — currently handled by the `ResizeObserver`; if you move the map into something hidden by default, trigger it on reveal.
- Store pins require `lat`/`lon` on `store_costs` entries — they come from the brand store CSVs server-side; don't try to join by store name client-side.

---

## Roadmap (tracked, NOT implemented)

Planned functionality that the current structure anticipates. UI hooks already in place are noted so future work slots in without a rewrite:

1. **LLM requery of generated ingredients** with an approval step before hitting supermarket APIs — the two-step button ("Resolve setup" → "Compare prices") is the seam: the resolve phase can grow an ingredient-resolution call + approval UI inside the ingredient-preview card, and only then unlock "Compare prices".
2. **NLP refiltering of brands / product names** (e.g. organic only), updatable post-run — the all-results filter bar is the natural host; `excluded`/`textFilters` state shape generalises to rule objects, and rows already carry `brand`/`returned_ingredient`.
3. **RAG-style recipe generation from a URL + Recipe instructions page** — first real second page; introduce the router then, promote `MapPanel`-style extraction for shared pieces (chips, badges, tables), and keep the home grid as the landing layout.
4. **Proper best-price optimisation + repicking interface** for approved ingredients — store-card `best_per_ingredient` rows become selectable pickers; `storeKey` identity and per-store grouping carry over unchanged.
5. **Download / email recipe + shopping list** — actions bar on the results heading; backend gains an export endpoint, frontend just POSTs current selection.
6. **Advanced settings page** (pipeline sources, persistent DB link, LLM credentials/models) — keep client-side only as a settings page reading/writing a config endpoint; never bake secrets into the bundle.

General guidance: prefer extracting components over growing `App.vue`, keep new pages under a router lazily, and reuse the brand-colour tokens (`BRAND_COLORS` / CSS vars) rather than hardcoding hexes.
