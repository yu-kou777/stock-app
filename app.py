import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
import os

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Pro", page_icon="🦅")

# --- 2. 永続保存ロジック (シンプルにテキストファイルを使用) ---
SAVE_FILE = "watchlist.txt"

def load_saved_list():
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "r") as f:
            return f.read().strip()
    return "9984, 6330" # 初期値

def save_list(text):
    with open(SAVE_FILE, "w") as f:
        f.write(text)

# --- 3. 解析ロジック (MTF + 反発検知) ---

def calculate_heikin_ashi(df):
    ha_df = df.copy()
    ha_df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    ha_df['HA_Open'] = 0.0
    ha_df.iloc[0, ha_df.columns.get_loc('HA_Open')] = (df.iloc[0]['Open'] + df.iloc[0]['Close']) / 2
    for i in range(1, len(df)):
        ha_df.iloc[i, ha_df.columns.get_loc('HA_Open')] = (ha_df.iloc[i-1]['HA_Open'] + ha_df.iloc[i-1]['HA_Close']) / 2
    return ha_df

def analyze_stock(ticker, min_p, max_p, is_force=False):
    try:
        tkr = yf.Ticker(ticker)
        df_d = tkr.history(period="6mo", interval="1d")
        df_w = tkr.history(period="2y", interval="1wk")
        if df_d.empty or df_w.empty: return None

        price = df_d.iloc[-1]['Close']
        if not is_force and not (min_p <= price <= max_p): return None

        df_w['MA20'] = df_w['Close'].rolling(20).mean()
        target_p = int(df_w['MA20'].iloc[-1])
        ha_w = calculate_heikin_ashi(df_w); w_l = ha_w.iloc[-1]
        ha_d = calculate_heikin_ashi(df_d); d_l = ha_d.iloc[-1]
        
        is_w_up = w_l['HA_Close'] > w_l['HA_Open']
        is_d_up = d_l['HA_Close'] > d_l['HA_Open']
        rsi_w = ta.rsi(df_w['Close'], length=14).iloc[-1]
        dev_w = (price - target_p) / target_p * 100

        # 反発フロア（-2σ相当）
        std20 = df_d['Close'].rolling(20).std().iloc[-1]
        ma20 = df_d['Close'].rolling(20).mean().iloc[-1]
        floor = int(ma20 - (std20 * 2))

        is_oversold = rsi_w < 35 or dev_w < -15
        if is_oversold:
            status_msg = f"🎯 反発開始 (目標:{target_p})" if is_d_up else f"⏳ 底打ち模索中 ({target_p})"
        else:
            status_msg = "📈 順張り" if is_d_up else "📉 調整"

        score = (50 if is_w_up else -50) + (40 if is_oversold else 0) + (30 if is_d_up else -30)
        if is_w_up != is_d_up: score *= 0.3

        return {
            "コード": ticker.replace(".T",""), "現在値": int(price),
            "判定": status_msg, "スコア": int(score), "週RSI": round(rsi_w, 1),
            "予想底値": floor, "目標(20週)": target_p, "根拠": f"週:{'陽' if is_w_up else '陰'} / 日:{'陽' if is_d_up else '陰'}"
        }
    except: return None

# --- 4. Streamlit UI ---

st.title("🏹 Stock Sniper Pro")

# サイドバー：戦略司令室
st.sidebar.title("💰 検索・保存")

# 保存されているリストを読み込む
saved_text = load_saved_list()
input_area = st.sidebar.text_area("監視銘柄 (カンマ区切り)", saved_text, height=150)

if st.sidebar.button("💾 リストを保存"):
    save_list(input_area)
    st.sidebar.success("保存しました！次回もここから始まります。")

st.sidebar.subheader("株価帯フィルタ")
col_min, col_max = st.sidebar.columns(2)
min_p = col_min.number_input("下限", 0, 100000, 1000, step=100)
max_p = col_max.number_input("上限", 0, 100000, 10000, step=100)

# 解析用リストの作成
ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_area.split(',') if t.strip()]

# メインボタン
c1, c2, c3 = st.columns(3)
btn_all = c1.button("📑 スキャン実行")
btn_buy = c2.button("🚀 買い・反発狙い")
btn_short = c3.button("📉 空売り狙い")

if btn_all or btn_buy or btn_short:
    results = []
    bar = st.progress(0)
    for i, t in enumerate(ticker_list):
        res = analyze_stock(t, min_p, max_p, is_force=True) # 自由入力は常に強制表示
        if res: results.append(res)
        bar.progress((i + 1) / len(ticker_list))
    
    if results:
        df = pd.DataFrame(results).sort_values("スコア", ascending=False)
        if btn_buy: df = df[df['判定'].str.contains("買") | df['判定'].str.contains("反発")]
        elif btn_short: df = df[df['スコア'] < 0]

        # 表示（スマホ向けExpander）
        for _, row in df.iterrows():
            with st.expander(f"{row['判定']} | コード: {row['コード']} - {row['現在値']}円"):
                st.write(f"**スコア:** {row['スコア']}点 | **週RSI:** {row['週RSI']}")
                st.write(f"**予想底値（指値目安）:** {row['予想底値']}円")
                st.write(f"**利確目標（20週線）:** {row['目標(20週)']}円")
                st.write(f"**状態:** {row['根拠']}")
        
        st.divider()
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("該当銘柄なし。コードまたは価格帯を確認してください。")

