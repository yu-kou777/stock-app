import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
from datetime import datetime
import numpy as np

# --- 銘柄データベース（主要銘柄を網羅） ---
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

# --- 平均足計算 ---
def calculate_heikin_ashi(df):
    ha_df = df.copy()
    ha_df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    ha_df['HA_Open'] = 0.0
    ha_df.iloc[0, ha_df.columns.get_loc('HA_Open')] = (df.iloc[0]['Open'] + df.iloc[0]['Close']) / 2
    for i in range(1, len(df)):
        ha_df.iloc[i, ha_df.columns.get_loc('HA_Open')] = (ha_df.iloc[i-1]['HA_Open'] + ha_df.iloc[i-1]['HA_Close']) / 2
    ha_df['HA_High'] = ha_df[['High', 'HA_Open', 'HA_Close']].max(axis=1)
    ha_df['HA_Low'] = ha_df[['Low', 'HA_Open', 'HA_Close']].min(axis=1)
    return ha_df

# --- 酒田五法判定 ---
def check_sakata_gohou(df):
    if len(df) < 5: return "-", 0
    signals = []; score = 0
    c = df['Close'].values; o = df['Open'].values
    if c[-1]>o[-1] and c[-2]>o[-2] and c[-3]>o[-3] and c[-1]>c[-2]>c[-3]:
        signals.append("🔥赤三兵"); score += 40
    if c[-1]<o[-1] and c[-2]<o[-2] and c[-3]<o[-3] and c[-1]<c[-2]<c[-3]:
        signals.append("⚠️黒三兵"); score -= 40
    return " / ".join(signals) if signals else "なし", score

# --- メイン解析エンジン ---
def analyze_stock(ticker):
    try:
        tkr = yf.Ticker(ticker)
        # 1. データ取得（日足と週足）
        df_d = tkr.history(period="6mo", interval="1d")
        df_w = tkr.history(period="2y", interval="1wk")
        if df_d.empty or df_w.empty: return None

        # 2. 週足トレンド（潮流）の判定
        ha_w = calculate_heikin_ashi(df_w)
        w_last = ha_w.iloc[-1]
        is_w_up = w_last['HA_Close'] > w_last['HA_Open']
        rsi_w = ta.rsi(df_w['Close'], length=14).iloc[-1]

        # 3. 日足トレンド（波）の判定
        ha_d = calculate_heikin_ashi(df_d)
        d_last = ha_d.iloc[-1]
        is_d_up = d_last['HA_Close'] > d_last['HA_Open']
        
        # 4. スコア計算
        score = 0; reasons = []
        
        # 週足の重み付け（MTF共鳴）
        if is_w_up: score += 50; reasons.append("🌊週足:上昇潮流")
        else: score -= 50; reasons.append("🌊週足:下落潮流")
            
        if is_d_up: score += 30; reasons.append("📈日足:陽線")
        else: score -= 30; reasons.append("📉日足:陰線")

        # 方向一致のボーナス
        if is_w_up == is_d_up:
            score += (20 if is_w_up else -20)
            reasons.append("⚡MTF共鳴(強気)" if is_w_up else "💀MTF共鳴(弱気)")
        else:
            score *= 0.5 # 不一致なら信頼度を半分にする
            reasons.append("⚠️トレンド不一致")

        # 酒田五法（日足）
        sakata_msg, sakata_score = check_sakata_gohou(df_d)
        score += sakata_score
        if sakata_msg != "なし": reasons.append(sakata_msg)

        # 最終判定
        if score >= 60: judge = "🔥 特級買"
        elif score >= 30: judge = "✨ 買目線"
        elif score <= -60: judge = "📉 特級売"
        elif score <= -30: judge = "☔ 売目線"
        else: judge = "☁️ 様子見"

        return {
            "銘柄": ticker.replace(".T",""), "社名": TICKER_MAP.get(ticker, "-"),
            "現在値": int(df_d.iloc[-1]['Close']), "判定": judge,
            "潮流(週)": "陽線" if is_w_up else "陰線", "週RSI": f"{rsi_w:.1f}",
            "根拠": ", ".join(reasons), "スコア": int(score)
        }
    except: return None

# --- Streamlit表示 ---
st.title("🚀 株スキャナー MTF Pro")
if st.button('スキャン開始'):
    results = [analyze_stock(t) for t in TICKER_MAP.keys()]
    results = [r for r in results if r]
    if results:
        df_res = pd.DataFrame(results).sort_values(by="スコア", ascending=False)
        st.dataframe(df_res, use_container_width=True)
    else:
        st.warning("データが取得できませんでした。")
