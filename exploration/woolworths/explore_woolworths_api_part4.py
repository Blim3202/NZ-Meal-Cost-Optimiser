"""
explore_woolworths_api_part4.py
=================================
Phase 3: Programmatic cw-lrkswrdjp cookie construction and price validation.

Background
----------
Phase 2 (part3) discovered that the cw-lrkswrdjp cookie alone controls the entire
store context.  Its format is: dm-Pickup,f-{fulfilmentStoreId},a-{areaId},s-38

Phase 2 also showed:
  - Injecting this 1 cookie correctly shifts /api/v1/shell context
  - fulfilmentStoreId as a URL param does NOT work
  - The a- and s- fields are optional (cookie works without them)

However, the fulfilmentStoreId and areaId are NOT available from the API -- they
are internal IDs set by Woolworths' JavaScript when a store is selected.  We
capture them via Playwright once, then construct cookies programmatically.

This script:
  Step 1: Capture cw-lrkswrdjp for a set of nearby stores via Playwright (one-time)
  Step 2: Save the mapping (pickupAddressId -> fulfilmentStoreId, areaId) to disk
  Step 3: Load mapping from disk, construct cookies, inject into requests.Session
  Step 4: Validate via /api/v1/shell (check fulfilmentStoreId matches expected)
  Step 5: Validate via /api/v1/products (check per-store pricing)
  Step 6: Compare programmatic construction vs Playwright-captured cookies

Known targets
  Greymouth (pickupAddressId 764300): Milk 3L = $7.15
  Glenfield  (pickupAddressId 1190273): Milk 3L = $7.33
"""

import os, sys, json, time, asyncio
import requests

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "exploration", "woolworths"))
MAPPING_FILE = os.path.join(DATA_DIR, "store_id_mapping.json")
BASE_URL   = "https://www.woolworths.co.nz"
API_BASE   = f"{BASE_URL}/api/v1"



# ── Stores for testing ───────────────────────────────────────────────────────
# Format: display_name -> {pickup_id: pickupAddressId from API}
STORES_TO_CAPTURE = {
    "Woolworths Greymouth":  764300,
    "Woolworths Glenfield":  1190273,
    "Woolworths Birkenhead": 2124460,
}

# Known expected values for validation
EXPECTED = {
    764300:  {"fulfilmentStoreId": 9009, "areaId": 224, "price_3l": 7.15, "address": "Woolworths Greymouth"},
    1190273: {"fulfilmentStoreId": 9443, "areaId": 440, "price_3l": 7.33, "address": "Woolworths Glenfield"},
    2124460: {"fulfilmentStoreId": 9101, "areaId": 720, "price_3l": None,  "address": "Woolworths Birkenhead"},
}

DEFAULT_FULFILMENT_STORE = 9171

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

def build_cw_lrkswrdjp(fulfilment_store_id: int, area_id: int,
                        delivery_method: str = "Pickup", site: int = 38) -> str:
    """
    Construct the cw-lrkswrdjp cookie value from known store IDs.

    Format: dm-{delivery_method},f-{fulfilment_store_id},a-{area_id},s-{site}
    """
    return f"dm-{delivery_method},f-{fulfilment_store_id},a-{area_id},s-{site}"


def parse_cw_lrkswrdjp(value: str) -> dict:
    """Parse a cw-lrkswrdjp cookie value into its component fields."""
    result = {}
    for part in value.split(","):
        key, _, val = part.partition("-")
        result[key] = val
    return result


def build_session_with_cw_cookie(fulfilment_store_id: int, area_id: int) -> requests.Session:
    """
    Create a requests.Session, seed baseline cookies, then inject a
    programmatically constructed cw-lrkswrdjp cookie.
    """
    session = requests.Session()
    session.headers.update(API_HEADERS)
    session.get(BASE_URL, timeout=15)  # seed baseline cookies

    cookie_val = build_cw_lrkswrdjp(fulfilment_store_id, area_id)
    session.cookies.set("cw-lrkswrdjp", cookie_val,
                        domain="www.woolworths.co.nz", path="/")
    return session


def get_shell_context(session: requests.Session) -> dict:
    """GET /api/v1/shell and return the context dict."""
    resp = session.get(f"{API_BASE}/shell", timeout=15)
    resp.raise_for_status()
    return resp.json().get("context", {})


def get_milk_3l_price(session: requests.Session) -> tuple:
    """Return (product_name, salePrice, sku) for the first 3L milk found."""
    resp = session.get(
        f"{API_BASE}/products",
        params={"target": "search", "search": "milk", "size": 10},
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


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1  --  Playwright cookie capture (one-time)
# ══════════════════════════════════════════════════════════════════════════════

def step1_capture_cookies():
    """
    Use Playwright to capture cw-lrkswrdjp cookies for each store.
    Returns a mapping: pickupAddressId -> {fulfilmentStoreId, areaId, cw_lrkswrdjp}
    """
    from playwright.async_api import async_playwright

    print("\n" + "=" * 70)
    print("STEP 1: Playwright cookie capture (one-time)")
    print("=" * 70)

    if os.name == "nt":
        print("NOTE: A headed Chromium window WILL OPEN for each store.\n")
        time.sleep(2)

    async def run():
        mapping = {}
        modal_url = f"{BASE_URL}/bookatimeslot/(hww-modal:change-pick-up-store)"

        for display_name, pickup_id in STORES_TO_CAPTURE.items():
            print(f"Capturing: {display_name} (pickupAddressId={pickup_id})...")

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
                    locale="en-NZ",
                    timezone_id="Pacific/Auckland",
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                await page.goto(modal_url, wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(3)

                dropdown_sel = 'select[id*="area-dropdown"]'
                await page.wait_for_selector(dropdown_sel, timeout=30000)
                await page.locator(dropdown_sel).select_option(label="All Pick up locations")
                await asyncio.sleep(4)

                btn = page.get_by_role("button", name=display_name)
                try:
                    await btn.wait_for(state="visible", timeout=10000)
                    await btn.click()
                    print(f"  Clicked '{display_name}'")
                except Exception as e:
                    print(f"  FAILED: {e}")
                    await browser.close()
                    continue

                await asyncio.sleep(5)

                # Extract cookie
                cookies = await context.cookies()
                cookie_dict = {c["name"]: c["value"] for c in cookies}
                cw_val = cookie_dict.get("cw-lrkswrdjp")

                if not cw_val:
                    print(f"  FAILED: cw-lrkswrdjp not found in cookies")
                    await browser.close()
                    continue

                parsed = parse_cw_lrkswrdjp(cw_val)
                fsid = int(parsed.get("f", 0))
                aid  = int(parsed.get("a", 0))

                mapping[pickup_id] = {
                    "fulfilmentStoreId": fsid,
                    "areaId": aid,
                    "cw_lrkswrdjp": cw_val,
                    "name": display_name,
                }
                print(f"  -> fulfilmentStoreId={fsid}, areaId={aid}")
                print(f"  -> cw-lrkswrdjp = {cw_val}")

                await browser.close()

        return mapping

    return asyncio.run(run())


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2  --  Save mapping to disk
# ══════════════════════════════════════════════════════════════════════════════

def step2_save_mapping(mapping: dict):
    """Save the store ID mapping to JSON."""
    print("\n" + "=" * 70)
    print("STEP 2: Save mapping to disk")
    print("=" * 70)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MAPPING_FILE, "w") as f:
        json.dump(mapping, f, indent=2)
    print(f"Saved {len(mapping)} store mappings to {MAPPING_FILE}")

    # Summary table
    print("\nMapping summary:")
    print(f"  {'pickupAddressId':>15}  {'fulfilmentStoreId':>17}  {'areaId':>6}  Name")
    for pid, data in mapping.items():
        print(f"  {pid:>15}  {data['fulfilmentStoreId']:>17}  {data['areaId']:>6}  {data['name']}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3  --  Load mapping and construct cookies
# ══════════════════════════════════════════════════════════════════════════════

def step3_load_and_construct():
    """Load mapping from disk, construct cookies programmatically."""
    print("\n" + "=" * 70)
    print("STEP 3: Load mapping and construct cookies")
    print("=" * 70)

    with open(MAPPING_FILE) as f:
        mapping = json.load(f)

    print(f"Loaded {len(mapping)} store mappings\n")

    for pid, data in mapping.items():
        fsid = data["fulfilmentStoreId"]
        aid  = data["areaId"]
        cookie_val = build_cw_lrkswrdjp(fsid, aid)
        print(f"  {data['name']} (pickupAddressId={pid})")
        print(f"    Constructed: {cookie_val}")
        print(f"    Original:    {data['cw_lrkswrdjp']}")
        match = cookie_val == data["cw_lrkswrdjp"]
        print(f"    Match: {'YES' if match else 'NO'}")
        print()

    return mapping


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4  --  Validate via /api/v1/shell
# ══════════════════════════════════════════════════════════════════════════════

def step4_validate_shell(mapping: dict):
    """
    For each store, inject the programmatically constructed cw-lrkswrdjp cookie
    and call /api/v1/shell to verify the context matches.
    """
    print("\n" + "=" * 70)
    print("STEP 4: Validate constructed cookies via /api/v1/shell")
    print("=" * 70)

    results = {}

    for pid, data in mapping.items():
        fsid = data["fulfilmentStoreId"]
        aid  = data["areaId"]
        name = data["name"]

        print(f"\n--- {name} (pickupAddressId={pid}) ---")
        print(f"  Cookie: {build_cw_lrkswrdjp(fsid, aid)}")

        session = build_session_with_cw_cookie(fsid, aid)
        ctx  = get_shell_context(session)
        fulf = ctx.get("fulfilment", {})

        actual_fid  = fulf.get("fulfilmentStoreId")
        actual_pid  = fulf.get("pickupAddressId")
        actual_addr = fulf.get("address")
        actual_meth = fulf.get("method")

        print(f"  Shell: fulfilmentStoreId={actual_fid}  pickupAddressId={actual_pid}  "
              f"address={actual_addr}  method={actual_meth}")

        # Validate
        is_correct = (actual_fid == fsid and actual_pid == pid)
        is_default = (actual_fid == DEFAULT_FULFILMENT_STORE)

        if is_correct:
            print(f"  [OK] Context matches expected store")
        elif is_default:
            print(f"  [FAIL] Got default context -- cookie not recognised")
        else:
            print(f"  [WARN] Context mismatch: expected fsid={fsid}, got {actual_fid}")

        results[pid] = {
            "name": name,
            "expected_fsid": fsid,
            "actual_fsid": actual_fid,
            "actual_pid": actual_pid,
            "address": actual_addr,
            "correct": is_correct,
        }

    # Summary
    print("\n" + "-" * 70)
    print("Shell validation summary:")
    for pid, res in results.items():
        status = "[OK]" if res["correct"] else "[FAIL]"
        print(f"  {status} {res['name']}: expected fsid={res['expected_fsid']}, "
              f"got fsid={res['actual_fsid']} pid={res['actual_pid']}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5  --  Validate via /api/v1/products (pricing)
# ══════════════════════════════════════════════════════════════════════════════

def step5_validate_pricing(mapping: dict):
    """
    For each store with a known expected price, inject the constructed cookie
    and check if /api/v1/products returns the correct per-store price.
    """
    print("\n" + "=" * 70)
    print("STEP 5: Validate constructed cookies via /api/v1/products (pricing)")
    print("=" * 70)

    results = {}

    for pid, data in mapping.items():
        fsid = data["fulfilmentStoreId"]
        aid  = data["areaId"]
        name = data["name"]
        expected_price = EXPECTED.get(pid, {}).get("price_3l")

        print(f"\n--- {name} (pickupAddressId={pid}) ---")

        session = build_session_with_cw_cookie(fsid, aid)

        milk_name, milk_price, milk_sku = get_milk_3l_price(session)
        if milk_name:
            print(f"  Milk 3L: ${milk_price}  [{milk_sku}]  {milk_name}")
        else:
            print(f"  Milk 3L: NOT FOUND in top 10 results")

        if expected_price is not None:
            if milk_price == expected_price:
                print(f"  [OK] Price matches expected ${expected_price}")
            elif milk_price is not None:
                print(f"  [FAIL] Expected ${expected_price}, got ${milk_price}")
            else:
                print(f"  [WARN] Expected ${expected_price}, price unavailable")
        else:
            print(f"  (no expected price to compare)")

        results[pid] = {
            "name": name,
            "expected_price": expected_price,
            "actual_price": milk_price,
            "milk_name": milk_name,
            "milk_sku": milk_sku,
        }

    # Summary
    print("\n" + "-" * 70)
    print("Pricing validation summary:")
    for pid, res in results.items():
        exp = res["expected_price"]
        act = res["actual_price"]
        if exp is not None and act is not None:
            status = "[OK]" if act == exp else "[FAIL]"
            print(f"  {status} {res['name']}: expected ${exp}, got ${act}")
        else:
            print(f"  [N/A] {res['name']}: expected={exp}, actual={act}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6  --  Compare constructed vs captured cookies
# ══════════════════════════════════════════════════════════════════════════════

def step6_compare_methods(mapping: dict):
    """
    Compare prices when using:
      A) Programmatically constructed cw-lrkswrdjp cookie
      B) Full Playwright-captured cookie jar (from part2_cookies.json)
    """
    print("\n" + "=" * 70)
    print("STEP 6: Compare constructed cookie vs full Playwright jar")
    print("=" * 70)

    part2_jar_path = os.path.join(DATA_DIR, "part2_cookies.json")
    if not os.path.exists(part2_jar_path):
        print("  part2_cookies.json not found -- skipping full jar comparison")
        return

    with open(part2_jar_path) as f:
        jars = json.load(f)

    # Map store names to pickup IDs
    name_to_pid = {
        "Greymouth": 764300,
        "Glenfield": 1190273,
    }

    for store_label, pid in name_to_pid.items():
        jar = jars.get(store_label, {})
        data = mapping.get(str(pid), mapping.get(pid, {}))
        if not data:
            print(f"\n  {store_label}: not in mapping, skipping")
            continue

        fsid = data["fulfilmentStoreId"]
        aid  = data["areaId"]

        print(f"\n--- {store_label} (pickupAddressId={pid}) ---")

        # Method A: constructed cookie
        session_a = build_session_with_cw_cookie(fsid, aid)
        name_a, price_a, sku_a = get_milk_3l_price(session_a)

        # Method B: full Playwright jar
        session_b = requests.Session()
        session_b.headers.update(API_HEADERS)
        session_b.get(BASE_URL, timeout=15)
        session_b.cookies.clear()
        for cname, cinfo in jar.items():
            domain = cinfo.get("domain") or "www.woolworths.co.nz"
            session_b.cookies.set(cname, cinfo["value"], domain=domain, path="/")
        name_b, price_b, sku_b = get_milk_3l_price(session_b)

        print(f"  Constructed cookie: ${price_a}  ({name_a})")
        print(f"  Full Playwright jar: ${price_b}  ({name_b})")

        if price_a == price_b:
            print(f"  [OK] Prices match -- constructed cookie is sufficient")
        else:
            print(f"  [FAIL] Prices differ -- full jar may be needed")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("Woolworths Programmatic Cookie Construction (explore_woolworths_api_part4)")
    print("=" * 70)
    print(f"Mapping file: {MAPPING_FILE}\n")

    # Step 1: Capture cookies via Playwright
    mapping = step1_capture_cookies()

    # Step 2: Save mapping
    step2_save_mapping(mapping)

    # Step 3: Load and verify construction
    step3_load_and_construct()

    # Step 4: Validate via shell
    shell_results = step4_validate_shell(mapping)

    # Step 5: Validate pricing
    pricing_results = step5_validate_pricing(mapping)

    # Step 6: Compare constructed vs full jar
    step6_compare_methods(mapping)

    # Final summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    all_shell_ok = all(r["correct"] for r in shell_results.values())
    print(f"Shell validation: {'ALL PASSED' if all_shell_ok else 'SOME FAILED'}")

    priced = {pid: r for pid, r in pricing_results.items() if r["expected_price"] is not None}
    if priced:
        all_price_ok = all(r["actual_price"] == r["expected_price"] for r in priced.values())
        print(f"Pricing validation: {'ALL PASSED' if all_price_ok else 'SOME FAILED'}")
    else:
        print(f"Pricing validation: NO EXPECTED PRICES TO COMPARE")

    print(f"""
Key questions:
  1. Does the constructed cw-lrkswrdjp cookie shift /api/v1/shell context?
     -> Check Step 4 results
  2. Does the constructed cookie produce correct per-store PRICING?
     -> Check Step 5 results (Greymouth=$7.15, Glenfield=$7.33)
  3. Is the constructed cookie equivalent to the full Playwright jar?
     -> Check Step 6 results
  4. Can we build a mapping table for all 171 stores?
     -> Yes, capture cookies once, save mapping, reuse indefinitely
""")


if __name__ == "__main__":
    main()
