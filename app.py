import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🛡️ 銘柄マスタ (アイさんの監視リスト)
# ==========================================
NAME_MAP = {
    "7203.T": "トヨタ", "9984.T": "SBG", "8306.T": "三菱UFJ", "6758.T": "ソニーG",
    "6098.T": "リクルート", "8035.T": "東エレク", "4063.T": "信越化学", "7974.T": "任天堂",
    "6701.T": "NEC", "4901.T": "富士フイルム", "6330.T": "東洋エンジ", "5406.T": "神戸鋼",
    "8151.T": "東陽テク", "9101.T": "日本郵船", "4661.T": "OLC", "5401.T": "日本製鉄",
    "7267.T": "ホンダ", "9432.T": "NTT"
}

# ==========================================
# 🌐 決算日チェック
# ==========================================
def scrape_earnings_date(code):
    clean_code = code.replace(".T", "")
    url = f"https://kabutan.jp/stock/finance?code={clean_code}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        target = soup.find(string=re.compile(r"決算発表予定日"))
        if target:
            match = re.search(r"(\d{2}/\d{2}/\d{2})", str(target.parent.get_text()))
            if match: return datetime.strptime("20" + match.group(1), "%Y/%m/%d").date()
    except: pass
    return None

# ==========================================
# 🕯️ テクニカル判定 (反転・継続・保ち合い)
# ==========================================
def detect_swing_patterns(df, rsi):
    if len(df) < 30: return None, 0, "判定不能", "neutral"
    
    close = df['Close']
    high = df['High']
    low = df['Low']
    curr_price = close.iloc[-1]
    ma5 = close.rolling(5).mean().iloc[-1]
    
    trend = "📈上昇" if curr_price > ma5 * 1.005 else "📉下落" if curr_price < ma5 * 0.995 else "☁️拮抗"

    # --- 1. 継続サイン：フラッグ (急騰後の調整) ---
    # 直近5日間で高値・安値が緩やかに切り下がっているが、ボラが小さい
    if all(high.iloc[i] < high.iloc[i-1] for i in range(-3, 0)) and \
       all(low.iloc[i] < low.iloc[i-1] for i in range(-3, 0)) and \
       (high.tail(5).max() - low.tail(5).min()) < (curr_price * 0.05):
        return "🚩フラッグ(上昇中継)", 75, trend, "buy"

    # --- 2. 保ち合い：スクエア (パワー蓄積) ---
    # 直近10日間の値幅が3%以内
    price_range = (high.tail(10).max() - low.tail(10).min()) / curr_price
    if price_range < 0.03:
        return "📦スクエア(保ち合い)", 65, trend, "neutral"

    # --- 3. 反転サイン (既存) ---
    if rsi < 60:
        # 逆三尊
        l = low.tail(15).values
        if l.min() == l[5:10].min() and l[0:5].min() > l[5:10].min() and l[10:15].min() > l[5:10].min():
            return "💎逆三尊", 80, trend, "buy"
        # 明けの明星
        if (close.iloc[-3] < df['Open'].iloc[-3] and close.iloc[-1] > df['Open'].iloc[-1]):
            return "🌅明けの明星", 90, trend, "buy"
        # 三空叩き込み
        if all(df['High'].iloc[i] < df['Low'].iloc[i-1] for i in range(-3, 0)):
            return "🔥三空叩き込み", 100, trend, "buy"

    if rsi > 40:
        # 三尊
        h = high.tail(15).values
        if h.max() == h[5:10].max() and h[0:5].max() < h[5:10].max() and h[10:15].max() < h[5:10].max():
            return "💀三尊(天井)", 85, trend, "sell"
        # 陰の包み足
        if (close.iloc[-2] > df['Open'].iloc[-2] and close.iloc[-1] < df['Open'].iloc[-1] and close.iloc[-1] < df['Open'].iloc[-2]):
            return "📉陰の包み足", 70, trend, "sell"

    return None, 0, trend, "neutral"

# ==========================================
# 🧠 精密分析ロジック
# ==========================================
def get_swing_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 60: return None
        curr_price = int(hist["Close"].iloc[-1])
        if not (min_p <= curr_price <= max_p): return None

        # 床の計算 (反転予測)
        ma20 = hist['Close'].rolling(20).mean()
        std20 = hist['Close'].rolling(20).std()
        floor = max(int(ma20.iloc[-1] - (std20.iloc[-1] * 2)), int(hist['Low'].tail(60).min()))
        entry_target = int(floor * 1.01)

        # 指標
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]
        
        # 判定
        p_name, p_score, trend, sig_type = detect_swing_patterns(hist, rsi)
        earn_date = scrape_earnings_date(ticker)
        
        # フラグ
        is_ambush = (curr_price <= floor * 1.03) and (rsi < 40)
        days_to_earn = (earn_date - datetime.now().date()).days if earn_date else 999
        is_risk = (0 <= days_to_earn <= 3)

        buy_score, sell_score = 0, 0
        if not is_risk:
            if rsi < 60:
                if rsi < 35: buy_score += 40
                if sig_type == "buy": buy_score += p_score
            if rsi > 65: sell_score += 40

        return {
            "コード": ticker.replace(".T", ""), "銘柄名": name, "現在値": curr_price,
            "RSI": round(rsi, 1), "フロア": floor, "エントリー": entry_target,
            "パターン": p_name if p_name else "-", "勢い": trend,
            "is_ambush": is_ambush, "buy_score": buy_score, "sell_score": sell_score,
            "buy_tp": int(hist['High'].tail(25).max()), "buy_sl": int(floor * 0.97),
            "決算": earn_date if earn_date else "-", "is_risk": is_risk
        }
    except: return None

# ==========================================
# 🐇 デイトレ分析 (5分足)
# ==========================================
def get_day_analysis(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d", interval="5m")
        if len(hist) < 20: return None
        last_dt = hist.index[-1].astimezone(timezone(timedelta(hours=9)))
        curr_price = int(hist["Close"].iloc[-1])
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        
        return {
            "現在値": curr_price, "勢い": "⚡上昇" if curr_price > ma20 else "⚡下落",
            "buy_tp": int(curr_price * 1.015), "buy_sl": int(curr_price * 0.99),
            "time_str": last_dt.strftime('%m/%d %H:%M')
        }
    except: return None

# ==========================================
# 📱 UI表示
# ==========================================
st.set_page_config(page_title="最強株スキャナー・最終形態", layout="wide")
st.title("🦅 最強株スキャナー (全方位・高精度モデル)")

code_in = st.text_input("コードを入力 (例: 6701)", "").strip()
if code_in:
    full_c = code_in + ".T" if ".T" not in code_in else code_in
    d_name = NAME_MAP.get(full_c, code_in)
    r_swing = get_swing_analysis(full_c, d_name, 0, 10000000)
    r_day = get_day_analysis(full_c)
    
    if r_swing:
        st.subheader(f"📊 {r_swing['銘柄名']} ({r_swing['コード']})")
        t1, t2 = st.tabs(["🐢 スイング (反転・継続)", "🐇 デイトレ (瞬間)"])
        with t1:
            if r_swing["is_risk"]: st.error(f"🛑 決算({r_swing['決算']})直前につき取引停止")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("現在値", f"{r_swing['現在値']}円", delta=r_swing['勢い'])
                st.warning(f"🛡️ 反転フロア: {r_swing['フロア']}円")
            with c2:
                st.markdown("##### 🏹 戦略")
                st.success(f"エントリー目安: {r_swing['エントリー']}円")
                st.write(f"🎯 利確目標: {r_swing['buy_tp']}円")
                st.metric("損切(Stop)", f"{r_swing['buy_sl']}円", delta_color="inverse")
            with c3:
                st.metric("RSI(日足)", r_swing['RSI'])
                st.write(f"**出現サイン:** {r_swing['パターン']}")
        with t2:
            if r_day:
                st.info(f"📅 データ日時: {r_day['time_str']}")
                st.metric("デイトレ勢い", r_day['勢い'], delta=f"{r_day['現在値']}円")
                st.write(f"🎯 瞬間利確: {r_day['buy_tp']}円 / 🛑 瞬間損切: {r_day['buy_sl']}円")

st.divider()

if st.button("全ロジックで一斉スキャン開始", use_container_width=True):
    with ThreadPoolExecutor(max_workers=5) as ex:
        fs = [ex.submit(get_swing_analysis, t, n, 1000, 100000) for t, n in NAME_MAP.items()]
        ds = [f.result() for f in fs if f.result()]
    if ds:
        df = pd.DataFrame(ds)
        st.subheader("🏹 反転・待ち伏せ候補")
        st.dataframe(df[df["is_ambush"] == True][["コード","銘柄名","現在値","フロア","エントリー","RSI"]], hide_index=True)
        st.subheader("🔥 買い推奨 (スイング・継続・ブレイク)")
        st.dataframe(df[df["buy_score"] >= 50][["コード","銘柄名","現在値","RSI","パターン","buy_tp","buy_sl"]], hide_index=True)
    else: st.warning("該当なし")

