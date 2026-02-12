import streamlit as st
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🛡️ バックアップ用リスト (日本語名付き)
# ==========================================
BACKUP_225 = {
    "7203.T": "トヨタ", "9984.T": "SBG", "8306.T": "三菱UFJ", "6758.T": "ソニーG",
    "6861.T": "キーエンス", "6098.T": "リクルート", "8035.T": "東エレク", "4063.T": "信越化学",
    "7974.T": "任天堂", "9432.T": "NTT", "8058.T": "三菱商事", "7267.T": "ホンダ",
    "4502.T": "武田薬品", "6501.T": "日立", "7741.T": "HOYA", "6367.T": "ダイキン",
    "6902.T": "デンソー", "4543.T": "テルモ", "3382.T": "7&iHD", "4519.T": "中外製薬",
    "6273.T": "SMC", "6954.T": "ファナック", "7269.T": "スズキ", "9101.T": "日本郵船",
    "9104.T": "商船三井", "5401.T": "日本製鉄", "8316.T": "三井住友", "8411.T": "みずほ",
    "8766.T": "東京海上", "8801.T": "三井不動産", "1605.T": "INPEX", "1925.T": "大和ハウス",
    "2413.T": "エムスリー", "2502.T": "アサヒ", "2801.T": "キッコーマン", "2914.T": "JT",
    "3407.T": "旭化成", "4503.T": "アステラス", "4507.T": "塩野義", "4523.T": "エーザイ",
    "4568.T": "第一三共", "4578.T": "大塚HD", "4661.T": "OLC", "4901.T": "富士フイルム",
    "4911.T": "資生堂", "5020.T": "ENEOS", "5108.T": "ブリヂストン", "5713.T": "住友鉱山",
    "6146.T": "ディスコ", "6301.T": "コマツ", "6326.T": "クボタ", "6503.T": "三菱電機",
    "6594.T": "ニデック", "6702.T": "富士通", "6723.T": "ルネサス", "6752.T": "パナソニック",
    "6762.T": "TDK", "6857.T": "アドバンテ", "6971.T": "京セラ", "6981.T": "村田製",
    "7011.T": "三菱重工", "7201.T": "日産自", "7270.T": "SUBARU", "7272.T": "ヤマハ発",
    "7733.T": "オリンパス", "7751.T": "キヤノン", "7832.T": "バンナム", "8001.T": "伊藤忠",
    "8002.T": "丸紅", "8015.T": "豊田通商", "8031.T": "三井物産", "8053.T": "住友商事",
    "8604.T": "野村HD", "8630.T": "SOMPO", "8725.T": "MS&AD", "8750.T": "第一生命",
    "8802.T": "三菱地所", "8830.T": "住友不", "9020.T": "JR東", "9021.T": "JR西",
    "9022.T": "JR東海", "9202.T": "ANA", "9735.T": "セコム", "9843.T": "ニトリ",
    "9983.T": "ファストリ", "9501.T": "東電HD", "9503.T": "関西電力", "9433.T": "KDDI",
    "9434.T": "ソフトバンク", "1332.T": "ニッスイ", "1801.T": "大成建設", "1802.T": "大林組",
    "1803.T": "清水建設", "1812.T": "鹿島", "1928.T": "積水ハウス", "2503.T": "キリンHD",
    "2802.T": "味の素", "3402.T": "東レ", "4005.T": "住友化学", "4183.T": "三井化学",
    "4506.T": "住友ファーマ", "4751.T": "サイバー", "4755.T": "楽天G", "5406.T": "神戸製鋼",
    "5714.T": "DOWA", "6504.T": "富士電機", "6701.T": "NEC", "6753.T": "シャープ",
    "7012.T": "川崎重工", "7013.T": "IHI", "7202.T": "いすゞ", "7211.T": "三菱自",
    "8601.T": "大和証券", "9107.T": "川崎汽船", "9531.T": "東京ガス", "9532.T": "大阪ガス"
}

MY_FAVORITES = {
    "8591.T": "オリックス", "3003.T": "ヒューリック", "2702.T": "マクドナルド"
}

# ==========================================
# 🔄 銘柄リスト自動取得ロジック
# ==========================================
@st.cache_data(ttl=3600*12) 
def get_tickers_safe():
    tickers_dict = {}
    try:
        url = "https://en.wikipedia.org/wiki/Nikkei_225"
        tables = pd.read_html(url, flavor='html5lib') 
        df = tables[0]
        code_col = None
        for col in df.columns:
            if df[col].astype(str).str.match(r'\d{4}').any():
                code_col = col
                break
        if code_col:
            name_col = "Company" if "Company" in df.columns else df.columns[0]
            for index, row in df.iterrows():
                code = str(row[code_col]) + ".T"
                name = str(row[name_col])
                tickers_dict[code] = name
    except Exception:
        pass
    
    if not tickers_dict:
        tickers_dict.update(BACKUP_225)
    tickers_dict.update(MY_FAVORITES)
    return tickers_dict

# ==========================================
# 🕯️ ローソク足パターン認識ロジック
# ==========================================
def detect_candle_pattern(df):
    """
    直近3日間のデータから、強力な反転シグナル（明けの明星など）を検出する
    df: 最新3日分以上のDataFrame (Open, Close, High, Low)
    戻り値: (シグナル名, スコア加点, タイプ 'buy' or 'sell' or None)
    """
    if len(df) < 3: return None, 0, None
    
    # 直近3日のデータ取り出し
    d1 = df.iloc[-3] # 2日前
    d2 = df.iloc[-2] # 昨日
    d3 = df.iloc[-1] # 今日 (最新)

    # 実体（Body）とヒゲの計算
    body1 = abs(d1['Close'] - d1['Open'])
    body2 = abs(d2['Close'] - d2['Open'])
    body3 = abs(d3['Close'] - d3['Open'])
    
    # 陽線・陰線の判定
    is_green1 = d1['Close'] > d1['Open']
    is_green2 = d2['Close'] > d2['Open']
    is_green3 = d3['Close'] > d3['Open']

    # --- 買いシグナル ---

    # 1. 🌅 明けの明星 (Morning Star) [底打ち反転]
    # 条件: 大陰線 -> 窓開け極小コマ(下) -> 大陽線(陰線の半値以上戻す)
    is_morning_star = (
        not is_green1 and body1 > d1['Open'] * 0.01 and # 1日目: 大陰線
        body2 < body1 * 0.3 and # 2日目: 小さな実体
        d2['Close'] < d1['Close'] and # ギャップダウン気味
        is_green3 and body3 > body1 * 0.5 and # 3日目: 強い陽線
        d3['Close'] > (d1['Open'] + d1['Close']) / 2 # 1日目の真ん中以上まで戻す
    )
    if is_morning_star:
        return "🌅明けの明星", 50, "buy"

    # 2. 📈 陽の包み足 (Bullish Engulfing) [強い買い]
    # 条件: 陰線 -> 翌日がそれを包む大陽線
    is_bull_engulfing = (
        not is_green2 and # 昨日陰線
        is_green3 and # 今日陽線
        d3['Open'] < d2['Close'] and # 今日の始値が昨日の終値より下（または同等）
        d3['Close'] > d2['Open'] and # 今日の終値が昨日の始値より上
        body3 > body2 # 実体が大きい
    )
    if is_bull_engulfing:
        return "📈陽の包み足", 30, "buy"

    # --- 売りシグナル ---

    # 3. 🌌 宵の明星 (Evening Star) [天井反転]
    # 条件: 大陽線 -> 窓開け極小コマ(上) -> 大陰線
    is_evening_star = (
        is_green1 and body1 > d1['Open'] * 0.01 and # 1日目: 大陽線
        body2 < body1 * 0.3 and # 2日目: 小さな実体
        d2['Close'] > d1['Close'] and # ギャップアップ気味
        not is_green3 and body3 > body1 * 0.5 and # 3日目: 強い陰線
        d3['Close'] < (d1['Open'] + d1['Close']) / 2 # 1日目の真ん中以下まで下げる
    )
    if is_evening_star:
        return "🌌宵の明星", 50, "sell"

    # 4. 📉 陰の包み足 (Bearish Engulfing) [強い売り]
    # 条件: 陽線 -> 翌日がそれを包む大陰線
    is_bear_engulfing = (
        is_green2 and # 昨日陽線
        not is_green3 and # 今日陰線
        d3['Open'] > d2['Close'] and # 今日の始値が昨日の終値より上
        d3['Close'] < d2['Open'] and # 今日の終値が昨日の始値より下
        body3 > body2
    )
    if is_bear_engulfing:
        return "📉陰の包み足", 30, "sell"

    return None, 0, None

# ==========================================
# 🧠 テクニカル分析ロジック
# ==========================================
def get_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        hist_check = stock.history(period="1d")
        if hist_check.empty: return None
        curr_price = hist_check["Close"].iloc[-1]
        
        if not (min_p <= curr_price <= max_p): return None

        df = stock.history(period="6mo")
        if len(df) < 60: return None

        close = df['Close']
        high = df['High']
        low = df['Low']
        
        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        curr_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-3]
        
        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist_now = macd_line.iloc[-1] - signal_line.iloc[-1]
        hist_prev = macd_line.iloc[-2] - signal_line.iloc[-2]

        # --- パターン認識 (New!) ---
        pattern_name, pattern_score, pattern_type = detect_candle_pattern(df)

        # テクニカルライン
        resistance_line = high.rolling(25).max().iloc[-1]
        support_line = low.rolling(25).min().iloc[-1]

        # ターゲット計算
        buy_target_pct = curr_price * 1.07
        buy_stop_pct = curr_price * 0.95
        sell_target_pct = curr_price * 0.93
        sell_stop_pct = curr_price * 1.05

        buy_score = 0
        sell_score = 0
        
        # 基本スコア
        if curr_rsi < 30: buy_score += 40
        elif curr_rsi < 40: buy_score += 20
        if hist_now > hist_prev: buy_score += 20
        if hist_now < 0 and hist_prev < 0: buy_score += 10
        if curr_rsi > prev_rsi: buy_score += 10 
        if curr_price <= support_line * 1.02: buy_score += 10
        
        # パターン加点 (買い)
        if pattern_type == "buy":
            buy_score += pattern_score # 激アツなら+50点

        # 基本スコア (売り)
        if curr_rsi > 70: sell_score += 40
        elif curr_rsi > 60: sell_score += 20
        if hist_now < hist_prev: sell_score += 20
        if hist_now > 0 and hist_prev > 0: sell_score += 10
        if curr_rsi < prev_rsi: sell_score += 10
        if curr_price >= resistance_line * 0.98: sell_score += 10
        
        # パターン加点 (売り)
        if pattern_type == "sell":
            sell_score += pattern_score

        # シグナル名 (なければハイフン)
        signal_display = pattern_name if pattern_name else "-"

        return {
            "name": name,
            "code": ticker.replace(".T", ""),
            "price": curr_price,
            "rsi": curr_rsi,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "signal": signal_display, # 表示用
            "buy_target_pct": buy_target_pct,
            "resistance": resistance_line,
            "sell_target_pct": sell_target_pct,
            "support": support_line
        }
    except:
        return None

def run_scan(min_p, max_p):
    tickers_dict = get_tickers_safe()
    results = []
    target_tickers = list(tickers_dict.keys())
    
    st.info(f"監視対象: **{len(target_tickers)}銘柄** をスキャン中...")
    
    progress_bar = st.progress(0)
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_analysis, t, tickers_dict[t], min_p, max_p) for t in target_tickers]
        total = len(futures)
        for i, f in enumerate(futures):
            res = f.result()
            if res:
                results.append(res)
            progress_bar.progress((i + 1) / total)
            
    progress_bar.empty()
    return results

# ==========================================
# 📱 アプリ画面 UI
# ==========================================
st.set_page_config(page_title="最強株スキャナー", layout="wide")
st.title("🦅 最強株スキャナー (チャートパターン搭載)")
st.caption("RSI/MACD ＋ 酒田五法（明星・包み足）を自動検知")

col1, col2 = st.columns([1, 2])
with col1:
    st.write("##### 💰 価格帯設定")
    p_min = st.number_input("下限 (円)", value=1000, step=100)
    p_max = st.number_input("上限 (円)", value=15000, step=100)
with col2:
    st.write("##### 🕯️ 注目のシグナル")
    st.info("""
    **🌅明けの明星 / 🌌宵の明星**: トレンド転換の強力なサイン
    **📈陽の包み足 / 📉陰の包み足**: 強い勢いを示すサイン
    ※これらのサインが出た銘柄はスコアが跳ね上がります。
    """)

if st.button("🚀 スキャン開始", use_container_width=True):
    data = run_scan(p_min, p_max)
    
    if data:
        df = pd.DataFrame(data)
        buys = df[df["buy_score"] >= 60].sort_values("buy_score", ascending=False).head(15)
        sells = df[df["sell_score"] >= 60].sort_values("sell_score", ascending=False).head(15)

        col_b, col_s = st.columns(2)
        with col_b:
            st.subheader("🔥 買い推奨 (シグナル重視)")
            if not buys.empty:
                st.dataframe(
                    buys[["name", "signal", "price", "rsi", "buy_target_pct", "resistance"]].rename(
                        columns={
                            "name": "銘柄名",
                            "signal": "🔥特選シグナル",
                            "price": "現在値",
                            "rsi": "RSI",
                            "buy_target_pct": "利確目標(+7%)",
                            "resistance": "参考:抵抗線"
                        }
                    ),
                    use_container_width=True
                )
            else:
                st.write("推奨なし")

        with col_s:
            st.subheader("📉 売り推奨 (シグナル重視)")
            if not sells.empty:
                st.dataframe(
                    sells[["name", "signal", "price", "rsi", "sell_target_pct", "support"]].rename(
                        columns={
                            "name": "銘柄名",
                            "signal": "⚡特選シグナル",
                            "price": "現在値",
                            "rsi": "RSI",
                            "sell_target_pct": "利確目標(-7%)",
                            "support": "参考:支持線"
                        }
                    ),
                    use_container_width=True
                )
            else:
                st.write("推奨なし")
    else:
        st.warning("条件に合う銘柄なし")
