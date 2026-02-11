import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# ⚙️ 設定エリア
# ==========================================

# 監視対象：日経225銘柄（代表的なものを抜粋）
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
# 🧠 テクニカル分析ロジック
# ==========================================

def get_stock_analysis(ticker):
    try:
        stock = yf.Ticker(ticker)
        # 日足データを取得（MACD計算のため期間を長めに設定）
        df = stock.history(period="1y")
        if len(df) < 50: return None

        close = df['Close']
        
        # --- RSI (14日) ---
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))

        # --- MACD (12, 26, 9) ---
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        
        # 直近の指標
        curr_price = close.iloc[-1]
        curr_rsi = rsi.iloc[-1]
        curr_macd = macd_line.iloc[-1]
        curr_signal = signal_line.iloc[-1]
        prev_macd = macd_line.iloc[-2]
        prev_signal = signal_line.iloc[-2]

        # 判定用フラグ
        is_golden_cross = (prev_macd < prev_signal) and (curr_macd > curr_signal)
        is_dead_cross = (prev_macd > prev_signal) and (curr_macd < curr_signal)

        return {
            "code": ticker,
            "price": curr_price,
            "rsi": curr_rsi,
            "macd_gc": is_golden_cross,
            "macd_dc": is_dead_cross,
            "trend": "up" if curr_macd > curr_signal else "down"
        }
    except:
        return None

def run_screening(min_p, max_p):
    results_buy = []
    results_sell = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        data_list = list(executor.map(get_stock_analysis, TICKERS))
    
    for data in data_list:
        if data is None: continue
        if not (min_p <= data["price"] <= max_p): continue
        
        # --- 買い時推奨 (Buy Signal) ---
        # 条件: RSIが40以下（売られすぎ）または MACDがゴールデンクロス
        if (data["rsi"] < 45 and data["trend"] == "up") or data["macd_gc"]:
            results_buy.append(data)

        # --- 売り時推奨 (Sell Signal / 空売り) ---
        # 条件: RSIが65以上（買われすぎ）または MACDがデッドクロス
        if (data["rsi"] > 60 and data["trend"] == "down") or data["macd_dc"]:
            results_sell.append(data)

    return sorted(results_buy, key=lambda x: x["rsi"])[:10], \
           sorted(results_sell, key=lambda x: x["rsi"], reverse=True)[:10]

# ==========================================
# 📱 アプリ画面設計 (UI)
# ==========================================

st.set_page_config(page_title="AI株スキャナー Pro", layout="centered")
st.title("🎯 AI株スキャナー Pro")
st.caption("RSI ＋ MACD 指標による大引け分析")

# --- 価格設定（手入力とバーの連動） ---
st.write("### 💰 検索価格帯を指定")

# 手入力用
c1, c2 = st.columns(2)
with c1:
    input_min = st.number_input("最低価格 (円)", value=1000, step=100)
with c2:
    input_max = st.number_input("最高価格 (円)", value=10000, step=100)

# バー（スライダー）用。手入力の値と初期値を連動。
slider_range = st.slider("スライダーで微調整", 100, 50000, (int(input_min), int(input_max)))

# --- 分析実行 ---
if st.button("🚀 最新の状況をスキャン", use_container_width=True):
    # スライダーの値を優先して採用
    p_min, p_max = slider_range
    
    with st.spinner('大引け状況を確認中...'):
        buy_list, sell_list = run_screening(p_min, p_max)
    
    st.success(f"スキャン完了！ (価格帯: {p_min:,}円 〜 {p_max:,}円)")

    # --- 結果表示: 買い推奨 ---
    st.subheader("🚀 買い時推奨 (Long)")
    st.info("RSI低位からの反発、またはMACDゴールデンクロスの銘柄です。")
    if buy_list:
        df_b = pd.DataFrame(buy_list)[["code", "price", "rsi"]]
        df_b.columns = ["コード", "終値", "RSI"]
        st.table(df_b)
    else:
        st.write("現在、推奨銘柄はありません。")

    # --- 結果表示: 売り推奨 ---
    st.subheader("📉 売り時推奨 (Short)")
    st.error("RSI高位からの反落、またはMACDデッドクロスの銘柄です。")
    if sell_list:
        df_s = pd.DataFrame(sell_list)[["code", "price", "rsi"]]
        df_s.columns = ["コード", "終値", "RSI"]
        st.table(df_s)
    else:
        st.write("現在、推奨銘柄はありません。")

st.divider()
st.caption("※15:00以降に実行すると、その日の大引け確定値で計算されます。")
