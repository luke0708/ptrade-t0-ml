import os
import pandas as pd
import numpy as np
import logging
from pathlib import Path

# ==========================================
# 初始化日志记录
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

WORK_DIR = Path(r"E:\AI炒股\机器学习")
DATA_DIR = WORK_DIR / "data"

def guess_minute_frequency(df):
    """自动识别分钟线频率"""
    if len(df) < 2:
        return "未知"
    diffs = df['datetime'].diff().dropna()
    mode_seconds = diffs.dt.total_seconds().mode()
    if len(mode_seconds) > 0:
        val = int(mode_seconds.iloc[0])
        if val == 60:
            return "1m"
        elif val == 300:
            return "5m"
        else:
            return f"{val}秒"
    return "未知"

def standardize_daily(filepath, is_main=False, prefix=''):
    """日线文件标准化"""
    logger.info(f"--- 读取并标准化日线文件: {filepath.name} ---")
    if not filepath.exists():
        logger.error(f"文件不存在: {filepath}")
        return pd.DataFrame()
        
    df = pd.read_csv(filepath)
    logger.info(f"原始列名: {df.columns.tolist()}")
    logger.info(f"原始行数: {len(df)}")
    
    # 中英文列名兼容映射
    col_mapping = {'日期':'date', '开盘':'open', '收盘':'close', '最高':'high', '最低':'low', '成交量':'volume', '成交额':'amount'}
    df.rename(columns=lambda x: col_mapping.get(x, x), inplace=True)
    
    df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.strftime('%Y-%m-%d')
    logger.info(f"时间范围: {df['date'].min()} 到 {df['date'].max()}")
    
    cols_to_keep = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
    for c in cols_to_keep:
        if c not in df.columns:
            df[c] = np.nan
        elif c != 'date':
            df[c] = pd.to_numeric(df[c], errors='coerce')
            
    df = df[cols_to_keep]
    
    # 主标的基础排雷
    if is_main:
        df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
        
    df = df.sort_values('date').drop_duplicates(subset=['date']).reset_index(drop=True)
    
    if prefix:
        df.rename(columns={c: f"{prefix}{c}" for c in cols_to_keep if c != 'date'}, inplace=True)
        
    return df

def standardize_minute(filepath, prefix=''):
    """分钟文件标准化"""
    logger.info(f"--- 读取并标准化分钟文件: {filepath.name} ---")
    if not filepath.exists():
        logger.error(f"文件不存在: {filepath}")
        return pd.DataFrame()
        
    df = pd.read_csv(filepath)
    logger.info(f"原始列名: {df.columns.tolist()}")
    logger.info(f"原始行数: {len(df)}")
    
    col_mapping = {'时间':'datetime', '开盘':'open', '收盘':'close', '最高':'high', '最低':'low', '成交量':'volume', '成交额':'amount'}
    df.rename(columns=lambda x: col_mapping.get(x, x), inplace=True)
    
    df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
    df = df.dropna(subset=['datetime']).copy()
    df['date'] = df['datetime'].dt.strftime('%Y-%m-%d')
    
    logger.info(f"时间范围: {df['datetime'].min()} 到 {df['datetime'].max()}")
    
    cols_to_keep = ['datetime', 'date', 'open', 'close', 'high', 'low', 'volume', 'amount']
    for c in cols_to_keep:
        if c not in df.columns:
            df[c] = np.nan
        elif c not in ['datetime', 'date']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
            
    df = df.sort_values('datetime').drop_duplicates(subset=['datetime']).reset_index(drop=True)
    
    # 基础清洗逻辑改进：过滤高低收小于等于0的严重异常，不再误杀仅 open=0 的合法记录
    mask_anomaly = (df['high'] <= 0) | (df['low'] <= 0) | (df['close'] <= 0)
    anomaly_count = mask_anomaly.sum()
    if anomaly_count > 0:
        logger.warning(f"发现并删除了 {anomaly_count} 条 H/L/C <= 0 的严重异常分钟记录")
        df = df[~mask_anomaly].reset_index(drop=True)
        
    # 对于 open <= 0 的可挽救记录，使用前一根 bar 的 close 填补，首根使用自己的 close
    open_zero_mask = df['open'] <= 0
    open_zero_count = open_zero_mask.sum()
    if open_zero_count > 0:
        logger.warning(f"发现并修复了 {open_zero_count} 条 open <= 0 的异常记录 (使用前收/现收填补)")
        df.loc[open_zero_mask, 'open'] = np.nan
        df['open'] = df['open'].fillna(df['close'].shift(1)).fillna(df['close'])
        
    # Amount检查
    if df['amount'].isnull().all():
        logger.warning(f"数据源缺失发现：{filepath.name} 的 'amount' 列全部为 NaN。")
        
    # 分辨粒度与打印条数分布
    freq = guess_minute_frequency(df)
    bar_counts = df.groupby('date').size()
    logger.info(f"根据相邻时间戳识别到的真实分钟粒度: {freq}")
    logger.info(f"每日 bar 数分布估算: 平均 {bar_counts.mean():.1f} 根，最小 {bar_counts.min()} 根，最大 {bar_counts.max()} 根")
    
    return df

def generate_daily_features(df, prefix='', is_main=False):
    """日线辅助衍生特征提取"""
    d = df.copy()
    
    o = f'{prefix}open' if prefix else 'open'
    c = f'{prefix}close' if prefix else 'close'
    h = f'{prefix}high' if prefix else 'high'
    l = f'{prefix}low' if prefix else 'low'
    v = f'{prefix}volume' if prefix else 'volume'
    
    pre_c = d[c].shift(1)
    d[f'{prefix}daily_return'] = d[c] / pre_c - 1
    d[f'{prefix}daily_range'] = np.where(d[l] > 0, d[h] / d[l] - 1, np.nan)
    
    if is_main:
        d['pre_close'] = pre_c
        d['gap_pct'] = d[o] / pre_c - 1
        d['ma5'] = d[c].rolling(5).mean()
        d['ma10'] = d[c].rolling(10).mean()
        d['ma20'] = d[c].rolling(20).mean()
        d['ma60'] = d[c].rolling(60).mean()
        d['vol_ma5'] = d[v].rolling(5).mean()
        d['vol_ma20'] = d[v].rolling(20).mean()
        d['close_to_ma20'] = d[c] / d['ma20'] - 1
        d['close_to_ma60'] = d[c] / d['ma60'] - 1
    else:
        d[f'{prefix}ma5'] = d[c].rolling(5).mean()
        d[f'{prefix}ma20'] = d[c].rolling(20).mean()
        d[f'{prefix}close_to_ma20'] = d[c] / d[f'{prefix}ma20'] - 1
        
    return d

def extract_minute_features(df_min, prefix):
    """从分钟特征聚合生成日维度特征"""
    if df_min.empty:
        return pd.DataFrame()
        
    amount_all_nan = df_min['amount'].isnull().all()
    if amount_all_nan:
        logger.warning(f"[{prefix.strip('_')}] 由于 amount 完全缺失，成交额占比与 VWAP 特征将保留为 NaN")
        
    results = []
    
    for date, group in df_min.groupby('date'):
        group = group.sort_values('datetime')
        if group.empty:
            continue
            
        bar_count = len(group)
        
        times = group['datetime'].dt.time
        open30 = group[(times >= pd.to_datetime('09:25').time()) & (times <= pd.to_datetime('10:00').time())]
        am = group[(times <= pd.to_datetime('11:30').time())]
        pm = group[(times >= pd.to_datetime('13:00').time())]
        last30 = group[(times >= pd.to_datetime('14:30').time()) & (times <= pd.to_datetime('15:00').time())]
        
        first_open = group.iloc[0]['open']
        last_close = group.iloc[-1]['close']
        day_max_high = group['high'].max()
        day_min_low = group['low'].min()
        
        # 首 30 分钟
        if len(open30) > 0 and open30.iloc[0]['open'] > 0:
            open30_return = open30.iloc[-1]['close'] / open30.iloc[0]['open'] - 1
            min_low30 = open30['low'].min()
            open30_range = open30['high'].max() / min_low30 - 1 if min_low30 > 0 else np.nan
            open30_vol = open30['volume'].sum()
            open30_amt = open30['amount'].sum(min_count=1)
        else:
            open30_return = np.nan
            open30_range = np.nan
            open30_vol = 0
            open30_amt = np.nan
            
        # 上午 (AM)
        if len(am) > 0 and am.iloc[0]['open'] > 0:
            am_return = am.iloc[-1]['close'] / am.iloc[0]['open'] - 1
            morning_high_break = am['high'].max() / first_open - 1 if first_open > 0 else np.nan
        else:
            am_return = np.nan
            morning_high_break = np.nan
            
        # 下午 (PM)
        if len(pm) > 0 and pm.iloc[0]['open'] > 0:
            pm_return = pm.iloc[-1]['close'] / pm.iloc[0]['open'] - 1
            afternoon_low_break = pm['low'].min() / first_open - 1 if first_open > 0 else np.nan
        else:
            pm_return = np.nan
            afternoon_low_break = np.nan
            
        # 最后 30 分钟
        if len(last30) > 0 and last30.iloc[0]['open'] > 0:
            last30_return = last30.iloc[-1]['close'] / last30.iloc[0]['open'] - 1
        else:
            last30_return = np.nan
            
        # 日内整体维度
        intraday_range = day_max_high / day_min_low - 1 if day_min_low > 0 else np.nan
        day_return_from_minutes = last_close / first_open - 1 if first_open > 0 else np.nan
        
        total_vol = group['volume'].sum()
        total_amt = group['amount'].sum(min_count=1)
        
        open30_volume_ratio = open30_vol / total_vol if total_vol > 0 else np.nan
        
        # VWAP与Amount处理
        if amount_all_nan or pd.isna(total_amt) or total_amt == 0:
            open30_amount_ratio = np.nan
            close_vwap_gap = np.nan
        else:
            open30_amount_ratio = open30_amt / total_amt if pd.notna(open30_amt) else np.nan
            vwap = total_amt / total_vol if total_vol > 0 else np.nan
            close_vwap_gap = last_close / vwap - 1 if pd.notna(vwap) and vwap > 0 else np.nan
            
        results.append({
            'date': date,
            f'{prefix}bar_count': bar_count,
            f'{prefix}open30_return': open30_return,
            f'{prefix}open30_range': open30_range,
            f'{prefix}am_return': am_return,
            f'{prefix}pm_return': pm_return,
            f'{prefix}last30_return': last30_return,
            f'{prefix}intraday_range': intraday_range,
            f'{prefix}day_return_from_minutes': day_return_from_minutes,
            f'{prefix}close_vwap_gap': close_vwap_gap,
            f'{prefix}open30_volume_ratio': open30_volume_ratio,
            f'{prefix}open30_amount_ratio': open30_amount_ratio,
            f'{prefix}morning_high_break': morning_high_break,
            f'{prefix}afternoon_low_break': afternoon_low_break,
        })
        
    return pd.DataFrame(results)

def main():
    logger.info("=========== 1. 日线特征处理与生成 ===========")
    df_stk_d = standardize_daily(DATA_DIR / '300661.csv', is_main=True)
    df_idx_d = standardize_daily(DATA_DIR / '399006.csv', prefix='idx_')
    df_sec_d = standardize_daily(DATA_DIR / '512480.csv', prefix='sec_')
    
    df_stk_d = generate_daily_features(df_stk_d, is_main=True)
    df_idx_d = generate_daily_features(df_idx_d, prefix='idx_')
    df_sec_d = generate_daily_features(df_sec_d, prefix='sec_')
    
    logger.info("=========== 2. 分钟特征处理与生成 ===========")
    df_stk_m = standardize_minute(DATA_DIR / '300661_5m.csv')
    df_idx_m = standardize_minute(DATA_DIR / '399006_5m.csv')
    df_sec_m = standardize_minute(DATA_DIR / '512480_5m.csv')
    
    feat_stk_m = extract_minute_features(df_stk_m, prefix='stk_m_')
    feat_idx_m = extract_minute_features(df_idx_m, prefix='idx_m_')
    feat_sec_m = extract_minute_features(df_sec_m, prefix='sec_m_')
    
    logger.info("=========== 3. 横向宽表合并 ===========")
    logger.info(f"Merge 前主表 (300661) 行数: {len(df_stk_d)}")
    df_base = df_stk_d.copy()
    
    # 结合日线辅助
    df_base = df_base.merge(df_idx_d, on='date', how='left')
    df_base = df_base.merge(df_sec_d, on='date', how='left')
    logger.info(f"日线全部合并之后行数: {len(df_base)}")
    
    # 向前填充外部环境(idx, sec)特征缺失
    idx_sec_cols = [c for c in df_base.columns if c.startswith('idx_') or c.startswith('sec_')]
    df_base[idx_sec_cols] = df_base[idx_sec_cols].ffill()
    
    # 结合分钟辅助
    if not feat_stk_m.empty:
        df_base = df_base.merge(feat_stk_m, on='date', how='left')
    if not feat_idx_m.empty:
        df_base = df_base.merge(feat_idx_m, on='date', how='left')
    if not feat_sec_m.empty:
        df_base = df_base.merge(feat_sec_m, on='date', how='left')
    logger.info(f"分钟聚合全部合并之后行数: {len(df_base)}")
    
    logger.info("=========== 4. 回归目标计算 ===========")
    df_base['target_upside_t1'] = df_base['high'].shift(-1) / df_base['close'] - 1
    df_base['target_downside_t1'] = df_base['low'].shift(-1) / df_base['close'] - 1
    
    # 最后一天的 T+1 是 NaN，删掉
    df_base = df_base.iloc[:-1].reset_index(drop=True)
    logger.info("目标列 (Upside 和 Downside) 统计摘要:\n" + str(df_base[['target_upside_t1', 'target_downside_t1']].describe()))
    
    logger.info("=========== 5. 输出记录与交集说明 ===========")
    logger.info(f"最终完整宽表维度: {df_base.shape[0]} 行 x {df_base.shape[1]} 列")
    logger.info(f"宽表缺失 Top 20 统计:\n{df_base.isnull().sum().sort_values(ascending=False).head(20)}")
    
    out_main_path = DATA_DIR / "300661_regression_dataset.csv"
    df_base.to_csv(out_main_path, index=False)
    logger.info(f"👉 最终主宽表生成完毕! 路径: {out_main_path}")
    
    # 交集处理 (要求明确记录并保存分钟特征的交集)
    sub_mask = df_base['stk_m_bar_count'].notnull() & df_base['idx_m_bar_count'].notnull() & df_base['sec_m_bar_count'].notnull()
    df_sub = df_base[sub_mask].reset_index(drop=True)
    out_sub_path = DATA_DIR / "300661_regression_dataset_with_minute_intersection.csv"
    
    if len(df_sub) > 0:
        df_sub.to_csv(out_sub_path, index=False)
        sub_ratio = len(df_sub) / len(df_base) * 100
        logger.info(f"========== 【重要事实打印】 ==========")
        logger.info("受限于分钟数据不同的采集跨度限制，全变量有效截面重叠期极短：")
        logger.info(f"分钟交集宽表起始至终点: [{df_sub['date'].min()}] - [{df_sub['date'].max()}]")
        logger.info(f"有效分钟交集只具有 {len(df_sub)} 行, 仅占主表全长比例的 {sub_ratio:.2f}%")
        logger.info(f"👉 交集子集保存路径: {out_sub_path}")
    else:
        logger.warning(f"未能找到三方重叠的分钟特征！略过子文件输出。")
        
    logger.info(f"宽表预览(前5行):\n{df_base.head()}")
    logger.info(f"宽表预览(后5行):\n{df_base.tail()}")
    
if __name__ == "__main__":
    main()
