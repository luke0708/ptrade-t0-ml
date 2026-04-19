import akshare as ak
import pandas as pd

def test_tencent():
    print("Testing Tencent Min Data...")
    try:
        # Some akshare forms use 'tx'. Let's see if there is one. 
        # Usually it's `ak.stock_zh_a_hist_min_tx`. Let's use `ak.__dir__()` or similar to find out.
        funcs = [f for f in dir(ak) if 'min' in f.lower() and 'hist' in f.lower()]
        print("Available min hist functions:", funcs)
    except Exception as e:
        print("Error:", e)

if __name__ == '__main__':
    test_tencent()
