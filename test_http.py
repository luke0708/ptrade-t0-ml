import akshare as ak
import requests
import pandas as pd

# Monkey patch requests to force HTTP for eastmoney to bypass Python 3.13 SSL issue
_original_get = requests.get
_original_post = requests.post

def _patched_get(url, **kwargs):
    if "eastmoney.com" in url and url.startswith("https://"):
        url = url.replace("https://", "http://")
    return _original_get(url, **kwargs)

def _patched_post(url, **kwargs):
    if "eastmoney.com" in url and url.startswith("https://"):
        url = url.replace("https://", "http://")
    return _original_post(url, **kwargs)

requests.get = _patched_get
requests.post = _patched_post

def download():
    print("Testing patched EM Daily Index...")
    df_idx_d = ak.stock_zh_index_daily_em(symbol="sz399006")
    df_idx_d.to_csv("E:/AI炒股/机器学习/data/399006.csv", index=False)
    print("Index Daily Done. rows:", len(df_idx_d))

    print("Testing patched EM ETF Daily...")
    df_etf_d = ak.fund_etf_hist_em(symbol="159915", start_date="20200101", end_date="20260413")
    print("ETF Daily Done. rows:", len(df_etf_d))
    
    print("Testing patched EM ETF Min...")
    df_min = ak.fund_etf_hist_min_em(symbol="512480", period="5")
    print("ETF Min Done. rows:", len(df_min))

if __name__ == '__main__':
    download()
