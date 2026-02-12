import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta, timezone
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
    "7049.T": "識学"
}

# ==========================================
# 🌐 決算日スクレイピング (株探連動)
# ==========================================
def scrape_earnings_date(code):
    clean_code = code.replace(".T", "")
    url = f"https://kabutan.jp/stock/finance?code={clean_code}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code != 200: return None
        soup = BeautifulSoup(res.text, "html.parser")
        target = soup.find(string=re.compile(r"決算発表予定日"))
        if target:
            date_match = re.search(r"(\d{2}/\d{2}/\d{2})", str(target.parent.get_text()))
            if date_match:
                return datetime.strptime("20" + date_match.group(1), "%Y/%m/%d").date()
    except:
        pass
    return None

# ==========================================
# 🕯️ テクニカル判定 (矛盾排除済み)
# ==========================================
def detect_premium_patterns(df, current_rsi):
    if len(df) < 20: return None, 0, "判定不能", "neutral"
    
    close, high, low = df['Close'], df['High'], df['Low']
    ma5 = close.rolling(5).mean().iloc[-1]
    curr_price = close.iloc[-1]
    
    # トレンド判定
    trend = "☁️ もみ合い"
    if curr_price > ma5 * 1.01: trend = "📈 強気上昇"
    elif curr_price < ma5 * 0.99: trend = "📉 弱気下降"

    # --- 買いパターン (RSI < 60 の時のみ) ---
    if current_rsi < 60:
        low_vals = low.tail(15).values
        if low_vals.min() == low_vals[5:10].min() and low_vals[0:5].min() > low_vals[5:10].min() and low_vals[10:15].min() > low_vals[5:10].min():
            return "💎 逆三尊(A級)", 80, trend, "buy"
        if len(df) >= 4 and all(df['High'].iloc[i] < df['Low'].iloc[i-1] for i in range(-3, 0)):
            return "🔥 三空叩き込み(特級)", 100, trend, "buy"
        if (close.iloc[-3] < df['Open'].iloc[-3] and 
            abs(close.iloc[-2]-df['Open'].iloc[-2]) < abs(close.iloc[-3]-df['Open'].iloc[-3])*0.3 and 
            close.iloc[-1] > df['Open'].iloc[-1]):
            return "🌅 明けの明星(1級)", 90, trend, "buy"

    # --- 売りパターン (RSI > 40 の時のみ) ---
    if current_rsi > 40:
        high_vals = high.tail(15).values
        if high_vals.max() == high_vals[5:10].max() and high_vals[0:5].max() < high_vals[5:10].max() and high_vals[10:15].max() < high_vals[5:10].max():
            return "💀 三尊(A級)", 80, trend, "sell"
        if len(df) >= 4 and all(df['Low'].iloc[i] > df['High'].iloc[i-1] for i in range(-3, 0)):
            return "☄️ 三空踏み上げ(特級)", 100, trend, "sell"

    return None, 0, trend, "neutral"

# ==========================================
# 🧠 分析・戦略算出ロジック
# ==========================================
def get_analysis(ticker, name, min_p=0, max_p=10000000):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if hist.empty or len(hist) < 25: return None
        
        curr_price = hist["Close"].iloc[-1]
        if not (min_p <= curr_price <= max_p): return None

        # 指標計算
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi_val = 100 - (100 / (1 + (gain / loss))).iloc[-1]

        # 抵抗線(25日高値) & 支持線(25日安値)
        res_line = int(hist['High'].tail(25).max())
        sup_line = int(hist['Low'].tail(25).min())

        # 利確・損切りターゲット計算 (買いの場合)
        # 利確: 現在値+5% または 抵抗線付近
        take_profit = int(curr_price * 1.05)
        # 損切: 現在値-3% (浅めに設定して資金を守る)
        stop_loss = int(curr_price * 0.97)

        earn_date = scrape_earnings_date(ticker)
        pattern_name, pattern_score, trend_label, signal_type = detect_premium_patterns(hist, rsi_val)
        
        # 決算リスク
        is_risk = False
        if earn_date and 0 <= (earn_date - datetime.now().date()).days <= 3:
            is_risk = True

        buy_score, sell_score = 0, 0
        if not is_risk:
            # 買いスコア
            if rsi_val < 60:
                if rsi_val < 30: buy_score += 50
                elif rsi_val < 45: buy_score += 30
                if "上昇" in trend_label: buy_score += 20
                if signal_type == "buy": buy_score += pattern_score

            # 売りスコア
            if rsi_val > 60:
                if rsi_val > 70: sell_score += 40
                elif rsi_val > 80: sell_score += 60
                if "下降" in trend_label: sell_score += 20
                if signal_type == "sell": sell_score += pattern_score

        return {
            "コード": ticker.replace(".T", ""), "銘柄名": name, "現在値": int(curr_price),
            "RSI": round(rsi_val, 1), 
            "パターン": pattern_name if pattern_name else "-",
            "トレンド": trend_label, 
            "利確(+5%)": take_profit, "損切(-3%)": stop_loss, "抵抗線": res_line, # 戦略カラム
            "決算日": earn_date if earn_date else "未定",
            "buy_score": buy_score, "sell_score": sell_score, "is_risk": is_risk
        }
    except: return None

# ==========================================
# 📱 アプリ画面設定
# ==========================================
st.set_page_config(page_title="最強株スキャナー・戦略版", layout="wide")
st.title("🦅 最強株スキャナー (戦略提案付き)")
st.caption("エントリーから出口戦略（利確・損切り）までを完全サポート")

# --- 1. 個別銘柄診断 ---
st.header("🔍 個別銘柄ピンポイント診断")
target_code = st.text_input("コードを入力（例：7203）", "").strip()

if target_code:
    full_code = target_code + ".T" if ".T" not in target_code else target_code
    display_name = NAME_MAP.get(full_code)
    if not display_name:
        try: display_name = yf.Ticker(full_code).info.get('longName', f"銘柄コード: {target_code}")
        except: display_name = f"銘柄コード: {target_code}"
    
    with st.spinner(f"{display_name} を分析中..."):
        res = get_analysis(full_code, display_name)
        
    if res:
        st.subheader(f"📊 {res['銘柄名']} ({res['コード']})")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("判定", "買い推奨 🚀" if res["buy_score"] >= 50 else "売り推奨 📉" if res["sell_score"] >= 50 else "様子見", delta=f"{res['現在値']}円")
            st.write(f"**トレンド:** {res['トレンド']}")
        with c2:
            st.metric("利確目標 (+5%)", f"{res['利確(+5%)']}円")
            st.metric("損切りライン (-3%)", f"{res['損切(-3%)']}円", delta_color="inverse")
        with c3:
            st.metric("RSI(14)", res['RSI'])
            st.write(f"**抵抗線(25日高値):** {res['抵抗線']}円")
            st.write(f"**決算:** {res['決算日']}")
        
        if res["is_risk"]: st.error("⚠️ 決算直前のためエントリー非推奨")
    else: st.error("データ取得失敗")

st.divider()

# --- 2. 一括スキャナー ---
st.header("🚀 監視リスト一括スキャン")
col_p1, col_p2 = st.columns(2)
with col_p1: p_min = st.number_input("最低価格", value=1000)
with col_p2: p_max = st.number_input("最高価格", value=100000)

if st.button("全銘柄を一斉スキャン", use_container_width=True):
    with st.spinner("戦略データを計算中..."):
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(get_analysis, t, n, p_min, p_max) for t, n in NAME_MAP.items()]
            data = [f.result() for f in futures if f.result() is not None]

    if data:
        df = pd.DataFrame(data)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🔥 買い時銘柄")
            buys = df[df["buy_score"] >= 50].sort_values("buy_score", ascending=False)
            if not buys.empty:
                # 戦略カラム（利確・損切・抵抗線）を追加表示
                st.dataframe(buys[["コード", "銘柄名", "現在値", "RSI", "トレンド", "利確(+5%)", "損切(-3%)", "抵抗線"]], hide_index=True)
            else: st.info("買いシグナルなし")
                
        with c2:
            st.subheader("📉 売り時銘柄")
            sells = df[df["sell_score"] >= 50].sort_values("sell_score", ascending=False)
            if not sells.empty:
                st.dataframe(sells[["コード", "銘柄名", "現在値", "RSI", "トレンド", "パターン"]], hide_index=True)
            else: st.info("売りシグナルなし")
