"""
Unit tests for Woolworths NZ Meal Cost Optimizer (woolworths_optimizer.py).

Tests focus on the build_row() function, which transforms a raw product
search result into a CSV row dict that matches the full_results.csv schema.

    - build_row() is tested with the normalized milk product from
      fixture/product_normalized.json (captured from the live Woolworths API).
    - _compute_pk_hash() is tested with known inputs to verify the
      deterministic SHA-256 hash prefix.
    - parse_woolworths_volume_size() is tested with real volumeSize
      strings extracted from the captured fixture data.
"""

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

# Make the woolworths scripts directory and combined helpers importable.
SCRIPT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(SCRIPT_DIR))                         # scripts/woolworths
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "combined"))  # shared optimizer_utils

FIXTURE_DIR = SCRIPT_DIR / "fixture"

from optimizer_utils import (
    CSV_COLUMNS,
    parse_woolworths_volume_size,
    _compute_pk_hash,
)
from woolworths_optimizer import build_row


def _load_json(filename):
    """Load a JSON fixture file from the fixture directory."""
    with open(FIXTURE_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


class TestBuildRow(unittest.TestCase):
    """Tests for build_row() using the real milk product from fixture data.

    The fixture (product_normalized.json) was captured from the live
    Woolworths NZ API at Nelson Junction Woolworths (extra1=9290).
    The product is "anchor milk standard blue" with salePrice=3.76.
    """

    def setUp(self):
        """Load the normalized milk product from the fixture."""
        # This product dict represents the OUTPUT of search_products(),
        # i.e. the normalized structure that build_row() consumes.
        self.milk_product = _load_json("product_normalized.json")
        self.now = datetime(2024, 8, 9, 12, 0, 0)

    def _build_test_row(self):
        """Helper: build a CSV row for the milk product in the fixture."""
        return build_row(
            company="Woolworths",
            store="Nelson Junction Woolworths",
            store_id="4166071",
            search_ingredient="milk",
            product=self.milk_product,
            now=self.now,
        )

    def test_row_matches_csv_columns(self):
        """The row dict must contain all CSV_COLUMNS except 'is_valid'.

        build_row() produces 17 of the 18 CSV_COLUMNS keys. The
        'is_valid' column is intentionally omitted by build_row()
        because it is managed separately by the validation pipeline
        (llm_validate.py) and the append_rows() function. It is added
        when the row is written to CSV via csv.DictWriter, which
        backfills missing columns as empty strings.
        """
        row = self._build_test_row()
        expected = set(CSV_COLUMNS) - {"is_valid"}
        self.assertEqual(set(row.keys()), expected)

    def test_company_value(self):
        """The 'company' field must be 'Woolworths'."""
        self.assertEqual(self._build_test_row()["company"], "Woolworths")

    def test_store_and_store_id_values(self):
        """store and store_id must match the inputs passed to build_row()."""
        row = self._build_test_row()
        self.assertEqual(row["store"], "Nelson Junction Woolworths")
        self.assertEqual(row["store_id"], "4166071")

    def test_search_ingredient_value(self):
        """search_ingredient must be 'milk' (the term we searched for)."""
        self.assertEqual(self._build_test_row()["search_ingredient"], "milk")

    def test_returned_ingredient_value(self):
        """returned_ingredient must be the product name from the fixture."""
        row = self._build_test_row()
        self.assertEqual(row["returned_ingredient"], "anchor milk standard blue")

    def test_price_value(self):
        """price must match salePrice from the fixture (3.76)."""
        row = self._build_test_row()
        self.assertEqual(row["price"], 3.76)

    def test_quantity_value(self):
        """quantity must be parsed from volumeSize '1L' -> 1.

        Note: parse_woolworths_volume_size lowercases the unit, so
        '1L' returns quantity 1 (as int) and measurement_unit 'l'.
        """
        row = self._build_test_row()
        self.assertEqual(row["quantity"], 1)

    def test_measurement_unit_value(self):
        """measurement_unit must be 'l' (from volumeSize '1L', lowercased).

        parse_woolworths_volume_size lowercases units, so '1L' -> 'l'.
        """
        row = self._build_test_row()
        self.assertEqual(row["measurement_unit"], "l")

    def test_per_unit_quantity_value(self):
        """per_unit_quantity must be cupMeasure '1L' from the fixture."""
        row = self._build_test_row()
        self.assertEqual(row["per_unit_quantity"], "1L")

    def test_per_unit_price_value(self):
        """per_unit_price must be cupListPrice from the fixture (3.76)."""
        row = self._build_test_row()
        self.assertEqual(row["per_unit_price"], 3.76)

    def test_is_sale_value(self):
        """is_sale must reflect isSpecial=False from the fixture."""
        row = self._build_test_row()
        self.assertFalse(row["is_sale"])

    def test_sku_value(self):
        """sku must match the fixture value '282848'."""
        row = self._build_test_row()
        self.assertEqual(row["sku"], "282848")

    def test_department_value(self):
        """department must be 'Fridge & Deli' from the fixture."""
        row = self._build_test_row()
        self.assertEqual(row["department"], "Fridge & Deli")

    def test_sub_department_is_empty(self):
        """sub_department must be an empty string (Woolworths doesn't set it)."""
        row = self._build_test_row()
        self.assertEqual(row["sub_department"], "")

    def test_date_created_value(self):
        """date_created must be YYYY-MM-DD derived from the 'now' timestamp."""
        row = self._build_test_row()
        self.assertEqual(row["date_created"], "2024-08-09")

    def test_datetime_created_value(self):
        """datetime_created must be YYYY-MM-DD HH:MM:SS from 'now'."""
        row = self._build_test_row()
        self.assertEqual(row["datetime_created"], "2024-08-09 12:00:00")

    def test_pk_hash_correct(self):
        """pk_hash must be the hash of store_id|sku|date_created."""
        row = self._build_test_row()
        expected_hash = _compute_pk_hash("4166071", "282848", "2024-08-09")
        self.assertEqual(row["pk_hash"], expected_hash)

    def test_quantity_500ml_from_fixture(self):
        """A volumeSize like '500mL' (from primo milk in the fixture) must parse correctly.

        The captured response contains items with volumeSize='500mL'.
        This tests that parse_woolworths_volume_size handles uppercase 'mL'.
        """
        qty, unit = parse_woolworths_volume_size("500mL", "")
        self.assertEqual((qty, unit), (500, "ml"))

    def test_quantity_3L_from_fixture(self):
        """A volumeSize like '3L' (from woolworths milk standard in the fixture)
        must parse to (3, 'l')."""
        qty, unit = parse_woolworths_volume_size("3L", "")
        self.assertEqual((qty, unit), (3, "l"))


class TestParseWoolworthsVolumeSize(unittest.TestCase):
    """Tests for the shared parse_woolworths_volume_size() helper.

    Uses real volumeSize strings extracted from the captured product search
    response (fixture/response_example1.json).

    NOTE: per the implementation in optimizer_utils.py, the returned unit
    is always lowercased. The regex patterns require a digit prefix —
    bare units like 'ea' without a number fall through to the cup_measure
    fallback or return (None, "").
    """

    def test_number_adjacent_unit_lowercased(self):
        """'500g' should parse to (500, 'g') — unit lowercased."""
        qty, unit = parse_woolworths_volume_size("500g", "")
        self.assertEqual((qty, unit), (500, "g"))

    def test_number_adjacent_unit_uppercase_lowercased(self):
        """'2L' should parse to (2, 'l') — unit lowercased from 'L'."""
        qty, unit = parse_woolworths_volume_size("2L", "")
        self.assertEqual((qty, unit), (2, "l"))

    def test_number_space_unit(self):
        """'2 pack' should parse to (2, 'pack')."""
        qty, unit = parse_woolworths_volume_size("2 pack", "")
        self.assertEqual((qty, unit), (2, "pack"))

    def test_decimal_quantity(self):
        """'1.5kg' should parse to (1.5, 'kg')."""
        qty, unit = parse_woolworths_volume_size("1.5kg", "")
        self.assertEqual((qty, unit), (1.5, "kg"))

    def test_fallback_to_cup_measure(self):
        """When volumeSize lacks a number, fall back to cup_measure.

        From the docstring example: ('for frying', '500ml') -> (500, 'ml').
        """
        qty, unit = parse_woolworths_volume_size("for frying", "500ml")
        self.assertEqual((qty, unit), (500, "ml"))

    def test_both_empty_returns_none(self):
        """When both fields are empty, return (None, '')."""
        qty, unit = parse_woolworths_volume_size("", "")
        self.assertEqual((qty, unit), (None, ""))

    def test_null_volume_size_falls_back(self):
        """A 'null' (string) volumeSize should trigger the cup_measure fallback.

        From the docstring example: ('null', '1kg') -> (1, 'kg').
        """
        qty, unit = parse_woolworths_volume_size("null", "1kg")
        self.assertEqual((qty, unit), (1, "kg"))

    def test_empty_volume_size_falls_back(self):
        """An empty volumeSize should trigger the cup_measure fallback."""
        qty, unit = parse_woolworths_volume_size("", "1L")
        self.assertEqual((qty, unit), (1, "l"))

    def test_bare_unit_no_cup_measure_falls_through(self):
        """A bare unit 'ea' with no cup_measure returns (None, '').

        The function has no Pattern 3 for bare units — they only parse
        if a cup_measure fallback is provided AND that fallback has a digit.
        """
        qty, unit = parse_woolworths_volume_size("ea", "")
        self.assertEqual((qty, unit), (None, ""))


class TestComputePkHash(unittest.TestCase):
    """Tests for _compute_pk_hash() deterministic output.

    The hash is the first 16 hex chars of SHA-256('{store_id}|{sku}|{date_created}').
    All expected values below were computed from the captured fixture data.
    """

    def test_known_hash_value(self):
        """Verify the hash for store_id=4166071, sku=282848, date=2024-08-09.

        This corresponds to the Nelson Junction Woolworths milk product
        in product_normalized.json. The expected value was computed
        independently using hashlib.sha256.
        """
        result = _compute_pk_hash("4166071", "282848", "2024-08-09")
        self.assertEqual(len(result), 16)
        # Independently verified hash for this input
        import hashlib
        raw = "4166071|282848|2024-08-09"
        expected = hashlib.sha256(raw.encode()).hexdigest()[:16]
        self.assertEqual(result, expected)

    def test_hash_changes_with_sku(self):
        """Different SKUs must produce different hashes."""
        h1 = _compute_pk_hash("4166071", "282848", "2024-08-09")
        h2 = _compute_pk_hash("4166071", "282849", "2024-08-09")
        self.assertNotEqual(h1, h2)

    def test_hash_changes_with_store(self):
        """Different store IDs must produce different hashes."""
        h1 = _compute_pk_hash("4166071", "282848", "2024-08-09")
        h2 = _compute_pk_hash("1225552", "282848", "2024-08-09")
        self.assertNotEqual(h1, h2)

    def test_hash_changes_with_date(self):
        """Different date_created values must produce different hashes."""
        h1 = _compute_pk_hash("4166071", "282848", "2024-08-09")
        h2 = _compute_pk_hash("4166071", "282848", "2024-08-10")
        self.assertNotEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
