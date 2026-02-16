import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Scanner Heikin-Ashi")

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

mode = st.sidebar.radio("戦術モード", ("デイトレ (5分足・平均足予測)", "スイング (日足)"))
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

# --- データ整形関数 ---
def flatten_data(df):
    if isinstance(df.columns, pd.MultiIndex):
        try: df.columns = df.columns.droplevel(1) 
        except: pass
    return df

# --- 平均足 (Heikin-Ashi) 計算ロジック ---
def calculate_heikin_ashi(df):
    """
    平均足を計算してDataFrameに追加する
    HA_Close = (Open + High + Low + Close) / 4
    HA_Open = (前日HA_Open + 前日HA_Close) / 2
    """
    ha_df = df.copy()
    ha_df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    
    # HA_Openの計算（ループが必要）
    ha_df['HA_Open'] = 0.0
    # 最初の行は通常のOpenで代用
    ha_df.iloc[0, ha_df.columns.get_loc('HA_Open')] = (df.iloc[0]['Open'] + df.iloc[0]['Close']) / 2
    
    for i in range(1, len(df)):
        prev_open = ha_df.iloc[i-1]['HA_Open']
        prev_close = ha_df.iloc[i-1]['HA_Close']
        ha_df.iloc[i, ha_df.columns.get_loc('HA_Open')] = (prev_open + prev_close) / 2
        
    ha_df['HA_High'] = ha_df[['High', 'HA_Open', 'HA_Close']].max(axis=1)
    ha_df['HA_Low'] = ha_df[['Low', 'HA_Open', 'HA_Close']].min(axis=1)
    
    return ha_df

# --- 目標株価計算 ---
def calculate_targets(price, judgement, mode_name):
    try:
        if "デイトレ" in mode_name:
            profit_ratio = 1.02; stop_ratio = 0.99
        else:
            profit_ratio = 1.07; stop_ratio = 0.97
        price = float(price)
        if "買い" in judgement:
            target = price * profit_ratio; stop = price * stop_ratio; entry = price
        elif "売り" in judgement:
            target = price * (2 - profit_ratio); stop = price * (2 - stop_ratio); entry = price
        else: return "-", "-", "-"
        return f"{int(entry)}円", f"{int(target)}円", f"{int(stop)}円"
    except: return "-", "-", "-"

# --- 解析エンジン ---
def analyze_stock(ticker, interval, min_p, max_p):
    try:
        # 1. データ取得
        period = "5d" if interval == "5m" else "6mo"
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if len(df) == 0: return {"銘柄": ticker, "判定": "❌ データなし", "スコア": -999}
        df = flatten_data(df)
        
        # 2. 平均足の計算 (デイトレ精度向上の要！)
        df = calculate_heikin_ashi(df)

        # 3. テクニカル指標 (移動平均線などは通常のCloseで計算)
        long_span = 75 if interval == "1d" else 20
        df['MA_Long'] = ta.sma(df['Close'], length=long_span)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)

        # 4. 最新データの取得
        latest = df.iloc[-1]
        price = float(latest['Close'])
        
        if not (min_p <= price <= max_p): return None 

        score = 0
        reasons = []

        # --- 平均足による未来予測ロジック ---
        # 実体の定義
        ha_close = float(latest['HA_Close'])
        ha_open = float(latest['HA_Open'])
        ha_low = float(latest['HA_Low'])
        ha_high = float(latest['HA_High'])
        
        body_len = abs(ha_close - ha_open)
        
        # 判定1: 赤三兵（強い上昇トレンドの継続示唆）
        if ha_close > ha_open: # 陽線
            # 下ヒゲがない（または極小）= 非常に強い
            if (ha_open - ha_low) < (body_len * 0.1):
                score += 30
                reasons.append("平均足:最強(下ヒゲなし)")
            else:
                score += 10
                reasons.append("平均足:陽線")
                
            # 実体が前の足より長い = 勢い加速
            prev_body = abs(df.iloc[-2]['HA_Close'] - df.iloc[-2]['HA_Open'])
            if body_len > prev_body:
                score += 10
                reasons.append("勢い加速")
        
        elif ha_close < ha_open: # 陰線
            if (ha_high - ha_open) < (body_len * 0.1):
                score -= 30
                reasons.append("平均足:最弱(上ヒゲなし)")
            else:
                score -= 10
                reasons.append("平均足:陰線")

        # --- 従来のテクニカル判定 ---
        # トレンド
        ma_long_val = float(latest['MA_Long'])
        if price > ma_long_val: score += 10; reasons.append("MA上抜け")
        else: score -= 10

        # RSI
        rsi_val = float(latest['RSI'])
        if rsi_val < 30: score += 20; reasons.append("RSI底")
        elif rsi_val > 70: score -= 20; reasons.append("RSI天井")

        # MACD
        hist = float(latest['MACDh_12_26_9'])
        prev_hist = float(df.iloc[-2]['MACDh_12_26_9'])
        if hist > 0 and prev_hist < 0: score += 30; reasons.append("MACD好転")

        # --- 総合判定 ---
        judgement = "☁️ 様子見"
        if score >= 50: judgement = "🔥 買い推奨 (強継続)"
        elif score >= 20: judgement = "✨ 買い検討"
        elif score <= -40: judgement = "📉 売り推奨"
        
        entry_p, target_p, stop_p = calculate_targets(price, judgement, mode)

        return {
            "銘柄": ticker.replace(".T", ""),
            "現在値": f"{int(price)}円",
            "判定": judgement,
            "予測": "上昇継続" if score > 30 else ("下落警戒" if score < -30 else "保ち合い"),
            "利確": target_p,
            "損切": stop_p,
            "スコア": score,
            "根拠": ", ".join(reasons)
        }

    except Exception as e:
        return {"銘柄": ticker, "判定": "⚠️ エラー", "理由": str(e), "スコア": -999}

# --- 画面表示 ---
st.title(f"🚀 株スキャナー：{mode}")
if "デイトレ" in mode:
    st.warning("⚠️ デイトレモード：平均足を使って「トレンドの継続性」を予測しています。20分遅延データのため、平均足が「最強(下ヒゲなし)」の銘柄のみを狙ってください。")

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
        # 列の整理
        cols = ["銘柄", "現在値", "判定", "予測", "利確", "損切", "根拠", "スコア"]
        df_res = df_res.reindex(columns=cols)
        st.dataframe(df_res)
        st.success(f"{len(results)} 件解析完了。平均足トレンド予測を適用済み。")
    else:
        st.warning("表示できる銘柄がありません。")

