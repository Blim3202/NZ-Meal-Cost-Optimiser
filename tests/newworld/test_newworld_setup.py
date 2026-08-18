"""
Unit tests for New World setup pipeline (newworld_setup.py).

Tests store pipeline helper functions using captured live API fixtures:

    - fixture/edge_store_list_example.json    -- 148 Edge API stores with physicalAddress, lat/lon
    - fixture/mobile_stores_example.json       -- 150 Mobile API physical stores (MNW banner)
    - fixture/mobile_login_example.json        -- Mobile guest login response

New World has NO store_finder source (no __NEXT_DATA__ in website store-finder),
so only "edge" and "mobile" sources are tested.

All assertions reference real fixture values to verify the parsing, schema
enforcement, coordinate filtering, and store-fetch dispatch logic.
"""

import argparse
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixture"


def _load_json(filename):
    """Load a JSON fixture file from the fixture directory."""
    with open(FIXTURE_DIR / filename, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


from tools.newworld.newworld_setup import (
    EXPECTED_COLUMNS,
    _parse_cleaned,
    _enforce_schema,
    fetch_stores,
    fetch_stores_from_edge_api,
    fetch_stores_from_mobile_api,
    clean_stores,
    run_full_setup,
)


class TestParseCleaned:
    """Tests for _parse_cleaned argument parser helper."""

    def test_parse_cleaned_true_values(self):
        assert _parse_cleaned("true")
        assert _parse_cleaned("True")
        assert _parse_cleaned("1")
        assert _parse_cleaned("yes")

    def test_parse_cleaned_false_values(self):
        assert not _parse_cleaned("false")
        assert not _parse_cleaned("False")
        assert not _parse_cleaned("0")
        assert not _parse_cleaned("no")

    def test_parse_cleaned_invalid(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_cleaned("maybe")


class TestEnforceSchema:
    """Tests for _enforce_schema DataFrame schema enforcement."""

    def test_enforce_schema_adds_missing_columns(self):
        df = pd.DataFrame([{"store_id": "123", "name": "Test Store"}])
        enforced = _enforce_schema(df)

        assert list(enforced.columns) == EXPECTED_COLUMNS
        assert len(enforced) == 1
        assert enforced.iloc[0]["banner"] == "MNW"
        assert not enforced.iloc[0]["click_and_collect"]
        assert not enforced.iloc[0]["delivery"]
        assert enforced.iloc[0]["city"] == ""
        assert enforced.iloc[0]["region"] == ""

    def test_enforce_schema_preserves_existing(self):
        df = pd.DataFrame([{
            "store_id": "abc",
            "name": "My Store",
            "banner": "CUSTOM",
            "click_and_collect": True,
            "extra_col": "should be dropped",
        }])
        enforced = _enforce_schema(df)

        assert list(enforced.columns) == EXPECTED_COLUMNS
        assert enforced.iloc[0]["store_id"] == "abc"
        assert enforced.iloc[0]["name"] == "My Store"
        assert enforced.iloc[0]["banner"] == "CUSTOM"
        assert enforced.iloc[0]["click_and_collect"]


class TestCleanStores:
    """Tests for clean_stores coordinate filtering."""

    def test_clean_stores_drops_nan_latitude(self):
        df = pd.DataFrame([
            {"store_id": "1", "name": "A", "latitude": -36.8, "longitude": 174.7},
            {"store_id": "2", "name": "B", "latitude": None, "longitude": None},
        ])

        cleaned = clean_stores(df, cleaned=True, verbose=False)
        assert len(cleaned) == 1
        assert cleaned.iloc[0]["store_id"] == "1"

    def test_clean_stores_keeps_all_when_not_cleaned(self):
        df = pd.DataFrame([
            {"store_id": "1", "name": "A", "latitude": -36.8, "longitude": 174.7},
            {"store_id": "2", "name": "B", "latitude": None, "longitude": None},
        ])

        kept = clean_stores(df, cleaned=False, verbose=False)
        assert len(kept) == 2
        assert kept.iloc[0]["store_id"] == "1"
        assert kept.iloc[1]["store_id"] == "2"


class TestFetchStoresFromEdgeAPI:
    """Tests for fetch_stores_from_edge_api using edge_store_list_example.json.

    Fixture source: generate_fixtures.py capture_edge_fixtures()
    - endpoint: GET https://api-prod.newworld.co.nz/v1/edge/store
    - store_count: 148
    - first_store: New World Papakura, id=ef977d89-f3d8-4e8b-8a48-b895ded38646
    """

    edge_stores: dict

    def setup_method(self):
        self.edge_stores = _load_json("edge_store_list_example.json")

    @patch("tools.newworld.newworld_setup.get_website_jwt")
    @patch("tools.newworld.newworld_setup.requests.get")
    def test_fetch_stores_from_edge_api_returns_148_stores(self, mock_get, mock_jwt):
        mock_jwt.return_value = "fake-jwt-token"
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.edge_stores
        mock_get.return_value = mock_resp

        df = fetch_stores_from_edge_api(verbose=False)

        assert len(df) == 148
        assert list(df.columns) == EXPECTED_COLUMNS

        first = df.iloc[0]
        assert first["store_id"] == "ef977d89-f3d8-4e8b-8a48-b895ded38646"
        assert first["name"] == "New World Papakura"
        assert first["address"] == "29-31 East Street, Auckland, 2110"
        assert first["latitude"] == -37.064268
        assert first["longitude"] == 174.941101
        assert first["region"] == "NI"
        assert first["banner"] == "MNW"
        assert first["click_and_collect"]

    @patch("tools.newworld.newworld_setup.get_website_jwt")
    @patch("tools.newworld.newworld_setup.requests.get")
    def test_fetch_stores_edge_uses_physical_address_city(self, mock_get, mock_jwt):
        mock_jwt.return_value = "fake-jwt-token"
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.edge_stores
        mock_get.return_value = mock_resp

        df = fetch_stores_from_edge_api(verbose=False)
        first = df.iloc[0]
        # city derived from physicalAddress.cityName = "Auckland"
        assert first["city"] == "Auckland"

    @patch("tools.newworld.newworld_setup.get_website_jwt")
    @patch("tools.newworld.newworld_setup.requests.get")
    def test_fetch_stores_edge_all_have_coordinates(self, mock_get, mock_jwt):
        mock_jwt.return_value = "fake-jwt-token"
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.edge_stores
        mock_get.return_value = mock_resp

        df = fetch_stores_from_edge_api(verbose=False)
        assert bool(df["latitude"].notna().all())
        assert bool(df["longitude"].notna().all())

        coords = list(zip(df["latitude"], df["longitude"]))
        unique_coords = set(coords)
        assert len(unique_coords) > 10

    @patch("tools.newworld.newworld_setup.get_website_jwt")
    @patch("tools.newworld.newworld_setup.requests.get")
    def test_fetch_stores_edge_all_banner_mnw(self, mock_get, mock_jwt):
        mock_jwt.return_value = "fake-jwt-token"
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.edge_stores
        mock_get.return_value = mock_resp

        df = fetch_stores_from_edge_api(verbose=False)
        assert (df["banner"] == "MNW").all()

    @patch("tools.newworld.newworld_setup.get_website_jwt")
    @patch("tools.newworld.newworld_setup.requests.get")
    def test_fetch_stores_edge_regions_present(self, mock_get, mock_jwt):
        mock_jwt.return_value = "fake-jwt-token"
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.edge_stores
        mock_get.return_value = mock_resp

        df = fetch_stores_from_edge_api(verbose=False)
        regions = set(df["region"].unique())
        assert "NI" in regions
        assert "SI" in regions


class TestFetchStoresFromMobileAPI:
    """Tests for fetch_stores_from_mobile_api using mobile_stores_example.json.

    Fixture source: generate_fixtures.py capture_mobile_fixtures()
    - endpoint: GET https://api-prod.prod.fsniwaikato.kiwi/prod/mobile/store/physical
    - banner filter: MNW
    - store_count: 150 (all MNW banner)
    - first_store: New World Papakura, id=ef977d89-f3d8-4e8b-8a48-b895ded38646
    """

    mobile_stores: dict

    def setup_method(self):
        self.mobile_stores = _load_json("mobile_stores_example.json")

    @patch("tools.newworld.newworld_setup.cloudscraper.create_scraper")
    def test_fetch_stores_from_mobile_api_returns_150_stores(self, mock_create):
        mock_scraper = MagicMock()
        login_resp = MagicMock()
        login_resp.json.return_value = _load_json("mobile_login_example.json")
        stores_resp = MagicMock()
        stores_resp.status_code = 200
        stores_resp.json.return_value = self.mobile_stores
        mock_scraper.post.return_value = login_resp
        mock_scraper.get.return_value = stores_resp
        mock_create.return_value = mock_scraper

        df = fetch_stores_from_mobile_api(verbose=False)

        assert len(df) == 150
        assert list(df.columns) == EXPECTED_COLUMNS

        first = df.iloc[0]
        assert first["store_id"] == "ef977d89-f3d8-4e8b-8a48-b895ded38646"
        assert first["name"] == "New World Papakura"
        assert first["banner"] == "MNW"
        assert first["latitude"] == -37.064268
        assert first["longitude"] == 174.941101
        # Mobile API setup hardcodes region as "" (not read from store data)
        assert first["region"] == ""
        assert first["click_and_collect"]

    @patch("tools.newworld.newworld_setup.cloudscraper.create_scraper")
    def test_fetch_stores_mobile_all_banner_mnw(self, mock_create):
        mock_scraper = MagicMock()
        login_resp = MagicMock()
        login_resp.json.return_value = _load_json("mobile_login_example.json")
        stores_resp = MagicMock()
        stores_resp.status_code = 200
        stores_resp.json.return_value = self.mobile_stores
        mock_scraper.post.return_value = login_resp
        mock_scraper.get.return_value = stores_resp
        mock_create.return_value = mock_scraper

        df = fetch_stores_from_mobile_api(verbose=False)
        assert (df["banner"] == "MNW").all()

    @patch("tools.newworld.newworld_setup.cloudscraper.create_scraper")
    def test_fetch_stores_mobile_regions_present(self, mock_create):
        """Mobile API setup hardcodes region as empty — verify no crash and region column exists."""
        mock_scraper = MagicMock()
        login_resp = MagicMock()
        login_resp.json.return_value = _load_json("mobile_login_example.json")
        stores_resp = MagicMock()
        stores_resp.status_code = 200
        stores_resp.json.return_value = self.mobile_stores
        mock_scraper.post.return_value = login_resp
        mock_scraper.get.return_value = stores_resp
        mock_create.return_value = mock_scraper

        df = fetch_stores_from_mobile_api(verbose=False)
        # region column exists (hardcoded empty in mobile setup)
        assert "region" in df.columns
        # All regions are empty string (mobile API doesn't populate region in setup)
        assert (df["region"] == "").all()


class TestFetchStoresDispatch:
    """Tests for fetch_stores() source dispatch.

    New World supports only "edge" and "mobile" sources — NOT "store_finder".
    """

    @patch("tools.newworld.newworld_setup.fetch_stores_from_edge_api")
    def test_fetch_stores_edge_dispatch(self, mock_fetch):
        mock_fetch.return_value = pd.DataFrame(columns=EXPECTED_COLUMNS)
        df = fetch_stores(source="edge", verbose=False)
        mock_fetch.assert_called_once()
        assert list(df.columns) == EXPECTED_COLUMNS

    @patch("tools.newworld.newworld_setup.fetch_stores_from_mobile_api")
    def test_fetch_stores_mobile_dispatch(self, mock_fetch):
        mock_fetch.return_value = pd.DataFrame(columns=EXPECTED_COLUMNS)
        df = fetch_stores(source="mobile", verbose=False)
        mock_fetch.assert_called_once()
        assert list(df.columns) == EXPECTED_COLUMNS

    @patch("tools.newworld.newworld_setup.fetch_stores_from_store_finder", create=True)
    def test_fetch_stores_store_finder_raises_valueerror(self, mock_fetch):
        """New World has no store_finder source — verify ValueError is raised."""
        with pytest.raises(ValueError):
            fetch_stores(source="store_finder", verbose=False)
