"""
Dish Filters Validator

Loads data/dish_filters.json (manually curated include/exclude keyword filters)
and validates them against data/full_results.csv (spaghetti bolognese).

This is the verification step for the dish_filters.json rules created from
domain knowledge (no LLM involved in filter creation).

Usage:
    python -m exploration.llm.validate_dish_filters
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

# Reuse the same path resolution as the project
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


# ─── Levenshtein word matching (same as explore_filter_explorer) ──────────────

def levenshtein(s1: str, s2: str) -> int:
    """Pure-python Levenshtein distance."""
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current = [i + 1]
        for j, c2 in enumerate(s2):
            insertions     = previous[j + 1] + 1
            deletions      = current[j] + 1
            substitutions  = previous[j] + (c1 != c2)
            current.append(min(insertions, deletions, substitutions))
        previous = current
    return previous[-1]


def word_matches(haystack_word: str, needle_word: str) -> bool:
    """True if words fuzzy-match (Levenshtein ratio <= 0.35, or exact)."""
    if needle_word == haystack_word:
        return True
    d = levenshtein(haystack_word, needle_word)
    max_len = max(len(haystack_word), len(needle_word))
    if max_len == 0:
        return True
    return (d / max_len) <= 0.35


def contains_word(haystack: str, needle: str) -> bool:
    """
    Multi-word aware fuzzy match.
    For single words: any word in haystack within ratio 0.35.
    For multi-word: ALL words must have at least one fuzzy match.
    """
    needle = needle.lower().strip()
    if not needle:
        return True
    haystack_lower = haystack.lower()
    haystack_words = re.findall(r"[a-z]+", haystack_lower)
    for n_word in needle.split():
        if not any(word_matches(hw, n_word) for hw in haystack_words):
            return False
    return True


# ─── Filter application ─────────────────────────────────────────────────

def load_filters() -> dict:
    """Load dish_filters.json. Returns {dish_name: {search_term: {includes:[...], excludes:[...]}}}."""
    fpath = DATA_DIR / "dish_filters.json"
    if not fpath.exists():
        print(f"ERROR: {fpath} not found.")
        sys.exit(1)
    with open(fpath, encoding="utf-8") as f:
        data = json.load(f)
    # Strip metadata keys
    filters = {k: v for k, v in data.items() if not k.startswith("_")}
    return filters


def load_dishes() -> dict:
    with open(DATA_DIR / "dishes.json", encoding="utf-8") as f:
        return json.load(f)


def matches_filters(returned: str, includes: list[str], excludes: list[str]) -> tuple[bool, str]:
    """
    Check if a returned_ingredient passes the include/exclude filters.
    Returns (passed, reason_if_rejected).
    """
    # Check includes: at least one include word must match
    include_hit = any(contains_word(returned, inc) for inc in includes) if includes else True
    if not include_hit:
        return False, f"INCLUDE {includes} missing"

    # Check excludes: none of the exclude words should match
    matched_excludes = [exc for exc in excludes if contains_word(returned, exc)]
    if matched_excludes:
        return False, f"EXCLUDE hit: {matched_excludes}"

    return True, ""


def validate_dish(dish_name: str, all_filters: dict):
    """Run filter validation against full_results.csv for a given dish."""
    dish_key = dish_name.lower().strip()
    if dish_key not in all_filters:
        print(f"  No filters defined for '{dish_name}'")
        return

    filters = all_filters[dish_key]
    dishes = load_dishes()
    search_terms = [ing["search_term"] for ing in dishes[dish_key]["ingredients"]]

    df = pd.read_csv(DATA_DIR / "full_results.csv", dtype=str, keep_default_na=False)
    df_dish = df[df["search_ingredient"].isin(search_terms)].copy()

    total = len(df_dish)
    print(f"\n=== Validating: {dish_name} ===")
    print(f"  Total rows in CSV: {total}")

    if total == 0:
        print("  (No rows in full_results.csv for this dish.")
        return

    accept = 0
    reject = 0
    reject_reasons: list[tuple[str, str, str]] = []

    for _, row in df_dish.iterrows():
        si = row["search_ingredient"]
        rt = row["returned_ingredient"]
        if si not in filters:
            reject += 1
            reject_reasons.append((si, rt, "no filter defined"))
            continue

        f = filters[si]
        incs = f.get("includes", [])
        excls = f.get("excludes", [])
        passed, reason = matches_filters(rt, incs, excls)
        if passed:
            accept += 1
        else:
            reject += 1
            reject_reasons.append((si, rt, reason))

    print(f"  PASSED: {accept}")
    print(f"  REJECTED: {reject}")
    print(f"  Reduction: {reject}/{total} = {reject/total*100:.1f}%")

    # Per-ingredient breakdown
    print("\n  Per-ingredient breakdown:")
    for term in search_terms:
        if term not in filters:
            continue
        f = filters[term]
        incs = f.get("includes", [])
        excls = f.get("excludes", [])
        sub = df_dish[df_dish["search_ingredient"] == term]
        inc_rej = sum(1 for si, rt, r in reject_reasons if si == term and "INCLUDE" in r)
        exc_rej = sum(1 for si, rt, r in reject_reasons if si == term and "EXCLUDE" in r)
        print(f"    {term:25s}  total={len(sub):4d}  include_rej={inc_rej:3d}  exclude_rej={exc_rej:3d}")

    # Show top rejections
    print("\n  Top 20 rejections:")
    for si, rt, reason in reject_reasons[:20]:
        print(f"    [{si}] {rt:55s}  -> {reason}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Validate dish_filters.json against full_results.csv")
    parser.add_argument("--dish", default="spaghetti bolognese",
                        help="Dish to validate (default: spaghetti bolognese)")
    args = parser.parse_args()

    filters = load_filters()
    validate_dish(args.dish, filters)


if __name__ == "__main__":
    main()
