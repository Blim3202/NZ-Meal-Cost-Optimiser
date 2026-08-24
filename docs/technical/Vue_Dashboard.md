# Vue Dashboard — `src/NZMealOptimiser/web/frontend/`

> **Doc policy — keep entries light.** This file documents *what exists, where, and the key logic contracts* (state machines, payload shapes, gotchas) — deliberately skipping visuals/CSS internals and code dumps; read the source for those. Update the relevant entry here whenever you add or refactor frontend code. Full API field reference lives in `FastAPI.md`.

## Overview

Vue 3 (Composition API) frontend for the optimiser, served by FastAPI at `/app` (standard dashboard) and `/test` (dish-builder workspace). The `/test` entry is a full **app shell**: a fixed left sidebar switches between the optimiser dashboard (preset/custom/shopping-list recipe modes), My Dishes, an LLM Recipe Builder stub, a Documentation viewer and a multi-section Settings page. Both pages share form → resolve setup → live job progress → results, with a Leaflet/OSM map, live pipeline console, and GPS support. They are the only consumers of the job-based API (`POST /optimise/jobs` / `GET /optimise/{id}`).

## Build & Toolchain

| Item | Value |
|---|---|
| Framework | Vue 3.5, Vue CLI 5, no router/state library |
| Markdown | `marked` ^12 — renders `/tech-docs` manuals client-side in the Documentation view |
| Syntax highlight | `highlight.js` (core + `python`/`bash`/`json` only, github-dark theme) — wired as a `marked` code-fence renderer in `DocsView.vue` |
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
├── TestApp.vue                # /test shell: AppSidebar + <component :is> view switcher
├── main.js / test-main.js     # entry points (create app, import styles.css)
├── styles.css                 # ALL styling (SFCs have no <style> block)
├── settings.js                # reactive settings store → localStorage 'meal-settings';
│                              #   applies --content-max / --font-scale CSS vars to :root
├── views/                     # /test sidebar pages (switched by TestApp shell, no router)
│   ├── DashboardView.vue      # the optimiser (ex-TestApp body); exposes loadPreset(key, edit)
│   ├── MyDishesView.vue       # dish library: Open/Edit/Delete + User/Curated badges
│   ├── RecipeBuilderView.vue  # LLM recipe-from-URL stub (disabled form + roadmap)
│   ├── DocsView.vue           # markdown viewer over GET /tech-docs (+ marked)
│   └── SettingsView.vue       # display / units / advanced / danger-zone sections
├── composables/
│   ├── useJobRunner.js        # shared job engine: POST /optimise/jobs, cursor polling,
│   │                          #   elapsed ticker, console feed + event merge
│   └── useViewport.js         # shared resize listener → {width, isMobile, isCompact}
├── components/
│   ├── AppSidebar.vue         # dark ink nav rail; gear/Settings pinned bottom;
│   │                          #   icon rail ≤1080px, overlay drawer ≤768px (pure CSS widths)
│   ├── DishBuilder.vue        # /test recipe editor (rows of ingredient/qty/unit/search term)
│   ├── PipelineConsole.vue    # terminal-style event log
│   ├── ProgressStrip.vue      # overall bar + per-brand SVG ring tiles
│   ├── ResultsSection.vue     # store cards + all-results table (shared by both pages)
│   └── MapPanel.vue           # Leaflet map, props in / events out
├── resultUtils.js             # winnerKeyOf / storesOf — result-vs-preview pin selection
└── unitOptions.js             # unit list + aliases mirrored from backend UNIT_ALIASES
                               #   (ALIASES exported — Settings unit-reference table reads it)
```

Shared components serve both pages; page-specific differences live in `App.vue` vs `views/DashboardView.vue`. Prefer extracting components over growing either file.

## Behaviour Notes (brief)

- **App shell (/test)**: `TestApp.vue` is a thin shell — `AppSidebar` + `<component :is>` view switcher over `views/`. No vue-router: navigation is a plain ref (`currentView`), so there are no deep links; the dashboard stays at `/test`. My Dishes → Dashboard handoff: `open-dish` event `{key, edit}` → shell navigates then calls the dashboard's exposed `loadPreset(key, edit)` after `nextTick`.
- **Responsive**: layout is pure CSS — fluid `clamp()` type/padding, `auto-fit/minmax` grids, three breakpoints (768 / 1080 / 1440) mirroring `useViewport.js`. Sidebar: full labels on desktop, icon rail ≤1080px, hamburger + overlay drawer ≤768px. Content width and UI scale come from CSS vars (`--content-max`, `--font-scale`) that `settings.js` writes to `:root`.
- **Two-step flow (/app)**: dual-use submit button — "Resolve setup" (`GET /geocode` or GPS lock) until dish + location are verified, then "Compare prices". Settings changes after resolve flip it back (stale notice) and refresh a `/stores/nearby` map preview.
- **Dish builder (/test)**: edit ingredients inline (quantity/unit/search term, optional ≈ fallbacks), run immediately, or "Save as preset" → `POST /dishes/save`. Runs send the recipe as `custom_dish` with its `base_portions`; the server scales to requested portions. "Clear all" (confirm-guarded) wipes the rows plus dish name/base portions.
- **Shopping list (/test)**: third recipe-source mode. Reuses the builder rows but submits `custom_dish {dish_name: "Shopping list", base_portions: 1, source_label: "shopping_list"}` with `portions: 1` — quantities priced as-is, no scaling; the Portions input is hidden and results show a teal "Shopping list" chip. Draft rows carry over between custom ↔ shopping modes.
- **CSV export (/test only)**: "Download CSV ⭳" on the All-results heading exports the current *filtered/sorted* view via a client-side `Blob` → `<a download>` click (native browser save dialog). UTF-8 BOM for Excel; raw numeric price columns; filename `<slugified-dish>-<date>.csv`. Gated behind the `csvDownload` prop so `/app` doesn't show it.
- **My Dishes (/test)**: card grid from `GET /dishes`; badge derives from each entry's `source` field (`"user"` = saved via the builder, absent = curated). Edit/Open emit the shell handoff above; Delete → `DELETE /dishes/{key}` with an extra warning line when deleting curated dishes.
- **Documentation (/test)**: lists `GET /tech-docs`, fetches raw markdown per file, renders with `marked` into `.doc-body` (v-html of trusted repo content). Code blocks go through a `highlight.js` renderer (python/bash/json registered — add more via `hljs.registerLanguage`); the `github-dark` theme is imported at the top of `styles.css`.
- **Settings (/test)**: four sections persisted as one JSON blob in localStorage (`meal-settings`). Display = content-width presets + UI-scale slider (applied instantly via CSS vars); Units = read-only alias table from `unitOptions.js`; Advanced = API-key stub + live thread-pool info from `GET /system-info`; Danger zone = overrides toggle gated behind an accept-risk modal ("I accept" required; disarming needs no confirm).
- **Danger-zone overrides**: when armed, the dashboard swaps Distance/Max-stores selects for number inputs (caps 50 km / 20 stores, clamped client-side and enforced server-side by `HARD_LIMITS`), and shows an amber "Overrides active" chip. Disarming clamps values back into the standard ranges.
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

### Dish builder (`views/DashboardView.vue` + `DishBuilder.vue`)
- `recipeMode` toggles preset↔custom↔shopping. The builder **auto-seeds from the selected preset on first switch to custom**; "Customise ✎" copies any preset into the draft; rows carry local `row-N` ids for stable v-for keys.
- **`validRows()` serialisation contract**: trim term → require `quantity > 0` → `normaliseUnit(unit)` → approx pair only when `approx_quantity > 0` (else both null). This exact shape is reused verbatim for *both* the `custom_dish` run payload and `POST /dishes/save`.
- `duplicateTerms` (case-insensitive) blocks resolve+save and highlights offending rows in DishBuilder.
- Save flow: overwrite `confirm()` if key exists → POST → refetch dishes → flip back to preset mode → mark setup stale if an origin was resolved.
- Scale chips (`×N → M portions`) are **display-only** — real scaling happens server-side in `_scale_ingredients_to_portions`. Shopping mode passes 1/1 so the chip reads "Base recipe · 1 portion".
- Mode-specific validation: custom requires name + rows; shopping requires rows only (name is fixed). The stale-detection `recipeSignature` scopes by mode (shopping tracks just the rows JSON).
- Template-ref surface for the shell: `loadPreset(key, edit=false)` — selects the preset, optionally jumping straight into custom/edit mode (used by My Dishes Open/Edit).

### Settings store (`settings.js`)
- Reactive singleton `{contentWidth, uiScale, overridesArmed}` persisted wholesale to localStorage on every change; `applyDisplaySettings()` mirrors display values onto `:root` as `--content-max` / `--font-scale` CSS vars (the shell re-applies on window resize so hard refreshes and tab restores stay consistent).
- `overridesArmed` is only ever set true through SettingsView's accept-risk modal — treat it as a user consent flag, not a preference.

### App shell (`TestApp.vue`) + `AppSidebar.vue`
- `VIEWS` registry maps ids → components; sidebar emits `navigate(id)`, shell swaps `<component :is>`. Adding a page = new view file + one registry entry + one nav item.
- Sidebar icons are inline SVG strings (`ICONS` map); active item gets an orange left bar. Rail/drawer behaviour is pure CSS media queries — JS only closes the drawer when leaving mobile widths.

### `ResultsSection.vue`
- Parent-facing API via template ref: `focusStore(pin)` (map pin → expand card + smooth-scroll) and `resetFilters()` (called before every run). Also resets itself on `result` change via watcher.
- Store sort re-implements the server ranking client-side: incomplete stores last, then ascending `total_used_cost`.
- Numeric sorts sink rows lacking the chosen value to the bottom regardless of direction.
- Statuses are snake_case in the payload: `statusLabel()` renders them spaced ("not found"), `statusClass()` maps to CSS (`not_found` → red `.status-not-found`).
- `downloadCsv()` (only mounted when the `csvDownload` prop is set — `/test` passes it): serialises `filteredRows` with proper quote/comma escaping, prefixes a UTF-8 BOM, and triggers the download via a temporary object-URL anchor.

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

### Type scale (`styles.css`) — the font-size storyboard

All text sizes come from `--fs-*` tokens defined on `:root`; **never introduce a raw `font-size` for text** — add/reuse a token instead. Every token is wrapped in `calc(<size> * var(--font-scale))`, so the Settings → Display UI-scale slider resizes the entire hierarchy uniformly (body base included).

Storyboard, largest → smallest (percentages are of the 14px body base at scale 100%):

| Token | Size @100% | ~% | Used for |
|---|---|---|---|
| `--fs-display` | clamp(2–3.5rem) | ≤400% | h1 page name ("Meal cost optimiser") |
| `--fs-title` | 2rem | 229% | h2, Documentation reader h1 |
| `--fs-stat-lg` | 1.5rem | 171% | hero numerals (Settings worker count) |
| `--fs-tile` | 1.3rem | 149% | progress-tile counters, doc reader h2 |
| `--fs-heading` | 1.25rem | 143% | h3 panel/card headings |
| `--fs-lead` | 1.05rem | 120% | lede paragraphs, store prices, sidebar brand, doc h3 |
| `--fs-emphasis` | .95rem | 109% | bolded text: tile names, topbar brand, adv-card h4, strip phase, **sidebar nav items**, doc body text |
| *(body inherit)* | 14px | 100% | normal running text (inputs, buttons, banners) |
| `--fs-label` | .85rem | 97% | hints, counts, ingredient lists, secondary meta |
| `--fs-ui` | .8rem | 91% | chips, small buttons, mode notes, tables, console-adjacent UI |
| `--fs-small` | .76rem | 87% | field labels, legends, captions, timestamps-meta |
| `--fs-micro` | .72rem | 82% | badges, status pills, warn hints, italic-style uppercase caps (`.tile-products em`) |
| `--fs-nano` | .7rem | 80% | eyebrows, table headers, filter counts |
| `--fs-mono` / `--fs-mono-tag` | 12px / 9.5px | — | terminal console body / tag pills |

**Documented exceptions** (raw px allowed): map pin glyphs and Leaflet tooltips (`font-size: 10/13/12/12.5px`) — their size is bound to fixed pixel geometry of the pin/overlay boxes. Inline code is the **relational exception**: `--fs-code` (`.84em`) is an em *ratio* of the surrounding text, deliberately NOT multiplied by `--font-scale` (the surrounding text is already scaled — double-scaling would over-inflate); code inside `.adv-card .hint` uses a tighter `.76em` ratio for code nested in already-small text. Everything else must use a token.

### Colour tokens (`styles.css`) — surfaces, status, brands

Same rule as type: repeated colour roles use `:root` tokens; raw hex only for single-use one-offs (hover washes, gradients, spinner alpha, winner-pin glow, ready-button states), the console **tag pills** (`.tag-*` accent tints), and **map-pin overlays** (white rings bound to pin geometry). All blackish surfaces share a blue-grey ramp (~212° hue) so console, doc code blocks and sidebar stay tinted consistently.

| Group | Tokens | Notes |
|---|---|---|
| Surfaces | `--surface` (#fff) · `--surface-soft` (#fbfcfd) · `--surface-muted` (#f3f5f6 disabled wells) · `--surface-dim` (#eef1f3 tracks/curated badge) · `--border-hover` (#b9c4cb) | `--surface` doubles as white ink on dark surfaces; `--field-bg` aliases `--surface-soft` |
| Status | `--ok` (#25803a) · `--approx` (#c56b00 partial-price/approximate) · `--warn/-bg/-line` (#b36a00/#fff8ee/#ffd9a3 chips) · `--err/-bg/-line` (#b42318/#fff0ef/#f5c0ba banners+danger zone) · `--err-alt` (#c62828 table-status red) | disambiguates red/green/amber collisions with brand accents |
| Brands | PNS: `--pns-bg` + text `--amber-text` · NW: `--nw-bg`, `--nw-text` (aliases `--err`) · WW: `--ww-bg/-line/-text` | badge/chip tints per banner |
| Info | `--info/-bg/-line` (#0b7285 trio) | user-dish badges + shopping-mode chip |
| Code | `--code-bg` (#f1f4f5) | inline code chip fill |
| Dark ramp | `--dark-bg` (#121b24 terminal/pre bg) · `--dark-track` (#0f1820 scrollbar) · `--dark-raised` (#182430 header) · `--dark-border` (#243545) · `--dark-scroll/-hover` (#36506c/#456088) · `--console-dim/-faint` (#5e7d92/#89a6bd timestamps/caret) | shared by `.terminal-*`, `.doc-body pre` |
| Sidebar | `--sidebar-bg` (#1b2836 — not `--ink`, keeps body text dark) · `--sidebar-hover/-active` (#26394d/#2c4054) · `--sidebar-line` (#2c3c4b) · `--sidebar-text/-muted/-icon` (#d8e2ec/#8ca1b4/#98b0c5) | nav chrome; lighter than the old #17212b base |

### Spacing scale (`styles.css`) — 4px lattice

`--sp-1`(4px) → `--sp-8`(32px). Apply to `padding`/`gap`/`margin` **only when every component lands on-grid** (e.g. `padding: var(--sp-3) var(--sp-5)`); off-lattice legacy values (`11px 12px`, `14px 16px`, `9px 13px`…) stay raw until a visual-consolidation pass snaps them — do not auto-snap. Spacing is fixed px and deliberately NOT multiplied by `--font-scale`.

> **App.vue ↔ DashboardView.vue duplication is deliberate**: resolve/GPS/preview/stale-signature logic (~150 lines) exists in both pages so each can diverge freely. Mirror any edits to this logic in **both files** (or extract into a composable later).

## Backend Contract

| Call | When | Response used for |
|---|---|---|
| `GET /dishes` | on mount | Preset dropdown + ingredient preview (+ `source` badge in My Dishes) |
| `GET /geocode?address=…` | "Resolve setup" (non-GPS) | `{lat, lon, cached}` |
| `GET /stores/nearby?…` | resolve success / settings change | Pre-run map preview pins |
| `POST /dishes/save` | "Save as preset" (/test) | Upsert into `data/dishes.json` (tags `"source": "user"`) |
| `DELETE /dishes/{key}` | My Dishes delete | Removes the preset; returns `{was_user, dishes_count}` |
| `GET /system-info` | Settings mount | Effective/configured thread-pool workers + `HARD_LIMITS` |
| `GET /tech-docs[/{name}]` | Documentation view | Manual list / raw markdown (whitelisted files only) |
| `POST /optimise/jobs` | submit | `{ job_id }` |
| `GET /optimise/{id}?events_since=N` | every ~700 ms | Snapshot: status/phase/counters/events/result |

Event shape `{i, t, kind, co, text}`; full field reference in `FastAPI.md`.

## Roadmap (tracked, NOT implemented)

Planned functionality that the current structure anticipates. UI hooks already in place are noted so future work slots in without a rewrite:

1. **LLM requery of generated ingredients** with an approval step before hitting supermarket APIs — the two-step button ("Resolve setup" → "Compare prices") is the seam: the resolve phase can grow an ingredient-resolution call + approval UI inside the ingredient-preview card, and only then unlock "Compare prices".
2. **NLP refiltering of brands / product names** (e.g. organic only), updatable post-run — the all-results filter bar is the natural host; `excluded`/`textFilters` state shape generalises to rule objects, and rows already carry `brand`/`returned_ingredient`.
3. **Proper best-price optimisation + repicking interface** for approved ingredients — store-card `best_per_ingredient` rows become selectable pickers; `storeKey` identity and per-store grouping carry over unchanged.
4. **Download / email recipe + shopping list** — actions bar on the results heading; backend gains an export endpoint, frontend just POSTs current selection. *(Partially shipped: client-side CSV export of the all-results table is live on `/test` — see ResultsSection; email/recipe-sheet export still open.)*

## Future plans / room to expand

Decisions made during the app-shell build-out (Aug 2026) that leave deliberate room to grow:

- **Navigation without a router**: `/test` switches views via a plain ref + `<component :is>`. When a page needs deep links or history (most likely the LLM Recipe Builder), introduce vue-router in the `test` entry only and map the existing view ids onto routes — the shell template needs almost no change. A FastAPI catch-all serving `test.html` for `/test/*` paths would be required for history-mode URLs; hash mode works with zero backend changes.
- **Extending the sidebar to `/app`**: App.vue still has no shell. If adopted there, extract the shared resolve/GPS/preview logic from DashboardView into a composable first (the duplication note above), then reuse `AppSidebar` + the same CSS as-is.
- **LLM Recipe Builder wiring**: `views/RecipeBuilderView.vue` is a styled stub with the intended flow documented on-page (fetch URL → LLM extraction → review → prefill builder). The handoff into the builder already exists: emit the dish rows through the same `loadPreset`-style path (or extend it to accept raw ingredient rows) once extraction lands. Backend seam: a new endpoint calling `resolve_ingredients()` against fetched recipe text.
- **Settings persistence**: settings live in localStorage (`meal-settings`) by design — nothing user-specific is trusted server-side yet. If settings must follow a user across devices, add a small key/value config endpoint and sync on mount; keep secrets out either way.
- **Runtime thread-pool resize**: workers are fixed at startup via `WEB_MAX_WORKERS` (see FastAPI.md). A live-resize endpoint is feasible (create pool → `loop.set_default_executor` → `old.shutdown(wait=False)` so in-flight jobs drain) but was deliberately deferred as risky-for-little-gain; the Settings page already shows effective vs configured values so the UI won't need changes if it lands.
- **Editable unit aliases**: the Settings unit table is read-only today. Custom aliases would be frontend-only (merged into `normaliseUnit` lookups) unless the backend gains persistence — note the builder's serialised units must stay backend-canonical, so prefer extending `UNIT_ALIASES` in `llm_utils.py` + `unitOptions.js` together instead.
- **Danger-zone scope**: overrides currently cover distance + stores/company behind hard server caps. Natural extensions (company whitelist overrides, per-run concurrency caps, request pacing) would slot into the same armed-state pattern: gate UI behind `settings.overridesArmed`, enforce real limits server-side in `_new_job`.

General guidance: prefer extracting components over growing `App.vue`/`TestApp.vue`, keep new pages under a router lazily, and reuse the brand-colour tokens (`BRAND_COLORS` / CSS vars) rather than hardcoding hexes.

## Gotchas

- Always rebuild after editing `src/` — uvicorn serves only the compiled bundle.
- Keep unit lists/aliases in sync between `unitOptions.js` and backend `UNIT_ALIASES`.
- Store pins need `lat`/`lon` from server-side `store_costs` — don't join client-side.
- Leaflet needs `invalidateSize()` on container resize — handled by a `ResizeObserver` in `MapPanel`.
- Global `table { min-width: 980px }` is intentional for results tables — any new table (docs reader, settings) must override it locally like `.doc-body table` / `.unit-table` do.
- Settings are per-browser localStorage; clearing site data resets display prefs and disarms overrides.
- The sidebar is fixed-position: new pages must render inside the shell's `.app-main` (or set their own left margin) or they'll slide under it.
- `marked` renderer signatures differ by major: v12 calls `code(code, infostring)` positionally, v13+ passes a `{ text, lang }` token. The `DocsView.vue` renderer accepts both — keep it dual-signature when upgrading `marked`.
