"""
New World Edge API Optimizer
=============================
Two-phase meal cost optimizer using the New World Edge API (two-pass pipeline).

Phase 1 (query):  Geocode address → find nearby stores → authenticate → search
                    each ingredient at each store → append ALL results to full_results.csv
Phase 2 (optimise): Read today's results from CSV → find best per-store totals
                     and best mix → print comparison table

Usage:
    python -m scripts.newworld.newworld_optimizer_edge "<address>" "<dish>" [--requery false] [--distance 5]

Flags:
    --requery true   (default) Query the API and append new results
    --requery false  Skip API calls, optimise from existing CSV data only
    --distance N     Store search radius in km (default 5)

Defaults:
    Address: Botany Town Centre, Auckland
    Dish:    spaghetti bolognese
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "combined"))

from newworld_api import (
    NewWorldEdgeAPI,
    find_nearby_stores,
)
from optimizer_utils import (
    foodstuffs_optimizer_edge,
    optimise,
)


def main():
    """CLI entrypoint.

    Usage: python newworld_optimizer_edge.py "<address>" "<dish>" [--requery false] [--distance 5]
    Defaults to Botany Town Centre, Auckland / spaghetti bolognese / requery true / distance 5km.
    """
    address = "Botany Town Centre, Auckland"
    dish = "spaghetti bolognese"
    requery = True
    max_dist_km = 5

    positional = []
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--requery":
            if i + 1 < len(sys.argv):
                requery = sys.argv[i + 1].lower() != "false"
                i += 2
            else:
                requery = True
                i += 1
        elif sys.argv[i] == "--distance":
            if i + 1 < len(sys.argv):
                max_dist_km = float(sys.argv[i + 1])
                i += 2
            else:
                i += 1
        else:
            positional.append(sys.argv[i])
            i += 1

    if len(positional) >= 1:
        address = positional[0]
    if len(positional) >= 2:
        dish = positional[1]

    has_data = foodstuffs_optimizer_edge(
        NewWorldEdgeAPI,
        find_nearby_stores,
        "NewWorld",
        "New World",
        address,
        dish,
        requery,
        max_dist_km=max_dist_km,
    )
    if has_data:
        optimise(dish, company="NewWorld")


if __name__ == "__main__":
    main()