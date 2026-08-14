"""
Unit tests for Pak'nSave Mobile Optimizer CLI (paknsave_optimizer_mobile.py).

Tests the main() function's argument parsing: positional address/dish args,
--requery flag parsing, --distance flag parsing, and correct forwarding of
parsed arguments to the shared foodstuffs_querier_mobile pipeline.

The shared foodstuffs_querier_mobile and optimise functions are mocked to avoid
network calls, but the argument parsing logic in main() is exercised for real
with various sys.argv combinations.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "combined"))


class TestPaknSaveOptimizerMobileCLI:
    """Tests for Mobile API optimizer main() argument parsing and dispatch."""

    DEFAULT_ADDRESS = "588 Chapel Road, East Tāmaki, Auckland 2016"
    DEFAULT_DISH = "spaghetti bolognese"

    @patch("paknsave_optimizer_mobile.foodstuffs_querier_mobile")
    @patch("paknsave_optimizer_mobile.optimise")
    def test_main_defaults(self, mock_optimise, mock_query):
        """Verify main() uses correct defaults when no CLI args are provided.

        With no positional arguments, main() should use:
        - address: "588 Chapel Road, East Tāmaki, Auckland 2016"
        - dish: "spaghetti bolognese"
        - requery: True (default)
        - max_dist_km: 5 (default)
        """
        mock_query.return_value = True
        import paknsave_optimizer_mobile

        with patch.object(sys, "argv", ["paknsave_optimizer_mobile.py"]):
            paknsave_optimizer_mobile.main()

        mock_query.assert_called_once()
        args, kwargs = mock_query.call_args
        assert args[4] == self.DEFAULT_ADDRESS
        assert args[5] == self.DEFAULT_DISH
        assert args[6] is True  # requery=True
        assert kwargs.get("max_dist_km") == 5

        mock_optimise.assert_called_once()
        opt_args, opt_kwargs = mock_optimise.call_args
        assert opt_args[0] == self.DEFAULT_DISH
        assert opt_kwargs.get("company") == "PaknSave"

    @patch("paknsave_optimizer_mobile.foodstuffs_querier_mobile")
    @patch("paknsave_optimizer_mobile.optimise")
    def test_main_custom_args(self, mock_optimise, mock_query):
        """Verify main() correctly parses custom address, ingredient, requery, and distance.

        argv: address="Custom Address", dish="milk", --requery=false, --distance=10
        """
        mock_query.return_value = True
        import paknsave_optimizer_mobile

        with patch.object(sys, "argv", [
            "paknsave_optimizer_mobile.py",
            "Custom Address",
            "milk",
            "--requery", "false",
            "--distance", "10",
        ]):
            paknsave_optimizer_mobile.main()

        args, kwargs = mock_query.call_args
        assert args[4] == "Custom Address"
        assert args[5] == "milk"
        assert args[6] is False  # requery=False
        assert kwargs.get("max_dist_km") == 10.0

    @patch("paknsave_optimizer_mobile.foodstuffs_querier_mobile")
    @patch("paknsave_optimizer_mobile.optimise")
    def test_main_requery_true(self, mock_optimise, mock_query):
        """Verify --requery true is parsed as boolean True."""
        mock_query.return_value = True
        import paknsave_optimizer_mobile

        with patch.object(sys, "argv", [
            "paknsave_optimizer_mobile.py",
            "Test Address", "soup",
            "--requery", "true",
        ]):
            paknsave_optimizer_mobile.main()

        args, _ = mock_query.call_args
        assert args[6] is True

    @patch("paknsave_optimizer_mobile.foodstuffs_querier_mobile")
    @patch("paknsave_optimizer_mobile.optimise")
    def test_main_no_optimise_when_no_data(self, mock_optimise, mock_query):
        """Verify optimise() is NOT called when foodstuffs_querier_mobile returns False."""
        mock_query.return_value = False
        import paknsave_optimizer_mobile

        with patch.object(sys, "argv", ["paknsave_optimizer_mobile.py"]):
            paknsave_optimizer_mobile.main()

        mock_query.assert_called_once()
        mock_optimise.assert_not_called()

    @patch("paknsave_optimizer_mobile.foodstuffs_querier_mobile")
    @patch("paknsave_optimizer_mobile.optimise")
    def test_main_distance_as_float(self, mock_optimise, mock_query):
        """Verify --distance accepts float values."""
        mock_query.return_value = True
        import paknsave_optimizer_mobile

        with patch.object(sys, "argv", [
            "paknsave_optimizer_mobile.py",
            "Address", "dish", "--distance", "7.5",
        ]):
            paknsave_optimizer_mobile.main()

        _, kwargs = mock_query.call_args
        assert kwargs.get("max_dist_km") == 7.5

    @patch("paknsave_optimizer_mobile.foodstuffs_querier_mobile")
    @patch("paknsave_optimizer_mobile.optimise")
    def test_main_default_distance_without_flag(self, mock_optimise, mock_query):
        """Verify default max_dist_km is 5 when --distance is not specified."""
        mock_query.return_value = True
        import paknsave_optimizer_mobile

        with patch.object(sys, "argv", [
            "paknsave_optimizer_mobile.py",
            "Address", "dish",
        ]):
            paknsave_optimizer_mobile.main()

        _, kwargs = mock_query.call_args
        assert kwargs.get("max_dist_km") == 5
