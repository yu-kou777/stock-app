import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🛡️ 銘柄マスタ
# ==========================================
NAME_MAP = {
    "7203.T": "トヨタ", "9984.T": "SBG", "8306.T": "三菱UFJ", "6758.T": "ソニーG",
    "6098.T": "リクルート", "8035.T": "東エレク", "4063.T": "信越化学", "7974.T": "任天堂",
    "6701.T": "NEC", "4901.T": "富士フイルム", "6330.T": "東洋エンジ", "5406.T": "神戸鋼",
    "8151.T": "東陽テク", "9101.T": "日本郵船", "4661.T": "OLC", "5401.T": "日本製鉄"
}

# ==========================================
# 🌐 決算日チェック (株探)
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
# 🕯️ パターン判定 (反転・継続・保ち合い)
# ==========================================
def detect_complex_patterns(df, rsi):
    if len(df) < 30: return None, 0, "neutral"
    close, high, low, open_p = df['Close'], df['High'], df['Low'], df['Open']
    curr_price = close.iloc[-1]

    # --- 1. 継続：フラッグ ---
    if all(high.iloc[i] < high.iloc[i-1] for i in range(-3, 0)) and \
       (high.tail(5).max() - low.tail(5).min()) < (curr_price * 0.04):
        return "🚩フラッグ(上昇中継)", 75, "buy"

    # --- 2. 保ち合い：スクエア ---
    if (high.tail(10).max() - low.tail(10).min()) / curr_price < 0.03:
        return "📦スクエア(保ち合い)", 65, "neutral"

    # --- 3. 反転：三空 / 明けの明星 / 逆三尊 ---
    if rsi < 60:
        if all(high.iloc[i] < low.iloc[i-1] for i in range(-3, 0)): return "🔥三空叩き込み", 100, "buy"
        if (close.iloc[-3] < open_p.iloc[-3] and close.iloc[-1] > open_p.iloc[-1]): return "🌅明けの明星", 90, "buy"
        l_vals = low.tail(15).values
        if l_vals.min() == l_vals[5:10].min() and l_vals[0:5].min() > l_vals[5:10].min(): return "💎逆三尊", 80, "buy"

    # --- 4. 売り：三尊 / 陰の包み足 ---
    if rsi > 40:
        h_vals = high.tail(15).values
        if h_vals.max() == h_vals[5:10].max() and h_vals[0:5].max() < h_vals[5:10].max(): return "💀三尊(天井)", 85, "sell"
        if (close.iloc[-2] > open_p.iloc[-2] and close.iloc[-1] < open_p.iloc[-2]): return "📉陰の包み足", 70, "sell"

    return None, 0, "neutral"

# ==========================================
# 🧠 精密分析ロジック
# ==========================================
def get_analysis_data(ticker, name, min_p=0, max_p=10000000):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y") # 余裕を持って1年分取得
        if len(hist) < 60: return None
        curr_price = int(hist["Close"].iloc[-1])
        if not (min_p <= curr_price <= max_p): return None

        # MACD
        ema12 = hist['Close'].ewm(span=12, adjust=False).mean()
        ema26 = hist['Close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        golden_cross = (macd.iloc[-2] < signal.iloc[-2]) and (macd.iloc[-1] > signal.iloc[-1])
        dead_cross = (macd.iloc[-2] > signal.iloc[-2]) and (macd.iloc[-1] < signal.iloc[-1])

        # RSI
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]

        # 床 (反転予測)
        ma20 = hist['Close'].rolling(20).mean()
        std20 = hist['Close'].rolling(20).std()
        floor = max(int(ma20.iloc[-1] - (std20.iloc[-1] * 2)), int(hist['Low'].tail(60).min()))

        # パターン
        p_name, p_score, sig_type = detect_complex_patterns(hist, rsi)
        
        # 決算リスク
        earn_date = scrape_earnings_date(ticker)
        days = (earn_date - datetime.now().date()).days if earn_date else 999
        is_risk = (0 <= days <= 3)
        is_earn_short = (0 <= days <= 14) and (rsi > 70 or curr_price > ma20.iloc[-1] * 1.07)

        # スコア (MACD GCを重視)
        buy_score = 0
        if not is_risk:
            if rsi < 50: buy_score += 20
            if golden_cross: buy_score += 50
            if sig_type == "buy": buy_score += p_score

        return {
            "コード": ticker.replace(".T", ""), "銘柄名": name, "現在値": curr_price,
            "RSI": round(rsi, 1), "MACD": "GC(買い)" if golden_cross else "DC(売り)" if dead_cross else "継続",
            "フロア": floor, "エントリー": int(floor * 1.01),
            "パターン": p_name if p_name else "なし", "利確目標": int(hist['High'].tail(25).max()),
            "損切目安": int(floor * 0.97), "決算": earn_date if earn_date else "未定",
            "is_risk": is_risk, "is_earn_short": is_earn_short, "buy_score": buy_score
        }
    except: return None

# ==========================================
# 🐇 デイトレ用 (5分足)
# ==========================================
def get_day_data(ticker):
    try:
        hist = yf.Ticker(ticker).history(period="5d", interval="5m")
        if len(hist) < 20: return None
        last_dt = hist.index[-1].astimezone(timezone(timedelta(hours=9)))
        curr = int(hist["Close"].iloc[-1])
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        return {
            "現在値": curr, "勢い": "⚡上昇" if curr > ma20 else "⚡下落",
            "利確": int(curr * 1.015), "損切": int(curr * 0.99), "時刻": last_dt.strftime('%H:%M')
        }
    except: return None

# ==========================================
# 📱 アプリ画面
# ==========================================
st.set_page_config(page_title="最強株スキャナー・真・最終版", layout="wide")
st.title("🦅 最強株スキャナー (全機能・全シグナル統合版)")

code_in = st.text_input("銘柄コードを入力", "").strip()
if code_in:
    full_c = code_in + ".T" if ".T" not in code_in else code_in
    res = get_analysis_data(full_c, NAME_MAP.get(full_c, code_in))
    day = get_day_data(full_c)
    if res:
        if res["is_risk"]: st.error(f"🛑 取引禁止：決算発表({res['決算']})が直前です。")
        elif res["is_earn_short"]: st.warning(f"💀 空売り注目：決算前の異常な過熱が検出されました。")
        
        tab1, tab2 = st.tabs(["🐢 スイング (反転・継続)", "🐇 デイトレ (瞬間)"])
        with tab1:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("現在値", f"{res['現在値']}円")
                st.info(f"🛡️ 反転予想フロア: {res['フロア']}円")
            with col2:
                st.success(f"指値目安: {res['エントリー']}円")
                st.metric("利確目標", f"{res['利確目標']}円")
                st.metric("損切目安", f"{res['損切目安']}円", delta_color="inverse")
            with col3:
                st.write(f"判定: **{'買い推奨 🚀' if res['buy_score']>=70 else '様子見 ☕'}**")
                st.write(f"出現サイン: **{res['パターン']}**")
                st.write(f"MACD: **{res['MACD']}** / RSI: **{res['RSI']}**")
        with tab2:
            if day:
                st.metric(f"5分足勢い ({day['時刻']})", day['勢い'], delta=f"{day['現在値']}円")
                st.write(f"🎯 瞬間利確: {day['利確']}円 / 🛑 瞬間損切: {day['損切']}円")

st.divider()

if st.button("全銘柄を一斉スキャニング", use_container_width=True):
    with ThreadPoolExecutor(max_workers=5) as ex:
        fs = [ex.submit(get_analysis_data, t, n) for t, n in NAME_MAP.items()]
        ds = [f.result() for f in fs if f.result()]
    if ds:
        df = pd.DataFrame(ds)
        # 💀 決算空売り
        shorts = df[df["is_earn_short"] == True]
        if not shorts.empty:
            st.subheader("💀 決算前・過熱空売り候補")
            st.dataframe(shorts[["コード","銘柄名","現在値","RSI","決算","利確目標"]].rename(columns={"利確目標":"空売り目標"}), hide_index=True)
        # 🔥 買い推奨
        st.subheader("🔥 買い推奨 (現物・信用買い)")
        buys = df[df["buy_score"] >= 70].sort_values("buy_score", ascending=False)
        st.dataframe(buys[["コード","銘柄名","現在値","RSI","MACD","パターン","利確目標","損切目安"]], hide_index=True)
    else: st.warning("現在、推奨銘柄はありません。")
