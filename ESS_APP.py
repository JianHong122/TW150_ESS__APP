import streamlit as st
import pandas as pd
import requests
import yfinance as yf
from datetime import datetime, timedelta
import io
import os
import altair as alt

# ==========================================
# 網頁基本設定
# ==========================================
st.set_page_config(page_title="霸王鮮果汁", layout="wide")
st.title("🍹 霸王鮮果汁")

# ==========================================
# 工具函式 (無檔案化處理)
# ==========================================
@st.cache_data(ttl=3600)
def get_trading_days():
    """自動偵測最近兩個台股交易日"""
    try:
        benchmark = yf.Ticker("0050.TW").history(period="15d")
        dates = benchmark.index.tz_localize(None).strftime('%Y%m%d').tolist()
        return dates[-2], dates[-1]
    except Exception as e:
        st.error(f"取得交易日失敗: {e}")
        return None, None

def fetch_twse_ranks(date_str, code):
    """記憶體內下載並解析 TWSE 法人買賣超資料"""
    url = f"https://www.twse.com.tw/rwd/zh/fund/{code}?date={date_str}&response=csv"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        
        csv_data = res.content.decode('cp950', errors='ignore')
        df = pd.read_csv(io.StringIO(csv_data), skiprows=1, on_bad_lines='skip')
        
        df.columns = [str(c).strip() for c in df.columns]
        
        if code == "TWT38U":
            df_extracted = df.iloc[:, [2, 5]].copy()
            df_extracted.columns = ['Name', 'Volume']
        else:
            name_col, vol_col = None, None
            for c in df.columns:
                if '證券名稱' in c: name_col = c
                if '買賣超' in c: vol_col = c
            if not name_col or not vol_col: return {}
            df_extracted = df[[name_col, vol_col]].copy()
            df_extracted.columns = ['Name', 'Volume']

        df_extracted = df_extracted.dropna()
        df_extracted['Name'] = df_extracted['Name'].astype(str).str.strip()
        df_extracted['Volume'] = df_extracted['Volume'].astype(str).str.replace(',', '', regex=False).str.strip()
        df_extracted['Volume'] = pd.to_numeric(df_extracted['Volume'], errors='coerce').fillna(0)
        
        ranks = {}
        df_buy = df_extracted[df_extracted['Volume'] > 0].sort_values(by='Volume', ascending=False).reset_index(drop=True)
        for idx, row in df_buy.iterrows(): ranks[row['Name']] = idx + 1
            
        df_sell = df_extracted[df_extracted['Volume'] < 0].sort_values(by='Volume', ascending=True).reset_index(drop=True)
        for idx, row in df_sell.iterrows(): ranks[row['Name']] = -(idx + 1)
            
        return ranks
    except Exception as e:
        return {}

def calc_ta(df):
    """計算技術指標"""
    if len(df) < 26: return df
    df['5MA'] = df['Close'].rolling(window=5).mean()
    df['10MA'] = df['Close'].rolling(window=10).mean()
    df['20MA'] = df['Close'].rolling(window=20).mean()
    
    df['9_High'] = df['High'].rolling(window=9).max()
    df['9_Low'] = df['Low'].rolling(window=9).min()
    
    rsv_list = []
    for i in range(len(df)):
        h9, l9, c = df['9_High'].iloc[i], df['9_Low'].iloc[i], df['Close'].iloc[i]
        if pd.isna(h9) or pd.isna(l9) or h9 == l9: rsv_list.append(0.0)
        else: rsv_list.append((c - l9) / (h9 - l9) * 100)
            
    K, D = [50.0] * len(df), [50.0] * len(df)
    for i in range(1, len(df)):
        if pd.isna(df['Close'].iloc[i]):
            K[i], D[i] = K[i-1], D[i-1]
        else:
            K[i] = K[i-1] * 2/3 + rsv_list[i] * 1/3
            D[i] = D[i-1] * 2/3 + K[i] * 1/3
            
    df['K'], df['D'] = K, D
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = df['EMA12'] - df['EMA26']
    df['MACD'] = df['DIF'].ewm(span=9, adjust=False).mean()
    return df

def check_conditions(row):
    """檢查多空條件"""
    if pd.isna(row['5MA']) or pd.isna(row['K']) or pd.isna(row['MACD']): return 0
    if (row['5MA'] > row['10MA'] > row['20MA']) and (row['K'] > row['D']) and ((row['DIF'] - row['MACD']) > 0): return 1
    if (row['5MA'] < row['10MA'] < row['20MA']) and (row['K'] < row['D']) and ((row['DIF'] - row['MACD']) < 0): return -1
    return 0

def format_sheet_data(today_stocks, yest_stocks, f_ranks, t_ranks, ind_map):
    """整理表格資料，保持唯一欄位名稱"""
    t_uniq = list(dict.fromkeys(today_stocks))
    y_uniq = list(dict.fromkeys(yest_stocks))
    
    maintained = [s for s in t_uniq if s in y_uniq]
    new_stocks = [s for s in t_uniq if s not in y_uniq]
    leave_stocks = [s for s in y_uniq if s not in t_uniq]
    
    def get_sort_key(s):
        r = f_ranks.get(s, 0)
        try:
            v = float(r)
            if v > 0: return (0, v)
            elif v < 0: return (1, v)
            else: return (2, 0)
        except: return (2, 0)

    maintained.sort(key=get_sort_key)
    new_stocks.sort(key=get_sort_key)
    leave_stocks.sort(key=get_sort_key)
    
    max_len = max(len(maintained), len(new_stocks), len(leave_stocks), 0)
    data = []
    for i in range(max_len):
        row = [""] * 12
        if i < len(maintained):
            s = maintained[i]
            row[0], row[1], row[2], row[3] = s, f_ranks.get(s, ""), t_ranks.get(s, ""), ind_map.get(s, "")
        if i < len(new_stocks):
            s = new_stocks[i]
            row[4], row[5], row[6], row[7] = s, f_ranks.get(s, ""), t_ranks.get(s, ""), ind_map.get(s, "")
        if i < len(leave_stocks):
            s = leave_stocks[i]
            row[8], row[9], row[10], row[11] = s, f_ranks.get(s, ""), t_ranks.get(s, ""), ind_map.get(s, "")
        data.append(row)
        
    cols = [
        "維持個股", "外資(維持)", "投信(維持)", "產業(維持)", 
        "新個股", "外資(新)", "投信(新)", "產業(新)", 
        "離開股", "外資(離)", "投信(離)", "產業(離)"
    ]
    return pd.DataFrame(data, columns=cols), maintained + new_stocks

def style_dataframe(df):
    """為 DataFrame 加上根據法人排行設定的背景顏色"""
    def highlight_cells(row):
        styles = [''] * len(row)
        
        def get_color(f, t):
            try:
                fv, tv = float(f), float(t)
                if fv > 0 and tv > 0: return 'background-color: #FFFF99; color: #000000;'
                if fv < 0 and tv < 0: return 'background-color: #CCFFCC; color: #000000;'
            except: pass
            return ''
            
        styles[0] = get_color(row.iloc[1], row.iloc[2])
        styles[4] = get_color(row.iloc[5], row.iloc[6])
        styles[8] = get_color(row.iloc[9], row.iloc[10])
        
        return styles
        
    return df.style.apply(highlight_cells, axis=1)

def analyze_volume(ticker, start_date, end_date):
    """計算單一個股的 64 日分價量資料，並回傳現價與標記當前價格區間"""
    try:
        hist = yf.Ticker(f"{ticker}.TW").history(start=start_date, end=end_date)
        if hist.empty:
            hist = yf.Ticker(f"{ticker}.TWO").history(start=start_date, end=end_date)
        if hist.empty or len(hist) < 64: return None
        
        hist_64 = hist.tail(64).copy()
        current_price = hist_64['Close'].iloc[-1] # 取得最新現價
        
        max_p = hist_64['High'].max()
        min_p = hist_64['Low'].min()
        if max_p == min_p: max_p, min_p = min_p * 1.05, min_p * 0.95
        
        bin_size = (max_p - min_p) / 20
        
        # 計算現價落在哪一個 index 區間
        curr_idx = int((current_price - min_p) / bin_size)
        curr_idx = max(0, min(19, curr_idx)) # 確保不超出 0~19 的範圍
        
        # 加上 is_current 布林值標記
        bins = [{'start': min_p + i * bin_size, 'end': min_p + (i + 1) * bin_size, 'vol': 0, 'is_current': i == curr_idx} for i in range(20)]
        
        for _, row in hist_64.iterrows():
            if pd.isna(row['Volume']) or row['Volume'] <= 0: continue
            total_vol = row['Volume']
            flat_prices = [{'price': row['Open'], 'vol': total_vol * 0.05}, 
                           {'price': row['Close'], 'vol': total_vol * 0.30}]
            
            vol_rem = total_vol * 0.65
            if row['High'] > row['Low']:
                curr_p = row['Low']
                ticks = []
                while curr_p <= row['High'] + 1e-5:
                    ticks.append(curr_p)
                    if curr_p < 10: step = 0.01
                    elif curr_p < 50: step = 0.05
                    elif curr_p < 100: step = 0.10
                    elif curr_p < 500: step = 0.50
                    elif curr_p < 1000: step = 1.00
                    else: step = 5.00
                    curr_p = round(curr_p + step, 2)
                if ticks and ticks[-1] < row['High'] - 1e-5: ticks.append(row['High'])
                
                if ticks:
                    v_tick = vol_rem / len(ticks)
                    for t in ticks: flat_prices.append({'price': t, 'vol': v_tick})
                else: flat_prices.append({'price': row['Close'], 'vol': vol_rem})
            else:
                flat_prices.append({'price': row['Close'], 'vol': vol_rem})
                
            for item in flat_prices:
                p, v = item['price'], item['vol']
                if pd.isna(p): continue
                if p >= max_p: bins[19]['vol'] += v
                elif p <= min_p: bins[0]['vol'] += v
                else:
                    idx = int((p - min_p) / bin_size)
                    bins[min(idx, 19)]['vol'] += v
                    
        df_bins = pd.DataFrame(bins)
        df_bins['label'] = df_bins.apply(lambda x: f"{x['start']:.2f}~{x['end']:.2f}", axis=1)
        
        # 回傳圖表 dataframe 與 現價
        return df_bins[['label', 'vol', 'start', 'is_current']], current_price
    except:
        return None

# ==========================================
# 介面渲染與主程式
# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TW50100_PATH = os.path.join(BASE_DIR, "TW50100.xlsx")

st.write("點擊下方按鈕開始自動載入名單並計算多空指標：")
run_btn = st.button("🚀 開始分析", use_container_width=True)

if run_btn:
    if not os.path.exists(TW50100_PATH):
        st.error(f"⚠️ 找不到 {TW50100_PATH}！請確保該檔案已上傳至 GitHub 專案中。")
        st.stop()

    st.divider()

    with st.spinner("正在背景抓取資料與計算技術指標，這可能需要幾分鐘..."):
        yest_date, today_date = get_trading_days()
        
        df_tw = pd.read_excel(TW50100_PATH, engine='openpyxl', dtype=str)
        col_tkr = df_tw.columns[0]
        col_name = df_tw.columns[1]
        col_ind = df_tw.columns[2] if len(df_tw.columns) > 2 else None
        
        name_to_ticker = {}
        name_to_ind = {}
        
        for _, row in df_tw.iterrows():
            if pd.notna(row[col_name]) and pd.notna(row[col_tkr]):
                name = str(row[col_name]).strip()
                tkr = str(row[col_tkr]).strip()
                if tkr.endswith('.0'): tkr = tkr[:-2]
                name_to_ticker[name] = tkr
                name_to_ind[name] = str(row[col_ind]).strip() if (col_ind and pd.notna(row[col_ind])) else ""
        
        f_ranks = fetch_twse_ranks(today_date, "TWT38U")
        t_ranks = fetch_twse_ranks(today_date, "TWT44U")
        
        target_today = datetime.strptime(today_date, "%Y%m%d")
        start_date = (target_today - timedelta(days=150)).strftime("%Y-%m-%d")
        end_date = (target_today + timedelta(days=1)).strftime("%Y-%m-%d")
        
        A_put, A_call, B_put, B_call = [], [], [], []
        
        progress_bar = st.progress(0)
        total_stocks = len(name_to_ticker)
        
        for idx, (name, tkr) in enumerate(name_to_ticker.items()):
            try:
                hist = yf.Ticker(f"{tkr}.TW").history(start=start_date, end=end_date)
                if hist.empty: hist = yf.Ticker(f"{tkr}.TWO").history(start=start_date, end=end_date)
                
                if not hist.empty and len(hist) > 26:
                    hist = calc_ta(hist)
                    hist['DateStr'] = hist.index.tz_localize(None).strftime('%Y%m%d')
                    
                    r_today = hist[hist['DateStr'] == today_date]
                    r_yest = hist[hist['DateStr'] == yest_date]
                    
                    if not r_today.empty:
                        cond = check_conditions(r_today.iloc[0])
                        if cond == 1: A_put.append(name)
                        elif cond == -1: A_call.append(name)
                            
                    if not r_yest.empty:
                        cond = check_conditions(r_yest.iloc[0])
                        if cond == 1: B_put.append(name)
                        elif cond == -1: B_call.append(name)
            except: pass
            progress_bar.progress((idx + 1) / total_stocks)
            
        progress_bar.empty()
        
        df_sheet1, bullish_stocks = format_sheet_data(A_put, B_put, f_ranks, t_ranks, name_to_ind)
        df_sheet2, _ = format_sheet_data(A_call, B_call, f_ranks, t_ranks, name_to_ind)

    st.header(f"📋 今日個股多空清單 ({today_date})")
    
    # 透過 column_config 覆寫前台抬頭
    display_config = {
        "外資(維持)": st.column_config.Column("外資排行"),
        "投信(維持)": st.column_config.Column("投信排行"),
        "外資(新)": st.column_config.Column("外資排行"),
        "投信(新)": st.column_config.Column("投信排行"),
        "外資(離)": st.column_config.Column("外資排行"),
        "投信(離)": st.column_config.Column("投信排行")
    }

    # 計算動態表格高度 (每行約 35px，表頭約 40px，上下限 150px ~ 800px)
    height_sheet1 = min(max(150, len(df_sheet1) * 35 + 43), 800)
    height_sheet2 = min(max(150, len(df_sheet2) * 35 + 43), 800)

    tab1, tab2 = st.tabs(["🟢 多頭個股清單", "🔴 空頭個股清單"])
    
    with tab1:
        styled_df1 = style_dataframe(df_sheet1)
        st.dataframe(styled_df1, use_container_width=True, hide_index=True, column_config=display_config, height=height_sheet1)
    with tab2:
        styled_df2 = style_dataframe(df_sheet2)
        st.dataframe(styled_df2, use_container_width=True, hide_index=True, column_config=display_config, height=height_sheet2)

    st.divider()

    st.header("📊 多頭個股 64 日分價量分析")
    st.caption("僅計算「維持」與「新進」的多頭個股。點擊各股名稱展開圖表。")
    
    if bullish_stocks:
        target_today = datetime.strptime(today_date, "%Y%m%d")
        v_start = (target_today - timedelta(days=150)).strftime("%Y-%m-%d")
        v_end = (target_today + timedelta(days=1)).strftime("%Y-%m-%d")
        
        for stock_name in bullish_stocks:
            tkr = name_to_ticker.get(stock_name)
            if not tkr: continue
            
            result = analyze_volume(tkr, v_start, v_end)
            if result is not None:
                df_vol, current_price = result
                # 標籤加上現價資訊
                with st.expander(f"🔹 {stock_name} ({tkr}) - 分價量圖表 / 現價 : {current_price:.2f}"):
                    
                    # Altair 條件上色 (如果 is_current 為 True 標橘色，否則維持預設鋼鐵藍)
                    color_condition = alt.condition(
                        alt.datum.is_current == True,
                        alt.value('orange'),
                        alt.value('steelblue')
                    )

                    chart = alt.Chart(df_vol).mark_bar(orient='horizontal').encode(
                        x=alt.X('vol:Q', title='累積成交量 (股)'),
                        y=alt.Y('label:N', title='價格區間 (TWD)', sort=alt.SortField(field='start', order='descending')),
                        color=color_condition,
                        tooltip=['label', 'vol']
                    ).properties(height=350)
                    
                    st.altair_chart(chart, use_container_width=True)
            else:
                with st.expander(f"🔹 {stock_name} ({tkr}) - 分價量圖表"):
                    st.write("查無有效的分價量資料。")
    else:
        st.info("今日無多頭個股需計算分價量。")
