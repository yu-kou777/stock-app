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
# 🧠 精密分析ロジック (MACD + RSI + 反転フロア)
# ==========================================
def get_swing_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 60: return None
        curr_price = int(hist["Close"].iloc[-1])
        if not (min_p <= curr_price <= max_p): return None

        # 1. 指標計算 (MACD)
        ema12 = hist['Close'].ewm(span=12, adjust=False).mean()
        ema26 = hist['Close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        golden_cross = (macd.iloc[-2] < signal.iloc[-2]) and (macd.iloc[-1] > signal.iloc[-1])
        dead_cross = (macd.iloc[-2] > signal.iloc[-2]) and (macd.iloc[-1] < signal.iloc[-1])

        # 2. 指標計算 (RSI)
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]

        # 3. 反転フロア (BB-2σ & 60日安値)
        ma20 = hist['Close'].rolling(20).mean()
        std20 = hist['Close'].rolling(20).std()
        floor = max(int(ma20.iloc[-1] - (std20.iloc[-1] * 2)), int(hist['Low'].tail(60).min()))
        entry_target = int(floor * 1.01)

        # 4. 判定フラグ
        earn_date = scrape_earnings_date(ticker)
        days_to_earn = (earn_date - datetime.now().date()).days if earn_date else 999
        is_risk = (0 <= days_to_earn <= 3) # 決算3日前は盾発動
        
        # 💀 決算スナイパー (空売り)
        is_earnings_short = (0 <= days_to_earn <= 14) and (rsi > 70 or (curr_price > ma20.iloc[-1]*1.07))
        
        # スコア判定 (RSI × MACD 複合)
        buy_score, sell_score = 0, 0
        if not is_risk:
            if rsi < 45: buy_score += 30
            if golden_cross: buy_score += 40 # MACD転換を重視
            if rsi > 65: sell_score += 30
            if dead_cross: sell_score += 40

        return {
            "コード": ticker.replace(".T", ""), "銘柄名": name, "現在値": curr_price,
            "RSI": round(rsi, 1), "MACD": "GC(買い)" if golden_cross else "DC(売り)" if dead_cross else "継続",
            "フロア": floor, "エントリー目安": entry_target,
            "is_earnings_short": is_earnings_short, "buy_score": buy_score, "sell_score": sell_score,
            "利確目標": int(hist['High'].tail(25).max()), "損切目安": int(floor * 0.97),
            "決算": earn_date if earn_date else "未定", "is_risk": is_risk
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
            "利確目標": int(curr_price * 1.015), "損切目安": int(curr_price * 0.99),
            "time_str": last_dt.strftime('%m/%d %H:%M')
        }
    except: return None

# ==========================================
# 📱 アプリ表示 (日本語表記)
# ==========================================
st.set_page_config(page_title="最強株スキャナー・フルスペック版", layout="wide")
st.title("🦅 最強株スキャナー (護身・特攻モデル)")

code_in = st.text_input("銘柄コードを入力 (例: 6701)", "").strip()
if code_in:
    full_c = code_in + ".T" if ".T" not in code_in else code_in
    d_name = NAME_MAP.get(full_c, code_in)
    r = get_swing_analysis(full_c, d_name, 0, 10000000)
    d = get_day_analysis(full_c)
    
    if r:
        st.subheader(f"📊 {r['銘柄名']} ({r['コード']}) の精密診断")
        if r["is_risk"]:
            st.error(f"🛑 取引禁止！決算発表({r['決算']})が目前です。暴落リスクを回避してください。")
        
        t1, t2 = st.tabs(["🐢 スイング (日足)", "🐇 デイトレ (5分足)"])
        with t1:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("現在値", f"{r['現在値']}円")
                st.warning(f"🛡️ 反転予想フロア: {r['フロア']}円")
            with c2:
                st.success(f"指値(Entry)目安: {r['エントリー目安']}円")
                st.metric("利確目標", f"{r['利確目標']}円")
                st.metric("損切目安", f"{r['損切目安']}円", delta_color="inverse")
            with c3:
                st.metric("RSI", r['RSI'])
                st.write(f"MACD状態: **{r['MACD']}**")
                st.write(f"判定: **{'買い推奨 🚀' if r['buy_score']>=60 else '様子見 ☕'}**")

        with t2:
            if d:
                st.info(f"📅 データ時刻: {d['time_str']}")
                st.metric("5分足トレンド", d['勢い'], delta=f"{d['現在値']}円")
                st.write(f"🎯 瞬間利確: {d['利確目標']}円 / 🛑 瞬間損切: {d['損切目安']}円")

st.divider()

if st.button("全銘柄を一斉スキャニング", use_container_width=True):
    with ThreadPoolExecutor(max_workers=5) as ex:
        fs = [ex.submit(get_swing_analysis, t, n, 1000, 100000) for t, n in NAME_MAP.items()]
        ds = [f.result() for f in fs if f.result()]
    
    if ds:
        df = pd.DataFrame(ds)
        
        # 1. 💀 決算空売り
        shorts = df[df["is_earnings_short"] == True]
        if not shorts.empty:
            st.subheader("💀 決算前・過熱空売り候補 (信用売りチャンス)")
            st.dataframe(shorts[["コード","銘柄名","現在値","RSI","決算","利確目標"]].rename(columns={"利確目標":"空売り目標"}), hide_index=True)

        # 2. 🔥 買い推奨
        st.subheader("🔥 買い推奨 (現物・信用買い)")
        buys = df[df["buy_score"] >= 60].sort_values("buy_score", ascending=False)
        st.dataframe(buys[["コード","銘柄名","現在値","RSI","MACD","利確目標","損切目安"]], hide_index=True)

    else: st.warning("現在、推奨銘柄はありません。")
