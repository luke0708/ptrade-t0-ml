import akshare as ak
import pandas as pd

df = ak.stock_zh_a_hist_min_em(symbol="300661", period="1", adjust="qfq")
if df is not None and not df.empty:
    print(f"Got {len(df)} rows from em.")
    print(df.head())
    print(df.tail())
else:
    print("Failed to get 1m data from em via akshare.")
