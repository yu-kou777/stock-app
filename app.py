import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
import plotly.graph_objects as go # ロウソク足用
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
def analyze_stock(ticker, min_p, max_p, is_force=False):
    try:
        tkr = yf.Ticker(ticker)
        df_d = tkr.history(period="6mo", interval="1d")
        df_w = tkr.history(period="2y", interval="1wk")
        if df_d.empty or df_w.empty: return None

        price = df_d.iloc[-1]['Close']
        if not is_force and not (min_p <= price <= max_p): return None

        # テクニカル指標計算
        df_d['MA60'] = df_d['Close'].rolling(60).mean()
        df_w['MA20'] = df_w['Close'].rolling(20).mean()
        target_p = int(df_w['MA20'].iloc[-1])
        
        rsi_w = ta.rsi(df_w['Close'], length=14).iloc[-1]
        dev_w = (price - target_p) / target_p * 100

        # 底値予測 (-2σ)
        std20 = df_d['Close'].rolling(20).std().iloc[-1]
        ma20 = df_d['Close'].rolling(20).mean().iloc[-1]
        floor = int(ma20 - (std20 * 2))

        # スコアリング（簡易化）
        is_w_up = df_w['Close'].iloc[-1] > df_w['Open'].iloc[-1]
        is_d_up = df_d['Close'].iloc[-1] > df_d['Open'].iloc[-1]
        score = (50 if is_w_up else -50) + (30 if is_d_up else -30)
        is_oversold = rsi_w < 35 or dev_w < -15
        if is_oversold: score += 40

        if score >= 60: judge = "🔥 特級買"
        elif score >= 20: judge = "✨ 買目線"
        elif score <= -60: judge = "📉 特級売"
        elif score <= -20: judge = "☔ 売目線"
        else: judge = "☁️ 様子見"

        return {
            "コード": ticker.replace(".T",""), "現在値": int(price), "判定": judge,
            "スコア": int(score), "週RSI": round(rsi_w, 1), "予想底値": floor,
            "目標(20週)": target_p, "df": df_d, "反発": "🎯 反発開始" if (is_oversold and is_d_up) else "-"
        }
    except: return None

# --- 4. 画面構築 ---
st.title("🏹 Stock Sniper Pro")

with st.expander("📚 判定ガイド"):
    st.markdown("- **60日線（オレンジ）**: トレンドの要。\n- **青点線（予想底値）**: 反発期待の指値ポイント。\n- **赤点線（目標）**: 週足移動平均線。")

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
max_p = st.sidebar.number_input("上限", 0, 100000, 100000)

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
        df_res = pd.DataFrame(results).sort_values("スコア", ascending=False)
        if btn_buy: df_res = df_res[df_res['スコア'] >= 20]
        elif btn_short: df_res = df_res[df_res['スコア'] <= -20]

        for _, row in df_res.iterrows():
            with st.expander(f"{row['判定']} | {row['コード']} - {row['現在値']}円 {row['反発'] if row['反発']!='-' else ''}"):
                # --- Plotly ロウソク足描画 ---
                fig = go.Figure()
                # ロウソク足
                fig.add_trace(go.Candlestick(x=row['df'].index, open=row['df']['Open'], high=row['df']['High'], low=row['df']['Low'], close=row['df']['Close'], name='価格'))
                # 60日線
                fig.add_trace(go.Scatter(x=row['df'].index, y=row['df']['MA60'], line=dict(color='orange', width=1.5), name='60MA'))
                # 予想底値（水平線）
                fig.add_hline(y=row['予想底値'], line_dash="dash", line_color="royalblue", annotation_text="予想底値")
                # 利確目標（水平線）
                fig.add_hline(y=row['目標(20週)'], line_dash="dash", line_color="crimson", annotation_text="利確目標")
                
                fig.update_layout(height=400, margin=dict(l=0, r=0, b=0, t=0), showlegend=False, xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
                
                st.write(f"スコア: {row['スコア']}点 | RSI: {row['週RSI']} | 指値目安: {row['予想底値']}円")
        
        st.divider()
        st.dataframe(df_res.drop(columns=['df', '反発']), use_container_width=True)
    else: st.warning("該当なし")
