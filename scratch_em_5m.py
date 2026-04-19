import urllib3
import requests
import json

urllib3.disable_warnings()
urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL:@SECLEVEL=1'
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL:@SECLEVEL=1'

def get_em_5m(secid):
    url = f"http://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "5",
        "fqt": "1",
        "secid": secid,
        "beg": "0",
        "end": "20500000",
        "lmt": "1000000",
    }
    r = requests.get(url, params=params, verify=False, timeout=10)
    data = r.json()
    return data['data']['klines']

try:
    klines = get_em_5m("0.300661")
    print("Fetched rows:", len(klines))
    if len(klines) > 0:
        print("First few:", klines[:2])
        print("Last few:", klines[-2:])
except Exception as e:
    print("Failed:", e)
