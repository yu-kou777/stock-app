import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Scanner Hybrid-X")

# --- サイドバー：トモユキさんの操作盤 ---
st.sidebar.title("🎛️ トモユキ専用・操作盤")

# 1. 検索モードの切り替え (デイトレ vs スイング)
mode = st.sidebar.radio(
    "戦術モード選択",
    ("デイトレ (5分足・超短期)", "スイング (日足・トレンド)")
)

# 2. 自由入力エリア (個別のデイトレ検索用)
st.sidebar.subheader("🔍 個別銘柄サーチ")
input_tickers = st.sidebar.text_area(
    "銘柄コードを入力 (カンマ区切り)",
    "9101.T, 8306.T, 9984.T, 7203.T, 6920.T" # デフォルト値
)

# リストの整形
ticker_list = [x.strip() for x in input_tickers.split(',')]

# --- パターン認識ロジック (アイ×トモユキのこだわり) ---
def check_candle_patterns(df):
    """明けの明星や包み足などのローソク足パターンを検出"""
    patterns = []
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]

    # 実体の定義
    body = abs(latest['Close'] - latest['Open'])
    prev_body = abs(prev['Close'] - prev['Open'])

    # 1. 明けの明星 (Morning Star) 風の反転サイン
    # (陰線 → 小陽線/十字 → 大陽線)
    if (prev2['Close'] < prev2['Open']) and \
       (abs(prev['Close'] - prev['Open']) < prev_body * 0.3) and \
       (latest['Close'] > latest['Open'] and latest['Close'] > prev2['Close']):
        patterns.append("✨明けの明星(反転)")

    # 2. 下ヒゲピンバー (底打ち示唆)
    # (ヒゲが実体の2倍以上)
    lower_shadow = min(latest['Open'], latest['Close']) - latest['Low']
    if lower_shadow > body * 2.5:
        patterns.append("📌下ヒゲピンバー(底堅い)")

    # 3. 大陽線 (強気)
    if latest['Close'] > latest['Open'] and body > prev_body * 2:
        patterns.append("🔥大陽線(勢いあり)")

    return patterns

# --- メイン解析エンジン ---
def analyze_stock_hybrid(ticker, interval):
    try:
        # 期間設定: デイトレなら5日分、スイングなら6ヶ月分
        period = "5d" if interval == "5m" else "6mo"
        
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if len(df) < 50: return None

        # --- テクニカル指標 ---
        # トレンド: 移動平均線 (デイトレ用短期/スイング用長期)
        df['MA_Short'] = ta.sma(df['Close'], length=5)
        df['MA_Long'] = ta.sma(df['Close'], length=75 if interval == "1d" else 20)
        
        # オシレーター: RSI & MACD
        df['RSI'] = ta.rsi(df['Close'], length=14)
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)

        # ボリンジャーバンド (±2σ)
        bb = ta.bbands(df['Close'], length=20, std=2)
        df = pd.concat([df, bb], axis=1)

        latest = df.iloc[-1]
        
        # --- 判定ロジック (プロ基準 + パターン認識) ---
        score = 0
        reasons = []

        # 1. トレンド判定 (75日線または20MA)
        if latest['Close'] > latest['MA_Long']:
            score += 20
            reasons.append("上昇トレンド中")
        else:
            score -= 20
            reasons.append("下落トレンド")

        # 2. RSIフィルター (買われすぎ警告)
        if latest['RSI'] < 35:
            score += 30
            reasons.append("売られすぎ(反発期待)")
        elif latest['RSI'] > 75:
            score -= 30
            reasons.append("買われすぎ(天井警戒)")

        # 3. ゴールデンクロス (MACD)
        if latest['MACD_12_26_9'] > latest['MACDs_12_26_9'] and df.iloc[-2]['MACD_12_26_9'] < df.iloc[-2]['MACDs_12_26_9']:
            score += 40
            reasons.append("MACD金クロス")

        # 4. アイとトモユキの「パターン認識」を注入
        detected_patterns = check_candle_patterns(df)
        if detected_patterns:
            score += 20 * len(detected_patterns)
            reasons.extend(detected_patterns)

        # 判定
        judgement = "様子見"
        if score >= 60: judgement = "買い推奨 (強気)"
        elif score >= 40: judgement = "買い検討 (打診)"
        elif score <= -40: judgement = "売り推奨 (空売り)"

        return {
            "銘柄": ticker,
            "現在値": round(latest['Close'], 1),
            "RSI": round(latest['RSI'], 1),
            "判定": judgement,
            "スコア": score,
            "検出サイン": ", ".join(reasons)
        }

    except Exception as e:
        return None

# --- アプリ画面 ---
st.title(f"🚀 最強株スキャナー：{mode}")
st.markdown("アイとトモユキの共同開発モデル (Ver. Hybrid-X)")

if st.button('スキャン開始'):
    interval_setting = "5m" if "デイトレ" in mode else "1d"
    
    results = []
    bar = st.progress(0)
    
    for i, ticker in enumerate(ticker_list):
        data = analyze_stock_hybrid(ticker, interval_setting)
        if data: results.append(data)
        bar.progress((i + 1) / len(ticker_list))
    
    if results:
        # スコア順に並び替え
        df_res = pd.DataFrame(results).sort_values(by="スコア", ascending=False)
        
        # 色付け機能
        def color_highlight(val):
            color = 'black'
            if '買い' in val: color = 'red'
            elif '売り' in val: color = 'blue'
            return f'color: {color}; font-weight: bold;'

        st.dataframe(df_res.style.map(color_highlight, subset=['判定']))
        st.success("スキャン完了！左のサイドバーで銘柄やモードを自由に変更できます。")
    else:
        st.error("データが取得できませんでした。銘柄コードを確認してください。")
