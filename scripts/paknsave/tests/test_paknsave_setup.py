"""
Unit tests for Pak'nSave setup pipeline (paknsave_setup.py).

Tests store pipeline helper functions using captured live API fixtures:

    - fixture/edge_store_list_example.json    -- 57 Edge API stores with physicalAddress, lat/lon
    - fixture/mobile_stores_example.json      -- 60 Mobile API physical stores
    - fixture/store_finder_page_example.json  -- Website __NEXT_DATA__ with 60 stores

All assertions reference real fixture values to verify the parsing, schema
enforcement, coordinate filtering, and store-fetch dispatch logic.
"""

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "combined"))

FIXTURE_DIR = SCRIPT_DIR / "fixture"


def _load_json(filename):
    """Load a JSON fixture file from the fixture directory."""
    with open(FIXTURE_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


def _wrap_next_data(data):
    """Wrap a __NEXT_DATA__ dict in the HTML script tag format the scraper expects.

    The store-finder page contains a <script id="__NEXT_DATA__" type="application/json">
    tag with the JSON payload embedded. fetch_stores_from_store_finder() uses a regex
    to extract this payload from the HTML response text.
    """
    json_str = json.dumps(data)
    return f'<script id="__NEXT_DATA__" type="application/json">{json_str}</script>'


from paknsave_setup import (
    EXPECTED_COLUMNS,
    _parse_cleaned,
    _enforce_schema,
    fetch_stores,
    fetch_stores_from_edge_api,
    fetch_stores_from_mobile_api,
    fetch_stores_from_store_finder,
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
        assert enforced.iloc[0]["banner"] == "PNS"
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
    - endpoint: GET {EDGE_BASE}/store
    - store_count: 57
    - first_store: PAK'nSAVE Te Awamutu, id=3bb30799-82ce-4648-8c02-5113228963ed
    """

    edge_stores: dict

    def setup_method(self):
        self.edge_stores = _load_json("edge_store_list_example.json")

    @patch("paknsave_setup.get_website_jwt")
    @patch("paknsave_setup.requests.get")
    def test_fetch_stores_from_edge_api_returns_57_stores(self, mock_get, mock_jwt):
        mock_jwt.return_value = "fake-jwt-token"
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.edge_stores
        mock_get.return_value = mock_resp

        df = fetch_stores_from_edge_api(verbose=False)

        assert len(df) == 57
        assert list(df.columns) == EXPECTED_COLUMNS

        first = df.iloc[0]
        assert first["store_id"] == "3bb30799-82ce-4648-8c02-5113228963ed"
        assert first["name"] == "PAK'nSAVE Te Awamutu"
        assert first["address"] == "670 Cambridge Road, Te Awamutu, 3800"
        assert first["latitude"] == -38.008101
        assert first["longitude"] == 175.340102
        assert first["region"] == "NI"
        assert first["banner"] == "PNS"
        assert first["click_and_collect"]

    @patch("paknsave_setup.get_website_jwt")
    @patch("paknsave_setup.requests.get")
    def test_fetch_stores_edge_uses_physical_address(self, mock_get, mock_jwt):
        mock_jwt.return_value = "fake-jwt-token"
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.edge_stores
        mock_get.return_value = mock_resp

        df = fetch_stores_from_edge_api(verbose=False)
        first = df.iloc[0]
        assert first["city"] == "Te Awamutu"

    @patch("paknsave_setup.get_website_jwt")
    @patch("paknsave_setup.requests.get")
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


class TestFetchStoresFromStoreFinder:
    """Tests for fetch_stores_from_store_finder using store_finder_page_example.json.

    Fixture source: generate_fixtures.py capture_store_finder_fixtures()
    - endpoint: GET https://www.paknsave.co.nz/store-finder
    - contentstackStores: 60 entries mapping URL -> store_id
    - regionStoreGroupings: 60 stores across northIsland (47) and southIsland (13)
    """

    store_finder_data: dict

    def setup_method(self):
        self.store_finder_data = _load_json("store_finder_page_example.json")

    @patch("paknsave_setup.cloudscraper.create_scraper")
    def test_fetch_stores_from_store_finder_returns_60_stores(self, mock_create):
        mock_scraper = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = _wrap_next_data(self.store_finder_data)
        mock_scraper.get.return_value = mock_resp
        mock_create.return_value = mock_scraper

        df = fetch_stores_from_store_finder(verbose=False)

        assert len(df) == 60
        assert list(df.columns) == EXPECTED_COLUMNS

        first = df.iloc[0]
        assert first["store_id"] is not None
        assert isinstance(first["name"], str)
        assert first["banner"] == "PNS"

        for lat in df["latitude"]:
            assert pd.isna(lat) or isinstance(lat, float)

    @patch("paknsave_setup.cloudscraper.create_scraper")
    def test_store_finder_maps_url_to_store_id(self, mock_create):
        mock_scraper = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = _wrap_next_data(self.store_finder_data)
        mock_scraper.get.return_value = mock_resp
        mock_create.return_value = mock_scraper

        df = fetch_stores_from_store_finder(verbose=False)

        cs_stores = self.store_finder_data["props"]["pageProps"]["contentstackStores"]
        expected_url = cs_stores[0]["url"]
        expected_store_id = cs_stores[0]["store_id"]

        matching = df[df["store_id"] == expected_store_id]
        assert len(matching) == 1
        assert matching.iloc[0]["name"] == "Albany"

    @patch("paknsave_setup.cloudscraper.create_scraper")
    def test_store_finder_region_labels(self, mock_create):
        mock_scraper = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = _wrap_next_data(self.store_finder_data)
        mock_scraper.get.return_value = mock_resp
        mock_create.return_value = mock_scraper

        df = fetch_stores_from_store_finder(verbose=False)
        regions = set(df["region"].unique())
        assert "NI" in regions
        assert "SI" in regions

        ni_stores = df[df["region"] == "NI"]
        assert len(ni_stores) > 0

        si_stores = df[df["region"] == "SI"]
        assert len(si_stores) > 0

    @patch("paknsave_setup.cloudscraper.create_scraper")
    def test_store_finder_address_extraction(self, mock_create):
        mock_scraper = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = _wrap_next_data(self.store_finder_data)
        mock_scraper.get.return_value = mock_resp
        mock_create.return_value = mock_scraper

        df = fetch_stores_from_store_finder(verbose=False)

        cs_stores = self.store_finder_data["props"]["pageProps"]["contentstackStores"]
        expected_store_id = cs_stores[0]["store_id"]
        matching = df[df["store_id"] == expected_store_id]
        assert len(matching) == 1

        row = matching.iloc[0]
        assert row["address"] == "Don McKinnon Drive, Albany, Auckland, 0632"
        assert row["city"] == "Don McKinnon Drive"


class TestFetchStoresDispatch:
    """Tests for fetch_stores() source dispatch."""

    @patch("paknsave_setup.fetch_stores_from_edge_api")
    def test_fetch_stores_edge_dispatch(self, mock_fetch):
        mock_fetch.return_value = pd.DataFrame(columns=EXPECTED_COLUMNS)
        df = fetch_stores(source="edge", verbose=False)
        mock_fetch.assert_called_once()
        assert list(df.columns) == EXPECTED_COLUMNS

    @patch("paknsave_setup.fetch_stores_from_store_finder")
    def test_fetch_stores_store_finder_dispatch(self, mock_fetch):
        mock_fetch.return_value = pd.DataFrame(columns=EXPECTED_COLUMNS)
        df = fetch_stores(source="store_finder", verbose=False)
        mock_fetch.assert_called_once()
        assert list(df.columns) == EXPECTED_COLUMNS

    @patch("paknsave_setup.fetch_stores_from_mobile_api")
    def test_fetch_stores_mobile_dispatch(self, mock_fetch):
        mock_fetch.return_value = pd.DataFrame(columns=EXPECTED_COLUMNS)
        df = fetch_stores(source="mobile", verbose=False)
        mock_fetch.assert_called_once()
        assert list(df.columns) == EXPECTED_COLUMNS

    def test_fetch_stores_invalid_source(self):
        with pytest.raises(ValueError):
            fetch_stores(source="invalid", verbose=False)
