"""
Unit tests for Woolworths NZ Store Setup (woolworths_setup.py).

Tests verify:
    1. clean_null() handles None, empty strings, and valid values.
    2. merge_stores() performs a correct left-join between the
       fixture store choices CSV (cookies_example1.csv) and the
       fixture store data CSV (store_data_fixture.csv).
    3. The cleaned=False merge keeps all stores.
    4. The cleaned=True merge drops stores without coordinates.
    5. The merged CSV output has the expected column structure.

All data is loaded from the fixture directory produced by
generate_fixtures.py — no live network calls during tests.

Fixture data (3 stores, all from the Nelson/South Island region):
    cookies_example1.csv (pickup choices):
        id=4166071 -> Nelson Junction Woolworths
        id=1225552 -> Nelson Woolworths
        id=2810937 -> Trafalgar Park Woolworths

    store_data_fixture.csv (CDX site data):
        SiteDataID=4166071 -> lat=-41.2977069, lon=173.241518  (has coords)
        SiteDataID=1225552 -> lat=-41.2727, lon=173.2773        (has coords)
        SiteDataID=2810937 -> lat=-41.2702, lon=173.2815        (has coords)

Since all 3 stores have coordinates, cleaned=True and cleaned=False
both return 3 rows. A separate edge-case test verifies the cleaning
logic by using a modified fixture.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

# Make the woolworths scripts directory and combined helpers importable.
SCRIPT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(SCRIPT_DIR))  # scripts/woolworths
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "combined"))  # shared utils

FIXTURE_DIR = SCRIPT_DIR / "fixture"

# Patch targets for woolworths_setup module
FIX_CHOICES_CSV = FIXTURE_DIR / "cookies_example1.csv"
FIX_STORE_DATA_CSV = FIXTURE_DIR / "store_data_fixture.csv"
FIX_STORE_DATA_JSON = FIXTURE_DIR / "store_data_example.json"


class TestCleanNull(unittest.TestCase):
    """Tests for woolworths_setup.clean_null()."""

    def setUp(self):
        from woolworths_setup import clean_null
        self.clean_null = clean_null

    def test_none_returns_empty_string(self):
        self.assertEqual(self.clean_null(None), "")

    def test_empty_string_returns_empty_string(self):
        self.assertEqual(self.clean_null(""), "")

    def test_whitespace_only_returns_empty_string(self):
        self.assertEqual(self.clean_null("   "), "")

    def test_valid_value_returns_stringified(self):
        """A non-empty value is returned as-is (stringified if needed)."""
        self.assertEqual(self.clean_null("Hello"), "Hello")
        self.assertEqual(self.clean_null(123), "123")


class TestMergeStores(unittest.TestCase):
    """Tests for woolworths_setup.merge_stores() using REAL fixture files.

    The fixture data (captured from live APIs) has 3 stores, all with
    valid coordinates. Therefore:
        - cleaned=True  -> 3 stores (all have coords)
        - cleaned=False -> 3 stores (same)
    """

    def _run_merge(self, cleaned, temp_csv=None):
        """Run merge_stores against fixture files.

        Args:
            cleaned: bool — whether to drop stores without coordinates.
            temp_csv: optional Path for the output CSV (avoids polluting
                      the fixture directory).

        Returns the merged DataFrame.
        """
        if temp_csv is None:
            temp_csv = FIXTURE_DIR / "_merge_test_output.csv"

        with patch("woolworths_setup.CSV_CHOICES", FIX_CHOICES_CSV), \
             patch("woolworths_setup.CSV_DATA", FIX_STORE_DATA_CSV), \
             patch("woolworths_setup.CSV_MERGED", temp_csv):
            from woolworths_setup import merge_stores
            merged = merge_stores(cleaned=cleaned)

        # Clean up the temp output file.
        if temp_csv.exists():
            temp_csv.unlink()

        return merged

    def test_cleaned_merge_keeps_all_with_coords(self):
        """cleaned=True with the fixture (all stores have coords) keeps all 3.

        Fixture: all 3 stores have valid lat/lon.
        """
        merged = self._run_merge(cleaned=True)
        self.assertEqual(len(merged), 3)

    def test_unpadded_merge_keeps_all(self):
        """cleaned=False keeps all 3 stores from the left-join."""
        merged = self._run_merge(cleaned=False)
        self.assertEqual(len(merged), 3)

    def test_merge_has_expected_columns(self):
        """The merged DataFrame must have id, name, address, latitude, longitude."""
        merged = self._run_merge(cleaned=False)
        expected = {"id", "name", "address", "latitude", "longitude"}
        self.assertTrue(expected.issubset(set(merged.columns)))

    def test_merge_preserves_store_names(self):
        """The merged DataFrame must contain the real store names from the fixture."""
        merged = self._run_merge(cleaned=False)
        names = set(merged["name"].tolist())
        self.assertIn("Nelson Junction Woolworths", names)
        self.assertIn("Nelson Woolworths", names)
        self.assertIn("Trafalgar Park Woolworths", names)

    def test_merge_preserves_site_data_ids(self):
        """The merged 'id' column must match the fixture choices CSV ids."""
        merged = self._run_merge(cleaned=False)
        expected_ids = {"4166071", "1225552", "2810937"}
        actual_ids = set(merged["id"].astype(str).tolist())
        self.assertEqual(actual_ids, expected_ids)

    def test_merge_joined_coordinates_correct(self):
        """The merged latitude/longitude must match the CDX data for store 4166071."""
        merged = self._run_merge(cleaned=False)
        row = merged[merged["id"].astype(str) == "4166071"].iloc[0]
        self.assertAlmostEqual(float(row["latitude"]), -41.2977069, places=4)
        self.assertAlmostEqual(float(row["longitude"]), 173.241518, places=4)


class TestMergeStoresCleaningLogic(unittest.TestCase):
    """Tests for the cleaned=True coordinate-filtering logic.

    The real fixtures have all stores with coordinates, so we create a
    temporary modified CSV where one store has empty coordinates, to
    verify the cleaning logic works on real data.
    """

    def test_cleaned_drops_missing_coords(self):
        """cleaned=True must drop stores with empty latitude/longitude.

        We create a temp copy of the fixture store data CSV where the
        second store's latitude and longitude are replaced with NaN,
        then verify that cleaned=True drops it while cleaned=False keeps it.
        """
        import numpy as np

        # Read the real fixture CSV and blank out one store's coords.
        df = pd.read_csv(FIX_STORE_DATA_CSV)
        # Use numpy NaN (not empty string) to avoid pandas dtype coercion
        # errors when setting on a float64 column.
        df.loc[df["SiteDataID"].astype(str) == "1225552", "latitude"] = np.nan
        df.loc[df["SiteDataID"].astype(str) == "1225552", "longitude"] = np.nan

        temp_data_csv = FIXTURE_DIR / "_temp_store_data.csv"
        temp_merged_csv = FIXTURE_DIR / "_temp_merged.csv"
        df.to_csv(temp_data_csv, index=False, encoding="utf-8")

        try:
            with patch("woolworths_setup.CSV_CHOICES", FIX_CHOICES_CSV), \
                 patch("woolworths_setup.CSV_DATA", temp_data_csv), \
                 patch("woolworths_setup.CSV_MERGED", temp_merged_csv):
                from woolworths_setup import merge_stores

                # cleaned=True should drop the store with blank coords
                merged_clean = merge_stores(cleaned=True)
                self.assertEqual(len(merged_clean), 2)
                self.assertNotIn("1225552",
                                 merged_clean["id"].astype(str).tolist())

                # cleaned=False should keep all 3
                merged_full = merge_stores(cleaned=False)
                self.assertEqual(len(merged_full), 3)
        finally:
            for p in [temp_data_csv, temp_merged_csv]:
                if p.exists():
                    p.unlink()


class TestMergeCsvOutput(unittest.TestCase):
    """Verify the merged CSV written by merge_stores has the expected columns."""

    def test_merged_csv_has_expected_columns(self):
        """The output CSV must have 'id', 'name', 'address', 'latitude', 'longitude'.

        These are the columns consumed by the optimizer and API modules.
        """
        temp_csv = FIXTURE_DIR / "_merge_col_test.csv"

        with patch("woolworths_setup.CSV_CHOICES", FIX_CHOICES_CSV), \
             patch("woolworths_setup.CSV_DATA", FIX_STORE_DATA_CSV), \
             patch("woolworths_setup.CSV_MERGED", temp_csv):
            from woolworths_setup import merge_stores
            merge_stores(cleaned=False)

        df = pd.read_csv(temp_csv)
        for col in ["id", "name", "address", "latitude", "longitude"]:
            self.assertIn(col, df.columns)

        if temp_csv.exists():
            temp_csv.unlink()


class TestSetupDataIntegration(unittest.TestCase):
    """Integration test: verify the fixture store_data_example.json and
    store_data_fixture.csv are consistent with the real captured data.

    This ensures the fixture files captured by generate_fixtures.py are
    internally coherent — the JSON and CSV describe the same stores
    with the same IDs and coordinates.
    """

    @patch("woolworths_api.STORE_JSON", FIX_STORE_DATA_JSON)
    def test_fixture_json_matches_csv(self):
        """The store IDs and coordinates in store_data_example.json must
        match those in store_data_fixture.csv.

        Note: pandas reads SiteDataID from the CSV as int64 (e.g. 4166071),
        while the JSON stores it as a string ('4166071'). We normalize
        to str for comparison.
        """
        from woolworths_api import _load_store_mapping

        mapping = _load_store_mapping()
        df = pd.read_csv(FIX_STORE_DATA_CSV)
        # Normalize SiteDataID to string for consistent comparison.
        df["SiteDataID"] = df["SiteDataID"].astype(str)

        # The JSON has 5 sites; the CSV has 3 (subset).
        # All 3 CSV SiteDataIDs must be present in the JSON mapping.
        self.assertEqual(len(mapping), 5)
        self.assertEqual(len(df), 3)

        for _, row in df.iterrows():
            site_id = row["SiteDataID"]
            self.assertIn(site_id, mapping,
                          f"SiteDataID {site_id} from CSV not in JSON mapping")

            json_entry = mapping[site_id]
            csv_lat = float(row["latitude"])
            csv_lon = float(row["longitude"])
            self.assertAlmostEqual(json_entry["lat"], csv_lat, places=4)
            self.assertAlmostEqual(json_entry["lon"], csv_lon, places=4)

    @patch("woolworths_api.STORE_JSON", FIX_STORE_DATA_JSON)
    def test_all_stores_have_valid_coords(self):
        """Every store in the fixture JSON must have non-null coordinates."""
        from woolworths_api import _load_store_mapping
        mapping = _load_store_mapping()
        for pid, info in mapping.items():
            self.assertIsNotNone(info["lat"],
                                 f"Store {pid} has null latitude")
            self.assertIsNotNone(info["lon"],
                                 f"Store {pid} has null longitude")


if __name__ == "__main__":
    unittest.main()
