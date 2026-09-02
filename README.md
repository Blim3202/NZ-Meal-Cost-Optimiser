# NZ Meal Cost Optimiser

Finds the cheapest nearby supermarket for any dish. Type an address and a meal and the app searches every Pak'nSave, New World and Woolworths within reach, prices each ingredient to the gram (or ml, or fillet), and ranks the stores by total basket cost.

The web dashboard is the primary surface. A CLI ships alongside it for batch use, and the whole thing is a single Docker image ready for Google Cloud Run.

## Key Features

- **Three brands, one comparison.** Per-store pricing for Pak'nSave (Edge API), New World (Edge API) and Woolworths (cookie-based per-store context), concurrently.
- **Quantity-aware cost math.** Recipe quantities scale against actual supermarket pack sizes — "500 g beef mince" priced from a 1 kg pack reports the correct used cost, not the whole pack.
- **Web dashboard at `/` + sandbox at `/test`.** Live job progress with brand-coloured tiles, a terminal-style event log, a Leaflet map, and a tabbed results card. The sandbox is for in-progress UI; promote to prod via one script.
- **Photon-backed address search + map pick-origin.** Type-as-you-go autocomplete and click-the-map origin selection, both backed by OSM data, no API key.
- **LLM recipe builder.** Paste a recipe (≤1000 chars) and an LLM drafts structured ingredients + filter rules you can save as a preset. Choose your model (Mistral or Google) from the Settings page.
- **AI filter compiler.** After a run, type one sentence like "only red onions, no flavoured milk" — the LLM compiles it to include/exclude keywords grounded in your actual returned products, dry-run previewed before any change.
- **Auto refine.** One-click cull of the most irrelevant search results per dish, grounded in the same vocabulary the filter compiler uses.
- **Curated filter presets.** Per-dish include/exclude keywords shipped in `data/dish_filters.json`, with a per-user local override store.
- **Live thread-pool slider.** Settings → Advanced exposes a 20–40 worker slider that resizes the search pool without restart; refuses with 409 while a job is running.

## Quick Start

### 1. Editable install

```powershell
# Windows / PowerShell
.venv\Scripts\Activate.ps1
pip install -e .          # install the package
pip install -e ".[dev]"   # add pytest
```

```bash
# macOS / Linux
source .venv/bin/activate
pip install -e .
pip install -e ".[dev]"
```

### 2a. Run the web dashboard

```powershell
.venv\Scripts\uvicorn NZMealOptimiser.web.main:app --host 0.0.0.0 --port 8000
```

Open:

| URL | What you get |
|---|---|
| `http://127.0.0.1:8000/` | Production dashboard (compiled `static/vue/index.html`) |
| `http://127.0.0.1:8000/test` | Sandbox (compiled `static/vue/test.html`) — same app shell, used during in-flight UI work |
| `http://127.0.0.1:8000/docs` | Swagger for the FastAPI surface |

After editing anything under `src/NZMealOptimiser/web/frontend/src/`, rebuild:

```bash
cd src/NZMealOptimiser/web/frontend
npm run lint && npm run build
```

### 2b. Or run a one-shot CLI optimisation

```powershell
python -m tools.paknsave.paknsave_optimiser_edge  "Botany Town Centre, Auckland" "spaghetti bolognese"
python -m tools.newworld.newworld_optimiser_edge  "Botany Town Centre, Auckland" "spaghetti bolognese"
python -m tools.woolworths.woolworths_optimiser   "Botany Town Centre, Auckland" "spaghetti bolognese"
```

Use `--distance 5` (default 5 km) to widen the search radius. Results are appended to `data/full_results.csv`.

### 3. Or run via Docker

```bash
docker build -t nz-meal-optimiser .
docker run --rm -p 8000:8000 nz-meal-optimiser
```

The image is a two-stage build (Node 20 → Python 3.12-slim) ready to deploy to Google Cloud Run:

```bash
gcloud run deploy nz-meal-optimiser --source . --region=australia-southeast1 --allow-unauthenticated
```

## Web Dashboard

The dashboard is the primary surface. It exposes five pages from the left sidebar:

| Page | What it does |
|---|---|
| **Optimiser** | Address + dish + portions + supermarket selection → ranked store comparison. Live brand progress tiles (SVG rings), a terminal-style pipeline console, a Leaflet/OSM map with a draggable origin pin, and a tabbed Summary / Filter tuner / All results card. |
| **My Dishes** | Your saved recipe presets (from `data/dishes.json` — both curated and user-saved, badge-distinguished). Open, edit, or delete. |
| **LLM Recipe Builder** | Paste a recipe, draft structured ingredients + filter rules via LLM, save as a preset or hand off to the Optimiser. |
| **Documentation** | In-app viewer over `docs/technical/*.md` and `docs/project/*.md` — rendered with `marked` + `highlight.js`. |
| **Settings** | Display (content width, UI scale), Units (alias table), Advanced (live thread-pool slider, non-food filter toggle), LLM Models (per-provider picker, refresh, save), Danger zone (gated overrides). |

### `/` vs `/test`

Both URLs serve the same app shell. `/test` is the **sandbox tree** (`src/test/`) used for in-flight UI work; `/` is the **production tree** (`src/`). After QA at `/test`, promote changes with:

```powershell
powershell -File tools\frontend\promote_test_to_app.ps1
cd src\NZMealOptimiser\web\frontend
npm run lint && npm run build
```

The script's "review the diff of `src/App.vue` before committing" banner is the right safety check.

### Job model

`POST /optimise/jobs` returns a `job_id` immediately. The dashboard polls `GET /optimise/{id}?events_since=N` every ~700 ms; the server streams phase, per-company store/product counters, and a per-search event log. The brand progress tiles and the terminal console are direct renders of that feed.

## CLI

Each brand has a thin CLI that wraps the shared `optimise()` pipeline. The CLI is for batch use and for testing new stores.

```powershell
# Pak'nSave (Edge API — recommended; two-pass relevance + per-store pricing)
python -m tools.paknsave.paknsave_optimiser_edge  "<address>" "<dish>" [--distance 5]

# New World (Edge API — recommended; same architecture as Pak'nSave)
python -m tools.newworld.newworld_optimiser_edge  "<address>" "<dish>" [--distance 5]

# Woolworths (cookie-based per-store context, fresh session per store)
python -m tools.woolworths.woolworths_optimiser   "<address>" "<dish>" [--distance 5]

# LLM interactive: walk through ingredient generation, review, query, optimise
python -m tools.llm.llm_interactive

# Post-hoc: validate cached rows in full_results.csv via ministral-3b
python -m tools.llm.llm_validate --max-rows 20
```

All brand optimisers append to `data/full_results.csv` and use the same append-only, hash-deduplicated, multi-day schema. Old runs are kept; the optimiser reads from the latest date's rows.

## Data Inputs

Everything in `data/` is the single source of truth. Paths are resolved from `DATA_DIR` in `src/NZMealOptimiser/__init__.py`.

| File | Owner | Purpose |
|---|---|---|
| `data/dishes.json` | curated + user | 21 hand-curated dishes + your saved recipes. Each dish carries `dish_name`, `portion`, `ingredients` (with `quantity`, `unit`, optional `approx_quantity`/`approx_unit` for non-standard units like "1 can" or "1 medium onion", and `search_term`). |
| `data/dish_filters.json` | curated | Per-dish include/exclude keyword presets, AND-semantics. Seeded into per-user localStorage on first visit. |
| `data/full_results.csv` | append-only | All product rows from every run, deduplicated by `pk_hash = SHA-256(store_id \| sku \| date_created)[:16]`. Has an `is_valid` column filled in post-hoc by `tools/llm/llm_validate.py`. **Never hand-edit in Excel — blank rows corrupt the file.** |
| `data/llm_settings.json` | Settings page | `{ingredient_model, filter_model, exclude_non_food}`. Written atomically (temp + replace + cleanup on failure). |
| `data/llm_models_cache.json` | cache | Live catalog from Mistral + Google, seeded on first `GET /llm/models`, refreshed by `POST /llm/models/refresh`. |
| `data/{paknsave,newworld,woolworths}_stores.csv` | per-brand setup | Generated by the per-brand setup CLI. Refreshed when store coverage changes. |
| `data/observed_category1_*.json` | exploratory | The 116 unique `category1` values from Foodstuffs' Algolia index, used to filter non-food categories. |

To refresh the store list for a brand:

```powershell
python -m tools.paknsave.paknsave_setup       # 57 Edge stores / 60 mobile
python -m tools.newworld.newworld_setup       # 148 Edge stores / 150 mobile
python -m tools.woolworths.woolworths_setup   # 179 CDX sites (with hardcoded exclusions)
```

## Dish Coverage

21 hand-curated dishes ship with the project. New dishes can be created from the **LLM Recipe Builder** or via `POST /dishes/generate`. Each curated dish:

| Dish | Search terms |
|---|---|
| Spaghetti Bolognese | beef mince, spaghetti pasta, canned tomatoes, onion, carrot, garlic, mixed herbs |
| Butter Chicken | chicken thigh, butter chicken sauce, rice, cream, onion |
| Chicken Stir Fry | chicken breast, stir fry vegetables, soy sauce, rice noodles |
| Beef Stir Fry | beef strips, stir fry vegetables, soy sauce, rice noodles |
| Fish and Chips | fish fillet, potato, oil |
| Roast Lamb | lamb roast, potato, carrot, broccoli, stock |
| Chicken Curry | chicken thigh, curry paste, coconut milk, rice, onion |
| Beef Curry | diced beef, curry paste, coconut milk, rice, onion |
| Nachos | beef mince, tortilla chips, cheese, beans, sour cream |
| Pumpkin Soup | pumpkin, onion, cream, stock, bread |
| Tacos | beef mince, taco shells, lettuce, tomato, cheese, sour cream |
| Lamb Chops | lamb chops, potato, mint sauce, mixed vegetables |
| Lasagne | beef mince, lasagne sheets, cheese, canned tomatoes, milk, butter, flour |
| Shepherd's Pie | beef mince, potato, carrot, peas, stock |
| Pizza | pizza base, pizza sauce, cheese, pepperoni |
| Veggie Stir Fry | stir fry vegetables, tofu, soy sauce, rice noodles, garlic |
| Frittata | eggs, potato, onion, cheese, milk |
| Pancakes | flour, eggs, milk, sugar, butter |
| Chicken Soup | chicken breast, carrot, onion, celery, stock, pasta |
| Tomato Pasta | pasta, canned tomatoes, garlic, olive oil, mixed herbs, cheese |
| Chicken Katsu | chicken breast, flour, eggs, bread crumbs, rice, katsu sauce |

Non-standard recipe units (cans, fillets, "medium onion") carry `approx_quantity`/`approx_unit` metadata so the proportional cost math still works when the supermarket pack is sold by weight or volume. Such rows are reported with `status="approximate"`.

## How It Works

```
  Address ─► geocode (Photon / Nominatim) ──► (lat, lon)
                                              │
                                              ▼
                                  nearby stores within 5 km
                                  (haversine, brand-specific CSVs)
                                              │
              ┌───────────────────────────────┼───────────────────────────────┐
              ▼                               ▼                               ▼
   Pak'nSave Edge API              New World Edge API                 Woolworths REST
   (Algolia two-pass)              (Algolia two-pass)                 (cookie per-store)
              │                               │                               │
              └───────────────────────────────┼───────────────────────────────┘
                                              ▼
                                per-ingredient per-store rows
                                              ▼
                          quantity scaling + "used cost" math
                                              ▼
                                      ranked store list
```

Per-brand detail:

- **Pak'nSave + New World (Foodstuffs Edge API)** — Two-pass Algolia pipeline. Pass 1 (`POST /search/products/query/index/products-index`) returns relevance hits with `_highlightResult.matchedWords`; pet/non-food categories are filtered via `category1`. Pass 2 (`POST /search/paginated/products`) prices the surviving product IDs at the target store with `PRICE_ASC` sort. Prices are in cents (divide by 100 for dollars).
- **Woolworths (cookie-based)** — `cw-lrkswrdjp` cookie carries `dm-Pickup,f-{extra1},s-38`. A fresh `requests.Session` is required per store (the server's `Set-Cookie` overwrites any injected cookie on reuse). Per-store pricing was confirmed across stores (e.g. Greymouth Milk 3L = $7.15, Glenfield = $7.33). `extra1` is the `fulfilmentStoreId` from the CDX store locator. Prices are already in dollars. Two hardcoded exclusions: `9285` (Te Atatu, shut 24/04/2025) and `9035` (Kaikohe, shut 15/02/2026).

## Architecture

```
opencode/
├── data/                             # All CSVs/JSON. DATA_DIR is the contract.
│   ├── dishes.json                   # 21 curated dishes (+ LLM/imported extensions)
│   ├── dish_filters.json             # Per-dish include/exclude keyword presets
│   ├── full_results.csv              # Append-only optimisation log (pk_hash dedup, is_valid)
│   ├── llm_settings.json             # LLM model selection + non-food toggle
│   ├── llm_models_cache.json         # Mistral + Google model catalog cache
│   └── <brand>_stores.csv            # Per-brand store CSVs (refresh via per-brand setup)
├── src/NZMealOptimiser/              # Installable package (pip install -e .)
│   ├── pricing/                      # optimiser_utils.py + per-brand *_api.py
│   ├── llm/                          # llm_client / llm_models / llm_settings / llm_utils / generation
│   └── web/                          # FastAPI app + Vue dashboard
├── tools/                            # CLI layer (per-brand optimisers + setup + LLM tools)
├── tests/                            # 520 tests, ~10 s
├── exploration/                      # Per-brand scratch + live API verification
├── docs/
│   ├── project/                      # decision.md, design.md, logs.md
│   └── technical/                    # <Brand>_API.md, FastAPI.md, Vue_Dashboard.md, LLM_Pipeline.md
├── Dockerfile                        # Google Cloud Run image (Node 20 → Python 3.12-slim)
├── pyproject.toml                    # src-layout package + pytest config
├── requirements.txt                  # Pinned runtime deps
├── AGENTS.md                         # Agent-facing project reference
└── README.md                         # This file
```

## Testing

```powershell
python -m pytest                        # all 520 tests, ~10 s
python -m pytest tests/llm              # one folder
python -m pytest -m "not network"       # skip the live-network tests
```

Per-folder layout:

- `tests/{paknsave,newworld,woolworths}/` — per-brand API + optimiser tests, with JSON fixtures of real captured API responses
- `tests/web/` — FastAPI + LLM HTTP layer (job lifecycle, geocode, LRU caches, Photon routing)
- `tests/llm/` — LLM client, models, settings, utils
- `tests/combined/` — cross-brand parser + utility tests

The `network` marker opts a test out of the default run; use `-m "not network"` for offline CI runs.

## Deployment

The repo ships a two-stage Dockerfile ready for `gcloud run deploy --source .`:

1. **Frontend stage** (`node:20-alpine`) — `npm ci && npm run build` inside `src/NZMealOptimiser/web/frontend/`, producing `index.html` (→ `/`) and `test.html` (→ `/test`) into `static/vue/`.
2. **Python stage** (`python:3.12-slim`) — installs the pinned requirements, editable-installs the package, overlays the freshly built Vue assets, and copies `data/`, `docs/` and `AGENTS.md` for `/tech-docs` and the LLM catalog seed.

`CMD` runs `uvicorn NZMealOptimiser.web.main:app --host 0.0.0.0 --port 8000`.

No secrets are required by default. The `.env` file is optional and only configures LLM provider keys (`MISTRAL_API_KEY`, `GOOGLE_API_KEY`); the app degrades gracefully — `/llm/models` and `/dishes/generate` will return 503 if a key is missing.

## Limitations

- **Approximate units.** Recipe quantities like "1 medium onion" or "1 can tomatoes" are scaled using an approximate weight (e.g. 150 g per medium onion) and reported with `status="approximate"`. Backward-compatible — recipes without `approx_quantity` are unchanged.
- **Woolworths per-store cookie.** The `cw-lrkswrdjp` cookie must be injected into a fresh `requests.Session` per store. The server's `Set-Cookie` overwrites injected values on reuse.
- **Store density.** Auckland CBD has one Pak'nSave within 5 km; East Auckland has three. Rural addresses may produce empty result sets; widen the radius or pick a closer origin on the map.
- **Photon demo throttling.** The address autocomplete is backed by the public Photon demo. Sustained traffic will hit "fair use" limits. Self-hosting Photon/Pelias against the LINZ NZ address dump is the long-term fallback (5–10 GB RAM, ~20 GB disk).
- **Algolia sort restrictions.** The Foodstuffs Edge API only supports `PRICE_ASC` and `PRICE_DESC` on the paginated endpoint; `RELEVANCE` returns 400. The two-pass pipeline works around this by combining a relevance-sorted Algolia index with a price-sorted filter.
- **Nominatim rate limit.** The forward geocoder (`GET /geocode` on the Optimiser's "Resolve setup" submit) is rate-limited to 1 request/second per the OSM Foundation TOS. The autocomplete dropdown does not call Nominatim — it uses Photon.
- **Nominatim TOS.** Browser-facing per-keystroke autocomplete would violate the OSM Foundation usage policy. This is why the address dropdown uses Photon, not Nominatim.
- **Photon ODbL attribution.** Photon's data is ODbL-licensed; the address-dropdown footer links to `photon.komoot.io` and `openstreetmap.org/copyright`. Removing those links would put the dashboard in violation of the OSM data license.

## Disclaimer

This is an experimental, personal project. Not affiliated with or endorsed by Pak'nSave, New World, Woolworths, or any supermarket chain. Functionality depends on the stability of the three supermarket APIs — endpoints may change without notice. Pricing data from Pak'nSave and New World is in cents; divide by 100 for dollars.

## Documentation

| Doc | Purpose |
|---|---|
| `AGENTS.md` | Agent-facing project reference: setup, project layout, confirmed research, key gotchas, per-brand CLI commands. The README stays user-facing; `AGENTS.md` is the deeper reference. |
| `docs/technical/PaknSave_API.md` | Foodstuffs Pak'nSave API — primary reference for shared Foodstuffs mobile + Edge API structure. |
| `docs/technical/NewWorld_API.md` | New World API — shared structure referenced from PaknSave_API.md; New World-specific Edge API and store data sources. |
| `docs/technical/Woolworths_API.md` | Full `/api/v1` endpoint documentation + cookie architecture. |
| `docs/technical/LLM_Pipeline.md` | LLM ingredient generation, post-run validation, quantity scaling, AI instruction → keyword compiler, auto-cull. |
| `docs/technical/FastAPI.md` | FastAPI architecture: endpoints, thread pool, job model, Pydantic models, geocoding providers. |
| `docs/technical/Vue_Dashboard.md` | Vue 3 dual-tree (prod `/` + sandbox `/test`), build flow, backend contract. |
| `docs/technical/CLI_vs_Dashboard.md` | Canonical CLI↔Dashboard↔Endpoint equivalence table. |
| `docs/project/decision.md` | Key decisions and rationale (chronological, decision #1 → #45+). |
| `docs/project/design.md` | Technical design (API, auth, pipeline, data flow). |
| `docs/project/logs.md` | Major errors and resolutions (logs #1 → #68+). |
