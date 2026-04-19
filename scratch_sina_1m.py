import akshare as ak

def test_sina_1m():
    print("Testing Sina 1m...")
    df = ak.stock_zh_a_minute(symbol="sz300661", period="1", adjust="qfq")
    print(f"Total rows: {len(df)}")
    if len(df) > 0:
        print(f"Start date: {df['day'].min()}")
        print(f"End date: {df['day'].max()}")

test_sina_1m()
