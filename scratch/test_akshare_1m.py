import akshare as ak
import pandas as pd

df = ak.stock_zh_a_minute(symbol="sz300661", period="1", adjust="qfq")
if df is not None and len(df) > 0:
    print(f"Got {len(df)} rows of sina 1m data.")
    print(df.head())
    print(df.tail())
else:
    print("Failed to get 1m data from Sina via akshare.")
