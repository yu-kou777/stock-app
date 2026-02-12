import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🛡️ 銘柄マスタ (主力・貸借銘柄中心)
# ==========================================
NAME_MAP = {
    "7203.T": "トヨタ", "9984.T": "SBG", "8306.T": "三菱UFJ", "6758.T": "ソニーG",
    "6861.T": "キーエンス", "6098.T": "リクルート", "8035.T": "東エレク", "4063.T": "信越化学",
    "7974.T": "任天堂", "9432.T": "NTT", "8058.T": "三菱商事", "8316.T": "三井住友",
    "8630.T": "SOMPO", "8725.T": "MS&AD", "6701.T": "NEC", "4901.T": "富士フイルム",
    "6702.T": "富士通", "4503.T": "アステラス", "6971.T": "京セラ", "7211.T": "三菱自",
    "8591.T": "オリックス", "3003.T": "ヒューリック", "2702.T": "マクドナルド",
    "7049.T": "識学", "9101.T": "日本郵船", "4661.T": "OLC"
}

# ==========================================
# 🌐 決算日スクレイピング (空売りは決算跨ぎ厳禁！)
# ==========================================
def scrape_earnings_date(code):
    clean_code = code.replace(".T", "")
    url = f"https://kabutan.jp/stock/finance?code={clean_code}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code != 200: return None
        soup = BeautifulSoup(res.text, "html.parser")
        target = soup.find(string=re.compile(r"決算発表予定日"))
        if target:
            match = re.search(r"(\d{2}/\d{2}/\d{2})", str(target.parent.get_text()))
            if match: return datetime.strptime("20" + match.group(1), "%Y/%m/%d").date()
    except: pass
    return None

# ==========================================
# 🕯️ テクニカル & パターン判定 (売り・買い対応)
# ==========================================
def detect_patterns(df, rsi):
    if len(df) < 25: return None, 0, "判定不能", "neutral"
    
    close = df['Close']
    high = df['High']
    low = df['Low']
    ma5 = close.rolling(5).mean().iloc[-1]
    curr_price = close.iloc[-1]
    
    # --- 板の勢い判定 (Itayomi Proxy) ---
    # MA5を割り込んでいるなら「売り圧力優勢」
    if curr_price < ma5 * 0.995: trend = "📉 下落優勢 (売り)"
    elif curr_price > ma5 * 1.005: trend = "📈 上昇優勢 (買い)"
    else: trend = "☁️ 拮抗"

    # --- 買いパターン (RSI < 60) ---
    if rsi < 60:
        # 逆三尊
        l = low.tail(15).values
        if l.min() == l[5:10].min() and l[0:5].min() > l[5:10].min() and l[10:15].min() > l[5:10].min():
            return "💎 逆三尊(底打ち)", 80, trend, "buy"
        # 明けの明星
        if (close.iloc[-3] < df['Open'].iloc[-3] and 
            abs(close.iloc[-2]-df['Open'].iloc[-2]) < abs(close.iloc[-3]-df['Open'].iloc[-3])*0.3 and 
            close.iloc[-1] > df['Open'].iloc[-1]):
            return "🌅 明けの明星", 90, trend, "buy"

    # --- 売りパターン (RSI > 40) ※空売り用 ---
    if rsi > 40:
        # 三尊 (天井サイン)
        h = high.tail(15).values
        if h.max() == h[5:10].max() and h[0:5].max() < h[5:10].max() and h[10:15].max() < h[5:10].max():
            return "💀 三尊(天井)", 85, trend, "sell"
        # 三空踏み上げ (過熱からの急落予兆)
        if len(df) >= 4 and all(df['Low'].iloc[i] > df['High'].iloc[i-1] for i in range(-3, 0)):
            return "☄️ 三空踏み上げ", 90, trend, "sell"
        # 宵の明星 (下落転換)
        if (close.iloc[-3] > df['Open'].iloc[-3] and 
            abs(close.iloc[-2]-df['Open'].iloc[-2]) < abs(close.iloc[-3]-df['Open'].iloc[-3])*0.3 and 
            close.iloc[-1] < df['Open'].iloc[-1]):
            return "🌌 宵の明星", 85, trend, "sell"
        # 陰の包み足 (強い売り)
        if (close.iloc[-2] > df['Open'].iloc[-2] and 
            close.iloc[-1] < df['Open'].iloc[-1] and 
            close.iloc[-1] < df['Open'].iloc[-2] and 
            df['Open'].iloc[-1] > df['Close'].iloc[-2]):
            return "📉 陰の包み足", 70, trend, "sell"

    return None, 0, trend, "neutral"

# ==========================================
# 🧠 精密分析ロジック (MACD予測・RSI補正)
# ==========================================
def get_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 30: return None
        curr_price = hist["Close"].iloc[-1]
        if not (min_p <= curr_price <= max_p): return None

        # --- RSI (補正用) ---
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]

        # --- MACD (トレンド予測) ---
        ema12 = hist['Close'].ewm(span=12, adjust=False).mean()
        ema26 = hist['Close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        
        macd_val = macd.iloc[-1]
        sig_val = signal.iloc[-1]
        prev_macd = macd.iloc[-2]
        prev_sig = signal.iloc[-2]

        # クロス判定
        golden_cross = (prev_macd < prev_sig) and (macd_val > sig_val)
        dead_cross = (prev_macd > prev_sig) and (macd_val < sig_val)
        
        # --- 戦略数値 ---
        # 買いの場合
        buy_tp = int(curr_price * 1.05)
        buy_sl = int(curr_price * 0.97)
        # 空売りの場合 (下がれば利益)
        sell_tp = int(curr_price * 0.95) # 5%下落で利確
        sell_sl = int(curr_price * 1.03) # 3%上昇で損切

        earn_date = scrape_earnings_date(ticker)
        p_name, p_score, trend, sig_type = detect_patterns(hist, rsi)

        # リスク判定
        is_risk = False
        if earn_date and 0 <= (earn_date - datetime.now().date()).days <= 3:
            is_risk = True

        buy_score, sell_score = 0, 0
        
        if not is_risk:
            # ========================
            # 🐂 買いロジック
            # ========================
            if rsi < 60: # 高値掴み防止
                if rsi < 35: buy_score += 40
                if golden_cross: buy_score += 30 # MACD予測
                if "上昇" in trend: buy_score += 20 # 板の勢い
                if sig_type == "buy": buy_score += p_score

            # ========================
            # 🐻 空売りロジック (信用)
            # ========================
            # RSI補正: 売られすぎ(30以下)での空売りは禁止
            if rsi > 40: 
                # 1. 過熱感
                if rsi > 70: sell_score += 40
                elif rsi > 60: sell_score += 20
                
                # 2. MACD予測 (デッドクロスは強い売り)
                if dead_cross: sell_score += 40
                elif macd_val < sig_val: sell_score += 10 # 既に下落トレンド
                
                # 3. 板の勢い (5日線を割っているか)
                if "下落" in trend: sell_score += 30
                
                # 4. パターン
                if sig_type == "sell": sell_score += p_score

        return {
            "コード": ticker.replace(".T", ""), "銘柄名": name, "現在値": int(curr_price),
            "RSI": round(rsi, 1), 
            "MACD状態": "⬇️デッドクロス" if dead_cross else "⬆️ゴールデンクロス" if golden_cross else "ー",
            "パターン": p_name if p_name else "-",
            "勢い": trend,
            "buy_score": buy_score, "buy_target": buy_tp, "buy_cut": buy_sl,
            "sell_score": sell_score, "sell_target": sell_tp, "sell_cut": sell_sl,
            "決算": earn_date if earn_date else "-"
        }
    except: return None

# ==========================================
# 📱 アプリ画面
# ==========================================
st.set_page_config(page_title="最強株スキャナー・信用対応", layout="wide")
st.title("🦅 最強株スキャナー (信用取引・空売り対応)")
st.caption("MACD予測 × 板の勢い × RSI補正で精密判定")

# --- 個別診断 ---
st.header("🔍 個別銘柄診断")
code_in = st.text_input("コード (例: 9984)", "").strip()
if code_in:
    full_c = code_in + ".T" if ".T" not in code_in else code_in
    d_name = NAME_MAP.get(full_c)
    if not d_name:
        try: d_name = yf.Ticker(full_c).info.get('longName', code_in)
        except: d_name = code_in
    
    with st.spinner("多角的分析中..."):
        r = get_analysis(full_c, d_name, 0, 1000000)
    
    if r:
        st.subheader(f"📊 {r['銘柄名']} ({r['コード']})")
        c1, c2, c3 = st.columns(3)
        with c1:
            # 判定ロジック
            if r['buy_score'] >= 50: judge = "買い推奨 🚀"
            elif r['sell_score'] >= 50: judge = "空売り推奨 📉"
            else: judge = "様子見 ☕"
            st.metric("AI判定", judge, delta=f"{r['現在値']}円")
            st.write(f"**勢い:** {r['勢い']}")
        with c2:
            if r['buy_score'] >= r['sell_score']:
                st.metric("利確 (+5%)", f"{r['buy_target']}円")
                st.metric("損切 (-3%)", f"{r['buy_cut']}円", delta_color="inverse")
            else:
                st.metric("空売り利確 (-5%)", f"{r['sell_target']}円", delta_color="inverse")
                st.metric("空売り損切 (+3%)", f"{r['sell_cut']}円")
        with c3:
            st.metric("RSI", r['RSI'])
            st.write(f"**MACD:** {r['MACD状態']}")
            st.write(f"**サイン:** {r['パターン']}")
    else: st.error("取得失敗")

st.divider()

# --- 一括スキャン ---
st.header("🚀 市場全体スキャン")
if st.button("スキャン開始", use_container_width=True):
    with st.spinner("信用売りのチャンスを探しています..."):
        with ThreadPoolExecutor(max_workers=5) as ex:
            fs = [ex.submit(get_analysis, t, n, 1000, 100000) for t, n in NAME_MAP.items()]
            ds = [f.result() for f in fs if f.result()]
    
    if ds:
        df = pd.DataFrame(ds)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🔥 買い推奨 (現物・信用買い)")
            bs = df[df["buy_score"] >= 50].sort_values("buy_score", ascending=False)
            if not bs.empty:
                st.dataframe(bs[["コード","銘柄名","現在値","RSI","MACD状態","勢い","パターン","buy_target"]], hide_index=True)
            else: st.info("なし")
        with c2:
            st.subheader("📉 空売り推奨 (信用売り)")
            ss = df[df["sell_score"] >= 50].sort_values("sell_score", ascending=False)
            if not ss.empty:
                st.dataframe(ss[["コード","銘柄名","現在値","RSI","MACD状態","勢い","パターン","sell_target"]], hide_index=True)
            else: st.info("空売りチャンスなし (相場が強いです)")

