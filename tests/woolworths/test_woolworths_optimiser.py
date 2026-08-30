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
from datetime import datetime
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixture"

from NZMealOptimiser.pricing.optimiser_utils import (
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

        build_woolworths_row() produces 18 of the 19 CSV_COLUMNS keys. The
        'is_valid' column is intentionally omitted by build_woolworths_row()
        because it is managed separately by the validation pipeline
        (llm_validate.py) and the append_rows() function. It is added
        when the row is written to CSV via csv.DictWriter, which
        backfills missing columns as empty strings.
        """
        row = self._build_milk_row()
        expected = set(CSV_COLUMNS) - {"is_valid"}
        assert set(row.keys()) == expected

    @pytest.mark.parametrize("field,expected", [
        ("company", "Woolworths"),
        ("store", "Nelson Junction Woolworths"),
        ("store_id", "9290"),
        ("search_ingredient", "milk"),
        ("returned_ingredient", "anchor milk standard blue"),
    ])
    def test_identity_field_values(self, field, expected):
        """Identity fields echo the function inputs verbatim (or a
        normalised form, e.g. the brand "anchor" → "Anchor")."""
        assert self._build_milk_row()[field] == expected

    def test_brand_capitalised(self):
        """brand is capitalised: raw "anchor" → "Anchor" (matches Foodstuffs casing)."""
        assert self._build_milk_row()["brand"] == "Anchor"

    def test_brand_fallback_to_company_name(self):
        """brand falls back to 'Woolworths' when the product has no brand.

        Covers in-house items where the API omits the brand field entirely.
        """
        product = dict(self.milk_product)
        del product["brand"]
        row = build_woolworths_row(
            company="Woolworths",
            store="Nelson Junction Woolworths",
            store_id="9290",
            search_ingredient="milk",
            product=product,
            now=self.now,
        )
        assert row["brand"] == "Woolworths"

    @pytest.mark.parametrize("field,expected", [
        ("price", 9.07),
        ("quantity", 3),
        ("measurement_unit", "l"),
        ("per_unit_quantity", "1L"),
        ("per_unit_price", 3.02),
        ("is_sale", False),
        ("sku", "705692"),
        ("department", "Fridge & Deli"),
        ("sub_department", ""),
    ])
    def test_product_field_values(self, field, expected):
        """Product-derived fields: price, size, SKU, department."""
        assert self._build_milk_row()[field] == expected

    @pytest.mark.parametrize("field,expected", [
        ("date_created", "2024-08-09"),
        ("datetime_created", "2024-08-09 12:00:00"),
    ])
    def test_timestamp_fields(self, field, expected):
        """date_created and datetime_created derive from the 'now' kwarg."""
        assert self._build_milk_row()[field] == expected

    def test_pk_hash_correct(self):
        """pk_hash is SHA-256('{store_id}|{sku}|{date_created}')[:16].

        Now hashed over store_id=9290 (extra1/fulfilmentStoreId, the
        canonical id), not the legacy pickupAddressId 4166071.
        """
        row = self._build_milk_row()
        expected_hash = _compute_pk_hash("9290", "705692", "2024-08-09")
        assert row["pk_hash"] == expected_hash

    def test_pk_hash_is_deterministic(self):
        """Two builds with identical inputs must yield the same pk_hash."""
        row1 = self._build_milk_row()
        row2 = self._build_milk_row()
        assert row1["pk_hash"] == row2["pk_hash"]

    def test_sale_item_is_sale_true(self):
        """build_woolworths_row with a sale product must set is_sale=True."""
        assert self._build_sale_row()["is_sale"] is True

    def test_sale_item_price_matches_sale_price(self):
        """build_woolworths_row must use salePrice (not originalPrice) for the price field."""
        row = self._build_sale_row()
        assert row["price"] == self.sale_product["salePrice"]
        assert row["price"] < self.sale_product["originalPrice"]

    @pytest.mark.parametrize("product_overrides,assertions", [
        # All optional fields blank/empty
        ({"volumeSize": "", "cupMeasure": "", "cupListPrice": ""},
         {"returned_ingredient": "test product", "price": 2.50,
          "quantity": "", "measurement_unit": "", "per_unit_quantity": "",
          "per_unit_price": ""}),
        # sku is None
        ({"sku": None, "name": "no sku product"},
         {"returned_ingredient": "no sku product", "sku": None}),
        # salePrice is None
        ({"salePrice": None, "originalPrice": None, "name": "no price product"},
         {"returned_ingredient": "no price product", "price": None}),
    ])
    def test_missing_or_none_field_handling(self, product_overrides, assertions):
        """Products with missing/None optional fields must still produce
        a valid row. build_woolworths_row converts None to "" for string
        fields and passes None through for price/sku."""
        base_product = {
            "sku": "999999",
            "name": "test product",
            "salePrice": 2.50,
            "originalPrice": 3.00,
            "isSpecial": False,
            "unitPrice": "",
            "volumeSize": "1L",
            "cupMeasure": "1L",
            "cupListPrice": 1.00,
            "url": "",
            "imageUrl": "",
            "department": "Pantry",
        }
        base_product.update(product_overrides)
        row = build_woolworths_row(
            company="Woolworths",
            store="Test Store",
            store_id="9999999",
            search_ingredient="test",
            product=base_product,
            now=self.now,
        )
        for field, expected in assertions.items():
            assert row[field] == expected


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