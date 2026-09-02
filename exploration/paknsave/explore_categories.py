"""
Discover all category1 values from the Pak'nSave Edge API.

Two discovery methods:
  1. Edge API categories endpoint (GET /v1/edge/store/{id}/categories)
  2. Algolia search hits (collecting unique category1 arrays from broad queries)

The categories endpoint gives us the navigation tree.  The Algolia hits
give us the actual category1 values that appear on products in the search
index — these are what we filter on in Pass 1 of the two-pass pipeline.

Usage:
    python -m exploration.paknsave.explore_categories
"""


import sys
import json
import time
import requests
from collections import Counter
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─── Constants ────────────────────────────────────────────────────────────
WEB_BASE = "https://www.paknsave.co.nz"
EDGE_BASE = "https://api-prod.paknsave.co.nz/v1/edge"

# Broad queries designed to trigger many different product categories.
# Single letters and short common words pull in the widest variety.
BROAD_QUERIES = [
    # single letters — each matches thousands of products across all depts
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "r", "s", "t", "v", "w",
    # proteins
    "beef", "chicken", "lamb", "pork", "fish", "salmon", "tuna", "prawn",
    "shrimp", "mussels", "oyster", "crab", "duck", "turkey", "venison",
    "bacon", "ham", "salami", "prosciutto", "pepperoni", "mince", "steak",
    "sausage", "meatballs", "roast", "chops", "ribs", "wagyu", "kangaroo",
    # dairy & eggs
    "milk", "cheese", "egg", "butter", "yoghurt", "yogurt", "cream",
    "sour cream", "cream cheese", "parmesan", "cheddar", "mozzarella",
    "feta", "ricotta", "cottage cheese", "margarine", "ghee",
    # bakery & grains
    "bread", "rice", "pasta", "noodles", "flour", "tortilla", "wrap",
    "bagel", "muffin", "croissant", "baguette", "sourdough", "naan",
    "pita", "flatbread", "croutons", "breadcrumbs", "oats", "cereal",
    "granola", "muesli", "weetbix", "cornflakes",
    # fruits
    "apple", "banana", "orange", "lemon", "lime", "grape", "strawberry",
    "blueberry", "raspberry", "blackberry", "mango", "pineapple", "kiwi",
    "peach", "pear", "plum", "cherry", "watermelon", "melon", "coconut",
    "avocado", "tomato", "olive",
    # vegetables
    "onion", "potato", "carrot", "broccoli", "cauliflower", "spinach",
    "lettuce", "cabbage", "capsicum", "pepper", "cucumber", "zucchini",
    "mushroom", "pumpkin", "corn", "peas", "beans", "broccolini",
    "beetroot", "courgette", "kumara", "leek", "celery", "asparagus",
    "eggplant", "brussels sprouts", " kale", "silverbeet",
    # spices, herbs & seasonings
    "salt", "pepper", "garlic", "ginger", "cumin", "paprika", "turmeric",
    "cinnamon", "oregano", "basil", "thyme", "rosemary", "parsley",
    "coriander", "chilli", "cayenne", "nutmeg", "saffron", "mixed herbs",
    "herbs", "spice", "seasoning", "stock powder",
    # sauces & condiments
    "sauce", "ketchup", "mustard", "mayonnaise", "mayo", "relish",
    "chutney", "pickle", "vinegar", "soy sauce", "worcestershire",
    "hot sauce", "tabasco", "sriracha", "oyster sauce", "fish sauce",
    "teriyaki", "bbq sauce", "tomato sauce", "pesto", "tahini",
    "horseradish", "mint sauce", "gravy", "marinade", "dressing",
    "dip", "salsa", "harissa", "miso", "wasabi",
    # cooking essentials
    "oil", "olive oil", "vegetable oil", "coconut oil", "sesame oil",
    "baking soda", "baking powder", "yeast", "sugar", "honey", "maple syrup",
    "cornflour", "cornstarch", "gelatine", "food colouring", "vanilla",
    "chocolate", "cocoa", "icing",
    # drinks
    "water", "juice", "beer", "wine", "coffee", "tea", "soft drink",
    "energy drink", "kombucha", "cordial", "milkshake", "smoothie",
    "sparkling water", "tonic", "soda", "lemonade",
    # frozen
    "frozen", "ice cream", "icecream", "ice block", "sorbet", "gelato",
    "frozen vegetables", "frozen fruit", "frozen pizza", "frozen meal",
    "frozen chips", "frozen nuggets", "frozen fish", "frozen peas",
    "frozen corn", "frozen berries", "frozen spinach",
    # prepared & packaged
    "soup", "stew", "curry", "ready meal", "microwave", "instant",
    "pizza", "pie", "sushi", "sandwich", "salad", "snack",
    "cracker", "chip", "crisp", "popcorn", "pretzel", "nut", "almond",
    "cashew", "peanut", "walnut", "pecan", "muesli bar", "granola bar",
    # canned & jarred
    "canned", "tinned", "diced tomatoes", "baked beans", "chickpeas",
    "lentils", "kidney beans", "coconut milk", "tuna", "sardines",
    "corned beef", "condensed milk", "jam", "marmalade", "vegemite",
    "peanut butter", "almond butter", "tahini",
    # baby & toddler
    "baby", "baby food", "baby formula", "infant", "toddler", "nappy",
    "nappies", "diaper", "baby wipes", "baby bath", "baby lotion",
    "baby shampoo", "dummy", "pacifier", "teething", "baby bottle",
    "baby rice", "puree", "baby cereal",
    # pet
    "dog", "cat", "pet", "dog food", "cat food", "pet food", "treats",
    "dog treat", "cat treat", "kibble", "bird", "fish food",
    # household & cleaning
    "detergent", "laundry", "fabric softener", "bleach", "cleaner",
    "disinfectant", "antibacterial", "surface spray", "floor cleaner",
    "toilet cleaner", "bathroom cleaner", "glass cleaner", "mould",
    "dishwashing", "dishwasher", "sponge", "cloth", "bin bag",
    "garbage bag", " cling wrap", "al foil", "baking paper",
    "zip lock", "food wrap", "paper towel", "toilet paper", "tissue",
    "facial tissue", "napkin", "serviette",
    # personal care — hair
    "shampoo", "conditioner", "hair treatment", "hair oil", "hair gel",
    "hair spray", "hair colour", "hair dye", "dry shampoo", "mousse",
    "leave in conditioner", "serum",
    # personal care — skin & body
    "soap", "body wash", "moisturiser", "lotion", "cream",
    "deodorant", "antiperspirant", "sunscreen", "sunblock",
    "lip balm", "hand cream", "body cream", "exfoliant", "scrub",
    "tanning", "self tan",
    # personal care — oral
    "toothpaste", "toothbrush", "mouthwash", "dental floss",
    "interdental", "denture",
    # personal care — other
    "razor", "shaving", "aftershave", "perfume", "cologne",
    "cotton buds", "cotton pads", "makeup", "cosmetic",
    "nail polish", "nail remover",
    # feminine & continence care
    "tampon", "pad", "sanitary", "menstrual", "period",
    "incontinence", "continence", "panty liner",
    # health & pharmacy
    "vitamin", "supplement", "mineral", "probiotic", "fish oil",
    "protein powder", "magnesium", "iron", "calcium", "zinc",
    "pharmacy", "medicine", "paracetamol", "ibuprofen", "aspirin",
    "antihistamine", "cold flu", "cough", "throat", "sinus",
    "allergy", "antacid", "indigestion", "laxative", "diarrhoea",
    "first aid", "bandage", "plaster", "antiseptic", "cream",
    "ointment", "thermometer", "blood pressure", "glucose",
    "diabetes", "insulin", "asthma", "inhaler",
    # baby & child health
    "nappy rash", "teething gel", "infant pain",
    # entertainment & stationery
    "toy", "game", "puzzle", "board game", "card game", "lego",
    "doll", "action figure", "stuffed animal", "plush",
    "colouring", "crayon", "pencil", "pen", "marker", "highlighter",
    "notebook", "exercise book", "scissors", "glue", "tape",
    "ruler", "eraser", "sharpener", "stapler", "staples",
    "paper", "printing paper", "copy paper", "card",
    "gift wrap", "ribbon", "bow", "balloon", "party",
    "magazine", "book", "comic", "colouring book",
    # household & kitchenware
    "kitchen", "cookware", "frying pan", "saucepan", "baking tray",
    "roasting dish", "casserole", "utensil", "spatula", "tongs",
    "ladle", "whisk", "colander", "mixing bowl", "measuring cup",
    "chopping board", "knife", "can opener", "corkscrew",
    "storage", "container", "lid", "jug", "cup", "mug",
    "glass", "plate", "bowl", "dish", "tray",
    # laundry & home
    "hanger", "peg", "clothesline", "iron", "ironing board",
    "vacuum", "broom", "mop", "bucket", "dustpan",
    "bin", "recycling", "compost",
    # outdoor & garden
    "garden", "plant", "pot", "soil", "fertiliser", "mulch",
    "seed", "seedling", "flower", "tree", "shrub",
    "lawn", "mower", "hose", "sprinkler", "nozzle",
    "outdoor", "furniture", "umbrella", "shade", "tent",
    "camping", "lantern", "torch", "battery",
    # clothing & accessories
    "clothing", "shirt", "pants", "shorts", "skirt", "dress",
    "jacket", "hoodie", "sweater", "jumper", "vest",
    "underwear", "socks", "tights", "leggings",
    "hat", "cap", "beanie", "scarf", "gloves",
    "shoe", "sandal", "slipper", "boot",
    "bag", "backpack", "handbag", "wallet", "purse",
    "belt", "tie", "sunglasses", "watch", "jewellery",
    "umbrella",
    # automotive
    "car", "vehicle", "motor oil", "coolant", "windscreen",
    "wiper", "tyre", "air freshener", "seat cover",
    # electronics & accessories
    "battery", "charger", "cable", "earphone", "headphone",
    "speaker", "phone case", "screen protector", "power bank",
    # tobacco & vaping
    "tobacco", "cigarette", "vape", "vaping", "e-cigarette",
    "rolling papers", "lighter", "ashtray",
    # miscellaneous
    "gum", "chewing gum", "mint", "lolly", "candy", "chocolate",
    "sweet", "treat", "snack", "confectionery",
    "pet", "gum", "stationery", "entertainment", "clothing",
    "outdoors", "laundry", "paper", "accessories", "formula",
    "medical", "first aid", "oral hygiene", "soaps",
]


def get_website_session():
    """Obtain website JWT (fs-user-token)."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": WEB_BASE,
        "Referer": WEB_BASE + "/",
    })
    session.get(WEB_BASE, timeout=30)
    session.post(f"{WEB_BASE}/api/user/get-current-user", json={}, timeout=30)
    token = session.cookies.get("fs-user-token")
    if not token:
        raise RuntimeError("Failed to obtain fs-user-token")
    return token


def auth_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "access_token": token,
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/shop",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }


def store_cookies(store_id, region="NI"):
    return {
        "eCom_STORE_ID": store_id,
        "STORE_ID_V2": f"{store_id}|False",
        "Region": region,
    }


def get_first_store(token):
    """Get a Pak'nSave store ID to use for queries."""
    headers = auth_headers(token)
    r = requests.get(f"{EDGE_BASE}/store", headers=headers, timeout=30)
    r.raise_for_status()
    stores = r.json().get("stores", [])
    if not stores:
        raise RuntimeError("No stores returned")
    # Prefer a NI store (testing purposes)
    for s in stores:
        if s.get("region") == "NI":
            return s["id"], s.get("name", "Unknown")
    return stores[0]["id"], stores[0].get("name", "Unknown")


def fetch_categories_tree(token, store_id):
    """Hit the categories endpoint to get the navigation tree."""
    headers = auth_headers(token)
    cookies = store_cookies(store_id)
    r = requests.get(
        f"{EDGE_BASE}/store/{store_id}/categories",
        headers=headers,
        cookies=cookies,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def walk_category_tree(nodes, depth=0, results=None):
    """Recursively walk the category tree and print it."""
    if results is None:
        results = []
    for node in (nodes or []):
        name = node.get("name", "?")
        code = node.get("code", "")
        indent = "  " * depth
        suffix = f"  (code: {code})" if code else ""
        line = f"{indent}{name}{suffix}"
        print(line)
        results.append((name, code, depth))
        walk_category_tree(node.get("children", []), depth + 1, results)
    return results


def search_algolia(token, store_id, query, hits_per_page=50):
    """Run a Pass 1-style Algolia search and return raw hits."""
    headers = auth_headers(token)
    cookies = store_cookies(store_id)
    payload = {
        "algoliaQuery": {"query": query},
        "page": 0,
        "hitsPerPage": hits_per_page,
        "storeId": store_id,
    }
    r = requests.post(
        f"{EDGE_BASE}/search/products/query/index/products-index",
        headers=headers,
        json=payload,
        cookies=cookies,
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("hits", [])


def main():
    print("=" * 80)
    print("PAK'nSAVE EDGE API — CATEGORY1 DISCOVERY")
    print("=" * 80)
    print()

    # ── Step 1: Authenticate ──────────────────────────────────────────────
    print("Step 1: Authenticating...")
    token = get_website_session()
    print(f"  JWT: {token[:40]}...")
    print()

    # ── Step 2: Get a store ───────────────────────────────────────────────
    print("Step 2: Getting a store...")
    store_id, store_name = get_first_store(token)
    print(f"  Store: {store_name} ({store_id})")
    print()

    # ── Step 3: Fetch categories endpoint ─────────────────────────────────
    print("=" * 80)
    print("STEP 3: Categories Endpoint — /v1/edge/store/{id}/categories")
    print("=" * 80)
    print()
    print("This is the navigation category tree returned by the Edge API.")
    print("It mirrors the website's Browse department/aisle/shelf structure.")
    print("NOTE: This may NOT exactly match the category1 values in Algolia")
    print("hits — those are a separate classification on the product itself.")
    print()
    try:
        tree = fetch_categories_tree(token, store_id)
        # The response could be a list or have a wrapper key
        if isinstance(tree, list):
            nodes = tree
        elif isinstance(tree, dict):
            # Try common wrapper keys
            nodes = tree.get("categories") or tree.get("data") or tree.get("items")
            if nodes is None:
                print("  Unexpected response structure. Keys:", list(tree.keys()))
                print("  Raw response (first 2000 chars):")
                print(json.dumps(tree, indent=2)[:2000])
                nodes = []
        else:
            print(f"  Unexpected type: {type(tree)}")
            nodes = []

        if nodes:
            tree_entries = walk_category_tree(nodes)
            print(f"\n  Total category tree nodes: {len(tree_entries)}")
        else:
            print("  (empty tree)")
    except Exception as e:
        print(f"  ERROR fetching categories: {e}")
    print()

    # # ── Step 4: Collect category1 from Algolia searches ───────────────────
    print("=" * 80)
    print("STEP 4: Algolia Search — Collecting category1 Values")
    print("=" * 80)
    print()
    print("Running broad search queries against products-index to discover")
    print("all unique category1 values that appear in the search index.")
    print(f"Queries to run: {len(BROAD_QUERIES)}")
    print()

    # Track unique category1 values and frequency
    cat1_counter = Counter()  # counts how many times each cat1 VALUE appears
    cat1_examples = {}        # cat1 value -> example product name

    for i, query in enumerate(BROAD_QUERIES, 1):
        try:
            hits = search_algolia(token, store_id, query, hits_per_page=50)
            for h in hits:
                cat1 = h.get("category1", [])
                display_name = h.get("DisplayName", "")
                # Record individual values
                for c in cat1:
                    cat1_counter[c] += 1
                    if c not in cat1_examples:
                        cat1_examples[c] = display_name
            print(f"  [{i:2d}/{len(BROAD_QUERIES)}] query='{query}' → {len(hits)} hits")
        except Exception as e:
            print(f"  [{i:2d}/{len(BROAD_QUERIES)}] query='{query}' → ERROR: {e}")
        time.sleep(0.12)  # gentle rate limit

    print()

    # ── Step 5: Display all unique category1 values ───────────────────────
    print("=" * 80)
    print("STEP 5: All Unique category1 Values (sorted by frequency)")
    print("=" * 80)
    print()
    print("These are every distinct value that appears in ANY product's")
    print("category1 array across all the search results.  This is the")
    print("EXACT set of values you can filter on in Pass 1.")
    print()
    print(f"{'Value':<45} {'Count':>6}  {'Example Product'}")
    print(f"{'─' * 45} {'─' * 6}  {'─' * 40}")

    for value, count in cat1_counter.most_common():
        example = cat1_examples.get(value, "")[:40]
        print(f"{value:<45} {count:>6}  {example}")

    print(f"\n  Total unique category1 values: {len(cat1_counter)}")
    print()

    # ── Step 6: Display all unique category1 combinations ─────────────────
    print("=" * 80)
    print("STEP 6: All Unique category1 Combinations (sorted by frequency)")
    print("=" * 80)
    print()
    print("Each product has a category1 ARRAY (e.g. ['Beef', 'Mince,")
    print("Sausages & Meatballs']).  This shows every unique combination")
    print("seen across all searches.")
    print()
    print(f"{'Combination':<70} {'Count':>6}")
    print(f"{'─' * 70} {'─' * 6}")


    # ── Save step 6 results to file ─────────────────────────
    observed_data = {
        "cat1_counter": dict(cat1_counter),
    }
    output_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "data"
        / "observed_category1_paknsave.json"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(observed_data, f, indent=2, ensure_ascii=False)
    print(f"  Saved to {output_path}")
    print()

    print("Done.")
    print("=" * 80)


if __name__ == "__main__":
    main()
