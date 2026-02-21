import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
import numpy as np

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Strategy Pro")

# --- 永続的なウォッチリストの初期化 (Session State) ---
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = ["9984.T", "6330.T", "7270.T"] # 初期値として設定

# --- 主要銘柄データベース ---
TICKER_MAP = {
    "8035.T": "東京エレク", "6920.T": "レーザーテク", "6857.T": "アドバンテ", "6723.T": "ルネサス",
    "6758.T": "ソニーG", "6501.T": "日立", "9984.T": "SBG", "6330.T": "東洋エンジ",
    "7203.T": "トヨタ", "7267.T": "ホンダ", "7270.T": "SUBARU", "8306.T": "三菱UFJ",
    "9101.T": "日本郵船", "9104.T": "商船三井", "9107.T": "川崎汽船"
}

# --- 解析ロジック (MTF + 反発検知) ---
def calculate_heikin_ashi(df):
    ha_df = df.copy()
    ha_df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    ha_df['HA_Open'] = 0.0
    ha_df.iloc[0, ha_df.columns.get_loc('HA_Open')] = (df.iloc[0]['Open'] + df.iloc[0]['Close']) / 2
    for i in range(1, len(df)):
        ha_df.iloc[i, ha_df.columns.get_loc('HA_Open')] = (ha_df.iloc[i-1]['HA_Open'] + ha_df.iloc[i-1]['HA_Close']) / 2
    return ha_df

def analyze_full(ticker, min_p, max_p, is_force=False):
    try:
        tkr = yf.Ticker(ticker)
        df_d = tkr.history(period="6mo", interval="1d")
        df_w = tkr.history(period="2y", interval="1wk")
        if df_d.empty or df_w.empty: return None

        price = df_d.iloc[-1]['Close']
        if not is_force and not (min_p <= price <= max_p): return None

        df_w['MA20'] = df_w['Close'].rolling(20).mean()
        ha_w = calculate_heikin_ashi(df_w); w_l = ha_w.iloc[-1]
        ha_d = calculate_heikin_ashi(df_d); d_l = ha_d.iloc[-1]
        
        is_w_up = w_l['HA_Close'] > w_l['HA_Open']
        is_d_up = d_l['HA_Close'] > d_l['HA_Open']
        rsi_w = ta.rsi(df_w['Close'], length=14).iloc[-1]
        target_p = int(df_w['MA20'].iloc[-1])
        dev_w = (price - target_p) / target_p * 100

        # 反発判定
        is_oversold = rsi_w < 35 or dev_w < -15
        if is_oversold:
            rebound_msg = f"🎯 反発開始 (目標:{target_p})" if is_d_up else f"⚠️ 底打ち模索中 ({target_p})"
            color = "🔥" if is_d_up else "⏳"
        else:
            rebound_msg = "📈 順張り" if is_d_up else "📉 調整"
            color = "🟢" if is_d_up else "⚪"

        score = (50 if is_w_up else -50) + (40 if is_oversold else 0) + (30 if is_d_up else -30)
        if is_w_up == is_d_up: score += 20 if is_w_up else -20
        else: score *= 0.3

        return {
            "銘柄": ticker.replace(".T",""), "社名": TICKER_MAP.get(ticker, "-"),
            "現在値": int(price), "判定": "🔥特級買" if score >= 60 else "📉特級売" if score <= -60 else "☁️様子見",
            "反発シグナル": f"{color} {rebound_msg}", "スコア": int(score), "根拠": f"週:{'陽' if is_w_up else '陰'}, 日:{'陽' if is_d_up else '陰'}"
        }
    except: return None

# --- サイドバー：ウォッチリスト管理 ---
st.sidebar.title("⭐ ウォッチリスト管理")
new_ticker = st.sidebar.text_input("銘柄追加 (例: 9984)", "")
if st.sidebar.button("追加"):
    t_code = f"{new_ticker.strip()}.T" if new_ticker.isdigit() else new_ticker.strip()
    if t_code and t_code not in st.session_state.watchlist:
        st.session_state.watchlist.append(t_code)
        st.sidebar.success(f"{t_code} を追加しました")

if st.sidebar.button("リストをリセット"):
    st.session_state.watchlist = []
    st.sidebar.warning("リストを空にしました")

st.sidebar.write("現在のリスト:", ", ".join([t.replace(".T","") for t in st.session_state.watchlist]))

# --- メイン操作 ---
st.sidebar.title("🎛️ モード切替")
mode = st.sidebar.radio("検索対象を選択", ("⭐ ウォッチリスト (前夜の獲物)", "📊 主要銘柄 (全体)", "📝 自由入力"))

# フィルタ設定
min_p = st.sidebar.number_input("株価下限", 0, 100000, 0)
max_p = st.sidebar.number_input("株価上限", 0, 100000, 100000)

if mode == "⭐ ウォッチリスト (前夜の獲物)":
    ticker_list = st.session_state.watchlist
    is_force = True
elif mode == "📝 自由入力":
    input_area = st.sidebar.text_area("直接入力 (カンマ区切り)", "9984, 6330")
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_area.split(',') if t.strip()]
    is_force = True
else:
    ticker_list = list(TICKER_MAP.keys())
    is_force = False

# --- メイン画面 ---
st.title("🏹 Stock Sniper Strategy Pro")
c1, c2, c3 = st.columns(3)
btn_all = c1.button("📑 リストをスキャン")
btn_buy = c2.button("🚀 おすすめ買い (反発含む)")
btn_short = c3.button("📉 おすすめ空売り")

if btn_all or btn_buy or btn_short:
    results = []
    bar = st.progress(0)
    for i, t in enumerate(ticker_list):
        res = analyze_full(t, min_p, max_p, is_force)
        if res: results.append(res)
        bar.progress((i + 1) / len(ticker_list))
    
    if results:
        df = pd.DataFrame(results).sort_values("スコア", ascending=False)
        if btn_buy: df = df[df['判定'].str.contains("買") | df['反発シグナル'].str.contains("🎯")]
        elif btn_short: df = df[df['判定'].str.contains("売")]
        st.dataframe(df, use_container_width=True)
    else: st.warning("該当なし")
