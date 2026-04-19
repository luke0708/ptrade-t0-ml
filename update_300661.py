import pandas as pd
import akshare as ak
from pathlib import Path
import logging
import urllib3
import requests.packages.urllib3

urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL:@SECLEVEL=1'
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL:@SECLEVEL=1'
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ==========================================
# 专门为 300661 提供数据拼接和增量更新的脚本
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_DIR = Path("E:/AI炒股/机器学习/data")
DATA_DIR.mkdir(exist_ok=True, parents=True)

def update_daily():
    csv_path = DATA_DIR / "300661.csv"
    logging.info(f"--- 更新 300661 日线数据 (增量拼接) ---")
    
    if csv_path.exists():
        try:
            df_old = pd.read_csv(csv_path)
            if df_old.empty or 'date' not in df_old.columns:
                raise ValueError("Empty or invalid columns")
            last_date = str(df_old['date'].max())
            logging.info(f"找到历史日线数据. 行数: {len(df_old)}, 最新日期: {last_date}")
        except Exception:
            df_old = pd.DataFrame()
            last_date = "2020-01-01"
            logging.info("未找到历史日线数据或读取失败，将从 2020-01-01 获取.")

    start_date_str = last_date.replace("-", "")
    today_str = pd.Timestamp.now().strftime("%Y%m%d")

    try:
        df_new = ak.stock_zh_a_hist(symbol="300661", period="daily", start_date=start_date_str, end_date=today_str, adjust="qfq")
    except Exception as e:
        logging.error(f"日线拉取失败: {e}")
        return

    if df_new is not None and not df_new.empty:
        col_mapping = {'日期':'date', '开盘':'open', '收盘':'close', '最高':'high', '最低':'low', '成交量':'volume', '成交额':'amount'}
        df_new.rename(columns=lambda x: col_mapping.get(x, x), inplace=True)
        
        cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
        for c in cols:
            if c not in df_new.columns:
                df_new[c] = pd.NA
        df_new = df_new[cols]
        df_new['date'] = pd.to_datetime(df_new['date']).dt.strftime('%Y-%m-%d')
        
        df_merged = pd.concat([df_old, df_new], ignore_index=True)
        # 用 date 去重，保留最新拉取的数据
        df_merged = df_merged.sort_values('date').drop_duplicates(subset=['date'], keep='last').reset_index(drop=True)
        df_merged.to_csv(csv_path, index=False)
        logging.info(f"日线拼接完成! 更新后总行数: {len(df_merged)}")
    else:
        logging.info("已经是最新，无需更新日线.")

def update_minute():
    csv_path = DATA_DIR / "300661_5m.csv"
    logging.info(f"--- 更新 300661 5分钟数据 (增量拼接) ---")
    
    if csv_path.exists():
        try:
            df_old = pd.read_csv(csv_path)
            if df_old.empty or 'datetime' not in df_old.columns:
                raise ValueError("Empty or invalid columns")
            last_dt = str(df_old['datetime'].max())
            logging.info(f"找到历史分钟数据. 行数: {len(df_old)}, 最新时间: {last_dt}")
            logging.warning("注: 若历史数据之前是 1 分钟频率(如 README 提及)，这里拼接 5 分钟数据可能会产生频率混杂。您可视情况删掉旧数据。")
        except Exception:
            df_old = pd.DataFrame()
            logging.info("未找到历史分钟数据或读取失败.")

    logging.info("正在使用新浪接口获取 300661 5分钟数据 (自带近2个月历史，拼接去重)...")
    try:
        df_new = ak.stock_zh_a_minute(symbol="sz300661", period="5", adjust="qfq")
    except Exception as e:
        logging.error(f"分钟线获取失败: {e}")
        return

    if df_new is not None and not df_new.empty:
        col_mapping = {'day':'datetime', 'open':'open', 'close':'close', 'high':'high', 'low':'low', 'volume':'volume'}
        df_new.rename(columns=lambda x: col_mapping.get(x, x), inplace=True)
        
        # 新浪数据无 amount
        if 'amount' not in df_new.columns:
            df_new['amount'] = pd.NA
            
        cols = ['datetime', 'open', 'close', 'high', 'low', 'volume', 'amount']
        df_new = df_new[cols]
        
        df_merged = pd.concat([df_old, df_new], ignore_index=True)
        df_merged['datetime'] = pd.to_datetime(df_merged['datetime'])
        df_merged = df_merged.sort_values('datetime').drop_duplicates(subset=['datetime'], keep='last').reset_index(drop=True)
        df_merged['datetime'] = df_merged['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        df_merged.to_csv(csv_path, index=False)
        logging.info(f"分钟线拼接完成! 更新后总行数: {len(df_merged)}, 最新一条时间: {df_merged['datetime'].iloc[-1]}")
    else:
        logging.info("无需更新或无新增分钟数据.")

if __name__ == '__main__':
    update_daily()
    update_minute()
