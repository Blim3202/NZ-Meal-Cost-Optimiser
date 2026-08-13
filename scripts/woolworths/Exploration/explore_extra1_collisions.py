"""
Woolworths extra1 Collision Investigation
==========================================
Investigates the 6 stores that share extra1 values in the CDX data:

    extra1=9290:  Nelson Junction Woolworths  (extra2=4166071, site.id=9290)
                  Motueka Woolworths          (extra2=767216,  site.id=9495)
    extra1=9112:  Te Puke Woolworths          (extra2=913417,  site.id=9448)
                  Bureta Park Woolworths      (extra2=1175393, site.id=9050)
    extra1=9511:  Bridge Street Woolworths    (extra2=1207646, site.id=9033)
                  Matamata Woolworths         (extra2=911335,  site.id=9120)

For each colliding pair, this script:
  1. Loads BOTH stores' full CDX metadata (all extra fields, site.id, etc.)
  2. Queries the live Woolworths API with each store's extra1 as the cookie key
     — this tests the CURRENT hypothesis (extra1 → cw-lrkswrdjp → f-{extra1}).
  3. ALSO queries with each store's extra2 (pickupAddressId) as an alternative
     hypothesis: does the cookie `f-{extra2}` produce DIFFERENT prices?
  4. ALSO queries with each store's site.id as another alternative.
  5. Compares the prices across all three keying strategies for a fixed search
     query ("milk"), so we can determine whether extra1 truly isolates a single
     physical store or whether it collapses two stores into one pricing context.

If the prices from extra1=9290 for Nelson Junction vs Motueka come back
**identical**, then extra1 is NOT a unique store key and we've been using the
wrong ID all along.

If the prices differ, extra1 may be correct (or the API may be returning cached
default prices regardless of the cookie — which would also be a problem).

OUTPUT: a human-readable report printed to stdout.
"""

import sys
import json
import requests
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from woolworths_api import create_session, set_store_context, search_products, find_cheapest

DATA_DIR = PROJECT_ROOT / "data"
JSON_DATA = DATA_DIR / "woolworths_store_data.json"

SEARCH_QUERY = "milk"

# The 6 stores in 3 colliding pairs, grouped by extra1.
COLLISION_PAIRS = {
    "9290": [
        {"name": "Nelson Junction Woolworths", "extra1": 9290, "extra2": 4166071, "site_id": 9290},
        {"name": "Motueka Woolworths",         "extra1": 9290, "extra2": 767216,  "site_id": 9495},
    ],
    "9112": [
        {"name": "Te Puke Woolworths",         "extra1": 9112, "extra2": 913417,  "site_id": 9448},
        {"name": "Bureta Park Woolworths",     "extra1": 9112, "extra2": 1175393, "site_id": 9050},
    ],
    "9511": [
        {"name": "Bridge Street Woolworths",   "extra1": 9511, "extra2": 1207646, "site_id": 9033},
        {"name": "Matamata Woolworths",        "extra1": 9511, "extra2": 911335,  "site_id": 9120},
    ],
}


def load_full_cdx():
    """Load the raw CDX JSON (woolworths_store_data.json)."""
    with open(JSON_DATA, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_site_metadata(extra1_or_extra2_or_siteid, field="extra1"):
    """Find the full CDX site dict matching a given field value."""
    data = load_full_cdx()
    for item in data.get("siteDetail", []):
        site = item.get("site", {})
        if str(site.get(field)) == str(extra1_or_extra2_or_siteid):
            return site
    return None


def query_store_with_key(key_type, key_value, label):
    """Create a fresh session, inject the key as the cookie, search, return best price.

    Args:
        key_type: one of 'extra1' (fulfilmentStoreId), 'extra2' (pickupAddressId),
                  'site_id' (CDX site id)
        key_value: the integer to put in the cookie f-{value}
        label: human-readable label for reporting
    """
    try:
        session = create_session()
        context = set_store_context(session, key_value)
        product = find_cheapest(session, SEARCH_QUERY, size=20, food_only=True)
        if product:
            return {
                "label": label,
                "key_type": key_type,
                "key_value": key_value,
                "cookie_fsid": context.get("fulfilmentStoreId"),
                "shell_store_name": context.get("storeName"),
                "sku": product.get("sku"),
                "name": product.get("name"),
                "sale_price": product.get("salePrice"),
                "unit_price": product.get("unitPrice"),
            }
        else:
            return {
                "label": label,
                "key_type": key_type,
                "key_value": key_value,
                "cookie_fsid": context.get("fulfilmentStoreId"),
                "shell_store_name": context.get("storeName"),
                "error": "No food products found for query",
            }
    except Exception as e:
        return {
            "label": label,
            "key_type": key_type,
            "key_value": key_value,
            "error": str(e),
        }


def print_divider(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def main():
    print_divider("Woolworths extra1 Collision Investigation")
    print(f"Search query: '{SEARCH_QUERY}'")
    print(f"JSON source:  {JSON_DATA}")

    # ---- Phase 1: Dump full CDX metadata for all 6 stores ----
    print_divider("Phase 1: CDX Metadata for Colliding Stores")

    for extra1_val, pair in COLLISION_PAIRS.items():
        print(f"\n--- Colliding extra1={extra1_val} ---")
        for store in pair:
            site = extract_site_metadata(store["extra2"], field="extra2")
            if site:
                print(f"  Store: {store['name']}")
                print(f"    extra1={site.get('extra1')}, extra2={site.get('extra2')}, site.id={site.get('id')}")
                print(f"    name={site.get('name')}")
                print(f"    address={site.get('addressLine1')}, {site.get('suburb')} {site.get('postcode')}")
                print(f"    lat={site.get('latitude')}, lon={site.get('longitude')}")
                print(f"    All extra fields present: extra1={site.get('extra1')}, extra2={site.get('extra2')}")
                # Print any extra3-extra15 that might reveal more
                for k in sorted(site.keys()):
                    if k.startswith("extra") and k not in ("extra1", "extra2"):
                        print(f"    {k}={site.get(k)}")
                print()
            else:
                print(f"  Store: {store['name']} — NOT FOUND in CDX JSON by extra2={store['extra2']}")

    # ---- Phase 2: Query each store's prices using extra1 (current method) ----
    print_divider("Phase 2: Live API Query with extra1 (current method)")

    for extra1_val, pair in COLLISION_PAIRS.items():
        print(f"\n--- Colliding extra1={extra1_val} ---")
        for store in pair:
            result = query_store_with_key("extra1", store["extra1"], store["name"])
            if "error" in result:
                print(f"  {store['name']}: ERROR — {result['error']}")
            else:
                print(f"  {store['name']}:")
                print(f"    cookie fsid={result['cookie_fsid']}, shell storeName={result['shell_store_name']}")
                print(f"    product: {result['name']} (sku={result['sku']})")
                print(f"    sale_price={result['sale_price']}, unit_price={result['unit_price']}")

    # ---- Phase 3: For the FIRST store in each pair, also try extra2 as cookie key ----
    print_divider("Phase 3: Live API Query with extra2 (alternative hypothesis)")

    for extra1_val, pair in COLLISION_PAIRS.items():
        print(f"\n--- extra1={extra1_val} | using extra2 as cookie key ---")
        for store in pair:
            result = query_store_with_key("extra2", store["extra2"], store["name"])
            if "error" in result:
                print(f"  {store['name']}: ERROR — {result['error']}")
            else:
                print(f"  {store['name']}:")
                print(f"    cookie fsid={result['cookie_fsid']}, shell storeName={result['shell_store_name']}")
                print(f"    product: {result['name']} (sku={result['sku']})")
                print(f"    sale_price={result['sale_price']}, unit_price={result['unit_price']}")

    # ---- Phase 4: Try site.id as cookie key ----
    print_divider("Phase 4: Live API Query with site.id (alternative hypothesis)")

    for extra1_val, pair in COLLISION_PAIRS.items():
        print(f"\n--- extra1={extra1_val} | using site.id as cookie key ---")
        for store in pair:
            result = query_store_with_key("site_id", store["site_id"], store["name"])
            if "error" in result:
                print(f"  {store['name']}: ERROR — {result['error']}")
            else:
                print(f"  {store['name']}:")
                print(f"    cookie fsid={result['cookie_fsid']}, shell storeName={result['shell_store_name']}")
                print(f"    product: {result['name']} (sku={result['sku']})")
                print(f"    sale_price={result['sale_price']}, unit_price={result['unit_price']}")

    # ---- Phase 5: Shell validation for each key type ----
    print_divider("Phase 5: /shell context validation for each key type")

    for extra1_val, pair in COLLISION_PAIRS.items():
        print(f"\n--- extra1={extra1_val} ---")
        for store in pair:
            for key_type, key_val in [("extra1", store["extra1"]),
                                      ("extra2", store["extra2"]),
                                      ("site_id", store["site_id"])]:
                try:
                    session = create_session()
                    ctx = set_store_context(session, key_val)
                    fulf_fsid = ctx.get("fulfilmentStoreId")
                    # Also check the shell's storeName
                    resp = session.get("https://www.woolworths.co.nz/api/v1/shell", timeout=15)
                    shell = resp.json()
                    store_name_in_shell = shell.get("context", {}).get("fulfilment", {}).get("storeName", "")
                    print(f"  {store['name']} | key={key_type}({key_val}): "
                          f"shell fulfilmentStoreId={fulf_fsid}, storeName='{store_name_in_shell}'")
                except Exception as e:
                    print(f"  {store['name']} | key={key_type}({key_val}): ERROR — {e}")


if __name__ == "__main__":
    main()
