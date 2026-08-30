# API claim verifiers

These scripts probe live New Zealand grocery APIs to verify documented
behaviour. They are **not pytest tests** — they hit the network on every
invocation and are intended for ad-hoc verification by a human or CI
smoke job, not regression testing.

Each script's docstring points to the relevant section of
`docs/technical/*_API.md` so the documented claim and its executable
verifier live side-by-side.

## Scripts

| Script | Verifies | Source docs |
|---|---|---|
| `newworld_highlight_permutations.py` | New World Edge Algolia `_highlightResult` / `matchedWords` semantics, the 8 dead index names, Pass 2 negative check | `docs/technical/NewWorld_API.md` §6.3, §6.4, §6.8 |
| `foodstuffs_parser_parity.py` | `parse_foodstuffs_volume_size` / `parse_foodstuffs_mobile_unit` are idempotent on live NW Edge + Mobile API products (idempotence only — correctness is in `tests/combined/test_parser_utils.py`) | `docs/technical/NewWorld_API.md` §6, §10 |
| `paknsave_setup_permutations.py` | `fetch_stores(source=...)` returns 10-column schema for `edge`/`mobile`/`store_finder` × `cleaned` ∈ {True, False} (6 permutations). Mutates `data/paknsave_stores.csv` as a side effect — back up first if you care | `docs/technical/PaknSave_API.md` §9 |
| `newworld_setup_permutations.py` | `fetch_stores(source=...)` returns 10-column schema for `edge`/`mobile` × `cleaned` ∈ {True, False} (4 permutations). Mutates `data/newworld_stores.csv` as a side effect | `docs/technical/NewWorld_API.md` §9 |

## Running

```powershell
python -m scripts.api_claims.newworld_highlight_permutations
python -m scripts.api_claims.foodstuffs_parser_parity
python -m scripts.api_claims.paknsave_setup_permutations
python -m scripts.api_claims.newworld_setup_permutations
```

## When to run

- After a documented API change in `docs/technical/*_API.md`.
- When the corresponding `tests/` suite starts failing in a way that
  suggests the live API has drifted from the documented contract.
- Not as part of regular CI — these scripts are slow and depend on the
  live API being reachable and behaving as documented.
