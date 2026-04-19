import baostock as bs
import pandas as pd

def test_bs():
    lg = bs.login()
    if lg.error_code != '0':
        print("login fail")
        return
        
    rs = bs.query_history_k_data_plus("sz.300661",
        "date,time,code,open,high,low,close,volume,amount",
        start_date='2026-01-01', end_date='2026-04-13',
        frequency="5", adjustflag="3")
    
    data_list = []
    while (rs.error_code == '0') & rs.next():
        data_list.append(rs.get_row_data())
        
    df = pd.DataFrame(data_list, columns=rs.fields)
    print(f"BaoStock rows: {len(df)}")
    if len(df) > 0:
        print("Min date:", df['date'].min())
        print("Max date:", df['date'].max())
        print(df.tail(2))
    bs.logout()

if __name__ == '__main__':
    test_bs()
