import urllib3
urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL:@SECLEVEL=1'
import requests

import akshare as ak

def test():
    try:
        print("Testing EastMoney 5m...")
        df = ak.stock_zh_a_hist_min_em(symbol="300661", start_date="2025-01-01 09:30:00", end_date="2026-04-13 15:00:00", period="5", adjust="qfq")
        print(f"Success! Lines: {len(df)}")
        print(df.head(2))
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test()
