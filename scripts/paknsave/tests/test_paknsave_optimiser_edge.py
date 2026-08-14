"""
Unit tests for Pak'nSave Edge Optimiser CLI (paknsave_optimiser_edge.py).

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


class TestPaknSaveOptimiserEdgeCLI:
    """Tests for Edge API Optimiser main() argument parsing and dispatch."""

    DEFAULT_ADDRESS = "588 Chapel Road, East Tāmaki, Auckland 2016"
    DEFAULT_DISH = "spaghetti bolognese"

    @patch("paknsave_optimiser_edge.foodstuffs_querier_edge")
    @patch("paknsave_optimiser_edge.optimise")
    def test_main_defaults(self, mock_optimise, mock_query):
        """Verify main() uses correct defaults when no CLI args are provided.

        With no positional arguments, main() should use:
        - address: "588 Chapel Road, East Tāmaki, Auckland 2016"
        - dish: "spaghetti bolognese"
        - requery: True (default)
        - max_dist_km: 5 (default)
        """
        mock_query.return_value = True
        import paknsave_optimiser_edge

        with patch.object(sys, "argv", ["paknsave_optimiser_edge.py"]):
            paknsave_optimiser_edge.main()

        mock_query.assert_called_once()
        args, kwargs = mock_query.call_args
        # foodstuffs_querier_edge(api_class, find_nearby_stores, company_id,
        #   company_name, user_address, dish_name, requery, max_dist_km=...)
        assert args[4] == self.DEFAULT_ADDRESS  # address
        assert args[5] == self.DEFAULT_DISH     # dish
        assert args[6] is True                  # requery=True
        assert kwargs.get("max_dist_km") == 5

        mock_optimise.assert_called_once()
        opt_args, opt_kwargs = mock_optimise.call_args
        assert opt_args[0] == self.DEFAULT_DISH
        assert opt_kwargs.get("company") == "PaknSave"

    @patch("paknsave_optimiser_edge.foodstuffs_querier_edge")
    @patch("paknsave_optimiser_edge.optimise")
    def test_main_custom_args(self, mock_optimise, mock_query):
        """Verify main() correctly parses custom address, ingredient, requery, and distance.

        argv: address="Custom Address", dish="milk", --requery=false, --distance=10
        """
        mock_query.return_value = True
        import paknsave_optimiser_edge

        with patch.object(sys, "argv", [
            "paknsave_optimiser_edge.py",
            "Custom Address",
            "milk",
            "--requery", "false",
            "--distance", "10",
        ]):
            paknsave_optimiser_edge.main()

        args, kwargs = mock_query.call_args
        assert args[4] == "Custom Address"
        assert args[5] == "milk"
        assert args[6] is False  # requery=False
        assert kwargs.get("max_dist_km") == 10.0

    @patch("paknsave_optimiser_edge.foodstuffs_querier_edge")
    @patch("paknsave_optimiser_edge.optimise")
    def test_main_requery_true(self, mock_optimise, mock_query):
        """Verify --requery true is parsed as boolean True."""
        mock_query.return_value = True
        import paknsave_optimiser_edge

        with patch.object(sys, "argv", [
            "paknsave_optimiser_edge.py",
            "Test Address", "soup",
            "--requery", "true",
        ]):
            paknsave_optimiser_edge.main()

        args, _ = mock_query.call_args
        assert args[6] is True

    @patch("paknsave_optimiser_edge.foodstuffs_querier_edge")
    @patch("paknsave_optimiser_edge.optimise")
    def test_main_no_optimise_when_no_data(self, mock_optimise, mock_query):
        """Verify optimise() is NOT called when foodstuffs_querier_edge returns False."""
        mock_query.return_value = False
        import paknsave_optimiser_edge

        with patch.object(sys, "argv", ["paknsave_optimiser_edge.py"]):
            paknsave_optimiser_edge.main()

        mock_query.assert_called_once()
        mock_optimise.assert_not_called()

    @patch("paknsave_optimiser_edge.foodstuffs_querier_edge")
    @patch("paknsave_optimiser_edge.optimise")
    def test_main_float_distance(self, mock_optimise, mock_query):
        """Verify --distance accepts float values."""
        mock_query.return_value = True
        import paknsave_optimiser_edge

        with patch.object(sys, "argv", [
            "paknsave_optimiser_edge.py",
            "Address", "dish", "--distance", "7.5",
        ]):
            paknsave_optimiser_edge.main()

        _, kwargs = mock_query.call_args
        assert kwargs.get("max_dist_km") == 7.5

    @patch("paknsave_optimiser_edge.foodstuffs_querier_edge")
    @patch("paknsave_optimiser_edge.optimise")
    def test_main_address_with_spaces(self, mock_optimise, mock_query):
        """Verify multi-word address and dish are parsed correctly as positional args.

        Tests the real address "588 Chapel Road, East Tāmaki, Auckland 2016"
        with a dish containing spaces "chicken stir fry".
        """
        mock_query.return_value = True
        import paknsave_optimiser_edge

        with patch.object(sys, "argv", [
            "paknsave_optimiser_edge.py",
            "588 Chapel Road, East Tāmaki, Auckland 2016",
            "chicken stir fry",
        ]):
            paknsave_optimiser_edge.main()

        args, _ = mock_query.call_args
        assert args[4] == "588 Chapel Road, East Tāmaki, Auckland 2016"
        assert args[5] == "chicken stir fry"
