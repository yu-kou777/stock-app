import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🛡️ 銘柄マスタ
# ==========================================
NAME_MAP = {
    "7203.T": "トヨタ", "9984.T": "SBG", "8306.T": "三菱UFJ", "6758.T": "ソニーG",
    "6861.T": "キーエンス", "6098.T": "リクルート", "8035.T": "東エレク", "4063.T": "信越化学",
    "7974.T": "任天堂", "9432.T": "NTT", "8058.T": "三菱商事", "8316.T": "三井住友",
    "8630.T": "SOMPO", "8725.T": "MS&AD", "6701.T": "NEC", "4901.T": "富士フイルム",
    "6702.T": "富士通", "4503.T": "アステラス", "6971.T": "京セラ", "7211.T": "三菱自",
    "8591.T": "オリックス", "3003.T": "ヒューリック", "2702.T": "マクドナルド",
    "7049.T": "識学", "9101.T": "日本郵船", "4661.T": "OLC", "5401.T": "日本製鉄",
    "9501.T": "東電HD", "7267.T": "ホンダ", "4502.T": "武田薬品", "8001.T": "伊藤忠"
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
# 🕯️ テクニカル & パターン判定
# ==========================================
def detect_patterns(df, rsi):
    if len(df) < 25: return None, 0, "判定不能", "neutral"
    
    close = df['Close']
    high = df['High']
    low = df['Low']
    ma5 = close.rolling(5).mean().iloc[-1]
    curr_price = close.iloc[-1]
    
    # 勢い判定
    if curr_price < ma5 * 0.995: trend = "📉下落(売り)"
    elif curr_price > ma5 * 1.005: trend = "📈上昇(買い)"
    else: trend = "☁️拮抗"

    # 買いパターン
    if rsi < 60:
        l = low.tail(15).values
        if l.min() == l[5:10].min() and l[0:5].min() > l[5:10].min() and l[10:15].min() > l[5:10].min():
            return "💎逆三尊", 80, trend, "buy"
        if (close.iloc[-3] < df['Open'].iloc[-3] and 
            abs(close.iloc[-2]-df['Open'].iloc[-2]) < abs(close.iloc[-3]-df['Open'].iloc[-3])*0.3 and 
            close.iloc[-1] > df['Open'].iloc[-1]):
            return "🌅明けの明星", 90, trend, "buy"

    # 売りパターン
    if rsi > 40:
        h = high.tail(15).values
        if h.max() == h[5:10].max() and h[0:5].max() < h[5:10].max() and h[10:15].max() < h[5:10].max():
            return "💀三尊(天井)", 85, trend, "sell"
        if (close.iloc[-2] > df['Open'].iloc[-2] and 
            close.iloc[-1] < df['Open'].iloc[-1] and 
            close.iloc[-1] < df['Open'].iloc[-2]):
            return "📉陰の包み足", 70, trend, "sell"

    return None, 0, trend, "neutral"

# ==========================================
# 🧠 分析ロジック
# ==========================================
def get_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 30: return None
        curr_price = hist["Close"].iloc[-1]
        
        # 価格帯フィルター
        if not (min_p <= curr_price <= max_p): return None

        # RSI計算
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]

        # MACD計算
        ema12 = hist['Close'].ewm(span=12, adjust=False).mean()
        ema26 = hist['Close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        golden_cross = (macd.iloc[-2] < signal.iloc[-2]) and (macd.iloc[-1] > signal.iloc[-1])
        dead_cross = (macd.iloc[-2] > signal.iloc[-2]) and (macd.iloc[-1] < signal.iloc[-1])
        
        # --- 戦略数値 (利確・損切) ---
        res_line = int(hist['High'].tail(25).max()) # 抵抗線
        sup_line = int(hist['Low'].tail(25).min())  # 支持線

        # 買い目標 (利確: +5% or 抵抗線 / 損切: -3%)
        if res_line < curr_price * 1.01:
            buy_tp = int(curr_price * 1.05)
        else:
            buy_tp = res_line
        buy_sl = int(curr_price * 0.97)

        # 売り目標 (利確: -5% or 支持線 / 損切: +3%)
        if sup_line > curr_price * 0.99:
            sell_tp = int(curr_price * 0.95)
        else:
            sell_tp = sup_line
        sell_sl = int(curr_price * 1.03)

        earn_date = scrape_earnings_date(ticker)
        p_name, p_score, trend, sig_type = detect_patterns(hist, rsi)

        # 決算リスク判定
        is_risk = False
        risk_msg = "✅安全"
        if earn_date:
            days = (earn_date - datetime.now().date()).days
            if 0 <= days <= 3:
                is_risk = True
                risk_msg = f"⚠️決算直前({earn_date})"

        buy_score, sell_score = 0, 0
        
        if not is_risk:
            # 買いスコア
            if rsi < 60:
                if rsi < 35: buy_score += 40
                if golden_cross: buy_score += 30
                if "上昇" in trend: buy_score += 20
                if sig_type == "buy": buy_score += p_score

            # 売りスコア
            if rsi > 40: 
                if rsi > 70: sell_score += 40
                if dead_cross: sell_score += 40
                if "下落" in trend: sell_score += 30
                if sig_type == "sell": sell_score += p_score

        return {
            "コード": ticker.replace(".T", ""), "銘柄名": name, "現在値": int(curr_price),
            "RSI": round(rsi, 1), 
            "MACD": "GC買い" if golden_cross else "DC売り" if dead_cross else "-",
            "勢い": trend, "パターン": p_name if p_name else "-",
            "buy_score": buy_score, "buy_tp": buy_tp, "buy_sl": buy_sl, "res_line": res_line,
            "sell_score": sell_score, "sell_tp": sell_tp, "sell_sl": sell_sl, "sup_line": sup_line,
            "決算": risk_msg, "is_risk": is_risk
        }
    except: return None

# ==========================================
# 📱 アプリ表示
# ==========================================
st.set_page_config(page_title="最強株スキャナー・完全版", layout="wide")
st.title("🦅 最強株スキャナー (買い戦略特化)")

# --- 1. 個別診断 ---
st.header("🔍 個別銘柄ピンポイント診断")
code_in = st.text_input("コード (例: 7203)", "").strip()

if code_in:
    full_c = code_in + ".T" if ".T" not in code_in else code_in
    d_name = NAME_MAP.get(full_c)
    if not d_name:
        try: d_name = yf.Ticker(full_c).info.get('longName', code_in)
        except: d_name = code_in
    
    with st.spinner("戦略データを計算中..."):
        # 個別診断時は価格フィルタ無効
        r = get_analysis(full_c, d_name, 0, 10000000)
    
    if r:
        st.subheader(f"📊 {r['銘柄名']} ({r['コード']})")
        
        if r["is_risk"]:
            st.error(f"🛑 {r['決算']} のため、現在は取引を控えるべきです。")
        else:
            # カラム1: 現在の状況
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("現在値", f"{r['現在値']}円", delta=r['勢い'])
                if r['buy_score'] >= 50: 
                    st.success("AI判定: 買い推奨 🚀")
                elif r['sell_score'] >= 50: 
                    st.error("AI判定: 空売り推奨 📉")
                else: 
                    st.info("AI判定: 様子見 ☕")

            # カラム2: 買いで入る場合の戦略 (常に表示)
            with c2:
                st.markdown("##### 🐂 買いエントリー戦略")
                st.metric("利確目標 (Target)", f"{r['buy_tp']}円", help="直近高値または+5%")
                st.metric("損切目安 (Stop)", f"{r['buy_sl']}円", delta="-3%", delta_color="inverse", help="エントリーから-3%")

            # カラム3: テクニカル指標
            with c3:
                st.write(f"**RSI:** {r['RSI']}")
                st.write(f"**MACD:** {r['MACD']}")
                st.write(f"**サイン:** {r['パターン']}")
                st.caption(f"抵抗線(上値): {r['res_line']}円")
    else: st.error("取得失敗")

st.divider()

# --- 2. 一括スキャン ---
st.header("🚀 市場全体スキャン (価格帯フィルタ)")

col_filt1, col_filt2 = st.columns(2)
with col_filt1:
    p_min_input = st.number_input("最低価格 (円)", value=1000, step=1000)
with col_filt2:
    p_max_input = st.number_input("最高価格 (円)", value=10000, step=1000)

if st.button("条件でスキャン開始", use_container_width=True):
    with st.spinner(f"{p_min_input}円 〜 {p_max_input}円 の銘柄を抽出中..."):
        with ThreadPoolExecutor(max_workers=5) as ex:
            fs = [ex.submit(get_analysis, t, n, p_min_input, p_max_input) for t, n in NAME_MAP.items()]
            ds = [f.result() for f in fs if f.result()]
    
    if ds:
        df = pd.DataFrame(ds)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🔥 買い推奨")
            bs = df[df["buy_score"] >= 50].sort_values("buy_score", ascending=False)
            if not bs.empty:
                st.dataframe(bs[["コード","銘柄名","現在値","buy_tp","buy_sl","勢い"]].rename(
                    columns={"buy_tp":"利確目標", "buy_sl":"損切目安"}
                ), hide_index=True)
            else: st.info("なし")
        with c2:
            st.subheader("📉 空売り推奨")
            ss = df[df["sell_score"] >= 50].sort_values("sell_score", ascending=False)
            if not ss.empty:
                st.dataframe(ss[["コード","銘柄名","現在値","sell_tp","sell_sl","勢い"]].rename(
                    columns={"sell_tp":"利確目標", "sell_sl":"損切目安"}
                ), hide_index=True)
            else: st.info("なし")
    else:
        st.warning("条件に合う銘柄が見つかりませんでした。")
