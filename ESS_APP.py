import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import os
import time
import io
from datetime import datetime

# --- 介面基本設定 (針對手機優化) ---
st.set_page_config(page_title="籌碼追蹤 APP", page_icon="📈", layout="centered")
CACHE_DIR = "cache_data"
os.makedirs(CACHE_DIR, exist_ok=True)

# --- 核心處理函數 ---
@st.cache_data(ttl=3600)  # 快取1小時，避免頻繁呼叫 yfinance
def get_trading_days(days=20):
    """取得最近 N 個台股交易日"""
    twii = yf.Ticker("^TWII")
    # 抓取近 2 個月資料，確保有足夠的 20 個交易日
    df = twii.history(period="2mo") 
    dates = df.index[-days:].strftime('%Y%m%d').tolist()
    return dates

def clean_twse_number(val):
    """清理證交所數字格式 (去除逗號)"""
    if pd.isna(val):
        return 0
    try:
        return float(str(val).replace(',', '').strip())
    except:
        return 0

def fetch_twse_data(date_str, type_):
    """抓取單日證交所 CSV 資料並解析"""
    if type_ == 'foreign':
        url = f"https://www.twse.com.tw/fund/TWT38U?date={date_str}&response=csv"
    else:
        url = f"https://www.twse.com.tw/fund/TWT44U?date={date_str}&response=csv"
        
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        
        # 過濾出有包含逗號的有效行數 (避開證交所 CSV 頭尾的雜訊)
        lines = [line for line in res.text.split('\n') if len(line.split('",')) >= 6]
        text_data = '\n'.join(lines)
        
        # 使用 pandas 讀取
        df = pd.read_csv(io.StringIO(text_data), header=None, on_bad_lines='skip')
        
        # 依需求擷取欄位: B欄(1)=代號, C欄(2)=名稱, F欄(5)=買賣超
        if df.shape[1] > 5:
            df = df[[1, 2, 5]]
            df.columns = ['Code', 'Name', 'Net']
            # 清理股票代號 (證交所常有 ="2330" 這種格式)
            df['Code'] = df['Code'].astype(str).str.replace('=', '').str.replace('"', '').str.strip()
            # 清理買賣超金額
            df['Net'] = df['Net'].apply(clean_twse_number)
            return df
    except Exception as e:
        # 忽略單日無資料或下載失敗的錯誤 (如颱風假等)
        pass
        
    return pd.DataFrame(columns=['Code', 'Name', 'Net'])

def get_data_for_date(date_str, force_update=False):
    """取得資料：優先從本地 cache 讀取，沒有或強制更新才下載"""
    f_path = os.path.join(CACHE_DIR, f"{date_str}_foreign.csv")
    t_path = os.path.join(CACHE_DIR, f"{date_str}_trust.csv")

    if force_update or not (os.path.exists(f_path) and os.path.exists(t_path)):
        # 下載資料
        f_df = fetch_twse_data(date_str, 'foreign')
        t_df = fetch_twse_data(date_str, 'trust')
        
        # 存入快取
        if not f_df.empty:
            f_df.to_csv(f_path, index=False, encoding='utf-8-sig')
        if not t_df.empty:
            t_df.to_csv(t_path, index=False, encoding='utf-8-sig')
            
        time.sleep(2.5)  # 證交所防爬蟲機制，需暫停
        return f_df, t_df
    else:
        # 從本地讀取
        f_df = pd.read_csv(f_path, dtype={'Code': str})
        t_df = pd.read_csv(t_path, dtype={'Code': str})
        return f_df, t_df

# --- 主程式 UI 與邏輯 ---
st.title("📊 法人籌碼近20日追蹤")

# 1. 讀取 TW150.xlsx (假設檔案與 app.py 在同一層目錄)
try:
    tw150_df = pd.read_excel('TW150.xlsx', header=None, dtype=str)
    # A欄=代號(0), B欄=名稱(1)
    target_stocks = dict(zip(tw150_df[0].str.strip(), tw150_df[1].str.strip()))
except Exception as e:
    st.error("找不到 TW150.xlsx，請確認檔案是否存在。")
    st.stop()

# 2. 獲取近 20 日交易日
trading_days = get_trading_days(20)

# 3. 側邊欄設定 / 強制更新按鈕
with st.sidebar:
    st.header("⚙️ 設定與狀態")
    st.write(f"📊 監測日期範圍:\n {trading_days[0]} ~ {trading_days[-1]}")
    st.write(f"🎯 觀察名單數量: {len(target_stocks)} 檔")
    force_update = st.button("🔄 強制重新下載/更新資料")

# 4. 下載與運算資料
# 初始化統計字典
stats = {code: {'Name': name, 'f_buy': 0, 't_buy': 0, 'f_sell': 0, 't_sell': 0} 
         for code, name in target_stocks.items()}

progress_text = "讀取/下載資料中，請稍候..."
progress_bar = st.progress(0, text=progress_text)

for idx, date in enumerate(trading_days):
    f_df, t_df = get_data_for_date(date, force_update)
    
    # 計算外資天數
    if not f_df.empty:
        # 只留下在 TW150 清單中的股票
        f_filtered = f_df[f_df['Code'].isin(target_stocks.keys())]
        for _, row in f_filtered.iterrows():
            code = row['Code']
            if row['Net'] > 0:
                stats[code]['f_buy'] += 1
            elif row['Net'] < 0:
                stats[code]['f_sell'] += 1
                
    # 計算投信天數
    if not t_df.empty:
        t_filtered = t_df[t_df['Code'].isin(target_stocks.keys())]
        for _, row in t_filtered.iterrows():
            code = row['Code']
            if row['Net'] > 0:
                stats[code]['t_buy'] += 1
            elif row['Net'] < 0:
                stats[code]['t_sell'] += 1
                
    # 更新進度條
    progress_bar.progress((idx + 1) / 20, text=f"正在處理: {date} ({idx+1}/20)")

progress_bar.empty() # 跑完隱藏進度條

# 5. 資料整理與排序
result_df = pd.DataFrame.from_dict(stats, orient='index')

# 建立兩個分頁 (適合手機滑動操作)
tab1, tab2 = st.tabs(["🔥 外資買超為主", "📈 投信買超為主"])

with tab1:
    st.subheader("前 30 名 - 外資買超天數排序")
    df_foreign = result_df[['Name', 'f_buy', 't_buy', 'f_sell', 't_sell']].copy()
    df_foreign.columns = ['個股名稱', '外資買超天數', '投信買超天數', '外資賣超天數', '投信賣超天數']
    df_foreign = df_foreign.sort_values(by=['外資買超天數', '投信買超天數'], ascending=[False, False]).head(30)
    
    # 設定 DataFrame 顯示樣式隱藏 index，在手機上更乾淨
    st.dataframe(df_foreign, use_container_width=True, hide_index=True)

with tab2:
    st.subheader("前 30 名 - 投信買超天數排序")
    df_trust = result_df[['Name', 't_buy', 'f_buy', 't_sell', 'f_sell']].copy()
    df_trust.columns = ['個股名稱', '投信買超天數', '外資買超天數', '投信賣超天數', '外資賣超天數']
    # 依循需求：以投信為主時，遇相同天數再以外資買超天數作為輔助排序
    df_trust = df_trust.sort_values(by=['投信買超天數', '外資買超天數'], ascending=[False, False]).head(30)
    
    st.dataframe(df_trust, use_container_width=True, hide_index=True)
