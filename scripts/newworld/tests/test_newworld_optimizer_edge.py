"""
Unit tests for New World Edge Optimizer CLI (newworld_optimizer_edge.py).

Tests the main() function's argument parsing: positional address/dish args,
--requery flag parsing, --distance flag parsing, and correct forwarding of
parsed arguments to the shared foodstuffs_querier_edge pipeline.

The shared foodstuffs_querier_edge and optimise functions are mocked to avoid
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


class TestNewWorldOptimizerEdgeCLI:
    """Tests for Edge API optimizer main() argument parsing and dispatch."""

    DEFAULT_ADDRESS = "Botany Town Centre, Auckland"
    DEFAULT_DISH = "spaghetti bolognese"

    @patch("newworld_optimizer_edge.foodstuffs_querier_edge")
    @patch("newworld_optimizer_edge.optimise")
    def test_main_defaults(self, mock_optimise, mock_query):
        mock_query.return_value = True
        import newworld_optimizer_edge

        with patch.object(sys, "argv", ["newworld_optimizer_edge.py"]):
            newworld_optimizer_edge.main()

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

    @patch("newworld_optimizer_edge.foodstuffs_querier_edge")
    @patch("newworld_optimizer_edge.optimise")
    def test_main_custom_args(self, mock_optimise, mock_query):
        mock_query.return_value = True
        import newworld_optimizer_edge

        with patch.object(sys, "argv", [
            "newworld_optimizer_edge.py",
            "Custom Address",
            "milk",
            "--requery", "false",
            "--distance", "10",
        ]):
            newworld_optimizer_edge.main()

        args, kwargs = mock_query.call_args
        assert args[4] == "Custom Address"
        assert args[5] == "milk"
        assert args[6] is False
        assert kwargs.get("max_dist_km") == 10.0

    @patch("newworld_optimizer_edge.foodstuffs_querier_edge")
    @patch("newworld_optimizer_edge.optimise")
    def test_main_requery_true(self, mock_optimise, mock_query):
        mock_query.return_value = True
        import newworld_optimizer_edge

        with patch.object(sys, "argv", [
            "newworld_optimizer_edge.py",
            "Test Address", "soup",
            "--requery", "true",
        ]):
            newworld_optimizer_edge.main()

        args, _ = mock_query.call_args
        assert args[6] is True

    @patch("newworld_optimizer_edge.foodstuffs_querier_edge")
    @patch("newworld_optimizer_edge.optimise")
    def test_main_no_optimise_when_no_data(self, mock_optimise, mock_query):
        mock_query.return_value = False
        import newworld_optimizer_edge

        with patch.object(sys, "argv", ["newworld_optimizer_edge.py"]):
            newworld_optimizer_edge.main()

        mock_query.assert_called_once()
        mock_optimise.assert_not_called()

    @patch("newworld_optimizer_edge.foodstuffs_querier_edge")
    @patch("newworld_optimizer_edge.optimise")
    def test_main_float_distance(self, mock_optimise, mock_query):
        mock_query.return_value = True
        import newworld_optimizer_edge

        with patch.object(sys, "argv", [
            "newworld_optimizer_edge.py",
            "Address", "dish", "--distance", "7.5",
        ]):
            newworld_optimizer_edge.main()

        _, kwargs = mock_query.call_args
        assert kwargs.get("max_dist_km") == 7.5

    @patch("newworld_optimizer_edge.foodstuffs_querier_edge")
    @patch("newworld_optimizer_edge.optimise")
    def test_main_address_with_spaces(self, mock_optimise, mock_query):
        mock_query.return_value = True
        import newworld_optimizer_edge

        with patch.object(sys, "argv", [
            "newworld_optimizer_edge.py",
            "Botany Town Centre, Auckland",
            "chicken stir fry",
        ]):
            newworld_optimizer_edge.main()

        args, _ = mock_query.call_args
        assert args[4] == "Botany Town Centre, Auckland"
        assert args[5] == "chicken stir fry"
