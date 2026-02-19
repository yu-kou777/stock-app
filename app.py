import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Scanner DayTrade Pro")

# --- 銘柄データベース & 和名辞書 ---
TICKER_MAP = {
    "8035.T": "東京エレク", "6920.T": "レーザーテク", "6857.T": "アドバンテ", "6723.T": "ルネサス",
    "6758.T": "ソニーG", "6501.T": "日立", "7735.T": "SCREEN", "6701.T": "NEC",
    "6702.T": "富士通", "6503.T": "三菱電機", "6861.T": "キーエンス", "6954.T": "ファナック",
    "6981.T": "村田製", "6971.T": "京セラ", "6902.T": "デンソー", "4063.T": "信越化",
    "7203.T": "トヨタ", "7267.T": "ホンダ", "7270.T": "SUBARU", "7201.T": "日産自",
    "6301.T": "コマツ", "6367.T": "ダイキン", "7011.T": "三菱重工", "7012.T": "川崎重工",
    "7013.T": "IHI", "8306.T": "三菱UFJ", "8316.T": "三井住友", "8411.T": "みずほ", 
    "8591.T": "オリックス", "8593.T": "三菱HCキャ", "8604.T": "野村HD", "8601.T": "大和証G", 
    "8766.T": "東京海上", "8750.T": "第一生命", "8001.T": "伊藤忠", "8002.T": "丸紅", 
    "8031.T": "三井物産", "8053.T": "住友商事", "8058.T": "三菱商事", "2768.T": "双日",
    "9101.T": "日本郵船", "9104.T": "商船三井", "9107.T": "川崎汽船", "5401.T": "日本製鉄",
    "5411.T": "JFE", "5406.T": "神戸鋼", "9984.T": "SBG", "9432.T": "NTT", 
    "9433.T": "KDDI", "9434.T": "SB", "6098.T": "リクルート", "4385.T": "メルカリ", 
    "2413.T": "エムスリー", "4661.T": "OLC", "4755.T": "楽天G", "3659.T": "ネクソン", 
    "3382.T": "7&iHD", "8267.T": "イオン", "9983.T": "ファストリ", "5802.T": "住友電工", 
    "5713.T": "住友鉱", "3407.T": "旭化成", "3402.T": "東レ", "4005.T": "住友化", 
    "4188.T": "三菱ケミ", "4901.T": "富士フイルム", "4911.T": "資生堂", "1605.T": "INPEX", 
    "5020.T": "ENEOS", "4502.T": "武田", "4568.T": "第一三共", "4519.T": "中外薬", 
    "4523.T": "エーザイ", "8801.T": "三井不", "8802.T": "三菱地所", "1925.T": "大和ハウス", 
    "1928.T": "積水ハウス", "2502.T": "アサヒ", "2503.T": "キリン", "2801.T": "キッコーマン", 
    "2802.T": "味の素", "2914.T": "JT", "9020.T": "JR東", "9021.T": "JR西", 
    "9022.T": "JR東海", "9201.T": "JAL", "9202.T": "ANA", "9501.T": "東電HD", "9503.T": "関電"
}
MARKET_TICKERS = list(TICKER_MAP.keys())

# --- サイドバー ---
st.sidebar.title("🎛️ トモユキ専用・操作盤")
st.sidebar.header("👀 表示フィルター")
show_all = st.sidebar.checkbox("☁️ 「様子見」も含めて全表示", value=False)
mode = st.sidebar.radio("戦術モード", ("デイトレ (5分足・即エントリー)", "スイング (日足・反発狙い)"))
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
    ticker_list = MARKET_TICKERS

# --- データ整形 ---
def flatten_data(df):
    if isinstance(df.columns, pd.MultiIndex):
        try: df.columns = df.columns.droplevel(1) 
        except: pass
    return df

# --- 平均足 ---
def calculate_heikin_ashi(df):
    ha_df = df.copy()
    ha_df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    ha_df['HA_Open'] = 0.0
    ha_df.iloc[0, ha_df.columns.get_loc('HA_Open')] = (df.iloc[0]['Open'] + df.iloc[0]['Close']) / 2
    for i in range(1, len(df)):
        prev_open = ha_df.iloc[i-1]['HA_Open']
        prev_close = ha_df.iloc[i-1]['HA_Close']
        ha_df.iloc[i, ha_df.columns.get_loc('HA_Open')] = (prev_open + prev_close) / 2
    ha_df['HA_High'] = ha_df[['High', 'HA_Open', 'HA_Close']].max(axis=1)
    ha_df['HA_Low'] = ha_df[['Low', 'HA_Open', 'HA_Close']].min(axis=1)
    return ha_df

# --- 利確ターゲット計算 (即エントリー特化) --- [復活]
def calculate_targets(price, judgement, mode_name):
    try:
        price = float(price)
        entry_msg = f"{int(price)}" 

        if "デイトレ" in mode_name:
            profit_ratio = 1.02 # +2%
            stop_ratio = 0.99   # -1%
        else:
            profit_ratio = 1.07 # +7%
            stop_ratio = 0.97   # -3%

        if "買い" in judgement or "突入" in judgement:
            target = price * profit_ratio
            stop = price * stop_ratio
            gain = int(target - price)
            return entry_msg, f"🎯 {int(target)} (+{gain})", f"🛡️ {int(stop)}"
        elif "売り" in judgement or "危険" in judgement:
            target = price * (2 - profit_ratio)
            stop = price * (2 - stop_ratio)
            gain = int(price - target)
            return entry_msg, f"🎯 {int(target)} (+{gain})", f"🛡️ {int(stop)}"
        else: return "-", "-", "-"
    except: return "-", "-", "-"

# --- 反発ライン計算 (スイング用待機) --- [復活]
def calculate_rebound_entry(df, trend_type, current_price, judgement):
    try:
        latest = df.iloc[-1]
        ma_long = float(latest['MA_Long'])
        recent_low = float(df['Low'].tail(20).min())
        recent_high = float(df['High'].tail(20).max())

        entry_price = 0
        if "買い" in judgement or "突入" in judgement:
            if trend_type == "上昇トレンド": entry_price = ma_long
            else: entry_price = recent_low
            if current_price <= entry_price * 1.01: return "⚡ 今すぐ突入"
            else: return f"⏳ {int(entry_price)}円待ち"
        elif "売り" in judgement:
            if trend_type == "下落トレンド": entry_price = ma_long
            else: entry_price = recent_high
            if current_price >= entry_price * 0.99: return "⚡ 今すぐ突入"
            else: return f"⏳ {int(entry_price)}円待ち"
        return "-"
    except: return "-"

# --- 解析エンジン (統合版) ---
def analyze_stock(ticker, interval, min_p, max_p):
    try:
        period = "5d" if interval == "5m" else "6mo"
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if len(df) < 25: return {"銘柄": ticker, "判定": "❌ データ不足", "スコア": -999}
        
        df = flatten_data(df)
        df = calculate_heikin_ashi(df)

        long_span = 75 if interval == "1d" else 20
        short_span = 25 if interval == "1d" else 5
        df['MA_Long'] = ta.sma(df['Close'], length=long_span)
        df['MA_Short'] = ta.sma(df['Close'], length=short_span)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        df['Vol_Avg5'] = df['Volume'].rolling(5).mean()
        df['Kairi'] = ((df['Close'] - df['MA_Short']) / df['MA_Short']) * 100
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)

        latest = df.iloc[-1]
        price = float(latest['Close'])
        if not (min_p <= price <= max_p): return None 

        score = 0
        reasons = []
        judgement = "☁️ 様子見"

        # --- ① トレンド判定 ---
        ma_long_val = float(latest['MA_Long'])
        trend_status = "ボックス"
        if ma_long_val > float(df.iloc[-5]['MA_Long']): trend_status = "上昇トレンド"

        # --- ② 需給・リスク判定 (新規) ---
        is_selclimax = False
        kairi = float(latest['Kairi'])
        rsi_val = float(latest['RSI'])
        vol_today = float(latest['Volume'])
        vol_avg = float(latest['Vol_Avg5'])

        if interval == "1d":
            if rsi_val < 20 and vol_today > (vol_avg * 3):
                is_selclimax = True
                score += 50
                reasons.append("💎セリクラ")
                judgement = "🔥 突入検討(底打ち)"

        if kairi < -20:
            score += 20; reasons.append(f"乖離率大({kairi:.1f}%)")
        elif kairi > 15:
            score -= 30; reasons.append(f"高値圏厳禁({kairi:.1f}%)")
            judgement = "🚫 危険(急騰後)"

        recent_high = float(df['High'].tail(20).max())
        recent_low = float(df['Low'].tail(20).min())
        drop_width = recent_high - recent_low
        rebound_1_3 = recent_low + (drop_width * 0.33)
        rebound_1_2 = recent_low + (drop_width * 0.5)

        # --- ③ 既存テクニカル・平均足判定 ---
        ha_close = float(latest['HA_Close']); ha_open = float(latest['HA_Open'])
        ha_low = float(latest['HA_Low']); ha_high = float(latest['HA_High'])
        body_len = abs(ha_close - ha_open)
        
        if ha_close > ha_open:
            if (ha_open - ha_low) < (body_len * 0.1): score += 30; reasons.append("平均足:最強")
            else: score += 10; reasons.append("平均足:陽")
        elif ha_close < ha_open:
            if (ha_high - ha_open) < (body_len * 0.1): score -= 30; reasons.append("平均足:最弱")
            else: score -= 10; reasons.append("平均足:陰")

        if rsi_val < 30 and not is_selclimax: score += 20; reasons.append("RSI底")
        elif rsi_val > 70: score -= 20; reasons.append("RSI天")
        
        if float(latest['MACDh_12_26_9']) > 0 and float(df.iloc[-2]['MACDh_12_26_9']) < 0: 
            score += 30; reasons.append("MACD好転")

        if "様子見" in judgement:
            if score >= 50: judgement = "🔥 買い推奨"
            elif score >= 20: judgement = "✨ 買い検討"
            elif score <= -40: judgement = "📉 売り推奨"
            elif score <= -20: judgement = "☔ 売り検討"

        # --- ④ 元の利確・損切・待機ターゲット計算を再適用 ---
        entry_target, profit_target, stop_loss = calculate_targets(price, judgement, mode)
        wait_target = "-"
        if interval == "1d":
            df_calc = df.copy(); df_calc['MA_Long'] = df['MA_Short']
            wait_target = calculate_rebound_entry(df_calc, trend_status, price, judgement)

        return {
            "銘柄": ticker.replace(".T", ""),
            "社名": TICKER_MAP.get(ticker, "-"),
            "現在値": f"{int(price)}",
            "判定": judgement,
            "待機(Swing)": wait_target,     # 復活
            "利確目標(+2/7%)": profit_target, # 復活
            "損切目安(-1/3%)": stop_loss,     # 復活
            "1/3戻(第一壁)": f"{int(rebound_1_3)}",  # 新規
            "1/2戻(第二壁)": f"{int(rebound_1_2)}",  # 新規
            "乖離率": f"{kairi:.1f}%",
            "スコア": score,
            "根拠": ", ".join(reasons)
        }
    except Exception as e:
        return {"銘柄": ticker, "判定": "⚠️ エラー", "根拠": str(e), "スコア": -999}

# --- 画面表示 ---
st.title(f"🚀 株スキャナー：{mode}")

if st.button('スキャン開始'):
    results = []
    interval = "5m" if "デイトレ" in mode else "1d"
    bar = st.progress(0)
    for i, t in enumerate(ticker_list):
        data = analyze_stock(t, interval, min_price, max_price)
        if data: results.append(data)
        bar.progress((i + 1) / len(ticker_list))
        
    if results:
        df_res = pd.DataFrame(results)
        if not show_all: df_res = df_res[~df_res["判定"].str.contains("様子見")]

        if not df_res.empty:
            df_res["絶対値スコア"] = df_res["スコア"].abs()
            df_res = df_res.sort_values(by="絶対値スコア", ascending=False)
            
            # 列の整理（元データと新データを綺麗に並べる）
            cols = [
                "銘柄", "社名", "現在値", "判定", 
                "待機(Swing)", "利確目標(+2/7%)", "損切目安(-1/3%)", 
                "1/3戻(第一壁)", "1/2戻(第二壁)", "乖離率", "根拠", "スコア"
            ]
            
            # デイトレモード時は不要な列を隠す
            if "デイトレ" in mode:
                cols.remove("待機(Swing)")
                cols.remove("1/3戻(第一壁)")
                cols.remove("1/2戻(第二壁)")
            
            st.dataframe(df_res[cols], use_container_width=True)
            
            if "デイトレ" in mode:
                st.success("🚀 デイトレモード：現在値からの目標利確・損切ラインを表示中。")
            else:
                st.success("📉 スイングモード：エントリー待機価格と、需給の壁（1/3戻し・1/2戻し）を同時監視中。")
        else:
            st.warning("現在、強いサインが出ている銘柄はありません。")
    else:
        st.warning("データなし")
