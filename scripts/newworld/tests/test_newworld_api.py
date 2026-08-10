"""
Unit tests for New World API module (newworld_api.py).

These tests are fully offline, using captured live API fixtures under fixture/:

    - edge_store_list_example.json        Edge API store list (148 stores)
    - edge_search_pass1_example.json      Edge Pass 1 relevance search ("milk", 40 hits)
    - edge_search_pass2_example.json      Edge Pass 2 per-store pricing (10 products)
    - mobile_login_example.json           Mobile guest token auth response
    - mobile_stores_example.json          Mobile physical stores (150 stores, all MNW)
    - mobile_search_example.json          Mobile product search ("milk", 20 products)

Every assertion references real fixture values -- prices, SKUs, category names,
store counts, and field structures -- to verify the code correctly parses and
filters live API responses.

Where a code path has no live fixture coverage (e.g. the promotions array in
Edge Pass 2 products), that code path is documented as uncovered rather than
tested with synthetic data.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "combined"))

FIXTURE_DIR = SCRIPT_DIR / "fixture"


def _load_json(filename):
    """Load a JSON fixture file from the fixture directory."""
    with open(FIXTURE_DIR / filename, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


from newworld_api import (
    NON_FOOD_CATEGORIES,
    load_stores,
    find_nearby_stores,
    NewWorldEdgeAPI,
    NewWorldMobileAPI,
    NewWorldAPI,
    create_api,
)


class TestNonFoodCategories:
    """Tests for the NON_FOOD_CATEGORIES blacklist from newworld_api.py."""

    def test_non_food_categories_contains_expected_entries(self):
        assert "Dog" in NON_FOOD_CATEGORIES
        assert "Cat" in NON_FOOD_CATEGORIES
        assert "Baby & Toddler Food" in NON_FOOD_CATEGORIES
        assert "Dishwashing" in NON_FOOD_CATEGORIES
        assert "Baby Formula" in NON_FOOD_CATEGORIES
        assert "Laundry" in NON_FOOD_CATEGORIES

    def test_non_food_categories_excludes_food(self):
        assert "Milk" not in NON_FOOD_CATEGORIES
        assert "Meat" not in NON_FOOD_CATEGORIES
        assert "Vegetables" not in NON_FOOD_CATEGORIES
        assert "Beef" not in NON_FOOD_CATEGORIES

    def test_non_food_categories_is_set(self):
        assert isinstance(NON_FOOD_CATEGORIES, set)
        assert len(NON_FOOD_CATEGORIES) > 30


class TestNewWorldEdgeAPI:
    """Tests for NewWorldEdgeAPI using captured live API fixtures.

    Fixtures from generate_fixtures.py capture_edge_fixtures():
    - edge_store_list_example.json: GET /v1/edge/store (148 stores)
    - edge_search_pass1_example.json: POST products-index (40 hits for "milk")
    - edge_search_pass2_example.json: POST paginated/products (10 products, PRICE_ASC)
    """

    edge_store_list: dict
    edge_pass1: dict
    edge_pass2: dict

    def setup_method(self):
        self.edge_store_list = _load_json("edge_store_list_example.json")
        self.edge_pass1 = _load_json("edge_search_pass1_example.json")
        self.edge_pass2 = _load_json("edge_search_pass2_example.json")

    def test_authenticate_success(self):
        api = NewWorldEdgeAPI()
        mock_session = MagicMock()
        mock_session.cookies.get.return_value = "fake-jwt-token-12345"
        api.session = mock_session

        token = api.authenticate()
        assert token == "fake-jwt-token-12345"
        assert api.token == "fake-jwt-token-12345"

    def test_authenticate_fails_no_token(self):
        api = NewWorldEdgeAPI()
        mock_session = MagicMock()
        mock_session.cookies.get.return_value = None
        api.session = mock_session

        with pytest.raises(RuntimeError):
            api.authenticate()

    @patch("newworld_api.requests.get")
    def test_get_stores_returns_live_count(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.edge_store_list
        mock_get.return_value = mock_resp

        api = NewWorldEdgeAPI()
        api.token = "test-token"
        stores = api.get_stores()

        assert len(stores) == 148

        first = stores[0]
        assert first["id"] == "ef977d89-f3d8-4e8b-8a48-b895ded38646"
        assert first["name"] == "New World Papakura"
        assert first["banner"] == "MNW"
        assert first["latitude"] == -37.064268
        assert first["longitude"] == 174.941101
        assert first["region"] == "NI"
        assert first["clickAndCollect"] is True

    def test_pass1_filtering_keeps_all_food_hits(self):
        """Verify pass1 filtering logic keeps all 40 hits from the live Pass 1 fixture.

        All 40 hits for "milk" have _highlightResult with matchedWords on
        DisplayName/category2AndBrand, and category1=["Milk"] (not in
        NON_FOOD_CATEGORIES), so all are kept.
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
        hits = self.edge_pass1["hits"]
        product_ids = [h["productID"] for h in hits]

        assert len(product_ids) == 40
        assert len(set(product_ids)) == 40
        assert product_ids[0] == "5201479-EA-000"

    @patch("newworld_api.requests.post")
    def test_pass2_per_store_pricing_returns_live_products(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.edge_pass2
        mock_post.return_value = mock_resp

        api = NewWorldEdgeAPI()
        api.token = "test-token"
        products = api.pass2_per_store_pricing("store-123", "milk", ["prod-1"])

        assert len(products) == 10

        # Prices in cents: 317, 374, 374, 389, 483, 483, 604, 604, 720, 720
        prices = [p["singlePrice"]["price"] for p in products]
        assert prices == sorted(prices)

        first = products[0]
        assert first["productId"] == "5201800-EA-000"
        assert first["singlePrice"]["price"] == 317

    def test_pass2_empty_product_ids_returns_empty(self):
        api = NewWorldEdgeAPI()
        result = api.pass2_per_store_pricing("store-123", "milk", [])
        assert result == []

    def test_extract_price_all_products(self):
        """Verify extract_price converts all 10 products in Pass 2 fixture to dollars.

        All products have singlePrice.price in cents, no promotions key.
        Expected prices (from edge_search_pass2_example.json):
        317, 374, 374, 389, 483, 483, 604, 604, 720, 720 cents
        """
        expected_prices = [3.17, 3.74, 3.74, 3.89, 4.83, 4.83, 6.04, 6.04, 7.20, 7.20]
        prices = [NewWorldEdgeAPI.extract_price(p) for p in self.edge_pass2["products"]]
        assert prices == expected_prices

    def test_extract_price_null_returns_none(self):
        """Verify extract_price returns None when no price is available.

        No promotion fixture exists in the captured data, so the promo branch
        of extract_price is untested against live data.
        """
        assert NewWorldEdgeAPI.extract_price({"singlePrice": {}}) is None
        assert NewWorldEdgeAPI.extract_price({}) is None

    def test_get_product_name(self):
        product = self.edge_pass2["products"][0]
        assert NewWorldEdgeAPI.get_product_name(product) == "Standard Milk"

    def test_get_product_size(self):
        product = self.edge_pass2["products"][0]
        assert NewWorldEdgeAPI.get_product_size(product) == "1l"


class TestNewWorldMobileAPI:
    """Tests for NewWorldMobileAPI using captured live API fixtures.

    Fixtures from generate_fixtures.py capture_mobile_fixtures():
    - mobile_login_example.json: POST /mobile/user/login/guest (access_token, banner=MNW)
    - mobile_stores_example.json: GET /mobile/store/physical (150 stores, all MNW)
    - mobile_search_example.json: POST /mobile/ecomm-products/MNW/{id}/search (20 products)
    """

    mobile_login: dict
    mobile_stores: dict
    mobile_search: dict

    def setup_method(self):
        self.mobile_login = _load_json("mobile_login_example.json")
        self.mobile_stores = _load_json("mobile_stores_example.json")
        self.mobile_search = _load_json("mobile_search_example.json")

    def test_is_food_product_all_fixture_products_are_food(self):
        """Verify _is_food_product correctly classifies all 20 real Mobile API products as food.

        All 20 products in mobile_search_example.json have categories where
        categories[0] is a food category (e.g. "Milk", "Fresh Milk",
        "UHT Milk & Milk Powder") — none match the NON_FOOD_CATEGORIES blacklist.
        """
        api = NewWorldMobileAPI()
        products = self.mobile_search["products"]

        food_count = sum(1 for p in products if api._is_food_product(p))
        assert food_count == 20

        assert api._is_food_product(products[0]) is True
        assert products[0]["categories"] == ["Milk", "Fresh Milk"]

    def test_is_food_product_filters_pet_food(self):
        """Verify _is_food_product excludes products whose category1 is in NON_FOOD_CATEGORIES.

        Uses inline product dicts with category1='Dog' / 'Cat' — these are
        simple classifier inputs (no API retrieval involved), allowed per
        the testing policy.
        """
        api = NewWorldMobileAPI()
        assert api._is_food_product({"categories": ["Dog"]}) is False
        assert api._is_food_product({"categories": ["Cat"]}) is False
        assert api._is_food_product({"categories": ["Dishwashing"]}) is False
        assert api._is_food_product({"categories": ["Milk"]}) is True
        # No categories → treated as food
        assert api._is_food_product({"categories": []}) is True
        assert api._is_food_product({"categories": None}) is True
        assert api._is_food_product({}) is True

    def test_ensure_token(self):
        """Verify _ensure_token stores the access_token from the live mobile login response.

        Mocks the scraper POST against mobile_login_example.json fixture.
        The fixture contains a real JWT access_token (expires_in: 1800 seconds).
        """
        api = NewWorldMobileAPI()
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

        Mocks the scraper POST/GET to return mobile_search_example.json (20 products).
        With food_only=True (default), all 20 are kept (all have food categories).
        """
        api = NewWorldMobileAPI()
        api._token = "test-token"

        mock_scraper = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self.mobile_search
        mock_scraper.post.return_value = mock_resp
        api.scraper = mock_scraper

        products = api.search_products("store-123", "milk")
        assert products is not None

        assert len(products) == 20

        first = products[0]
        assert first["productId"] == "5201479-EA-000"
        assert first["name"] == "Standard Milk"
        assert first["price"] == 483
        assert first["unitPrice"] == "$2.42/1L"
        assert first["units"] == "2l"

    @patch("newworld_api.cloudscraper.create_scraper")
    def test_get_stores_returns_150_stores(self, mock_create):
        """Verify get_stores returns 150 stores from the live Mobile API fixture.

        Mocks the login + GET /mobile/store/physical to return
        mobile_stores_example.json (150 stores, all MNW).
        Returns a dict keyed by store ID.
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

        api = NewWorldMobileAPI()
        stores = api.get_stores()

        assert len(stores) == 150

        first_store = list(stores.values())[0]
        assert first_store["id"] == "ef977d89-f3d8-4e8b-8a48-b895ded38646"
        assert first_store["name"] == "New World Papakura"
        assert first_store["banner"] == "MNW"
        assert first_store["latitude"] == -37.064268

    def test_extract_price_mobile(self):
        """Verify MobileAPI.extract_price converts cents to dollars from real fixture."""
        product = self.mobile_search["products"][0]
        # price=483 cents -> 4.83 dollars
        assert NewWorldMobileAPI.extract_price(product) == 4.83

    def test_get_product_name_mobile(self):
        product = self.mobile_search["products"][0]
        assert NewWorldMobileAPI.get_product_name(product) == "Standard Milk"

    def test_get_product_size_mobile(self):
        product = self.mobile_search["products"][0]
        # Mobile API product has no 'size' or 'packageSize' field → returns ""
        assert NewWorldMobileAPI.get_product_size(product) == ""


class TestNewWorldAPIUnified:
    """Tests for the NewWorldAPI unified wrapper and create_api factory."""

    def test_create_api_edge(self):
        api = create_api("edge")
        assert api.backend == "edge"
        assert isinstance(api.client, NewWorldEdgeAPI)

    def test_create_api_mobile(self):
        api = create_api("mobile")
        assert api.backend == "mobile"
        assert isinstance(api.client, NewWorldMobileAPI)

    def test_unified_get_stores_edge(self):
        """Verify NewWorldAPI.get_stores() returns list directly for edge backend."""
        api = create_api("edge")
        mock_client = MagicMock(spec=NewWorldEdgeAPI)
        mock_client.get_stores.return_value = [{"id": "test-id"}]
        api.client = mock_client
        result = api.get_stores()
        assert result == [{"id": "test-id"}]
        assert isinstance(result, list)

    def test_unified_get_stores_mobile(self):
        """Verify NewWorldAPI.get_stores() converts mobile dict to list correctly."""
        api = create_api("mobile")
        mock_client = MagicMock()
        mock_client.get_stores.return_value = {"store-1": {"id": "store-1"}}
        api.client = mock_client
        result = api.get_stores()
        assert len(result) == 1
        assert result[0]["id"] == "store-1"
