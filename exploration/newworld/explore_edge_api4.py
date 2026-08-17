import requests
import json

# Get token for mobile API
r = requests.post(
    'https://api-prod.prod.fsniwaikato.kiwi/prod/mobile/user/login/guest',
    json={'banner': 'MNW'},
    headers={'User-Agent': 'NewWorldApp/4.32.0', 'Content-Type': 'application/json'},
    timeout=10
)
r.raise_for_status()
token_data = r.json()
token = token_data['access_token']
refresh_token = token_data.get('refresh_token')
auth_headers = {
    'Authorization': f'Bearer {token}',
    'access_token': token,
    'User-Agent': 'NewWorldApp/4.32.0',
    'Content-Type': 'application/json',
}

# Check the refresh token
print("=== Refresh Token ===")
if refresh_token:
    r2 = requests.post(
        'https://api-prod.prod.fsniwaikato.kiwi/prod/mobile/v1/users/login/refreshtoken',
        headers={'User-Agent': 'NewWorldApp/4.32.0'},
        json={'refresh_token': refresh_token},
        timeout=10
    )
    print(f'Status: {r2.status_code}')
    if r2.status_code == 200:
        print(f'Response: {r2.json()}')

# Check if mobile API has any other endpoints we might have missed
print("\n=== Mobile API Discovery ===")
mobile_endpoints = [
    '/mobile/v1/products/category?storeId=f95243ac-bfc9-483a-b10a-b681f4fc4ba2&banner=MNW',
    '/mobile/v1/upgrade',
    '/mobile/v1/error',
    '/mobile/v1/users/profile',
]
for ep in mobile_endpoints:
    r = requests.get(f'https://api-prod.prod.fsniwaikato.kiwi/prod{ep}', headers=auth_headers, timeout=5)
    print(f'{ep}: {r.status_code} - {r.text[:200]}')

# Try the website's actual search - it uses Next.js so data might be in __NEXT_DATA__
# Let's fetch a product search page
print("\n=== Website Product Search Page ===")
try:
    r = requests.get('https://www.newworld.co.nz/search?q=milk', 
                     headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
    print(f'Status: {r.status_code}')
    if '__NEXT_DATA__' in r.text:
        print('Found __NEXT_DATA__')
        # Extract it
        import re
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
        if match:
            data = json.loads(match.group(1))
            print(f'Keys: {list(data.keys())}')
            print(f'Page props keys: {list(data.get("props", {}).get("pageProps", {}).keys())}')
    else:
        print('No __NEXT_DATA__ found')
except Exception as e:
    print(f'ERROR: {e}')

# Check if there's a GraphQL endpoint
print("\n=== GraphQL Endpoint ===")
try:
    r = requests.post('https://www.newworld.co.nz/api/graphql',
                     headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'},
                     json={'query': '{ products(search: "milk") { name price } }'},
                     timeout=10)
    print(f'Status: {r.status_code}')
    print(f'Response: {r.text[:500]}')
except Exception as e:
    print(f'ERROR: {e}')

# Let's also check if the Edge API has any product-related endpoints we haven't tried
# Maybe it uses a different path pattern
print("\n=== Edge API - More Endpoints ===")
edge_endpoints = [
    '/v1/edge/products',
    '/v1/edge/products/milk',
    '/v1/edge/search',
    '/v1/edge/ecomm-products',
]
for ep in edge_endpoints:
    r = requests.get(f'https://api-prod.newworld.co.nz{ep}', headers=auth_headers, timeout=5)
    print(f'{ep}: {r.status_code} - {r.text[:200]}')