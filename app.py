import streamlit as st
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# ⚙️ ユーザー設定エリア
# ==========================================

# 1. ここに「225以外で監視したい銘柄」を追加できます
#    （例：スタンダード市場の株、REIT、優待株など）
MY_FAVORITES = {
    # "コード.T": "銘柄名",
    "8591.T": "オリックス",
    "9434.T": "ソフトバンク",
    "3003.T": "ヒューリック",
    "2702.T": "マクドナルド",
    # 必要に応じて増やしてください
}

# ==========================================
# 🔄 銘柄リスト自動取得ロジック
# ==========================================
@st.cache_data(ttl=3600*12) # 半日キャッシュ
def get_target_tickers():
    # 1. 日経225を自動取得
    auto_dict = {}
    try:
        url = "https://en.wikipedia.org/wiki/Nikkei_225"
        tables = pd.read_html(url)
        df = tables[0]
        
        # 銘柄コードの列を探す
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
                auto_dict[code] = name
    except:
        pass # 失敗しても手動リストだけで動かす

    # 2. 手動リストと合体させる（重複は上書き）
    auto_dict.update(MY_FAVORITES)
    
    return auto_dict

# ==========================================
# 🧠 テクニカル分析ロジック
# ==========================================
def get_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        
        # 現在値チェック（高速化）
        hist_check = stock.history(period="1d")
        if hist_check.empty: return None
        curr_price = hist_check["Close"].iloc[-1]
        
        if not (min_p <= curr_price <= max_p): return None

        # 詳細データ取得
        df = stock.history(period="6mo")
        if len(df) < 60: return None

        close = df['Close']
        high = df['High']
        low = df['Low']
        
        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        curr_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-3]
        
        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        
        hist_now = macd_line.iloc[-1] - signal_line.iloc[-1]
        hist_prev = macd_line.iloc[-2] - signal_line.iloc[-2]

        # 抵抗線・支持線
        resistance = high.rolling(25).max().iloc[-1]
        support = low.rolling(25).min().iloc[-1]

        # 判定スコア
        buy_score = 0
        sell_score = 0
        
        # 買いロジック
        if curr_rsi < 30: buy_score += 40
        elif curr_rsi < 40: buy_score += 20
        if hist_now > hist_prev: buy_score += 20 # MACD改善
        if hist_now < 0 and hist_prev < 0: buy_score += 10
        if curr_rsi > prev_rsi: buy_score += 10 

        # 売りロジック
        if curr_rsi > 70: sell_score += 40
        elif curr_rsi > 60: sell_score += 20
        if hist_now < hist_prev: sell_score += 20 # MACD悪化
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

def run_scan(ticker_dict, min_p, max_p):
    results = []
    target_tickers = list(ticker_dict.keys())
    
    progress_text = "市場全体をスキャン中..."
    my_bar = st.progress(0, text=progress_text)
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_analysis, t, ticker_dict[t], min_p, max_p) for t in target_tickers]
        total = len(futures)
        for i, f in enumerate(futures):
            res = f.result()
            if res:
                results.append(res)
            my_bar.progress((i + 1) / total, text=f"{progress_text} ({i+1}/{total})")
            
    my_bar.empty()
    return results

# ==========================================
# 📱 アプリ画面 UI
# ==========================================
st.set_page_config(page_title="最強株スキャナー", layout="wide")
st.title("🦅 最強株スキャナー (ハイブリッド版)")
st.caption("日経225自動取得 ＋ お気に入り銘柄を一括分析")

# リスト取得
with st.spinner('監視リストを更新中...'):
    TICKER_DICT = get_target_tickers()

st.success(f"現在の監視対象: **{len(TICKER_DICT)}銘柄**")

# 設定
col1, col2 = st.columns([1, 2])
with col1:
    st.write("##### 💰 価格帯設定")
    p_min = st.number_input("下限 (円)", value=1000, step=100)
    p_max = st.number_input("上限 (円)", value=10000, step=100)
with col2:
    st.info("日経225（主要株）と、コード内で指定した「お気に入り株」をまとめて監視します。")

# 実行
if st.button("🚀 全銘柄スキャン開始", use_container_width=True):
    data = run_scan(TICKER_DICT, p_min, p_max)
    
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
