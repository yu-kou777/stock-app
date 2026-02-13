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
# 🌐 決算日チェック (株探連動)
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
# 🕯️ テクニカル判定ロジック (全シグナル網羅)
# ==========================================
def detect_complex_patterns(df, rsi):
    if len(df) < 30: return None, 0, "neutral"
    close, high, low, open_p = df['Close'], df['High'], df['Low'], df['Open']
    curr_price = close.iloc[-1]
    ma5 = close.rolling(5).mean().iloc[-1]
    
    trend = "📈上昇" if curr_price > ma5 * 1.005 else "📉下落" if curr_price < ma5 * 0.995 else "☁️拮抗"

    # --- 1. 継続サイン：上昇フラッグ ---
    if all(high.iloc[i] < high.iloc[i-1] for i in range(-3, 0)) and \
       (high.tail(5).max() - low.tail(5).min()) < (curr_price * 0.04):
        return "🚩上昇フラッグ", 75, trend, "buy"

    # --- 2. 保ち合い：スクエア ---
    if (high.tail(10).max() - low.tail(10).min()) / curr_price < 0.03:
        return "📦スクエア(保ち合い)", 65, trend, "neutral"

    # --- 3. 反転買いサイン ---
    if rsi < 60:
        # 三空叩き込み
        if all(df['High'].iloc[i] < df['Low'].iloc[i-1] for i in range(-3, 0)): return "🔥三空叩き込み", 100, trend, "buy"
        # 明けの明星
        if (close.iloc[-3] < open_p.iloc[-3] and close.iloc[-1] > open_p.iloc[-1]): return "🌅明けの明星", 90, trend, "buy"
        # 逆三尊
        l_vals = low.tail(15).values
        if l_vals.min() == l_vals[5:10].min() and l_vals[0:5].min() > l_vals[5:10].min(): return "💎逆三尊", 80, trend, "buy"

    # --- 4. 売りサイン ---
    if rsi > 40:
        # 三尊 (天井)
        h_vals = high.tail(15).values
        if h_vals.max() == h_vals[5:10].max() and h_vals[0:5].max() < h_vals[5:10].max(): return "💀三尊(天井)", 85, trend, "sell"
        # 陰の包み足
        if (close.iloc[-2] > open_p.iloc[-2] and close.iloc[-1] < open_p.iloc[-2]): return "📉陰の包み足", 70, trend, "sell"

    return None, 0, trend, "neutral"

# ==========================================
# 🧠 精密分析ロジック (スイング・決算・戦略数値)
# ==========================================
def get_swing_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 60: return None
        curr_price = int(hist["Close"].iloc[-1])
        if not (min_p <= curr_price <= max_p): return None

        # 指標計算
        ma20 = hist['Close'].rolling(20).mean()
        std20 = hist['Close'].rolling(20).std()
        floor = max(int(ma20.iloc[-1] - (std20.iloc[-1] * 2)), int(hist['Low'].tail(60).min()))
        ceiling = min(int(ma20.iloc[-1] + (std20.iloc[-1] * 2)), int(hist['High'].tail(60).max()))

        ema12 = hist['Close'].ewm(span=12, adjust=False).mean()
        ema26 = hist['Close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        golden_cross = (macd.iloc[-2] < signal.iloc[-2]) and (macd.iloc[-1] > signal.iloc[-1])
        dead_cross = (macd.iloc[-2] > signal.iloc[-2]) and (macd.iloc[-1] < signal.iloc[-1])

        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]

        # パターン・決算
        p_name, p_score, trend, sig_type = detect_complex_patterns(hist, rsi)
        earn_date = scrape_earnings_date(ticker)
        days = (earn_date - datetime.now().date()).days if earn_date else 999
        
        is_risk = (0 <= days <= 3) # 決算ガード
        is_earn_short = (0 <= days <= 14) and (rsi > 70 or (curr_price > ma20.iloc[-1] * 1.07)) # 決算スナイパー

        # スコアリング
        buy_score, sell_score = 0, 0
        if not is_risk:
            if rsi < 50: buy_score += 20
            if golden_cross: buy_score += 40
            if sig_type == "buy": buy_score += p_score
            if rsi > 65: sell_score += 20
            if dead_cross: sell_score += 40
            if sig_type == "sell": sell_score += p_score

        return {
            "コード": ticker.replace(".T", ""), "銘柄名": name, "現在値": curr_price,
            "RSI": round(rsi, 1), "MACD": "GC(買い)" if golden_cross else "DC(売り)" if dead_cross else "継続",
            "勢い": trend, "パターン": p_name if p_name else "なし",
            "買いエントリー": int(floor * 1.01), "買い利確": int(hist['High'].tail(25).max()), "買い損切": int(floor * 0.97),
            "売りエントリー": int(ceiling * 0.99), "売り利確": int(hist['Low'].tail(25).min()), "売り損切": int(ceiling * 1.03),
            "決算": earn_date if earn_date else "未定", "is_risk": is_risk, "is_earn_short": is_earn_short,
            "buy_score": buy_score, "sell_score": sell_score, "フロア": floor
        }
    except: return None

# ==========================================
# 🐇 デイトレ分析 (5分足)
# ==========================================
def get_day_analysis(ticker):
    try:
        hist = yf.Ticker(ticker).history(period="5d", interval="5m")
        if len(hist) < 20: return None
        curr = int(hist["Close"].iloc[-1])
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        return {
            "現在値": curr, "勢い": "⚡上昇" if curr > ma20 else "⚡下落",
            "利確": int(curr * 1.015), "損切": int(curr * 0.99),
            "時刻": hist.index[-1].astimezone(timezone(timedelta(hours=9))).strftime('%H:%M')
        }
    except: return None

# ==========================================
# 📱 アプリ画面表示 (完全日本語化)
# ==========================================
st.set_page_config(page_title="最強株スキャナー・最終形態", layout="wide")
st.title("🦅 最強株スキャナー (全方位・高精度モデル)")

code_in = st.text_input("銘柄コードを入力 (例: 6701)", "").strip()
if code_in:
    full_c = code_in + ".T" if ".T" not in code_in else code_in
    r = get_swing_analysis(full_c, NAME_MAP.get(full_c, code_in), 0, 10000000)
    d = get_day_analysis(full_c)
    if r:
        if r["is_risk"]: st.error(f"🛑 決算発表({r['決算']})目前につき取引禁止 (防御発動)")
        elif r["is_earn_short"]: st.warning(f"💀 決算スナイパー：異常な過熱を検出。空売りのチャンスです。")
        
        tab1, tab2 = st.tabs(["🐢 スイング (日足分析)", "🐇 デイトレ (5分足分析)"])
        with tab1:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("現在値", f"{r['現在値']}円", delta=r['勢い'])
                st.info(f"🛡️ 反転予想フロア: {r['フロア']}円")
            with c2:
                st.success(f"買い指値(Entry): {r['買いエントリー']}円")
                st.write(f"🎯 利確: {r['買い利確']}円 / 🛑 損切: {r['買い損切']}円")
                st.error(f"売り指値(Entry): {r['売りエントリー']}円")
                st.write(f"🎯 利確: {r['売り利確']}円 / 🛑 損切: {r['売り損切']}円")
            with c3:
                st.write(f"判定: **{'買い推奨 🚀' if r['buy_score']>=70 else '空売り推奨 📉' if r['sell_score']>=70 else '様子見 ☕'}**")
                st.write(f"出現サイン: **{r['パターン']}**")
                st.write(f"MACD: {r['MACD']} / RSI: {r['RSI']}")
        with tab2:
            if d:
                st.metric(f"5分足勢い ({d['時刻']})", d['勢い'], delta=f"{d['現在値']}円")
                st.write(f"🎯 瞬間利確: {d['利確']}円 / 🛑 瞬間損切: {d['損切']}円")

st.divider()

# --- 一括スキャンセクション ---
st.header("🚀 市場全体スキャン (価格帯フィルタ)")
col_f1, col_f2 = st.columns(2)
with col_f1: p_min = st.number_input("最低価格", value=1000)
with col_f2: p_max = st.number_input("最高価格", value=100000)

if st.button("全ロジックで一斉スキャン開始", use_container_width=True):
    with ThreadPoolExecutor(max_workers=5) as ex:
        fs = [ex.submit(get_swing_analysis, t, n, p_min, p_max) for t, n in NAME_MAP.items()]
        ds = [f.result() for f in fs if f.result()]
    if ds:
        df = pd.DataFrame(ds)
        
        # 💀 決算スナイパー
        shorts_sniper = df[df["is_earn_short"] == True]
        if not shorts_sniper.empty:
            st.subheader("💀 決算前・過熱空売り候補 (矛)")
            st.dataframe(shorts_sniper[["コード","銘柄名","現在値","RSI","決算","売りエントリー","売り利確"]].rename(columns={"売りエントリー":"指値目安","売り利確":"目標価格"}), hide_index=True)

        # 🔥 買い推奨
        st.subheader("🔥 買い推奨 (現物・信用買い)")
        buys = df[df["buy_score"] >= 70].sort_values("buy_score", ascending=False)
        st.dataframe(buys[["コード","銘柄名","現在値","RSI","MACD","パターン","買いエントリー","買い利確","買い損切"]].rename(columns={"買いエントリー":"指値目安","買い利確":"目標価格","買い損切":"損切目安"}), hide_index=True)

        # 📉 空売り推奨
        st.subheader("📉 空売り推奨 (信用売り)")
        shorts = df[df["sell_score"] >= 70].sort_values("sell_score", ascending=False)
        st.dataframe(shorts[["コード","銘柄名","現在値","RSI","MACD","パターン","売りエントリー","売り利確","売り損切"]].rename(columns={"売りエントリー":"指値目安","売り利確":"目標価格","売り損切":"損切目安"}), hide_index=True)
    else: st.warning("該当なし")
