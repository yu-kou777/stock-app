import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🛡️ 銘柄マスタ (日本語名固定)
# ==========================================
NAME_MAP = {
    "7203.T": "トヨタ", "9984.T": "SBG", "8306.T": "三菱UFJ", "6758.T": "ソニーG",
    "6861.T": "キーエンス", "6098.T": "リクルート", "8035.T": "東エレク", "4063.T": "信越化学",
    "7974.T": "任天堂", "9432.T": "NTT", "8058.T": "三菱商事", "8316.T": "三井住友",
    "8630.T": "SOMPO", "8725.T": "MS&AD", "6701.T": "NEC", "4901.T": "富士フイルム",
    "6702.T": "富士通", "4503.T": "アステラス", "6971.T": "京セラ", "7211.T": "三菱自",
    "8591.T": "オリックス", "3003.T": "ヒューリック", "2702.T": "マクドナルド",
    "9101.T": "日本郵船", "9104.T": "商船三井", "5401.T": "日本製鉄"
}

# ==========================================
# 🌐 決算日スクレイピング (株探連動)
# ==========================================
def scrape_earnings_date(code):
    """株探から次回決算発表日を取得する"""
    url = f"https://kabutan.jp/stock/finance?code={code.replace('.T', '')}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        target = soup.find(text=re.compile(r"決算発表予定日"))
        if target:
            date_match = re.search(r"(\d{2}/\d{2}/\d{2})", str(target.parent.get_text()))
            if date_match:
                return datetime.strptime("20" + date_match.group(1), "%Y/%m/%d").date()
    except: pass
    return None

# ==========================================
# 🧠 テクニカル分析 ＋ 防衛ロジック
# ==========================================
def get_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 25: return None
        
        curr_price = hist["Close"].iloc[-1]
        if not (min_p <= curr_price <= max_p): return None

        # 指標計算
        close = hist['Close']
        ma5 = close.rolling(5).mean().iloc[-1]
        
        # RSI計算
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        # RSI式: $100 - (100 / (1 + \text{Gain} / \text{Loss}))$
        rsi = 100 - (100 / (1 + (gain / loss)))
        curr_rsi = rsi.iloc[-1]

        # 決算リスク判定
        now = datetime.now().date()
        earn_date = scrape_earnings_date(ticker)
        is_risk = False
        status_note = "☁️拮抗"
        
        if earn_date:
            days_to_earn = (earn_date - now).days
            if 0 <= days_to_earn <= 3:
                is_risk = True
                status_note = f"⚠️決算警戒({earn_date})"
        
        # 決算直後のボラティリティ抑制 (±5%以上の急変時は見送り)
        if len(hist) >= 2:
            last_change = abs((close.iloc[-1] / close.iloc[-2]) - 1)
            if last_change >= 0.05:
                is_risk = True
                status_note = "⚡決算直後ボラ警戒"

        # 需給判断 (MA5との乖離)
        if not is_risk:
            if curr_price > ma5 * 1.01: status_note = "📈買い優勢"
            elif curr_price < ma5 * 0.99: status_note = "📉売り優勢"

        # スコアリング
        buy_score, sell_score = 0, 0
        if not is_risk:
            # 買い: RSI < 60 の絶対条件 (高値掴み防止)
            if curr_rsi < 60:
                if curr_rsi < 35: buy_score += 60
                if curr_price <= hist['Low'].rolling(25).min().iloc[-1] * 1.02: buy_score += 20
            # 売り
            if curr_rsi > 65: sell_score += 60

        return {
            "code": ticker.replace(".T", ""),
            "name": name,
            "price": int(curr_price),
            "rsi": round(curr_rsi, 1),
            "status": status_note,
            "earn_date": earn_date if earn_date else "未定",
            "buy_score": buy_score,
            "sell_score": sell_score
        }
    except: return None

def run_scan(min_p, max_p):
    results = []
    with st.spinner("スキャン中..."):
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(get_analysis, t, n, min_p, max_p) for t, n in NAME_MAP.items()]
            results = [f.result() for f in futures if f.result() is not None]
    return results

# ==========================================
# 📱 画面レイアウト
# ==========================================
st.set_page_config(page_title="最強株スキャナー・防衛版", layout="wide")
st.title("🦅 最強株スキャナー (決算防衛版)")
st.caption("RSI安全装置 × 需給判断 × 株探決算回避")

col1, col2 = st.columns([1, 2])
with col1:
    p_min = st.number_input("下限価格 (円)", value=1000, step=100)
    p_max = st.number_input("上限価格 (円)", value=10000, step=100)
with col2:
    st.info("買い推奨は **RSI 60未満** かつ **非決算期間** の銘柄のみ表示します。")

if st.button("🚀 スキャン開始", use_container_width=True):
    data = run_scan(p_min, p_max)
    if data:
        df = pd.DataFrame(data)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🔥 買い推奨")
            buys = df[df["buy_score"] >= 60].sort_values("buy_score", ascending=False)
            st.dataframe(buys[["code", "name", "price", "rsi", "status", "earn_date"]], hide_index=True)
        with c2:
            st.subheader("📉 売り推奨")
            sells = df[df["sell_score"] >= 60].sort_values("sell_score", ascending=False)
            st.dataframe(sells[["code", "name", "price", "rsi", "status", "earn_date"]], hide_index=True)

        st.divider()
        st.subheader("⏳ 判定見送り中 (決算リスク等)")
        pending = df[df["status"].str.contains("⚠️|⚡")]
        st.dataframe(pending[["code", "name", "earn_date", "status"]], hide_index=True)
    else:
        st.warning("条件に合う銘柄がありません")
