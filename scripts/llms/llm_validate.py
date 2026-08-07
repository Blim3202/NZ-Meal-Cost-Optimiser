"""
LLM-Based Search Result Validator
==================================
Validates whether supermarket search API results match the intended search term.

Reads rows from data/full_results.csv, constructs per-row description text
following the SQL logic provided, and batches rows through ministral-3b-2512
to get a boolean "is_valid" per row.

Usage:
    python scripts/llms/llm_validate.py --max-rows 20 --batch-size 20

The model_alias "small" maps to ministral-3b-2512 (see llm_client.py DEFAULT_MODELS).
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, List

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.llms.llm_client import LLMClient

DATA_FILE = _PROJECT_ROOT / "data" / "full_results.csv"

VALIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {"type": "boolean"},
        }
    },
    "required": ["results"],
}

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "search_result_validation",
        "schema": VALIDATE_SCHEMA,
        "strict": True,
    },
}

VALIDATE_PROMPT = """You are a product-matches-search-term validator. For each numbered item, decide whether the returned product is a valid match for what was searched.

A result is VALID when the returned_ingredient IS the type of item the user was searching for. For example:
- Searching for "beef mince" and getting "beef mince" -> VALID
- Searching for "beef mince" and getting "beef burgers" -> INVALID (burgers, not mince)
- Searching for "spaghetti pasta" and getting "pasta spaghetti" -> VALID
- Searching for "spaghetti pasta" and getting "pasta penne" -> INVALID (wrong pasta shape)
- Searching for "canned tomatoes" and getting "crushed & sieved tomatoes" -> VALID (same ingredient, different form)
- Searching for "canned tomatoes" and getting "roast garlic & onion" -> INVALID (different flavouring variant, but still tomatoes -> borderline; only mark INVALID if it is clearly a different product type)

Respond with ONLY a JSON object: {{"results": [true, false, ...]}} -- one boolean per item, in order. No other text.

{rows_text}"""


def _clean(value):
    """Return a stripped non-null string, or empty string for NaN/None."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def build_row_text(row, idx):
    """Construct the description text for a single row.

    logic:
        'Searching for [X] returned [Y]'
        + CASE for department / sub_department.
    """
    search = _clean(row.get("search_ingredient"))
    returned = _clean(row.get("returned_ingredient"))
    dept = _clean(row.get("department"))
    subdept = _clean(row.get("sub_department"))

    text = f"Searching for [{search}] returned [{returned}]"

    has_dept = bool(dept)
    has_sub = bool(subdept)

    if has_dept and has_sub:
        text += f" in departments [{dept}] and [{subdept}]"
    elif has_dept:
        text += f" in departments [{dept}]"
    elif has_sub:
        text += f" in departments [{subdept}]"
    # else: nothing appended (matches ELSE '' in SQL)

    return f"{idx}. {text}"


def validate_batch(client: Any, rows_text: str, batch_number: int) -> List[bool]:
    """Send a batch of row descriptions to the LLM and return a list of booleans.

    Uses json_schema response format so the model is guaranteed to return
    {"results": [bool, ...]} with the correct structure — no manual
    schema validation or retry-on-parse needed.
    """
    prompt = VALIDATE_PROMPT.format(rows_text=rows_text)
    max_retries = 3

    for attempt in range(max_retries):
        try:
            response = client.client.chat.complete(
                model=client.model_id,
                messages=[{"role": "user", "content": prompt}],
                response_format=RESPONSE_FORMAT,
            )
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  [WARN] batch {batch_number}: API error (attempt {attempt + 1}): {e}")
                time.sleep(1.0)
                continue
            raise

        content = response.choices[0].message.content

        try:
            data = json.loads(content)
            results = data["results"]
            if not isinstance(results, list) or not all(isinstance(x, bool) for x in results):
                raise ValueError(f"'results' is not a list of booleans: {results!r}")
            return results
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
            if attempt < max_retries - 1:
                print(f"  [WARN] batch {batch_number}: parse error (attempt {attempt + 1}): {e}")
                time.sleep(0.5)
                continue
            raise ValueError(f"Batch {batch_number}: could not parse LLM response. Raw: {content[:200]}")

    # Should be unreachable due to raise inside loop
    raise RuntimeError(f"Batch {batch_number}: failed after {max_retries} attempts.")


def validate_rows(df: pd.DataFrame, df_work: pd.DataFrame, unvalidated_full_indices: Any, data_file: Path, batch_size: int = 20) -> List[bool]:
    """Validate all rows in df_work in batches, saving to CSV after each batch.

    After each batch completes, the is_valid values are written back to the
    full DataFrame and persisted to the CSV file. This ensures partial results
    survive early termination / crashes.

    Args:
        df: The full DataFrame (updated in-place with is_valid values).
        df_work: Subset of unvalidated rows to process.
        unvalidated_full_indices: Index labels in df corresponding to the
            rows in df_work, used to map batch results back to the full df.
        data_file: Path to the CSV file for incremental saving.
        batch_size: number of rows to send to the LLM per API call

    Returns:
        list[bool]: one boolean per row in df_work, in order
    """
    client = LLMClient(model_alias="small")
    all_results = []

    for start in range(0, len(df_work), batch_size):
        batch = df_work.iloc[start:start + batch_size]
        rows_text = "\n".join(
            build_row_text(row, i + 1)
            for i, (_, row) in enumerate(batch.iterrows())
        )
        batch_number = start // batch_size + 1
        print(f"\n--- Batch {batch_number} (rows {start + 1}-{start + len(batch)}) ---")

        results = validate_batch(client, rows_text, batch_number)
        all_results.extend(results)

        for i, (_, row) in enumerate(batch.iterrows()):
            global_idx = start + i + 1
            status = "VALID" if results[i] else "INVALID"
            print(f"  Row {global_idx}: [{status}] {build_row_text(row, global_idx)}")

        # Persist results for this batch immediately so partial results
        # survive early termination or crashes.
        batch_indices = unvalidated_full_indices[start:start + len(batch)]
        for idx_in_full, result in zip(batch_indices, results):
            df.loc[idx_in_full, "is_valid"] = result
        df.to_csv(data_file, index=False)
        print(f"  [SAVED] Batch {batch_number} ({len(results)} rows) written to {data_file}")

    return all_results


def main():
    parser = argparse.ArgumentParser(
        description="Validate supermarket search results match the search term via LLM."
    )
    parser.add_argument(
        "--max-rows", type=int, default=20,
        help="Number of rows to validate (default: 20)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=20,
        help="Rows per LLM API call (default: 20)",
    )
    parser.add_argument(
        "--data-file", default=str(DATA_FILE),
        help="Path to full_results.csv",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.data_file)

    # Only process rows where is_valid is missing (NaN or empty string)
    if "is_valid" not in df.columns:
        df["is_valid"] = None

    df["is_valid"] = df["is_valid"].astype(object)
    df.loc[df["is_valid"].isna() | (df["is_valid"].astype(str).str.strip() == ""), "is_valid"] = None

    unvalidated = df[df["is_valid"].isna()].reset_index(drop=True)

    if len(unvalidated) == 0:
        print("All rows already validated — nothing to do.")
        return

    # Limit to max_rows unvalidated rows
    df_work = unvalidated.iloc[:args.max_rows].copy()
    unvalidated_full_indices = df[df["is_valid"].isna()].index[:args.max_rows]

    print(f"Loaded {len(df)} total rows from {args.data_file}")
    print(f"Found {len(unvalidated)} unvalidated rows")
    print(f"Validating first {len(df_work)} (max-rows={args.max_rows})")
    print(f"Model: ministral-3b-2512 (alias: small)")
    print(f"Batch size: {args.batch_size}")

    start_time = time.time()
    results = validate_rows(
        df, df_work, unvalidated_full_indices, args.data_file,
        batch_size=args.batch_size,
    )
    elapsed = time.time() - start_time

    valid_count = sum(results)
    print(f"\n{'=' * 60}")
    print(f"Results: {valid_count} valid / {len(results) - valid_count} invalid "
          f"out of {len(results)} rows")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"{'=' * 60}")
    print(f"\nWrote is_valid values back to {args.data_file}")

    # Show summary of the rows we processed
    print(f"\nSummary table:")
    summary_df = df.iloc[unvalidated_full_indices][["search_ingredient", "returned_ingredient", "department", "is_valid"]]
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
