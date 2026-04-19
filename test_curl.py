import subprocess
import requests

_original_get = requests.get
_original_post = requests.post

def patched_get(url, **kwargs):
    if "eastmoney.com" in url:
        try:
            result = subprocess.run(["curl.exe", "-s", "-L", url], capture_output=True, text=True, encoding='utf-8', timeout=15)
            if result.returncode == 0:
                resp = requests.models.Response()
                resp.status_code = 200
                # _content needs to be bytes
                resp._content = result.stdout.encode('utf-8')
                resp.url = url
                
                # Mock json()
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
    print("Testing EM Index 5m via CURL...")
    df = ak.index_zh_a_hist_min_em(symbol="399006", period="5")
    print("Rows:", len(df))
    if len(df) > 0:
        print(df.head(2))

if __name__ == '__main__':
    test()
