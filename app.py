import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
import os

# --- 1. アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Pro", page_icon="🦅")

# --- 2. データベース & 保存 ---
SAVE_FILE = "watchlist.txt"
MARKET_DATABASE = {
    "8035.T": "東京エレク", "6920.T": "レーザーテク", "6857.T": "アドバンテ", "6723.T": "ルネサス",
    "6758.T": "ソニーG", "6501.T": "日立", "7735.T": "SCREEN", "6701.T": "NEC",
    "6702.T": "富士通", "6503.T": "三菱電機", "6861.T": "キーエンス", "6954.T": "ファナック",
    "7203.T": "トヨタ", "7267.T": "ホンダ", "7270.T": "SUBARU", "8306.T": "三菱UFJ",
    "9101.T": "日本郵船", "9104.T": "商船三井", "9107.T": "川崎汽船", "9984.T": "SBG",
    "4385.T": "メルカリ", "4755.T": "楽天G", "9983.T": "ファストリ", "6330.T": "東洋エンジ"
}

def load_saved_list():
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "r") as f: return f.read().strip()
    return "9984, 6330"

def save_list(text):
    with open(SAVE_FILE, "w") as f: f.write(text)

# --- 3. 解析エンジン ---
def calculate_heikin_ashi(df):
    ha_df = df.copy()
    ha_df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    ha_df['HA_Open'] = 0.0
    ha_df.iloc[0, ha_df.columns.get_loc('HA_Open')] = (df.iloc[0]['Open'] + df.iloc[0]['Close']) / 2
    for i in range(1, len(df)):
        ha_df.iloc[i, ha_df.columns.get_loc('HA_Open')] = (ha_df.iloc[i-1]['HA_Open'] + ha_df.iloc[i-1]['HA_Close']) / 2
    return ha_df

def analyze_stock(ticker, min_p, max_p, is_force=False):
    try:
        tkr = yf.Ticker(ticker)
        df_d = tkr.history(period="6mo", interval="1d")
        df_w = tkr.history(period="2y", interval="1wk")
        if df_d.empty or df_w.empty: return None

        price = df_d.iloc[-1]['Close']
        if not is_force and not (min_p <= price <= max_p): return None

        # 指標計算
        df_w['MA20'] = df_w['Close'].rolling(20).mean()
        target_p = int(df_w['MA20'].iloc[-1])
        ha_w = calculate_heikin_ashi(df_w); w_l = ha_w.iloc[-1]
        ha_d = calculate_heikin_ashi(df_d); d_l = ha_d.iloc[-1]
        
        is_w_up = w_l['HA_Close'] > w_l['HA_Open']
        is_d_up = d_l['HA_Close'] > d_l['HA_Open']
        rsi_w = ta.rsi(df_w['Close'], length=14).iloc[-1]
        dev_w = (price - target_p) / target_p * 100

        # 底値予測 (-2σ)
        std20 = df_d['Close'].rolling(20).std().iloc[-1]
        ma20 = df_d['Close'].rolling(20).mean().iloc[-1]
        floor = int(ma20 - (std20 * 2))

        # スコアリング
        score = (50 if is_w_up else -50) + (30 if is_d_up else -30)
        is_oversold = rsi_w < 35 or dev_w < -15
        if is_oversold: score += 40

        # 判定ラベルの修正
        if score >= 60: judge = "🔥 特級買"
        elif score >= 20: judge = "✨ 買目線"
        elif score <= -60: judge = "📉 特級売"
        elif score <= -20: judge = "☔ 売目線"
        else: judge = "☁️ 様子見"

        # 反発ステータス
        rebound_msg = "🎯 反発開始" if (is_oversold and is_d_up) else ("⏳ 底打ち模索" if is_oversold else "-")

        return {
            "コード": ticker.replace(".T",""), "現在値": int(price), "判定": judge,
            "スコア": int(score), "週RSI": round(rsi_w, 1), "予想底値": floor,
            "目標(20週)": target_p, "状態": f"週:{'陽' if is_w_up else '陰'} / 日:{'陽' if is_d_up else '陰'}",
            "反発": rebound_msg, "hist": df_d['Close']
        }
    except: return None

# --- 4. 画面構築 ---
st.title("🏹 Stock Sniper Pro")

# 解説プルダウン
with st.expander("📚 判定・用語ガイド（ここをタップで表示）"):
    st.markdown("""
    - **🔥 特級買 / ✨ 買目線**: 週足と日足の方向が一致している、物理的に強い上昇局面。
    - **🎯 反発開始**: 売られすぎ（RSI低）の状態から、日足が陽転した「リバウンド」の初動。
    - **📉 特級売 / ☔ 売目線**: 空売りの好機。週足が陰線で、下げの力が強い状態。
    - **🛡️ 予想底値**: ボリンジャーバンド-2σ付近。統計的に反発しやすい「指値」の目安。
    """)

# サイドバー
st.sidebar.title("💰 検索・保存")
mode = st.sidebar.radio("検索対象", ["📊 市場全体", "⭐ 保存リスト", "📝 自由入力"])

if mode == "📊 市場全体":
    ticker_list = list(MARKET_DATABASE.keys()); is_force = False
elif mode == "⭐ 保存リスト":
    saved_text = load_saved_list()
    input_area = st.sidebar.text_area("編集", saved_text, height=150)
    if st.sidebar.button("💾 保存"): save_list(input_area)
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_area.split(',') if t.strip()]
    is_force = True
else:
    input_area = st.sidebar.text_area("コード入力", "9984, 6330", height=100)
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_area.split(',') if t.strip()]
    is_force = True

min_p = st.sidebar.number_input("下限", 0, 100000, 1000)
max_p = st.sidebar.number_input("上限", 0, 100000, 50000)

# メインボタン
c1, c2, c3 = st.columns(3)
btn_all = c1.button("📑 全件スキャン")
btn_buy = c2.button("🚀 買い・反発狙い")
btn_short = c3.button("📉 空売り狙い")

if btn_all or btn_buy or btn_short:
    results = []
    bar = st.progress(0)
    for i, t in enumerate(ticker_list):
        res = analyze_stock(t, min_p, max_p, is_force)
        if res: results.append(res)
        bar.progress((i + 1) / len(ticker_list))
    
    if results:
        df = pd.DataFrame(results).sort_values("スコア", ascending=False)
        # フィルタロジックの修正
        if btn_buy: df = df[df['スコア'] >= 20]
        elif btn_short: df = df[df['スコア'] <= -20]

        for _, row in df.iterrows():
            with st.expander(f"{row['判定']} | {row['コード']} - {row['現在値']}円 {row['反発'] if row['反発'] != '-' else ''}"):
                col_info, col_chart = st.columns([1, 1])
                with col_info:
                    st.write(f"**スコア:** {row['スコア']}点 | **週RSI:** {row['週RSI']}")
                    st.write(f"**指値目安:** {row['予想底値']}円")
                    st.write(f"**目標(20週):** {row['目標(20週)']}円")
                    st.write(f"**状態:** {row['状態']}")
                with col_chart:
                    st.line_chart(row['hist'], height=150) # 高速チャート
        
        st.divider()
        st.dataframe(df.drop(columns=['hist', '反発']), use_container_width=True)
    else: st.warning("該当なし。市場環境を確認してください。")
