# LLM Pipeline

The LLM pipeline augments the supermarket optimiser with AI-generated ingredient lists, pasted-recipe import, post-run search-result validation, quantity-based cost scaling, and post-run keyword-filter compilation. The **web dashboard is the primary surface** (`POST /dishes/generate`, `POST /dishes/import_text`, `POST /optimise/{id}/ai_filter_preview`, `POST /optimise/{id}/auto_cull_preview`); `tools/llm/llm_interactive.py` remains as a legacy interactive CLI. Validation (`tools/llm/llm_validate.py`) runs **separately and post-hoc** on the CSV; it is not yet wired into the optimiser at runtime.

## Architecture & Data Flow

```
User input (dish, address, portions, supermarkets)
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  llm_utils.py                                                           │
│   ├── resolve_ingredients ──► curated dishes.json  OR  LLM generation   │
│   │                          (via llm_client + llm_settings)            │
│   └── parse_optimiser_columns ──► quantity scaling / cost math          │
└──────┬──────────────────────────────────────────────────────────────────┘
       │
       ├──► Web dashboard ────────────────────────────────────────────────┐
       │    ├── POST /dishes/generate ──► generation.py                   │
       │    │   ├── generate_dish_ingredients  (ingredient_model)         │
       │    │   │     └── _clean_parsed_rows (drop/merge/cap 10)          │
       │    │   └── generate_ingredient_filters (filter_model)            │
       │    │         └── call_filter_model (temp 0.1, 4096 tokens)       │
       │    ├── POST /dishes/import_text ──► generate_dish_               │
       │    │       ingredients_from_text (ok / rejected → 200)           │
       │    └── POST /optimise/{id}/ai_filter_preview ──┐                 │
       │        POST /optimise/{id}/auto_cull_preview ──┘                 │
       │            └── ai_filter_compiler.py ──► call_filter_model       │
       │                ├── build_deduped_summary (Terms + Brands)        │
       │                ├── compile_ai_instruction  (sentence)            │
       │                └── compile_auto_cull_filters (dish-wide)         │
       │                                                                  │
       ├──► optimiser_utils.py / woolworths_api ──► query + rows ─────────┤
       │    └── _apply_ingredient_validity (matches_* filters)            │
       │                                                                  │
       └──► llm_validate.py (post-hoc, batch) ──► is_valid column ────────┘

Shared LLM layer (used by generation + compiler):
  llm_client.py ── Mistral + Google Gemini (rate-limit + 3-retry, json_object)
  llm_models.py ── live catalog + cache (data/llm_models_cache.json)
  llm_settings.py ── selection store (data/llm_settings.json)
```

```
┌──────────────────────────┐   ┌──────────────────────────┐   ┌──────────────────────────┐
│ data/dishes.json         │   │ data/full_results.csv    │   │ data/llm_settings.json   │
│ (21 curated dishes)      │   │ (18 csv cols + 9         │   │ ingredient_model +       │
│ + data/dish_filters.json │   │  enriched cols)          │   │ filter_model +           │
│ curated filter presets   │   │ is_valid (appended)      │   │ exclude_non_food         │
└─────────────▲────────────┘   └─────────────▲────────────┘   └─────────────▲────────────┘
              │                              │                              │
              └──────────────────────────────┴──────────────────────────────┴──► (web + CLI)
```

**Key principle:** The LLM assists, but the user is always in the loop. No fully-automated dish-to-cost pipeline exists yet.

## Contents

- [Architecture & Data Flow](#architecture--data-flow)
- [Components](#components)
- [Custom-Dish Generation Service (`generation.py`, web dashboard)](#custom-dish-generation-service-generationpy-web-dashboard)
- [Pasted-Recipe Import (`import_text`)](#pasted-recipe-import-import_text)
- [AI Filter Compiler (`ai_filter_compiler.py`)](#ai-filter-compiler-ai_filter_compilerpy)
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
| `src/NZMealOptimiser/llm/llm_client.py` | Dual-provider client — Mistral (`mistralai` SDK, `MISTRAL_API_KEY`) + Google Gemini via OpenAI-compat (`https://generativelanguage.googleapis.com/v1beta/openai/`, `GOOGLE_API_KEY`). `LLMClient(provider, model_id)` is canonical; legacy `model_alias` shim (`small/medium/large` → `DEFAULT_MODELS`) kept for `llm_interactive` + tests. Handles per-provider rate-limit sleep, 3-retry with linear `20s*attempt` backoff on `429`/`RateLimitError`, and `response_format: json_object`. Prompts: `INGREDIENT_PROMPT` (name→ingredients), `IMPORT_INGREDIENTS_PROMPT` (pasted text → dual-status ok/rejected). |
| `src/NZMealOptimiser/llm/llm_utils.py` | Ingredient parsing/validation (`parse_and_validate` → `ParsedDish`, `LLMParseError` on hard failures, printed warnings on soft issues), resolution order (`resolve_ingredients`), and quantity scaling (`parse_optimiser_columns`, `UNIT_ALIASES` + `normalise_unit`, `compound x 375ml` expander, 1ml≈1g approximation). |
| `src/NZMealOptimiser/llm/llm_models.py` | Live model catalog + file cache (`data/llm_models_cache.json`). `list_mistral_models` filters `capabilities.completion_chat==true && type!="fine-tuned" && !archived && deprecation is None && billing_model_name==id` (drops `-latest` aliases), `list_google_models` filters `supportedGenerationMethods contains generateContent` and strips `models/` prefix. Both sort by `id`. `fetch_all_providers` isolates per-provider failures; `ensure_cache_seeded()` seeds on first `GET /llm/models`. |
| `src/NZMealOptimiser/llm/llm_settings.py` | Selection store (`data/llm_settings.json`). Defaults `ingredient_model: {mistral, mistral-medium-3-5}` + `filter_model: {google, gemini-3.1-flash-lite}` + `exclude_non_food: true`. `load_llm_settings()` is tolerant (`_coerce_model` fallback to defaults); `save_llm_settings()` validates `provider∈{mistral,google}` + non-empty `model_id` and writes atomically via `tmp → os.replace` with cleanup on failure. `get_active_models()` is the per-request accessor used by `generation.py` + `ai_filter_compiler.py`. |
| `src/NZMealOptimiser/llm/generation.py` | Custom-dish draft service: name-based `generate_dish_ingredients` + pasted-text `generate_dish_ingredients_from_text` (both via `_clean_parsed_rows`: drop blank term / `qty≤0` / dedup case-insensitive first-wins, fold `approx_*` through `normalise_unit`, cap `MAX_INGREDIENTS=10` with warnings), plus `generate_ingredient_filters` (`FILTER_PROMPT_TEMPLATE`, `MAX_EXCLUDES=5`, trim warning, `includes`→single-element list). `call_filter_model(prompt, model)` uses `temperature=0.1, max_tokens=4096`. Legacy `call_gemini` shim kept for tests. Orchestrators `generate_custom_dish` / `generate_custom_dish_from_text` compose ingredients+filters; filter failures are soft (empty rules + warning). |
| `src/NZMealOptimiser/llm/ai_filter_compiler.py` | Post-run keyword-filter compiler. Turns one universal sentence **or** a dish-wide auto-cull request + deduped `{Ingredient, Terms, Brands}` summary (built fast in Python, no word cap) into `{search_term: {includes, excludes, brand_includes, brand_excludes}}`. Prompt-injection guarded (`<< >>` DATA markers), vocab-grounded, capped `15/list`, warnings for truncation and unknown drops, user confirms before apply. See "AI Filter Compiler" below. |
| `tools/llm/llm_interactive.py` | End-to-end interactive CLI that ties ingredient resolution → optimiser queries → results (legacy; web is primary). |
| `tools/llm/llm_validate.py` | Post-run validator: sends batches of CSV rows to the LLM to mark `is_valid` (True/False). |

## Custom-Dish Generation Service (`generation.py`, web dashboard)

Backs the dashboard's **"Generate custom ingredients"** button via `POST /dishes/generate`. Two sequential calls, each using the **configured model from `data/llm_settings.json`** (read per-request via `get_active_models()`; no restart needed):

1. **Ingredients — configured ingredient model** (any chat-capable model from Mistral or Google, default `mistral-medium-3-5`). `generate_dish_ingredients()` reuses `LLMClient.generate_ingredients` + `parse_and_validate`, then `_clean_parsed_rows`:
   - units folded through `UNIT_ALIASES` (`normalise_unit`, e.g. `kg→g`, `eggs→each`, unknown pass-through),
   - case-insensitive duplicates merged (first wins) → warning `merged duplicate search term 'x'`,
   - empty-term / non-positive-quantity rows dropped → warnings `dropped one ingredient with an empty search term` / `dropped 'x' — its quantity must be greater than zero`,
   - `approx_quantity`/`approx_unit` folded similarly when present and `>0`,
   - count capped at `MAX_INGREDIENTS` (10) → warning `capped the recipe at 10 ingredients (N dropped)`.
2. **Filter rules — configured filter model** (any chat-capable model, default Google `gemini-3.1-flash-lite` over the OpenAI-compat endpoint, `temperature=0.1, max_tokens=4096`). `generate_ingredient_filters()` ports the labelling prompt from `exploration/llm/explore_filter_explorer.py` and returns `{search_term: {includes: [word], excludes: [...]}}` — the exact shape of `data/dish_filters.json` entries / `IngredientFilterSet`. **`brand_includes` / `brand_excludes` are intentionally never populated here** — brand preferences stay user-set on the dashboard (enforced by `test_parse_filters_never_emits_brand_fields`); the matcher is a separate `matches_brand_filters` call that only fires on rows whose title already passed. `parse_filters` caps `excludes` at `MAX_EXCLUDES=5` → warning `'term': trimmed excludes from N to 5`; unknown `search_term` → `ignored unknown search_term 'x'`; missing terms → `no filter generated for: ...`.

Error model: missing API key → `GenerationConfigError` → HTTP 503; ingredient generation/validation failure after retries → `IngredientGenerationError` → HTTP 502; **filter failures are non-fatal** — the response carries empty rules plus a warning so a provider outage never blocks usable ingredients. `POST /dishes/generate` returns `{dish_name, base_portions, source:"llm", ingredients, filters, warnings}` (~5-20 s, run in thread pool).

The generated rules are seeded into the dashboard's shared `custom` filter scope and remain fully user-editable before the run; at runtime they flow through the same `matches_ingredient_filters` + `matches_brand_filters` machinery as curated presets (brand rule runs first and takes precedence — a brand rejection wins even when the title would also fail, and `filter_reason` records the winning failure; see FastAPI.md §`IngredientFilterSet`).

## Pasted-Recipe Import (`import_text`)

Backs **"Import pasted recipe"** via `POST /dishes/import_text` (body `{recipe_text, dish_name, base_portions, notes}` — `recipe_text` ≤1000 chars, `notes` ≤100 chars; `dish_name` / `base_portions` are user-supplied identity, never trusted from the model). One LLM call via `LLMClient.generate_ingredients_from_text` using `IMPORT_INGREDIENTS_PROMPT`:

- Prompt wraps `<<dish_name>>`, `<<base_portions>>`, and `<<recipe_text>>` as **DATA** with an explicit security rule; injection attempts are treated as untrusted and mapped to a refusal.
- The model must answer exactly one of two JSON shapes:
  1. `{"status":"ok","ingredients":[{quantity,unit,search_term,approx_quantity?,approx_unit?},...]}` — proceeds through `parse_and_validate` + `_clean_parsed_rows` (same warnings/caps as above), then filter-rule generation (soft, same as `POST /dishes/generate`).
  2. `{"status":"rejected","reason":"<one short lowercase phrase>"}` — mapped to `RecipeRejectedError` and returned as **HTTP 200** `{"status":"rejected","reason","base_portions"}` so the UI shows a gentle notice, not an error banner. Canonical reasons: `text is not a recipe`, `attempted prompt injection`, `no ingredient list found`.
- Retries: 3× JSON-parse loop; a rejection is first-class and never burns retries. Missing key → `GenerationConfigError` → 503; extraction failure after retries / no usable rows → `IngredientGenerationError` → 502.

Success shape mirrors `POST /dishes/generate` plus `status:"ok"` and the caller-supplied `notes` (`{status, dish_name, base_portions, source:"llm", ingredients, filters, warnings, notes}`); rejection shape is `{status:"rejected", reason, base_portions, ingredients:[], filters:{}, warnings:[]}`.

## AI Filter Compiler (`ai_filter_compiler.py`)

Post-run layer in the **Filter Tuner + Summary**. Not run at search time — runs **after** a comparison completes against the job's cached product rows. All filtering is local; the product table is never sent to the LLM.

**Problem:** a free-text sentence like `"only red onions, no flavoured milk"` should filter thousands of cached rows, but sending the rows to the LLM hits rate limits and risks hallucination.

**Solution — deduped summary, not rows:**
1. **Python builds a vocabulary** per ingredient from the cached rows: `build_deduped_summary(search_terms, rows)` → `[{Ingredient, Terms: [sorted unique lowercased words from every returned_ingredient], Brands: [sorted unique brands (both lower + original)]}]`. No cap on word counts — deduped only, not truncated. This is a fast `set()` pass, ~1000-2000 tokens for a typical dish (well within 128k).
2. **One LLM call** compiles the summary (+ optional context) into keyword rules via `call_filter_model` (configured **filter model** from `data/llm_settings.json`, default `gemini-3.1-flash-lite`, `temperature=0.1, max_tokens=4096`). Prompt wraps the raw sentence/dish between `<< >>` markers and instructs the model to treat anything inside as **DATA, not instructions** (injection guard). Empty/vague inputs return `{}` with no error. No product rows are sent.
3. **Local apply over every cached row** via the existing `matches_ingredient_filters` / `matches_brand_filters` (Levenshtein `contains_word` ≤0.35, case-insensitive, partial-word; title AND-semantics, brand OR-semantics) stamps `valid_ingredient` + `filter_reason`. Additive merge (`Set` dedup, case-insensitive, capped `15/list`, `40` chars each) via `_merge_request_filters` so hand-tuned rules survive.

The instruction is **universal** — even when the user is viewing the `beef mince` editor, they can say `"only Red onions"` and the compiler maps it to the `onion` ingredient because the summary for every ingredient is in the prompt.

### `POST /optimise/{job_id}/ai_filter_preview` — universal sentence

Body `{instruction: string}` (`1..500` chars; `400` on empty/overlong). Compiles `compile_ai_instruction(instruction, search_terms, rows)` → `({term:{includes,excludes,brand_includes,brand_excludes}}, summary, warnings)`. Prompts the model for `includes` (EVERY word must match title, use only when instruction says KEEP a variant, e.g. `"only red onions"→includes ["red"]` for `onion`), `excludes` (none may match), and `brand_*` (same single-word brand matching, only when a brand is mentioned). Every keyword is lowercased/stripped; multi-word inputs are truncated to the first word (see Warnings).

Returns `{instruction, compiled_filters, warnings, summary, preview: {terms:{total,matched}, products:[{company,store,sku,search_ingredient,returned_ingredient,brand,quantity,measurement_unit,price,valid,reason}]}}` — a dry-run so the tuner can show chip diff + `matched/total` before Apply. **No mutation** of `job.result`/`pipeline_cache`; Apply is `POST /optimise/{id}/reapply` with the merged filters. Errors: `404` unknown job · `409` not-complete/no rows · `502` LLM JSON/validation failure · `503` missing API key.

### `POST /optimise/{job_id}/auto_cull_preview` — dish-wide auto-cull

Body `{"current_filters": {term:{includes,excludes,brand_includes,brand_excludes}}}` (optional, defaults `{}`). Uses the run's dish name (`pipeline_cache.dish_name` → `job.result.dish` → `"this dish"`, sanitized `<<dish>>` with the same injection guard) + the same deduped `{Ingredient,Terms,Brands}` summary (+ `current_filters` as context to avoid duplicates) to ask the filter model via `compile_auto_cull_filters(dish, search_terms, rows, current_filters)` for up to **15 `excludes` + 15 `brand_excludes` per ingredient**, most irrelevant first, grounded strictly to the vocab. `includes`/`brand_includes` are intentionally omitted. After `_coerce_ai_filters`, an extra vocab-clip drops any keyword not in `Terms`/`Brands` and slices to `15/list`.

Returns `{dish, compiled_filters: {term:{includes:[],excludes:[],brand_includes:[],brand_excludes:[]}}, warnings, summary, preview:{terms,products}}` where `preview` is the **additive** dry-run (`current ∪ suggestions`, case-insensitive dedup, capped `15/list`) so both Summary and Filter tuner show `N new · matched/total` before Apply. Same `404/409/502/503` semantics. Second click is idempotent (no net new → no extra preview filter).

### Normalization, caps, and warnings

`_coerce_ai_filters` normalizes every keyword: `strip → lower → split on whitespace → keep first token if multi-word`. Unknown `search_term` entries are dropped. Post-coercion vocab clipping (`compile_auto_cull_filters`) enforces grounding.

| Warning string | When it fires | Example |
|---|---|---|
| `'onion': 'red onion' → 'red'` | `ai_filter_compiler._coerce_ai_filters:162` keyword contained a space; only first word kept (all lists must be single-word for `contains_word`) | LLM returned `["red onion"]` → `["red"]` |
| `'milk': skipped N unknown excludes` | `compile_auto_cull_filters:264` title `excludes` not in `Terms` for that ingredient | `["powder","flavoured"]` but no milk title contained those |
| `'coconut milk': skipped N unknown brand_excludes` | `compile_auto_cull_filters:266` `brand_excludes` not in `Brands` for that ingredient | `["sanitarium"]` not in `[Ayam,Kara,Trident]` |
| `'onion': capped N excludes to 15` | `compile_auto_cull_filters:268` LLM returned more than 15 vocab-grounded `excludes` for an ingredient | LLM emitted 18 valid `excludes`, kept the first 15 |
| `'coconut milk': capped N brand_excludes to 15` | `compile_auto_cull_filters:270` same cap on `brand_excludes` | LLM emitted 17 valid `brand_excludes`, kept the first 15 |
| `skipped unknown ingredient 'garlic'` | `ai_filter_compiler._coerce_ai_filters:144` LLM invented a `search_term` not in `search_terms` | Dish has `onion`, LLM returned filter for `garlic` |
| `onion: skipped (invalid entry)` | `ai_filter_compiler._coerce_ai_filters:160` value for that term wasn't an object | `"onion": "red"` instead of `{"excludes":[...]}` |
| `response not an object` | `ai_filter_compiler._coerce_ai_filters:124` top-level JSON was not a dict | Model returned a bare string or array |
| `response missing filters` | `ai_filter_compiler._coerce_ai_filters:140` top-level shape was `{someKey: [..]}` with no `filters` key | Model skipped the contract wrapper |
| `filters not an object` | `ai_filter_compiler._coerce_ai_filters:142` `filters` was set but was not a dict | Model returned `"filters": "..."` |

Warnings are surfaced as `Warnings: a; b` in `FilterTunerPanel.vue` / `SummaryPanel.vue` subcard hints and do not block Apply — remaining valid keywords still merge.

**Cost:** one LLM call per action, ~1000-2000 tokens of deduped words for a typical dish, cached client-side by `hash(instruction+terms)` where applicable.

### Model selection

The model used for each leg is **user-selectable** from the Settings page. The choice is persisted server-side in `data/llm_settings.json` (atomic temp+replace write, parallels `dishes.json`). No `.env` rewrite is needed and no server restart is required — settings are read per request, so swapping models takes effect on the next generation call.

The model catalog is fetched from each provider:

- **Mistral** — `GET /v1/models`. Filtered to `capabilities.completion_chat == true`, `type != "fine-tuned"`, `archived == false`, `deprecation is None`, `billing_model_name == id` (drops `-latest` aliases and deprecated entries).
- **Google Gemini** — `GET /v1beta/models`. Filtered to models whose `supportedGenerationMethods` contains `generateContent` (the method the OpenAI-compat chat surface maps to). The `models/` prefix is stripped from each id.

The catalog is **file-cached** in `data/llm_models_cache.json` as `{fetched_at: ISO8601Z, providers: {mistral:{available,models,error}, google:{...}}}` with `fetched_at` timestamp. The Settings page shows the last-fetched time and a "Refresh model list" button (`POST /llm/models/refresh`) that re-fetches from both providers and overwrites the cache. Failures are isolated per provider (one provider down does not block the other). This keeps provider quota use minimal: the catalog is fetched once on first load and only again on a manual refresh. `ensure_cache_seeded()` seeds the cache on the first `GET /llm/models` hit when the file is missing.

The active selection shape:

```json
{
  "ingredient_model": {"provider": "mistral", "model_id": "mistral-medium-3-5"},
  "filter_model": {"provider": "google", "model_id": "gemini-3.1-flash-lite"},
  "exclude_non_food": true
}
```

`exclude_non_food` (bool, default `true`) controls whether non-food departments are filtered during search; persisted alongside the two model specs and read per request.

### Settings page endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/llm/models` | Returns the cached catalog + active selection. Seeds the cache on first call via `ensure_cache_seeded()`. |
| `POST` | `/llm/models/refresh` | Re-fetches both providers, overwrites the catalog cache, returns the new catalog + selection. |
| `GET` | `/llm/settings` | Returns the active selection only (`{ingredient_model, filter_model, exclude_non_food}`). |
| `PUT` | `/llm/settings` | Validates the body (`provider ∈ {mistral, google}`, non-empty `model_id`, `exclude_non_food` bool) and writes `data/llm_settings.json` atomically. `400` on invalid provider/model_id. |

The Settings page reads `/llm/models` on mount and uses "Refresh model list" for the cache refresh. "Save model selection" issues `PUT /llm/settings`. "Reset to defaults" restores the seeded defaults and re-saves.

### Storage location

| File | Purpose |
|------|---------|
| `data/llm_settings.json` | Active ingredient + filter model selection + `exclude_non_food`. Atomic tmp+replace; tolerant reads fall back to defaults. |
| `data/llm_models_cache.json` | Last-fetched model catalog `{fetched_at, providers}` with per-provider `{available,models,error}`. |

## Ingredient Resolution

`resolve_ingredients(dish, portions, regenerate)` resolves a dish name to a list of ingredient dicts. The LLM model is **not** hardcoded — it comes from `data/llm_settings.json` (`get_active_models()["ingredient_model"]` → `LLMClient(provider, model_id)`); the legacy `model_alias` shim (`small/medium/large`) is retained only for `tools/llm/llm_interactive.py` and tests.

1. **Curated JSON** — `data/dishes.json` lookup (21 dishes). If the dish key exists and `regenerate` is False, returns the structured ingredients directly (with `quantity`, `unit`, `search_term`, and optional `approx_quantity`/`approx_unit` for non-standard units; units are folded through `normalise_unit` at pipeline time).
2. **LLM Generation** — If not curated or `regenerate=True`, calls the configured ingredient model via `LLMClient.generate_ingredients(dish, portion)` (3-retry JSON-parse loop, rate-limit backoff), then validates through `parse_and_validate` (`LLMParseError` on hard failures: missing `dish_name`/`portion`/`ingredients`/`quantity`/`unit`/`search_term`; printed warnings on empty `search_term` / non-string `approx_unit`).
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
5. Writes results back to the CSV (append-safe; preserves existing `is_valid` values; `pk_hash` dedup prevents duplicates — see `optimiser_utils._compute_pk_hash`).

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

- Model: `ministral-3b-2512` (alias `small`, `MISTRAL_API_KEY` + `MISTRAL_RATE_LIMIT_SMALL` or `DEFAULT_RATE_LIMITS["small"]=10.0`)
- Each batch of 20 rows = 1 API call
- Typical runtime: ~1s per 20 rows

### Incremental validation

Re-running the script skips rows already marked `is_valid` (True or False), filling in only the blanks. The CSV is written in-place via `df.to_csv(index=False)`.

## Quantity Scaling

`parse_optimiser_columns(row)` is the core scaling function. It takes an optimiser CSV row enriched with LLM ingredient data and computes purchase quantities and proportional costs.

### Normalized units

Units are converted to a common base for comparison. All recipe + `approx_*` + pack units are folded through `normalise_unit` (`UNIT_ALIASES`, e.g. `eggs→each`, `pk→pack`, `tin→can`, `bases→base`; unknown pass-through; `base` is a one-way semantic alias so `6 eggs` sold as `10 ea` scales count-vs-count). Full alias map in `llm_utils.py:290` (`g/kg/oz/ml/l/tsp/tbsp/cup/each/pack/can/jar/bottle/bag/box/bunch/head/block/clove/slice/fillet/chop/stalk/medium/large/base`).

| Category | Units normalized to | Examples |
|----------|-------------------|----------|
| Weight | grams (g) | kg→1000, oz→28.35, lb→453.59, clove→5, mg→0.001 |
| Volume | milliliters (ml) | l→1000, cl→10, cup→240, tbsp→15, tsp→5 |
| Count | count | ea, unit, pk, pack, bunch, each (grouped) |
| Other | original lowercased | can, jar, bottle, bag, box, bunch, head, block, slice, fillet, chop, stalk, medium, large, base |

**Compound units** like `x 375ml` (meaning 10 × 375ml bottles) are expanded: multiplier parsed via `_parse_compound_unit`, quantity scaled accordingly.

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

21 hand-curated dishes, mapping dish name → `{"dish_name", "portion", "ingredients": [...]}`. Each ingredient has `quantity`, `unit`, and `search_term`. Ingredients with non-standard units (e.g. "1 can", "1 medium", "2 fillets") also include optional `approx_quantity` and `approx_unit` (in g or ml) for use as a fallback when supermarket packs are sold by weight/volume. Units are folded through `UNIT_ALIASES` at pipeline time.

### `data/dish_filters.json`

Curated include/exclude keyword presets per dish → `{dish: {search_term: {includes:[word], excludes:[word,...]}}}` (shape mirrors `IngredientFilterSet` without brand fields). Seeded into the dashboard's filter store on first load; `brand_*` fields are user-set only and never stored here.

### `data/full_results.csv`

Append-only results store. 18 CSV columns + 9 enriched fields (returned as `rows[]` in `OptimisationResult`; the CSV itself stores the 18, the 9 are computed per-request via `parse_optimiser_columns` + filter stamping):

| Column | Source | Stored in CSV? |
|--------|--------|----------------|
| `company` | optimiser | yes |
| `store` | optimiser | yes |
| `store_id` | optimiser | yes |
| `search_ingredient` | from DISHES / LLM | yes |
| `returned_ingredient` | API response | yes |
| `price` | API response | yes |
| `quantity` | parsed from pack size | yes |
| `measurement_unit` | parsed from pack size | yes |
| `per_unit_quantity` | comparative price qty | yes |
| `per_unit_price` | comparative price | yes |
| `is_sale` | promotion flag | yes |
| `sku` | API response | yes |
| `department` | Pass 1 Algolia / API | yes |
| `sub_department` | Pass 1 Algolia / API | yes |
| `datetime_created` | timestamp | yes |
| `date_created` | date | yes |
| `pk_hash` | SHA-256 of `store_id|sku|date_created` (16-char prefix) | yes |
| `is_valid` | **LLM validation** | yes (blank until validated) |
| `ingredient_quantity` | enriched from dish | no (computed) |
| `ingredient_measurement` | enriched | no |
| `ingredient_approx_quantity` | enriched | no |
| `ingredient_approx_unit` | enriched | no |
| `used_price` | `parse_optimiser_columns` | no |
| `purchase_quantity` | `parse_optimiser_columns` | no |
| `purchase_price` | `parse_optimiser_columns` | no |
| `scaling_ratio` | `parse_optimiser_columns` | no |
| `status` | `ok/approximate/incompatible_units` | no |
| `valid_ingredient` / `filter_reason` | `matches_*` filters | no |

Duplicates are detected via `pk_hash`. The `is_valid` column is blank for newly-appended rows until `llm_validate.py` fills it in.

### `data/llm_settings.json` / `data/llm_models_cache.json`

See [Storage location](#storage-location) above.

## Configuration

Environment variables (`.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MISTRAL_API_KEY` | — | Mistral API key (required for ingredient generation, validation, and when `ingredient_model`/`filter_model` points at Mistral) |
| `GOOGLE_API_KEY` | — | Google API key (required when either model points at `google`; `llm_client.GOOGLE_API_KEY_ENVS[0]`) |
| `MISTRAL_MODEL_SMALL` | `ministral-3b-2512` | Override for `small` alias (`MISTRAL_MODEL_ENV_PREFIX`) |
| `MISTRAL_MODEL_MEDIUM` | `mistral-medium-latest` | Override for `medium` alias |
| `MISTRAL_MODEL_LARGE` | `mistral-large-2512` | Override for `large` alias |
| `GOOGLE_FILTER_MODEL` | `gemini-3.1-flash-lite` | Legacy env for filter model (now via `llm_settings.json`; kept for fallback) |
| `MISTRAL_RATE_LIMIT_SMALL` | `10.0` | RPS for `small` alias |
| `MISTRAL_RATE_LIMIT_MEDIUM` | `0.5` | RPS for `medium` alias |
| `MISTRAL_RATE_LIMIT_LARGE` | `0.067` | RPS for `large` alias |
| `MISTRAL_RATE_LIMIT_CUSTOM` | `0.5` | RPS for explicit `LLMClient(provider=mistral, model_id=...)` |
| `GOOGLE_RATE_LIMIT` | `0.5` | RPS for explicit `LLMClient(provider=google, ...)` |

Defaults are in `llm_client.py:70-80` (`DEFAULT_MODELS`, `DEFAULT_RATE_LIMITS`, `DEFAULT_MISTRAL_RPS`/`DEFAULT_GOOGLE_RPS`). `get_active_models()` reads `data/llm_settings.json` per request — no restart needed after a model swap.

## Usage

### Web dashboard (primary)

```bash
# Generate custom dish (LLM)
curl -X POST http://127.0.0.1:8000/dishes/generate \
  -H "Content-Type: application/json" \
  -d '{"dish_name":"kumara & chorizo hash","base_portions":4}'

# Import pasted recipe (≤1000 chars; 200 rejected on non-recipe)
curl -X POST http://127.0.0.1:8000/dishes/import_text \
  -H "Content-Type: application/json" \
  -d '{"dish":"My Hash","base_portions":4,"recipe_text":"...paste..."}'

# Post-run AI filters (after GET /optimise/{id} is complete)
curl -X POST http://127.0.0.1:8000/optimise/{id}/ai_filter_preview \
  -H "Content-Type: application/json" \
  -d '{"instruction":"only red onions, no flavoured milk"}'

curl -X POST http://127.0.0.1:8000/optimise/{id}/auto_cull_preview \
  -H "Content-Type: application/json" \
  -d '{"current_filters":{}}'

# Persist settings
curl -X PUT http://127.0.0.1:8000/llm/settings \
  -H "Content-Type: application/json" \
  -d '{"ingredient_model":{"provider":"mistral","model_id":"mistral-medium-3-5"},"filter_model":{"provider":"google","model_id":"gemini-3.1-flash-lite"},"exclude_non_food":true}'
```

Dashboard equivalents: **Generate custom ingredients** / **Import pasted recipe** (LLM Recipe Builder), **Generate filters** (universal sentence) + **Auto refine** (dish-wide cull) in Filter Tuner + Summary — both show chip diff + `matched/total` preview and require explicit **Apply** (`POST /optimise/{id}/reapply`).

### Interactive pipeline (legacy CLI)

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

Options: `--dish`, `--portions`, `--address`, `--supermarkets` (1-7 or comma-separated names), `--distance`, `--requery` (true/false), `--regenerate` (force LLM even if curated), `--non-interactive`, `--model` (small/medium/large alias for `llm_interactive` only; web uses `llm_settings.json`).

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
- Ingredient generation for common dishes (21 curated + arbitrary LLM generation via configured `ingredient_model`)
- Pasted-recipe import with injection guard and soft `200 rejected` handling
- Post-run AI filter compilation (universal sentence + dish-wide auto-cull) grounded to `Terms`/`Brands` vocab, with additive preview before Apply
- Prompt-level control for units, portions, search terms
- Structured parsing with clear failure modes (`LLMParseError`, `GenerationConfigError`→503, `IngredientGenerationError`→502, `FilterGenerationError` soft, `RecipeRejectedError`→200)
- Unit normalisation across weight/volume/count (including `base` one-way alias)
- Incremental validation with no data loss

### Edge cases & limitations
- **Compound units** (e.g., `x 375ml`) are handled, but unusual pack formats can confuse the parser.
- **Cross-category approximation** (1ml≈1g) is a heuristic — works for water-like densities, not oils or powders.
- **Brand refiltering** now exists (`ai_filter_compiler` → `brand_includes`/`brand_excludes` via `matches_brand_filters`, OR/ reject semantics, same Levenshtein ≤0.35) but is **post-run only** — it reranks cached rows, it does not re-query the APIs.
- **Validation is offline** — `is_valid` is not consulted by the optimiser at runtime; it's purely a data-quality aid.
- **No automated feedback loop** — the user must manually review and re-run.
- **Garlic pricing** (noted in main README) — loose garlic is per-kg ($40+), so crushed garlic jars are returned instead.

### Performance
- 20 validated rows ≈ 1 second (1 API call to `ministral-3b-2512`).
- Full 4,800-row dataset ≈ 4 minutes at batch size 20.
- Ingredient generation (configured model) ≈ 2-3 seconds per dish.
- Filter compilation (configured filter model) ≈ 1-2 seconds per preview (one LLM call, ~1000-2000 tokens).

## Future Work

- **Runtime validation** — use `is_valid` during optimisation to prefer validated results.
- **Re-query from filters** — let post-run `brand_*`/`excludes` trigger a targeted re-search for under-matched ingredients instead of only reranking cached rows.
- **Brand-specific ingredient substitution** — at runtime, substitute ingredients based on what's cheapest or available at the selected store (e.g., "cheapest cheese" instead of a fixed search term).
- **Automated batch validation** — optionally run `llm_validate.py` as part of the optimiser pipeline (flag to enable/disable).
