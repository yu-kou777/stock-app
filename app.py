import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
import numpy as np

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Technical Pro")

# --- 銘柄データベース ---
TICKER_MAP = {
    "9984.T": "SBG", "6330.T": "東洋エンジ", "7270.T": "SUBARU", 
    "6971.T": "京セラ", "9101.T": "日本郵船", "8306.T": "三菱UFJ",
    "8035.T": "東京エレク", "6920.T": "レーザーテク", "7203.T": "トヨタ"
}

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
        if not is_manual and not (min_p <= price <= max_p): return None

        # 1. 指標計算
        df_w['MA20'] = df_w['Close'].rolling(20).mean()
        ha_w = calculate_heikin_ashi(df_w); w_l = ha_w.iloc[-1]
        ha_d = calculate_heikin_ashi(df_d); d_l = ha_d.iloc[-1]
        
        is_w_up = w_l['HA_Close'] > w_l['HA_Open']
        is_d_up = d_l['HA_Close'] > d_l['HA_Open']
        rsi_w = ta.rsi(df_w['Close'], length=14).iloc[-1]
        target_p = int(df_w['MA20'].iloc[-1])
        dev_w = (price - target_p) / target_p * 100

        # 2. 反発シグナルの断定ロジック
        # 週足で売られすぎ(RSI<35 または 乖離<-15%)
        is_oversold = rsi_w < 35 or dev_w < -15
        
        if is_oversold:
            if is_d_up:
                rebound_msg = f"🎯 反発開始 (目標:{target_p}円)"
                rebound_color = "🔥"
            else:
                rebound_msg = f"⚠️ 底打ち模索中 (目安:{target_p}円)"
                rebound_color = "⏳"
        else:
            rebound_msg = "📈 順張り巡航中" if is_d_up else "📉 調整局面"
            rebound_color = "☁️"

        # 3. スコアリング
        score = 0; reasons = []
        score += 50 if is_w_up else -50
        reasons.append("週足:上昇" if is_w_up else "週足:下落")
        
        if is_oversold:
            score += 40 # 逆張り期待値
            reasons.append(f"週足乖離:{dev_w:.1f}%")
        
        score += 30 if is_d_up else -30
        reasons.append("日足:陽線" if is_d_up else "日足:陰線")

        if is_w_up == is_d_up: score += 20 if is_w_up else -20
        else: score *= 0.3 # 不一致時は慎重に

        # 4. 判定
        if score >= 60: judge = "🔥 特級買"
        elif score >= 20: judge = "✨ 買目線"
        elif score <= -60: judge = "📉 特級売"
        elif score <= -20: judge = "☔ 売目線"
        else: judge = "☁️ 様子見"

        return {
            "銘柄": ticker.replace(".T",""), "社名": TICKER_MAP.get(ticker, "-"),
            "現在値": int(price), "判定": judge, "反発シグナル": f"{rebound_color} {rebound_msg}",
            "スコア": int(score), "根拠": ", ".join(reasons)
        }
    except: return None

# --- UI構築 ---
st.sidebar.title("🎛️ 戦略司令室")
search_source = st.sidebar.radio("モード切替", ("📊 主要銘柄", "📝 自由入力"))
min_p = st.sidebar.number_input("株価下限", 0, 100000, 0)
max_p = st.sidebar.number_input("株価上限", 0, 100000, 100000)

if search_source == "📝 自由入力":
    input_tkrs = st.sidebar.text_area("銘柄コード(例: 9984, 6330)", "9984, 6330")
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_tkrs.split(',') if t.strip()]
    is_manual = True
else:
    ticker_list = list(TICKER_MAP.keys())
    is_manual = False

st.title("🏹 Stock Sniper Technical Pro")
c1, c2, c3 = st.columns(3)
btn_all = c1.button("📑 全件スキャン")
btn_buy = c2.button("🚀 おすすめ買い (反発含む)")
btn_short = c3.button("📉 おすすめ空売り")

if btn_all or btn_buy or btn_short:
    results = []
    bar = st.progress(0)
    for i, t in enumerate(ticker_list):
        res = analyze_full(t, min_p, max_p, is_manual)
        if res: results.append(res)
        bar.progress((i + 1) / len(ticker_list))
    
    if results:
        df = pd.DataFrame(results)
        if btn_buy:
            df = df[df['判定'].str.contains("買") | df['反発シグナル'].str.contains("🎯")]
        elif btn_short:
            df = df[df['判定'].str.contains("売")]
        
        df = df.sort_values("スコア", ascending=False)
        st.dataframe(df, use_container_width=True)
