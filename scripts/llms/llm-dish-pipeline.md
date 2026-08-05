# LLM-Integrated Interactive Dish Pipeline — Design

## Goal

Replace the hardcoded `DISH_INGREDIENTS` dict (21 dishes) with an LLM-backed interactive system that:
1. Generates ingredient lists for **any** dish the user describes via the Mistral API
2. Keeps a curated reference set of dishes in `data/dishes.json` (numeric portions only, no ingredients) — used for quick lookup of known dishes
3. If a dish is not in the curated set, the LLM dish builder generates ingredients on the fly (no caching of LLM output)
4. Interactively lets the user review, edit, and filter ingredients before searching
5. Routes to the correct existing optimizer+supermarket combinations (up to 6)
6. Parses optimizer output columns to compute per-ingredient scaling ratios (quantity mismatch between LLM-generated amount and supermarket pack size)

## Models (Mistral API)

| Alias  | Model ID                 | Rate Limit         |
|--------|--------------------------|--------------------|
| small  | `ministral-3b-2512`      | 10 req/s           |
| medium | `mistral-medium-latest`  | 0.5 req/s          |
| large  | `mistral-large-2512`     | 1 req / 15 seconds |

**Initial assignment:** use **medium** for `generate_ingredients`. Promote to `large` later if quality is inadequate. Model per task configured via `.env` (no code change needed to switch).

---

## Files to Create

```
scripts/llms/
├── DESIGN.md                  # This file
├── __init__.py                # Empty
├── test_llm_client.py         # Phase 1: smoke test (call Mistral, print JSON)
├── llm_client.py              # Mistral API wrapper (single responsibility)
├── ingredient_parser.py       # Validate/parse/normalize LLM JSON output
├── quantity_scaling_parser.py # Parse optimizer columns → compute scaling ratios
└── llm_interactive.py         # Phase 3: full interactive CLI orchestrator

data/
└── dishes.json                # Curated dish reference set (search_terms + default_portions as int)

.gitignore                     # Add .env
.env                           # MISTRAL_API_KEY=... (gitignored)
requirements.txt               # + python-dotenv, mistralai
```

### `.env` example

```
MISTRAL_API_KEY=your_key_here
MISTRAL_MODEL_SMALL=ministral-3b-2512
MISTRAL_MODEL_MEDIUM=mistral-medium-latest
MISTRAL_MODEL_LARGE=mistral-large-2512
MISTRAL_RATE_LIMIT_SMALL=10
MISTRAL_RATE_LIMIT_MEDIUM=0.5
MISTRAL_RATE_LIMIT_LARGE=0.067
```

Rate limits are read by `llm_client.py` and enforced via `time.sleep` before each API call.

**Also modified (Phase 3 only):**
| File | Function | Change |
|------|----------|--------|
| `scripts/combined/optimizer_utils.py` | `foodstuffs_optimizer_edge` (L714) | Accept `dish` param as JSON object `{dish_name, portions, ingredients}` instead of string `dish_name` |
| `scripts/combined/optimizer_utils.py` | `foodstuffs_optimizer_mobile` (L887) | Same |
| `scripts/woolworths/woolworths_optimizer.py` | `query_and_save` (L110) | Accept `dish` param as JSON object, extract `dish_name` internally |

When `dish` is a string (backward compat), functions call `get_ingredients(dish_name)` as before. When `dish` is a dict, the `ingredients` list from the dict is used directly. Default distance for Woolworths also changed from 2 km → 5 km for consistency.

---

## Phase 1: `test_llm_client.py` — Smoke Test

**Status:** PASSED on both small and medium models.

**Key findings:**
- `response_format={"type": "json_object"}` eliminates the need for "Return ONLY valid JSON" guardrails in the prompt — the model produces clean JSON every time
- Single `search_term` (string, not list) per ingredient is sufficient — the API returns ~20 results per query which covers enough area
- Both `ministral-3b-2512` (small) and `mistral-medium-latest` (medium) produce valid JSON
- `portion` field must always be an **int** (not a string) — both models should return numeric portions
- `quantity` field can be int or float (small model returns int, medium may return float)

**Test results:**

| Test | Model | Dish | Portions | Ingredients | JSON Valid |
|------|-------|------|----------|-------------|-----------|
| 1 | medium | spaghetti bolognese | 4 | 10 | Yes |
| 2 | small | spaghetti bolognese | 4 | 11 | Yes |

**Updated prompt** (simplified — JSON mode handles format enforcement, portions always numeric):

```
You are a recipe ingredient generator. Given a classic or user stylised dish and portion count,
return a JSON object with ingredients and quantities.

Dish: {dish}
Portions: {portions}

Return a JSON object with this shape:
{{
  "dish_name": "...",
  "portion": 4,
  "ingredients": [
    {{
      "quantity": 500,
      "unit": "g",
      "search_term": "beef mince"
    }}
  ]
}}

Rules:
- Each ingredient must have exactly ONE search_term (a single string, not a list).
- "search_term" is the term to query supermarket APIs (use the most common NZ supermarket name).
- "portion" must be an integer (number of servings), not a string.
- "quantity" must be a number (int or float).
- "unit" must be a string (e.g. "g", "ml", "tbsp", "cloves", "unit").
- OMIT small or condiment ingredients like "water", "oil", "salt", "pepper" UNLESS the dish is centred around them (e.g. "deep fried chicken" keeps oil for frying, "pepper crab" keeps pepper).
- Do not include notes or extra fields.
```

**Usage:**
```
python -m scripts.llms.test_llm_client
python -m scripts.llms.test_llm_client --dish "chicken katsu" --portions 2
python -m scripts.llms.test_llm_client --model small
```

---

## Phase 2: Production Modules

### `llm_client.py`

```python
class LLMClient:
    def __init__(self, model_alias: str = "medium"):
        # Reads MISTRAL_API_KEY from env
        # Resolves model_alias → actual model ID via env vars
        # e.g. os.getenv("MISTRAL_MODEL_MEDIUM") → "mistral-medium-latest"
        # Reads rate limit from env: MISTRAL_RATE_LIMIT_{ALIAS} (e.g. "0.5" for 0.5 req/s)
        # Enforces rate limit before each API call via time.sleep

    def generate_ingredients(self, dish_name, portion=4) -> dict:
        """Build prompt, enforce rate limit, call Mistral with response_format={"type": "json_object"},
        return parsed JSON dict.
        Retries up to 2x if JSON parsing fails.
        Raises LLMGenerationError on 3rd failure.
        """
```

### `ingredient_parser.py`

```python
class ParsedDish:
    dish_name: str
    portion: int              # always int, never string
    ingredients: list[dict]   # [{quantity, unit, search_term}]

def parse_and_validate(raw_json: dict) -> ParsedDish:
    """Structural validation:
      - dish_name must be present (str)
      - portion must be int (reject string, coerce float→int if safe)
      - ingredients must be non-empty list
      - each ingredient must have 'quantity' (number), 'unit' (str), 'search_term' (str, single term)
    Warnings (non-fatal): missing quantity/unit, empty search_term
    """

def dish_to_json(dish: ParsedDish, model: str) -> dict:
    """Serialize for dishes.json (adds last_generated, generator_model)."""

def json_to_dish(record: dict) -> ParsedDish:
    """Deserialize from dishes.json."""
```

### `quantity_scaling_parser.py`

```python
def parse_optimizer_columns(row: dict) -> dict:
    """Parse optimizer output columns [search_ingredient, returned_ingredient, quantity, measurement_unit, per_unit_price]
    and compute the scaling ratio between the LLM-generated ingredient quantity and the supermarket pack size.

    Args:
        row: dict with keys from full_results.csv columns

    Returns:
        {
            "search_ingredient": str,
            "returned_ingredient": str,
            "quantity": number,          # LLM-generated quantity
            "measurement_unit": str,     # LLM-generated unit
            "per_unit_price": number,    # price per unit from supermarket
            "pack_quantity": number,     # quantity from the supermarket API result
            "pack_unit": str,            # measurement_unit from the supermarket API result
            "scaling_ratio": float,      # LLM quantity / pack quantity
            "used_price": float,         # scaled cost for the amount the user needs
            "purchase_quantity": int,    # number of packs to buy (ceil if ratio > 1)
            "purchase_price": float,     # total cost for the number of packs
        }

    Rules:
      - If scaling_ratio <= 1: used_price = per_unit_price * scaling_ratio (fraction of pack)
        purchase_quantity = 1 (still buy 1 pack), purchase_price = per_unit_price
      - If scaling_ratio > 1: purchase_quantity = ceil(scaling_ratio) (round up to nearest whole pack)
        purchase_price = per_unit_price * purchase_quantity
        used_price = per_unit_price * scaling_ratio (proportional cost for what was actually used)
    """
```

This parser sits between the optimizer output and the final cost comparison, enabling accurate per-ingredient cost calculation when pack sizes don't match the recipe quantity.

### `data/dishes.json` schema (curated reference set only)

```json
{
  "spaghetti bolognese": {
    "search_terms": ["spaghetti", "bolognese sauce", "parmesan"],
    "default_portions": 4
  }
}
```

Key differences from a previous iteration:
- **No `ingredients` field** — ingredients are generated by the LLM, not stored
- **No `last_generated`, `generator_model`** — no persistence of LLM output
- **`default_portions` is always an int** — never a string
- **`search_terms` is a list of strings** — terms used by the optimizer to find products
- This is a curated reference set for known dishes only
- If a dish is not in this set, the LLM dish builder generates ingredients on the fly (no caching)

### Ingredient Resolution Order

```
1. dishes.json curated set  ← if dish_key exists → use search_terms + default_portions (int)
2. LLM dish builder  ← generate fresh, no caching
3. Fallback [dish_name]  ← legacy single-search-term behavior
```

No caching of LLM-generated dishes. Every new dish request goes through the LLM.

### Dish Object Format (for optimizer functions)

Optimizer functions (`foodstuffs_optimizer_edge`, `foodstuffs_optimizer_mobile`, `query_and_save`) now accept a `dish` parameter that can be either:
- A **string** (backward compat) — treated as `dish_name`, calls `get_ingredients(dish_name)` internally
- A **dict** with shape `{"dish_name": str, "portion": int, "ingredients": list[dict]}` — uses the explicit ingredients list directly

The dict format enables the LLM-generated ingredient list to flow directly into the optimizer without intermediate parsing of `DISH_INGREDIENTS`.

---

## Phase 3: `llm_interactive.py` — Full Interactive CLI

### Step-by-Step Flow

```
STEP 1: Collect inputs
  Address [> interactive prompt, or --address CLI arg]
  Distance [default 5 km, or --distance]
  Dish name [prompt or --dish]
  Portions [default 4, or --portions]  ← always numeric (int)
  Supermarket [default "all", prompt, or --supermarkets 1,2,3,... per terminal group]

STEP 2: Get ingredients
  → resolve_ingredients(dish, portions, regenerate)
  → prints source: [curated] / [LLM] / [fallback]

STEP 3: Review & refinement (interactive)
  Shows ingredient table:
    #  Ingredient         Qty  Unit  Search Term
    1  beef mince        500   g     "beef mince"
    2  spaghetti pasta   500   g     "spaghetti pasta"
    ...
  Actions: [A]ccept all  [C]hange #N  [D]elete #N  [R]egenerate  [Q]uit
    A → proceed
    C 4 → prompt "New quantity:" "New unit:" "New search term:"
    D 7 → remove ingredient
    R → re-call LLM (same params, different generation)
    Q → exit

STEP 4: Query optimizers (for each selected supermarket)
  For each selected combo:
    brand in ["pns_edge","pns_mobile","nw_edge","nw_mobile","woolworths"]:
      match brand:
        woolworths → query_and_save(addr, dish_dict, requery, distance=dist)
        pns_edge   → foodstuffs_optimizer_edge(PNS, find_nearby_pns, "PaknSave", "Pak'nSave", ..., dish=dish_dict)
        etc.

STEP 5: Optimise & present
  For each brand used:
    optimise(dish_name, company=company)
  Cross-brand cheapest winner at bottom of table.

STEP 6: Apply quantity scaling
  For each ingredient in the results:
    → quantity_scaling_parser.parse_optimizer_columns(row)
    → display used_price, purchase_quantity, purchase_price alongside raw results
```

### CLI Arguments

```powershell
python -m scripts.llms.llm_interactive [OPTIONS]

Fields:
  --address "123 Queen St, Auckland CBD"     # default: interactive prompt
  --distance 5                                # km, default 5
  --dish "spaghetti bolognese"                # default: interactive prompt
  --portions 4                                # default: 4, always numeric (int)
  --supermarkets "pns_edge,woolworths"        # comma, default "all"

Flags:
  --regenerate            # force LLM even if dish is in curated set
  --requery false         # skip API calls, use existing CSV
  --non-interactive       # accept LLM output without review step
```

Omitted fields → interactive prompt (unless `--non-interactive` + default exists).

---

## Backward Compatibility

- `DISH_INGREDIENTS` and `DISH_QUANTITIES` are **removed** from `optimizer_utils.py`
- `get_ingredients(dish_name)` is **removed** — replaced by `resolve_ingredients(dish)` which checks curated set then LLM
- Optimizer functions work identically when `dish` is a string (backward compat path)
- All existing CLI scripts (`paknsave_optimizer_*.py`, etc.) continue to work independently — they pass a string `dish_name` and get the old behavior
- `dishes.json` is additive — no migration needed for hardcoded dishes

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| `--requery false` but no CSV data for today | "No results found. Run with --requery true to query" |
| LLM returns malformed JSON | Retry 2x → fallback to manual input |
| `--regenerate` + `--requery false` | Regenerate ingredients from LLM, skip re-querying API |
| Dish not in curated set | LLM generates, no caching, proceeds |
| `portion` returned as string by model | Parser rejects, retries with explicit "must be integer" instruction |
| `quantity` returned as string by model | Parser coerce to float, warn |
| Scaling ratio = 0 (LLM qty < pack qty) | used_price = per_unit_price * ratio, purchase_quantity = 1 |
| Scaling ratio > 1 (LLM qty > pack qty) | purchase_quantity = ceil(ratio), purchase_price = per_unit_price * purchase_quantity |

---

## Stretch Goals (not in Phase 1-3)

- `llm_client.filter_products(products, ingredient)` — NLP filtering of API results
- Per-ingredient brand preference (e.g. "only organic" or "buy Pams")
- Calorie/nutrition estimates
- Ingredient substitution ("no beef → use chicken")

---

## Model Assignment (Phase 1)

| Step | Model | Model from env |
|------|-------|-----------------------|
| `generate_ingredients` | medium | `MISTRAL_MODEL_MEDIUM` → `mistral-medium-latest` |

Future: if quality is insufficient (e.g. wrong quantities split, wrong search terms for NZ context), boost `generate_ingredients` to `large` by updating `.env`.

---

## Implementation Order

1. **Phase 1:** `test_llm_client.py` — smoke test against real Mistral endpoint. (DONE)
2. **Phase 2:** `llm_client.py`, `ingredient_parser.py`, `quantity_scaling_parser.py`, `init_dishes_json.py`, `.env` + `.gitignore` update.
3. **Phase 3:** `llm_interactive.py` + modify optimizer functions for `dish` dict param + `quantity_scaling_parser` integration.