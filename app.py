import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Scanner Hybrid-X (Stable)")

# --- 銘柄データベース (市場全体モード用) ---
# 主要銘柄リスト
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

# --- サイドバー：操作盤 ---
st.sidebar.title("🎛️ トモユキ専用・操作盤")

# 1. 検索モード
mode = st.sidebar.radio(
    "戦術モード",
    ("デイトレ (5分足)", "スイング (日足)")
)

# 2. 検索対象
search_source = st.sidebar.selectbox(
    "検索対象",
    ("📝 自由入力 (自分のリスト)", "📊 市場全体 (日経225+主要株)")
)

# 3. 株価フィルタ
st.sidebar.subheader("💰 株価フィルタ")
col1, col2 = st.sidebar.columns(2)
with col1:
    min_price = st.number_input("下限 (円)", value=0, step=100)
with col2:
    max_price = st.number_input("上限 (円)", value=50000, step=100)

# 4. 銘柄リスト作成
ticker_list = []
if "自由入力" in search_source:
    st.sidebar.subheader("🔍 銘柄コード入力")
    input_tickers = st.sidebar.text_area(
        "数字だけでOK (例: 9101, 8306)",
        "9101, 8306, 9984, 7203, 6920"
    )
    raw_list = [x.strip() for x in input_tickers.split(',')]
    for t in raw_list:
        if t.isdigit(): ticker_list.append(f"{t}.T")
        elif t: ticker_list.append(t)
else:
    st.sidebar.info(f"主要 {len(MARKET_TICKERS)} 銘柄からサーチします")
    ticker_list = [f"{t}.T" for t in MARKET_TICKERS]

# --- パターン認識ロジック ---
def check_candle_patterns(df):
    patterns = []
    try:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]
        
        # エラー対策: 値をfloatに強制変換
        close_now = float(latest['Close'])
        open_now = float(latest['Open'])
        close_prev = float(prev['Close'])
        open_prev = float(prev['Open'])
        close_prev2 = float(prev2['Close'])
        open_prev2 = float(prev2['Open'])
        low_now = float(latest['Low'])

        body = abs(close_now - open_now)
        prev_body = abs(close_prev - open_prev)

        # 明けの明星
        if (close_prev2 < open_prev2) and \
           (abs(close_prev - open_prev) < prev_body * 0.3) and \
           (close_now > open_now and close_now > close_prev2):
            patterns.append("✨明けの明星")
        
        # 下ヒゲピンバー
        lower_shadow = min(open_now, close_now) - low_now
        if lower_shadow > body * 2.5:
            patterns.append("📌下ヒゲ")

    except:
        pass # 計算エラー時は無視
    return patterns

# --- 解析エンジン (バグ修正版) ---
def analyze_stock_hybrid(ticker, interval, min_p, max_p):
    try:
        # 市場全体モードの高速フィルタ
        if "市場全体" in search_source:
            # 1日分だけ取って価格チェック
            fast_check = yf.download(ticker, period="1d", progress=False)
            if len(fast_check) == 0: return None
            
            # 【重要】ここが修正ポイント: .iloc[-1].item() で確実に数字にする
            try:
                curr_check = float(fast_check['Close'].iloc[-1])
            except:
                curr_check = float(fast_check['Close'].iloc[-1].iloc[0]) # 万が一の保険
                
            if not (min_p <= curr_check <= max_p):
                return None

        # 本番データ取得
        period = "5d" if interval == "5m" else "6mo"
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if len(df) < 20: return None

        # データ整形 (MultiIndex対策)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        latest = df.iloc[-1]
        
        # 【重要】ここも修正: 確実にfloatにする
        current_price = float(latest['Close'])
        
        # 最終価格フィルタ
        if not (min_p <= current_price <= max_p):
            return None

        # テクニカル計算
        long_span = 75 if interval == "1d" else 20
        df['MA_Long'] = ta.sma(df['Close'], length=long_span)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)

        score = 0
        reasons = []

        # トレンド判定
        ma_long_val = float(latest['MA_Long'])
        if current_price > ma_long_val:
            score += 20; reasons.append("上昇中")
        else:
            score -= 20; reasons.append("下落中")

        # RSI判定
        rsi_val = float(latest['RSI'])
        if rsi_val < 35: score += 30; reasons.append("売られすぎ") # 条件を少し緩めました(30->35)
        elif rsi_val > 70: score -= 30; reasons.append("買われすぎ")

        # MACD判定
        macd_val = float(latest['MACD_12_26_9'])
        signal_val = float(latest['MACDs_12_26_9'])
        prev_macd = float(df.iloc[-2]['MACD_12_26_9'])
        prev_signal = float(df.iloc[-2]['MACDs_12_26_9'])

        if macd_val > signal_val and prev_macd < prev_signal:
            score += 40; reasons.append("MACD金クロス")

        # パターン認識
        detected = check_candle_patterns(df)
        if detected:
            score += 20 * len(detected)
            reasons.extend(detected)

        # 判定
        judgement = "様子見"
        if score >= 60: judgement = "買い推奨 (強気)"
        elif score >= 40: judgement = "買い検討 (打診)"
        elif score <= -40: judgement = "売り推奨 (空売り)"
        
        # 市場全体モードなら「様子見」はカット
        if "市場全体" in search_source and judgement == "様子見":
            return None

        return {
            "銘柄": ticker.replace(".T", ""),
            "現在値": f"{int(current_price)}円",
            "RSI": round(rsi_val, 1),
            "判定": judgement,
            "スコア": score,
            "サイン": ", ".join(reasons)
        }
    except Exception as e:
        # print(e) # デバッグ用
        return None

# --- 結果表示 ---
st.title(f"🚀 最強株スキャナー：{mode}")

if st.button('スキャン開始'):
    interval_setting = "5m" if "デイトレ" in mode else "1d"
    results = []
    
    bar = st.progress(0)
    status = st.empty()
    
    for i, ticker in enumerate(ticker_list):
        status.text(f"解析中... {ticker}")
        data = analyze_stock_hybrid(ticker, interval_setting, min_price, max_price)
        if data: results.append(data)
        bar.progress((i + 1) / len(ticker_list))
    
    status.empty()
    bar.empty()

    if results:
        df_res = pd.DataFrame(results).sort_values(by="スコア", ascending=False)
        
        def color_highlight(val):
            color = 'black'
            if '買い' in val: color = 'red'
            elif '売り' in val: color = 'blue'
            return f'color: {color}; font-weight: bold;'

        st.dataframe(df_res.style.map(color_highlight, subset=['判定']))
        st.success(f"{len(results)} 件のチャンス銘柄を発見！")
    else:
        st.warning("条件に合う銘柄が見つかりませんでした。価格範囲を広げるか、リストを切り替えてみてください。")
