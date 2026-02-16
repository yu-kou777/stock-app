import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Scanner Diagnostic")

# --- サイドバー ---
st.sidebar.title("🎛️ 診断モード")

mode = st.sidebar.radio("戦術", ("デイトレ (5分足)", "スイング (日足)"))
search_source = st.sidebar.selectbox("検索対象", ("📝 自由入力", "📊 市場全体"))

col1, col2 = st.sidebar.columns(2)
min_price = col1.number_input("下限", value=0, step=100)
max_price = col2.number_input("上限", value=50000, step=100)

ticker_list = []
if "自由入力" in search_source:
    input_tickers = st.sidebar.text_area("銘柄コード", "9101, 8306, 9984, 7203")
    raw = [x.strip() for x in input_tickers.split(',')]
    for t in raw:
        if t.isdigit(): ticker_list.append(f"{t}.T")
        elif t: ticker_list.append(t)
else:
    # 市場全体（診断用・少量）
    ticker_list = ["9101.T", "8306.T", "7203.T", "9984.T", "6758.T"]
    st.sidebar.info(f"診断のため主要 {len(ticker_list)} 銘柄のみチェックします")

# --- 診断ロジック ---
def diagnose_stock(ticker, interval, min_p, max_p):
    try:
        period = "5d" if interval == "5m" else "6mo"
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        
        # 1. データ取得チェック
        if len(df) == 0:
            return {"銘柄": ticker, "状態": "❌ 取得失敗", "理由": "データ空"}
        
        latest = df.iloc[-1]
        price = latest['Close']
        
        # 2. 価格フィルタチェック
        if not (min_p <= price <= max_p):
            return {"銘柄": ticker, "状態": "⚠️ 除外", "理由": f"価格対象外({int(price)}円)"}

        # 3. テクニカル計算
        long_span = 75 if interval == "1d" else 20
        df['MA_Long'] = ta.sma(df['Close'], length=long_span)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        
        score = 0
        if latest['Close'] > latest['MA_Long']: score += 20
        else: score -= 20
        
        if latest['RSI'] < 30: score += 30
        elif latest['RSI'] > 70: score -= 30
        
        # 4. 判定チェック
        judgement = "様子見"
        if score >= 60: judgement = "買い推奨"
        elif score <= -40: judgement = "売り推奨"
        
        # 市場全体モードでのフィルタ
        if "市場全体" in search_source and judgement == "様子見":
             return {"銘柄": ticker, "状態": "😶 非表示", "理由": "シグナルなし(様子見)"}

        return {
            "銘柄": ticker, 
            "状態": "✅ 表示", 
            "現在値": f"{int(price)}円", 
            "判定": judgement
        }

    except Exception as e:
        return {"銘柄": ticker, "状態": "❌ エラー", "理由": str(e)}

# --- 実行 ---
st.title("🩺 スキャナー診断モード")

if st.button('診断開始'):
    results = []
    interval = "5m" if "デイトレ" in mode else "1d"
    
    bar = st.progress(0)
    for i, t in enumerate(ticker_list):
        res = diagnose_stock(t, interval, min_price, max_price)
        results.append(res)
        bar.progress((i+1)/len(ticker_list))
        
    df = pd.DataFrame(results)
    st.table(df)
