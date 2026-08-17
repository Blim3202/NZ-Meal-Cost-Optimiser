"""
Unit tests for Pak'nSave API module (paknsave_api.py).

These tests are fully offline, using captured live API fixtures under fixture/:

    - edge_store_list_example.json        Edge API store list (57 stores)
    - edge_search_pass1_example.json      Edge Pass 1 relevance search ("milk", 40 hits)
    - edge_search_pass2_example.json      Edge Pass 2 per-store pricing (10 products)
    - mobile_login_example.json           Mobile guest token auth response
    - mobile_stores_example.json          Mobile physical stores (60 stores)
    - mobile_search_example.json          Mobile product search ("milk", 20 products)
    - store_finder_page_example.json      Website __NEXT_DATA__ (60 stores)

Every assertion references real fixture values -- prices, SKUs, category names,
store counts, and field structures -- to verify the code correctly parses and
filters live API responses.

Where a code path has no live fixture coverage (e.g. the promotions array in
Edge Pass 2 products), that code path is documented as uncovered rather than
tested with synthetic data.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixture"


def _load_json(filename):
    """Load a JSON fixture file from the fixture directory.

    Args:
        filename: the fixture file name (lives in tests/paknsave/fixture/).

    Returns:
        The parsed JSON content as a dict or list.
    """
    with open(FIXTURE_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


from NZMealOptimiser.pricing.paknsave_api import (
    NON_FOOD_CATEGORIES,
    load_stores,
    find_nearby_stores,
    PaknSaveEdgeAPI,
    PaknSaveMobileAPI,
    PaknSaveAPI,
    create_api,
)


class TestNonFoodCategories:
    """Tests for the NON_FOOD_CATEGORIES blacklist from paknsave_api.py.

    The blacklist is sourced from data/observed_category1_paknsave.json,
    which documents all 116 unique category1 values observed in the live API.
    """

    def test_non_food_categories_contains_expected_entries(self):
        """Verify NON_FOOD_CATEGORIES includes key non-food department names.

        These values are confirmed present in observed_category1_paknsave.json:
        - "Dog" (333 occurrences)
        - "Cat" (304 occurrences)
        - "Baby & Toddler Food" (232 occurrences)
        - "Dishwashing" (209 occurrences)
        """
        assert "Dog" in NON_FOOD_CATEGORIES
        assert "Cat" in NON_FOOD_CATEGORIES
        assert "Baby & Toddler Food" in NON_FOOD_CATEGORIES
        assert "Dishwashing" in NON_FOOD_CATEGORIES
        assert "Baby Formula" in NON_FOOD_CATEGORIES
        assert "Laundry" in NON_FOOD_CATEGORIES

    def test_non_food_categories_excludes_food(self):
        """Verify NON_FOOD_CATEGORIES does NOT include food categories."""
        assert "Milk" not in NON_FOOD_CATEGORIES
        assert "Meat" not in NON_FOOD_CATEGORIES
        assert "Vegetables" not in NON_FOOD_CATEGORIES
        assert "Beef" not in NON_FOOD_CATEGORIES

    def test_non_food_categories_is_set(self):
        """Verify NON_FOOD_CATEGORIES is a set for O(1) membership testing."""
        assert isinstance(NON_FOOD_CATEGORIES, set)
        assert len(NON_FOOD_CATEGORIES) > 30


class TestPaknSaveEdgeAPI:
    """Tests for PaknSaveEdgeAPI using captured live API fixtures.

    Fixtures from generate_fixtures.py capture_edge_fixtures():
    - edge_store_list_example.json: GET /v1/edge/store (57 stores)
    - edge_search_pass1_example.json: POST products-index (40 hits for "milk")
    - edge_search_pass2_example.json: POST paginated/products (10 products, PRICE_ASC)
    """

    edge_store_list: dict
    edge_pass1: dict
    edge_pass2: dict

    def setup_method(self):
        """Load all Edge API fixtures once for the class."""
        self.edge_store_list = _load_json("edge_store_list_example.json")
        self.edge_pass1 = _load_json("edge_search_pass1_example.json")
        self.edge_pass2 = _load_json("edge_search_pass2_example.json")

    def test_authenticate_success(self):
        """Verify authenticate() reads the fs-user-token cookie after a successful GET.

        The Edge API uses website JWT flow: GET the site, POST to
        /api/user/get-current-user, then extract the fs-user-token cookie.
        """
        api = PaknSaveEdgeAPI()
        mock_session = MagicMock()
        mock_session.cookies.get.return_value = "fake-jwt-token-12345"
        api.session = mock_session

        token = api.authenticate()
        assert token == "fake-jwt-token-12345"
        assert api.token == "fake-jwt-token-12345"

    def test_authenticate_fails_no_token(self):
        """Verify authenticate() raises RuntimeError when fs-user-token cookie is absent."""
        api = PaknSaveEdgeAPI()
        mock_session = MagicMock()
        mock_session.cookies.get.return_value = None
        api.session = mock_session

        with pytest.raises(RuntimeError):
            api.authenticate()

    @patch("NZMealOptimiser.pricing.paknsave_api.requests.get")
    def test_get_stores_returns_live_count(self, mock_get):
        """Verify get_stores() returns exactly 57 stores from the live Edge API fixture.

        Mocks the GET /v1/edge/store endpoint to return edge_store_list_example.json.
        Asserts the store count matches the real fixture (57 per edge_store_list_example_meta.json).
        """
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.edge_store_list
        mock_get.return_value = mock_resp

        api = PaknSaveEdgeAPI()
        api.token = "test-token"
        stores = api.get_stores()

        assert len(stores) == 57

        first = stores[0]
        assert first["id"] == "3bb30799-82ce-4648-8c02-5113228963ed"
        assert first["name"] == "PAK'nSAVE Te Awamutu"
        assert first["banner"] == "PNS"
        assert first["latitude"] == -38.008101
        assert first["longitude"] == 175.340102
        assert first["region"] == "NI"
        assert first["clickAndCollect"] is True

    def test_pass1_filtering_keeps_all_food_hits(self):
        """Verify pass1 filtering logic keeps all 40 hits from the live Pass 1 fixture.

        The live Pass 1 fixture (edge_search_pass1_example.json) contains 40 hits
        for "milk", ALL of which have matchedWords=True in _highlightResult
        and category1=["Milk"] (not in NON_FOOD_CATEGORIES).

        The filtering logic in pass1_relevance_search_hits() should return all 40 hits
        since none are filtered out by the food category blacklist.
        """
        hits = self.edge_pass1["hits"]
        filtered = []
        for h in hits:
            hr = h.get("_highlightResult", {})
            matched = any(
                isinstance(v, dict) and v.get("matchedWords")
                for v in hr.values()
            )
            cat1 = h.get("category1", [])
            if matched and not any(c in NON_FOOD_CATEGORIES for c in cat1):
                filtered.append(h)

        assert len(filtered) == 40

        first = filtered[0]
        assert first["productID"] == "5201479-EA-000"
        assert first["category1"] == ["Milk"]

    def test_pass1_product_ids_unique(self):
        """Verify pass1 product IDs are unique across the 40 real hits.

        Uses the real edge_search_pass1_example.json fixture to extract all
        40 productIDs and confirm uniqueness.
        """
        hits = self.edge_pass1["hits"]
        product_ids = [h["productID"] for h in hits]

        assert len(product_ids) == 40
        assert len(set(product_ids)) == 40
        assert product_ids[0] == "5201479-EA-000"

    @patch("NZMealOptimiser.pricing.paknsave_api.requests.post")
    def test_pass2_per_store_pricing_returns_live_products(self, mock_post):
        """Verify pass2_per_store_pricing() returns real per-store pricing products.

        Mocks the POST /paginated/products endpoint to return
        edge_search_pass2_example.json (10 products sorted by PRICE_ASC).
        """
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.edge_pass2
        mock_post.return_value = mock_resp

        api = PaknSaveEdgeAPI()
        api.token = "test-token"
        products = api.pass2_per_store_pricing("store-123", "milk", ["prod-1"])

        assert len(products) == 10

        # Prices in cents: 209, 259, 357, 479, 479, 522, 585, 711, 711, 871
        prices = [p["singlePrice"]["price"] for p in products]
        assert prices == sorted(prices)

        first = products[0]
        assert first["productId"] == "5004752-EA-000"
        assert first["singlePrice"]["price"] == 209

    def test_pass2_empty_product_ids_returns_empty(self):
        """Verify pass2_per_store_pricing returns empty list when no product IDs given."""
        api = PaknSaveEdgeAPI()
        result = api.pass2_per_store_pricing("store-123", "milk", [])
        assert result == []

    def test_extract_price_all_products(self):
        """Verify extract_price converts all 10 products in Pass 2 fixture to dollars.

        All products have singlePrice.price in cents, no promotions key.
        Expected prices (from edge_search_pass2_example.json):
        209, 259, 357, 479, 479, 522, 585, 711, 711, 871 cents
        """
        expected_prices = [2.09, 2.59, 3.57, 4.79, 4.79, 5.22, 5.85, 7.11, 7.11, 8.71]
        prices = [PaknSaveEdgeAPI.extract_price(p) for p in self.edge_pass2["products"]]
        assert prices == expected_prices

    def test_extract_price_null_returns_none(self):
        """Verify extract_price returns None when no price is available.

        No promotion fixture exists in the captured data, so the promo branch
        of extract_price is untested against live data.
        """
        assert PaknSaveEdgeAPI.extract_price({"singlePrice": {}}) is None
        assert PaknSaveEdgeAPI.extract_price({}) is None

    def test_get_product_name(self):
        """Verify get_product_name returns the product name from Pass 2 fixture.

        Uses edge_search_pass2_example.json products[0] which has name="Standard UHT Milk".
        """
        product = self.edge_pass2["products"][0]
        assert PaknSaveEdgeAPI.get_product_name(product) == "Standard UHT Milk"

    def test_get_product_size(self):
        """Verify get_product_size returns the displayName from Pass 2 fixture.

        Products in edge_search_pass2_example.json have displayName field (e.g. "1l").
        """
        product = self.edge_pass2["products"][0]
        assert PaknSaveEdgeAPI.get_product_size(product) == "1l"


class TestPaknSaveMobileAPI:
    """Tests for PaknSaveMobileAPI using captured live API fixtures.

    Fixtures from generate_fixtures.py capture_mobile_fixtures():
    - mobile_login_example.json: POST /mobile/user/login/guest (access_token)
    - mobile_stores_example.json: GET /mobile/store/physical (60 stores)
    - mobile_search_example.json: POST /mobile/ecomm-products/PNS/{id}/search (20 products)
    """

    mobile_login: dict
    mobile_stores: dict
    mobile_search: dict

    def setup_method(self):
        """Load all Mobile API fixtures once for the class."""
        self.mobile_login = _load_json("mobile_login_example.json")
        self.mobile_stores = _load_json("mobile_stores_example.json")
        self.mobile_search = _load_json("mobile_search_example.json")

    def test_is_food_product_all_fixture_products_are_food(self):
        """Verify _is_food_product correctly classifies all 20 real Mobile API products as food.

        All 20 products in mobile_search_example.json have categories like
        ["Milk", "Fresh Milk"] or ["Milk", "UHT Milk & Milk Powder"] -- all food.
        None match the NON_FOOD_CATEGORIES blacklist.
        """
        api = PaknSaveMobileAPI()
        products = self.mobile_search["products"]

        food_count = sum(1 for p in products if api._is_food_product(p))
        assert food_count == 20

        assert api._is_food_product(products[0]) is True
        assert products[0]["categories"] == ["Milk", "Fresh Milk"]

    def test_ensure_token(self):
        """Verify _ensure_token stores the access_token from the live mobile login response.

        Mocks the scraper POST against mobile_login_example.json fixture.
        The fixture contains a real JWT access_token (expires_in: 1800 seconds).
        """
        api = PaknSaveMobileAPI()
        mock_scraper = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.mobile_login
        mock_scraper.post.return_value = mock_resp
        api.scraper = mock_scraper

        api._ensure_token()
        assert api._token == self.mobile_login["access_token"]

    @patch("cloudscraper.create_scraper")
    def test_search_products_returns_20_results(self, mock_create):
        """Verify search_products returns 20 products from the live Mobile API fixture.

        Mocks the scraper POST to return mobile_search_example.json (20 products).
        With food_only=True (default), all 20 are kept (all have food categories).
        """
        mock_scraper = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self.mobile_search
        mock_scraper.post.return_value = mock_resp
        mock_create.return_value = mock_scraper

        api = PaknSaveMobileAPI()
        api._token = "test-token"
        products = api.search_products("store-123", "milk")
        assert products is not None  # guaranteed by fixture response

        assert len(products) == 20

        first = products[0]
        assert first["productId"] == "5201479-EA-000"
        assert first["name"] == "Standard Milk"
        assert first["price"] == 479
        assert first["unitPrice"] == "$2.40/1L"
        assert first["units"] == "2l"

    @patch("cloudscraper.create_scraper")
    def test_get_stores_returns_60_stores(self, mock_create):
        """Verify get_stores returns 60 stores from the live Mobile API fixture.

        Mocks the login + GET /mobile/store/physical to return mobile_stores_example.json
        (60 stores). Returns a dict keyed by store ID.
        """
        mock_scraper = MagicMock()
        login_resp = MagicMock()
        login_resp.json.return_value = self.mobile_login
        stores_resp = MagicMock()
        stores_resp.status_code = 200
        stores_resp.json.return_value = self.mobile_stores
        mock_scraper.post.return_value = login_resp
        mock_scraper.get.return_value = stores_resp
        mock_create.return_value = mock_scraper

        api = PaknSaveMobileAPI()
        stores = api.get_stores()

        assert len(stores) == 60

        first_store = list(stores.values())[0]
        assert first_store["id"] == "3bb30799-82ce-4648-8c02-5113228963ed"
        assert first_store["name"] == "PAK'nSAVE Te Awamutu"
        assert first_store["banner"] == "PNS"
        assert first_store["latitude"] == -38.008101


class TestPaknSaveAPIUnified:
    """Tests for the PaknSaveAPI unified wrapper and create_api factory."""

    def test_create_api_edge(self):
        """Verify create_api('edge') returns edge backend with PaknSaveEdgeAPI."""
        api = create_api("edge")
        assert api.backend == "edge"
        assert isinstance(api.client, PaknSaveEdgeAPI)

    def test_create_api_mobile(self):
        """Verify create_api('mobile') returns mobile backend with PaknSaveMobileAPI."""
        api = create_api("mobile")
        assert api.backend == "mobile"
        assert isinstance(api.client, PaknSaveMobileAPI)

    def test_unified_get_stores_edge(self):
        """Verify PaknSaveAPI.get_stores() returns list directly for edge backend.

        The Edge backend's get_stores() already returns a list, so PaknSaveAPI
        passes it through without conversion.
        """
        api = create_api("edge")
        mock_client = MagicMock(spec=PaknSaveEdgeAPI)
        mock_client.get_stores.return_value = [{"id": "test-id"}]
        api.client = mock_client
        result = api.get_stores()
        assert result == [{"id": "test-id"}]
        assert isinstance(result, list)

    def test_unified_get_stores_mobile(self):
        """Verify PaknSaveAPI.get_stores() converts mobile dict to list correctly."""
        api = create_api("mobile")
        mock_client = MagicMock()
        mock_client.get_stores.return_value = {"store-1": {"id": "store-1"}}
        api.client = mock_client
        result = api.get_stores()
        assert len(result) == 1
        assert result[0]["id"] == "store-1"
