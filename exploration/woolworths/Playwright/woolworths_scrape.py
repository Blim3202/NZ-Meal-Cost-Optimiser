import os
import time
import re
from playwright.sync_api import sync_playwright

URL = "https://www.woolworths.co.nz/"
SEARCH_TERM = "milk"
OUT_DIR = os.path.join(".", ".Temp")
MAX_PRODUCTS = 20


def scrape_woolworths(search_term: str) -> list[dict]:
    """
    Launch headed Chromium, navigate to Woolworths search results,
    and extract product data directly from the rendered DOM.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-default-browser-check",
            ],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            locale="en-NZ",
            timezone_id="Pacific/Auckland",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        print("Navigating to homepage...")
        resp = page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        print(f"Homepage status: {resp.status}")
        print(f"Homepage final URL: {page.url}")

        print("\nNavigating to search results...")
        page.goto(
            f"{URL}shop/searchproducts?search={search_term}",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        time.sleep(12)
        print(f"Search final URL: {page.url}")
        print(f"Search title: {page.title()}")

        # Save full rendered HTML for offline inspection / debugging
        html = page.content()
        os.makedirs(OUT_DIR, exist_ok=True)
        out_path = os.path.join(OUT_DIR, "woolworths_search_full.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nSaved HTML dump -> {out_path}")
        print(f"HTML length: {len(html)}")

        # Diagnostic: look for common app-state markers
        markers = [
            "window.__INITIAL_STATE__",
            "window.__APOLLO_STATE__",
            "window.__NEXT_DATA__",
            "self.__next_f",
            "ng-state",
        ]
        found = [m for m in markers if m in html]
        if found:
            for m in found:
                idx = html.find(m)
                print(f"Found marker: {m} ...{html[idx:idx+120]}...")
        else:
            print("No standard app-state markers found.")

        # Extract up to MAX_PRODUCTS from the live DOM.
        # Each product lives in a <product-stamp-grid> > .product-entry
        # and exposes:
        #   - title:   h3[id$="-title"]
        #   - unitPrice:  [id$="-unitPrice"] .cupPrice
        #   - price:   [id$="-price"]  (use aria-label for clean value)
        products = page.evaluate(
            """(limit) => {
                const entries = Array.from(
                    document.querySelectorAll('product-stamp-grid .product-entry')
                );
                const out = [];
                for (const el of entries.slice(0, limit)) {
                    try {
                        const titleEl = el.querySelector('h3[id$="-title"]');
                        const unitEl  = el.querySelector('[id$="-unitPrice"] .cupPrice');
                        const priceEl = el.querySelector('[id$="-price"]');
                        const name = titleEl ? titleEl.innerText.trim() : '';
                        const unit = unitEl ? unitEl.innerText.trim() : '';
                        const price = priceEl
                            ? (priceEl.getAttribute('aria-label') || priceEl.innerText || '')
                            : '';
                        out.push({ name, unitPrice: unit, actualPrice: price });
                    } catch (_) { /* skip broken entries */ }
                }
                return out;
            }""",
            MAX_PRODUCTS,
        )

        browser.close()
        return products


def format_table(products: list[dict]) -> str:
    """Build a simple aligned table from the extracted product list."""
    headers = ["#", "Product", "Unit Cost", "Actual Price"]
    rows = []
    for i, p in enumerate(products, 1):
        rows.append(
            [
                str(i),
                p.get("name", "—")[:45],
                p.get("unitPrice", "—"),
                p.get("actualPrice", "—"),
            ]
        )

    col_widths = [len(h) for h in headers]
    for row in rows:
        for j, cell in enumerate(row):
            col_widths[j] = max(col_widths[j], len(cell))

    def fmt(cells):
        return " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(cells))

    separator = "-+-".join("-" * w for w in col_widths)
    lines = [fmt(headers), separator]
    for row in rows:
        lines.append(fmt(row))
    return "\n".join(lines)


def main():
    products = scrape_woolworths(SEARCH_TERM)
    print(f"\nExtracted {len(products)} product(s) \n")
    if products:
        print(format_table(products))
    else:
        print("No products could be extracted.")


if __name__ == "__main__":
    main()
