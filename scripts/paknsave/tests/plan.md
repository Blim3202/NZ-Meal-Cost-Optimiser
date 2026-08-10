# PaknSave Unit Test Plan (Detailed)

## 1. Scope & Modules to Test

| Module | Functions / Classes / Components |
|---|---|
| `scripts/paknsave/paknsave_api.py` | `load_stores()`, `find_nearby_stores()`, `NON_FOOD_CATEGORIES`, `PaknSaveEdgeAPI` (`authenticate`, `_auth_headers`, `_store_cookies`, `get_stores`, `pass1_relevance_search`, `pass1_relevance_search_hits`, `pass2_per_store_pricing`, `search_ingredient`, `extract_price`, `extract_unit_price`, `get_product_name`, `get_product_size`), `PaknSaveMobileAPI` (`_ensure_token`, `_auth_headers`, `_is_food_product`, `search_products`, `get_stores`, `extract_price`, `extract_unit_price`, `get_product_name`, `get_product_size`), `PaknSaveAPI` (`search_ingredient`, `get_stores`, `extract_unit_price`, `get_product_name`, `get_product_size`), `create_api()` |
| `scripts/paknsave/paknsave_optimizer_edge.py` | `main()` (CLI parsing: `--requery`, `--distance`, positional address/dish, invocation of `foodstuffs_optimizer_edge` & `optimise`) |
| `scripts/paknsave/paknsave_optimizer_mobile.py` | `main()` (CLI parsing: `--requery`, `--distance`, positional address/dish, invocation of `foodstuffs_optimizer_mobile` & `optimise`) |
| `scripts/paknsave/paknsave_setup.py` | `_configure_stdout_utf8()`, `get_website_jwt()`, `fetch_stores_from_store_finder()`, `fetch_stores_from_edge_api()`, `fetch_stores_from_mobile_api()`, `_enforce_schema()`, `_parse_cleaned()`, `fetch_stores()`, `clean_stores()`, `run_full_setup()`, CLI argparse |
| `scripts/combined/optimizer_utils.py` (shared helpers) | `get_ingredients()`, `_build_quantity_map()`, `_resolve_dish_dict()`, `_resolve_dish()`, `parse_foodstuffs_volume_size()`, `parse_foodstuffs_mobile_unit()`, `build_edge_row()`, `build_mobile_row()`, `_parse_display_name()`, `_compute_pk_hash()`, `load_existing_hashes()`, `append_rows()`, `haversine()`, `geocode()`, `analyze_results()`, `foodstuffs_optimizer_edge()`, `foodstuffs_optimizer_mobile()`, `optimise()` |

---

## 2. Test Cases & Methods per Module

### A. `test_paknsave_api.py`
1. **`TestLoadStores`**:
   - `test_load_stores_valid`: loads CSV/JSON fixture, asserts returned list of dicts, float lat/lon conversion.
   - `test_load_stores_missing`: returns empty list when file doesn't exist.
2. **`TestFindNearbyStores`**:
   - `test_find_nearby_stores_radius`: points near East Tamaki, asserts stores within 5km are returned, sorted by `distance_km` ascending.
   - `test_find_nearby_stores_none`: remote coordinates return empty list.
3. **`TestNonFoodCategories`**:
   - `test_non_food_categories_content`: verify blacklist contains expected non-food category strings ("Dog", "Cat", "Baby & Toddler Food", etc.).
4. **`TestPaknSaveEdgeAPI`**:
   - `test_authenticate_success`: mock session.get (SITE_URL) and session.post (`/api/user/get-current-user`), assert `fs-user-token` cookie extracted and returned.
   - `test_authenticate_fails_no_token`: mock session returning no `fs-user-token` cookie, assert `RuntimeError`.
   - `test_get_stores`: mock GET `${EDGE_BASE}/store`, assert returns stores list.
   - `test_pass1_relevance_search_hits`: mock POST `products-index`, test filtering logic (keeps items with matchedWords and non-blacklisted category1).
   - `test_pass2_per_store_pricing`: mock POST `paginated/products`, verify Algolia filter syntax (`productID:xxx OR productID:yyy`) and sortOrder `PRICE_ASC`.
   - `test_extract_price`: static method test with promo vs regular pricing (cents to dollars).
5. **`TestPaknSaveMobileAPI`**:
   - `test_ensure_token`: mock cloudscraper post login/guest, assert access_token cached.
   - `test_search_products`: mock cloudscraper post search endpoint, test `food_only` filtering via `_is_food_product`.
   - `test_get_stores`: mock cloudscraper get physical stores, assert dict mapping ID to store dict.
6. **`TestPaknSaveAPIUnified`**:
   - `TestPaknSaveAPI`: verify routing between edge and mobile backends for `search_ingredient`, `get_stores`, and helper extractors.

### B. `test_paknsave_optimizer_edge.py` & `test_paknsave_optimizer_mobile.py`
1. **`TestOptimizerCLI`**:
   - `test_cli_default_args`: invoke `main()` with sys.argv patched to defaults, assert `foodstuffs_optimizer_edge`/`mobile` called with default chapel road address and spaghetti bolognese.
   - `test_cli_custom_flags`: invoke with `--requery false --distance 10`, assert parameters passed correctly.

### C. `test_paknsave_setup.py`
1. **`TestSetupPipeline`**:
   - `test_parse_cleaned`: test valid ("true", "false", "1", "0") and invalid boolean inputs (raises `ArgumentTypeError`).
   - `test_enforce_schema`: test that DataFrames missing columns are padded to 10 columns (`EXPECTED_COLUMNS`) in exact order.
   - `test_fetch_stores_edge`: mock Edge API store fetch, verify output schema.
   - `test_fetch_stores_mobile`: mock Mobile API login + store fetch, verify output schema.
   - `test_fetch_stores_store_finder`: mock Pak'nSave store-finder page with `__NEXT_DATA__`, test regex extraction of `contentstackStores` map and `regionStoreGroupings`, assert 60 stores returned.
   - `test_clean_stores`: drop null lat/lon rows.
   - `test_run_full_setup`: end-to-end setup orchestration test with mocked API calls, verifying CSV and JSON output files.

### D. `test_shared_optimizer_utils.py` (Shared Helpers)
1. **`TestDishResolution`**:
   - `_resolve_dish` with string ("spaghetti bolognese") vs structured dict.
   - `get_ingredients` and `_build_quantity_map`.
2. **`TestVolumeParsers`**:
   - `parse_foodstuffs_volume_size` (Edge API parsing: qty, unit, per_unit_qty, per_unit_price).
   - `parse_foodstuffs_mobile_unit` (Mobile API units + unitPrice parsing, including "3 x 31g" sachet/pack edge case and bare "ea" fallback).
3. **`TestRowBuilders`**:
   - `build_edge_row` and `build_mobile_row` creating exact CSV columns dicts (`CSV_COLUMNS`).
4. **`TestHashAndDedup`**:
   - `_compute_pk_hash` deterministic SHA-256 hash.
   - `append_rows` deduplication via `pk_hash`.
5. **`TestAnalyzeResults`**:
   - `haversine`, `geocode` (mocked), `analyze_results` cost summaries and per-ingredient comparison table.

---

## 3. Fixtures to Generate (`scripts/paknsave/fixture/generate_fixtures.py`)

1. **`edge_store_list_example.json`** + metadata: Response from `GET /v1/edge/store`.
2. **`edge_search_pass1_example.json`** + metadata: Response from `POST /v1/edge/search/products/query/index/products-index`.
3. **`edge_search_pass2_example.json`** + metadata: Response from `POST /v1/edge/search/paginated/products`.
4. **`mobile_login_example.json`** + metadata: Response from `POST /mobile/user/login/guest`.
5. **`mobile_stores_example.json`** + metadata: Response from `GET /mobile/store/physical`.
6. **`mobile_search_example.json`** + metadata: Response from `POST /mobile/ecomm-products/PNS/{store_id}/search`.
7. **`store_finder_page_example.html`** (or raw text/json extracted) + metadata: Response from `GET /store-finder` containing `__NEXT_DATA__`.

All fixtures will have accompanying `*_meta.json` files documenting endpoints, timestamps, and query parameters per `TEST_GUIDE.md`.
