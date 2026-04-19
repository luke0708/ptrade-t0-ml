import subprocess
import requests

_original_get = requests.get

def patched_get(url, **kwargs):
    if "eastmoney.com" in url:
        try:
            print(f"Using curl for: {url}")
            result = subprocess.run(["curl.exe", "-s", "-L", url], capture_output=True, text=True, encoding='utf-8', timeout=15)
            if result.returncode == 0:
                resp = requests.models.Response()
                resp.status_code = 200
                resp._content = result.stdout.encode('utf-8')
                resp.url = url
                
                # Mock json
                import json
                def _json(**kwargs):
                    return json.loads(result.stdout)
                resp.json = _json
                return resp
        except Exception as e:
            print("curl fallback failed:", e)
    return _original_get(url, **kwargs)

requests.Session.get = lambda self, url, **kwargs: patched_get(url, **kwargs)
requests.get = patched_get

import akshare as ak

def test():
    print("Testing 300661 5m...")
    df = ak.stock_zh_a_hist_min_em(symbol="300661", period="5", adjust="qfq")
    print("Rows:", len(df))
    if len(df) > 0:
        print("Start:", df['时间'].min())
        print("End:", df['时间'].max())
        print(df.head(2))

if __name__ == '__main__':
    test()
