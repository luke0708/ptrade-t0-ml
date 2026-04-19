import urllib3
urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL:@SECLEVEL=1'
import requests.packages.urllib3
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL:@SECLEVEL=1'

import requests
import json
import pandas as pd

def get_em_kline(secid, freq=5):
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": freq,
        "fqt": 1,
        "secid": secid,
        "beg": "0",
        "end": "20500000"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    
    r = requests.get(url, params=params, headers=headers, verify=False)
    data = r.json()
    klines = data['data']['klines']
    
    parsed = []
    for k in klines:
        # time, open, close, high, low, volume, amount, amplitude, pct_change, change, turnover
        parts = k.split(',')
        parsed.append({
            'datetime': parts[0],
            'open': float(parts[1]),
            'close': float(parts[2]),
            'high': float(parts[3]),
            'low': float(parts[4]),
            'volume': float(parts[5]),
            'amount': float(parts[6]),
        })
        
    df = pd.DataFrame(parsed)
    return df

def test():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    print("Fetching 399006...")
    df1 = get_em_kline("0.399006")
    print(df1.head(2))
    print("Rows:", len(df1), "Date Range:", df1['datetime'].min(), "to", df1['datetime'].max())
    
    print("Fetching 512480...")
    df2 = get_em_kline("1.512480")
    print("Rows:", len(df2), "Date Range:", df2['datetime'].min(), "to", df2['datetime'].max())
    
    print("Fetching 300661...")
    df3 = get_em_kline("0.300661")
    print("Rows:", len(df3), "Date Range:", df3['datetime'].min(), "to", df3['datetime'].max())

if __name__ == '__main__':
    test()
