"""
Unit tests for foodstuffs parser utilities.

Tests parse_foodstuffs_volume_size (Edge API) and
parse_foodstuffs_mobile_unit (Mobile API) with a variety of
inputs covering Pak'nSave and New World product data patterns.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest

from optimiser_utils import (
    parse_foodstuffs_mobile_unit,
    parse_foodstuffs_volume_size,
)


class TestParseFoodstuffsMobileUnit(unittest.TestCase):
    """Tests for parse_foodstuffs_mobile_unit — the mobile API parser."""

    # --- unitPrice present, units has count + measure ---

    def test_sachet_count_x_measure(self):
        result = parse_foodstuffs_mobile_unit("3 x 31g", "$26.99/1kg")
        self.assertEqual(result, (3, "x 31g", "1kg", 26.99))

    def test_numeric_adjacent_unit_with_unit_price(self):
        result = parse_foodstuffs_mobile_unit("500g", "$18.99/kg")
        self.assertEqual(result, (500, "g", "kg", 18.99))

    def test_count_space_unit_with_unit_price(self):
        result = parse_foodstuffs_mobile_unit("2 pack", "$3.49/ea")
        self.assertEqual(result, (2, "pack", "ea", 3.49))

    def test_litre_adjacent_with_unit_price(self):
        result = parse_foodstuffs_mobile_unit("2L", "$2.50/L")
        self.assertEqual(result, (2, "l", "L", 2.50))

    # --- unitPrice present, units is bare unit ---

    def test_bare_ea_with_unit_price(self):
        result = parse_foodstuffs_mobile_unit("ea", "$1.99/ea")
        self.assertEqual(result, (1, "ea", "ea", 1.99))

    def test_bare_kg_with_unit_price(self):
        result = parse_foodstuffs_mobile_unit("kg", "$2.50/kg")
        self.assertEqual(result, (1, "kg", "kg", 2.50))

    # --- no unitPrice, bare "ea" with price_cents (existing fallback) ---

    def test_bare_ea_no_unit_price_with_cents(self):
        result = parse_foodstuffs_mobile_unit("ea", "", 250)
        self.assertEqual(result, (1, "ea", "ea", 2.5))

    def test_bare_ea_no_unit_price_no_cents(self):
        result = parse_foodstuffs_mobile_unit("ea", "")
        self.assertEqual(result, (1, "ea", "", 0))

    # --- no unitPrice, numeric prefix in units (NEW fallback) ---

    def test_numeric_prefix_no_unit_price_with_cents(self):
        result = parse_foodstuffs_mobile_unit("1pk", "", 299)
        self.assertEqual(result, (1, "pk", "pk", 2.99))

    def test_numeric_prefix_500g_no_unit_price_with_cents(self):
        result = parse_foodstuffs_mobile_unit("500g", "", 1499)
        self.assertEqual(result, (500, "g", "g", 14.99))

    def test_numeric_prefix_2pack_no_unit_price_with_cents(self):
        result = parse_foodstuffs_mobile_unit("2 pack", "", 599)
        self.assertEqual(result, (2, "pack", "pack", 5.99))

    def test_numeric_prefix_12pk_no_unit_price_with_cents(self):
        result = parse_foodstuffs_mobile_unit("12pk", "", 3499)
        self.assertEqual(result, (12, "pk", "pk", 34.99))

    def test_numeric_prefix_2l_no_unit_price_with_cents(self):
        result = parse_foodstuffs_mobile_unit("2L", "", 499)
        self.assertEqual(result, (2, "l", "l", 4.99))

    # --- no unitPrice, numeric prefix without price_cents ---

    def test_numeric_prefix_no_unit_price_no_cents(self):
        result = parse_foodstuffs_mobile_unit("1pk", "")
        self.assertEqual(result, (1, "pk", "", 0))

    # --- empty / null inputs ---

    def test_empty_units_empty_unit_price(self):
        result = parse_foodstuffs_mobile_unit("", "")
        self.assertEqual(result, ("", "", "", 0))

    def test_null_units(self):
        result = parse_foodstuffs_mobile_unit(None, "")
        self.assertEqual(result, ("", "", "", 0))

    def test_null_string_units(self):
        result = parse_foodstuffs_mobile_unit("null", "")
        self.assertEqual(result, ("", "", "", 0))

    def test_unit_price_only_no_units(self):
        result = parse_foodstuffs_mobile_unit("", "$2.99/ea")
        self.assertEqual(result, ("", "", "ea", 2.99))

    # --- unitPrice without slash ---

    def test_unit_price_no_slash(self):
        result = parse_foodstuffs_mobile_unit("ea", "$2.50")
        self.assertEqual(result, (1, "ea", "", 2.5))

    # --- decimal quantity ---

    def test_decimal_count_with_unit_price(self):
        result = parse_foodstuffs_mobile_unit("1.5kg", "$3.00/kg")
        self.assertEqual(result, (1.5, "kg", "kg", 3.00))

    def test_decimal_count_no_unit_price_with_cents(self):
        result = parse_foodstuffs_mobile_unit("1.5kg", "", 300)
        self.assertEqual(result, (1.5, "kg", "kg", 3.0))


class TestParseFoodstuffsVolumeSize(unittest.TestCase):
    """Tests for parse_foodstuffs_volume_size — the Edge API parser."""

    # --- displayName with number adjacent to unit ---

    def test_display_name_numeric_adjacent(self):
        result = parse_foodstuffs_volume_size("500g", {"price": 188}, [])
        self.assertEqual(result, (500, "g", "g", 1.88))

    def test_display_name_2l(self):
        result = parse_foodstuffs_volume_size("2l", {"price": 199}, [])
        self.assertEqual(result, (2, "l", "l", 1.99))

    def test_display_name_1kg(self):
        result = parse_foodstuffs_volume_size("1kg", {"price": 250}, [])
        self.assertEqual(result, (1, "kg", "kg", 2.50))

    # --- displayName bare unit ---

    def test_display_name_bare_ea(self):
        result = parse_foodstuffs_volume_size("ea", {"price": 199}, [])
        self.assertEqual(result, (1, "ea", "ea", 1.99))

    def test_display_name_bare_kg(self):
        result = parse_foodstuffs_volume_size("kg", {"price": 188}, [])
        self.assertEqual(result, (1, "kg", "kg", 1.88))

    # --- displayName with comparativePrice (measureDescription) ---

    def test_display_name_with_comparative_price(self):
        result = parse_foodstuffs_volume_size(
            "1.4kg",
            {"price": 3399, "comparativePrice": {"pricePerUnit": 243, "unitQuantityUom": "g", "measureDescription": "100g"}},
            [],
        )
        self.assertEqual(result, (1.4, "kg", "100g", 2.43))

    def test_display_name_with_promotion_comparative_price(self):
        result = parse_foodstuffs_volume_size(
            "ea",
            {"price": 199},
            [{"comparativePrice": {"pricePerUnit": 167, "measureDescription": "ea"}}],
        )
        self.assertEqual(result, (1, "ea", "ea", 1.67))

    def test_display_name_kg_with_comparative_price_1kg(self):
        result = parse_foodstuffs_volume_size(
            "kg",
            {"price": 188, "comparativePrice": {"pricePerUnit": 188, "unitQuantityUom": "kg", "measureDescription": "1kg"}},
            [],
        )
        self.assertEqual(result, (1, "kg", "1kg", 1.88))

    # --- empty / null displayName ---

    def test_empty_display_name(self):
        result = parse_foodstuffs_volume_size("", {"price": 199}, [])
        self.assertEqual(result, (None, "", "", 1.99))

    def test_null_display_name(self):
        result = parse_foodstuffs_volume_size(None, {"price": 199}, [])
        self.assertEqual(result, (None, "", "", 1.99))

    def test_null_string_display_name(self):
        result = parse_foodstuffs_volume_size("null", {"price": 199}, [])
        self.assertEqual(result, (None, "", "", 1.99))

    # --- no singlePrice, no promotions ---

    def test_no_price_no_promotions(self):
        result = parse_foodstuffs_volume_size("500g", None, [])
        self.assertEqual(result, (500, "g", "g", 0))


class TestParserParity(unittest.TestCase):
    """Tests that both parsers handle the same logical patterns consistently."""

    def test_numeric_prefix_parity(self):
        """When units='1pk' and no unitPrice, mobile parser should
        infer per_unit from price_cents — same concept as edge parser
        using singlePrice when no comparativePrice is available."""
        mobile = parse_foodstuffs_mobile_unit("1pk", "", 299)
        self.assertEqual(mobile, (1, "pk", "pk", 2.99))

    def test_bare_ea_parity(self):
        """Both parsers handle bare 'ea' consistently."""
        mobile = parse_foodstuffs_mobile_unit("ea", "", 250)
        self.assertEqual(mobile, (1, "ea", "ea", 2.5))

        edge = parse_foodstuffs_volume_size("ea", {"price": 250}, [])
        self.assertEqual(edge, (1, "ea", "ea", 2.5))

    def test_counted_unit_parity(self):
        """Both parsers handle counted units (e.g. '500g') consistently."""
        mobile = parse_foodstuffs_mobile_unit("500g", "", 1499)
        self.assertEqual(mobile, (500, "g", "g", 14.99))

        edge = parse_foodstuffs_volume_size("500g", {"price": 1499}, [])
        self.assertEqual(edge, (500, "g", "g", 14.99))


if __name__ == "__main__":
    unittest.main()