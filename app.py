import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
import plotly.graph_objects as go
import os

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Pro", page_icon="🦅")

# --- 2. データベース & JPX全銘柄名簿の自動取得 ---
SAVE_FILE = "watchlist.txt"

@st.cache_data(ttl=86400) # 1日キャッシュして高速化
def get_jpx_master():
    url = "https://www.jpx.co.jp/markets/statistics-fra/data/files/p_stock_data.xlsx"
    try:
        df = pd.read_excel(url)
        prime = df[df['市場・商品区分'].str.contains('プライム', na=False)]['コード'].astype(str).tolist()
        standard = df[df['市場・商品区分'].str.contains('スタンダード', na=False)]['コード'].astype(str).tolist()
        names = dict(zip(df['コード'].astype(str), df['銘柄名']))
        return {"prime": prime, "standard": standard, "names": names}
    except:
        return {"prime": [], "standard": [], "names": {}}

jpx = get_jpx_master()

# RCI（順位相関指数）の計算関数
def calculate_rci(series, period=9):
    def rci_logic(s):
        n = len(s)
        time_ranks = list(range(n, 0, -1))
        price_ranks = pd.Series(s).rank(ascending=False).tolist()
        sum_d2 = sum((tr - pr) ** 2 for tr, pr in zip(time_ranks, price_ranks))
        return (1 - (6 * sum_d2) / (n * (n**2 - 1))) * 100
    return series.rolling(window=period).apply(rci_logic)

# --- 3. 解析エンジン ---
def analyze_stock(ticker, min_p, max_p, rsi_range, rci_range, is_force=False):
    try:
        tkr = yf.Ticker(ticker)
        df = tkr.history(period="6mo", interval="1d")
        if df.empty or len(df) < 60: return None
        
        price = df.iloc[-1]['Close']
        if not is_force and not (min_p <= price <= max_p): return None

        # テクニカル指標の計算
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        df['RSI'] = ta.rsi(df['Close'], length=14)
        df['RCI'] = calculate_rci(df['Close'], period=9) # 9日RCI
        
        curr_rsi = df['RSI'].iloc[-1]
        curr_rci = df['RCI'].iloc[-1]

        # RSIとRCIの範囲チェック
        if not (rsi_range[0] <= curr_rsi <= rsi_range[1]): return None
        if not (rci_range[0] <= curr_rci <= rci_range[1]): return None

        # スコアリング
        low_60 = df['Low'].tail(60).min()
        std20 = df['Close'].rolling(20).std().iloc[-1]
        score = 0
        if curr_rsi < 30: score += 30
        if curr_rci < -80: score += 30
        if price <= low_60 * 1.015: score += 20
        
        p_floor = int((df['MA20'].iloc[-1] - (std20 * 2) + low_60) / 2)
        judge = "🚀 超精密買" if score >= 50 else "✨ 買目線" if score >= 20 else "☁️ 様子見"

        code_only = ticker.replace(".T","")
        return {
            "コード": code_only, "和名": jpx["names"].get(code_only, "不明"),
            "現在値": int(price), "判定": judge, "スコア": int(score), 
            "RSI": round(curr_rsi, 1), "RCI": round(curr_rci, 1),
            "指値": p_floor, "df": df
        }
    except: return None

# --- 4. 画面構築 ---
st.title("🏹 Stock Sniper Pro: RSI & RCI Edition")

# サイドバー設定
st.sidebar.title("💰 検索・フィルタ")
mode = st.sidebar.radio("対象市場", ["📊 プライム", "🏛️ スタンダード", "⭐ 保存リスト"])
min_p = st.sidebar.number_input("株価下限", 0, 100000, 500)
max_p = st.sidebar.number_input("株価上限", 0, 100000, 5000)

st.sidebar.subheader("📈 指標フィルタ")
rsi_range = st.sidebar.slider("RSI範囲", 0, 100, (0, 40)) # デフォルトで売られすぎ狙い
rci_range = st.sidebar.slider("RCI範囲", -100, 100, (-100, -50))

# 実行ボタン
if st.button("🛰️ 全力スキャン開始"):
    targets = [f"{c}.T" for c in (jpx["prime"] if mode=="📊 プライム" else jpx["standard"])]
    results = []
    bar = st.progress(0)
    MAX_DISPLAY = 50 # サーバー負荷対策
    
    for i, t in enumerate(targets):
        res = analyze_stock(t, min_p, max_p, rsi_range, rci_range)
        if res:
            results.append(res)
            if len(results) >= MAX_DISPLAY:
                st.warning(f"⚠️ ヒット数が多いため、上位{MAX_DISPLAY}件で停止しました。")
                break
        bar.progress((i + 1) / len(targets))

    if results:
        df_res = pd.DataFrame(results).sort_values("スコア", ascending=False)
        st.success(f"🎯 条件に合致する銘柄が {len(results)} 件見つかりました。")
        
        for _, row in df_res.iterrows():
            with st.expander(f"{row['判定']} | {row['和名']} ({row['コード']}) RSI:{row['RSI']} / RCI:{row['RCI']}"):
                fig = go.Figure(data=[go.Candlestick(x=row['df'].index, open=row['df']['Open'], high=row['df']['High'], low=row['df']['Low'], close=row['df']['Close'])])
                fig.add_hline(y=row['指値'], line_dash="dash", line_color="royalblue", annotation_text="指値")
                fig.update_layout(height=400, margin=dict(l=0, r=0, b=0, t=0), xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
                st.write(f"現在値: {row['現在値']}円 / **指値目安: {row['指値']}円**")
    else:
        st.info("条件に合う銘柄は見つかりませんでした。フィルタを広げてください。")
