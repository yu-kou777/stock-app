import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🛡️ 銘柄マスタ (主要・貸借銘柄)
# ==========================================
NAME_MAP = {
    "7203.T": "トヨタ", "9984.T": "SBG", "8306.T": "三菱UFJ", "6758.T": "ソニーG",
    "6861.T": "キーエンス", "6098.T": "リクルート", "8035.T": "東エレク", "4063.T": "信越化学",
    "7974.T": "任天堂", "9432.T": "NTT", "8058.T": "三菱商事", "8316.T": "三井住友",
    "8630.T": "SOMPO", "8725.T": "MS&AD", "6701.T": "NEC", "4901.T": "富士フイルム",
    "6702.T": "富士通", "4503.T": "アステラス", "6971.T": "京セラ", "7211.T": "三菱自",
    "8591.T": "オリックス", "3003.T": "ヒューリック", "2702.T": "マクドナルド",
    "7049.T": "識学", "9101.T": "日本郵船", "4661.T": "OLC", "5401.T": "日本製鉄",
    "9501.T": "東電HD", "7267.T": "ホンダ", "4502.T": "武田薬品", "8001.T": "伊藤忠",
    "8151.T": "東陽テクニカ"
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
        if res.status_code != 200: return None
        soup = BeautifulSoup(res.text, "html.parser")
        target = soup.find(string=re.compile(r"決算発表予定日"))
        if target:
            match = re.search(r"(\d{2}/\d{2}/\d{2})", str(target.parent.get_text()))
            if match: return datetime.strptime("20" + match.group(1), "%Y/%m/%d").date()
    except: pass
    return None

# ==========================================
# 🕯️ テクニカル判定 (スイング用)
# ==========================================
def detect_patterns(df, rsi):
    if len(df) < 25: return None, 0, "判定不能", "neutral"
    
    close = df['Close']
    high = df['High']
    low = df['Low']
    ma5 = close.rolling(5).mean().iloc[-1]
    curr_price = close.iloc[-1]
    
    if curr_price < ma5 * 0.995: trend = "📉下落"
    elif curr_price > ma5 * 1.005: trend = "📈上昇"
    else: trend = "☁️拮抗"

    # パターン検出 (簡略化)
    if rsi < 60:
        l = low.tail(15).values
        if l.min() == l[5:10].min() and l[0:5].min() > l[5:10].min():
            return "💎逆三尊", 80, trend, "buy"
        if (close.iloc[-3] < df['Open'].iloc[-3] and close.iloc[-1] > df['Open'].iloc[-1]):
            return "🌅明けの明星", 90, trend, "buy"
    
    if rsi > 40:
        h = high.tail(15).values
        if h.max() == h[5:10].max() and h[0:5].max() < h[5:10].max():
            return "💀三尊", 85, trend, "sell"
        if (close.iloc[-2] > df['Open'].iloc[-2] and close.iloc[-1] < df['Open'].iloc[-1]):
            return "📉陰の包み足", 70, trend, "sell"

    return None, 0, trend, "neutral"

# ==========================================
# 🐢 スイング分析 (日足)
# ==========================================
def get_swing_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 30: return None
        curr_price = int(hist["Close"].iloc[-1])
        
        if not (min_p <= curr_price <= max_p): return None

        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]

        res_line = int(hist['High'].tail(25).max())
        sup_line = int(hist['Low'].tail(25).min())

        # 目標株価
        buy_tp = res_line if res_line > curr_price * 1.01 else int(curr_price * 1.05)
        buy_sl = int(curr_price * 0.97)
        sell_tp = sup_line if sup_line < curr_price * 0.99 else int(curr_price * 0.95)
        sell_sl = int(curr_price * 1.03)

        earn_date = scrape_earnings_date(ticker)
        p_name, p_score, trend, sig_type = detect_patterns(hist, rsi)

        is_risk = False
        risk_msg = "✅安全"
        if earn_date:
            days = (earn_date - datetime.now().date()).days
            if 0 <= days <= 3:
                is_risk = True
                risk_msg = f"⚠️決算直前({earn_date})"

        buy_score, sell_score = 0, 0
        if not is_risk:
            if rsi < 60:
                if rsi < 35: buy_score += 40
                if "上昇" in trend: buy_score += 20
                if sig_type == "buy": buy_score += p_score
            if rsi > 40: 
                if rsi > 70: sell_score += 40
                if "下落" in trend: sell_score += 30
                if sig_type == "sell": sell_score += p_score

        return {
            "type": "SWING", "コード": ticker.replace(".T", ""), "銘柄名": name, 
            "現在値": curr_price, "RSI": round(rsi, 1), "勢い": trend, "パターン": p_name,
            "buy_score": buy_score, "buy_tp": buy_tp, "buy_sl": buy_sl,
            "sell_score": sell_score, "sell_tp": sell_tp, "sell_sl": sell_sl,
            "決算": risk_msg, "is_risk": is_risk, "res_line": res_line
        }
    except: return None

# ==========================================
# 🐇 デイトレ分析 (5分足)
# ==========================================
def get_day_analysis(ticker):
    try:
        stock = yf.Ticker(ticker)
        # 5日分の5分足を取得 (移動平均線のため)
        hist = stock.history(period="5d", interval="5m")
        if len(hist) < 30: return None
        
        curr_price = int(hist["Close"].iloc[-1])
        
        # RSI (5分足)
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]
        
        # 移動平均線 (20本=約100分)
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        
        # トレンド判定
        if curr_price > ma20 * 1.001: trend = "⚡短期上昇"
        elif curr_price < ma20 * 0.999: trend = "⚡短期下落"
        else: trend = "☁️短期もみ合い"

        # デイトレ戦略 (幅は狭く: 利確+1.5%, 損切-1%)
        buy_tp = int(curr_price * 1.015)
        buy_sl = int(curr_price * 0.99)
        sell_tp = int(curr_price * 0.985)
        sell_sl = int(curr_price * 1.01)

        # スコアリング
        b_score, s_score = 0, 0
        
        # 買い: RSI売られすぎ + 上昇トレンド
        if rsi < 30: b_score += 50
        elif rsi < 40: b_score += 20
        if curr_price > ma20: b_score += 30
        
        # 売り: RSI買われすぎ + 下落トレンド
        if rsi > 70: s_score += 50
        elif rsi > 60: s_score += 20
        if curr_price < ma20: s_score += 30

        return {
            "type": "DAY", "現在値": curr_price, "RSI": round(rsi, 1), "勢い": trend,
            "buy_score": b_score, "sell_score": s_score,
            "buy_tp": buy_tp, "buy_sl": buy_sl,
            "sell_tp": sell_tp, "sell_sl": sell_sl
        }
    except: return None

# ==========================================
# 📱 アプリ表示
# ==========================================
st.set_page_config(page_title="最強株スキャナー・デイトレ対応", layout="wide")
st.title("🦅 最強株スキャナー (スイング ＆ デイトレ)")

# --- 1. 個別診断 (スイング + デイトレ) ---
st.header("🔍 個別銘柄ピンポイント診断")
code_in = st.text_input("コード (例: 7203)", "").strip()

if code_in:
    full_c = code_in + ".T" if ".T" not in code_in else code_in
    d_name = NAME_MAP.get(full_c)
    if not d_name:
        try: d_name = yf.Ticker(full_c).info.get('longName', code_in)
        except: d_name = code_in
    
    with st.spinner("スイング＆デイトレのW分析中..."):
        # スイング分析 (日足)
        r_swing = get_swing_analysis(full_c, d_name, 0, 10000000)
        # デイトレ分析 (5分足)
        r_day = get_day_analysis(full_c)
    
    if r_swing:
        st.subheader(f"📊 {r_swing['銘柄名']} ({r_swing['コード']})")
        if r_swing["is_risk"]:
            st.error(f"🛑 {r_swing['決算']} のため、スイング取引は禁止です。")
        
        # タブで切り替え、または並べて表示
        tab1, tab2 = st.tabs(["🐢 スイング (数日向け)", "🐇 デイトレ (1日向け)"])
        
        with tab1: # スイング診断
            c1, c2, c3 = st.columns(3)
            with c1:
                if r_swing['buy_score'] >= 50: st.success("判定: 買い推奨 🚀")
                elif r_swing['sell_score'] >= 50: st.error("判定: 空売り推奨 📉")
                else: st.info("判定: 様子見 ☕")
                st.metric("現在値", f"{r_swing['現在値']}円", delta=r_swing['勢い'])
            with c2:
                st.write("**買い戦略**")
                st.write(f"🎯 利確: {r_swing['buy_tp']}円")
                st.write(f"🛑 損切: {r_swing['buy_sl']}円 (-3%)")
            with c3:
                st.write(f"**RSI(日足):** {r_swing['RSI']}")
                st.write(f"**サイン:** {r_swing['パターン'] if r_swing['パターン'] else 'なし'}")
                st.caption(f"決算: {r_swing['決算']}")

        with tab2: # デイトレ診断
            if r_day:
                d1, d2, d3 = st.columns(3)
                with d1:
                    if r_day['buy_score'] >= 50: st.success("瞬間判定: 今が買い時! 🔥")
                    elif r_day['sell_score'] >= 50: st.error("瞬間判定: 今が売り時! ❄️")
                    else: st.info("瞬間判定: チャンス待ち ⏳")
                    st.metric("5分足トレンド", r_day['勢い'])
                with d2:
                    st.write("**デイトレ戦略 (幅狭め)**")
                    st.write(f"🎯 利確: {r_day['buy_tp']}円 (+1.5%)")
                    st.write(f"🛑 損切: {r_day['buy_sl']}円 (-1.0%)")
                with d3:
                    st.metric("RSI (5分足)", r_day['RSI'])
                    st.caption("※5分足データを使用")
            else:
                st.warning("デイトレ用の詳細データが取得できませんでした (市場終了後など)")

    else: st.error("データ取得失敗")

st.divider()

# --- 2. 一括スキャン (スイング用) ---
st.header("🚀 市場全体スキャン (スイング)")
col_filt1, col_filt2 = st.columns(2)
with col_filt1: p_min_input = st.number_input("最低価格 (円)", value=1000, step=1000)
with col_filt2: p_max_input = st.number_input("最高価格 (円)", value=10000, step=1000)

if st.button("条件でスキャン開始", use_container_width=True):
    with st.spinner(f"対象銘柄を抽出中..."):
        with ThreadPoolExecutor(max_workers=5) as ex:
            fs = [ex.submit(get_swing_analysis, t, n, p_min_input, p_max_input) for t, n in NAME_MAP.items()]
            ds = [f.result() for f in fs if f.result()]
    
    if ds:
        df = pd.DataFrame(ds)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🔥 買い推奨 (Swing)")
            bs = df[df["buy_score"] >= 50].sort_values("buy_score", ascending=False)
            if not bs.empty:
                st.dataframe(bs[["コード","銘柄名","現在値","buy_tp","buy_sl","勢い"]].rename(columns={"buy_tp":"利確","buy_sl":"損切"}), hide_index=True)
            else: st.info("なし")
        with c2:
            st.subheader("📉 空売り推奨 (Swing)")
            ss = df[df["sell_score"] >= 50].sort_values("sell_score", ascending=False)
            if not ss.empty:
                st.dataframe(ss[["コード","銘柄名","現在値","sell_tp","sell_sl","勢い"]].rename(columns={"sell_tp":"利確","sell_sl":"損切"}), hide_index=True)
            else: st.info("なし")
    else: st.warning("該当なし")

