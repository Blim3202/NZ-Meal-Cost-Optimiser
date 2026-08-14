"""
Woolworths NZ Meal Cost Optimiser
=================================
Two-Step meal cost optimiser using the Woolworths NZ API (cookie-based per-store pricing).

Step 1 (query):  Geocode address → find nearby stores → search each ingredient at
                 each store → append ALL results to full_results.csv. Shared
                 implementation in optimiser_utils.woolworths_querier().
Step 2 (optimise): Read today's results from CSV → find best per-store totals
                   and best mix → print comparison table.

Usage:
    python woolworths_optimiser.py "<address>" "<dish>" [--requery false] [--distance 5]

Flags:
    --requery true   (default) Query the API and append new results
    --requery false  Skip API calls, optimise from existing CSV data only
    --distance N     Store search radius in km (default 5)

Defaults:
    Address: 123 Queen Street, Auckland CBD, 1010
    Dish:    spaghetti bolognese
"""

import sys
from pathlib import Path

# Add scripts/combined to path for optimiser_utils
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "combined"))

import woolworths_api
from optimiser_utils import (
    woolworths_querier,
    optimise,
)


def main():
    """CLI entrypoint.

    Usage: python woolworths_optimiser.py "<address>" "<dish>" [--requery false] [--distance 5]
    Defaults to 123 Queen Street, Auckland CBD / spaghetti bolognese / requery true / distance 5km.
    """
    address = "123 Queen Street, Auckland CBD, 1010"
    dish = "spaghetti bolognese"
    requery = True
    max_dist_km = 5

    # Manual arg parsing: collect positional args, handle --flag value pairs
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

    has_data = woolworths_querier(
        woolworths_api,
        "Woolworths",
        "Woolworths",
        address,
        dish,
        requery,
        max_dist_km=max_dist_km,
    )
    if has_data:
        optimise(dish, company="Woolworths")


if __name__ == "__main__":
    main()
