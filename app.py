import streamlit as st
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🛡️ バックアップ用リスト (ネット取得失敗時の保険)
# ==========================================
BACKUP_225 = [
    "7203.T", "9984.T", "8306.T", "6758.T", "6861.T", "6098.T", "8035.T", "4063.T", "7974.T", "9432.T",
    "8058.T", "7267.T", "4502.T", "6501.T", "7741.T", "6367.T", "6902.T", "4543.T", "3382.T", "4519.T",
    "6273.T", "6954.T", "7269.T", "9101.T", "9104.T", "5401.T", "8316.T", "8411.T", "8766.T", "8801.T",
    "1605.T", "1925.T", "2413.T", "2502.T", "2801.T", "2914.T", "3407.T", "4503.T", "4507.T", "4523.T",
    "4568.T", "4578.T", "4661.T", "4901.T", "4911.T", "5020.T", "5108.T", "5713.T", "6146.T", "6301.T",
    "6326.T", "6503.T", "6594.T", "6702.T", "6723.T", "6752.T", "6762.T", "6857.T", "6971.T", "6981.T",
    "7011.T", "7201.T", "7270.T", "7272.T", "7733.T", "7751.T", "7832.T", "8001.T", "8002.T", "8015.T",
    "8031.T", "8053.T", "8604.T", "8630.T", "8725.T", "8750.T", "8802.T", "8830.T", "9020.T", "9021.T",
    "9022.T", "9202.T", "9735.T", "9843.T", "9983.T"
    # (主要なものを抜粋)
]

# ユーザーのお気に入り (常に監視)
MY_FAVORITES = {
    "8591.T": "オリックス", "9434.T": "ソフトバンク", "3003.T": "ヒューリック", "2702.T": "マクドナルド"
}

# ==========================================
# 🔄 銘柄リスト自動取得ロジック
# ==========================================
@st.cache_data(ttl=3600*12) 
def get_tickers_safe():
    tickers_dict = {}
    
    # 1. Wikipediaから自動取得を試みる
    try:
        url = "https://en.wikipedia.org/wiki/Nikkei_225"
        # html5libを使って丁寧に読み込む
        tables = pd.read_html(url, flavor='html5lib') 
        df = tables[0]
        
        # コード列を探す
        code_col = None
        for col in df.columns:
            if df[col].astype(str).str.match(r'\d{4}').any():
                code_col = col
                break
        
        if code_col:
            name_col = "Company" if "Company" in df.columns else df.columns[0]
            for index, row in df.iterrows():
                code = str(row[code_col]) + ".T"
                name = str(row[name_col])
                tickers_dict[code] = name
            st.toast("✅ 最新の日経225リストを取得しました", icon="🌐")
            
    except Exception as e:
        # 失敗したらバックアップを使う
        st.toast("⚠️ ネット取得失敗。バックアップリストを使用します", icon="🛡️")
        for t in BACKUP_225:
            tickers_dict[t] = "日経225(Backup)"
    
    # 2. 取得できたリストが空なら強制的にバックアップ
    if not tickers_dict:
        for t in BACKUP_225:
            tickers_dict[t] = "日経225(Backup)"

    # 3. お気に入りを追加
    tickers_dict.update(MY_FAVORITES)
    
    return tickers_dict

# ==========================================
# 🧠 テクニカル分析ロジック
# ==========================================
def get_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        
        hist_check = stock.history(period="1d")
        if hist_check.empty: return None
        curr_price = hist_check["Close"].iloc[-1]
        
        if not (min_p <= curr_price <= max_p): return None

        df = stock.history(period="6mo")
        if len(df) < 60: return None

        close = df['Close']
        high = df['High']
        low = df['Low']
        
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        curr_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-3]
        
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        
        hist_now = macd_line.iloc[-1] - signal_line.iloc[-1]
        hist_prev = macd_line.iloc[-2] - signal_line.iloc[-2]

        resistance = high.rolling(25).max().iloc[-1]
        support = low.rolling(25).min().iloc[-1]

        buy_score = 0
        sell_score = 0
        
        if curr_rsi < 30: buy_score += 40
        elif curr_rsi < 40: buy_score += 20
        if hist_now > hist_prev: buy_score += 20
        if hist_now < 0 and hist_prev < 0: buy_score += 10
        if curr_rsi > prev_rsi: buy_score += 10 

        if curr_rsi > 70: sell_score += 40
        elif curr_rsi > 60: sell_score += 20
        if hist_now < hist_prev: sell_score += 20
        if hist_now > 0 and hist_prev > 0: sell_score += 10
        if curr_rsi < prev_rsi: sell_score += 10 

        return {
            "name": name,
            "code": ticker.replace(".T", ""),
            "price": curr_price,
            "rsi": curr_rsi,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "resistance": resistance,
            "support": support
        }
    except:
        return None

def run_scan(min_p, max_p):
    # リスト取得（ここでネットorバックアップを判断）
    tickers_dict = get_tickers_safe()
    
    results = []
    target_tickers = list(tickers_dict.keys())
    
    # メッセージ表示
    st.info(f"監視対象: **{len(target_tickers)}銘柄** をスキャン中...")
    
    progress_bar = st.progress(0)
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_analysis, t, tickers_dict[t], min_p, max_p) for t in target_tickers]
        total = len(futures)
        for i, f in enumerate(futures):
            res = f.result()
            if res:
                results.append(res)
            progress_bar.progress((i + 1) / total)
            
    progress_bar.empty()
    return results

# ==========================================
# 📱 アプリ画面 UI
# ==========================================
st.set_page_config(page_title="最強株スキャナー (自動取得)", layout="wide")
st.title("🦅 最強株スキャナー (自動取得版)")

col1, col2 = st.columns([1, 2])
with col1:
    st.write("##### 💰 価格帯設定")
    p_min = st.number_input("下限 (円)", value=1000, step=100)
    p_max = st.number_input("上限 (円)", value=10000, step=100)
with col2:
    st.write("##### 📊 分析モード")
    st.caption("Wikipediaから最新の225銘柄を取得し、分析します。(失敗時はバックアップ稼働)")

if st.button("🚀 スキャン開始", use_container_width=True):
    data = run_scan(p_min, p_max)
    
    if data:
        df = pd.DataFrame(data)
        buys = df[df["buy_score"] >= 60].sort_values("buy_score", ascending=False).head(15)
        sells = df[df["sell_score"] >= 60].sort_values("sell_score", ascending=False).head(15)

        col_b, col_s = st.columns(2)
        with col_b:
            st.subheader("🔥 買い推奨")
            if not buys.empty:
                st.dataframe(buys[["name", "code", "price", "rsi", "support", "resistance"]], use_container_width=True)
            else:
                st.write("推奨なし")

        with col_s:
            st.subheader("📉 売り推奨")
            if not sells.empty:
                st.dataframe(sells[["name", "code", "price", "rsi", "resistance", "support"]], use_container_width=True)
            else:
                st.write("推奨なし")
    else:
        st.warning("条件に合う銘柄なし")
