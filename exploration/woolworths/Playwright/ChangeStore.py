import os
import time
from playwright.sync_api import sync_playwright

# Configuration
# Go straight to the store change dropdown url
MODAL_URL = "https://www.woolworths.co.nz/bookatimeslot/(hww-modal:change-pick-up-store)"
OUT_DIR = os.path.join(".", ".Temp")
STORE = "Woolworths Birkenhead"
os.makedirs(OUT_DIR, exist_ok=True)


def save_html(page, step_name):
    """Save rendered DOM after a major step."""
    html = page.content()
    out_path = os.path.join(OUT_DIR, f"woolworths_{step_name}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved HTML to {out_path}")
    return out_path

def main():
    print("Starting Woolworths Birkenhead selection test...")

    with sync_playwright() as p:
        print("Launching headed Chromium...")
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-default-browser-check",
            ],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/138.0.0.0 Safari/537.36",
            locale="en-NZ",
            timezone_id="Pacific/Auckland",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # Step 1: Navigate directly to modal
        print(f"Navigating to {MODAL_URL}...")
        page.goto(MODAL_URL, wait_until="domcontentloaded", timeout=60000)

        # Step 2: Dropdown Selection
        dropdown_selector = 'select[id*="area-dropdown"]' # Selects the element if the ID contains "area-dropdown" anywhere (should be dropdown 0)
        page.wait_for_selector(dropdown_selector, timeout=30000)
        dropdown = page.locator(dropdown_selector)
        
        # Select "All Pick up locations"
        dropdown.select_option(label="All Pick up locations") # Selects the drop down with the "All Pick up locations option"
        time.sleep(5) # Allow list to update
        save_html(page, "after_dropdown")


        # Step 3: Select Birkenhead
        print(f"Selecting '{STORE}'...")
        # Find the button with text e.g, "Woolworths Birkenhead"
        # Using get_by_role for robust matching
        store_btn = page.get_by_role("button", name=STORE)
        
        # Wait for button to be clickable
        store_btn.wait_for(state="visible", timeout=10000)
        store_btn.click()
        
        print(f"Clicked '{STORE}'. Waiting for UI update...")
        time.sleep(10) # Wait for selection process to complete
        save_html(page, "after_selection")

        print("Test completed.")
        browser.close()

if __name__ == "__main__":
    main()