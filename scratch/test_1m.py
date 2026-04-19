import sys
from pathlib import Path

# Add project dir to path
sys.path.append("E:/AI炒股/机器学习")
from download_new_5m_data import get_em_kline_ps

df = get_em_kline_ps("0.300661", 1) # freq 1 = 1 minute?
if len(df) > 0:
    print(f"Got {len(df)} rows of 1m data.")
    print(df.head())
    print(df.tail())
else:
    print("Failed to get 1m data.")
