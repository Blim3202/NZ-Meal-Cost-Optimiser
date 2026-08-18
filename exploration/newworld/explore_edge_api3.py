import requests
import json

# Get token for mobile API
login_r = requests.post(
    'https://api-prod.prod.fsniwaikato.kiwi/prod/mobile/user/login/guest',
    json={'banner': 'MNW'},
    headers={'User-Agent': 'NewWorldApp/4.32.0', 'Content-Type': 'application/json'},
    timeout=10
)
login_r.raise_for_status()
token = login_r.json()['access_token']
auth_headers = {
    'Authorization': f'Bearer {token}',
    'access_token': token,
    'User-Agent': 'NewWorldApp/4.32.0',
    'Content-Type': 'application/json',
}

# Try Edge API with web-like headers
web_headers = {
    'Authorization': f'Bearer {token}',
    'access_token': token,
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Referer': 'https://www.newworld.co.nz/',
    'Origin': 'https://www.newworld.co.nz',
}

print("=== Edge API with web headers ===")
r = requests.get('https://api-prod.newworld.co.nz/v1/edge/store/physical', headers=web_headers, timeout=10)
print(f'Status: {r.status_code}')
print(f'Store count: {len(r.json()["stores"])}')

# Try website product API with timeout
print("\n=== Website API Tests ===")
website_apis = [
    'https://www.newworld.co.nz/api/products/search?q=milk',
    'https://www.newworld.co.nz/api/v1/products/search?q=milk',
]
for ep in website_apis:
    try:
        r = requests.get(ep, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        print(f'{ep}: {r.status_code} - {r.text[:200]}')
    except Exception as e:
        print(f'{ep}: ERROR - {e}')


# Check the refresh token
print("\n=== Refresh Token ===")
refresh_token = login_r.json().get('refresh_token')
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
# Try to see what other endpoints exist
mobile_endpoints = [
    '/mobile/v1/products/category?storeId=f95243ac-bfc9-483a-b10a-b681f4fc4ba2&banner=MNW',
    '/mobile/v1/upgrade',
    '/mobile/v1/error',
    '/mobile/v1/users/profile',
]
for ep in mobile_endpoints:
    r = requests.get(f'https://api-prod.prod.fsniwaikato.kiwi/prod{ep}', headers=auth_headers, timeout=5)
    print(f'{ep}: {r.status_code} - {r.text[:200]}')