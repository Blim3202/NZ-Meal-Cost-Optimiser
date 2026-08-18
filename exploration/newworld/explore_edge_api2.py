import requests
import json

# Get token for mobile API
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

# Get stores from Edge API
r = requests.get('https://api-prod.newworld.co.nz/v1/edge/store/physical', headers=auth_headers)
stores = r.json()['stores']
print(f"Edge API stores: {len(stores)}")
print(f"First: {stores[0]['name']} (id={stores[0]['id']})")

# Try product search on Edge API
store_id = stores[0]['id']

# Edge product search - try different formats
endpoints = [
    f'https://api-prod.newworld.co.nz/v1/edge/products/search?q=milk&storeId={store_id}',
    f'https://api-prod.newworld.co.nz/v1/edge/products?storeId={store_id}&q=milk',
    f'https://api-prod.newworld.co.nz/v1/edge/ecomm-products/MNW/{store_id}/search?q=milk',
    f'https://api-prod.newworld.co.nz/v1/edge/store/{store_id}/products/search?q=milk',
    f'https://api-prod.newworld.co.nz/v1/edge/search?q=milk&storeId={store_id}',
]

print("\n=== Edge Product Search Tests ===")
for ep in endpoints:
    r = requests.get(ep, headers=auth_headers)
    print(f'{ep}: {r.status_code} - {r.text[:200]}')

# Also try POST like mobile API
post_endpoints = [
    f'https://api-prod.newworld.co.nz/v1/edge/ecomm-products/MNW/{store_id}/search?q=milk',
    f'https://api-prod.newworld.co.nz/v1/edge/products/search',
]

print("\n=== Edge POST Product Search Tests ===")
for ep in post_endpoints:
    r = requests.post(ep, headers=auth_headers, json=[])
    print(f'{ep}: {r.status_code} - {r.text[:200]}')

# Check if there's a different product endpoint - maybe v2?
v2_endpoints = [
    f'https://api-prod.newworld.co.nz/v2/edge/products/search?q=milk&storeId={store_id}',
    f'https://api-prod.newworld.co.nz/v2/edge/store/{store_id}/products?q=milk',
]

print("\n=== V2 Edge Endpoints ===")
for ep in v2_endpoints:
    r = requests.get(ep, headers=auth_headers)
    print(f'{ep}: {r.status_code} - {r.text[:200]}')

# Check what the website actually calls
# Let's look at the New World website network traffic pattern
# The website is a Next.js app - maybe it uses a different API

# Try the mobile API's product search for comparison
mobile_ep = f'https://api-prod.prod.fsniwaikato.kiwi/prod/mobile/ecomm-products/MNW/{store_id}/search?q=milk'
r = requests.post(mobile_ep, headers=auth_headers, json=[])
print(f'\nMobile API product search: {r.status_code}')
if r.status_code == 200:
    data = r.json()
    print(f'Products found: {data["totalHits"]}')
    if data['products']:
        print(f'First: {data["products"][0]["name"]} - ${data["products"][0]["price"]/100:.2f}')