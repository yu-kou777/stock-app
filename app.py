import streamlit as st
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🛡️ 銘柄辞書 (日本語表記用マスタ)
# ==========================================
# ネットで取得したコードがここにあれば、この日本語名を使います
NAME_MAP = {
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
    "8601.T": "大和証券", "9107.T": "川崎汽船", "9531.T": "東京ガス", "9532.T": "大阪ガス",
    "8591.T": "オリックス", "3003.T": "ヒューリック", "2702.T": "マクドナルド"
}

# お気に入り (常に監視)
MY_FAVORITES = {
    "8591.T": "オリックス", "3003.T": "ヒューリック", "2702.T": "マクドナルド"
}

# ==========================================
# 🔄 銘柄リスト自動取得ロジック (改良版)
# ==========================================
@st.cache_data(ttl=3600*12) 
def get_tickers_safe():
    tickers_dict = {}
    try:
        # Wikipediaからコードを取得
        url = "https://en.wikipedia.org/wiki/Nikkei_225"
        tables = pd.read_html(url, flavor='html5lib') 
        df = tables[0]
        
        code_col = None
        for col in df.columns:
            if df[col].astype(str).str.match(r'\d{4}').any():
                code_col = col
                break
        
        if code_col:
            for index, row in df.iterrows():
                code = str(row[code_col]) + ".T"
                # 【重要】もし辞書に日本語名があればそれを使う。なければネットの名前を使う
                if code in NAME_MAP:
                    name = NAME_MAP[code]
                else:
                    name = str(row[1]) # 新規採用銘柄などは仮名
                tickers_dict[code] = name
                
    except Exception:
        pass
    
    # 失敗時は辞書全体をバックアップとして使う
    if not tickers_dict:
        tickers_dict.update(NAME_MAP)

    # お気に入りを追加
    tickers_dict.update(MY_FAVORITES)
    
    return tickers_dict

# ==========================================
# 🕯️ パターン認識
# ==========================================
def detect_candle_pattern(df):
    if len(df) < 3: return None, 0, None
    d1, d2, d3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    body1, body2, body3 = abs(d1.Close-d1.Open), abs(d2.Close-d2.Open), abs(d3.Close-d3.Open)
    is_green1, is_green3 = d1.Close > d1.Open, d3.Close > d3.Open

    # 1. 明けの明星
    if (not is_green1 and body1 > d1.Open*0.01 and body2 < body1*0.3 and 
        d2.Close < d1.Close and is_green3 and body3 > body1*0.5 and 
        d3.Close > (d1.Open+d1.Close)/2):
        return "🌅明けの明星", 50, "buy"
    # 2. 陽の包み足
    if (d2.Close < d2.Open and is_green3 and d3.Open < d2.Close and d3.Close > d2.Open and body3 > body2):
        return "📈陽の包み足", 30, "buy"
    # 3. 宵の明星
    if (is_green1 and body1 > d1.Open*0.01 and body2 < body1*0.3 and 
        d2.Close > d1.Close and not is_green3 and body3 > body1*0.5 and 
        d3.Close < (d1.Open+d1.Close)/2):
        return "🌌宵の明星", 50, "sell"
    # 4. 陰の包み足
    if (d2.Close > d2.Open and not is_green3 and d3.Open > d2.Close and d3.Close < d2.Open and body3 > body2):
        return "📉陰の包み足", 30, "sell"
    return None, 0, None

# ==========================================
# 🧠 テクニカル分析ロジック
# ==========================================
def get_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 60: return None
        
        curr_price = hist["Close"].iloc[-1]
        if not (min_p <= curr_price <= max_p): return None

        # 指標計算
        close = hist['Close']
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        curr_rsi = rsi.iloc[-1]
        
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist_now = macd.iloc[-1] - signal.iloc[-1]
        hist_prev = macd.iloc[-2] - signal.iloc[-2]

        pattern_name, pattern_score, pattern_type = detect_candle_pattern(hist)
        
        # ターゲット計算
        res_line = hist['High'].rolling(25).max().iloc[-1]
        sup_line = hist['Low'].rolling(25).min().iloc[-1]
        buy_target = curr_price * 1.07
        sell_target = curr_price * 0.93

        # スコア計算
        buy_score, sell_score = 0, 0
        
        # --- 買いスコア (RSI < 60 安全装置) ---
        if curr_rsi < 60:
            if curr_rsi < 30: buy_score += 40
            elif curr_rsi < 40: buy_score += 20
            if hist_now > hist_prev: buy_score += 20
            if pattern_type == "buy": buy_score += pattern_score
        
        # --- 売りスコア ---
        if curr_rsi > 70: sell_score += 40
        elif curr_rsi > 60: sell_score += 20
        if hist_now < hist_prev: sell_score += 20
        if pattern_type == "sell": sell_score += pattern_score

        signal_disp = pattern_name if pattern_name else "-"

        return {
            "name": name,
            "code": ticker.replace(".T", ""),
            "price": curr_price,
            "rsi": curr_rsi,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "signal": signal_disp,
            "buy_target": buy_target,
            "res_line": res_line,
            "sell_target": sell_target,
            "sup_line": sup_line
        }
    except:
        return None

def run_scan(min_p, max_p):
    tickers = get_tickers_safe()
    results = []
    
    st.info(f"監視対象: **{len(tickers)}銘柄** をスキャン中...")
    bar = st.progress(0)
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_analysis, t, tickers[t], min_p, max_p) for t in tickers]
        for i, f in enumerate(futures):
            res = f.result()
            if res: results.append(res)
            bar.progress((i + 1) / len(futures))
    bar.empty()
    return results

# ==========================================
# 📱 アプリ画面設定
# ==========================================
st.set_page_config(page_title="最強株スキャナー", layout="wide")
st.title("🦅 最強株スキャナー (安全装置付き)")
st.caption("RSI 60未満 × 強力シグナル × 日本語最適化")

col1, col2 = st.columns([1, 2])
with col1:
    p_min = st.number_input("下限 (円)", value=2000, step=100)
    p_max = st.number_input("上限 (円)", value=7000, step=100)
with col2:
    st.info("買い推奨の絶対ルール: RSI < 60 の銘柄のみ表示 (高値掴み防止)")

if st.button("🚀 スキャン開始", use_container_width=True):
    data = run_scan(p_min, p_max)
    if data:
        df = pd.DataFrame(data)
        
        # 小数点以下を丸める処理（見やすさ改善）
        df['price'] = df['price'].astype(int)
        df['rsi'] = df['rsi'].round(1)
        df['buy_target'] = df['buy_target'].astype(int)
        df['sell_target'] = df['sell_target'].astype(int)
        df['res_line'] = df['res_line'].astype(int)
        df['sup_line'] = df['sup_line'].astype(int)

        buys = df[df["buy_score"] >= 60].sort_values("buy_score", ascending=False).head(15)
        sells = df[df["sell_score"] >= 60].sort_values("sell_score", ascending=False).head(15)

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🔥 買い推奨")
            if not buys.empty:
                # カラム順序を強制指定して、名前を最初に持ってくる
                st.dataframe(
                    buys[["name", "signal", "price", "rsi", "buy_target", "res_line"]].rename(
                        columns={"name":"銘柄名", "signal":"特選シグナル", "price":"現在値", "rsi":"RSI", "buy_target":"利確(+7%)", "res_line":"抵抗線"}
                    ),
                    use_container_width=True,
                    hide_index=True # インデックス番号を隠してスッキリさせる
                )
            else:
                st.write("推奨なし")

        with c2:
            st.subheader("📉 売り推奨")
            if not sells.empty:
                st.dataframe(
                    sells[["name", "signal", "price", "rsi", "sell_target", "sup_line"]].rename(
                        columns={"name":"銘柄名", "signal":"特選シグナル", "price":"現在値", "rsi":"RSI", "sell_target":"利確(-7%)", "sup_line":"支持線"}
                    ),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.write("推奨なし")
