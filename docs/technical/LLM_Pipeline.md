# LLM Pipeline

The LLM pipeline augments the supermarket optimiser with AI-generated ingredient lists, post-run search-result validation, and quantity-based cost scaling. It is **manual/interactive** — the user runs `llm_interactive.py` to step through a dish, query stores, and review results. Validation (`llm_validate.py`) runs **separately and post-hoc** on the CSV; it is not yet wired into the optimiser at runtime.

## Architecture & Data Flow

```
User input (dish, address, portions, supermarkets)
    │
    ▼
llm_interactive.py  (CLI orchestration, 6 steps)
    │
    ├──► llm_utils.py
    │       ├── resolve_ingredients  → curated JSON  OR  LLM generation
    │       └── parse_optimiser_columns  → quantity scaling / cost math
    │
    ├──► optimiser_utils.py / woolworths_optimiser.py  (woolworths_querier)
    │       └── query + append_rows → data/full_results.csv
    │
    └──► llm_validate.py  (run separately, post-hoc)
            └── validate  →  is_valid column written back to CSV

┌─────────────────────────┐   ┌─────────────────────┐
│ data/dishes.json        │   │ data/full_results.csv │
│ (21 curated dishes)     │   │ (18 columns)          │
└──────────▲──────────────┘   └──────────▲────────────┘
           │                             │
           │                             │  is_valid
           │                             │  (appended)
           └─────────────────────────────┴──────────► (user)
```

**Key principle:** The LLM assists, but the user is always in the loop. No fully-automated dish-to-cost pipeline exists yet.

## Contents

- [Architecture & Data Flow](#architecture--data-flow)
- [Components](#components)
- [Custom-Dish Generation Service (`generation.py`, web dashboard)](#custom-dish-generation-service-generationpy-web-dashboard)
- [Ingredient Resolution](#ingredient-resolution)
- [LLM Validation](#llm-validation)
- [Quantity Scaling](#quantity-scaling)
- [Data Files](#data-files)
- [Configuration](#configuration)
- [Usage](#usage)
- [Capabilities & Limitations](#capabilities--limitations)
- [Future Work](#future-work)

## Components

| Script | Role |
|--------|------|
| `src/NZMealOptimiser/llm/llm_client.py` | Mistral API client. Enforces rate limiting and JSON parsing with retries. |
| `src/NZMealOptimiser/llm/llm_utils.py` | Ingredient resolution (curated → LLM), dish parsing/validation, quantity scaling math. |
| `src/NZMealOptimiser/llm/generation.py` | Custom-dish draft service for the web dashboard: Mistral ingredients + Gemini filter rules (see "Custom-Dish Generation Service" below). |
| `tools/llm/llm_interactive.py` | End-to-end interactive CLI that ties ingredient resolution → optimiser queries → results. |
| `tools/llm/llm_validate.py` | Post-run validator: sends batches of CSV rows to the LLM to mark `is_valid` (True/False). |

## Custom-Dish Generation Service (`generation.py`, web dashboard)

Backs the `/test` dashboard's **"Generate custom ingredients"** button via `POST /dishes/generate`. Two sequential calls:

1. **Ingredients — configured model** (any chat-capable model from Mistral or Google Gemini, picked in the Settings page; default `mistral-medium-latest`). `generate_dish_ingredients()` reuses `LLMClient.generate_ingredients` + `parse_and_validate`, then cleans the output — units folded through `UNIT_ALIASES`, case-insensitive duplicates merged, empty-term/non-positive-quantity rows dropped (each intervention reported as a warning), count capped at `MAX_INGREDIENTS` (10).
2. **Filter rules — configured model** (any chat-capable model from either provider; default Google Gemini `gemini-3.1-flash-lite` over the OpenAI-compat endpoint). `generate_ingredient_filters()` ports the generic labelling prompt from `exploration/llm/explore_filter_explorer.py` and returns `{search_term: {includes: [word], excludes: [...]}}` — the exact shape of `data/dish_filters.json` entries / `IngredientFilterSet`.

Error model: missing API key → `GenerationConfigError` → HTTP 503; ingredient generation/validation failure after retries → `IngredientGenerationError` → HTTP 502; **filter failures are non-fatal** — the response carries empty rules plus a warning so a provider outage never blocks usable ingredients.

The generated rules are seeded into the dashboard's shared `custom` filter scope and remain fully user-editable before the run; at runtime they flow through the same `matches_ingredient_filters` machinery as curated presets.

### Model selection

The model used for each leg is **user-selectable** from the Settings page. The choice is persisted server-side in `data/llm_settings.json` (atomic temp+replace write, parallels `dishes.json`). No `.env` rewrite is needed and no server restart is required — settings are read per request, so swapping models takes effect on the next generation call.

The model catalog is fetched from each provider:

- **Mistral** — `GET /v1/models`. Filtered to `capabilities.completion_chat == true`, `type != "fine-tuned"`, `archived == false`.
- **Google Gemini** — `GET /v1beta/models`. Filtered to models whose `supportedGenerationMethods` contains `generateContent` (the method the OpenAI-compat chat surface maps to). The `models/` prefix is stripped from each id.

The catalog is **file-cached** in `data/llm_models_cache.json` with a `fetched_at` timestamp. The Settings page shows the last-fetched time and a "Refresh model list" button (`POST /llm/models/refresh`) that re-fetches from both providers and overwrites the cache. This keeps provider quota use minimal: the catalog is fetched once on first load and only again on a manual refresh.

The active selection shape:

```json
{
  "ingredient_model": {"provider": "mistral", "model_id": "mistral-medium-latest"},
  "filter_model": {"provider": "google", "model_id": "gemini-3.1-flash-lite"}
}
```

### Settings page endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/llm/models` | Returns the cached catalog + active selection. Seeds the cache on first call. |
| `POST` | `/llm/models/refresh` | Re-fetches both providers, overwrites the cache, returns the new catalog + selection. |
| `GET` | `/llm/settings` | Returns the active selection only. |
| `PUT` | `/llm/settings` | Validates the body (provider ∈ {mistral, google}, non-empty model_id) and writes the file. |

The `/test` Settings page reads `/llm/models` on mount and uses the Settings page "Refresh model list" button for the cache refresh. "Save model selection" issues `PUT /llm/settings`. "Reset to defaults" restores the seeded defaults and re-saves.

### Storage location

| File | Purpose |
|------|---------|
| `data/llm_settings.json` | Active ingredient + filter model selection. |
| `data/llm_models_cache.json` | Last-fetched model catalog with `fetched_at` timestamp. |

## Ingredient Resolution

`resolve_ingredients(dish, portions, regenerate, model_alias)` resolves a dish name to a list of ingredient dicts:

1. **Curated JSON** — `data/dishes.json` lookup (21 dishes). If the dish key exists and `regenerate` is False, returns the structured ingredients directly.
2. **LLM Generation** — If not curated or `regenerate=True`, calls `mistral-large-latest` (or specified model) via `LLMClient.generate_ingredients`, then validates through `parse_and_validate`.
3. **Fallback** (edge case only) — If both curated and LLM fail, returns the raw dish name as a single search term. This is a safety net, not part of the normal flow.

### Example: curated dish entry

```json
"spaghetti bolognese": {
  "dish_name": "spaghetti bolognese",
  "portion": 4,
  "ingredients": [
    {"quantity": 500, "unit": "g", "search_term": "beef mince"},
    {"quantity": 400, "unit": "g", "search_term": "spaghetti pasta"},
    {"quantity": 1, "unit": "can", "search_term": "canned tomatoes"},
    {"quantity": 2, "unit": "cloves", "search_term": "garlic"}
  ]
}
```

## LLM Validation

`llm_validate.py` validates whether each supermarket search result (`returned_ingredient`) matches what the user was searching for (`search_ingredient`). It runs **after** the optimiser has written results to `data/full_results.csv`.

### How it works

1. Loads `data/full_results.csv` via pandas.
2. Filters to rows where `is_valid` is missing (NaN or empty).
3. Processes the first `--max-rows` unvalidated rows in batches of `--batch-size`.
4. Sends each batch to `ministral-3b-2512` with a structured prompt.
5. Writes results back to the CSV (append-safe; preserves existing `is_valid` values).

### Prompt design

The validator uses a simple prompt: each row is rendered as:

```
Searching for [X] returned [Y] in departments [Z]
```

With validation rules (examples):

- Search "beef mince" → result "beef mince" = VALID
- Search "beef mince" → result "beef burgers" = INVALID
- Search "spaghetti pasta" → result "pasta spaghetti" = VALID
- Search "spaghetti pasta" → result "pasta penne" = INVALID (wrong shape)

### JSON schema enforcement

Mistral is instructed to return strict JSON via a `json_schema` response format:

```python
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "search_result_validation",
        "schema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {"type": "boolean"},
                }
            },
            "required": ["results"],
        },
        "strict": True,
    },
}
```

This prevents free-form text output and guarantees parseable booleans.

### Rate limiting

- Model: `ministral-3b-2512` (alias `small`)
- Default rate limit: 10 requests/second
- Each batch of 20 rows = 1 API call
- Typical runtime: ~1s per 20 rows

### Incremental validation

Re-running the script skips rows already marked `is_valid` (True or False), filling in only the blanks. The CSV is written in-place via `df.to_csv(index=False)`.

## Quantity Scaling

`parse_optimiser_columns(row)` is the core scaling function. It takes an optimiser CSV row enriched with LLM ingredient data and computes purchase quantities and proportional costs.

### Normalized units

Units are converted to a common base for comparison:

| Category | Units normalized to | Examples |
|----------|-------------------|----------|
| Weight | grams (g) | kg→1000, oz→28.35, lb→453.59, clove→5 |
| Volume | milliliters (ml) | l→1000, cl→10, cup→240, tbsp→15, tsp→5 |
| Count | count | ea, unit, pk, pack, bunch, each |

**Compound units** like `x 375ml` (meaning 10 × 375ml bottles) are expanded: multiplier parsed, quantity scaled accordingly.

### Cross-category approximation

When units are in different physical categories (weight vs volume), a **1ml ≈ 1g** approximation is applied, flagged via `unit_approximate=True` and `status="approximate"`.

### Incompatible units

If units are fundamentally incompatible (e.g., a "count" item vs a weight requirement like "500g"), the row is marked `status="incompatible_units"` with `used_price=None`. However, if the LLM provided `approx_quantity` and `approx_unit` for that ingredient (e.g. "1 medium onion" → approx 150g), the function falls back to those values to compute a proportional cost with `status="approximate"`. This handles common recipe phrasing like "1 can", "1 medium", "2 fillets", "1 head" where the supermarket sells the item by weight.

### Cost math

| Condition | Purchase qty | Purchase price | Used price (proportional) |
|-----------|-------------|----------------|--------------------------|
| `ratio <= 1` | 1 pack | `pack_price` | `pack_price × ratio` |
| `ratio > 1` | `ceil(ratio)` packs | `pack_price × ceil(ratio)` | `pack_price × ratio` |
| Incompatible | 0 | None | None |

### Example

| Field | Value |
|-------|-------|
| LLM requirement | 500g beef mince |
| Pack from CSV | 1kg ($9.49) |
| Scaling ratio | 500/1000 = 0.5 |
| Purchase qty | 1 pack |
| Purchase price | $9.49 |
| Used price | $9.49 × 0.5 = **$4.745** |

## Data Files

### `data/dishes.json`

21 hand-curated dishes, mapping dish name → `{"dish_name", "portion", "ingredients": [...]}`. Each ingredient has `quantity`, `unit`, and `search_term`. Ingredients with non-standard units (e.g. "1 can", "1 medium", "2 fillets") also include optional `approx_quantity` and `approx_unit` (in g or ml) for use as a fallback when supermarket packs are sold by weight/volume.

### `data/full_results.csv`

Append-only results store. 18 columns:

| Column | Source |
|--------|--------|
| `company` | optimiser |
| `store` | optimiser |
| `store_id` | optimiser |
| `search_ingredient` | from DISHES / LLM |
| `returned_ingredient` | API response |
| `price` | API response |
| `quantity` | parsed from pack size |
| `measurement_unit` | parsed from pack size |
| `per_unit_quantity` | comparative price qty |
| `per_unit_price` | comparative price |
| `is_sale` | promotion flag |
| `sku` | API response |
| `department` | Pass 1 Algolia / API |
| `sub_department` | Pass 1 Algolia / API |
| `datetime_created` | timestamp |
| `date_created` | date |
| `pk_hash` | SHA-256 of `store_id|sku|date_created` |
| `is_valid` | **LLM validation** |

Duplicates are detected via `pk_hash`. The `is_valid` column is blank for newly-appended rows until `llm_validate.py` fills it in.

## Configuration

Environment variables (`.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MISTRAL_API_KEY` | — | Mistral API key (required) |
| `MISTRAL_MODEL_SMALL` | `ministral-3b-2512` | Model for validation |
| `MISTRAL_MODEL_MEDIUM` | `mistral-medium-latest` | Model for ingredient generation |
| `MISTRAL_MODEL_LARGE` | `mistral-large-2512` | Model for ingredient generation |

Rate limits (calls/second):

| Alias | Model | Default RPS |
|-------|-------|-------------|
| `small` | `ministral-3b-2512` | 10.0 |
| `medium` | `mistral-medium-latest` | 0.5 |
| `large` | `mistral-large-2512` | 0.067 |

## Usage

### Interactive pipeline

```bash
python -m tools.llm.llm_interactive \
  --dish "spaghetti bolognese" \
  --portions 4 \
  --address "123 Queen Street, Auckland CBD, 1010" \
  --supermarkets "7" \
  --distance 5 \
  --requery true \
  --model medium
```

Options: `--dish`, `--portions`, `--address`, `--supermarkets` (1-7 or comma-separated names), `--distance`, `--requery` (true/false), `--regenerate`, `--non-interactive`, `--model` (small/medium/large).

### Validation (post-run)

```bash
python -m tools.llm.llm_validate --max-rows 20 --batch-size 20
```

- `--max-rows`: number of unvalidated rows to process (default: 20)
- `--batch-size`: rows per LLM API call (default: 20)
- `--data-file`: path to CSV (default: `data/full_results.csv`)

Re-run to incrementally fill in more rows — already-validated rows are always skipped.

## Capabilities & Limitations

### What works well
- Ingredient generation for common dishes (21 curated + arbitrary LLM generation)
- Prompt-level control for units, portions, search terms
- Structured parsing with clear failure modes (`LLMParseError`)
- Unit normalisation across weight/volume/count
- Incremental validation with no data loss

### Edge cases & limitations
- **Compound units** (e.g., `x 375ml`) are handled, but unusual pack formats can confuse the parser.
- **Cross-category approximation** (1ml≈1g) is a heuristic — works for water-like densities, not oils or powders.
- **No brand-specific refiltering** — ingredients are not re-evaluated based on store-specific substitutions (e.g., "cheapest cheese available").
- **Validation is offline** — `is_valid` is not consulted by the optimiser at runtime; it's purely a data-quality aid.
- **No automated feedback loop** — the user must manually review and re-run.
- **Garlic pricing** (noted in main README) — loose garlic is per-kg ($40+), so crushed garlic jars are returned instead.

### Performance
- 20 validated rows ≈ 1 second (1 API call to `ministral-3b-2512`).
- Full 4,800-row dataset ≈ 4 minutes at batch size 20.
- Ingredient generation (medium model) ≈ 2-3 seconds per dish.

## Future Work

- **Runtime validation** — use `is_valid` during optimisation to prefer validated results.
- **Interactive feedback loop** — let users flag invalid results during `llm_interactive.py` and feed corrections back to the LLM prompt for re-generation.
- **Brand-specific ingredient substitution** — at runtime, substitute ingredients based on what's cheapest or available at the selected store (e.g., "cheapest cheese" instead of a fixed search term).
- **Automated batch validation** — optionally run `llm_validate.py` as part of the optimiser pipeline (flag to enable/disable).
