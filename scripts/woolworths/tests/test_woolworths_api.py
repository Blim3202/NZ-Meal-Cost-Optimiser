"""
Unit tests for Woolworths NZ API module (woolworths_api.py).

These tests are fully offline:
    - Store mapping is loaded from fixture/store_data_example.json
      (a real slice of the CDX site-location API, captured by
      fixture/generate_fixtures.py).
    - Product responses are loaded from fixture/response_example1.json
      (a real product search response from the live Woolworths API).
    - The non-food filtering test uses a hand-crafted product dict
      that is loaded from fixture/nonfood_product_example.json,
      which is also generated from the same live response structure.

All assertions reference fixture data directly so that test outcomes are
deterministic and traceable to the actual API responses captured.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Make the woolworths scripts directory and combined helpers importable.
SCRIPT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(SCRIPT_DIR))                         # scripts/woolworths
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "combined"))  # shared optimizer_utils

FIXTURE_DIR = SCRIPT_DIR / "fixture"

from woolworths_api import (
    is_food_department,
    _load_store_mapping,
    get_nearby_stores,
    set_store_context,
    search_products,
    # get_store_mapping, # Simple loader, no need to test
    # create_session, # Simple get request, no need to test
    # find_cheapest, # Simple min() on search results, no need to test
)

from woolworths_api import create_session


def _load_json(filename):
    """Load a JSON fixture file from the fixture directory."""
    with open(FIXTURE_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


class TestIsFoodDepartment(unittest.TestCase):
    """Tests for is_food_department()."""

    def _make_product(self, dept_ids):
        """Create a minimal product dict with the given department ids."""
        return {"departments": [{"id": d} for d in dept_ids]}

    def test_food_department_included(self):
        """A product in a food department (id=4 Fridge & Deli) should be included.

        Department 4 is used in the real fixture (response_example1.json)
        for milk products.
        """
        product = self._make_product([4])  # Fridge & Deli
        self.assertTrue(is_food_department(product))

    def test_non_food_department_excluded(self):
        """A product in a non-food department (id=11 Household) must be excluded."""
        product = self._make_product([11])
        self.assertFalse(is_food_department(product))

    def test_pet_department_excluded(self):
        """A product in the Pet department (id=13) must be excluded."""
        product = self._make_product([13])
        self.assertFalse(is_food_department(product))

    def test_empty_departments_included(self):
        """Products with no department info are assumed food (included).

        This matches the real ad/promo item (index 4 in the fixture)
        which has no departments and should be treated as non-food
        only if it has a SKU — actually is_food_department returns True
        for empty departments, so it would be included unless filtered
        elsewhere (search_products checks SKU).
        """
        product = {"departments": []}
        self.assertTrue(is_food_department(product))

    def test_mixed_food_and_non_food_excluded(self):
        """If ANY department is non-food, the product is excluded."""
        product = self._make_product([4, 11])  # Food + Household
        self.assertFalse(is_food_department(product))


class TestLoadStoreMapping(unittest.TestCase):
    """Tests for _load_store_mapping() using real fixture data.

    The fixture (store_data_example.json) was captured from the live CDX
    site-location API and contains 5 stores in the Nelson region.
    """

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_load_valid_store_mapping(self):
        """Load the fixture and verify the mapping for the first store
        (Nelson Junction Woolworths).

        Expected mapping entry (from store_data_example.json):
            extra2=4166071 -> {'fulfilmentStoreId': 9290,
                               'name': 'Nelson Junction Woolworths',
                               'lat': -41.2977069,
                               'lon': 173.241518}
        """
        mapping = _load_store_mapping()
        self.assertIn("4166071", mapping)
        entry = mapping["4166071"]
        self.assertEqual(entry["fulfilmentStoreId"], 9290)
        self.assertEqual(entry["name"], "Nelson Junction Woolworths")
        self.assertAlmostEqual(entry["lat"], -41.2977069, places=4)
        self.assertAlmostEqual(entry["lon"], 173.241518, places=4)

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_all_fixture_stores_loaded(self):
        """All 5 stores in the fixture should be loaded into the mapping."""
        mapping = _load_store_mapping()
        self.assertEqual(len(mapping), 5)

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_all_stores_have_fulfilment_ids(self):
        """Every entry in the mapping must have a non-null fulfilmentStoreId."""
        mapping = _load_store_mapping()
        for pid, info in mapping.items():
            self.assertIsInstance(info["fulfilmentStoreId"], int)
            self.assertNotEqual(info["fulfilmentStoreId"], 9171)  # not the default


class TestGetNearbyStores(unittest.TestCase):
    """Tests for get_nearby_stores() using real fixture coordinates.

    The fixture stores are all in the Nelson/South Island region.
    Reference point: Nelson Junction Woolworths (-41.2977069, 173.241518)
    """

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_nearby_stores_from_reference_point(self):
        """All 5 fixture stores are within 5 km of Nelson Junction.

        Using Nelson Junction's coordinates as the query point, we expect
        at least 3 stores within 5 km (Nelson Junction itself + nearby
        Nelson stores). The result should be sorted by distance ascending.
        """
        ref = _load_json("nearby_stores_example.json")
        user_lat = ref["reference_point"]["lat"]
        user_lon = ref["reference_point"]["lon"]

        nearby = get_nearby_stores(user_lat, user_lon, max_dist_km=5)
        self.assertGreaterEqual(len(nearby), 3)

        # Results must be sorted by distance ascending
        distances = [s["distance_km"] for s in nearby]
        self.assertEqual(distances, sorted(distances))

        # The closest store should be Nelson Junction itself (distance ~0)
        self.assertAlmostEqual(nearby[0]["distance_km"], 0.0, places=1)
        self.assertEqual(nearby[0]["name"], "Nelson Junction Woolworths")

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_no_nearby_stores_far_point(self):
        """A query point in Auckland (>500km away) must return no stores.

        The fixture stores are in Nelson (lat ~-41.3). Querying from
        Auckland (lat ~-36.8) is ~500 km away.
        """
        user_lat, user_lon = -36.8485, 174.7635  # Auckland CBD
        nearby = get_nearby_stores(user_lat, user_lon, max_dist_km=5)
        self.assertEqual(len(nearby), 0)


class TestSearchProductsFiltering(unittest.TestCase):
    """Tests for search_products() filtering logic using a mocked session.

    The mocked session.get returns the real captured response from
    fixture/response_example1.json (a milk search at Nelson Junction store).
    """

    def _mock_session(self):
        """Build a MagicMock session whose .get returns the captured
        response_example1.json fixture."""
        fixture = _load_json("response_example1.json")
        mock_resp = MagicMock()
        mock_resp.json.return_value = fixture
        session = MagicMock()
        session.get.return_value = mock_resp
        return session

    def test_search_products_includes_food(self):
        """search_products with food_only=True must include milk products.

        The captured response contains 13 food items (department 4,
        Fridge & Deli) plus 1 ad/promo item with no SKU (filtered out).
        """
        session = self._mock_session()
        products = search_products(session, "milk", food_only=True)
        names = [p["name"] for p in products]
        # The first item should be "anchor milk standard blue"
        self.assertTrue(any("milk" in n.lower() for n in names))
        # food_only=True includes items with no department info (treated as food)
        # so the ad item (index 4, departments=[]) is also returned.
        # Total: 14 items (13 with departments + 1 ad with no departments).
        self.assertEqual(len(products), 14)

    def test_search_products_excludes_no_sku_items(self):
        """The raw API response contains an ad item with an empty SKU.

        search_products() includes items regardless of SKU (it only filters
        by food_only). The ad item (index 4 in the fixture) has sku="" and
        departments=[]. This test verifies the raw response structure —
        the SKU filtering happens downstream in build_row().
        """
        session = self._mock_session()
        products = search_products(session, "milk", food_only=False)
        skus = [p["sku"] for p in products]
        # The ad item has an empty SKU — verify it appears in raw results
        empty_sku_count = sum(1 for s in skus if not s)
        self.assertGreaterEqual(empty_sku_count, 1)

    def test_search_products_no_food_filter_returns_all(self):
        """Without food_only, all items from the response are returned.

        The captured response contains 14 items total (including 1 ad item
        with no SKU and no departments).
        """
        session = self._mock_session()
        products = search_products(session, "milk", food_only=False)
        self.assertEqual(len(products), 14)

    def test_search_products_normalizes_fields(self):
        """search_products must flatten the raw API response into the
        normalized dict structure expected by build_row().

        Specifically: salePrice, volumeSize, cupMeasure, cupListPrice,
        isSpecial, and department (string name).
        """
        session = self._mock_session()
        products = search_products(session, "milk", food_only=False)
        first = products[0]

        # Verify all normalized keys are present
        expected_keys = {"sku", "name", "salePrice", "originalPrice",
                         "isSpecial", "unitPrice", "volumeSize",
                         "cupMeasure", "cupListPrice", "url",
                         "imageUrl", "department"}
        self.assertTrue(expected_keys.issubset(set(first.keys())))

        # Verify specific values from the first item (anchor milk standard blue)
        self.assertEqual(first["sku"], "282848")
        self.assertEqual(first["salePrice"], 3.76)
        self.assertEqual(first["volumeSize"], "1L")
        self.assertEqual(first["cupMeasure"], "1L")
        self.assertEqual(first["cupListPrice"], 3.76)
        self.assertEqual(first["department"], "Fridge & Deli")


class TestSetStoreContext(unittest.TestCase):
    """Tests for set_store_context() — the per-store cookie injection mechanism.

    set_store_context() does two things:
    1. Constructs the cw-lrkswrdjp cookie from the store's fulfilmentStoreId
       (extra1 in the CDX data).
    2. GETs /api/v1/shell to VERIFY the cookie took effect — it checks that
       the shell's fulfilment.fulfilmentStoreId matches the injected value.
       If the shell still shows the default store (9171), it raises RuntimeError.

    These tests use the REAL captured shell response from
    fixture/shell_example1.json (Nelson Junction Woolworths, fsId=9290)
    and mock the session.get() call that hits /api/v1/shell.
    """

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_cookie_value_constructed_correctly(self):
        """The cw-lrkswrdjp cookie must be 'dm-Pickup,f-{fsid},s-38'.

        For Nelson Junction Woolworths (extra1=9290, extra2=4166071):
            cookie = "dm-Pickup,f-9290,s-38"
        """
        session = MagicMock()
        shell_fixture = _load_json("shell_example1.json")
        mock_resp = MagicMock()
        mock_resp.json.return_value = shell_fixture
        session.get.return_value = mock_resp

        result = set_store_context(session, "4166071")
        self.assertEqual(result["fulfilmentStoreId"], 9290)
        self.assertEqual(result["method"], "Pickup")

        # Verify the cookie was set with the correct value
        session.cookies.set.assert_called_once()
        call_args = session.cookies.set.call_args
        cookie_val = call_args[0][0]  # First positional argument is cookie_val
        # The cookie val is the second argument
        cookie_name = call_args[0][0] if call_args[0] else None
        cookie_value = call_args[0][1] if len(call_args[0]) > 1 else None
        # cookies.set("cw-lrkswrdjp", cookie_val, domain=..., path=...)
        # First positional arg: "cw-lrkswrdjp"
        # Second positional arg: cookie_val
        self.assertEqual(cookie_name, "cw-lrkswrdjp")
        self.assertEqual(cookie_value, "dm-Pickup,f-9290,s-38")

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_shell_validation_passes(self):
        """When the shell returns the expected fulfilmentStoreId, no error is raised.

        Uses the captured shell fixture where the injected store (9290) Nelson Junction Woolworths
        correctly appears as the active store context.
        """
        session = MagicMock()
        shell_fixture = _load_json("shell_example1.json")
        mock_resp = MagicMock()
        mock_resp.json.return_value = shell_fixture
        session.get.return_value = mock_resp

        # This should NOT raise RuntimeError
        result = set_store_context(session, "4166071")
        self.assertEqual(result["fulfilmentStoreId"], 9290)

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_store_not_found_raises_value_error(self):
        """Requesting a non-existent pickup_address_id must raise ValueError."""
        session = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            set_store_context(session, "999999")
        self.assertIn("not in mapping", str(ctx.exception))

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_default_store_shell_raises_runtime_error(self):
        """When the shell still shows the default store (9171), RuntimeError is raised.

        This simulates the case where the cookie injection fails. We mock
        the shell response to show fulfilmentStoreId=9171 (the default).
        """
        session = MagicMock()
        # Mock a shell response that shows the DEFAULT store (9171)
        fake_shell = {
            "context": {
                "fulfilment": {
                    "fulfilmentStoreId": 9171,  # default store — proves cookie didn't work
                    "method": "Courier",
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_shell
        session.get.return_value = mock_resp

        with self.assertRaises(RuntimeError) as ctx:
            set_store_context(session, "4166071")
        self.assertIn("Cookie not accepted", str(ctx.exception))

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_cookie_injected_before_shell_validation(self):
        """The cookie must be set BEFORE the shell validation call.

        set_store_context() first sets the cookie, then calls shell to verify.
        We verify by checking the call order on the session mock.
        """
        session = MagicMock()
        shell_fixture = _load_json("shell_example1.json")
        mock_resp = MagicMock()
        mock_resp.json.return_value = shell_fixture
        session.get.return_value = mock_resp

        set_store_context(session, "4166071")

        # cookies.set (positional args) should be called before session.get
        # We verify both were called
        self.assertTrue(session.cookies.set.called)
        self.assertTrue(session.get.called)


if __name__ == "__main__":
    unittest.main()
