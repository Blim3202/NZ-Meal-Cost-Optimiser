# Vue Dashboard — `src/NZMealOptimiser/web/frontend/`

> **Doc policy — keep entries light.** This file documents *what exists, where, and the key logic contracts* (state machines, payload shapes, gotchas) — deliberately skipping visuals/CSS internals and code dumps; read the source for those. Update the relevant entry here whenever you add or refactor frontend code. Full API field reference lives in `FastAPI.md`.

## Overview

Vue 3 (Composition API) frontend for the optimiser, served by FastAPI at `/app` (standard dashboard) and `/test` (dish builder). Form → resolve setup → live job progress → results, with a Leaflet/OSM map, live pipeline console, and GPS support. It is the only consumer of the job-based API (`POST /optimise/jobs` / `GET /optimise/{id}`).

## Build & Toolchain

| Item | Value |
|---|---|
| Framework | Vue 3.5, Vue CLI 5, no router/state library |
| Map | Leaflet 1.9.4 + OSM tiles |
| Build | `npm run lint` → `npm run build` (run inside `frontend/`) |
| Pages | Multi-page via `vue.config.js`: `index` → `static/vue/index.html` (`main.js`/`App.vue`, served at `/app`), `test` → `static/vue/test.html` (`test-main.js`/`TestApp.vue`, served at `/test`) |
| Output | `src/NZMealOptimiser/web/static/vue/` — **never hand-edit; always rebuild after editing `src/`** |
| Public path | `/static/vue/` (absolute — pages only work through uvicorn, not `file://`) |

ESLint config lives inline in `package.json`; keep `no-console` clean.

## Source Map

```
src/
├── App.vue                    # /app page: all state in one setup()
├── TestApp.vue                # /test page: dish builder + same run/results flow
├── main.js / test-main.js     # entry points (create app, import styles.css)
├── styles.css                 # ALL styling (SFCs have no <style> block)
├── composables/
│   └── useJobRunner.js        # shared job engine: POST /optimise/jobs, cursor polling,
│                              #   elapsed ticker, console feed + event merge
├── components/
│   ├── DishBuilder.vue        # /test recipe editor (rows of ingredient/qty/unit/search term)
│   ├── PipelineConsole.vue    # terminal-style event log
│   ├── ProgressStrip.vue      # overall bar + per-brand SVG ring tiles
│   ├── ResultsSection.vue     # store cards + all-results table (shared by both pages)
│   └── MapPanel.vue           # Leaflet map, props in / events out
├── resultUtils.js             # winnerKeyOf / storesOf — result-vs-preview pin selection
└── unitOptions.js             # unit list + aliases mirrored from backend UNIT_ALIASES
```

Shared components serve both pages; page-specific differences live in `App.vue` vs `TestApp.vue`. Prefer extracting components over growing either page file.

## Behaviour Notes (brief)

- **Two-step flow (/app)**: dual-use submit button — "Resolve setup" (`GET /geocode` or GPS lock) until dish + location are verified, then "Compare prices". Settings changes after resolve flip it back (stale notice) and refresh a `/stores/nearby` map preview.
- **Dish builder (/test)**: edit ingredients inline (quantity/unit/search term, optional ≈ fallbacks), run immediately, or "Save as preset" → `POST /dishes/save`. Runs send the recipe as `custom_dish` with its `base_portions`; the server scales to requested portions.
- **Polling**: ~700 ms `setTimeout` loop with an incremental `events_since` cursor; a monotonic `pollRun` token guards against stale polls across runs.
- **Results**: store cards ranked complete-basket-first; missing ingredients render as blank "not found" rows (`status: "not_found"` → red label) plus the amber ⚠ issues banner; ★ winner pin goes to the first complete store.
- **Filter bar**: categorical popovers + text lookups + numeric sort over `result.rows`; state resets each run.

## Key Logic Reference

### `useJobRunner.js` — run engine (shared by both pages)
- **Console merge**: `consoleLines = [...feed, ...job.events]`. Pages write setup activity via `logLine(kind, co, text)` (wall-clock `HH:MM`, `boot: true`); polled server events render with `+12.4s`-style stamps. PipelineConsole receives the merged array.
- **Elapsed ticker**: local tick adds `+0.25` every 250 ms while running; snapshots converge it via `Math.max(local, server)`.
- **`start(payload)`**: clears result/job → POST `/optimise/jobs` → bumps the monotonic `pollRun` token → starts ticker + poll loop. A failed POST surfaces `detail` and resets to idle.
- **Poll loop**: ~700 ms sequential `setTimeout`; transient fetch errors are swallowed and retried. Exits only on terminal status or a token mismatch (`run !== pollRun`) — that guard is what stops a stale poll from run N leaking into run N+1.
- Exposed surface consumed by both pages: `{job, result, loading, error, logLine, start, reset, jobRunning, overallPct, elapsedDisplay, terminalTitle, consoleLines}`.

### Dish builder (`TestApp.vue` + `DishBuilder.vue`)
- `recipeMode` toggles preset↔custom. The builder **auto-seeds from the selected preset on first switch**; "Customise ✎" copies any preset into the draft; rows carry local `row-N` ids for stable v-for keys.
- **`validRows()` serialisation contract**: trim term → require `quantity > 0` → `normaliseUnit(unit)` → approx pair only when `approx_quantity > 0` (else both null). This exact shape is reused verbatim for *both* the `custom_dish` run payload and `POST /dishes/save`.
- `duplicateTerms` (case-insensitive) blocks resolve+save and highlights offending rows in DishBuilder.
- Save flow: overwrite `confirm()` if key exists → POST → refetch dishes → flip back to preset mode → mark setup stale if an origin was resolved.
- Scale chips (`×N → M portions`) are **display-only** — real scaling happens server-side in `_scale_ingredients_to_portions`.

### `ResultsSection.vue`
- Parent-facing API via template ref: `focusStore(pin)` (map pin → expand card + smooth-scroll) and `resetFilters()` (called before every run). Also resets itself on `result` change via watcher.
- Store sort re-implements the server ranking client-side: incomplete stores last, then ascending `total_used_cost`.
- Numeric sorts sink rows lacking the chosen value to the bottom regardless of direction.
- Statuses are snake_case in the payload: `statusLabel()` renders them spaced ("not found"), `statusClass()` maps to CSS (`not_found` → red `.status-not-found`).

### `MapPanel.vue`
- `BRAND_COLORS` / `COMPANY_LABELS` are the single source for pin + legend colours; pins are inline-styled `L.divIcon`s (winner gets ★).
- Tooltip distinguishes pre-run pins ("Price preview — run Compare prices") from completed runs ($ total used cost + ⚠ issue count).
- `fitView`: no points → NZ-wide view; one point → `setView` zoom ≥ 13; else `fitBounds(...).pad(0.25)` capped at zoom 14.
- Radius circle tracks the `radiusKm` prop live; `ResizeObserver` calls `invalidateSize()` on container resize.

### `ProgressStrip.vue`
- Hidden while `job.status === 'idle'`. Overall bar shows an indeterminate shimmer while `running && !total_tasks`.
- Ring = SVG circle (`r=20`, stroke-width 5, rotated −90°), animated via `strokeDashoffset = C × (1 − stores_done/stores_total)` with `C = 2π·20`. Three states: **idle** (dashed segment spinning — `stores_total` falsy), **running** (partial arc + brand-coloured shimmer underline), **done** (full circle + ink check path).

### `PipelineConsole.vue`
- Pure props component (`title`, `lines`, `running`). A watcher on `lines.length` pins scroll to bottom after `nextTick()` — every printed line jumps the view; there is no user-scroll override. Blinking caret line while `running`.

### Shared helpers
- `unitOptions.js`: the `SCALABLE` set (`g/kg/oz/ml/l/tsp/tbsp/cup/each/pack`) drives DishBuilder's ≈ fallback prompt (`needsApprox`); `ALIASES` mirror backend `UNIT_ALIASES` incl. the one-way `egg/eggs → each` alias.
- `resultUtils.js`: `winnerKeyOf` = first store where `complete !== false`, else first store overall; `storesOf` = coords-filtered `store_costs` once a result exists, else the `/stores/nearby` preview list.

> **App.vue ↔ TestApp.vue duplication is deliberate**: resolve/GPS/preview/stale-signature logic (~150 lines) exists in both pages so each can diverge freely. Mirror any edits to this logic in **both files** (or extract into a composable later).

## Backend Contract

| Call | When | Response used for |
|---|---|---|
| `GET /dishes` | on mount | Preset dropdown + ingredient preview |
| `GET /geocode?address=…` | "Resolve setup" (non-GPS) | `{lat, lon, cached}` |
| `GET /stores/nearby?…` | resolve success / settings change | Pre-run map preview pins |
| `POST /dishes/save` | "Save as preset" (/test) | Upsert into `data/dishes.json` |
| `POST /optimise/jobs` | submit | `{ job_id }` |
| `GET /optimise/{id}?events_since=N` | every ~700 ms | Snapshot: status/phase/counters/events/result |

Event shape `{i, t, kind, co, text}`; full field reference in `FastAPI.md`.

## Roadmap (tracked, NOT implemented)

Planned functionality that the current structure anticipates. UI hooks already in place are noted so future work slots in without a rewrite:

1. **LLM requery of generated ingredients** with an approval step before hitting supermarket APIs — the two-step button ("Resolve setup" → "Compare prices") is the seam: the resolve phase can grow an ingredient-resolution call + approval UI inside the ingredient-preview card, and only then unlock "Compare prices".
2. **NLP refiltering of brands / product names** (e.g. organic only), updatable post-run — the all-results filter bar is the natural host; `excluded`/`textFilters` state shape generalises to rule objects, and rows already carry `brand`/`returned_ingredient`.
3. **RAG-style recipe generation from a URL + Recipe instructions page** — first real second page; introduce the router then, promote `MapPanel`-style extraction for shared pieces (chips, badges, tables), and keep the home grid as the landing layout. *(Note: `/test` now exists as a second page via multi-page build — no router yet; this item would introduce one.)*
4. **Proper best-price optimisation + repicking interface** for approved ingredients — store-card `best_per_ingredient` rows become selectable pickers; `storeKey` identity and per-store grouping carry over unchanged.
5. **Download / email recipe + shopping list** — actions bar on the results heading; backend gains an export endpoint, frontend just POSTs current selection.
6. **Advanced settings page** (pipeline sources, persistent DB link, LLM credentials/models) — keep client-side only as a settings page reading/writing a config endpoint; never bake secrets into the bundle.

General guidance: prefer extracting components over growing `App.vue`/`TestApp.vue`, keep new pages under a router lazily, and reuse the brand-colour tokens (`BRAND_COLORS` / CSS vars) rather than hardcoding hexes.

## Gotchas

- Always rebuild after editing `src/` — uvicorn serves only the compiled bundle.
- Keep unit lists/aliases in sync between `unitOptions.js` and backend `UNIT_ALIASES`.
- Store pins need `lat`/`lon` from server-side `store_costs` — don't join client-side.
- Leaflet needs `invalidateSize()` on container resize — handled by a `ResizeObserver` in `MapPanel`.
