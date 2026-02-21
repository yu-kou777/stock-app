import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
import numpy as np

# --- 銘柄データベース（東洋エンジ 6330.T を追加） ---
TICKER_MAP = {
    "9984.T": "SBG", "6330.T": "東洋エンジ", "7270.T": "SUBARU", 
    "6971.T": "京セラ", "8035.T": "東京エレク", "6920.T": "レーザーテク",
    "7203.T": "トヨタ", "8306.T": "三菱UFJ", "9101.T": "日本郵船"
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

        # 1. 週足トレンドと乖離率の計算
        df_w['MA20'] = df_w['Close'].rolling(20).mean()
        ha_w = calculate_heikin_ashi(df_w); w_l = ha_w.iloc[-1]
        is_w_up = w_l['HA_Close'] > w_l['HA_Open']
        
        # 2. RSI（過熱感）
        rsi_w = ta.rsi(df_w['Close'], length=14).iloc[-1]
        
        # 3. 反発ターゲット（20週線の価格を磁力ターゲットとする）
        target_price = df_w['MA20'].iloc[-1]
        deviation_w = (price - target_price) / target_price * 100

        score = 0; reasons = []
        rebound_signal = "⚡ 観測中"
        
        # MTF基本ロジック
        if is_w_up: score += 50; reasons.append("🌊週足:上昇")
        else: score -= 50; reasons.append("🌊週足:下落")
            
        # ★ 自律反発（リバウンド）検知ロジック
        if rsi_w < 30 or deviation_w < -15:
            rebound_signal = f"🎯 自律反発期待値：高 ({int(target_price)}円目標)"
            score += 40 # 逆張りの買い要素
            reasons.append(f"📉 週足乖離: {deviation_w:.1f}%")
        
        # 日足トレンド
        ha_d = calculate_heikin_ashi(df_d); d_l = ha_d.iloc[-1]
        is_d_up = d_l['HA_Close'] > d_l['HA_Open']
        score += 30 if is_d_up else -30

        # 同期判定
        if is_w_up == is_d_up:
            score += 20 if is_w_up else -20
        else:
            score *= 0.3
            reasons.append("⚠️ 不一致(調整中)")

        if score >= 60: judge = "🔥 特級買"
        elif score >= 20: judge = "✨ 買目線"
        elif score <= -60: judge = "📉 特級売"
        elif score <= -20: judge = "☔ 売目線"
        else: judge = "☁️ 様子見"

        return {
            "銘柄": ticker.replace(".T",""), "社名": TICKER_MAP.get(ticker, "-"),
            "現在値": int(price), "判定": judge, "反発シグナル": rebound_signal,
            "スコア": int(score), "根拠": ", ".join(reasons)
        }
    except: return None

# --- UI (サイドバー・メインは前回同様) ---
st.sidebar.title("🎛️ 戦略司令室")
search_source = st.sidebar.radio("モード切替", ("📊 主要銘柄", "📝 自由入力"))
min_p = st.sidebar.number_input("株価下限", 0, 100000, 0)
max_p = st.sidebar.number_input("株価上限", 0, 100000, 100000)

if search_source == "📝 自由入力":
    input_tkrs = st.sidebar.text_area("銘柄コード(例: 9984, 6330)", "9984, 6330")
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_tkrs.split(',') if t.strip()]
    is_manual_mode = True
else:
    ticker_list = list(TICKER_MAP.keys())
    is_manual_mode = False

st.title("🏹 Stock Sniper Technical Pro")
if st.button("📑 解析実行"):
    results = [analyze_full(t, min_p, max_p, is_manual_mode) for t in ticker_list]
    results = [r for r in results if r]
    if results:
        df = pd.DataFrame(results).sort_values("スコア", ascending=False)
        st.dataframe(df, use_container_width=True)
