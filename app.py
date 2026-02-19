import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Scanner DayTrade Pro")

# --- 銘柄データベース & 和名辞書 ---
TICKER_MAP = {
    # 半導体・ハイテク
    "8035.T": "東京エレク", "6920.T": "レーザーテク", "6857.T": "アドバンテ", "6723.T": "ルネサス",
    "6758.T": "ソニーG", "6501.T": "日立", "7735.T": "SCREEN", "6701.T": "NEC",
    "6702.T": "富士通", "6503.T": "三菱電機", "6861.T": "キーエンス", "6954.T": "ファナック",
    "6981.T": "村田製", "6971.T": "京セラ", "6902.T": "デンソー", "4063.T": "信越化",
    # 自動車・機械
    "7203.T": "トヨタ", "7267.T": "ホンダ", "7270.T": "SUBARU", "7201.T": "日産自",
    "6301.T": "コマツ", "6367.T": "ダイキン", "7011.T": "三菱重工", "7012.T": "川崎重工",
    "7013.T": "IHI",
    # 金融
    "8306.T": "三菱UFJ", "8316.T": "三井住友", "8411.T": "みずほ", "8591.T": "オリックス",
    "8593.T": "三菱HCキャ", "8604.T": "野村HD", "8601.T": "大和証G", "8766.T": "東京海上",
    "8750.T": "第一生命",
    # 商社
    "8001.T": "伊藤忠", "8002.T": "丸紅", "8031.T": "三井物産", "8053.T": "住友商事",
    "8058.T": "三菱商事", "2768.T": "双日",
    # 海運・鉄鋼
    "9101.T": "日本郵船", "9104.T": "商船三井", "9107.T": "川崎汽船", "5401.T": "日本製鉄",
    "5411.T": "JFE", "5406.T": "神戸鋼",
    # 通信・サービス
    "9984.T": "SBG", "9432.T": "NTT", "9433.T": "KDDI", "9434.T": "SB",
    "6098.T": "リクルート", "4385.T": "メルカリ", "2413.T": "エムスリー", "4661.T": "OLC",
    "4755.T": "楽天G", "3659.T": "ネクソン", "3382.T": "7&iHD", "8267.T": "イオン",
    "9983.T": "ファストリ",
    # 素材・エネルギー・その他
    "5802.T": "住友電工", "5713.T": "住友鉱", "3407.T": "旭化成", "3402.T": "東レ",
    "4005.T": "住友化", "4188.T": "三菱ケミ", "4901.T": "富士フイルム", "4911.T": "資生堂",
    "1605.T": "INPEX", "5020.T": "ENEOS", "4502.T": "武田", "4568.T": "第一三共",
    "4519.T": "中外薬", "4523.T": "エーザイ", "8801.T": "三井不", "8802.T": "三菱地所",
    "1925.T": "大和ハウス", "1928.T": "積水ハウス", "2502.T": "アサヒ", "2503.T": "キリン",
    "2801.T": "キッコーマン", "2802.T": "味の素", "2914.T": "JT",
    "9020.T": "JR東", "9021.T": "JR西", "9022.T": "JR東海", "9201.T": "JAL",
    "9202.T": "ANA", "9501.T": "東電HD", "9503.T": "関電"
}
MARKET_TICKERS = list(TICKER_MAP.keys())

# --- サイドバー ---
st.sidebar.title("🎛️ トモユキ専用・操作盤")
st.sidebar.header("👀 表示フィルター")
show_all = st.sidebar.checkbox("☁️ 「様子見」も含めて全表示", value=False)
mode = st.sidebar.radio("戦術モード", ("デイトレ (5分足・即エントリー)", "スイング・リバ取り (日足・反発狙い)"))
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

# --- 解析エンジン (需給・ファンダメンタル視点統合) ---
def analyze_stock(ticker, interval, min_p, max_p):
    try:
        # 需給やシコリを長期間で見るため、スイング時は最低半年分取得
        period = "5d" if interval == "5m" else "6mo"
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if len(df) < 25: return {"銘柄": ticker, "判定": "❌ データ不足", "スコア": -999}
        
        df = flatten_data(df)
        df = calculate_heikin_ashi(df)

        # テクニカル指標の計算
        long_span = 75 if interval == "1d" else 20
        short_span = 25 if interval == "1d" else 5
        df['MA_Long'] = ta.sma(df['Close'], length=long_span)
        df['MA_Short'] = ta.sma(df['Close'], length=short_span)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        df['Vol_Avg5'] = df['Volume'].rolling(5).mean() # 5日平均出来高
        
        # 乖離率の計算（25日線 or 5本線からの乖離）
        df['Kairi'] = ((df['Close'] - df['MA_Short']) / df['MA_Short']) * 100
        
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)

        latest = df.iloc[-1]
        price = float(latest['Close'])
        if not (min_p <= price <= max_p): return None 

        score = 0
        reasons = []
        judgement = "☁️ 様子見"

        # --------------------------------------------------
        # ★ 需給・リスク判定ロジック ★
        # --------------------------------------------------
        is_selclimax = False
        kairi = float(latest['Kairi'])
        rsi_val = float(latest['RSI'])
        vol_today = float(latest['Volume'])
        vol_avg = float(latest['Vol_Avg5'])

        # ① セリングクライマックス検知 (RSI20以下 + 出来高3倍)
        if interval == "1d":
            if rsi_val < 20 and vol_today > (vol_avg * 3):
                is_selclimax = True
                score += 50
                reasons.append("💎セリクラ(投げ売り完了)")
                judgement = "🔥 突入検討(底打ち)"

        # ② 乖離率による高値掴み・リバ狙い判定
        if kairi < -20:
            score += 20
            reasons.append(f"乖離率大({kairi:.1f}%)")
        elif kairi > 15:
            score -= 30
            reasons.append(f"高値圏・追っかけ厳禁({kairi:.1f}%)")
            judgement = "🚫 危険(急騰後)"

        # ③ 戻り売りの壁 (逃げ場) の計算
        # 直近20日の高値と安値から、シコリ解消の「やれやれ売り」が出るラインを推計
        recent_high = float(df['High'].tail(20).max())
        recent_low = float(df['Low'].tail(20).min())
        drop_width = recent_high - recent_low
        
        rebound_1_3 = recent_low + (drop_width * 0.33)
        rebound_1_2 = recent_low + (drop_width * 0.5)

        # --------------------------------------------------
        # 既存のテクニカル・平均足判定
        # --------------------------------------------------
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

        # 最終判定 (セリクラ・追っかけ厳禁が優先されない場合の通常判定)
        if "様子見" in judgement:
            if score >= 50: judgement = "🔥 買い推奨"
            elif score >= 20: judgement = "✨ 買い検討"
            elif score <= -40: judgement = "📉 売り推奨"
            elif score <= -20: judgement = "☔ 売り検討"
        
        # 将来のJ-Quants連携用プレースホルダー
        # jquants_margin_ratio = None 
        # if jquants_margin_ratio and jquants_margin_ratio > 3.0:
        #    reasons.append("⚠️信用シコリ大")

        company_name = TICKER_MAP.get(ticker, "-")

        return {
            "銘柄": ticker.replace(".T", ""),
            "社名": company_name,
            "現在値": f"{int(price)}",
            "判定": judgement,
            "乖離率": f"{kairi:.1f}%",
            "1/3戻し(第一逃げ場)": f"{int(rebound_1_3)}",
            "1/2戻し(第二逃げ場)": f"{int(rebound_1_2)}",
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
            
            # 列の整理
            cols = ["銘柄", "社名", "現在値", "判定", "乖離率", "1/3戻し(第一逃げ場)", "1/2戻し(第二逃げ場)", "根拠", "スコア"]
            
            # Streamlitで色付け表示を分かりやすく
            st.dataframe(df_res[cols], use_container_width=True)
            
            if "デイトレ" in mode:
                st.success("🚀 デイトレモード：5分足の動きを監視中。")
            else:
                st.success("📉 スイング・リバ取りモード：セリングクライマックスの検知と、やれやれ売りが出る「逃げ場」を計算しました。")
        else:
            st.warning("現在、強いサインが出ている銘柄はありません。")
    else:
        st.warning("データなし")
