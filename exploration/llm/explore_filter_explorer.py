"""
Filter Explorer — LLM include/exclude filter generation & evaluation.

Asks Mistral Large and Google Gemini to generate include/exclude keyword
filters for ONE dish's ingredient search_terms (generic prompt, no
dish-specific rules), then applies each backend's filters against that
dish's rows in data/full_results.csv and reports exactly what would be
excluded.

Usage:
    python -m exploration.llm.explore_filter_explorer --dish "spaghetti bolognese"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from exploration.llm.validate_dish_filters import contains_word, matches_filters  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

# MISTRAL_FILTER_MODEL = "mistral-large-2512"
MISTRAL_FILTER_MODEL = "mistral-medium-latest"
GOOGLE_FILTER_MODEL = "gemini-3.1-flash-lite"

MAX_EXCLUDES = 5

PROMPT_TEMPLATE = textwrap.dedent("""\
    You are a search-intent filter labeller for a New Zealand supermarket price comparator.
    A recipe needs the ingredients listed below. For each search_term (the exact query sent
    to the supermarket product search API), produce keyword filters that separate CORRECT
    products from the WRONG products such searches commonly return.

    Respond with ONE JSON object and nothing else:
    {{"filters": [
        {{"search_term": "<verbatim copy of a search term>",
          "includes": "<one word>",
          "excludes": ["<word>", "<word>"]}}
    ]}}

    Rules:
    - Return exactly one filter object per search_term, echoing "search_term" verbatim.
    - "includes": ONE singular word — the core noun identifying the ingredient itself as it
      appears on NZ supermarket shelf labels. Fuzzy matching handles plurals and minor typos,
      so the singular form is safest ("carrot" matches both Carrots and Carrot). Pick the
      single most distinctive noun; never use brand names, pack sizes, or the dish name.
    - "excludes": up to {max_excludes} single words which, if present in a product title,
      mark it as WRONG for this search_term. Consider which of these common false-positive
      categories actually apply:
      * processed/derived forms of the ingredient: powder, flakes, seasoning, sachet, extract
      * prepared foods built on the ingredient: soup, pie, cake, dip, chips, crackers, sauce
      * flavoured snacks and meal kits that merely mention the ingredient
      Only add an exclude when products containing that word would genuinely be unsuitable.
      Do not pad with speculative words, and never exclude a legitimate form of the ingredient.

    Search terms:
    {search_terms_json}
""")


# ─── Backend call wrappers ──────────────────────────────────────────────────

def _chat_with_retry(send, is_rate_limit, max_retries: int = 3) -> str:
    """Call *send()* retrying on rate limits with linear backoff."""
    for attempt in range(1, max_retries + 1):
        try:
            return send()
        except Exception as e:
            if is_rate_limit(e) and attempt < max_retries:
                wait = 20 * attempt
                print(f"    [rate limited] sleeping {wait}s "
                      f"(attempt {attempt}/{max_retries})...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("unreachable")


def _loads_json(content: str):
    """Parse model output tolerating markdown code fences."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    return json.loads(cleaned)


def call_mistral(prompt: str) -> str:
    from mistralai.client import Mistral
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("MISTRAL_API_KEY not set in .env")
    client = Mistral(api_key=api_key)

    def send():
        resp = client.chat.complete(
            model=MISTRAL_FILTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        return resp.choices[0].message.content

    def is_rate_limit(e):
        return getattr(e, "status_code", None) == 429

    return _chat_with_retry(send, is_rate_limit)


def call_google(prompt: str, model: str) -> str:
    from openai import OpenAI
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Neither GOOGLE_API_KEY nor GEMINI_API_KEY is set in .env")
    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    def send():
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=4096,
        )
        return resp.choices[0].message.content

    def is_rate_limit(e):
        return type(e).__name__ == "RateLimitError"

    return _chat_with_retry(send, is_rate_limit)


# ─── Filter parsing ─────────────────────────────────────────────────────────

def parse_filters(parsed, search_terms: list[str]) -> tuple[dict, list[str]]:
    """
    Normalise model output to {search_term: {"includes": str, "excludes": [str]}}.
    Accepts a bare array or a dict wrapping one. Returns (filters, warnings).
    """
    if isinstance(parsed, dict):
        entries = next((v for v in parsed.values() if isinstance(v, list)), None)
    elif isinstance(parsed, list):
        entries = parsed
    else:
        entries = None
    if entries is None:
        raise ValueError("no filter list found in model response")

    terms_lower = {t.lower(): t for t in search_terms}
    filters: dict[str, dict] = {}
    warnings: list[str] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_term = str(entry.get("search_term", "")).strip()
        term = terms_lower.get(raw_term.lower())
        if term is None:
            warnings.append(f"ignored unknown search_term '{raw_term}'")
            continue
        inc = entry.get("includes", "")
        if isinstance(inc, list):
            inc = " ".join(str(w) for w in inc)
        exc = entry.get("excludes", [])
        if isinstance(exc, str):
            exc = [exc]
        exc = [str(w).strip().lower() for w in exc if str(w).strip()]
        if len(exc) > MAX_EXCLUDES:
            warnings.append(f"'{term}': trimmed excludes from {len(exc)} to {MAX_EXCLUDES}")
            exc = exc[:MAX_EXCLUDES]
        filters[term] = {"includes": str(inc).strip().lower(), "excludes": exc}

    missing = [t for t in search_terms if t not in filters]
    if missing:
        warnings.append(f"no filter generated for: {missing}")
    return filters, warnings


# ─── Evaluation against full_results.csv ────────────────────────────────────

def evaluate(filters: dict, df_dish: pd.DataFrame):
    """Apply filters to every row. Returns (accept, reject_count, rejects list)."""
    accept = 0
    rejects: list[tuple[str, str, str]] = []
    for _, row in df_dish.iterrows():
        si = row["search_ingredient"]
        rt = row["returned_ingredient"]
        f = filters.get(si)
        if f is None:
            rejects.append((si, rt, "no filter"))
            continue
        passed, reason = matches_filters(
            rt,
            [f["includes"]] if f["includes"] else [],
            f["excludes"],
        )
        if passed:
            accept += 1
        else:
            rejects.append((si, rt, reason))
    return accept, len(rejects), rejects


def print_filter_table(filters: dict, warnings: list[str]):
    print("\n  Generated filters:")
    for term, f in filters.items():
        print(f"    {term:25s} includes='{f['includes']}'  excludes={f['excludes']}")
    for w in warnings:
        print(f"    WARNING: {w}")


def print_rejections(filters: dict, rejects: list[tuple[str, str, str]]):
    """Show every unique rejected product title grouped by ingredient."""
    unique: dict[tuple[str, str], str] = {}
    for si, rt, reason in rejects:
        unique.setdefault((si, rt), reason)

    print("\n  Excluded products (unique titles):")
    for term in filters:
        rows = [(si, rt, reason) for (si, rt), reason in unique.items()
                if si == term]
        if not rows:
            continue
        print(f"    [{term}]")
        for _, rt, reason in rows:
            print(f"      {rt:60s} -> {reason}")


def save_outputs(name: str, tag: str, filters: dict, rejects: list):
    base = OUTPUT_DIR / f"{name}_{tag}"
    try:
        with open(f"{base}_filters.json", "w", encoding="utf-8") as f:
            json.dump(filters, f, indent=2, ensure_ascii=False)
        pd.DataFrame(rejects, columns=["search_ingredient", "returned_ingredient", "reason"]) \
            .to_csv(f"{base}_rejects.csv", index=False)
        print(f"\n  Saved: {base}_filters.json, {base}_rejects.csv")
    except PermissionError:
        tmp = Path(tempfile.gettempdir()) / f"{name}_{tag}_{int(time.time())}"
        with open(f"{tmp}_filters.json", "w", encoding="utf-8") as f:
            json.dump(filters, f, indent=2, ensure_ascii=False)
        pd.DataFrame(rejects, columns=["search_ingredient", "returned_ingredient", "reason"]) \
            .to_csv(f"{tmp}_rejects.csv", index=False)
        print(f"\n  Output dir locked; saved to temp: {tmp}_*.json/csv")


# ─── Main ───────────────────────────────────────────────────────────────────

def load_dishes() -> dict:
    with open(DATA_DIR / "dishes.json", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Generate + evaluate include/exclude filters via Mistral and Google")
    parser.add_argument("--dish", default="spaghetti bolognese",
                        help="Dish name from data/dishes.json (default: 'spaghetti bolognese')")
    parser.add_argument("--google-model", default=GOOGLE_FILTER_MODEL,
                        help=f"Google model name (default: {GOOGLE_FILTER_MODEL})")
    args = parser.parse_args()

    dish_key = args.dish.lower().strip()
    dishes = load_dishes()
    if dish_key not in dishes:
        sys.exit(f"Dish '{args.dish}' not found in data/dishes.json. "
                 f"Available: {', '.join(sorted(dishes))}")
    search_terms = [ing["search_term"] for ing in dishes[dish_key]["ingredients"]]

    df = pd.read_csv(DATA_DIR / "full_results.csv", dtype=str, keep_default_na=False)
    df_dish = df[df["search_ingredient"].isin(search_terms)].copy()
    total = len(df_dish)

    print(f"=== Filter Explorer: '{dish_key}' ===")
    print(f"Search terms ({len(search_terms)}): {search_terms}")
    print(f"Rows in full_results.csv for this dish: {total}")

    prompt = PROMPT_TEMPLATE.format(
        max_excludes=MAX_EXCLUDES,
        search_terms_json=json.dumps(search_terms, ensure_ascii=False),
    )
    backends = [
        ("mistral", MISTRAL_FILTER_MODEL, call_mistral),
        ("google", args.google_model, lambda p, m=args.google_model: call_google(p, m)),
    ]

    summary = []
    for name, model, caller in backends:
        print(f"\n{'=' * 70}\nBackend: {name} ({model})\n{'=' * 70}")
        try:
            parsed = _loads_json(caller(prompt))
            filters, warnings = parse_filters(parsed, search_terms)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            summary.append((name, model, None, None, None))
            continue

        print_filter_table(filters, warnings)
        accept, reject, rejects = evaluate(filters, df_dish)
        reduction = (reject / total * 100) if total else 0.0
        print(f"\n  Rows PASSED: {accept}   REJECTED: {reject}   "
              f"Reduction: {reduction:.1f}%")
        print_rejections(filters, rejects)
        save_outputs(name, dish_key.replace(" ", "_"), filters, rejects)
        summary.append((name, model, accept, reject, reduction))

    print(f"\n{'=' * 70}\n=== Comparison ===\n{'=' * 70}")
    print(f"  {'backend':10s} {'model':28s} {'passed':>7s} {'rejected':>9s} {'reduction':>10s}")
    for name, model, accept, reject, reduction in summary:
        if accept is None:
            print(f"  {name:10s} {model:28s} {'FAILED':>7s}")
        else:
            print(f"  {name:10s} {model:28s} {accept:>7d} {reject:>9d} {reduction:>9.1f}%")


if __name__ == "__main__":
    main()
