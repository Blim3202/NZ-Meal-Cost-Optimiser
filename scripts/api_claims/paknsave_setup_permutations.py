"""
Verify that fetch_stores(source=...) returns a 10-column DataFrame for
each (source, cleaned) permutation in tools/paknsave/paknsave_setup.

Sources:   edge, mobile, store_finder
Cleaned:   true, false
Total:     3 sources x 2 cleaned = 6 permutations

For each permutation:
  1. fetch_stores(source=...) returns 10 columns
  2. run_full_setup(source=..., cleaned=...) returns 10 columns
  3. The written CSV has 10 columns

This script was previously tests/combined/test_paknsave_setup_permutations.py —
moved to scripts/api_claims/ because it hits the live API on every invocation
and was masquerading as a pytest test.

NOTE: run_full_setup mutates data/paknsave_stores.csv as a side effect.
Back up the file if you care about its current contents.

Source docs: docs/technical/PaknSave_API.md §9.

Usage:
    python -m scripts.api_claims.paknsave_setup_permutations
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.paknsave.paknsave_setup import (
    EXPECTED_COLUMNS,
    fetch_stores,
    run_full_setup,
)

PERMUTATIONS = [
    {"source": "edge", "cleaned": True},
    {"source": "edge", "cleaned": False},
    {"source": "mobile", "cleaned": True},
    {"source": "mobile", "cleaned": False},
    {"source": "store_finder", "cleaned": True},
    {"source": "store_finder", "cleaned": False},
]

NUM_COLUMNS = len(EXPECTED_COLUMNS)


def check_columns(df, label):
    """Verify df has exactly EXPECTED_COLUMNS in the right order."""
    actual = list(df.columns)
    if actual != EXPECTED_COLUMNS:
        print(f"  FAIL {label}: columns={actual}")
        return False
    print(f"  PASS {label}: {len(df)} rows, {NUM_COLUMNS} columns OK")
    return True


def check_permutation(source, cleaned):
    """Check one permutation: fetch_stores + run_full_setup."""
    label = f"source={source}, cleaned={cleaned}"
    all_ok = True

    try:
        df = fetch_stores(source=source, verbose=False)
        if not check_columns(df, f"fetch_stores({label})"):
            all_ok = False
    except Exception as e:
        print(f"  FAIL fetch_stores({label}): {e}")
        all_ok = False

    try:
        df = run_full_setup(source=source, cleaned=cleaned, verbose=False)
        if not check_columns(df, f"run_full_setup({label})"):
            all_ok = False
        from NZMealOptimiser import DATA_DIR
        import pandas as pd
        csv_df = pd.read_csv(str(DATA_DIR / "paknsave_stores.csv"))
        if not check_columns(csv_df, f"CSV({label})"):
            all_ok = False
    except Exception as e:
        print(f"  FAIL run_full_setup({label}): {e}")
        all_ok = False

    return all_ok


def main():
    print("=" * 60)
    print("Pak'nSave Setup Permutation Probe")
    print(f"Expected columns ({NUM_COLUMNS}): {EXPECTED_COLUMNS}")
    print("=" * 60)

    total_failed = 0

    print("\n--- Permutation probes (network required) ---")
    for perm in PERMUTATIONS:
        label = f"source={perm['source']}, cleaned={perm['cleaned']}"
        print(f"\n[{label}]")
        if not check_permutation(perm["source"], perm["cleaned"]):
            total_failed += 1

    print("\n" + "=" * 60)
    if total_failed == 0:
        print("ALL PERMUTATIONS OK: 10-column schema verified for every source/cleaned combo.")
    else:
        print(f"FAILURES: {total_failed} permutation(s) failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
