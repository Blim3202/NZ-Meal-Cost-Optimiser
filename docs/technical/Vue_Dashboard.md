# Vue Dashboard — `src/NZMealOptimiser/web/frontend/`

 This file documents *what exists, where, and the key logic contracts* (state machines, payload shapes, gotchas) — deliberately skipping visuals/CSS internals and code dumps. Full API field reference lives in `FastAPI.md`.

## Overview

Vue 3 (Composition API) frontend for the optimiser, served by FastAPI at `/` (production) and `/test` (sandbox). Both entries render the same **app shell**: a fixed left sidebar switches between the optimiser dashboard (preset/custom/shopping-list recipe modes), My Dishes, an LLM Recipe Builder, a Documentation viewer and a multi-section Settings page, with a Leaflet/OSM map, live pipeline console, and GPS support. They are the only consumers of the job-based API (`POST /optimise/jobs` / `GET /optimise/{id}`).

## Build & Toolchain

| Item | Value |
|---|---|
| Framework | Vue 3.5, Vue CLI 5, no router/state library |
| Markdown | `marked` ^12 — renders `/tech-docs` manuals client-side in the Documentation view |
| Syntax highlight | `highlight.js` (core + `python`/`bash`/`json` only, github-dark theme) — wired as a `marked` code-fence renderer in `DocsView.vue` |
| Map | Leaflet 1.9.4 + OSM tiles |
| Build | `npm run lint` → `npm run build` (run inside `frontend/`) |
| Pages | Multi-page via `vue.config.js`: `index` → `static/vue/index.html` (`main.js`/`App.vue`, served at `/`), `test` → `static/vue/test.html` (`test-main.js`/`TestApp.vue`, served at `/test`) |
| Output | `src/NZMealOptimiser/web/static/vue/` — **never hand-edit; always rebuild after editing `src/`** |
| Public path | `/static/vue/` (absolute — pages only work through uvicorn, not `file://`) |

ESLint config lives inline in `package.json`; keep `no-console` clean.

## Contents

- [Overview](#overview)
- [Build & Toolchain](#build--toolchain)
- [Source Map](#source-map)
- [How `/test` and `/` diverge today](#how-test-and--diverge-today)
- [Behaviour Notes](#behaviour-notes)
- [Key Logic Reference](#key-logic-reference)
- [Backend Contract](#backend-contract)
- [Future plans / room to expand](#future-plans--room-to-expand)
- [Gotchas](#gotchas)

## Source Map

```
src/                            # PRODUCTION tree → `/`
├── App.vue                     # shell: AppSidebar + <component :is> view switcher (topbar subtitle: "/app")
├── main.js                     # entry point (create app, import styles.css)
├── test-main.js                # test entry: mounts TestApp.vue with src/test/styles.css
├── styles.css                  # ALL styling (SFCs have no <style> block)
├── settings.js                 # reactive settings store → localStorage 'meal-settings';
│                               #   applies --content-max / --font-scale CSS vars to :root
├── filterStore.js              # scoped filter state (preset / custom / shopping_list scopes);
│                               #   rules carry includes / excludes / brand_includes / brand_excludes
├── views/                      # sidebar pages (switched by App.vue shell, no router)
│   ├── DashboardView.vue       # the optimiser; exposes loadPreset(key, edit) + loadDraft(payload)
│   ├── MyDishesView.vue        # dish library: Open/Edit/Delete + User/Curated badges
│   ├── RecipeBuilderView.vue   # LLM Recipe Builder — paste text → /dishes/import_text → review → save or open-in-builder
│   ├── DocsView.vue            # markdown viewer over GET /tech-docs (+ marked)
│   └── SettingsView.vue        # display / units / advanced / LLM models / danger-zone sections
├── components/
│   ├── AppSidebar.vue          # dark ink nav rail; gear/Settings pinned bottom;
│   │                           #   icon rail ≤1080px, overlay drawer ≤768px (pure CSS widths)
│   ├── DishBuilder.vue         # recipe editor (rows of ingredient/qty/unit/search term)
│   ├── FilterEditor.vue        # per-ingredient include/exclude keyword chips
│   │                           #   (product filters; parent owns the term→filters map)
│   ├── FilterTunerPanel.vue    # live filter editor — 3 subcards (ingredient counters / rule editor / per-store product audit)
│   ├── ResultsTabs.vue         # tabbed Summary / Filter tuner / All results card
│   ├── SummaryPanel.vue        # ranked store list + summaryBasis ⇄ Purchase-cost toggle + Auto refine
│   ├── AllResultsPanel.vue     # CSV export + sortable all-results table (Status split into Unit + Ingredient)
│   ├── BrandAutocomplete.vue   # Photon/keyword brand picker used by FilterTunerPanel
│   ├── NumberPopover.vue       # numeric popover for distance / max-stores (Settings overrides mode)
│   ├── AddressAutocomplete.vue # Photon-backed address dropdown (replaces the old <datalist>)
│   ├── PipelineConsole.vue     # terminal-style event log
│   ├── ProgressStrip.vue       # overall bar + per-brand SVG ring tiles
│   ├── ResultsSection.vue      # store cards + all-results table (legacy — kept for ResultsTabs)
│   └── MapPanel.vue            # Leaflet map; emits select-store + pick-origin; draggable origin pin
├── composables/
│   ├── useJobRunner.js         # shared job engine: POST /optimise/jobs, cursor polling,
│   │                           #   elapsed ticker, console feed + event merge
│   ├── useLlmModels.js         # LLM model catalog hook (Settings → LLM Models card)
│   └── useViewport.js          # shared resize listener → {width, isMobile, isCompact}
├── resultUtils.js              # winnerKeyOf / storesOf — result-vs-preview pin selection
└── unitOptions.js              # unit list + aliases mirrored from backend UNIT_ALIASES
                                #   (ALIASES exported — Settings unit-reference table reads it)
```

## How `/test` and `/` diverge today

`src/test/` is a near-mirror of `src/` — every Vue component, view, composable, and the shared `resultUtils.js` / `unitOptions.js` / `settings.js` / `styles.css` are byte-for-byte identical between the two trees (verified via `Compare-Object` after the most recent promote). The only real divergences today are:

1. **App shell topbar** — `src/App.vue` (prod) shows the `/app` subtitle; `src/test/TestApp.vue` (sandbox) shows the `/test workspace` subtitle. This is the only intentional divergence the promote script (`tools/frontend/promote_test_to_app.ps1`) preserves — it rewrites `/test workspace` → `/app` while copying files from `src/test/` → `src/`.
2. **`App.vue` vs `TestApp.vue`** — the only intentional source difference above. The script's "Review the diff of `src/App.vue` before committing" banner is the right safety check.
3. **`filterStore.js` content** — historically the sandbox copy sometimes carries newer rule shapes (`brand_includes` / `brand_excludes` arrays) that the prod copy is missing. After the most recent sync both copies carry the same shape; before any future promote, verify with `Compare-Object (Get-Content src/filterStore.js) (Get-Content src/test/filterStore.js)` so a stale sandbox copy can't silently regress the prod rule shape.

> **Practical consequence:** the historical "this feature is `/test` only" annotations in older docs and code comments no longer hold. New features should be built in the sandbox, QA'd at `/test`, and then promoted via `tools/frontend/promote_test_to_app.ps1` + rebuild — that workflow remains the only sanctioned path for getting a `/test` change to `/`.

## Behaviour Notes

The behavioural details below are grouped by view. Cross-cutting rules (responsive, polling, danger-zone overrides) are at the end.

### Optimiser dashboard (DashboardView.vue)

- **Two-step flow**: dual-use submit button — "Resolve setup" (`GET /geocode` or GPS lock) until dish + location are verified, then "Compare prices". Settings changes after resolve flip it back (stale notice) and refresh a `/stores/nearby` map preview.
- **Address autocomplete** (`AddressAutocomplete.vue`): the address field is a debounced (300 ms) Photon search-as-you-type dropdown — see `FastAPI.md` §Geocoding providers for why Photon and not Nominatim. 5–8 suggestions per query with `display`, `lat`, `lon`, `type`, `postcode`; keyboard nav (↑/↓/Enter/Esc), click-outside dismiss, ✕ clear button. The selected suggestion's coords are used directly (no second Nominatim round-trip). 400/502 surface as a red banner in the dropdown; "no matches" is a friendly hint, not an error. The "Search by Photon / OpenStreetMap contributors" attribution is mandatory (ODbL).
- **Map click-to-pick + draggable origin** (`MapPanel.vue`): clicking the map background OR dragging the dark origin pin emits `pick-origin` → `onPickOrigin()` sets a new `origin = {lat, lon, source: "picked"}` (third source alongside `'gps'` / `'geocoded'`) and re-runs the preview immediately. A "Click anywhere on the map (or drag the pin) to pick a location" hint sits over the map until an origin is set. A debounced `GET /geocode/reverse?lat&lon` (Photon) fetches a real street label that gets written into the address field; a teal "📍 Pinned · …" chip with ✕ replaces the GPS chip while picked. The address-input watch skips programmatic writes via a `_suppressAddressReset` counter so the picked label doesn't immediately kill the pin.
- **Pure manual GPS picking**: the map pick path never calls Nominatim forward-geocoding (Nominatim is still used for `/geocode` on submit). Photon handles both keystroke suggestions and the pin → label reverse. The `'picked'` source is a discriminator so the existing `'gps'` and `'geocoded'` flows are unchanged.
- **Dish builder**: edit ingredients inline (quantity/unit/search term, optional ≈ fallbacks), run immediately, or "Save as preset" → `POST /dishes/save`. Runs send the recipe as `custom_dish` with its `base_portions`; the server scales to requested portions. "Clear all" (confirm-guarded) wipes the rows plus dish name/base portions. In custom mode the form card also offers **"Generate custom ingredients"** → `POST /dishes/generate` (LLM-drafted rows + filter-rule seeding; confirm-guarded when rows already exist).
- **Shopping list**: third recipe-source mode. Reuses the builder rows but submits `custom_dish {dish_name: "Shopping list", base_portions: 1, source_label: "shopping_list"}` with `portions: 1` — quantities priced as-is, no scaling; the Portions input is hidden and results show a teal "Shopping list" chip. Draft rows carry over between custom ↔ shopping modes.
- **CSV export**: "Download CSV ↓" on the All-results heading exports the current *filtered/sorted* view via a client-side `Blob` → `<a download>` click (native browser save dialog). UTF-8 BOM for Excel; raw numeric price columns; filename `<slugified-dish>-<date>.csv`. Gated behind the `csvDownload` prop (`ResultsSection` default false; `DashboardView.vue` binds it on).
- **Product filters**: every ingredient row (all three recipe modes) has a collapsible "Product filters" editor (`FilterEditor.vue`) with include/exclude **title** keyword chips. The tuner panel (`FilterTunerPanel.vue`) also exposes **brand** include/exclude chips (green/red), always empty by default and never auto-populated by the LLM or `data/dish_filters.json`. Title rules use AND-semantics (every keyword must fuzzy-match the product name); brand rules use OR-semantics for includes (any match passes) and reject-on-match for excludes — both use the same `contains_word` Levenshtein matcher (≤ 0.35, case-insensitive, partial-word). **Filter pass order: brand first, then title** — a brand rejection wins even when the title would also fail, and `filter_reason` records the winning failure. Preset scopes seed once from `GET /dish_filters` (`data/dish_filters.json`); edits live in a per-user localStorage store (`meal-filters-v1`, `_seen` marker prevents deleted keywords resurrecting) and "Reset filters" restores the curated baseline when it drifts. Runs send the active keywords as `ingredient_filters`; rejected products come back flagged (`valid_ingredient: false` + reason) and are skipped by store costs — shown dimmed with a red "filtered" badge in the All-results table.
- **Reapply / AI instruction / Auto refine (post-run filter flow)**: after a run, the Filter tuner is the central control surface. (1) Its rule editor adds an **AI instruction** textarea (universal dish-wide sentence, e.g. `"only red onions, no flavoured milk"` — works across all ingredients regardless of which term is selected) + `Generate filters` → `POST /optimise/{id}/ai_filter_preview`. The server builds a deduped `{Ingredient, Terms, Brands}` summary per search term from the cached rows in Python (no word cap, no rows sent to the LLM) and feeds an injection-guarded `<<instruction>>` prompt to the configured filter model, returning `compiled_filters` + a dry-run `matched/total` preview per ingredient plus any truncation/vocab warnings; the user sees the suggested chip diff and clicks **Apply** to merge them additively into the scope (capped 15/list, 40 chars). (2) **Auto refine** — dish-wide button in **both** Filter tuner and Summary (`POST /optimise/{id}/auto_cull_preview {current_filters}`) asks the same filter model for up to **15 `excludes` + 15 `brand_excludes` per ingredient**, most irrelevant first, grounded strictly to the vocab; the preview is additive (`current ∪ suggestions`) and capped 15/list, shown as `N new · matched/total` per ingredient before Apply. No mutation until `reapply`. Summary and tuner share the same `filterStore[scope]` so either entry point stays in sync. Both endpoints surface 8+ keyword suggestions per term, capped 8/list, then the normal live preview/reapply takes over. See `LLM_Pipeline.md` §AI Instruction Compiler.
- **Results**: store cards ranked complete-basket-first; missing ingredients render as blank "not found" rows (`status: "not_found"` → red label) plus the amber ⚠ issues banner; ★ winner pin goes to the first complete store.
- **Filter bar**: categorical popovers + text lookups + numeric sort over `result.rows`; state resets each run.
- **Tabbed results card (`ResultsTabs.vue`)**: the dashboard replaces the stacked comparison + all-results panels with one `ResultsTabs.vue` card — **Summary / Filter tuner / All results**. The card is always visible and defaults to the Filter tuner (works pre-run off the builder rows); Summary and All results show a "Compare prices to view this table" placeholder until a run completes, at which point the card auto-jumps to Summary — except when the swap came from this card's own **Apply filters** (`suppressJumpOnce()` exposed via `defineExpose`), which keeps you on the tuner and raises a right-edge toast ("N filter changes applied — check Summary for updated comparisons", with an Open-summary action, 6 s auto-dismiss). The live progress strip is likewise always rendered, idling on an "Awaiting request…" placeholder until a job starts. Summary re-ranks stores client-side from `result.rows` under a Used-cost ⇄ Purchase-cost toggle (persisted in `meal-settings` as `summaryBasis`; eligibility = `valid_ingredient !== false && used_price != null`, units-match wins ties) with #1 auto-expanded, plus a "Best across stores" smart-basket mode (`basketMode`) that picks the cheapest eligible product per ingredient across all shops. Filter tuner moves keyword editing into three subcards stacked ~⅓ / ~⅔ — ingredients + rules in the left column (Include Term / Exclude Term / Include Brand / Exclude Brand — CamelCase, brand labels green/red), a full-height per-store product audit right (6 columns: Ingredient / Search result / Brand / Quantity / Price / Match status with matched/filtered pills) — driven by debounced `POST /optimise/{id}/filter_preview` dry-runs; its **Apply filters** button calls the existing reapply endpoint (the legacy amber bar is gone). All results splits Status into Unit Match + Ingredient Match columns and adds click-to-sort headers (blank values sink). Builder rows show a passive "n rules" chip deep-linking to the tuner.

### My Dishes (MyDishesView.vue)

- **My Dishes**: card grid from `GET /dishes`; badge derives from each entry's `source` field (`"user"` = saved via the builder, absent = curated). Edit/Open emit the shell handoff above; Delete → `DELETE /dishes/{key}` with an extra warning line when deleting curated dishes.

### LLM Recipe Builder (RecipeBuilderView.vue)

- **Workflow**: paste recipe text (≤1000 chars) into a `<textarea>` → `POST /dishes/import_text {recipe_text, dish_name, base_portions, notes}` → preview the LLM-drafted ingredients + filter rules in a review table → either **Save as preset** (`POST /dishes/save`) or **Open in dish builder** (emits `open-draft` on the shell, which `App.vue` forwards to `DashboardView.loadDraft(payload)`). The full request/response contract is in `FastAPI.md` §`/dishes/import_text`.
- **Rejection handling**: an HTTP 200 with `{"status": "rejected", "reason": ..., "base_portions": N}` is a soft-fail — the page surfaces the reason as a gentle notice (not a red error banner). Only genuine pipeline failures (502 / 503) show an error.
- **Filter seeding**: when the imported payload has non-empty `filters`, the page calls the same `seedPresetRules` helper the builder uses, so the rules land in the user's per-scope filter store and survive the handoff into the dashboard.
- **Handoff to dashboard**: the `open-draft` event is a second cross-view handoff (in addition to My Dishes' `open-dish`). Both go through the shell's `App.vue` event listener, which calls the right method on `DashboardView` (`loadPreset` for My Dishes, `loadDraft` for the Recipe Builder). `loadDraft` is intentionally distinct because the payload is a raw LLM draft (custom_dish-shaped), not a saved preset key.

### Documentation (DocsView.vue)

- **Documentation**: lists `GET /tech-docs`, fetches raw markdown per file, renders with `marked` into `.doc-body` (v-html of trusted repo content). Code blocks go through a `highlight.js` renderer (python/bash/json registered — add more via `hljs.registerLanguage`); the `github-dark` theme is imported at the top of `styles.css`.

### Settings (SettingsView.vue)

- **Sections**: Display · Units · Advanced · LLM Models · Danger zone — all sections of UI prefs persist as one JSON blob in `meal-settings`. `exclude_non_food`, `summaryBasis` (`'used' | 'purchase'`), `basketMode` (`'single' | 'best-across'`) and `overridesArmed` all ride along on the same blob; the latter is the consent flag for unlocking the Danger-zone inputs.
- **Display**: content-width presets + UI-scale slider (applied instantly via `--content-max` / `--font-scale` CSS vars on `:root`).
- **Units**: read-only alias table from `unitOptions.js` (mirrors backend `UNIT_ALIASES`).
- **Advanced**: live thread-pool slider (20–40, step 5 via `POST /system/thread-pool`, blocked with 409 while jobs are running) + non-food category filter toggle (`exclude_non_food`, persisted server-side via `PUT /llm/settings`).
- **LLM Models**: ingredient + filter model pickers (Mistral / Google), refresh button (`POST /llm/models/refresh`, isolated per-provider failures), Save/Restore against `PUT /llm/settings`. Catalog is file-cached (`data/llm_models_cache.json`) and seeded on first call. Powered by `composables/useLlmModels.js`.
- **Danger zone**: overrides toggle gated behind an accept-risk modal ("I accept" required; disarming needs no confirm).

### App shell + cross-cutting (App.vue / TestApp.vue / AppSidebar.vue)

- **App shell**: `App.vue` (production) / `TestApp.vue` (sandbox) are thin shells — `AppSidebar` + `<component :is>` view switcher over `views/`. No vue-router: navigation is a plain ref (`currentView`), so there are no deep links. Two cross-view handoffs go through the shell:
  - `open-dish {key, edit}` — My Dishes → Dashboard; shell navigates then calls the dashboard's exposed `loadPreset(key, edit)` after `nextTick`.
  - `open-draft payload` — LLM Recipe Builder → Dashboard; shell navigates then calls the dashboard's exposed `loadDraft(payload)` (handles raw LLM drafts, not saved presets — see the Recipe Builder section above).
- **Responsive**: layout is pure CSS — fluid `clamp()` type/padding, `auto-fit/minmax` grids, three breakpoints (768 / 1080 / 1440) mirroring `useViewport.js`. Sidebar: full labels on desktop, icon rail ≤1080px, hamburger + overlay drawer ≤768px. Content width and UI scale come from CSS vars (`--content-max`, `--font-scale`) that `settings.js` writes to `:root`.
- **Polling**: ~700 ms `setTimeout` loop with an incremental `events_since` cursor; a monotonic `pollRun` token guards against stale polls across runs.
- **Danger-zone overrides**: when armed, the dashboard swaps Distance/Max-stores selects for number inputs (caps 50 km / 20 stores, clamped client-side and enforced server-side by `HARD_LIMITS`), and shows an amber "Overrides active" chip. Disarming clamps values back into the standard ranges.

## Key Logic Reference

### `useJobRunner.js` — run engine (shared by both pages)
- **Console merge**: `consoleLines = [...feed, ...job.events]`. Pages write setup activity via `logLine(kind, co, text)` (wall-clock `HH:MM`, `boot: true`); polled server events render with `+12.4s`-style stamps. PipelineConsole receives the merged array.
- **Elapsed ticker**: local tick adds `+0.25` every 250 ms while running; snapshots converge it via `Math.max(local, server)`.
- **`start(payload)`**: clears result/job → POST `/optimise/jobs` → bumps the monotonic `pollRun` token → starts ticker + poll loop. A failed POST surfaces `detail` and resets to idle.
- **Poll loop**: ~700 ms sequential `setTimeout`; transient fetch errors are swallowed and retried. Exits only on terminal status or a token mismatch (`run !== pollRun`) — that guard is what stops a stale poll from run N leaking into run N+1.
- Exposed surface consumed by both pages: `{job, result, loading, error, logLine, start, reset, jobRunning, overallPct, elapsedDisplay, terminalTitle, consoleLines}`.

### Dish builder (`views/DashboardView.vue` + `DishBuilder.vue`)
- `recipeMode` toggles preset↔custom↔shopping. Switching to custom **always resets the builder** (rows, dish name, base portions) *and* clears the shared `custom` filter scope — a blank slate for a new recipe, so stale rules from a previous custom dish can never leak in ("Customise ✎" bypasses `setMode` and still copies any preset into the draft); rows carry local `row-N` ids for stable v-for keys.
- **LLM generation**: "Generate custom ingredients" (custom mode only, enabled once the dish name is filled) → `POST /dishes/generate` → maps returned rows into builder rows via the same shape as `loadIntoDraft`, replaces the whole `custom` filter scope with the returned rules, logs each backend warning to the console, and marks setup stale if an origin was resolved.
- **`validRows()` serialisation contract**: trim term → require `quantity > 0` → `normaliseUnit(unit)` → approx pair only when `approx_quantity > 0` (else both null). This exact shape is reused verbatim for *both* the `custom_dish` run payload and `POST /dishes/save`.
- `duplicateTerms` (case-insensitive) blocks resolve+save and highlights offending rows in DishBuilder.
- Save flow: overwrite `confirm()` if key exists → POST → refetch dishes → flip back to preset mode → mark setup stale if an origin was resolved.
- Scale chips (`×N → M portions`) are **display-only** — real scaling happens server-side in `_scale_ingredients_to_portions`. Shopping mode passes 1/1 so the chip reads "Base recipe · 1 portion".
- Mode-specific validation: custom requires name + rows; shopping requires rows only (name is fixed). The stale-detection `recipeSignature` scopes by mode (shopping tracks just the rows JSON).
- Template-ref surface for the shell: `loadPreset(key, edit=false)` (selects a saved preset, optionally jumping straight into custom/edit mode — used by My Dishes Open/Edit) and `loadDraft(payload)` (hands a raw LLM draft from the Recipe Builder into the dish builder — payload shape matches the `POST /dishes/import_text` success body, including `notes` which rides along to `Save as preset`).
- `applyGeneratedFilters(filters)` is the shared filter-seeding function used by both `loadDraft` and the LLM generation path (`POST /dishes/generate`); it normalises shape, drops empties, and merges into the per-scope filter store with `_seen` markers so deleted keywords can't resurrect.

### Settings store (`settings.js`)
- Reactive singleton `{contentWidth, uiScale, overridesArmed}` persisted wholesale to localStorage on every change; `applyDisplaySettings()` mirrors display values onto `:root` as `--content-max` / `--font-scale` CSS vars (the shell re-applies on window resize so hard refreshes and tab restores stay consistent).
- `overridesArmed` is only ever set true through SettingsView's accept-risk modal — treat it as a user consent flag, not a preference.

### App shell (`App.vue` / `TestApp.vue`) + `AppSidebar.vue`
- `VIEWS` registry maps ids → components; sidebar emits `navigate(id)`, shell swaps `<component :is>`. Adding a page = new view file + one registry entry + one nav item.
- Sidebar icons are inline SVG strings (`ICONS` map); active item gets an orange left bar. Rail/drawer behaviour is pure CSS media queries — JS only closes the drawer when leaving mobile widths.

### `ResultsSection.vue`
- Parent-facing API via template ref: `focusStore(pin)` (map pin → expand card + smooth-scroll) and `resetFilters()` (called before every run). Also resets itself on `result` change via watcher.
- Store sort re-implements the server ranking client-side: incomplete stores last, then ascending `total_used_cost`.
- Numeric sorts sink rows lacking the chosen value to the bottom regardless of direction.
- Statuses are snake_case in the payload: `statusLabel()` renders them spaced ("not found"), `statusClass()` maps to CSS (`not_found` → red `.status-not-found`).
- `downloadCsv()` (only mounted when the `csvDownload` prop is set — `DashboardView.vue` binds it): serialises `filteredRows` with proper quote/comma escaping, prefixes a UTF-8 BOM, and triggers the download via a temporary object-URL anchor.

### `MapPanel.vue`
- `BRAND_COLORS` / `COMPANY_LABELS` are the single source for pin + legend colours; pins are inline-styled `L.divIcon`s (winner gets ★).
- Tooltip distinguishes pre-run pins ("Price preview — run Compare prices") from completed runs ($ total used cost + ⚠ issue count).
- `fitView`: no points → NZ-wide view; one point → `setView` zoom ≥ 13; else `fitBounds(...).pad(0.25)` capped at zoom 14.
- The origin marker is `draggable: true` and the map background is wired to `map.on('click', ...)` — both emit `pick-origin` with `{lat, lon}` so the dashboard can set `origin.source = 'picked'`. The pin carries `cursor: grab` / `:active { cursor: grabbing }` to advertise the affordance.
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

> The pre-shell single-page `App.vue` was retired when the sandbox UI was promoted to `/`. DashboardView is the only optimiser implementation per tree; intentional divergence now happens between the `src/` and `src/test/` trees — reconcile via the promote script, never by editing production files ad hoc.

## Backend Contract

| Call | When | Response used for |
|---|---|---|
| `GET /dishes` | on mount | Preset dropdown + ingredient preview (+ `source` badge in My Dishes) |
| `GET /geocode?address=…` | "Resolve setup" (non-GPS) | `{lat, lon, cached}` |
| `GET /stores/nearby?…` | resolve success / settings change | Pre-run map preview pins |
| `POST /dishes/save` | "Save as preset" | Upsert into `data/dishes.json` (tags `"source": "user"`) |
| `POST /dishes/generate` | "Generate custom ingredients" (custom mode) | `{ingredients, filters, warnings}` — LLM-drafted recipe + seeded filter rules (503 = missing API key, 502 = generation failed) |
| `DELETE /dishes/{key}` | My Dishes delete | Removes the preset; returns `{was_user, dishes_count}` |
| `GET /system-info` | Settings mount | Effective/configured thread-pool workers + slider bounds + `running_jobs` count + `HARD_LIMITS` |
| `GET /system/running-jobs` | Settings slider popover | `{count: N}` polled every 2 s while the slider is open to gate the Apply button while a job runs |
| `GET /tech-docs[/{name}]` | Documentation view | Manual list / raw markdown (whitelisted files only) |
| `GET /llm/models` | Settings → LLM Models mount | Cached catalog from Mistral + Google + active selection; seeds cache on first call |
| `POST /llm/models/refresh` | Settings → LLM Models "Refresh" button | Re-fetches both providers, isolated per-provider failures, overwrites `data/llm_models_cache.json` |
| `GET /llm/settings` | Settings → LLM Models on mount | `{ingredient_model, filter_model, exclude_non_food}` |
| `PUT /llm/settings` | Settings → LLM Models "Save" | Persist model selection (provider ∈ {mistral, google}, non-empty model_id, model_id exists in catalog) → `data/llm_settings.json` atomically. `LLMConfigError` → 400. |
| `POST /optimise/jobs` | submit | `{ job_id }` |
| `GET /optimise/{id}?events_since=N` | every ~700 ms | Snapshot: status/phase/counters/events/result |
| `GET /dish_filters` | on mount | Curated include/exclude presets for seeding preset scopes |
| `POST /optimise/{id}/reapply` | "Reapply filters" (tuner) | Recalculated result from cached rows (no new API calls) |
| `POST /optimise/{id}/filter_preview` | Filter tuner (debounced) | Dry-run preview of pending filters: per-term matched/total counters + per-product list, no mutation |
| `POST /optimise/{id}/update_ingredients` | "Update ingredient prices" (builder) | Partial refresh — added/renamed terms re-queried against original stores; quantity/unit edits pure rescale |
| `POST /optimise/{id}/ai_filter_preview` | Filter tuner AI instruction | Universal dish-wide sentence → suggested `compiled_filters` + dry-run preview + truncation/vocab warnings (ask-and-confirm before apply) |
| `POST /optimise/{id}/auto_cull_preview` | Summary + Filter tuner Auto refine | Dish-wide auto-cull: up to 15 excludes + 15 brand_excludes per ingredient → additive preview (both pages) before apply |

Event shape `{i, t, kind, co, text}`; full field reference in `FastAPI.md`.

## Future plans / room to expand

Decisions made during the app-shell build-out (Aug 2026) that leave deliberate room to grow. Items already shipped in earlier sections are not re-listed here.

- **Navigation without a router**: both shells switch views via a plain ref + `<component :is>`. When a page needs deep links or history (most likely the LLM Recipe Builder), introduce vue-router in the sandbox (`test`) entry first and map the existing view ids onto routes — the shell template needs almost no change. A FastAPI catch-all serving `test.html` for `/test/*` paths would be required for history-mode URLs; hash mode works with zero backend changes.
- **Editable unit aliases**: the Settings unit table is read-only today. Custom aliases would be frontend-only (merged into `normaliseUnit` lookups) unless the backend gains persistence — note the builder's serialised units must stay backend-canonical, so prefer extending `UNIT_ALIASES` in `llm_utils.py` + `unitOptions.js` together instead.
- **Danger-zone scope**: overrides currently cover distance + stores/company behind hard server caps. Natural extensions (company whitelist overrides, per-run concurrency caps, request pacing) would slot into the same armed-state pattern: gate UI behind `settings.overridesArmed`, enforce real limits server-side in `_new_job`.
- **Recipe / shopping-list export**: the client-side CSV export of the all-results table is live (see `ResultsSection`). A backend endpoint that takes the current selection and returns a markdown / PDF recipe card or a share-link shopping list is still open.

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
- **Origin source discriminator** (`'gps' | 'geocoded' | 'picked'`): the address-input watch skips programmatic writes via a `_suppressAddressReset` counter incremented inside `onPickOrigin` and `onAddressSelect` so the picked label or autocomplete-selected label doesn't immediately wipe the just-set origin. **Never** remove the increment when refactoring these handlers — it would silently break map picking.
- **Nominatim TOS forbids browser autocomplete** (decision #68): `AddressAutocomplete.vue` calls `/geocode/autocomplete` (Photon), never `/geocode` (Nominatim) directly. The Photon attribution under the dropdown is mandatory (ODbL) — keep the link.
- **Photon attribution is ODbL-required** — the dropdown footer links to photon.komoot.io and openstreetmap.org/copyright. Removing those links would put the dashboard in violation of the OSM data license.
