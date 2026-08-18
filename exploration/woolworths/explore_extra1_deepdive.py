"""
Deep-dive investigation: why extra1 collisions happen and what the
API returns for store-specific metadata.

For each of the 3 colliding extra1 pairs, this script:
  1. Checks ALL extra fields (extra1-extra15) in CDX for both stores
  2. Queries the shell endpoint with extra1 and dumps the FULL JSON response
     — looking for storeName, address, city, region fields that might
     disambiguate.
  3. Queries a product search and dumps the full product response, checking
     for any store-specific metadata.
"""

import sys
import json
import requests
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from woolworths_api import create_session, set_store_context, BASE_URL

DATA_DIR = PROJECT_ROOT / "data"
JSON_DATA = DATA_DIR / "woolworths_store_data.json"

COLLISION_PAIRS = {
    "9290": [
        {"name": "Nelson Junction Woolworths", "extra1": 9290, "extra2": 4166071, "site_id": 9290, "address": "33 Cadillac Way, Nelson"},
        {"name": "Motueka Woolworths",         "extra1": 9290, "extra2": 767216,  "site_id": 9495, "address": "108 High Street, Motueka"},
    ],
    "9112": [
        {"name": "Te Puke Woolworths",         "extra1": 9112, "extra2": 913417,  "site_id": 9448, "address": "Cnr Queen & Boucher St, Te Puke"},
        {"name": "Bureta Park Woolworths",     "extra1": 9112, "extra2": 1175393, "site_id": 9050, "address": "44-50 Bureta Rd, Tauranga"},
    ],
    "9511": [
        {"name": "Bridge Street Woolworths",   "extra1": 9511, "extra2": 1207646, "site_id": 9033, "address": "Hamilton"},
        {"name": "Matamata Woolworths",        "extra1": 9511, "extra2": 911335,  "site_id": 9120, "address": "Matamata"},
    ],
}


def dump_full_cdx_site(extra2):
    """Find and dump the full site dict from CDX JSON by extra2."""
    with open(JSON_DATA, "r", encoding="utf-8") as f:
        data = json.load(f)
    for item in data.get("siteDetail", []):
        site = item.get("site", {})
        if str(site.get("extra2")) == str(extra2):
            return site
    return None


def query_shell_full(key_value):
    """Inject cookie and get the FULL /shell JSON response."""
    session = create_session()
    fsid = str(key_value)
    cookie_val = f"dm-Pickup,f-{fsid},s-38"
    session.cookies.set("cw-lrkswrdjp", cookie_val, domain="www.woolworths.co.nz", path="/")
    
    resp = session.get(f"{BASE_URL}/shell", timeout=15)
    try:
        return resp.json()
    except ValueError:
        return {"error": f"Non-JSON response (HTTP {resp.status_code})", "text": resp.text[:500]}


def query_products_full(key_value, query="milk"):
    """Inject cookie and get the FULL product search response."""
    session = create_session()
    fsid = str(key_value)
    cookie_val = f"dm-Pickup,f-{fsid},s-38"
    session.cookies.set("cw-lrkswrdjp", cookie_val, domain="www.woolworths.co.nz", path="/")
    
    resp = session.get(
        f"{BASE_URL}/products",
        params={"target": "search", "search": query, "size": 5},
        timeout=15,
    )
    try:
        return resp.json()
    except ValueError:
        return {"error": f"Non-JSON response (HTTP {resp.status_code})", "text": resp.text[:500]}


def print_divider(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def main():
    print_divider("Deep-Dive: extra1 Collision Investigation")
    
    for extra1_val, pair in COLLISION_PAIRS.items():
        print_divider(f"Colliding extra1={extra1_val}: {pair[0]['name']} vs {pair[1]['name']}")
        
        for store in pair:
            print(f"\n--- {store['name']} ---")
            
            # Phase 1: Full CDX metadata
            print("  [CDX metadata]")
            site = dump_full_cdx_site(store["extra2"])
            if site:
                for k in sorted(site.keys()):
                    val = site.get(k)
                    if val is not None and val != "null" and val != "":
                        print(f"    {k}={val}")
            
            # Phase 2: Full shell response
            print("  [Full /shell response]")
            shell = query_shell_full(store["extra1"])
            if isinstance(shell, dict) and "error" not in shell:
                # Pretty-print the full shell response
                print(f"    {json.dumps(shell, indent=6)}")
            else:
                print(f"    {shell}")
            
            # Phase 3: Full product search response (first result only)
            print("  [Full /products response (first item)]")
            products = query_products_full(store["extra1"], "milk")
            if isinstance(products, dict) and "error" not in products:
                items = products.get("products", {}).get("items", [])
                if items:
                    first = items[0]
                    print(f"    sku={first.get('sku')}")
                    print(f"    name={first.get('name')}")
                    print(f"    price={first.get('price')}")
                    print(f"    size={first.get('size')}")
                    print(f"    url={first.get('url')}")
                    # Check if there are any store-specific fields
                    for k in sorted(first.keys()):
                        if k not in ("sku", "name", "price", "size", "url"):
                            val = first.get(k)
                            if val is not None and val != "null":
                                print(f"    {k}={val}")
                else:
                    print(f"    No products returned")
            else:
                print(f"    {products}")

    print_divider("Investigation Complete")
    print("""
HYPOTHESIS: extra1 is the correct cookie key (shell accepts it).
The price collisions may be legitimate — Woolworths may price
milk identically across all stores nationally.

RECOMMENDATION: 
  1. Test with a highly store-specific product (e.g. fresh produce, 
     deli items) to see if prices actually differ between colliding 
     extra1 pairs.
  2. Check if the store NAME in product results differs (the API may
     embed store-specific metadata we haven't inspected).
""")


if __name__ == "__main__":
    main()
