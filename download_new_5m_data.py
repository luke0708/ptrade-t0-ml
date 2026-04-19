import subprocess
import json
import pandas as pd
from pathlib import Path

DATA_DIR = Path("E:/AI炒股/机器学习/data")

def get_em_kline_ps(secid, freq, start_date="0", is_daily=False):
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&ut=7eea3edcaed734bea9cbfc24409ed989&klt={freq}&fqt=1&secid={secid}&beg={start_date}&end=20500000"
    
    print(f"Fetching url via powershell: {secid} freq={freq}")
    ps_cmd = f'(Invoke-WebRequest -Uri "{url}" -UseBasicParsing).Content'
    
    result = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)
    if result.returncode != 0:
        print("PS err")
        return pd.DataFrame()
        
    try:
        out_str = result.stdout.decode('utf-8', errors='ignore')
        # sometimes PS wraps in extra whitespace or newlines
        out_str = out_str.strip()
        data = json.loads(out_str)
        if data.get('data') is None:
            return pd.DataFrame()
        klines = data['data']['klines']
    except Exception as e:
        print("JSON err:", e)
        return pd.DataFrame()
        
    parsed = []
    for k in klines:
        parts = k.split(',')
        dt = parts[0] if is_daily else parts[0] + ":00"
        parsed.append({
            'datetime' if not is_daily else 'date': dt,
            'open': float(parts[1]),
            'close': float(parts[2]),
            'high': float(parts[3]),
            'low': float(parts[4]),
            'volume': float(parts[5]),
            'amount': float(parts[6]),
        })
        
    return pd.DataFrame(parsed)

def get_tushare_maybe():
    pass

def download_daily():
    df1 = get_em_kline_ps("0.300661", 101, is_daily=True)
    if len(df1)>0: 
        df1.to_csv(DATA_DIR / "300661.csv", index=False)
        print("300661 Daily:", len(df1))
    
    df2 = get_em_kline_ps("0.399006", 101, is_daily=True)
    if len(df2)>0: 
        df2.to_csv(DATA_DIR / "399006.csv", index=False)
        print("399006 Daily:", len(df2))
    
    df3 = get_em_kline_ps("1.512480", 101, is_daily=True)
    if len(df3)>0: 
        df3.to_csv(DATA_DIR / "512480.csv", index=False)
        print("512480 Daily:", len(df3))

def download_minute():
    df1 = get_em_kline_ps("0.300661", 5)
    if len(df1)>0: 
        df1.to_csv(DATA_DIR / "300661_5m.csv", index=False)
        print("300661 5m:", len(df1), "Start:", df1['datetime'].min())
    
    df2 = get_em_kline_ps("0.399006", 5)
    if len(df2)>0: 
        df2.to_csv(DATA_DIR / "399006_5m.csv", index=False)
        print("399006 5m:", len(df2), "Start:", df2['datetime'].min())
    
    df3 = get_em_kline_ps("1.512480", 5)
    if len(df3)>0: 
        df3.to_csv(DATA_DIR / "512480_5m.csv", index=False)
        print("512480 5m:", len(df3), "Start:", df3['datetime'].min())

if __name__ == '__main__':
    download_daily()
    download_minute()
