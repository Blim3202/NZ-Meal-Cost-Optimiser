"""
explore_woolworths_api_part3.py
=================================
Phase 2: Validate stored cookie jars via /api/v1/shell and /api/v1/products.

Background
----------
Phase 1 (part2) confirmed that injecting a full Playwright-captured cookie jar into a
requests.Session causes /api/v1/products to return correct per-store pricing.  This
script builds on that finding with two diagnostic checks:

  1. /api/v1/shell   -- returns the session's current store context in
     `context.fulfilment` (fulfilmentStoreId, pickupAddressId, method, address).
     If our cookies are valid, the shell's store ID should match the store we
     selected during Playwright capture.  If it shows the *default* ID (9171),
     the cookies are stale/invalid.

  2. /api/v1/products  -- does `fulfilmentStoreId` as a query parameter influence
     the response *when cookies are absent*?  If so, we have a fallback path
     that avoids Playwright entirely (though Phase 1 already showed this is
     ineffective for pricing).

Additionally, we analyse the `cw-lrkswrdjp` cookie across stores  -- it encodes
delivery method, fulfilment area, area, and a store segment:
  Greymouth: dm-Pickup,f-9009,a-224,s-38
  Glenfield: dm-Pickup,f-9443,a-440,s-38
This cookie is a strong candidate for the per-store pricing signal.

Known targets
  Greymouth (id 764300): Milk 3L = $7.15, cw-lrkswrdjp f-9009, a-224
  Glenfield  (id 1190273): Milk 3L = $7.33, cw-lrkswrdjp f-9443, a-440
"""

import os, sys, json, time, asyncio
import requests
from playwright.async_api import async_playwright

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "..", "data", "Exploration", "woolworths"))
COOKIE_JAR = os.path.join(DATA_DIR, "part2_cookies.json")
BASE_URL   = "https://www.woolworths.co.nz"
API_BASE   = f"{BASE_URL}/api/v1"

# ── Known stores ─────────────────────────────────────────────────────────────
STORES = {
    "Greymouth": {"pickup_id": 764300,  "area_id": 224,  "fulfil_id": 9009},
    "Glenfield":  {"pickup_id": 1190273, "area_id": 440,  "fulfil_id": 9443},
}
DEFAULT_FULFILMENT_STORE = 9171   # what /api/v1/shell returns when no store is selected

# ── Standard headers ─────────────────────────────────────────────────────────
API_HEADERS = {
    "x-requested-with": "??",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-NZ,en;q=0.9",
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def load_cookie_jars() -> dict[str, dict[str, dict]]:
    """Load previously saved Playwright cookie jars from disk."""
    with open(COOKIE_JAR, "r") as f:
        return json.load(f)


def build_session_with_cookies(cookie_dict: dict[str, dict]) -> requests.Session:
    """
    Create a requests.Session, seed basic cookies from GET /, then overwrite
    with the Playwright-captured cookie jar (preserving domain scoping).
    """
    session = requests.Session()
    session.headers.update(API_HEADERS)

    # Seed baseline cookies from the homepage
    session.get(BASE_URL, timeout=15)

    # Overwrite with Playwright cookies
    session.cookies.clear()
    for name, info in cookie_dict.items():
        value  = info["value"]
        domain = info.get("domain") or "www.woolworths.co.nz"
        session.cookies.set(name, value, domain=domain, path="/")
    return session


def get_shell_context(session: requests.Session) -> dict:
    """GET /api/v1/shell and return the context dict (store info lives here)."""
    resp = session.get(f"{API_BASE}/shell", timeout=15)
    resp.raise_for_status()
    return resp.json().get("context", {})


def get_milk_3l_price(session: requests.Session) -> tuple[str | None, float | None, str | None]:
    """Return (product_name, salePrice, sku) for the first 3L milk found, or Nones."""
    resp = session.get(
        f"{API_BASE}/products",
        params={"target": "search", "search": "milk", "size": 5},
        timeout=15,
    )
    if resp.status_code != 200:
        return None, None, None
    for item in resp.json().get("products", {}).get("items", []):
        name = item.get("name", "")
        if "3l" in name.lower() or "3 l" in name.lower():
            try:
                return name, item["price"]["salePrice"], item.get("sku", "")
            except (KeyError, TypeError):
                pass
    return None, None, None


def cw_lrkswrdjp_summary(cookie_dict: dict[str, dict]) -> str | None:
    """Extract the cw-lrkswrdjp cookie value (encodes store context in-browser)."""
    info = cookie_dict.get("cw-lrkswrdjp")
    if info:
        return info.get("value", "")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1   --  /api/v1/shell store context validation
# ══════════════════════════════════════════════════════════════════════════════

def step1_shell_store_context():
    """
    For each store, inject its cookie jar into requests.Session and call
    /api/v1/shell.  The response's context.fulfilment block tells us what
    store the API *thinks* we have selected.

    If fulfilmentStoreId matches the store we captured cookies for  -> valid.
    If it matches 9171 (default)  -> cookies have expired or are not being sent.
    """
    print("\n" + "=" * 70)
    print("STEP 1: /api/v1/shell  -- store context validation")
    print("=" * 70)
    print("Goal: confirm injected cookies make the API recognise the correct store\n")

    jars = load_cookie_jars()
    results = {}

    for store_name in ["Greymouth", "Glenfield"]:
        expected = STORES[store_name]
        cookie_dict = jars.get(store_name, {})
        if not cookie_dict:
            print(f"  [!] No cookies found for {store_name}  -- run part2 first")
            continue

        print(f"--- {store_name} ---")
        print(f"  Expected: fulfilmentStoreId=?  (known pickupAddressId={expected['pickup_id']})")

        session = build_session_with_cookies(cookie_dict)
        ctx = get_shell_context(session)
        fulf = ctx.get("fulfilment", {})

        actual_store_id     = fulf.get("fulfilmentStoreId")
        actual_pickup_id    = fulf.get("pickupAddressId")
        actual_method       = fulf.get("method")
        actual_area_id      = fulf.get("areaId")
        actual_address      = fulf.get("address")
        actual_is_default   = fulf.get("isDefaultDeliveryAddress")
        actual_in_zone      = fulf.get("isAddressInDeliveryZone")

        print(f"  Shell returns:")
        print(f"    fulfilmentStoreId  = {actual_store_id}")
        print(f"    pickupAddressId    = {actual_pickup_id}")
        print(f"    method             = {actual_method}")
        print(f"    areaId             = {actual_area_id}")
        print(f"    address            = {actual_address}")
        print(f"    isDefaultDelivery  = {actual_is_default}")
        print(f"    isInDeliveryZone   = {actual_in_zone}")

        # Validation
        is_default = (actual_store_id == DEFAULT_FULFILMENT_STORE)
        if is_default:
            print(f"  [FAIL] fulfilmentStoreId={actual_store_id} is the DEFAULT -- cookies are not being recognised")
        else:
            print(f"  [OK]   fulfilmentStoreId={actual_store_id} is NOT the default -- cookies are active")

        # cw-lrkswrdjp analysis
        cw = cw_lrkswrdjp_summary(cookie_dict)
        if cw:
            print(f"  cw-lrkswrdjp = {cw}")
        else:
            print(f"  cw-lrkswrdjp = (not present in jar)")

        results[store_name] = {
            "fulfilmentStoreId": actual_store_id,
            "pickupAddressId": actual_pickup_id,
            "method": actual_method,
            "areaId": actual_area_id,
            "address": actual_address,
            "isDefault": is_default,
            "cw_lrkswrdjp": cw,
        }
        print()

    # ── Cross-compare ──
    print("-" * 70)
    print("Cross-comparison of shell contexts:")
    for store_name, res in results.items():
        print(f"  {store_name}: fulfilmentStoreId={res['fulfilmentStoreId']}, "
              f"pickupAddressId={res['pickupAddressId']}, method={res['method']}, "
              f"areaId={res['areaId']}, address={res['address']}")
    print()

    return results


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2   --  fulfilmentStoreId query param (no cookies)
# ══════════════════════════════════════════════════════════════════════════════

def step2_products_fulfilment_param():
    """
    Without Playwright cookies, test whether passing fulfilmentStoreId as a
    query parameter on /api/v1/products changes the response  -- both the
    shell context returned alongside it and the actual product prices.

    This is a fallback check: Phase 1 already showed this doesn't change
    pricing, but we want to see if it changes the *shell context* or
    product availability.
    """
    print("=" * 70)
    print("STEP 2: fulfilmentStoreId as query param (no Playwright cookies)")
    print("=" * 70)

    store_ids = [764300, 1190273]  # Greymouth, Glenfield
    results = {}

    for sid in store_ids:
        store_name = [k for k, v in STORES.items() if v["pickup_id"] == sid][0]
        print(f"\n--- {store_name} (fulfilmentStoreId={sid}) ---")

        session = requests.Session()
        session.headers.update(API_HEADERS)
        session.get(BASE_URL, timeout=15)

        # 1) Check /api/v1/shell with this param
        print(f"  [shell] GET /api/v1/shell?fulfilmentStoreId={sid}")
        shell_resp = session.get(
            f"{API_BASE}/shell",
            params={"fulfilmentStoreId": sid},
            timeout=15,
        )
        shell_ctx  = shell_resp.json().get("context", {}).get("fulfilment", {})
        shell_fid  = shell_ctx.get("fulfilmentStoreId")
        shell_pid  = shell_ctx.get("pickupAddressId")
        shell_addr = shell_ctx.get("address")
        shell_meth = shell_ctx.get("method")
        print(f"    fulfilmentStoreId = {shell_fid}")
        print(f"    pickupAddressId   = {shell_pid}")
        print(f"    address           = {shell_addr}")
        print(f"    method            = {shell_meth}")
        shell_changed = (shell_fid != DEFAULT_FULFILMENT_STORE)
        print(f"    Context changed?  {'YES' if shell_changed else 'NO (still default)'}")

        # 2) Check /api/v1/products with this param
        print(f"  [products] GET /api/v1/products?fulfilmentStoreId={sid}")
        prod_resp = session.get(
            f"{API_BASE}/products",
            params={"target": "search", "search": "milk", "size": 5, "fulfilmentStoreId": sid},
            timeout=15,
        )
        items = prod_resp.json().get("products", {}).get("items", [])
        for item in items:
            name = item.get("name", "")
            if "3l" in name.lower():
                price = item.get("price", {}).get("salePrice")
                print(f"    Milk 3L: ${price}  ({name})")
                results[store_name] = price

        time.sleep(0.3)

    # Comparison
    print("\n" + "-" * 70)
    print("Price comparison (expect $7.15 Greymouth vs $7.33 Glenfield if param works):")
    for store_name, price in results.items():
        print(f"  {store_name}: ${price}")
    if results:
        vals = list(results.values())
        if len(vals) > 1 and vals[0] == vals[1]:
            print("  [FAIL] Prices identical -- fulfilmentStoreId param does NOT affect pricing")
        elif len(vals) > 1:
            print("  [OK]   Prices differ -- fulfilmentStoreId param DOES affect pricing")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3   --  cw-lrkswrdjp cookie analysis
# ══════════════════════════════════════════════════════════════════════════════

def step3_cw_lrkswrdjp_analysis():
    """
    Deep-dive into the cw-lrkswrdjp cookie across stores.

    Observed format:
      Greymouth: dm-Pickup,f-9009,a-224,s-38
      Glenfield: dm-Pickup,f-9443,a-440,s-38

    Fields (hypothesis):
      dm  = delivery method (Pickup)
      f   = fulfilment store ID / area ID (not the same as pickupAddressId)
      a   = area ID
      s   = store segment / site ID (constant)

    Test:
      1. Load jars from disk, compare cw-lrkswrdjp across Greymouth/Glenfield/BASELINE
      2. Check whether injecting ONLY this cookie (plus session_state) is enough
         to shift /api/v1/shell's fulfilmentStoreId
      3. Compare prices with just cw-lrkswrdjp injected
    """
    print("\n" + "=" * 70)
    print("STEP 3: cw-lrkswrdjp cookie deep-dive")
    print("=" * 70)

    jars = load_cookie_jars()

    # ── 3a: Compare values across stores ─────────────────────────────────────
    print("\n[3a] cw-lrkswrdjp values per store:")
    cw_values = {}
    for label, jar in jars.items():
        cw = jar.get("cw-lrkswrdjp", {})
        val = cw.get("value", "(missing)") if isinstance(cw, dict) else str(cw)
        cw_values[label] = val
        print(f"  {label}: {val}")

    # Parse fields
    print("\nParsed fields:")
    for label, val in cw_values.items():
        if val == "(missing)":
            print(f"  {label}:  --")
            continue
        parts = val.split(",")
        parsed = {}
        for part in parts:
            k, _, v = part.partition("-")
            parsed[k] = v
        print(f"  {label}: dm={parsed.get('dm','?')}  f={parsed.get('f','?')}  "
              f"a={parsed.get('a','?')}  s={parsed.get('s','?')}")

    # ── 3b: Inject cw-lrkswrdjp + session_state only  -> check shell context ───
    print("\n[3b] Injecting cw-lrkswrdjp + session_state ONLY  -> /api/v1/shell")
    print("     (no other Playwright cookies  -- testing if these 2 are sufficient)\n")

    for store_name in ["Greymouth", "Glenfield"]:
        jar = jars.get(store_name, {})
        expected = STORES[store_name]

        # Filter to cw-lrkswrdjp + session_state
        target = {
            name: info
            for name, info in jar.items()
            if name == "cw-lrkswrdjp" or "session_state" in name.lower()
        }
        print(f"--- {store_name}: injecting {list(target.keys())} ---")

        session = requests.Session()
        session.headers.update(API_HEADERS)
        session.get(BASE_URL, timeout=15)
        session.cookies.clear()

        for name, info in target.items():
            domain = info.get("domain") or "www.woolworths.co.nz"
            session.cookies.set(name, info["value"], domain=domain, path="/")

        # Verify what's in the jar
        print(f"  Cookies in jar: {list(session.cookies.keys())}")

        ctx  = get_shell_context(session)
        fulf = ctx.get("fulfilment", {})
        print(f"  fulfilmentStoreId = {fulf.get('fulfilmentStoreId')}")
        print(f"  pickupAddressId   = {fulf.get('pickupAddressId')}")
        print(f"  address           = {fulf.get('address')}")
        print(f"  method            = {fulf.get('method')}")

        # Also check the price
        name, price, sku = get_milk_3l_price(session)
        if name:
            print(f"  Milk 3L price: ${price}  ({name})")
        else:
            print(f"  Milk 3L price: (not found in results)")
        print()

    # ── 3c: Inject cw-lrkswrdjp only (no session_state)  -> check shell ────────
    print("[3c] Injecting cw-lrkswrdjp ONLY  -> /api/v1/shell\n")

    for store_name in ["Greymouth", "Glenfield"]:
        jar = jars.get(store_name, {})
        cw = jar.get("cw-lrkswrdjp")
        if not cw:
            print(f"  {store_name}: cw-lrkswrdjp not found  -- skipping")
            continue

        target = {"cw-lrkswrdjp": cw}
        print(f"--- {store_name}: injecting cw-lrkswrdjp only ---")

        session = requests.Session()
        session.headers.update(API_HEADERS)
        session.get(BASE_URL, timeout=15)
        session.cookies.clear()

        for name, info in target.items():
            domain = info.get("domain") or "www.woolworths.co.nz"
            session.cookies.set(name, info["value"], domain=domain, path="/")

        ctx  = get_shell_context(session)
        fulf = ctx.get("fulfilment", {})
        print(f"  fulfilmentStoreId = {fulf.get('fulfilmentStoreId')}")
        print(f"  pickupAddressId   = {fulf.get('pickupAddressId')}")
        print(f"  address           = {fulf.get('address')}")

        name, price, sku = get_milk_3l_price(session)
        if name:
            print(f"  Milk 3L price: ${price}  ({name})")
        print()

    return cw_values


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4   --  BASELINE shell context (no cookies injected)
# ══════════════════════════════════════════════════════════════════════════════

def step4_baseline_shell():
    """
    Call /api/v1/shell with no Playwright cookies (vanilla requests session)
    to capture the default context for comparison.
    """
    print("=" * 70)
    print("STEP 4: BASELINE /api/v1/shell (no Playwright cookies)")
    print("=" * 70)

    session = requests.Session()
    session.headers.update(API_HEADERS)
    session.get(BASE_URL, timeout=15)

    ctx  = get_shell_context(session)
    fulf = ctx.get("fulfilment", {})
    print(f"  fulfilmentStoreId = {fulf.get('fulfilmentStoreId')}  (expected default: {DEFAULT_FULFILMENT_STORE})")
    print(f"  pickupAddressId   = {fulf.get('pickupAddressId')}")
    print(f"  address           = {fulf.get('address')}")
    print(f"  method            = {fulf.get('method')}")
    print(f"  areaId            = {fulf.get('areaId')}")

    name, price, sku = get_milk_3l_price(session)
    if name:
        print(f"  Milk 3L price: ${price}  ({name})")
    return fulf


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("Woolworths Cookie Validation  -- Phase 2 (explore_woolworths_api_part3)")
    print("=" * 70)
    print("Validates stored cookie jars via /api/v1/shell and product pricing.\n")
    print("Prerequisites: run explore_woolworths_api_part2.py first to generate")
    print(f"               {COOKIE_JAR}")

    # Step 4: Capture baseline first (for reference)
    step4_baseline_shell()

    # Step 1: Inject cookies  -> /api/v1/shell  -> check store context
    step1_shell_store_context()

    # Step 2: Test fulfilmentStoreId as query param (no cookies)
    step2_products_fulfilment_param()

    # Step 3: Deep-dive cw-lrkswrdjp cookie
    step3_cw_lrkswrdjp_analysis()

    print("\n" + "=" * 70)
    print("DONE.")
    print("=" * 70)
    print("""
Key questions answered:
  1. Does /api/v1/shell reflect the correct store when cookies are injected?
      -> Check Step 1 output: fulfilmentStoreId should NOT be 9171

  2. Does fulfilmentStoreId as a query param change shell context or prices?
      -> Check Step 2 output: prices and context should remain unchanged

  3. Is cw-lrkswrdjp the key per-store cookie?
      -> Check Step 3 output: injecting just this cookie (+session_state)
        should shift the shell context if it is the carrier
""")


if __name__ == "__main__":
    main()
