import urllib3
import requests
import akshare as ak

urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL:@SECLEVEL=1'

def test():
    df1 = ak.index_zh_a_hist_min_em(symbol="399006", period="5")
    df2 = ak.fund_etf_hist_min_em(symbol="512480", period="5")
    
    print(f"399006 EastMoney 5m: {len(df1)} rows. From {df1['时间'].min()} to {df1['时间'].max()}")
    print("Columns:", df1.columns)
    
    print(f"512480 EastMoney 5m: {len(df2)} rows. From {df2['时间'].min()} to {df2['时间'].max()}")
    print("Columns:", df2.columns)

if __name__ == "__main__":
    test()
