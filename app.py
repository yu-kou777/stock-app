import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Scanner Hybrid-X")

# --- サイドバー：トモユキ専用・操作盤 ---
st.sidebar.title("🎛️ トモユキ専用・操作盤")

# 1. 検索モード
mode = st.sidebar.radio(
    "戦術モード選択",
    ("デイトレ (5分足・超短期)", "スイング (日足・トレンド)")
)

# 2. 株価範囲フィルタ (復活機能！)
st.sidebar.subheader("💰 株価範囲フィルタ")
col1, col2 = st.sidebar.columns(2)
with col1:
    min_price = st.number_input("最低価格 (円)", value=0, step=100)
with col2:
    max_price = st.number_input("最高価格 (円)", value=50000, step=100)

st.sidebar.caption(f"※現在 {min_price}円 〜 {max_price}円 の銘柄のみ表示します")

# 3. 自由入力エリア (数字だけでOK)
st.sidebar.subheader("🔍 個別銘柄サーチ")
st.sidebar.caption("※数字(6758)だけでOK！")
input_tickers = st.sidebar.text_area(
    "銘柄コードを入力 (カンマ区切り)",
    "9101, 8306, 9984, 7203, 6920, 5032, 2413" 
)

# 数字だけの入力を「.T」に自動変換
raw_list = [x.strip() for x in input_tickers.split(',')]
ticker_list = []
for t in raw_list:
    if t.isdigit():
        ticker_list.append(f"{t}.T")
    elif t:
        ticker_list.append(t)

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

    return patterns

# --- メイン解析エンジン ---
def analyze_stock_hybrid(ticker, interval, min_p, max_p):
    try:
        period = "5d" if interval == "5m" else "6mo"
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        
        if len(df) < 20: return None

        latest = df.iloc[-1]
        current_price = latest['Close']

        # --- 【ここでフィルタリング】 ---
        # 設定した価格範囲外なら、計算せずに終了
        if not (min_p <= current_price <= max_p):
            return None

        # テクニカル指標計算
        # 期間に応じて長期線を変える
        long_span = 75 if interval == "1d" else 20
        df['MA_Long'] = ta.sma(df['Close'], length=long_span)
        
        df['RSI'] = ta.rsi(df['Close'], length=14)
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)

        score = 0
        reasons = []

        # トレンド判定
        if latest['Close'] > latest['MA_Long']:
            score += 20
            reasons.append("上昇中")
        else:
            score -= 20
            reasons.append("下落中")

        # RSI
        if latest['RSI'] < 30:
            score += 30
            reasons.append("売られすぎ")
        elif latest['RSI'] > 70:
            score -= 30
            reasons.append("買われすぎ")

        # ゴールデンクロス
        if latest['MACD_12_26_9'] > latest['MACDs_12_26_9'] and df.iloc[-2]['MACD_12_26_9'] < df.iloc[-2]['MACDs_12_26_9']:
            score += 40
            reasons.append("MACD金クロス")

        # パターン認識
        detected = check_candle_patterns(df)
        if detected:
            score += 20 * len(detected)
            reasons.extend(detected)

        # 総合判定
        judgement = "様子見"
        if score >= 60: judgement = "買い推奨 (強気)"
        elif score >= 40: judgement = "買い検討 (打診)"
        elif score <= -40: judgement = "売り推奨 (空売り)"

        return {
            "銘柄": ticker.replace(".T", ""), # .T を消して見やすく
            "現在値": f"{current_price:.0f}円",
            "RSI": round(latest['RSI'], 1),
            "判定": judgement,
            "スコア": score,
            "サイン": ", ".join(reasons)
        }

    except Exception as e:
        return None

# --- アプリ画面表示 ---
st.title(f"🚀 最強株スキャナー：{mode}")
st.write(f"監視対象: {len(ticker_list)} 銘柄") 

if st.button('スキャン開始'):
    interval_setting = "5m" if "デイトレ" in mode else "1d"
    
    results = []
    bar = st.progress(0)
    
    for i, ticker in enumerate(ticker_list):
        # フィルタ設定(min_price, max_price)を渡す
        data = analyze_stock_hybrid(ticker, interval_setting, min_price, max_price)
        if data: results.append(data)
        bar.progress((i + 1) / len(ticker_list))
    
    if results:
        df_res = pd.DataFrame(results).sort_values(by="スコア", ascending=False)
        
        def color_highlight(val):
            color = 'black'
            if '買い' in val: color = 'red'
            elif '売り' in val: color = 'blue'
            return f'color: {color}; font-weight: bold;'

        st.dataframe(df_res.style.map(color_highlight, subset=['判定']))
        st.success(f"{len(results)} 件の銘柄が見つかりました（価格フィルタ適用済）")
    else:
        st.warning("条件に合う銘柄が見つかりませんでした。価格範囲を広げるか、リストを追加してください。")
