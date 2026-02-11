import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# ⚙️ 設定エリア
# ==========================================

# 監視対象：日経225主要銘柄（動作軽量化のため選抜）
TICKERS = [
    "7203.T", "9984.T", "8306.T", "6758.T", "6861.T", "6920.T", "6098.T", "8035.T",
    "4063.T", "7974.T", "9432.T", "8058.T", "7267.T", "4502.T", "6501.T", "7741.T",
    "6367.T", "6902.T", "4543.T", "3382.T", "4519.T", "6273.T", "6954.T", "7269.T",
    "9101.T", "9104.T", "9107.T", "5401.T", "8316.T", "8411.T", "8766.T", "8801.T",
    "1605.T", "1925.T", "2413.T", "2502.T", "2801.T", "2914.T", "3407.T", "4503.T",
    "4507.T", "4523.T", "4568.T", "4578.T", "4661.T", "4901.T", "4911.T", "5020.T",
    "5108.T", "5713.T", "6146.T", "6301.T", "6326.T", "6503.T", "6594.T", "6702.T",
    "6723.T", "6752.T", "6762.T", "6857.T", "6971.T", "6981.T", "7011.T", "7201.T",
    "7270.T", "7272.T", "7733.T", "7751.T", "7832.T", "8001.T", "8002.T", "8015.T",
    "8031.T", "8053.T", "8604.T", "8630.T", "8725.T", "8750.T", "8802.T", "8830.T",
    "9020.T", "9021.T", "9022.T", "9202.T", "9735.T", "9843.T", "9983.T"
]

# ==========================================
# 🧠 高度テクニカル分析ロジック
# ==========================================

def get_advanced_analysis(ticker):
    try:
        stock = yf.Ticker(ticker)
        # 過去6ヶ月分のデータ取得
        df = stock.history(period="6mo")
        if len(df) < 60: return None

        close = df['Close']
        high = df['High']
        low = df['Low']
        
        # --- 1. RSI (14日) とその傾き ---
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        
        # RSIの傾き（現在値 - 3日前）: 上向いているかチェック
        rsi_slope = rsi.iloc[-1] - rsi.iloc[-4]

        # --- 2. MACD ヒストグラム（予兆検知） ---
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        
        # ヒストグラム（MACDとシグナルの距離）
        histogram = macd_line - signal_line
        
        # ヒストグラムの変化率（縮小しているか？）
        hist_now = histogram.iloc[-1]
        hist_prev = histogram.iloc[-2]
        hist_change = hist_now - hist_prev  # プラスなら好転の兆し

        # --- 3. 抵抗線・支持線の計算（直近20日の高値・安値） ---
        resistance = high.rolling(20).max().iloc[-1] # 直近の高値（売り目標）
        support = low.rolling(20).min().iloc[-1]     # 直近の安値（損切りライン）
        
        curr_price = close.iloc[-1]

        # 判定結果をまとめる
        return {
            "code": ticker,
            "price": curr_price,
            "rsi": rsi.iloc[-1],
            "rsi_slope": rsi_slope,
            "hist_now": hist_now,
            "hist_change": hist_change,
            "resistance": resistance,
            "support": support,
            "upside": resistance - curr_price # 上値余地
        }
    except:
        return None

def run_prediction_scan(min_p, max_p):
    buy_candidates = []
    sell_candidates = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(get_advanced_analysis, TICKERS))
    
    for d in results:
        if d is None: continue
        if not (min_p <= d["price"] <= max_p): continue
        
        # --- 買いの予兆判定 (Pre-Bullish) ---
        # 1. MACDはまだマイナス圏だが、ヒストグラムが増加中（赤色が薄くなってきた状態）
        # 2. RSIが低い位置(45以下)から上向き(slope > 0)に転じている
        if (d["hist_now"] < 0 and d["hist_change"] > 0) and (d["rsi"] < 45 and d["rsi_slope"] > 0):
            d["signal_type"] = "買い予兆"
            d["comment"] = "反発開始の気配あり"
            buy_candidates.append(d)

        # --- 売りの予兆判定 (Pre-Bearish) ---
        # 1. MACDはプラス圏だが、ヒストグラムが減少中（上昇力が弱まってきた）
        # 2. RSIが高い位置(60以上)から下向きに転じている
        elif (d["hist_now"] > 0 and d["hist_change"] < 0) and (d["rsi"] > 60 and d["rsi_slope"] < 0):
            d["signal_type"] = "売り予兆"
            d["comment"] = "天井打ちの気配あり"
            sell_candidates.append(d)

    return buy_candidates, sell_candidates

# ==========================================
# 📱 アプリ画面設計
# ==========================================

st.set_page_config(page_title="先読みAIチャート", layout="wide")
st.title("🦅 先読みAIチャート (Early Entry)")
st.caption("MACDクロス前の「予兆」と「抵抗線」を可視化")

# 設定エリア
col1, col2 = st.columns([1, 2])
with col1:
    st.write("##### 💰 価格帯設定")
    p_min = st.number_input("下限 (円)", value=1000, step=100)
    p_max = st.number_input("上限 (円)", value=10000, step=100)
with col2:
    st.write("##### 📊 分析概要")
    st.info("クロスが発生してからでは遅いため、RSIの反転とMACDの幅(ヒストグラム)の縮小を検知して、トレンドの初動を狙います。")

if st.button("🚀 先読みスキャン開始", use_container_width=True):
    with st.spinner('全銘柄の「気配」を分析中...'):
        buys, sells = run_prediction_scan(p_min, p_max)

    # --- 買いチャンス表示 ---
    st.subheader(f"📈 買いの予兆あり ({len(buys)}件)")
    if buys:
        # 表示用データフレーム作成
        df_b = pd.DataFrame(buys)
        # 見やすいように列を選んでリネーム
        display_b = df_b[["code", "price", "rsi", "resistance", "support", "comment"]]
        display_b.columns = ["銘柄", "現在値", "RSI", "売却目標(抵抗線)", "損切目安(支持線)", "AIコメント"]
        st.dataframe(display_b, use_container_width=True)
    else:
        st.write("現在、明確な買い予兆は見つかりません。")

    # --- 売りチャンス表示 ---
    st.subheader(f"📉 空売りの予兆あり ({len(sells)}件)")
    if sells:
        df_s = pd.DataFrame(sells)
        display_s = df_s[["code", "price", "rsi", "support", "resistance", "comment"]]
        display_s.columns = ["銘柄", "現在値", "RSI", "買戻目安(支持線)", "上値抵抗線", "AIコメント"]
        st.dataframe(display_s, use_container_width=True)
    else:
        st.write("現在、明確な売り予兆は見つかりません。")

    st.write("---")
    st.caption("※抵抗線：直近20日間の最高値（ここまでは上がる余地があるが、ここを超えると重い）")
    st.caption("※支持線：直近20日間の最安値（ここを割ると危険なため損切りの目安になる）")
