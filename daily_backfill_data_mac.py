import sys
from pathlib import Path

# 添加 vendor 目录到 sys.path 以便导入下载的依赖
vendor_dir = str(Path(__file__).parent / "vendor")
if vendor_dir not in sys.path:
    sys.path.insert(0, vendor_dir)

import pandas as pd
import akshare as ak
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_DIR = Path(__file__).parent / "data"

def get_ak_daily(symbol):
    """
    使用 akshare 获取日线数据 (Mac 专用)
    """
    try:
        # 尝试使用通用的 stock_zh_a_hist (支持股票和指数)
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
        
        if df is None or df.empty:
            # 如果是 ETF，尝试 fund_etf_hist_em
            df = ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust="qfq")
            
        if df is None or df.empty:
            return pd.DataFrame()
            
        # 映射字段
        col_mapping = {
            '日期': 'date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount'
        }
        df.rename(columns=col_mapping, inplace=True)
        # 统一日期格式为 YYYY-MM-DD
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        return df[['date', 'open', 'close', 'high', 'low', 'volume', 'amount']]
    except Exception as e:
        logging.error(f"Fetch {symbol} failed: {e}")
        return pd.DataFrame()

def update_daily_file(symbol, csv_filename):
    csv_path = DATA_DIR / csv_filename
    logging.info(f"--- 更新 {csv_filename} (日线数据) ---")
    
    if csv_path.exists():
        try:
            df_old = pd.read_csv(csv_path)
            if 'date' not in df_old.columns:
                 df_old = pd.DataFrame()
        except:
            df_old = pd.DataFrame()
    else:
        df_old = pd.DataFrame()

    df_new = get_ak_daily(symbol)
    if df_new.empty:
        logging.warning(f"新数据 {symbol} 获取为空，跳过更新")
        return

    if not df_old.empty:
        df_old['date'] = pd.to_datetime(df_old['date']).dt.strftime('%Y-%m-%d')
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
        try:
            df_old = pd.read_csv(csv_path)
            if 'datetime' not in df_old.columns:
                df_old = pd.DataFrame()
        except:
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
        
        if 'open' in df_new.columns and 'close' in df_new.columns:
            df_new['open'] = df_new.apply(lambda row: row['close'] if row['open'] == 0.0 else row['open'], axis=1)

        df_new['code'] = '300661.SZ'
        if 'price' not in df_new.columns:
            df_new['price'] = df_new['close']

        cols = ['datetime', 'code', 'open', 'high', 'low', 'close', 'volume', 'amount', 'price']
        for c in cols:
            if c not in df_new.columns:
                df_new[c] = pd.NA
        df_new = df_new[cols]
        
        df_new['datetime'] = pd.to_datetime(df_new['datetime']).dt.strftime('%Y-%m-%d %H:%M:%S')

        if not df_old.empty:
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
    # 512480: 半导体 ETF
    # 399006: 创业板指
    update_daily_file("512480", "512480.csv")
    update_daily_file("399006", "399006.csv")
    update_300661_1m()
