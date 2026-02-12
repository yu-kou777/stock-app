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
# 🌐 決算日スクレイピング (株探連動・安定化版)
# ==========================================
def scrape_earnings_date(code):
    """株探から次回決算発表日を取得。失敗時はNoneを返す"""
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
# 🕯️ 画像のテクニカル判定 (矛盾排除ロジック)
# ==========================================
def detect_premium_patterns(df, current_rsi):
    """
    RSIの水準に合わせて、適切なパターンのみを検出する
    (高値圏で底打ちサインが出ないようにフィルタリング)
    """
    if len(df) < 20: return None, 0, "判定不能", "neutral"
    
    close, high, low = df['Close'], df['High'], df['Low']
    ma5 = close.rolling(5).mean().iloc[-1]
    curr_price = close.iloc[-1]
    
    # トレンド判定
    trend = "☁️ もみ合い"
    if curr_price > ma5 * 1.01: trend = "📈 強気上昇"
    elif curr_price < ma5 * 0.99: trend = "📉 弱気下降"

    # --- 買いパターンの判定 (RSIが低い時のみ有効) ---
    if current_rsi < 60:
        # 逆三尊 (Aランク)
        low_vals = low.tail(15).values
        if low_vals.min() == low_vals[5:10].min() and low_vals[0:5].min() > low_vals[5:10].min() and low_vals[10:15].min() > low_vals[5:10].min():
            return "💎 逆三尊(A級)", 80, trend, "buy"

        # 三空叩き込み (特級)
        if len(df) >= 4:
            if all(df['High'].iloc[i] < df['Low'].iloc[i-1] for i in range(-3, 0)):
                return "🔥 三空叩き込み(特級)", 100, trend, "buy"

        # 明けの明星 (1級)
        if (close.iloc[-3] < df['Open'].iloc[-3] and 
            abs(close.iloc[-2]-df['Open'].iloc[-2]) < abs(close.iloc[-3]-df['Open'].iloc[-3])*0.3 and 
            close.iloc[-1] > df['Open'].iloc[-1]):
            return "🌅 明けの明星(1級)", 90, trend, "buy"

    # --- 売りパターンの判定 (RSIが高い時のみ有効) ---
    if current_rsi > 40:
        # 三尊 (Aランク)
        high_vals = high.tail(15).values
        if high_vals.max() == high_vals[5:10].max() and high_vals[0:5].max() < high_vals[5:10].max() and high_vals[10:15].max() < high_vals[5:10].max():
            return "💀 三尊(A級)", 80, trend, "sell"

        # 三空踏み上げ (特級売り)
        if len(df) >= 4:
            if all(df['Low'].iloc[i] > df['High'].iloc[i-1] for i in range(-3, 0)):
                return "☄️ 三空踏み上げ(特級)", 100, trend, "sell"

    return None, 0, trend, "neutral"

# ==========================================
# 🧠 分析・リスク管理ロジック
# ==========================================
def get_analysis(ticker, name, min_p=0, max_p=10000000):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if hist.empty or len(hist) < 25: return None
        
        curr_price = hist["Close"].iloc[-1]
        if not (min_p <= curr_price <= max_p): return None

        # RSI計算
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi_val = 100 - (100 / (1 + (gain / loss))).iloc[-1]

        earn_date = scrape_earnings_date(ticker)
        
        # パターン検出 (RSIを渡して矛盾を防ぐ)
        pattern_name, pattern_score, trend_label, signal_type = detect_premium_patterns(hist, rsi_val)
        
        # 決算リスク判定
        is_risk = False
        now_date = datetime.now().date()
        if earn_date:
            days_to_earn = (earn_date - now_date).days
            if 0 <= days_to_earn <= 3:
                is_risk = True

        # スコア計算
        buy_score, sell_score = 0, 0
        
        if not is_risk:
            # --- 買いスコア ---
            # 基本点: RSIが低いほど高い
            if rsi_val < 60:
                if rsi_val < 30: buy_score += 50      # 売られすぎ
                elif rsi_val < 45: buy_score += 30    # 買い場
                
                # トレンド加点 (上昇トレンドの押し目買い)
                if "上昇" in trend_label: buy_score += 20
                
                # パターン加点 (買いサインが出ている場合のみ)
                if signal_type == "buy": buy_score += pattern_score

            # --- 売りスコア ---
            if rsi_val > 60:
                if rsi_val > 70: sell_score += 40     # 買われすぎ
                elif rsi_val > 80: sell_score += 60   # 危険水準
                
                if "下降" in trend_label: sell_score += 20
                
                # パターン加点 (売りサインが出ている場合のみ)
                if signal_type == "sell": sell_score += pattern_score

        return {
            "コード": ticker.replace(".T", ""), "銘柄名": name, "現在値": int(curr_price),
            "RSI": round(rsi_val, 1), 
            "パターン": pattern_name if pattern_name else "-",
            "トレンド": trend_label, "決算日": earn_date if earn_date else "未定",
            "buy_score": buy_score, "sell_score": sell_score, "is_risk": is_risk
        }
    except:
        return None

# ==========================================
# 📱 アプリ画面設定
# ==========================================
st.set_page_config(page_title="最強株スキャナー・完全版", layout="wide")
st.title("🦅 最強株スキャナー (矛盾修正・完全版)")
st.caption("特級サイン検知 × 決算リスク回避 × 厳密なトレンド判定")

# --- 1. 個別銘柄診断機能 ---
st.header("🔍 個別銘柄ピンポイント診断")
target_code = st.text_input("コードを入力（例：7203）", "").strip()

if target_code:
    full_code = target_code + ".T" if ".T" not in target_code else target_code
    display_name = NAME_MAP.get(full_code)
    if not display_name:
        try:
            display_name = yf.Ticker(full_code).info.get('longName', f"銘柄コード: {target_code}")
        except:
            display_name = f"銘柄コード: {target_code}"
    
    with st.spinner(f"{display_name} を診断中..."):
        res = get_analysis(full_code, display_name)
        
    if res:
        st.subheader(f"📊 {res['銘柄名']} ({res['コード']}) の診断結果")
        col_res1, col_res2, col_res3 = st.columns(3)
        with col_res1:
            if res["is_risk"]:
                st.metric("判定", "⚠️ 見送り推奨", delta="決算リスク", delta_color="inverse")
            else:
                judge = "買い推奨 🚀" if res["buy_score"] >= 50 else "売り推奨 📉" if res["sell_score"] >= 50 else "様子見 ☕"
                st.metric("判定", judge)
            st.write(f"**現在価格:** {res['現在値']}円")
        with col_res2:
            st.metric("トレンド", res["トレンド"])
            st.write(f"**RSI(14):** {res['RSI']}")
        with col_res3:
            st.write(f"**出現サイン:** {res['パターン']}")
            st.write(f"**決算日:** {res['決算日']}")
        
        if res["is_risk"]:
            st.error(f"⚠️ 決算発表({res['決算日']})が近いため、テクニカル分析に関わらずエントリーは危険です。")
    else:
        st.error("データの取得に失敗しました。")

st.divider()

# --- 2. 一括スキャナー機能 ---
st.header("🚀 監視リスト一括スキャン")
col_p1, col_p2 = st.columns(2)
with col_p1: p_min = st.number_input("最低価格 (円)", value=1000)
with col_p2: p_max = st.number_input("最高価格 (円)", value=100000)

if st.button("全銘柄を一斉スキャン", use_container_width=True):
    with st.spinner("矛盾のない正確なサインを探索中..."):
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(get_analysis, t, n, p_min, p_max) for t, n in NAME_MAP.items()]
            data = [f.result() for f in futures if f.result() is not None]

    if data:
        df = pd.DataFrame(data)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🔥 買い時銘柄")
            # 買いスコア50以上を表示 (基準を少し緩和してNECなども拾えるように調整)
            buys = df[df["buy_score"] >= 50].sort_values("buy_score", ascending=False)
            if not buys.empty:
                st.dataframe(buys[["コード", "銘柄名", "現在値", "RSI", "トレンド", "パターン"]], hide_index=True)
            else:
                st.info("現在、強い買いシグナルは出ていません。")
                
        with c2:
            st.subheader("📉 売り時銘柄")
            sells = df[df["sell_score"] >= 50].sort_values("sell_score", ascending=False)
            if not sells.empty:
                st.dataframe(sells[["コード", "銘柄名", "現在値", "RSI", "トレンド", "パターン"]], hide_index=True)
            else:
                st.info("現在、強い売りシグナルは出ていません。")
    else:
        st.info("データが取得できませんでした。")
