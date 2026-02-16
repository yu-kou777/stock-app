import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Scanner Hybrid-X (Final)")

# --- 銘柄データベース ---
MARKET_TICKERS = [
    "8035", "6920", "6857", "6723", "6758", "6501", "7735", "6701", "6702", "6503",
    "7203", "7267", "7270", "7201", "6301", "6367", "7011", "7012", "7013",
    "8306", "8316", "8411", "8591", "8593", "8604", "8601", "8766", "8750",
    "8001", "8002", "8031", "8053", "8058", "2768",
    "9101", "9104", "9107", "5401", "5411", "5406",
    "9984", "9432", "9433", "9434", "6098", "4385", "2413", "4661", "4755", "3659",
    "4502", "4503", "4568", "4519", "4523", "3382", "8267", "9983", "6954", "6981",
    "6971", "6902", "6861", "5802", "5713", "3407", "3402", "4063", "4005", "4188",
    "4901", "4911", "1605", "5020", "8801", "8802", "1925", "1928", "2502", "2503",
    "2801", "2802", "2914", "9020", "9021", "9022", "9201", "9202", "9501", "9503"
]

# --- サイドバー ---
st.sidebar.title("🎛️ トモユキ専用・操作盤")

mode = st.sidebar.radio("戦術モード", ("デイトレ (5分足)", "スイング (日足)"))
search_source = st.sidebar.selectbox("検索対象", ("📝 自由入力", "📊 市場全体 (主要株)"))

st.sidebar.subheader("💰 株価フィルタ")
col1, col2 = st.sidebar.columns(2)
min_price = col1.number_input("下限", value=0, step=100)
max_price = col2.number_input("上限", value=50000, step=100)

ticker_list = []
if "自由入力" in search_source:
    st.sidebar.subheader("🔍 銘柄コード入力")
    input_tickers = st.sidebar.text_area("数字だけでOK", "9101, 8306, 9984, 7203")
    raw_list = [x.strip() for x in input_tickers.split(',')]
    for t in raw_list:
        if t.isdigit(): ticker_list.append(f"{t}.T")
        elif t: ticker_list.append(t)
else:
    st.sidebar.info(f"主要 {len(MARKET_TICKERS)} 銘柄を全チェックします")
    ticker_list = [f"{t}.T" for t in MARKET_TICKERS]

# --- ヘルパー関数 ---
def flatten_data(df):
    if isinstance(df.columns, pd.MultiIndex):
        try: df.columns = df.columns.droplevel(1) 
        except: pass
    return df

def check_patterns(df):
    patterns = []
    try:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        body = abs(latest['Close'] - latest['Open'])
        lower_shadow = min(latest['Open'], latest['Close']) - latest['Low']
        
        if lower_shadow > body * 2.5: patterns.append("📌下ヒゲ")
        if latest['Close'] > latest['Open'] and body > abs(prev['Close'] - prev['Open']) * 2:
            patterns.append("🔥大陽線")
    except: pass
    return patterns

# --- 解析エンジン (修正済み) ---
def analyze_stock(ticker, interval, min_p, max_p):
    try:
        # 1. データ取得
        period = "5d" if interval == "5m" else "6mo"
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        
        if len(df) == 0: return {"銘柄": ticker, "判定": "❌ データなし", "スコア": -999}
        
        # 2. データ整形
        df = flatten_data(df)
        
        # 3. テクニカル指標の計算 (ここを先にやる！)
        long_span = 75 if interval == "1d" else 20
        df['MA_Long'] = ta.sma(df['Close'], length=long_span)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)

        # 4. 最新データの取得 (計算が終わってから取得する！これが修正点)
        latest = df.iloc[-1]
        price = float(latest['Close'])
        
        # 価格フィルタ
        if not (min_p <= price <= max_p):
            return None 

        score = 0
        reasons = []

        # トレンド判定
        ma_long_val = float(latest['MA_Long'])
        if price > ma_long_val:
            score += 20; reasons.append("上昇中")
        else:
            score -= 20; reasons.append("下落中")

        # RSI判定 (エラーの元凶だった場所)
        rsi_val = float(latest['RSI']) # ここで確実に数値を取る
        if rsi_val < 30: score += 30; reasons.append("売られすぎ")
        elif rsi_val > 70: score -= 30; reasons.append("買われすぎ")

        # MACD判定
        hist = float(latest['MACDh_12_26_9'])
        prev_hist = float(df.iloc[-2]['MACDh_12_26_9'])
        if hist > 0 and prev_hist < 0:
            score += 40; reasons.append("MACD金クロス")

        # パターン認識
        pats = check_patterns(df)
        if pats:
            score += 20; reasons.extend(pats)

        # 判定ラベル
        judgement = "☁️ 様子見"
        if score >= 60: judgement = "🔥 買い推奨"
        elif score >= 20: judgement = "✨ 買い検討"
        elif score <= -40: judgement = "📉 売り推奨"
        
        return {
            "銘柄": ticker.replace(".T", ""),
            "現在値": f"{int(price)}円",
            "RSI": round(rsi_val, 1),
            "判定": judgement,
            "スコア": score,
            "サイン": ", ".join(reasons)
        }

    except Exception as e:
        # エラーが起きたらその内容を表示
        return {"銘柄": ticker, "判定": "⚠️ エラー", "理由": str(e), "スコア": -999}

# --- 画面表示 ---
st.title(f"🚀 株スキャナー：{mode} (完動版)")

if st.button('スキャン開始'):
    results = []
    interval = "5m" if "デイトレ" in mode else "1d"
    bar = st.progress(0)
    
    for i, t in enumerate(ticker_list):
        data = analyze_stock(t, interval, min_price, max_price)
        if data: results.append(data)
        bar.progress((i + 1) / len(ticker_list))
        
    if results:
        df_res = pd.DataFrame(results).sort_values(by="スコア", ascending=False)
        st.dataframe(df_res)
        st.success(f"{len(results)} 件を表示しました。")
    else:
        st.warning("表示できる銘柄がありません。価格フィルタを確認してください。")
