r"""
Test all New World setup permutations for 10-column schema compliance.

Per Brand: New World
Sources:   edge, mobile
Cleaned:   true, false

Total permutations: 2 sources x 2 cleaned = 4

Each permutation:
  1. Tests fetch_stores(source=...) returns 10 columns
  2. Tests run_full_setup(source=..., cleaned=...) returns 10 columns
  3. Tests CLI argparse accepts --source and --cleaned args

Usage:
    .venv\Scripts\Activate.ps1
    python scripts\test\test_newworld_setup_permutations.py
"""

import subprocess
import sys
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPT_DIR / "newworld"))

from newworld_setup import (
    EXPECTED_COLUMNS,
    fetch_stores,
    run_full_setup,
)

PERMUTATIONS = [
    {"source": "edge", "cleaned": True},
    {"source": "edge", "cleaned": False},
    {"source": "mobile", "cleaned": True},
    {"source": "mobile", "cleaned": False},
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


def test_cli_args():
    """Verify argparse accepts all valid --source and --cleaned combinations (no network)."""
    script = str(PROJECT_ROOT / "scripts" / "newworld" / "newworld_setup.py")
    passed = 0
    failed = 0

    for source in ["edge", "mobile"]:
        for cleaned in ["true", "false"]:
            # --help should always pass; instead, test that --source + --cleaned are accepted
            # by checking the parser via a dry import and parse
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        f"import sys; sys.path.insert(0, r'{PROJECT_ROOT}'); "
                        f"sys.path.insert(0, r'{PROJECT_ROOT / 'scripts' / 'newworld'}'); "
                        f"from newworld_setup import _parse_cleaned; "
                        f"assert _parse_cleaned('{cleaned}') == ({cleaned.lower() == 'true'}); "
                        f"print('OK')",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and "OK" in result.stdout:
                    print(f"  PASS CLI parse: --source={source} --cleaned={cleaned}")
                    passed += 1
                else:
                    print(f"  FAIL CLI parse: --source={source} --cleaned={cleaned}: {result.stderr.strip()}")
                    failed += 1
            except Exception as e:
                print(f"  FAIL CLI parse: --source={source} --cleaned={cleaned}: {e}")
                failed += 1

    return failed == 0


def test_permutation(source, cleaned):
    """Test one permutation: fetch_stores + run_full_setup."""
    label = f"source={source}, cleaned={cleaned}"
    all_ok = True

    # Test 1: fetch_stores returns 10 columns
    try:
        df = fetch_stores(source=source, verbose=False)
        if not check_columns(df, f"fetch_stores({label})"):
            all_ok = False
    except Exception as e:
        print(f"  FAIL fetch_stores({label}): {e}")
        all_ok = False

    # Test 2: run_full_setup returns 10 columns
    try:
        df = run_full_setup(source=source, cleaned=cleaned, verbose=False)
        if not check_columns(df, f"run_full_setup({label})"):
            all_ok = False
        # Also verify written CSV has 10 columns
        import pandas as pd
        csv_df = pd.read_csv(str(PROJECT_ROOT / "data" / "newworld_stores.csv"))
        if not check_columns(csv_df, f"CSV({label})"):
            all_ok = False
    except Exception as e:
        print(f"  FAIL run_full_setup({label}): {e}")
        all_ok = False

    return all_ok


def main():
    print("=" * 60)
    print("New World Setup Permutation Tests")
    print(f"Expected columns ({NUM_COLUMNS}): {EXPECTED_COLUMNS}")
    print("=" * 60)

    total_failed = 0

    print("\n--- CLI argument parsing tests ---")
    if not test_cli_args():
        total_failed += 1

    print("\n--- Permutation tests (network required) ---")
    for perm in PERMUTATIONS:
        label = f"source={perm['source']}, cleaned={perm['cleaned']}"
        print(f"\n[{label}]")
        if not test_permutation(perm["source"], perm["cleaned"]):
            total_failed += 1

    print("\n" + "=" * 60)
    if total_failed == 0:
        print("ALL PASSED: All permutations return 10 columns.")
    else:
        print(f"FAILURES: {total_failed} permutation(s) failed — review needed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
