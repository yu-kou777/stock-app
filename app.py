import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Scanner Hybrid-X")

# --- 銘柄データベース (市場全体モード用) ---
# トモユキさんのために、流動性が高く値動きのある主要銘柄を厳選登録しました
MARKET_TICKERS = [
    # 半導体・ハイテク
    "8035", "6920", "6857", "6723", "6758", "6501", "7735", "6701", "6702", "6503",
    # 自動車・機械
    "7203", "7267", "7270", "7201", "6301", "6367", "7011", "7012", "7013",
    # 銀行・金融
    "8306", "8316", "8411", "8591", "8593", "8604", "8601", "8766", "8750",
    # 商社・卸売
    "8001", "8002", "8031", "8053", "8058", "2768",
    # 海運・鉄鋼
    "9101", "9104", "9107", "5401", "5411", "5406",
    # 通信・サービス・その他有力株
    "9984", "9432", "9433", "9434", "6098", "4385", "2413", "4661", "4755", "3659",
    "4502", "4503", "4568", "4519", "4523", "3382", "8267", "9983", "6954", "6981",
    "6971", "6902", "6861", "5802", "5713", "3407", "3402", "4063", "4005", "4188",
    "4901", "4911", "1605", "5020", "8801", "8802", "1925", "1928", "2502", "2503",
    "2801", "2802", "2914", "9020", "9021", "9022", "9201", "9202", "9501", "9503"
]

# --- サイドバー：トモユキ専用・操作盤 ---
st.sidebar.title("🎛️ トモユキ専用・操作盤")

# 1. 検索モード
mode = st.sidebar.radio(
    "戦術モード",
    ("デイトレ (5分足)", "スイング (日足)")
)

# 2. 検索対象の選択 (復活機能！)
search_source = st.sidebar.selectbox(
    "検索対象",
    ("📝 自由入力 (自分のリスト)", "📊 市場全体 (日経225+主要株)")
)

# 3. 株価範囲フィルタ
st.sidebar.subheader("💰 株価フィルタ")
col1, col2 = st.sidebar.columns(2)
with col1:
    min_price = st.number_input("下限 (円)", value=0, step=100)
with col2:
    max_price = st.number_input("上限 (円)", value=50000, step=100)

# 4. 銘柄リストの決定
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
    # 市場全体モードならデータベースを使用
    st.sidebar.info(f"主要 {len(MARKET_TICKERS)} 銘柄から、条件に合うお宝を探します...")
    ticker_list = [f"{t}.T" for t in MARKET_TICKERS]

# --- パターン認識ロジック ---
def check_candle_patterns(df):
    patterns = []
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]
    body = abs(latest['Close'] - latest['Open'])
    prev_body = abs(prev['Close'] - prev['Open'])

    # 明けの明星
    if (prev2['Close'] < prev2['Open']) and \
       (abs(prev['Close'] - prev['Open']) < prev_body * 0.3) and \
       (latest['Close'] > latest['Open'] and latest['Close'] > prev2['Close']):
        patterns.append("✨明けの明星")
    # 下ヒゲピンバー
    lower_shadow = min(latest['Open'], latest['Close']) - latest['Low']
    if lower_shadow > body * 2.5:
        patterns.append("📌下ヒゲ")
    # 大陽線
    if latest['Close'] > latest['Open'] and body > prev_body * 2:
        patterns.append("🔥大陽線")

    return patterns

# --- 解析エンジン (軽量化版) ---
def analyze_stock_hybrid(ticker, interval, min_p, max_p):
    try:
        # 市場全体モードの時は、まず最新価格だけ取って高速フィルタする
        if "市場全体" in search_source:
            # 1日分のデータだけ超高速取得
            fast_check = yf.download(ticker, period="1d", progress=False)
            if len(fast_check) == 0: return None
            curr = fast_check['Close'].iloc[-1]
            # 価格フィルタで弾かれたら、重い計算をせずに即終了
            if not (min_p <= curr <= max_p):
                return None

        # 本番データ取得
        period = "5d" if interval == "5m" else "6mo"
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if len(df) < 20: return None

        latest = df.iloc[-1]
        current_price = latest['Close']
        
        # 念のためここでも価格フィルタ (自由入力モード用)
        if not (min_p <= current_price <= max_p):
            return None

        # テクニカル計算
        long_span = 75 if interval == "1d" else 20
        df['MA_Long'] = ta.sma(df['Close'], length=long_span)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)
        bb = ta.bbands(df['Close'], length=20, std=2)
        df = pd.concat([df, bb], axis=1)

        score = 0
        reasons = []

        # 判定ロジック
        if latest['Close'] > latest['MA_Long']:
            score += 20; reasons.append("上昇中")
        else:
            score -= 20; reasons.append("下落中")

        if latest['RSI'] < 30: score += 30; reasons.append("売られすぎ")
        elif latest['RSI'] > 70: score -= 30; reasons.append("買われすぎ")

        if latest['MACD_12_26_9'] > latest['MACDs_12_26_9'] and df.iloc[-2]['MACD_12_26_9'] < df.iloc[-2]['MACDs_12_26_9']:
            score += 40; reasons.append("MACD金クロス")

        detected = check_candle_patterns(df)
        if detected:
            score += 20 * len(detected)
            reasons.extend(detected)

        # フィルター: 「様子見」は表示しない (市場全体モードのみ)
        judgement = "様子見"
        if score >= 60: judgement = "買い推奨 (強気)"
        elif score >= 40: judgement = "買い検討 (打診)"
        elif score <= -40: judgement = "売り推奨 (空売り)"
        
        # 市場全体モードで「様子見」ばかり出ても邪魔なので、チャンス銘柄だけ返す
        if "市場全体" in search_source and judgement == "様子見":
            return None

        return {
            "銘柄": ticker.replace(".T", ""),
            "現在値": f"{current_price:.0f}円",
            "RSI": round(latest['RSI'], 1),
            "判定": judgement,
            "スコア": score,
            "サイン": ", ".join(reasons)
        }
    except:
        return None

# --- 結果表示 ---
st.title(f"🚀 最強株スキャナー：{mode}")

if st.button('スキャン開始'):
    interval_setting = "5m" if "デイトレ" in mode else "1d"
    results = []
    
    # プログレスバー
    bar = st.progress(0)
    status_text = st.empty()
    
    for i, ticker in enumerate(ticker_list):
        status_text.text(f"解析中... {ticker} ({i+1}/{len(ticker_list)})")
        data = analyze_stock_hybrid(ticker, interval_setting, min_price, max_price)
        if data: results.append(data)
        bar.progress((i + 1) / len(ticker_list))
    
    status_text.empty()
    bar.empty()

    if results:
        df_res = pd.DataFrame(results).sort_values(by="スコア", ascending=False)
        
        def color_highlight(val):
            color = 'black'
            if '買い' in val: color = 'red'
            elif '売り' in val: color = 'blue'
            return f'color: {color}; font-weight: bold;'

        st.dataframe(df_res.style.map(color_highlight, subset=['判定']))
        st.success(f"{len(results)} 件のお宝銘柄を発見しました！")
    else:
        st.warning("条件に合う銘柄が見つかりませんでした。価格範囲を広げてみてください。")
