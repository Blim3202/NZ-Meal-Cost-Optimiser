import requests
import json
import re

# Get mobile token
r = requests.post(
    'https://api-prod.prod.fsniwaikato.kiwi/prod/mobile/user/login/guest',
    json={'banner': 'MNW'},
    headers={'User-Agent': 'NewWorldApp/4.32.0', 'Content-Type': 'application/json'},
)
r.raise_for_status()
token = r.json()['access_token']
auth_headers = {
    'Authorization': f'Bearer {token}',
    'access_token': token,
    'User-Agent': 'NewWorldApp/4.32.0',
    'Content-Type': 'application/json',
}

# Fetch the store finder page to see what APIs it calls
print("=== Store Finder Page ===")
r = requests.get('https://www.newworld.co.nz/store-finder', timeout=10)
print(f'Status: {r.status_code}')
match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
if match:
    data = json.loads(match.group(1))
    page_props = data.get('props', {}).get('pageProps', {})
    print(f'Page props keys: {list(page_props.keys())}')
    if 'stores' in page_props:
        print(f'Stores count: {len(page_props["stores"])}')

# Fetch a product search page - e.g., search for "milk"
print("\n=== Product Search Page ===")
r = requests.get('https://www.newworld.co.nz/search?q=milk', timeout=10)
print(f'Status: {r.status_code}')
match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
if match:
    data = json.loads(match.group(1))
    page_props = data.get('props', {}).get('pageProps', {})
    print(f'Page props keys: {list(page_props.keys())}')

# Check the homepage for API clues
print("\n=== Homepage ===")
r = requests.get('https://www.newworld.co.nz', timeout=10)
print(f'Status: {r.status_code}')
match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
if match:
    data = json.loads(match.group(1))
    page_props = data.get('props', {}).get('pageProps', {})
    print(f'Page props keys: {list(page_props.keys())}')

# The website likely makes API calls to the mobile API for products
# Let's check if there's an API gateway or proxy on the main domain
print("\n=== API Gateway on main domain ===")
api_endpoints = [
    '/api/mobile/store/physical',
    '/api/mobile/ecomm-products/MNW/f95243ac-bfc9-483a-b10a-b681f4fc4ba2/search?q=milk',
    '/api/mobile/user/login/guest',
    '/api/v1/products/search?q=milk',
    '/api/v1/shell',
]
for ep in api_endpoints:
    r = requests.get(f'https://www.newworld.co.nz{ep}', 
                     headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
    print(f'{ep}: {r.status_code} - {r.text[:200]}')

# Check if the mobile API is proxied through the main domain
print("\n=== Mobile API via main domain ===")
r = requests.post('https://www.newworld.co.nz/api/mobile/user/login/guest',
                 json={'banner': 'MNW'},
                 headers={'User-Agent': 'NewWorldApp/4.32.0', 'Content-Type': 'application/json'},
                 timeout=10)
print(f'Guest login: {r.status_code} - {r.text[:200]}')