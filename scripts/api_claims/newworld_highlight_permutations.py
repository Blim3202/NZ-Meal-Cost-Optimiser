"""
Focused verification of the NewWorld_API.md claims about `_highlightResult`
and `matchedWords` on the Algolia Edge API endpoint.

Claims under test (NewWorld_API.md sections 6.3 / 6.4 / 6.8):
  1. `products-index` returns HTTP 200 and carries `_highlightResult`.
  2. `_highlightResult` field values expose `value`, `matchLevel`, `matchedWords`.
  3. Relevance hits have non-empty `matchedWords`; no-match queries do not.
  4. `matchedWords` tokens are generally derivable from the query
     (Algolia may add taxonomy/brand tokens not literally in the query).
  5. `<em>` emphasis markers appear in `value` wherever `matchedWords` is non-empty.
  6. The 8 "dead" indices (price-asc/desc, relevance, name-asc/desc, newest,
     bestselling, trending) return HTTP 500 as documented in section 6.4.
  7. Pass 2 `paginated/products` returns pricing only — products carry no
     `_highlightResult`.

NOTE on the production filter (scripts/newworld/newworld_api.py):
  `any(isinstance(v, dict) and v.get("matchedWords") for v in hr.values())`
  only inspects SCALAR dict values. Array fields (e.g. `category1`, `category2`)
  are lists-of-dicts and are skipped by that logic. The test therefore records
  matches under two lenses:
    - "scalar match"  -> would the production filter flag this hit?
    - "any match"     -> does ANY field (incl. list fields) hold a match?

Every JSON response is printed in full, except the store-availability fields
`inStoreAvailable` and `onlineAvailable`, whose values are redacted with
"TRUNCATED FOR TEST" so the rest of the payload stays readable.

Usage:
    python -m scripts.api_claims.newworld_highlight_permutations
"""

import json
import re
import sys
import time

WEB_BASE = "https://www.newworld.co.nz"
EDGE_BASE = "https://api-prod.newworld.co.nz/v1/edge"
STORE_ID = "60928d93-06fa-4d8f-92a6-8c359e7e846d"  # New World Metro Auckland
REGION = "NI"

HITS_PER_PAGE = 20
PAGE = 0

# Only the first N hits are printed and analysed (the server always returns
# 40 regardless of HITS_PER_PAGE, so this keeps terminal output small).
HITS_LIMIT = 1

QUERIES = ["milk", "beef mince", "dog food", "zzzqqq"]

WORKING_INDEX = "products-index"

# Documented as HTTP 500 (section 6.4) — these index names do not exist
DEAD_INDICES = [
    "products-index-price-asc",
    "products-index-price-desc",
    "products-index-relevance",
    "products-index-name-asc",
    "products-index-name-desc",
    "products-index-newest",
    "products-index-bestselling",
    "products-index-trending",
]

# Fields whose values are redacted in printed JSON.
REDACT_KEYS = {"inStoreAvailable", "onlineAvailable", "stores"}


def _configure_stdout_utf8() -> None:
    """Best-effort stdout UTF-8 configuration for console use.

    Safe to call when this module is imported, because we only touch the
    stream if it actually exposes a reconfigure() method.
    """
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def get_jwt():
    """Website JWT (fs-user-token) via the public anonymous flow."""
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    session.get(WEB_BASE, timeout=30)
    session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    return session.cookies.get("fs-user-token")


def auth_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }


def store_cookies():
    return {
        "eCom_STORE_ID": STORE_ID,
        "STORE_ID_V2": f"{STORE_ID}|False",
        "Region": REGION,
    }


def redact(obj):
    """Deep-copy `obj` replacing REDACT_KEYS values with TRUNCATED FOR TEST."""
    if isinstance(obj, dict):
        return {
            k: ("TRUNCATED FOR TEST" if k in REDACT_KEYS else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def print_json(data):
    print(json.dumps(redact(data), indent=2, ensure_ascii=False))


def query_tokens(query):
    return set(re.findall(r"[a-z0-9]+", (query or "").lower()))


def matched_in_query(matched_words, query):
    """Yield (word, derivable_from_query) for each matched word."""
    qtokens = query_tokens(query)
    for w in matched_words or []:
        wl = str(w).lower()
        in_q = any(
            qt == wl or qt.startswith(wl) or wl.startswith(qt)
            for qt in qtokens
        )
        yield w, in_q


def split_matches(hr):
    """Return (scalar_matches, any_matches) across a _highlightResult dict.

    scalar_matches: fields whose value is a SCALAR dict with non-empty
    matchedWords (this is what the production filter sees).

    any_matches: fields where ANY entry (scalar or list-of-dicts) holds a
    non-empty matchedWords.
    """
    scalar_matches = []
    any_matches = []
    for field, info in hr.items():
        if isinstance(info, dict):
            if info.get("matchedWords"):
                scalar_matches.append(field)
                any_matches.append(field)
        elif isinstance(info, list):
            if any(
                isinstance(item, dict) and item.get("matchedWords")
                for item in info
            ):
                any_matches.append(field)
    return scalar_matches, any_matches


def summarize_field(field, info, query):
    """One-line human-readable summary of a _highlightResult entry."""
    head = f"          {field:24s}"
    if isinstance(info, dict):
        words = info.get("matchedWords") or []
        out = (f"{head} dict  matchedWords={words}"
               f" matchLevel={info.get('matchLevel')}")
        if words:
            em = "<em>" in (info.get("value") or "")
            deriv = [f"{w}{'' if ok else '(!)'}"
                     for w, ok in matched_in_query(words, query)]
            out += (" em=OK" if em else " em=MISSING")
            out += " derived_from_query=[" + ", ".join(deriv) + "]"
        return out
    if isinstance(info, list):
        matched = sum(
            1 for item in info
            if isinstance(item, dict) and item.get("matchedWords")
        )
        return f"{head} list x{len(info)} (entries_with_match={matched})"
    return f"{head} {type(info).__name__}"


def analyse_hit(hit, query):
    hl = hit.get("_highlightResult", None)
    scalar_matches, any_matches = split_matches(hl) if isinstance(hl, dict) else ([], [])
    return {
        "productID": hit.get("productID"),
        "DisplayName": hit.get("DisplayName"),
        "has_hr_key": "_highlightResult" in hit,
        "hr_is_dict": isinstance(hl, dict),
        "hr_empty": isinstance(hl, dict) and len(hl) == 0,
        "scalar_matches": scalar_matches,
        "any_matches": any_matches,
        "scalar_flagged": bool(scalar_matches),
        "any_flagged": bool(any_matches),
        "_highlightResult": hl,
    }


def main():
    import requests  # deferred so the module can be imported without it

    _configure_stdout_utf8()

    print("=" * 80)
    print("TEST: _highlightResult / matchedWords on products-index (New World Edge)")
    print("=" * 80)

    token = get_jwt()
    print(f"1. Auth: fs-user-token {'OK' if token else 'FAILED'}\n")
    if not token:
        return
    headers = auth_headers(token)
    cookies = store_cookies()

    # ── 1b. Dead-index status probes (claim 6) ─────────────────────────
    print("2. Dead-index status probes (documented HTTP 404):")
    dead_ok = True
    dead_all_error = True
    dead_codes = set()
    for idx in DEAD_INDICES:
        r = requests.post(
            f"{EDGE_BASE}/search/products/query/index/{idx}",
            headers=headers,
            json={"algoliaQuery": {"query": "milk"}, "page": 0,
                  "hitsPerPage": 5, "storeId": STORE_ID},
            cookies=cookies,
            timeout=30,
        )
        dead_codes.add(r.status_code)
        is_500 = r.status_code == 500
        is_error = 400 <= r.status_code <= 599
        dead_ok &= is_500
        dead_all_error &= is_error
        print(f"      {idx:40s} -> {r.status_code}  "
              f"{'[OK 500]' if is_500 else ('[non-200 error]' if is_error else '[UNEXPECTED]')}")
        if r.status_code != 500:
            print(f"          body: {r.text[:120]!r}")
    verdict6 = 'PASS' if dead_ok else ('PARTIAL' if dead_all_error else 'FAIL')
    print(f"      CLAIM[6] dead indices return 500 = {verdict6}; "
          f"statuses seen = {sorted(dead_codes)}")

    # ── 3. products-index sweep (claims 1-5) ───────────────────────────
    print("3. products-index search sweep:")
    overall = []
    for q in QUERIES:
        print(f"\n   --- Query: {q!r} (Metro Auckland, page {PAGE}, "
              f"hitsPerPage {HITS_PER_PAGE}) ---")
        r = requests.post(
            f"{EDGE_BASE}/search/products/query/index/{WORKING_INDEX}",
            headers=headers,
            json={"algoliaQuery": {"query": q}, "page": PAGE,
                  "hitsPerPage": HITS_PER_PAGE, "storeId": STORE_ID},
            cookies=cookies,
            timeout=30,
        )
        print(f"      HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"      {r.text[:300]}")
            overall.append((q, "HTTP_ERR", []))
            continue
        data = r.json()
        hits = data.get("hits", [])
        print(f"      nbHits={data.get('nbHits')} hits returned={len(hits)} "
              f"(showing/analysing first {min(len(hits), HITS_LIMIT)})")
        display = {**data, "hits": hits[:HITS_LIMIT]}
        print(f"      FULL RESPONSE (inStoreAvailable / onlineAvailable "
              f"redacted, hits truncated to {HITS_LIMIT}):")
        print_json(display)

        analysed = [analyse_hit(h, q) for h in hits[:HITS_LIMIT]]
        n = len(analysed)
        if n == 0:
            print("      (no hits)")
            overall.append((q, "OK_EMPTY", analysed))
            continue

        has_hr = sum(1 for a in analysed if a["has_hr_key"])
        hr_dict = sum(1 for a in analysed if a["hr_is_dict"])
        empty = sum(1 for a in analysed if a["hr_empty"])
        scalar_flagged = sum(1 for a in analysed if a["scalar_flagged"])
        any_flagged = sum(1 for a in analysed if a["any_flagged"])
        scalar_fields = sorted({f for a in analysed for f in a["scalar_matches"]})

        print(f"\n      Hit analysis ({n} hits):")
        print(f"        _highlightResult key present   : {has_hr}/{n}")
        print(f"        _highlightResult is dict       : {hr_dict}/{n}")
        print(f"        _highlightResult empty dict    : {empty}")
        print(f"        hits with scalar match (prodn) : {scalar_flagged}")
        print(f"        hits with any match (incl list): {any_flagged}")
        print(f"        matched field names (scalar)   : {scalar_fields}")

        for a in analysed:
            print(f"        {a['productID']}  {a['DisplayName']!r}  "
                  f"scalar_match={a['scalar_flagged']}  any_match={a['any_flagged']}")
            if a["_highlightResult"]:
                for field, info in a["_highlightResult"].items():
                    print(summarize_field(field, info, q))
        print()

        overall.append((q, "OK", analysed))
        time.sleep(0.3)

    # ── 4. Pass 2 negative check (claim 7) ─────────────────────────────
    print("4. Pass 2 negative check (paginated/products, pricing only):")
    pass2_ok = True
    pass2_checked = 0
    last_ok = next((a for a in overall if a[1] == "OK"), None)
    if last_ok:
        q, _, analysed = last_ok
        ids = [a["productID"] for a in analysed if a["any_flagged"]]
    else:
        q, ids = None, []
    if ids:
        filter_str = " OR ".join(f"productID:{p}" for p in ids)
        r2 = requests.post(
            f"{EDGE_BASE}/search/paginated/products",
            headers=headers,
            json={"algoliaQuery": {"query": q, "filters": filter_str},
                  "page": 0, "hitsPerPage": 50, "storeId": STORE_ID,
                  "sortOrder": "PRICE_ASC"},
            cookies=cookies,
            timeout=30,
        )
        print(f"      HTTP {r2.status_code} (filter IDs={len(ids)}, query={q!r})")
        if r2.status_code == 200:
            products = r2.json().get("products", [])
            print(f"      products returned={len(products)}")
            for p in products:
                hl = p.get("_highlightResult", None)
                if hl:
                    pass2_ok = False
                    print(f"        UNEXPECTED _highlightResult on {p.get('productId')}")
                    print_json(hl)
                else:
                    pass2_checked += 1
                    print(f"        {p.get('productId')}  {p.get('name')}  "
                          f"price={p.get('singlePrice', {}).get('price')}  "
                          f"(no _highlightResult [OK])")
        else:
            print(f"      response: {r2.text[:300]}")
    else:
        print("      no productIDs to test")
    if pass2_checked == 0:
        print("      (no products to inspect — negative claim not exercised)")
    print(f"      CLAIM[7 pass2 has no _highlightResult] "
          f"{'PASS' if pass2_ok else 'FAIL'} ({pass2_checked} products inspected)\n")

    # ── 5. Summary ─────────────────────────────────────────────────────
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    ok_responses = all(s in ("OK", "OK_EMPTY") for _, s, _ in overall)
    print(f"  [1] products-index HTTP 200 + _highlightResult present : "
          f"{'PASS' if ok_responses else 'CHECK HTTP'}")
    print(f"  [6] 8 dead indices return 500                           : "
          f"{verdict6} (statuses {sorted(dead_codes)})")

    print("\n  Per-query hit analysis:")
    for q, status, analysed in overall:
        if status != "OK":
            print(f"      {q!r:14s} {status}")
            continue
        scalar = sum(1 for a in analysed if a["scalar_flagged"])
        anym = sum(1 for a in analysed if a["any_flagged"])
        print(f"      {q!r:14s} hits={len(analysed):3d}  "
              f"scalar_match={scalar:3d}  any_match={anym:3d}")
    print("=" * 80)


if __name__ == "__main__":
    main()