"""
explore_woolworths_api_part2.py
=================================
Phase 1: Per-store pricing exploration.

Goals:
1. Test if URL parameters on the GET / seed the right store-context cookies
   (user's hypothesis: visiting https://www.woolworths.co.nz/?pickupStoreId=xxx might
   set cookies that make the API return per-store prices)
2. If not, use Playwright to capture cookies from a real browser store-selection
   flow and inject them into a requests.Session to test

Known pricing:
  - Greymouth (id 764300): Woolworths Milk Standard Bottle 3L = $7.15
  - Glenfield  (id 1190273): Woolworths Milk Standard Bottle 3L = $7.33

Strategy:
  Step 1  Try requests only: seed session with different ?pickupStoreId= URL params
          and compare milk price from /api/v1/products
  Step 2  If no price change, fall back to Playwright: capture cookie jars for each
          store after selection, diff cookies, inject into requests.Session, test API
"""

import sys, os, math, time, json, asyncio, http.cookiejar
import requests
import pandas as pd
from playwright.async_api import async_playwright

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(SCRIPT_DIR, "data")
BASE_URL   = "https://www.woolworths.co.nz"
API_BASE   = f"{BASE_URL}/api/v1"

# ── Known store IDs ─────────────────────────────────────────────────────────
STORES = {
    "Greymouth": 764300,
    "Glenfield":  1190273,
}

MILK_SEARCH = "milk"
MILK_SIZE   = 5   # number of results to fetch

# ── Standard headers for API calls ──────────────────────────────────────────
API_HEADERS = {
    "x-requested-with": "??",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-NZ,en;q=0.9",
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def search_milk(session: requests.Session, size: int = MILK_SIZE) -> list[dict]:
    """Return milk product items from /api/v1/products."""
    resp = session.get(
        f"{API_BASE}/products",
        params={"target": "search", "search": MILK_SEARCH, "size": size},
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"  [!] API returned {resp.status_code}: {resp.text[:200]}")
        return []
    data = resp.json()
    return data.get("products", {}).get("items", [])


def milk_price_and_name(items: list[dict]) -> list[tuple[str, float, str]]:
    """Extract (product_name, salePrice, sku) from milk items."""
    results = []
    for it in items:
        try:
            name  = it.get("name", "")
            price = it["price"]["salePrice"]
            sku   = it.get("sku", "")
            results.append((name, price, sku))
        except (KeyError, TypeError):
            continue
    return results


def print_milk_prices(items: list[dict], label: str = ""):
    rows = milk_price_and_name(items)
    if not rows:
        print(f"  {label} No milk products returned.")
        return
    print(f"  {label} Milk products ({len(rows)} results):")
    for name, price, sku in rows:
        print(f"    ${price:.2f}  [{sku}]  {name}")


def cookie_jar_summary(jar: http.cookiejar.CookieJar) -> dict[str, str]:
    """Return a dict of cookie name → value for all cookies in the jar."""
    return {cookie.name: cookie.value for cookie in jar}


def diff_cookies(jar1: dict, jar2: dict) -> tuple[dict, dict]:
    """Return cookie entries only in jar1, and only in jar2. Handles both
    {name: str} and {name: {"value": ..., "domain": ...}} formats."""
    set1, set2 = set(jar1), set(jar2)
    return {k: jar1[k] for k in set1 - set2}, {k: jar2[k] for k in set2 - set1}


def _fmt_val(v) -> str:
    """Safely stringify a cookie value for printing."""
    if isinstance(v, dict):
        return v.get("value", "")[:50]
    return str(v)[:50]


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1  —  requests + URL-parameter seeding
# ══════════════════════════════════════════════════════════════════════════════

def step1_url_param_seeding():
    """
    Test if visiting the homepage with different ?pickupStoreId= URL parameters
    causes the /api/v1/products API to return different prices.

    We test three seed URLs:
      1. https://www.woolworths.co.nz/               (baseline — no param)
      2. https://www.woolworths.co.nz/?pickupStoreId=764300  (Greymouth)
      3. https://www.woolworths.co.nz/?pickupStoreId=1190273 (Glenfield)
    """
    print("\n" + "=" * 70)
    print("STEP 1: URL-param session seeding  (requests only, no Playwright)")
    print("=" * 70)

    results = {}

    for label, store_id in [("BASELINE (no param)", None),
                             ("Greymouth (?pickupStoreId=764300)", 764300),
                             ("Glenfield  (?pickupStoreId=1190273)", 1190273)]:

        session = requests.Session()
        session.headers.update(API_HEADERS)

        # Seed URL
        seed_url = BASE_URL if store_id is None else f"{BASE_URL}/?pickupStoreId={store_id}"
        print(f"\n[{label}]")
        print(f"  Seed URL: {seed_url}")

        try:
            r = session.get(seed_url, timeout=15)
            print(f"  Homepage ---> {r.status_code}  (cookies: {len(session.cookies)})")
        except Exception as e:
            print(f"  [!] Homepage request failed: {e}")
            continue

        # Show cookies
        cj = cookie_jar_summary(session.cookies)
        ww_cookies  = {k: v for k, v in cj.items() if "woolworths" in k.lower() or "countdown" in k.lower()}
        print(f"  Site cookies: {len(ww_cookies)}")
        for k, v in ww_cookies.items():
            print(f"    {k}: {v[:40]}...")

        # API call
        items   = search_milk(session)
        rows    = milk_price_and_name(items)
        results[label] = rows
        print_milk_prices(items, label)

    # ── Compare ────────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("PRICE COMPARISON  (looking for $7.15 Greymouth vs $7.33 Glenfield)")
    for label, rows in results.items():
        for name, price, sku in rows:
            if "3l" in name.lower() or "3 L" in name.lower():
                print(f"  {label}: ${price:.2f} — {name}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2  —  Playwright cookie capture + injection
# ══════════════════════════════════════════════════════════════════════════════

async def _playwright_capture_cookies(store_name: str, store_id: int) -> dict:
    """
    Use Playwright (headed) to:
      1. Navigate to the store-selection modal
      2. Select the named store
      3. Return the full cookie dict with domain info: {name: {value, domain, ...}}
    """
    modal_url = f"{BASE_URL}/bookatimeslot/(hww-modal:change-pick-up-store)"

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

        store_btn = page.get_by_role("button", name=store_name)
        try:
            await store_btn.wait_for(state="visible", timeout=10000)
            await store_btn.click()
            print(f"  [Playwright] Clicked '{store_name}' (id={store_id})")
        except Exception as e:
            print(f"  [Playwright] Could not find button for '{store_name}': {e}")
            await browser.close()
            return {}

        await asyncio.sleep(5)

        cookies = await context.cookies()
        await browser.close()

    # Return full cookie dict so we can preserve domain info on injection
    return {c["name"]: {"value": c["value"], "domain": c.get("domain", None)}
            for c in cookies}


def step2_playwright_injection():
    """
    Phase 2a: Capture cookie jars for Greymouth and Glenfield via Playwright,
              then inject into requests.Session and test API pricing.

    Phase 2b: Also capture the BASELINE (no store selected) cookie jar.
    """
    print("\n" + "=" * 70)
    print("STEP 2: Playwright cookie capture + requests injection")
    print("=" * 70)

    if os.name == "nt":
        print("\nNOTE: A headed Chromium window WILL OPEN for each store.")
        print("It will be visible on-screen. Press Ctrl+C to abort.\n")
        time.sleep(3)

    async def run():
        jars = {}
        for store_name, store_id in STORES.items():
            print(f"\n[Capturing cookies for {store_name} (id={store_id})...]")
            jars[store_name] = await _playwright_capture_cookies(store_name, store_id)
            print(f"  Captured {len(jars[store_name])} cookies")

        # Also capture baseline (no store selected)
        print("\n[Capturing BASELINE cookies (no store selected)...]")
        modal_url = f"{BASE_URL}/bookatimeslot/(hww-modal:change-pick-up-store)"
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False,
                args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
                locale="en-NZ",
                timezone_id="Pacific/Auckland",
            )
            page = await context.new_page()
            await page.goto(modal_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)
            # DO NOT select a store — just close immediately
            cookies = await context.cookies()
            jars["BASELINE"] = {c["name"]: {"value": c["value"], "domain": c.get("domain", None)}
                            for c in cookies}
            await browser.close()

        print(f"\nBaseline cookies: {len(jars['BASELINE'])}")

        # Print cookie diff between Greymouth and Glenfield
        greymouth_cookies = jars.get("Greymouth", {})
        glenfield_cookies  = jars.get("Glenfield",  {})
        only_g, only_gf = diff_cookies(greymouth_cookies, glenfield_cookies)

        print(f"\nCookies only in Greymouth: {len(only_g)}")
        for k, v in only_g.items():
            print(f"  {k}: {_fmt_val(v)}")
        print(f"\nCookies only in Glenfield: {len(only_gf)}")
        for k, v in only_gf.items():
            print(f"  {k}: {_fmt_val(v)}")

        # ── Inject cookies into requests.Session and call API ──────────────
        print("\n" + "-" * 70)
        print("API price check — injecting Playwright cookies into requests.Session")

        results = {}
        for label, cookie_dict in [
            ("BASELINE (no store)", jars.get("BASELINE", {})),
            ("Greymouth (from Playwright)", greymouth_cookies),
            ("Glenfield  (from Playwright)", glenfield_cookies),
        ]:
            session = requests.Session()
            session.headers.update(API_HEADERS)

            # Seed basic cookies first
            session.get(BASE_URL, timeout=15)

            # Overwrite with Playwright cookies — preserve original domain from Playwright
            session.cookies.clear()
            for name, info in cookie_dict.items():
                value  = info["value"]
                domain = info.get("domain") or "www.woolworths.co.nz"
                session.cookies.set(name, value, domain=domain, path="/")

            print(f"\n[{label}]")
            cj = cookie_jar_summary(session.cookies)
            ww_c = {k: v for k, v in cj.items()
                    if "woolworths" in k.lower() or "countdown" in k.lower()}
            print(f"  Site cookies in session: {len(ww_c)}")
            for k, v in ww_c.items():
                print(f"    {k}: {v[:60]}")

            items = search_milk(session)
            results[label] = milk_price_and_name(items)
            print_milk_prices(items, label)

        # ── Final comparison ──────────────────────────────────────────────
        print("\n" + "-" * 70)
        print("FINAL COMPARISON  (target: Greymouth $7.15, Glenfield $7.33)")
        for label, rows in results.items():
            for name, price, sku in rows:
                if "3l" in name.lower() or "3 L" in name.lower():
                    print(f"  {label}: ${price:.2f} — {name}")

        # ── STEP 2b: Is session_state cookie alone sufficient? ──────────────
        print("\n" + "-" * 70)
        print("STEP 2b: Testing session_state cookie ONLY (no RT/Analytics cookie)")
        print("-" * 70)

        greymouth_full = jars.get("Greymouth", {})
        glenfield_full = jars.get("Glenfield", {})

        for store_label, jar in [("Greymouth", greymouth_full),
                                  ("Glenfield",  glenfield_full)]:
            # Filter to only session_state cookie
            session_state_cookies = {
                name: info
                for name, info in jar.items()
                if "session_state" in name.lower()
            }
            print(f"\n[{store_label}] session_state cookie(s): {len(session_state_cookies)}")
            for name in session_state_cookies:
                print(f"  {name[:60]}...")

            # Inject ONLY the session_state cookie(s)
            session = requests.Session()
            session.headers.update(API_HEADERS)
            session.get(BASE_URL, timeout=15)
            session.cookies.clear()
            for name, info in session_state_cookies.items():
                domain = info.get("domain") or "www.woolworths.co.nz"
                session.cookies.set(name, info["value"], domain=domain, path="/")

            items = search_milk(session)
            rows  = milk_price_and_name(items)
            print_milk_prices(items, f"{store_label} (session_state ONLY)")
            results[f"{store_label} (session_state ONLY)"] = rows

        # ── STEP 2c: RT + session_state combo ─────────────────────────────────
        print("\n" + "-" * 70)
        print("STEP 2c: Testing session_state + RT TOGETHER")
        print("-" * 70)

        for store_label, jar in [("Greymouth", greymouth_full),
                                  ("Glenfield",  glenfield_full)]:
            # Filter to session_state + RT cookies only
            target_cookies = {
                name: info
                for name, info in jar.items()
                if "session_state" in name.lower() or name == "RT"
            }
            print(f"\n[{store_label}] Cookies being injected: {[n[:40] for n in target_cookies]}")

            session = requests.Session()
            session.headers.update(API_HEADERS)
            session.get(BASE_URL, timeout=15)
            session.cookies.clear()
            for name, info in target_cookies.items():
                domain = info.get("domain") or "www.woolworths.co.nz"
                session.cookies.set(name, info["value"], domain=domain, path="/")

            # Verify what actually got into the jar
            cj = cookie_jar_summary(session.cookies)
            print(f"  Cookies actually in jar: {list(cj.keys())}")

            items = search_milk(session)
            rows  = milk_price_and_name(items)
            for name, price, sku in rows:
                if "3l" in name.lower():
                    print(f"  --> Woolworths Milk 3L [{sku}]: ${price:.2f}")
            results[f"{store_label} (RT+session_state)"] = rows

        # Save cookies for debugging
        out = os.path.join(DATA_DIR, "part2_cookies.json")
        with open(out, "w") as f:
            json.dump(jars, f, indent=2)
        print(f"\nCookie jars saved to {out}")

        return results

    return asyncio.run(run())


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3  —  Explore session endpoint parameters
# ══════════════════════════════════════════════════════════════════════════════

def step3_session_params():
    """
    The user suggested: maybe different parameters on the GET / request itself
    can populate different cookies (rather than injecting Playwright cookies).

    Test: visit / with different query strings and see if the resulting
    cookie set differs or if API prices differ.
    """
    print("\n" + "=" * 70)
    print("STEP 3: Exploring GET / with different URL parameters")
    print("=" * 70)

    test_urls = [
        ("base /",                                 f"{BASE_URL}/"),
        ("/?pickupStoreId=764300",                 f"{BASE_URL}/?pickupStoreId=764300"),
        ("/?pickupStoreId=1190273",                f"{BASE_URL}/?pickupStoreId=1190273"),
        ("/?storeId=764300",                       f"{BASE_URL}/?storeId=764300"),
        ("/?storeId=764300&pickupStoreId=764300",  f"{BASE_URL}/?storeId=764300&pickupStoreId=764300"),
        ("/shop/searchproducts?search=milk",       f"{BASE_URL}/shop/searchproducts?search=milk"),
        ("/bookatimeslot/(hww-modal:change-pick-up-store)",
                                                    f"{BASE_URL}/bookatimeslot/(hww-modal:change-pick-up-store)"),
    ]

    all_cookies = {}

    for label, url in test_urls:
        session = requests.Session()
        session.headers.update(API_HEADERS)
        try:
            r = session.get(url, timeout=15)
        except Exception as e:
            print(f"\n[{label}] FAIL: {e}")
            continue

        cj = cookie_jar_summary(session.cookies)
        ww = {k: v for k, v in cj.items()
              if any(x in k.lower() for x in ["woolworths", "countdown", "shop", "session"])}
        all_cookies[label] = ww

        print(f"\n[{label}] ---> {r.status_code}")
        print(f"  Cookies ({len(ww)}): {list(ww.keys())}")

        # Quick API call
        items = search_milk(session)
        rows  = milk_price_and_name(items)
        print_milk_prices(items, label)

    return all_cookies


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("Woolworths Per-Store Pricing — Phase 1 Exploration")
    print("=" * 70)
    print(f"Target: Greymouth $7.15 vs Glenfield $7.33 for 3L standard milk")

    # ── Step 1: Simple URL-param seeding (no Playwright needed) ─────────────
    step1_url_param_seeding()

    # ── Step 2: Playwright cookie capture + injection ─────────────────────
    step2_playwright_injection()

    # ── Step 3: Explore GET / with different URL parameters ────────────────
    step3_session_params()

    print("\n" + "=" * 70)
    print("DONE. Check output above for any price differences.")
    print("If prices differ by store, we have found per-store pricing via cookies.")
    print("=" * 70)


if __name__ == "__main__":
    main()