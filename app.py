import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
from datetime import datetime
from urllib.parse import urljoin
import numpy as np

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Pro")

# --- 銘柄リスト ---
TICKER_MAP = {
    "8035.T": "東京エレク", "6920.T": "レーザーテク", "6857.T": "アドバンテ", "6723.T": "ルネサス",
    "6758.T": "ソニーG", "6501.T": "日立", "7735.T": "SCREEN", "6701.T": "NEC",
    "6702.T": "富士通", "6503.T": "三菱電機", "6861.T": "キーエンス", "6954.T": "ファナック",
    "6981.T": "村田製", "6971.T": "京セラ", "6902.T": "デンソー", "4063.T": "信越化",
    "7203.T": "トヨタ", "7267.T": "ホンダ", "7270.T": "SUBARU", "7201.T": "日産自",
    "6301.T": "コマツ", "6367.T": "ダイキン", "7011.T": "三菱重工", "7012.T": "川崎重工",
    "7013.T": "IHI", "8306.T": "三菱UFJ", "8316.T": "三井住友", "8411.T": "みずほ", 
    "8604.T": "野村HD", "8766.T": "東京海上", "8031.T": "三井物産", "8058.T": "三菱商事",
    "9101.T": "日本郵船", "9104.T": "商船三井", "9107.T": "川崎汽船", "5401.T": "日本製鉄",
    "5411.T": "JFE", "5406.T": "神戸鋼", "9984.T": "SBG", "9432.T": "NTT", 
    "6098.T": "リクルート", "4385.T": "メルカリ", "4755.T": "楽天G", "9983.T": "ファストリ", 
    "1605.T": "INPEX", "5020.T": "ENEOS", "6330.T": "東洋エンジ"
}

# --- 平均足・判定関数 ---
def calculate_heikin_ashi(df):
    ha_df = df.copy()
    ha_df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    ha_df['HA_Open'] = 0.0
    ha_df.iloc[0, ha_df.columns.get_loc('HA_Open')] = (df.iloc[0]['Open'] + df.iloc[0]['Close']) / 2
    for i in range(1, len(df)):
        ha_df.iloc[i, ha_df.columns.get_loc('HA_Open')] = (ha_df.iloc[i-1]['HA_Open'] + ha_df.iloc[i-1]['HA_Close']) / 2
    return ha_df

def analyze_full(ticker, min_p, max_p, is_manual=False):
    try:
        tkr = yf.Ticker(ticker)
        df_d = tkr.history(period="6mo", interval="1d")
        df_w = tkr.history(period="2y", interval="1wk")
        if df_d.empty or df_w.empty: return None

        price = df_d.iloc[-1]['Close']
        # ★自由入力(is_manual=True)なら価格フィルタを無視する
        if not is_manual:
            if not (min_p <= price <= max_p): return None

        ha_w = calculate_heikin_ashi(df_w); w_l = ha_w.iloc[-1]
        ha_d = calculate_heikin_ashi(df_d); d_l = ha_d.iloc[-1]
        is_w_up = w_l['HA_Close'] > w_l['HA_Open']
        is_d_up = d_l['HA_Close'] > d_l['HA_Open']

        score = 0; reasons = []
        # MTFロジック
        if is_w_up: score += 50; reasons.append("🌊週足:上昇")
        else: score -= 50; reasons.append("🌊週足:下落")
        if is_d_up: score += 30; reasons.append("📈日足:陽線")
        else: score -= 30; reasons.append("📉日足:陰線")

        if is_w_up == is_d_up:
            score += 20 if is_w_up else -20
            reasons.append("⚡共鳴" if is_w_up else "💀共鳴(弱)")
        else:
            score *= 0.3
            reasons.append("⚠️不一致")

        if score >= 60: judge = "🔥 特級買"
        elif score >= 20: judge = "✨ 買目線"
        elif score <= -60: judge = "📉 特級売"
        elif score <= -20: judge = "☔ 売目線"
        else: judge = "☁️ 様子見"

        return {"銘柄": ticker.replace(".T",""), "社名": TICKER_MAP.get(ticker, "-"), "現在値": int(price), "判定": judge, "スコア": int(score), "根拠": ", ".join(reasons)}
    except: return None

# --- サイドバー ---
st.sidebar.title("🎛️ 戦略司令室")
search_source = st.sidebar.radio("モード切替", ("📊 主要銘柄", "📝 自由入力"))
min_p = st.sidebar.number_input("株価下限", 0, 100000, 0)
max_p = st.sidebar.number_input("株価上限", 0, 100000, 100000)

if search_source == "📝 自由入力":
    input_tkrs = st.sidebar.text_area("銘柄コード(例: 9984, 7270)", "9984, 7270")
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_tkrs.split(',') if t.strip()]
    is_manual_mode = True
else:
    ticker_list = list(TICKER_MAP.keys())
    is_manual_mode = False

# --- メイン画面 ---
st.title("🏹 Stock Sniper Technical Pro")

col1, col2, col3 = st.columns(3)
btn_all = col1.button("📑 全スキャン")
btn_buy = col2.button("🚀 おすすめ買い銘柄")
btn_short = col3.button("📉 おすすめ空売り銘柄")

if btn_all or btn_buy or btn_short:
    results = []
    bar = st.progress(0)
    for i, t in enumerate(ticker_list):
        res = analyze_full(t, min_p, max_p, is_manual=is_manual_mode)
        if res: results.append(res)
        bar.progress((i + 1) / len(ticker_list))
    
    if results:
        df = pd.DataFrame(results)
        # ワンボタン絞り込み機能
        if btn_buy:
            df = df[df['判定'].str.contains("買")]
            st.subheader("🔥 今、物理的に優位な「買い」銘柄")
        elif btn_short:
            df = df[df['判定'].str.contains("売")]
            st.subheader("📉 今、重力に抗えない「空売り」銘柄")
        
        df = df.sort_values("スコア", ascending=False)
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("該当銘柄なし")
