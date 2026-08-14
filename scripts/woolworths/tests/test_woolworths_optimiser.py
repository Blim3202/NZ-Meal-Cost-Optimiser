"""
Unit tests for the shared Woolworths CSV row builder
(optimiser_utils.build_woolworths_row).

Tests focus on build_woolworths_row(), which transforms a raw product
search result into a CSV row dict that matches the full_results.csv schema.

    - build_woolworths_row() is tested with the normalized milk product from
      fixture/product_normalized.json (captured from the live Woolworths API).
    - build_woolworths_row() is tested with a sale item from
      fixture/product_normalized_sale.json (real or synthetic sale product).
    - _compute_pk_hash() is tested with known inputs to verify the
      deterministic SHA-256 hash prefix.
    - parse_woolworths_volume_size() is tested with real volumeSize
      strings extracted from the captured fixture data.
"""

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # project root

sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "combined"))  # shared optimiser_utils

FIXTURE_DIR = PROJECT_ROOT / "scripts" / "woolworths" / "fixture"

from optimiser_utils import (
    CSV_COLUMNS,
    build_woolworths_row,
    parse_woolworths_volume_size,
    _compute_pk_hash,
)


def _load_json(filename):
    """Load a JSON fixture file from the fixture directory."""
    with open(FIXTURE_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


class TestBuildRow:
    """Tests for build_woolworths_row() using real fixture data.

    The fixture (product_normalized.json) was captured from the live
    Woolworths NZ API at Nelson Junction Woolworths (extra1=9290;
    canonical store_id keyed directly on extra1/fulfilmentStoreId).
    The product is "anchor milk standard blue" with salePrice=9.07,
    volumeSize="3L", cupMeasure="1L", cupListPrice=3.02.
    """

    def setup_method(self):
        """Load the normalized product fixtures."""
        self.milk_product = _load_json("product_normalized.json")
        self.sale_product = _load_json("product_normalized_sale.json")
        self.now = datetime(2024, 8, 9, 12, 0, 0)

    def _build_milk_row(self):
        """Helper: build a CSV row for the milk product in the fixture.

        Uses store_id=9290 (extra1/fulfilmentStoreId, the canonical id).
        """
        return build_woolworths_row(
            company="Woolworths",
            store="Nelson Junction Woolworths",
            store_id="9290",
            search_ingredient="milk",
            product=self.milk_product,
            now=self.now,
        )

    def _build_sale_row(self):
        """Helper: build a CSV row for the sale product in the fixture.

        Uses store_id=9290 (extra1/fulfilmentStoreId, the canonical id).
        """
        return build_woolworths_row(
            company="Woolworths",
            store="Nelson Junction Woolworths",
            store_id="9290",
            search_ingredient="milk",
            product=self.sale_product,
            now=self.now,
        )

    def test_row_matches_csv_columns(self):
        """The row dict must contain all CSV_COLUMNS except 'is_valid'.

        build_woolworths_row() produces 17 of the 18 CSV_COLUMNS keys. The
        'is_valid' column is intentionally omitted by build_woolworths_row()
        because it is managed separately by the validation pipeline
        (llm_validate.py) and the append_rows() function. It is added
        when the row is written to CSV via csv.DictWriter, which
        backfills missing columns as empty strings.
        """
        row = self._build_milk_row()
        expected = set(CSV_COLUMNS) - {"is_valid"}
        assert set(row.keys()) == expected

    def test_company_value(self):
        """The 'company' field must be 'Woolworths'."""
        assert self._build_milk_row()["company"] == "Woolworths"

    def test_store_and_store_id_values(self):
        """store and store_id must match the inputs passed to build_woolworths_row()."""
        row = self._build_milk_row()
        assert row["store"] == "Nelson Junction Woolworths"
        assert row["store_id"] == "9290"

    def test_search_ingredient_value(self):
        """search_ingredient must be 'milk' (the term we searched for)."""
        assert self._build_milk_row()["search_ingredient"] == "milk"

    def test_returned_ingredient_value(self):
        """returned_ingredient must be the product name from the fixture."""
        row = self._build_milk_row()
        assert row["returned_ingredient"] == "anchor milk standard blue"

    def test_price_value(self):
        """price must match salePrice from the fixture (9.07)."""
        assert self._build_milk_row()["price"] == 9.07

    def test_quantity_value(self):
        """quantity must be parsed from volumeSize '3L' -> 3.

        Note: parse_woolworths_volume_size lowercases the unit, so
        '3L' returns quantity 3 (as int) and measurement_unit 'l'.
        """
        assert self._build_milk_row()["quantity"] == 3

    def test_measurement_unit_value(self):
        """measurement_unit must be 'l' (from volumeSize '3L', lowercased)."""
        assert self._build_milk_row()["measurement_unit"] == "l"

    def test_per_unit_quantity_value(self):
        """per_unit_quantity must be cupMeasure '1L' from the fixture."""
        assert self._build_milk_row()["per_unit_quantity"] == "1L"

    def test_per_unit_price_value(self):
        """per_unit_price must be cupListPrice from the fixture (3.02)."""
        assert self._build_milk_row()["per_unit_price"] == 3.02

    def test_is_sale_value(self):
        """is_sale must reflect isSpecial=False from the fixture."""
        assert self._build_milk_row()["is_sale"] is False

    def test_sku_value(self):
        """sku must match the fixture value '705692'."""
        assert self._build_milk_row()["sku"] == "705692"

    def test_department_value(self):
        """department must be 'Fridge & Deli' from the fixture."""
        assert self._build_milk_row()["department"] == "Fridge & Deli"

    def test_sub_department_is_empty(self):
        """sub_department must be an empty string (Woolworths doesn't set it)."""
        assert self._build_milk_row()["sub_department"] == ""

    def test_date_created_value(self):
        """date_created must be YYYY-MM-DD derived from the 'now' timestamp."""
        assert self._build_milk_row()["date_created"] == "2024-08-09"

    def test_datetime_created_value(self):
        """datetime_created must be YYYY-MM-DD HH:MM:SS from 'now'."""
        assert self._build_milk_row()["datetime_created"] == "2024-08-09 12:00:00"

    def test_pk_hash_correct(self):
        """pk_hash must be the hash of store_id|sku|date_created.

        Now hashed over store_id=9290 (extra1/fulfilmentStoreId, the
        canonical id), not the legacy pickupAddressId 4166071.
        """
        row = self._build_milk_row()
        expected_hash = _compute_pk_hash("9290", "705692", "2024-08-09")
        assert row["pk_hash"] == expected_hash

    def test_sale_item_is_sale_true(self):
        """build_woolworths_row with a sale product must set is_sale=True."""
        row = self._build_sale_row()
        assert row["is_sale"] is True

    def test_sale_item_price_matches_sale_price(self):
        """build_woolworths_row must use salePrice (not originalPrice) for the price field."""
        row = self._build_sale_row()
        assert row["price"] == self.sale_product["salePrice"]
        assert row["price"] < self.sale_product["originalPrice"]

    def test_sale_item_returned_ingredient(self):
        """The sale item's product name must be correctly set."""
        row = self._build_sale_row()
        assert row["returned_ingredient"] == self.sale_product["name"]

    def test_sale_item_sku(self):
        """The sale item's SKU must be correctly set."""
        row = self._build_sale_row()
        assert row["sku"] == self.sale_product["sku"]

    def test_sale_item_per_unit_price(self):
        """The sale item's per_unit_price must be correctly set."""
        row = self._build_sale_row()
        assert row["per_unit_price"] == self.sale_product["cupListPrice"]

    def test_missing_optional_fields_handled(self):
        """build_woolworths_row must handle products with missing optional fields.

        If cupMeasure, cupListPrice, volumeSize are missing/None, build_woolworths_row
        should still produce a valid row without crashing.
        """
        product = {
            "sku": "999999",
            "name": "test product",
            "salePrice": 2.50,
            "originalPrice": 3.00,
            "isSpecial": False,
            "unitPrice": "",
            "volumeSize": "",
            "cupMeasure": "",
            "cupListPrice": "",
            "url": "",
            "imageUrl": "",
            "department": "",
        }
        row = build_woolworths_row(
            company="Woolworths",
            store="Test Store",
            store_id="9999999",
            search_ingredient="test",
            product=product,
            now=self.now,
        )
        assert row["returned_ingredient"] == "test product"
        assert row["price"] == 2.50
        assert row["quantity"] == ""  # build_woolworths_row converts None to ""
        assert row["measurement_unit"] == ""
        assert row["per_unit_quantity"] == ""
        assert row["per_unit_price"] == ""

    def test_none_sku_handled(self):
        """build_woolworths_row must handle products with sku=None."""
        product = {
            "sku": None,
            "name": "no sku product",
            "salePrice": 1.00,
            "originalPrice": 1.00,
            "isSpecial": False,
            "unitPrice": 1.00,
            "volumeSize": "1L",
            "cupMeasure": "1L",
            "cupListPrice": 1.00,
            "url": "",
            "imageUrl": "",
            "department": "Pantry",
        }
        row = build_woolworths_row(
            company="Woolworths",
            store="Test Store",
            store_id="9999999",
            search_ingredient="test",
            product=product,
            now=self.now,
        )
        assert row["returned_ingredient"] == "no sku product"
        assert row["sku"] is None

    def test_none_sale_price_handled(self):
        """build_woolworths_row must handle products with salePrice=None."""
        product = {
            "sku": "888888",
            "name": "no price product",
            "salePrice": None,
            "originalPrice": None,
            "isSpecial": False,
            "unitPrice": "",
            "volumeSize": "1L",
            "cupMeasure": "1L",
            "cupListPrice": "",
            "url": "",
            "imageUrl": "",
            "department": "Pantry",
        }
        row = build_woolworths_row(
            company="Woolworths",
            store="Test Store",
            store_id="9999999",
            search_ingredient="test",
            product=product,
            now=self.now,
        )
        assert row["returned_ingredient"] == "no price product"
        assert row["price"] is None

    def test_pk_hash_consistency_between_calls(self):
        """build_woolworths_row should produce the same pk_hash for identical inputs."""
        row1 = self._build_milk_row()
        row2 = self._build_milk_row()
        assert row1["pk_hash"] == row2["pk_hash"]


class TestParseWoolworthsVolumeSize:
    """Tests for the shared parse_woolworths_volume_size() helper.

    Uses real volumeSize strings extracted from the captured product search
    response (fixture/response_example1.json) and from full_results.csv.

    NOTE: per the implementation in optimiser_utils.py, the returned unit
    is always lowercased. The regex patterns require a digit prefix —
    bare units like 'ea' without a number fall through to the cup_measure
    fallback or return (None, "").
    """

    @pytest.mark.parametrize("input_str,cup_measure,expected", [
        # Real volumeSize values from response_example1.json
        ("1L", "", (1, "l")),
        ("2L", "", (2, "l")),
        ("3L", "", (3, "l")),
        ("", "", (None, "")),
        # Real volumeSize values from full_results.csv
        ("100g", "", (100, "g")),
        ("10g", "", (10, "g")),
        ("1kg", "", (1, "kg")),
        ("1ea", "", (1, "ea")),
        ("500g", "", (500, "g")),
        ("500mL", "", (500, "ml")),
        # Decimal quantities
        ("1.5kg", "", (1.5, "kg")),
        # Number followed by unit with space
        ("2 pack", "", (2, "pack")),
        ("6 pack", "", (6, "pack")),
    ])
    def test_parse_various_volume_sizes(self, input_str, cup_measure, expected):
        """Test parsing of real volumeSize strings from the fixture data."""
        qty, unit = parse_woolworths_volume_size(input_str, cup_measure)
        assert (qty, unit) == expected

    def test_fallback_to_cup_measure(self):
        """When volumeSize lacks a number, fall back to cup_measure.

        From the docstring example: ('for frying', '500ml') -> (500, 'ml').
        """
        qty, unit = parse_woolworths_volume_size("for frying", "500ml")
        assert (qty, unit) == (500, "ml")

    def test_null_volume_size_falls_back(self):
        """A 'null' (string) volumeSize should trigger the cup_measure fallback.

        From the docstring example: ('null', '1kg') -> (1, 'kg').
        """
        qty, unit = parse_woolworths_volume_size("null", "1kg")
        assert (qty, unit) == (1, "kg")

    def test_empty_volume_size_falls_back(self):
        """An empty volumeSize should trigger the cup_measure fallback."""
        qty, unit = parse_woolworths_volume_size("", "1L")
        assert (qty, unit) == (1, "l")

    def test_bare_unit_no_cup_measure_falls_through(self):
        """A bare unit 'ea' with no cup_measure returns (None, '').

        The function has no Pattern 3 for bare units — they only parse
        if a cup_measure fallback is provided AND that fallback has a digit.
        """
        qty, unit = parse_woolworths_volume_size("ea", "")
        assert (qty, unit) == (None, "")


class TestComputePkHash:
    """Tests for _compute_pk_hash() deterministic output.

    The hash is the first 16 hex chars of SHA-256('{store_id}|{sku}|{date_created}').
    All expected values below were computed from the captured fixture data.
    """

    def test_known_hash_value(self):
        """Verify the hash for store_id=9290, sku=282768, date=2024-08-09.

        Uses store_id=9290 (extra1/fulfilmentStoreId, the canonical id).
        This corresponds to the Nelson Junction Woolworths milk product
        in product_normalized.json. The expected value was computed
        independently using hashlib.sha256.
        """
        result = _compute_pk_hash("9290", "282768", "2024-08-09")
        assert len(result) == 16
        # Independently verified hash for this input
        raw = "9290|282768|2024-08-09"
        expected = hashlib.sha256(raw.encode()).hexdigest()[:16]
        assert result == expected

    def test_hash_changes_with_sku(self):
        """Different SKUs must produce different hashes."""
        h1 = _compute_pk_hash("9290", "282768", "2024-08-09")
        h2 = _compute_pk_hash("9290", "282769", "2024-08-09")
        assert h1 != h2

    def test_hash_changes_with_store(self):
        """Different store IDs must produce different hashes."""
        h1 = _compute_pk_hash("9290", "282768", "2024-08-09")
        h2 = _compute_pk_hash("1225552", "282768", "2024-08-09")
        assert h1 != h2

    def test_hash_changes_with_date(self):
        """Different date_created values must produce different hashes."""
        h1 = _compute_pk_hash("9290", "282768", "2024-08-09")
        h2 = _compute_pk_hash("9290", "282768", "2024-08-10")
        assert h1 != h2