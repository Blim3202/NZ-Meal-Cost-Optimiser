"""
Unit tests for New World Mobile Optimiser CLI (newworld_optimiser_mobile.py).

Tests the main() function's argument parsing: positional address/dish args,
--requery flag parsing, --distance flag parsing, and correct forwarding of
parsed arguments to the shared foodstuffs_querier_mobile pipeline.

The shared foodstuffs_querier_mobile and optimise functions are mocked to avoid
network calls, but the argument parsing logic in main() is exercised for real
with various sys.argv combinations.
"""

import sys
from unittest.mock import patch

import pytest


class TestNewWorldOptimiserMobileCLI:
    """Tests for Mobile API Optimiser main() argument parsing and dispatch."""

    DEFAULT_ADDRESS = "Botany Town Centre, Auckland"
    DEFAULT_DISH = "spaghetti bolognese"

    @patch("tools.newworld.newworld_optimiser_mobile.foodstuffs_querier_mobile")
    @patch("tools.newworld.newworld_optimiser_mobile.optimise")
    def test_main_defaults(self, mock_optimise, mock_query):
        mock_query.return_value = True
        import tools.newworld.newworld_optimiser_mobile as newworld_optimiser_mobile

        with patch.object(sys, "argv", ["newworld_optimiser_mobile.py"]):
            newworld_optimiser_mobile.main()

        mock_query.assert_called_once()
        args, kwargs = mock_query.call_args
        assert args[4] == self.DEFAULT_ADDRESS
        assert args[5] == self.DEFAULT_DISH
        assert args[6] is True
        assert kwargs.get("max_dist_km") == 5

        mock_optimise.assert_called_once()
        opt_args, opt_kwargs = mock_optimise.call_args
        assert opt_args[0] == self.DEFAULT_DISH
        assert opt_kwargs.get("company") == "NewWorld"

    @patch("tools.newworld.newworld_optimiser_mobile.foodstuffs_querier_mobile")
    @patch("tools.newworld.newworld_optimiser_mobile.optimise")
    def test_main_custom_args(self, mock_optimise, mock_query):
        mock_query.return_value = True
        import tools.newworld.newworld_optimiser_mobile as newworld_optimiser_mobile

        with patch.object(sys, "argv", [
            "newworld_optimiser_mobile.py",
            "Custom Address",
            "milk",
            "--requery", "false",
            "--distance", "10",
        ]):
            newworld_optimiser_mobile.main()

        args, kwargs = mock_query.call_args
        assert args[4] == "Custom Address"
        assert args[5] == "milk"
        assert args[6] is False
        assert kwargs.get("max_dist_km") == 10.0

    @patch("tools.newworld.newworld_optimiser_mobile.foodstuffs_querier_mobile")
    @patch("tools.newworld.newworld_optimiser_mobile.optimise")
    def test_main_requery_true(self, mock_optimise, mock_query):
        mock_query.return_value = True
        import tools.newworld.newworld_optimiser_mobile as newworld_optimiser_mobile

        with patch.object(sys, "argv", [
            "newworld_optimiser_mobile.py",
            "Test Address", "soup",
            "--requery", "true",
        ]):
            newworld_optimiser_mobile.main()

        args, _ = mock_query.call_args
        assert args[6] is True

    @patch("tools.newworld.newworld_optimiser_mobile.foodstuffs_querier_mobile")
    @patch("tools.newworld.newworld_optimiser_mobile.optimise")
    def test_main_no_optimise_when_no_data(self, mock_optimise, mock_query):
        mock_query.return_value = False
        import tools.newworld.newworld_optimiser_mobile as newworld_optimiser_mobile

        with patch.object(sys, "argv", ["newworld_optimiser_mobile.py"]):
            newworld_optimiser_mobile.main()

        mock_query.assert_called_once()
        mock_optimise.assert_not_called()

    @patch("tools.newworld.newworld_optimiser_mobile.foodstuffs_querier_mobile")
    @patch("tools.newworld.newworld_optimiser_mobile.optimise")
    def test_main_distance_as_float(self, mock_optimise, mock_query):
        mock_query.return_value = True
        import tools.newworld.newworld_optimiser_mobile as newworld_optimiser_mobile

        with patch.object(sys, "argv", [
            "newworld_optimiser_mobile.py",
            "Address", "dish", "--distance", "7.5",
        ]):
            newworld_optimiser_mobile.main()

        _, kwargs = mock_query.call_args
        assert kwargs.get("max_dist_km") == 7.5

    @patch("tools.newworld.newworld_optimiser_mobile.foodstuffs_querier_mobile")
    @patch("tools.newworld.newworld_optimiser_mobile.optimise")
    def test_main_default_distance_without_flag(self, mock_optimise, mock_query):
        mock_query.return_value = True
        import tools.newworld.newworld_optimiser_mobile as newworld_optimiser_mobile

        with patch.object(sys, "argv", [
            "newworld_optimiser_mobile.py",
            "Address", "dish",
        ]):
            newworld_optimiser_mobile.main()

        _, kwargs = mock_query.call_args
        assert kwargs.get("max_dist_km") == 5
