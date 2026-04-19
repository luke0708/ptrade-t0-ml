import akshare as ak
import pandas as pd

def download_5m():
    try:
        print("Sina 300661...")
        df_stk = ak.stock_zh_a_minute(symbol="sz300661", period="5", adjust="qfq")
        print(f"300661: {len(df_stk)} rows. {df_stk['day'].min()} to {df_stk['day'].max()}")
        
        print("Sina 399006...")
        df_idx = ak.stock_zh_a_minute(symbol="sz399006", period="5", adjust="")
        print(f"399006: {len(df_idx)} rows. {df_idx['day'].min()} to {df_idx['day'].max()}")
        
        print("Sina 512480...")
        df_sec = ak.stock_zh_a_minute(symbol="sh512480", period="5", adjust="qfq")
        print(f"512480: {len(df_sec)} rows. {df_sec['day'].min()} to {df_sec['day'].max()}")
    except Exception as e:
        print("Error:", e)

if __name__ == '__main__':
    download_5m()
