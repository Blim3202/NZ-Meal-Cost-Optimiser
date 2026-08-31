# CLI vs Dashboard Equivalence Table

This document maps user goals to the CLI entry point, the Vue dashboard surface,
and the underlying FastAPI endpoint — the cross-reference the docs previously
lacked. If you're a new user wondering "I ran the CLI optimiser — what does the
same flow look like in the dashboard?" or vice versa, this table is the answer.

| User goal | CLI entry point | Vue dashboard surface | FastAPI endpoint |
|---|---|---|---|
| Run a full optimisation | `python -m tools.<brand>.<brand>_optimiser_edge "<addr>" "<dish>"` (or `_mobile` for legacy) | Optimiser dashboard → preset mode → "Compare prices" | `POST /optimise/jobs` → poll `GET /optimise/{id}` |
| Run all 3 brands in one go | `python -m tools.llm.llm_interactive --dish "..." --address "..."` | Optimiser dashboard (no brand filter = all 3) | `POST /optimise/jobs` with no `companies` filter |
| Generate a custom dish from a name | (none — only available via web) | "Generate custom ingredients" button in custom-recipe mode | `POST /dishes/generate` |
| Generate a custom dish from pasted recipe text | (none) | `/test` only — LLM Recipe Builder page | `POST /dishes/import_text` |
| Save a custom recipe as a preset | (none) | My Dishes → "Save as preset" | `POST /dishes/save` |
| Edit / delete a saved dish | (edit `data/dishes.json` by hand) | My Dishes card grid | `GET /dishes`, `DELETE /dishes/{key}` |
| Refresh / seed store list (Pak'nSave) | `python -m tools.paknsave.paknsave_setup` (default: edge; `--source mobile` for legacy; `--source store_finder` for the website parser) | (none) | — |
| Refresh / seed store list (New World) | `python -m tools.newworld.newworld_setup` (default: edge; `--source mobile` for legacy) | (none) | — |
| Refresh / seed store list (Woolworths) | `python -m tools.woolworths.woolworths_setup` | (none) | — |
| Adjust per-ingredient product filters (incl/excl keywords) | Edit `data/dish_filters.json` by hand, OR use LLM-generated filters (write `seedPresetRules` in `/test` only) | Filter tuner (filter tab in tabbed results card) — `POST /optimise/{id}/filter_preview` + `reapply` | `POST /optimise/{id}/reapply`, `POST /optimise/{id}/filter_preview` |
| Edit a single ingredient's quantity / unit / search term mid-run | (none) | "Update ingredient prices" in the tuner | `POST /optimise/{id}/update_ingredients` |
| Validate cached results (`is_valid` column) | `python -m tools.llm.llm_validate --max-rows N --batch-size N` | (none — validation runs as part of `llm_interactive`) | — |
| Validate a dish's results in a one-shot | `python -m tools.llm.llm_interactive --validate` | (implicitly enabled in `/test` tuner) | — |
| Choose LLM model | `tools/llm/llm_interactive --model {small\|medium\|large}` | Settings → Models (`/test` only) | `PUT /llm/settings` |
| Browse the LLM model catalog | (none) | Settings → Models → "Refresh model list" (`/test` only) | `GET /llm/models`, `POST /llm/models/refresh` |
| Geocode an address | (used implicitly by optimisers via `optimiser_utils.geocode`) | Dashboard "Resolve setup" | `GET /geocode?address=...` |
| Preview which stores would be searched | (none) | Map panel updates as the user types distance / changes settings | `GET /stores/nearby` |
| Read the in-tree technical docs | Open `.md` files in editor | `/test` Documentation page | `GET /tech-docs`, `GET /tech-docs/{name}` |
| Export the current result to CSV | (none — the per-run `<brand>_latest_results.csv` files are written by the optimisers) | "Download CSV ↓" on the all-results heading (Dashboard) | (client-side only; no backend endpoint) |
| Run the test suite | `python -m pytest` | (none) | — |
| Replay / sanity-check live API behaviour | `python -m exploration.paknsave.check_foodstuffs_parser_parity` (Foodstuffs parser idempotence)<br>`python -m exploration.newworld.newworld_highlight_permutations` (NW Edge `_highlightResult` / dead indices) | (none) | — |
| Run the FastAPI server | `.venv\Scripts\uvicorn NZMealOptimiser.web.main:app --host 0.0.0.0 --port 8000` | — | (the server itself) |
| Read this documentation | Open `.md` files | `/test` Documentation page | `GET /tech-docs` |

## Notes

- The "CLI" column for `/test`-only features (Settings → Models, Recipe Builder, Documentation page) is deliberately empty — those are web-only.
- The "FastAPI endpoint" column is the *backend* behind the Vue dashboard. Some Vue buttons call multiple endpoints in sequence (e.g. "Save as preset" → `POST /dishes/save` + `GET /dishes` for refetch).
- The CSV export row is a notable case: the CSV is **client-side** in the Vue app (per `Vue_Dashboard.md` "Behaviour Notes" → "CSV export" — `Blob` → `<a download>`). No backend endpoint involved.
- The store-setup CLIs are deliberately not surfaced in the dashboard. They're a developer / ops task, not a user task.