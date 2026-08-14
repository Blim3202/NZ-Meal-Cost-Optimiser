"""
Unit tests for shared optimizer helpers as used by New World (from optimizer_utils.py).

These tests are fully offline, using captured live API fixtures and the real dishes.json:

Fixtures used:
    - fixture/edge_store_list_example.json    Edge API store list (148 stores)
    - fixture/edge_search_pass2_example.json    Edge Pass 2 per-store pricing for "milk" (10 products)
    - fixture/edge_search_pass1_example.json   Edge Pass 1 relevance hits (40 hits, with category0/category1)
    - fixture/mobile_search_example.json        Mobile API product search for "milk" (20 products)
    - fixture/mobile_login_example.json         Mobile guest login response
    - data/dishes.json                          Curated dish definitions (spaghetti bolognese, etc.)

All assertions reference fixture data values directly for deterministic, traceable results.
No synthetic test data is used for API responses — every value under test comes from a
live-captured fixture or the production dishes.json registry.

Exception: simple permutation tests for parsers/filters/calculations (e.g. _parse_display_name,
NON_FOOD_CATEGORIES membership, haversine, pk_hash arithmetic) use inline inputs since these
are deterministic pure functions not involving API data retrieval.
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
    _resolve_dish_terms,
    _resolve_dish_data,
    _build_quantity_map,
    get_ingredients,
    _parse_display_name,
    load_existing_hashes,
    append_rows,
    haversine,
)
import newworld_api

from newworld_api import (
    NON_FOOD_CATEGORIES,
    NewWorldEdgeAPI,
    NewWorldMobileAPI,
    NewWorldAPI,
    create_api,
    find_nearby_stores,
    load_stores,
)

ROW_COLUMNS = [c for c in CSV_COLUMNS if c != "is_valid"]

FIXTURE_DIR = SCRIPT_DIR / "fixture"
DISHES_FILE = PROJECT_ROOT / "data" / "dishes.json"


def _load_json(filename):
    with open(FIXTURE_DIR / filename, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def _load_dishes():
    with open(DISHES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


class TestDishResolution:
    """Tests for dish resolution helpers using real data/dishes.json."""

    dishes: list

    def setup_method(self):
        self.dishes = _load_dishes()

    def test_resolve_dish_from_string(self):
        dish_name, ingredients = _resolve_dish_terms("spaghetti bolognese")
        assert dish_name == "spaghetti bolognese"
        assert len(ingredients) == 7
        assert ingredients[0] == "beef mince"
        assert ingredients[1] == "spaghetti pasta"
        assert ingredients[2] == "canned tomatoes"
        assert ingredients[-1] == "mixed herbs"

    def test_resolve_dish_from_dict(self):
        dish_dict = {
            "dish_name": "test dish",
            "portion": 2,
            "ingredients": [
                {"quantity": 100, "unit": "g", "search_term": "test ingredient"},
            ],
        }
        dish_name, ingredients = _resolve_dish_terms(dish_dict)
        assert dish_name == "test dish"
        assert ingredients == ["test ingredient"]

    def test_resolve_dish_unknown_string_raises(self):
        with pytest.raises(ValueError):
            _resolve_dish_terms("nonexistent dish")

    def test_get_ingredients(self):
        ingredients = get_ingredients("chicken stir fry")
        assert len(ingredients) == 4
        assert ingredients[0] == "chicken breast"
        assert ingredients[1] == "stir fry vegetables"
        assert ingredients[2] == "soy sauce"
        assert ingredients[3] == "rice noodles"

    def test_build_quantity_map(self):
        dish = "roast lamb"
        qty_map = _build_quantity_map(dish)
        assert len(qty_map) == 5
        assert qty_map["lamb roast"] == "1.2 kg"
        assert qty_map["potato"] == "4 medium (~600 g)"
        assert qty_map["carrot"] == "3 medium (~180 g)"
        assert qty_map["broccoli"] == "1 head (~300 g)"
        assert qty_map["stock"] == "2 cups"

    def test_resolve_dish_data_from_registry(self):
        dish_dict: dict[str, Any] = cast(dict[str, Any], _resolve_dish_data("beef curry"))
        assert dish_dict["dish_name"] == "beef curry"
        assert dish_dict["portion"] == 4
        ingredients: list[dict[str, Any]] = dish_dict["ingredients"]
        assert len(ingredients) == 5
        assert ingredients[0]["search_term"] == "diced beef"


class TestDisplayNameParsing:
    """Tests for _parse_display_name using real displayName values from fixtures."""

    def test_parse_display_name_unit_with_number(self):
        qty, unit = _parse_display_name("1l")
        assert qty == 1
        assert unit == "l"

        qty, unit = _parse_display_name("2l")
        assert qty == 2
        assert unit == "l"

        qty, unit = _parse_display_name("3l")
        assert qty == 3
        assert unit == "l"

    def test_parse_display_name_unit_only(self):
        qty, unit = _parse_display_name("ea")
        assert qty == 1
        assert unit == "ea"

        qty, unit = _parse_display_name("kg")
        assert qty == 1
        assert unit == "kg"

    def test_parse_display_name_empty(self):
        assert _parse_display_name("") == (None, "")
        assert _parse_display_name(None) == (None, "")


class TestOptimizerUtilsNewWorld:
    """Tests for foodstuffs parsers and row builders using live fixture JSON data."""

    edge_data: dict
    edge_pass1: dict
    mobile_data: dict

    def setup_method(self):
        self.edge_data = _load_json("edge_search_pass2_example.json")
        self.edge_pass1 = _load_json("edge_search_pass1_example.json")
        self.mobile_data = _load_json("mobile_search_example.json")

    def test_parse_foodstuffs_volume_size(self):
        """Parse volume size from an Edge API product fixture (Standard Milk 1L).

        Uses edge_search_pass2_example.json products[0] — displayName="1l",
        singlePrice.price=317 (cents), comparativePrice.pricePerUnit=317,
        comparativePrice.measureDescription="1L".
        """
        product = self.edge_data["products"][0]
        qty, unit, per_unit_qty, per_unit_price = parse_foodstuffs_volume_size(
            product["displayName"],
            product["singlePrice"],
            product.get("promotions") or [],
        )
        assert qty == 1
        assert unit == "l"
        assert per_unit_qty == "1L"
        assert per_unit_price == 3.17

    def test_parse_foodstuffs_volume_size_3l(self):
        """Parse volume size from edge_search_pass2_example.json products[8] (3l milk).

        displayName="3l", price=720 cents, comparativePrice.pricePerUnit=240,
        measureDescription="1L".
        """
        product = self.edge_data["products"][8]
        qty, unit, per_unit_qty, per_unit_price = parse_foodstuffs_volume_size(
            product["displayName"],
            product["singlePrice"],
            product.get("promotions") or [],
        )
        assert qty == 3
        assert unit == "l"
        assert per_unit_qty == "1L"
        assert per_unit_price == 2.40

    def test_parse_foodstuffs_mobile_unit(self):
        """Parse units and unit price from a Mobile API product fixture (2L milk).

        Uses mobile_search_example.json products[0] — units="2l", unitPrice="$2.42/1L",
        price=483 cents.
        """
        product = self.mobile_data["products"][0]
        qty, unit, per_unit_qty, per_unit_price = parse_foodstuffs_mobile_unit(
            product["units"], product["unitPrice"], product["price"]
        )
        assert qty == 2
        assert unit == "l"
        assert per_unit_qty == "1L"
        assert per_unit_price == 2.42

    def test_parse_foodstuffs_mobile_unit_300ml(self):
        """Parse units from a Mobile API product with non-trivial volume (300ml).

        Finds a product with units containing '300ml' from mobile_search_example.json.
        Verifies qty=300, unit="ml".
        """
        product = None
        for p in self.mobile_data["products"]:
            if "300ml" in (p.get("units") or ""):
                product = p
                break
        assert product is not None
        qty, unit, per_unit_qty, per_unit_price = parse_foodstuffs_mobile_unit(
            product["units"], product.get("unitPrice", ""), product["price"]
        )
        assert qty == 300
        assert unit == "ml"

    def test_build_edge_row(self):
        """Build a standardized CSV row dict from an Edge API product and verify all fields.

        Uses edge_search_pass2_example.json products[0] (Standard Milk, 317 cents/1L).
        Store metadata (name, store_id) comes from edge_store_list_example.json first store
        (New World Papakura, id=ef977d89-f3d8-4e8b-8a48-b895ded38646).
        pass1 hit provides category0=["Fridge, Deli & Eggs"] and category1=["Milk"].
        """
        now = datetime(2026, 8, 10, 12, 0, 0)

        stores_fixture = _load_json("edge_store_list_example.json")
        store = stores_fixture["stores"][0]
        store_name = store["name"]
        store_id = store["id"]

        product = self.edge_data["products"][0]
        pass1_hit = {
            "category0": [product["categoryTrees"][0]["level0"]] if product.get("categoryTrees") else ["Fridge, Deli & Eggs"],
            "category1": [product["categoryTrees"][0]["level1"]] if product.get("categoryTrees") else ["Milk"],
        }

        row = build_edge_row("NewWorld", store_name, store_id, "milk", product, pass1_hit, now)

        for col in ROW_COLUMNS:
            assert col in row

        assert row["company"] == "NewWorld"
        assert row["store"] == store_name
        assert row["store_id"] == store_id
        assert row["search_ingredient"] == "milk"
        assert row["returned_ingredient"] == "Standard Milk"
        assert row["price"] == 3.17
        assert row["quantity"] == 1
        assert row["measurement_unit"] == "l"
        assert row["per_unit_quantity"] == "1L"
        assert row["per_unit_price"] == 3.17
        assert row["is_sale"] is False
        assert row["sku"] == "5201800-EA-000"
        assert row["department"] == "Fridge, Deli & Eggs"
        assert row["sub_department"] == "Milk"
        assert row["date_created"] == "2026-08-10"

        expected_hash = _compute_pk_hash(store_id, product["productId"], "2026-08-10")
        assert row["pk_hash"] == expected_hash

    def test_build_edge_row_from_pass1_hit_categories(self):
        """Build an edge row using categories lifted directly from a Pass 1 hit fixture.

        Uses edge_search_pass1_example.json hits[0] to supply category0/category1.
        Verifies department and sub_department columns populated from real Pass 1 categories.
        """
        now = datetime(2026, 8, 10, 12, 0, 0)
        stores_fixture = _load_json("edge_store_list_example.json")
        store = stores_fixture["stores"][0]
        store_name = store["name"]
        store_id = store["id"]

        h0 = self.edge_pass1["hits"][0]
        pass1_hit = {
            "category0": h0.get("category0", []),
            "category1": h0.get("category1", []),
        }

        product = self.edge_data["products"][0]
        row = build_edge_row("NewWorld", store_name, store_id, "milk", product, pass1_hit, now)

        assert row["department"] == "Fridge, Deli & Eggs"
        assert row["sub_department"] == "Milk"

    def test_build_mobile_row(self):
        """Build a standardized CSV row dict from a Mobile API product and verify all fields.

        Uses mobile_search_example.json products[0] (Standard Milk, 483 cents/2L).
        Store metadata comes from edge_store_list_example.json first store.
        """
        now = datetime(2026, 8, 10, 12, 0, 0)

        stores_fixture = _load_json("edge_store_list_example.json")
        store = stores_fixture["stores"][0]
        store_name = store["name"]
        store_id = store["id"]

        product = self.mobile_data["products"][0]
        row = build_mobile_row("NewWorld", store_name, store_id, "milk", product, now)

        for col in ROW_COLUMNS:
            assert col in row

        assert row["company"] == "NewWorld"
        assert row["store"] == store_name
        assert row["store_id"] == store_id
        assert row["search_ingredient"] == "milk"
        assert row["returned_ingredient"] == "Standard Milk"
        assert row["price"] == 4.83
        assert row["quantity"] == 2
        assert row["measurement_unit"] == "l"
        assert row["per_unit_quantity"] == "1L"
        assert row["per_unit_price"] == 2.42
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
        store_id = self.stores_fixture["stores"][0]["id"]
        sku = "5201800-EA-000"  # from edge_search_pass2_example.json products[0]
        date_str = "2026-08-10"

        hash1 = _compute_pk_hash(store_id, sku, date_str)
        hash2 = _compute_pk_hash(store_id, sku, date_str)

        assert hash1 == hash2
        assert len(hash1) == 16
        assert all(c in "0123456789abcdef" for c in hash1)

        raw = f"{store_id}|{sku}|{date_str}"
        expected = hashlib.sha256(raw.encode()).hexdigest()[:16]
        assert hash1 == expected

    def test_compute_pk_hash_different_inputs(self):
        hash1 = _compute_pk_hash("store-A", "sku-1", "2026-08-10")
        hash2 = _compute_pk_hash("store-B", "sku-1", "2026-08-10")
        hash3 = _compute_pk_hash("store-A", "sku-2", "2026-08-10")

        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3

    def test_append_rows_dedup_and_new(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
            csv_path = Path(f.name)

        try:
            store = self.stores_fixture["stores"][0]
            now = datetime(2026, 8, 10, 12, 0, 0)

            product1 = self.edge_data["products"][0]
            pass1_hit1 = {
                "category0": [product1["categoryTrees"][0]["level0"]],
                "category1": [product1["categoryTrees"][0]["level1"]],
            }
            row1 = build_edge_row(
                "NewWorld", store["name"], store["id"], "milk", product1, pass1_hit1, now,
            )

            product2 = self.edge_data["products"][1]
            pass1_hit2 = {
                "category0": [product2["categoryTrees"][0]["level0"]],
                "category1": [product2["categoryTrees"][0]["level1"]],
            }
            row2 = build_edge_row(
                "NewWorld", store["name"], store["id"], "milk", product2, pass1_hit2, now,
            )

            # Row 3: duplicate of row1 (same store_id + sku + date)
            row3 = build_edge_row(
                "NewWorld", store["name"], store["id"], "milk", product1, pass1_hit1, now,
            )

            appended, skipped = append_rows([row1, row2], csv_path)
            assert appended == 2
            assert skipped == 0

            appended2, skipped2 = append_rows([row1, row2, row3], csv_path)
            assert appended2 == 0
            assert skipped2 == 3

            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 2
            assert rows[0]["sku"] == product1["productId"]
            assert rows[1]["sku"] == product2["productId"]
        finally:
            csv_path.unlink(missing_ok=True)

    def test_load_existing_hashes(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
            csv_path = Path(f.name)

        try:
            store_id = self.stores_fixture["stores"][0]["id"]
            now = datetime(2026, 8, 10, 12, 0, 0)

            product1 = self.edge_data["products"][0]
            pass1_hit1 = {
                "category0": [product1["categoryTrees"][0]["level0"]],
                "category1": [product1["categoryTrees"][0]["level1"]],
            }
            row1 = build_edge_row("NewWorld", "Test Store", store_id, "milk", product1, pass1_hit1, now)
            product2 = self.edge_data["products"][1]
            pass1_hit2 = {
                "category0": [product2["categoryTrees"][0]["level0"]],
                "category1": [product2["categoryTrees"][0]["level1"]],
            }
            row2 = build_edge_row("NewWorld", "Test Store", store_id, "milk", product2, pass1_hit2, now)

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


class TestNewWorldSpecific:
    """Tests for New World-specific behaviour (banner, endpoints, categories)."""

    def test_non_food_categories_excludes_milk(self):
        assert "Milk" not in NON_FOOD_CATEGORIES

    def test_edge_search_returns_40_hits(self):
        """All 40 Pass 1 hits belong to food categories in the real fixture."""
        pass1 = _load_json("edge_search_pass1_example.json")
        for h in pass1["hits"]:
            cat1 = h.get("category1", [])
            assert not any(c in NON_FOOD_CATEGORIES for c in cat1)

    def test_mobile_search_products_are_food(self):
        """All 20 Mobile search products belong to food categories."""
        mobile_search = _load_json("mobile_search_example.json")
        for p in mobile_search["products"]:
            cats = p.get("categories", []) or []
            cat1 = cats[0] if cats else ""
            assert cat1 not in NON_FOOD_CATEGORIES or not cat1

    def test_haversine_within_new_zealand(self):
        """Haversine between two NZ cities returns a sensible distance (~600 km Auckland-Wellington)."""
        # Auckland ≈ -36.8485, 174.7635; Wellington ≈ -41.2865, 174.7762
        dist = haversine(-36.8485, 174.7635, -41.2865, 174.7762)
        assert 400 < dist < 800

    def test_find_nearby_stores_returns_empty_when_no_csv(self):
        """find_nearby_stores returns empty list when stores CSV is missing."""
        from unittest.mock import patch
        with patch.object(newworld_api, "STORES_CSV", Path("/nonexistent/path.csv")):
            result = find_nearby_stores(-36.8, 174.7, radius_km=5)
            assert result == []

    def test_load_stores_handles_missing_csv(self):
        """load_stores returns empty list when stores CSV does not exist."""
        original = newworld_api.STORES_CSV
        newworld_api.STORES_CSV = Path("/nonexistent/path.csv")
        try:
            result = load_stores()
            assert result == []
        finally:
            newworld_api.STORES_CSV = original


class TestOptimizerIntegration:
    """Integration tests verifying the full flow from fixtures to CSV rows."""

    def test_edge_row_price_in_dollars(self):
        """Verify build_edge_row converts cents to dollars correctly for all 10 Pass 2 products."""
        edge_data = _load_json("edge_search_pass2_example.json")
        stores_fixture = _load_json("edge_store_list_example.json")
        store = stores_fixture["stores"][0]
        now = datetime(2026, 8, 10, 12, 0, 0)

        prices = []
        for prod in edge_data["products"]:
            pass1_hit = {
                "category0": [prod["categoryTrees"][0]["level0"]],
                "category1": [prod["categoryTrees"][0]["level1"]],
            }
            row = build_edge_row("NewWorld", store["name"], store["id"], "milk", prod, pass1_hit, now)
            price = row["price"]
            if price != "":
                prices.append(price)

        # All prices should be valid floats in dollars (cents/100)
        expected_cents = sorted([p["singlePrice"]["price"] for p in edge_data["products"]])
        expected_dollars = [round(c / 100.0, 2) for c in expected_cents]
        assert prices == expected_dollars

    def test_mobile_row_price_in_dollars(self):
        """Verify build_mobile_row converts cents to dollars correctly for all 20 Mobile products."""
        mobile_data = _load_json("mobile_search_example.json")
        stores_fixture = _load_json("edge_store_list_example.json")
        store = stores_fixture["stores"][0]
        now = datetime(2026, 8, 10, 12, 0, 0)

        prices = []
        for prod in mobile_data["products"]:
            row = build_mobile_row("NewWorld", store["name"], store["id"], "milk", prod, now)
            price = row["price"]
            if price != "":
                prices.append(price)

        # Verify prices match the raw cents converted to dollars
        raw_cents = [p["price"] for p in mobile_data["products"]]
        expected_dollars = [round(c / 100.0, 2) for c in raw_cents]
        assert prices == expected_dollars
