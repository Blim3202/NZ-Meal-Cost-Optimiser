"""
New World Mobile API Optimiser
=================================
Two-phase meal cost optimiser using the New World Mobile API (single-pass pipeline).

Phase 1 (query):  Geocode address → find nearby stores → authenticate → search
                    each ingredient at each store → append ALL results to full_results.csv
Phase 2 (optimise): Read today's results from CSV → find best per-store totals
                     and best mix → print comparison table

Usage:
    python -m tools.newworld.newworld_optimiser_mobile "<address>" "<dish>" [--requery false] [--distance 5]

Flags:
    --requery true   (default) Query the API and append new results
    --requery false  Skip API calls, optimise from existing CSV data only
    --distance N     Store search radius in km (default 5)

Defaults:
    Address: Botany Town Centre, Auckland
    Dish:    spaghetti bolognese
"""

import sys

from NZMealOptimiser.pricing.newworld_api import (
    NewWorldMobileAPI,
    find_nearby_stores,
)
from NZMealOptimiser.pricing.optimiser_utils import (
    foodstuffs_querier_mobile,
    optimise,
)


def main():
    """CLI entrypoint.

    Usage: python newworld_optimiser_mobile.py "<address>" "<dish>" [--requery false] [--distance 5]
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

    has_data = foodstuffs_querier_mobile(
        NewWorldMobileAPI,
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