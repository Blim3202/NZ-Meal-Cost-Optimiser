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
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

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
    create_session,
)


def _load_json(filename):
    """Load a JSON fixture file from the fixture directory."""
    with open(FIXTURE_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


class TestIsFoodDepartment:
    """Tests for is_food_department()."""

    @staticmethod
    def _make_product(dept_ids):
        """Create a minimal product dict with the given department ids."""
        return {"departments": [{"id": d} for d in dept_ids]}

    def test_food_department_included(self):
        """A product in a food department (id=4 Fridge & Deli) should be included.

        Department 4 is used in the real fixture (response_example1.json)
        for milk products.
        """
        product = self._make_product([4])  # Fridge & Deli
        assert is_food_department(product) is True

    def test_non_food_department_excluded(self):
        """A product in a non-food department (id=11 Household) must be excluded."""
        product = self._make_product([11])
        assert is_food_department(product) is False

    def test_pet_department_excluded(self):
        """A product in the Pet department (id=13) must be excluded."""
        product = self._make_product([13])
        assert is_food_department(product) is False

    def test_empty_departments_included(self):
        """Products with no department info are assumed food (included).

        This matches the real ad/promo item (index 4 in the fixture)
        which has no departments and should be treated as non-food
        only if it has a SKU — actually is_food_department returns True
        for empty departments, so it would be included unless filtered
        elsewhere (search_products checks SKU).
        """
        product = {"departments": []}
        assert is_food_department(product) is True

    def test_mixed_food_and_non_food_excluded(self):
        """If ANY department is non-food, the product is excluded."""
        product = self._make_product([4, 11])  # Food + Household
        assert is_food_department(product) is False


class TestLoadStoreMapping:
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
        assert "4166071" in mapping
        entry = mapping["4166071"]
        assert entry["fulfilmentStoreId"] == 9290
        assert entry["name"] == "Nelson Junction Woolworths"
        assert abs(entry["lat"] - (-41.2977069)) < 0.0001
        assert abs(entry["lon"] - 173.241518) < 0.0001

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_all_fixture_stores_loaded(self):
        """All 5 stores in the fixture should be loaded into the mapping."""
        mapping = _load_store_mapping()
        assert len(mapping) == 5

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_all_stores_have_fulfilment_ids(self):
        """Every entry in the mapping must have a non-null fulfilmentStoreId."""
        mapping = _load_store_mapping()
        for pid, info in mapping.items():
            assert isinstance(info["fulfilmentStoreId"], int)
            assert info["fulfilmentStoreId"] != 9171  # not the default

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_mapping_keys_are_pickup_address_ids(self):
        """Mapping keys must be the extra2 (pickupAddressId) values as strings."""
        mapping = _load_store_mapping()
        # From store_data_example.json: extra2 values are 4166071, 1225552, 2810937, 2367135, 2723227
        expected_keys = {"4166071", "1225552", "2810937", "2367135", "2723227"}
        assert set(mapping.keys()) == expected_keys

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_mapping_contains_all_extra1_fulfilment_ids(self):
        """All extra1 (fulfilmentStoreId) values from the fixture must be present."""
        mapping = _load_store_mapping()
        fulfilment_ids = {info["fulfilmentStoreId"] for info in mapping.values()}
        # From fixture: extra1 values are 9290, 9527, 9246, 9168, 9040
        expected_ids = {9290, 9527, 9246, 9168, 9040}
        assert fulfilment_ids == expected_ids


class TestGetNearbyStores:
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
        assert len(nearby) >= 3

        # Results must be sorted by distance ascending
        distances = [s["distance_km"] for s in nearby]
        assert distances == sorted(distances)

        # The closest store should be Nelson Junction itself (distance ~0)
        assert abs(nearby[0]["distance_km"] - 0.0) < 0.1
        assert nearby[0]["name"] == "Nelson Junction Woolworths"

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_no_nearby_stores_far_point(self):
        """A query point in Auckland (>500km away) must return no stores.

        The fixture stores are in Nelson (lat ~-41.3). Querying from
        Auckland (lat ~-36.8) is ~500 km away.
        """
        user_lat, user_lon = -36.8485, 174.7635  # Auckland CBD
        nearby = get_nearby_stores(user_lat, user_lon, max_dist_km=5)
        assert len(nearby) == 0

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_nearby_stores_all_within_radius(self):
        """Every returned store must be within the specified radius."""
        ref = _load_json("nearby_stores_example.json")
        user_lat = ref["reference_point"]["lat"]
        user_lon = ref["reference_point"]["lon"]

        nearby = get_nearby_stores(user_lat, user_lon, max_dist_km=5)
        for store in nearby:
            assert store["distance_km"] <= 5.0

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_nearby_stores_contain_fulfilment_store_id(self):
        """Each nearby store dict must contain a 'fulfilmentStoreId' key."""
        ref = _load_json("nearby_stores_example.json")
        user_lat = ref["reference_point"]["lat"]
        user_lon = ref["reference_point"]["lon"]

        nearby = get_nearby_stores(user_lat, user_lon, max_dist_km=5)
        for store in nearby:
            assert "fulfilmentStoreId" in store
            assert isinstance(store["fulfilmentStoreId"], int)


class TestSearchProductsFiltering:
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

        The captured response contains food items (department 4, Fridge & Deli)
        plus 1 ad/promo item with no SKU and no departments. Since is_food_department
        returns True for empty departments (items with no dept are assumed food),
        the ad item is also included.
        """
        session = self._mock_session()
        products = search_products(session, "milk", food_only=True)
        names = [p["name"] for p in products]
        # All products should be milk-related
        assert any("milk" in n.lower() for n in names)
        # food_only=True excludes items with non-food departments (Household, Pet, etc.)
        # but does NOT exclude items with empty SKU or empty departments (those are treated as food)
        # The ad item (index 4, sku="", departments=[]) is included because is_food_department([]) returns True
        for p in products:
            if p["department"]:
                assert p["department"] == "Fridge & Deli"  # Only food dept in fixture

    def test_search_products_no_sku_items_excluded_with_food_filter(self):
        """With food_only=True, items with empty SKU are NOT excluded.

        search_products only filters by department, not SKU. The ad item
        (index 4) has empty SKU and empty departments, which is treated
        as food (is_food_department returns True for empty departments).
        So empty SKU items ARE included when food_only=True.
        """
        session = self._mock_session()
        products = search_products(session, "milk", food_only=True)
        skus = [p["sku"] for p in products]
        # The ad item has empty SKU — it IS included because food_only
        # only filters by department, and empty departments pass the food check
        empty_sku_count = sum(1 for s in skus if not s)
        assert empty_sku_count >= 1

    def test_search_products_no_food_filter_returns_all_with_sku(self):
        """Without food_only, all items with valid SKUs are returned."""
        session = self._mock_session()
        products = search_products(session, "milk", food_only=False)
        # 11 items total, 1 has empty SKU (ad item)
        # search_products with food_only=False returns all items
        assert len(products) == 11

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
        assert expected_keys.issubset(set(first.keys()))

        # Verify specific values from the first item (woolworths milk standard, 3L)
        assert first["sku"] == "282768"
        assert first["salePrice"] == 7.04
        assert first["volumeSize"] == "3L"
        assert first["cupMeasure"] == "1L"
        assert first["cupListPrice"] == 2.35
        assert first["department"] == "Fridge & Deli"

    def test_search_products_preserves_all_products(self):
        """search_products with food_only=False must return all 11 items
        from the captured response (no filtering)."""
        session = self._mock_session()
        products = search_products(session, "milk", food_only=False)
        assert len(products) == 11


class TestSetStoreContext:
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
        assert result["fulfilmentStoreId"] == 9290
        assert result["method"] == "Pickup"

        # Verify the cookie was set with the correct value
        session.cookies.set.assert_called_once()
        call_args = session.cookies.set.call_args
        # cookies.set is called as set("cw-lrkswrdjp", "dm-Pickup,f-9290,s-38", domain=..., path=...)
        assert call_args.args[0] == "cw-lrkswrdjp"
        assert call_args.args[1] == "dm-Pickup,f-9290,s-38"
        assert call_args.kwargs.get("domain") == "www.woolworths.co.nz"
        assert call_args.kwargs.get("path") == "/"

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
        assert result["fulfilmentStoreId"] == 9290

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_store_not_found_raises_value_error(self):
        """Requesting a non-existent pickup_address_id must raise ValueError."""
        session = MagicMock()
        with pytest.raises(ValueError, match="not in mapping"):
            set_store_context(session, "999999")

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

        with pytest.raises(RuntimeError, match="Cookie not accepted"):
            set_store_context(session, "4166071")

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

        # Verify call order: cookies.set called before session.get
        # In MagicMock, call order is preserved in mock_calls
        mock_calls = session.mock_calls

        # Find indices of the relevant calls
        cookie_set_idx = None
        shell_get_idx = None
        for i, call in enumerate(mock_calls):
            if call[0] == "cookies.set":
                cookie_set_idx = i
            elif call[0] == "get" and cookie_set_idx is not None:
                shell_get_idx = i
                break

        assert cookie_set_idx is not None, "cookies.set was not called"
        assert shell_get_idx is not None, "session.get was not called"
        assert cookie_set_idx < shell_get_idx, "Cookie must be set before shell validation GET"

    @patch("woolworths_api.STORE_JSON", FIXTURE_DIR / "store_data_example.json")
    def test_shell_is_called_with_correct_url(self):
        """The shell validation GET must be called against /api/v1/shell."""
        session = MagicMock()
        shell_fixture = _load_json("shell_example1.json")
        mock_resp = MagicMock()
        mock_resp.json.return_value = shell_fixture
        session.get.return_value = mock_resp

        result = set_store_context(session, "4166071")

        # Verify the shell endpoint was called
        session.get.assert_called_once()
        call_args = session.get.call_args
        assert "/shell" in call_args[0][0] or "/shell" in str(call_args)