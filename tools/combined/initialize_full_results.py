"""
Initialise Full Results CSV
==================================
Creates data/full_results.csv with the correct column structure
if it does not already exist.

Columns match data/full_results.csv.

Usage:
    python -m tools.combined.initialize_full_results
"""

import csv

from NZMealOptimiser import DATA_DIR

OUTPUT_FILE = DATA_DIR / "full_results.csv"

COLUMNS = [
    "company",
    "store",
    "store_id",             # PK
    "search_ingredient",
    "returned_ingredient",
    "brand",
    "price",
    "quantity",
    "measurement_unit",
    "per_unit_quantity",
    "per_unit_price",
    "is_sale",
    "sku",                  # PK
    "department",
    "sub_department",
    "datetime_created",
    "date_created",         # PK
    "pk_hash",              # SHA-256(store_id + sku + date_created)
    "is_valid",             # filled by tools/llm/llm_validate.py
]


def initialize():
    if OUTPUT_FILE.exists():
        print(f"File already exists: {OUTPUT_FILE}")
        return
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
    print(f"Created: {OUTPUT_FILE}")


if __name__ == "__main__":
    initialize()
