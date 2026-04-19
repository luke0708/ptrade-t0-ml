import akshare as ak

# ETF
df_etf = ak.fund_etf_hist_em(symbol="512480", period="daily", start_date="20240101", end_date="20240110")
print("ETF:")
print(df_etf.head())

# Index
df_index = ak.index_zh_a_hist(symbol="399006", period="daily", start_date="20240101", end_date="20240110")
print("Index:")
print(df_index.head())
