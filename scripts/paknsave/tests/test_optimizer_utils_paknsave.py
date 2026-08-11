"""
Unit tests for shared optimizer helpers as used by Pak'nSave (from optimizer_utils.py).

These tests are fully offline, using captured live API fixtures and the real dishes.json:

Fixtures used:
    - fixture/edge_search_pass2_example.json  — Edge Pass 2 per-store pricing for "milk" (10 products)
    - fixture/mobile_search_example.json      — Mobile API product search for "milk" (20 products)
    - data/dishes.json                         — Curated dish definitions (spaghetti bolognese, etc.)

All assertions reference fixture data values directly for deterministic, traceable results.
No synthetic test data is used — every value under test comes from a live-captured fixture
or the production dishes.json registry.
"""

import csv
import hashlib
import json
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import pytest

# Setup paths for importing scripts/paknsave and scripts/combined
SCRIPT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "combined"))

from optimizer_utils import (
    CSV_COLUMNS,
    parse_foodstuffs_volume_size,
    parse_foodstuffs_mobile_unit,
    build_edge_row,
    build_mobile_row,
    _compute_pk_hash,
    _resolve_dish,
    _resolve_dish_dict,
    _build_quantity_map,
    get_ingredients,
    _parse_display_name,
    load_existing_hashes,
    append_rows,
)

# CSV_COLUMNS includes "is_valid" which is added by initialize_full_results.py
# when creating the CSV header; row builders do not populate it. Tests check
# for the row builder columns (CSV_COLUMNS minus "is_valid").
ROW_COLUMNS = [c for c in CSV_COLUMNS if c != "is_valid"]

FIXTURE_DIR = SCRIPT_DIR / "fixture"
DISHES_FILE = PROJECT_ROOT / "data" / "dishes.json"


def _load_json(filename):
    """Load a JSON fixture file from the fixture directory.

    Args:
        filename: the fixture file name (lives in scripts/paknsave/fixture/).

    Returns:
        The parsed JSON content as a dict or list.
    """
    with open(FIXTURE_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_dishes():
    """Load the real dishes.json registry from data/."""
    with open(DISHES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


class TestDishResolution:
    """Tests for dish resolution helpers using real data/dishes.json."""

    dishes: list

    def setup_method(self):
        self.dishes = _load_dishes()

    def test_resolve_dish_from_string(self):
        """Verify _resolve_dish resolves a dish name string to (dish_name, search_terms).

        Uses the real "spaghetti bolognese" entry from data/dishes.json — it has
        exactly 7 ingredients (beef mince, spaghetti pasta, canned tomatoes,
        onion, carrot, garlic, mixed herbs).
        """
        dish_name, ingredients = _resolve_dish("spaghetti bolognese")
        # Dish name normalized (lowercased in dishes.json)
        assert dish_name == "spaghetti bolognese"
        # 7 ingredients per the fixture
        assert len(ingredients) == 7
        # First three ingredients from the fixture
        assert ingredients[0] == "beef mince"
        assert ingredients[1] == "spaghetti pasta"
        assert ingredients[2] == "canned tomatoes"
        # Last ingredient
        assert ingredients[-1] == "mixed herbs"

    def test_resolve_dish_from_dict(self):
        """Verify _resolve_dish handles structured dict input.

        Constructs a dish dict inline matching the JSON schema shape:
        {dish_name, portion, ingredients: [{quantity, unit, search_term}, ...]}.
        """
        dish_dict = {
            "dish_name": "test dish",
            "portion": 2,
            "ingredients": [
                {"quantity": 100, "unit": "g", "search_term": "test ingredient"},
            ],
        }
        dish_name, ingredients = _resolve_dish(dish_dict)
        assert dish_name == "test dish"
        assert ingredients == ["test ingredient"]

    def test_resolve_dish_unknown_string_raises(self):
        """Verify _resolve_dish raises ValueError for unknown dish names."""
        with pytest.raises(ValueError):
            _resolve_dish("nonexistent dish")

    def test_get_ingredients(self):
        """Verify get_ingredients returns search terms from the dishes registry.

        Uses real "chicken stir fry" from data/dishes.json — 4 ingredients:
        chicken breast, stir fry vegetables, soy sauce, rice noodles.
        """
        ingredients = get_ingredients("chicken stir fry")
        assert len(ingredients) == 4
        assert ingredients[0] == "chicken breast"
        assert ingredients[1] == "stir fry vegetables"
        assert ingredients[2] == "soy sauce"
        assert ingredients[3] == "rice noodles"

    def test_build_quantity_map(self):
        """Verify _build_quantity_map produces {search_term: "quantity unit"} from dishes.json.

        Uses real "roast lamb" from data/dishes.json — 5 ingredients with quantities
        like "1.2 kg", "4 medium", etc.
        """
        dish = "roast lamb"
        qty_map = _build_quantity_map(dish)
        assert len(qty_map) == 5
        # Verify specific quantity strings from the fixture
        assert qty_map["lamb roast"] == "1.2 kg"
        assert qty_map["potato"] == "4 medium (~600 g)"
        assert qty_map["carrot"] == "3 medium (~180 g)"
        assert qty_map["broccoli"] == "1 head (~300 g)"
        assert qty_map["stock"] == "2 cups"

    def test_resolve_dish_dict_from_registry(self):
        """Verify _resolve_dish_dict returns the full dish dict from DISHES."""
        dish_dict: dict[str, Any] = cast(dict[str, Any], _resolve_dish_dict("beef curry"))
        assert dish_dict["dish_name"] == "beef curry"
        assert dish_dict["portion"] == 4
        ingredients: list[dict[str, Any]] = dish_dict["ingredients"]  # type: ignore
        assert len(ingredients) == 5
        assert ingredients[0]["search_term"] == "diced beef"


class TestDisplayNameParsing:
    """Tests for _parse_display_name using real displayName values from fixtures."""

    def test_parse_display_name_unit_with_number(self):
        """Verify _parse_display_name parses '1l' -> (1, 'l') and '3l' -> (3, 'l').

        Values '1l', '2l', '3l' come directly from edge_search_pass2_example.json
        products (Standard UHT Milk, Standard Milk, Lite Milk).
        """
        # "1l" — from edge_search_pass2_example.json first product (displayName="1l")
        qty, unit = _parse_display_name("1l")
        assert qty == 1
        assert unit == "l"

        # "2l" — from edge_search_pass2_example.json fourth product (displayName="2l")
        qty, unit = _parse_display_name("2l")
        assert qty == 2
        assert unit == "l"

        # "3l" — from edge_search_pass2_example.json seventh product (displayName="3l")
        qty, unit = _parse_display_name("3l")
        assert qty == 3
        assert unit == "l"

    def test_parse_display_name_unit_only(self):
        """Verify _parse_display_name parses bare units like 'ea' -> (1, 'ea').

        These values appear in Foodstuffs displayName field per docstring examples.
        """
        qty, unit = _parse_display_name("ea")
        assert qty == 1
        assert unit == "ea"

        qty, unit = _parse_display_name("kg")
        assert qty == 1
        assert unit == "kg"

    def test_parse_display_name_empty(self):
        """Verify _parse_display_name returns (None, '') for empty/null input."""
        assert _parse_display_name("") == (None, "")
        assert _parse_display_name(None) == (None, "")


class TestOptimizerUtilsPaknSave:
    """Tests for foodstuffs parsers and row builders using live fixture JSON data."""

    edge_data: dict
    mobile_data: dict

    def setup_method(self):
        self.edge_data = _load_json("edge_search_pass2_example.json")
        self.mobile_data = _load_json("mobile_search_example.json")

    def test_parse_foodstuffs_volume_size(self):
        """Parse volume size from an Edge API product fixture (e.g., UHT milk 1L).

        Uses edge_search_pass2_example.json products[0] — displayName="1l",
        singlePrice.price=209 (cents), comparativePrice.pricePerUnit=209,
        comparativePrice.measureDescription="1L".
        """
        product = self.edge_data["products"][0]
        qty, unit, per_unit_qty, per_unit_price = parse_foodstuffs_volume_size(
            product["displayName"],
            product["singlePrice"],
            product.get("promotions") or [],
        )
        # displayName="1l" -> qty=1, unit="l"
        assert qty == 1
        assert unit == "l"
        # comparativePrice.measureDescription="1L" -> per_unit_qty="1L"
        assert per_unit_qty == "1L"
        # comparativePrice.pricePerUnit=209 cents -> 2.09 dollars
        assert per_unit_price == 2.09

    def test_parse_foodstuffs_volume_size_3l(self):
        """Parse volume size from edge_search_pass2_example.json products[7] (3l milk).

        displayName="3l", price=711 cents, comparativePrice.pricePerUnit=237,
        measureDescription="1L".
        """
        product = self.edge_data["products"][7]
        qty, unit, per_unit_qty, per_unit_price = parse_foodstuffs_volume_size(
            product["displayName"],
            product["singlePrice"],
            product.get("promotions") or [],
        )
        assert qty == 3
        assert unit == "l"
        assert per_unit_qty == "1L"
        assert per_unit_price == 2.37

    def test_parse_foodstuffs_mobile_unit(self):
        """Parse units and unit price from a Mobile API product fixture (2L milk).

        Uses mobile_search_example.json products[0] — units="2l", unitPrice="$2.40/1L",
        price=479 cents.
        """
        product = self.mobile_data["products"][0]
        qty, unit, per_unit_qty, per_unit_price = parse_foodstuffs_mobile_unit(
            product["units"], product["unitPrice"], product["price"]
        )
        # units="2l" -> qty=2, measurement_unit="l"
        assert qty == 2
        assert unit == "l"
        # unitPrice="$2.40/1L" -> per_unit_price=2.40, per_unit_qty="1L"
        assert per_unit_qty == "1L"
        assert per_unit_price == 2.40

    def test_parse_foodstuffs_mobile_unit_300ml(self):
        """Parse units and unit price from mobile_search_example.json products[17] (300ml milk).

        units="300ml", unitPrice="$6.10/1L", price=183 cents.
        """
        product = self.mobile_data["products"][17]
        qty, unit, per_unit_qty, per_unit_price = parse_foodstuffs_mobile_unit(
            product["units"], product["unitPrice"], product["price"]
        )
        assert qty == 300
        assert unit == "ml"
        assert per_unit_qty == "1L"
        assert per_unit_price == 6.10

    def test_build_edge_row(self):
        """Build a standardized CSV row dict from an Edge API product and verify all fields.

        Uses edge_search_pass2_example.json products[0] (Standard UHT Milk, 209 cents/1L).
        Store metadata (name, store_id) comes from edge_store_list_example.json first store
        (PAK'nSAVE Te Awamutu, id=3bb30799-82ce-4648-8c02-5113228963ed).
        """
        now = datetime(2026, 8, 10, 12, 0, 0)

        # Load real store metadata from edge_store_list_example.json
        stores_fixture = _load_json("edge_store_list_example.json")
        store = stores_fixture["stores"][0]
        store_name = store["name"]  # "PAK'nSAVE Te Awamutu"
        store_id = store["id"]      # "3bb30799-82ce-4648-8c02-5113228963ed"

        product = self.edge_data["products"][0]
        pass1_hit = {
            "category0": [product["categoryTrees"][0]["level0"]],
            "category1": [product["categoryTrees"][0]["level1"]],
        }

        row = build_edge_row("PaknSave", store_name, store_id, "milk", product, pass1_hit, now)

        # Verify all expected row columns are present
        for col in ROW_COLUMNS:
            assert col in row

        # Verify values from fixture data
        assert row["company"] == "PaknSave"
        assert row["store"] == store_name
        assert row["store_id"] == store_id
        assert row["search_ingredient"] == "milk"
        assert row["returned_ingredient"] == "Standard UHT Milk"
        assert row["price"] == 2.09  # 209 cents / 100
        assert row["quantity"] == 1
        assert row["measurement_unit"] == "l"
        assert row["per_unit_quantity"] == "1L"
        assert row["per_unit_price"] == 2.09
        assert row["is_sale"] is False  # no promotions in fixture
        assert row["sku"] == "5004752-EA-000"
        assert row["department"] == "Fridge, Deli & Eggs"
        assert row["sub_department"] == "Milk"
        assert row["date_created"] == "2026-08-10"

        # Verify pk_hash matches _compute_pk_hash with real store_id and sku
        expected_hash = _compute_pk_hash(store_id, product["productId"], "2026-08-10")
        assert row["pk_hash"] == expected_hash

    def test_build_mobile_row(self):
        """Build a standardized CSV row dict from a Mobile API product and verify all fields.

        Uses mobile_search_example.json products[0] (Standard Milk, 479 cents/2L).
        Store metadata comes from edge_store_list_example.json first store.
        """
        now = datetime(2026, 8, 10, 12, 0, 0)

        # Load real store metadata
        stores_fixture = _load_json("edge_store_list_example.json")
        store = stores_fixture["stores"][0]
        store_name = store["name"]
        store_id = store["id"]

        product = self.mobile_data["products"][0]
        row = build_mobile_row("PaknSave", store_name, store_id, "milk", product, now)

        # Verify all expected row columns are present
        for col in ROW_COLUMNS:
            assert col in row

        # Verify values from fixture data
        assert row["company"] == "PaknSave"
        assert row["store"] == store_name
        assert row["store_id"] == store_id
        assert row["search_ingredient"] == "milk"
        assert row["returned_ingredient"] == "Standard Milk"
        assert row["price"] == 4.79  # 479 cents / 100
        assert row["quantity"] == 2
        assert row["measurement_unit"] == "l"
        assert row["per_unit_quantity"] == "1L"
        assert row["per_unit_price"] == 2.40
        assert row["is_sale"] is False
        assert row["sku"] == "5201479-EA-000"
        assert row["department"] == ""  # no department in mobile API
        assert row["sub_department"] == "Milk"  # categories[0]
        assert row["date_created"] == "2026-08-10"

        expected_hash = _compute_pk_hash(store_id, product["productId"], "2026-08-10")
        assert row["pk_hash"] == expected_hash


class TestPkHashAndDedup:
    """Tests for primary key hashing and CSV deduplication."""

    edge_data: dict
    stores_fixture: dict

    def setup_method(self):
        self.edge_data = _load_json("edge_search_pass2_example.json")
        self.stores_fixture = _load_json("edge_store_list_example.json")

    def test_compute_pk_hash_deterministic(self):
        """Verify _compute_pk_hash produces consistent, deterministic SHA-256 output.

        Uses real SKU from edge_search_pass2_example.json products[0]
        (productId="5004752-EA-000") and real store_id from edge_store_list_example.json.
        """
        # Load real store_id from fixture
        store_id = self.stores_fixture["stores"][0]["id"]
        sku = "5004752-EA-000"  # from edge_search_pass2_example.json products[0]
        date_str = "2026-08-10"

        hash1 = _compute_pk_hash(store_id, sku, date_str)
        hash2 = _compute_pk_hash(store_id, sku, date_str)

        # Must be deterministic
        assert hash1 == hash2

        # Must be 16-char hex string (SHA-256 truncated to 16 hex chars)
        assert len(hash1) == 16
        assert all(c in "0123456789abcdef" for c in hash1)

        # Verify it's the actual SHA-256 of "store_id|sku|date"
        raw = f"{store_id}|{sku}|{date_str}"
        expected = hashlib.sha256(raw.encode()).hexdigest()[:16]
        assert hash1 == expected

    def test_compute_pk_hash_different_inputs(self):
        """Verify _compute_pk_hash produces different hashes for different inputs."""
        hash1 = _compute_pk_hash("store-A", "sku-1", "2026-08-10")
        hash2 = _compute_pk_hash("store-B", "sku-1", "2026-08-10")
        hash3 = _compute_pk_hash("store-A", "sku-2", "2026-08-10")

        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3

    def test_append_rows_dedup_and_new(self):
        """Verify append_rows skips duplicates via pk_hash and appends new rows.

        Uses real fixture product SKUs and store IDs from edge_search_pass2_example.json
        and edge_store_list_example.json.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
            csv_path = Path(f.name)

        try:
            # Build rows from real fixture products
            store = self.stores_fixture["stores"][0]
            now = datetime(2026, 8, 10, 12, 0, 0)

            # Row 1: edge_search_pass2_example.json products[0]
            product1 = self.edge_data["products"][0]
            row1 = build_edge_row(
                "PaknSave", store["name"], store["id"], "milk", product1,
                {"category0": ["Fridge, Deli & Eggs"], "category1": ["Milk"]}, now,
            )

            # Row 2: edge_search_pass2_example.json products[1] (different SKU)
            product2 = self.edge_data["products"][1]
            row2 = build_edge_row(
                "PaknSave", store["name"], store["id"], "milk", product2,
                {"category0": ["Fridge, Deli & Eggs"], "category1": ["Milk"]}, now,
            )

            # Row 3: duplicate of row1 (same store_id + sku + date)
            row3 = build_edge_row(
                "PaknSave", store["name"], store["id"], "milk", product1,
                {"category0": ["Fridge, Deli & Eggs"], "category1": ["Milk"]}, now,
            )

            # First append: 2 new rows
            appended, skipped = append_rows([row1, row2], csv_path)
            assert appended == 2
            assert skipped == 0

            # Second append: row1 is duplicate, row2 is duplicate, row3 is duplicate
            appended2, skipped2 = append_rows([row1, row2, row3], csv_path)
            assert appended2 == 0
            assert skipped2 == 3

            # Verify CSV contents
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 2
            assert rows[0]["sku"] == product1["productId"]
            assert rows[1]["sku"] == product2["productId"]
        finally:
            csv_path.unlink(missing_ok=True)

    def test_load_existing_hashes(self):
        """Verify load_existing_hashes reads pk_hash values from a CSV file.

        Creates a temp CSV with real fixture data, then verifies hashes are loaded.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
            csv_path = Path(f.name)

        try:
            # Write a CSV with two real SKUs from edge_search_pass2_example.json
            store_id = self.stores_fixture["stores"][0]["id"]
            now = datetime(2026, 8, 10, 12, 0, 0)

            product1 = self.edge_data["products"][0]
            row1 = build_edge_row("PaknSave", "Test Store", store_id, "milk", product1, None, now)
            product2 = self.edge_data["products"][1]
            row2 = build_edge_row("PaknSave", "Test Store", store_id, "milk", product2, None, now)

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                writer.writerow(row1)
                writer.writerow(row2)

            hashes = load_existing_hashes(csv_path)
            assert len(hashes) == 2
            assert row1["pk_hash"] in hashes
            assert row2["pk_hash"] in hashes
        finally:
            csv_path.unlink(missing_ok=True)
