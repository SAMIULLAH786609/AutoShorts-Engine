import httpx
import re

url = 'https://auto-shorts-engine-lg5a.vercel.app/'
try:
    print('Fetching Vercel homepage...')
    r = httpx.get(url, timeout=10)
    html = r.text
    
    # Find all /assets/*.js links using regex
    js_files = re.findall(r'src="(/assets/[a-zA-Z0-9.-]+\.js)"', html)
    js_urls = [url + js.lstrip('/') for js in js_files]
            
    print('Found JS bundles:', js_urls)
    for js_url in js_urls:
        print(f'Checking {js_url}...')
        js_data = httpx.get(js_url).text
        # Search for backend URL patterns
        matches = re.findall(r'https?://[a-zA-Z0-9.-]+onrender\.com', js_data)
        print('Found onrender URLs in JS:', matches)
        matches_api = re.findall(r'baseURL\s*:\s*["\'][^"\']+["\']', js_data)
        print('Found baseURL patterns:', matches_api)
except Exception as e:
    print('Error:', e)
