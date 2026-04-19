import subprocess
import json
import pandas as pd
from pathlib import Path
import akshare as ak
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_DIR = Path(__file__).parent / "data"

def get_em_kline_ps(secid, freq, start_date="0", is_daily=False):
    """
    使用 Powershell绕过 Python SSL 限制，并拉取东方财富历史数据
    fqt=1 代表前复权，klt 是频率 (101=日线)
    """
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&ut=7eea3edcaed734bea9cbfc24409ed989&klt={freq}&fqt=1&secid={secid}&beg={start_date}&end=20500000"
    
    ps_cmd = f'(Invoke-WebRequest -Uri "{url}" -UseBasicParsing).Content'
    
    result = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)
    if result.returncode != 0:
        logging.error("Powershell fetch failed")
        return pd.DataFrame()
        
    try:
        out_str = result.stdout.decode('utf-8', errors='ignore').strip()
        data = json.loads(out_str)
        if data.get('data') is None:
            return pd.DataFrame()
        klines = data['data']['klines']
    except Exception as e:
        logging.error(f"JSON parse error: {e}")
        return pd.DataFrame()
        
    parsed = []
    for k in klines:
        parts = k.split(',')
        dt = parts[0] if is_daily else parts[0] + ":00"
        parsed.append({
            'date' if is_daily else 'datetime': dt,
            'open': float(parts[1]),
            'close': float(parts[2]),
            'high': float(parts[3]),
            'low': float(parts[4]),
            'volume': float(parts[5]),
            'amount': float(parts[6]),
        })
        
    return pd.DataFrame(parsed)

def update_daily_file(secid, csv_filename):
    csv_path = DATA_DIR / csv_filename
    logging.info(f"--- 更新 {csv_filename} (日线数据) ---")
    
    if csv_path.exists():
        df_old = pd.read_csv(csv_path)
        if df_old.empty or 'date' not in df_old.columns:
            df_old = pd.DataFrame()
    else:
        df_old = pd.DataFrame()

    df_new = get_em_kline_ps(secid, 101, is_daily=True)
    if df_new.empty:
        logging.warning("新数据获取为空，跳过更新")
        return

    if not df_old.empty:
        df_merged = pd.concat([df_old, df_new], ignore_index=True)
        # 用 date 去重，保留最新拉取的数据
        df_merged = df_merged.sort_values('date').drop_duplicates(subset=['date'], keep='last').reset_index(drop=True)
    else:
        df_merged = df_new

    # 保证列顺序并保存
    cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
    df_merged = df_merged[cols]
    df_merged.to_csv(csv_path, index=False)
    logging.info(f"{csv_filename} 更新完成! 最新的日期: {df_merged['date'].iloc[-1]}, 总行数: {len(df_merged)}")


def update_300661_1m():
    csv_path = DATA_DIR / "300661_SZ_1m_ptrade.csv"
    logging.info(f"--- 更新 300661_SZ_1m_ptrade.csv (1分钟数据) ---")
    
    if csv_path.exists():
        df_old = pd.read_csv(csv_path)
        if df_old.empty or 'datetime' not in df_old.columns:
            df_old = pd.DataFrame()
    else:
        df_old = pd.DataFrame()

    try:
        # adjust="qfq" 代表前复权
        df_new = ak.stock_zh_a_hist_min_em(symbol="300661", period="1", adjust="qfq")
    except Exception as e:
        logging.error(f"akshare 获取分钟线失败: {e}")
        return

    if df_new is not None and not df_new.empty:
        # 处理 akshare em json columns: 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 最新价/等等
        col_mapping = {
            '时间': 'datetime',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
            '最新价': 'price'
        }
        df_new.rename(columns=lambda x: col_mapping.get(x, x), inplace=True)
        
        # 修复 known bug: EM 前几分钟open可能为 0.0
        if 'open' in df_new.columns and 'close' in df_new.columns:
            df_new['open'] = df_new.apply(lambda row: row['close'] if row['open'] == 0.0 else row['open'], axis=1)

        # 增加缺失的 code(ptrade标准) 与 price(如果没有的话)
        df_new['code'] = '300661.SZ'
        if 'price' not in df_new.columns:
            df_new['price'] = df_new['close']

        cols = ['datetime', 'code', 'open', 'high', 'low', 'close', 'volume', 'amount', 'price']
        for c in cols:
            if c not in df_new.columns:
                df_new[c] = pd.NA
        df_new = df_new[cols]
        
        # 兼容 ptrade 时间格式，将 time 强转为 YYYY-MM-DD HH:MM:SS
        df_new['datetime'] = pd.to_datetime(df_new['datetime']).dt.strftime('%Y-%m-%d %H:%M:%S')

        if not df_old.empty:
            # 兼容老数据
            df_old['datetime'] = pd.to_datetime(df_old['datetime']).dt.strftime('%Y-%m-%d %H:%M:%S')
            df_merged = pd.concat([df_old, df_new], ignore_index=True)
            df_merged = df_merged.sort_values('datetime').drop_duplicates(subset=['datetime'], keep='last').reset_index(drop=True)
        else:
            df_merged = df_new

        df_merged.to_csv(csv_path, index=False)
        logging.info(f"300661 1分钟线更新完成! 最新一分钟时间: {df_merged['datetime'].iloc[-1]}, 总行数: {len(df_merged)}")
    else:
        logging.info("新拉取的分钟线为空，跳过更新.")

if __name__ == '__main__':
    update_daily_file("1.512480", "512480.csv")
    update_daily_file("0.399006", "399006.csv")
    update_300661_1m()
