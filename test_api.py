import requests
import json

url = 'http://localhost:5000/api/analyze'
payload = {'url': 'https://www.youtube.com/watch?v=z19HM7ANZlo'}

print('Testing /api/analyze endpoint...')
print('=' * 60)

try:
    response = requests.post(url, json=payload, timeout=15)
    print(f'Status: {response.status_code}')
    data = response.json()
    
    if data.get('success'):
        print('✅ SUCCESS!')
        print(f'   Title: {data.get("title")}')
        print(f'   Duration: {data.get("duration")}')
        print(f'   Uploader: {data.get("uploader")}')
        print(f'   Formats: {len(data.get("formats", []))} available')
    else:
        print(f'❌ Failed: {data.get("error")}')
except Exception as e:
    print(f'Error: {str(e)}')

print('\nTesting /api/oauth2/shared-account-status endpoint...')
print('=' * 60)

try:
    url = 'http://localhost:5000/api/oauth2/shared-account-status'
    response = requests.get(url, timeout=15)
    print(f'Status: {response.status_code}')
    data = response.json()
    
    if data.get('success'):
        print('✅ SUCCESS!')
        print(f'   Has Shared Account: {data.get("has_shared_account")}')
        if data.get('has_shared_account'):
            print(f'   Account Info: {data.get("account_info")}')
    else:
        print(f'❌ Failed: {data.get("error")}')
except Exception as e:
    print(f'Error: {str(e)}')
