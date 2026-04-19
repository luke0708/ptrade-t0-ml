import akshare as ak
import pandas as pd

def test_sina():
    print("Fetching Sina 5m for 300661...")
    df = ak.stock_zh_a_minute(symbol="sz300661", period="5", adjust="qfq")
    print(f"Rows: {len(df)}")
    if len(df) > 0:
        print("Columns:", df.columns.tolist())
        print("Head:")
        print(df.head(2))
        print("Tail:")
        print(df.tail(2))

if __name__ == '__main__':
    test_sina()
