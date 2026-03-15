import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
import plotly.graph_objects as go
import os

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Pro", page_icon="🦅")

# --- 2. データベース & JPX全銘柄名簿の自動取得 ---
SAVE_FILE = "watchlist.txt"

@st.cache_data(ttl=86400)  # 1日1回だけ実行して高速化
def get_jpx_master():
    """JPX公式サイトから最新の全銘柄名簿を取得する"""
    url = "https://www.jpx.co.jp/markets/statistics-fra/data/files/p_stock_data.xlsx"
    try:
        df = pd.read_excel(url)
        # プライムとスタンダードを抽出
        prime = df[df['市場・商品区分'].str.contains('プライム', na=False)]['コード'].astype(str).tolist()
        standard = df[df['市場・商品区分'].str.contains('スタンダード', na=False)]['コード'].astype(str).tolist()
        # 銘柄名辞書を自動生成
        names = dict(zip(df['コード'].astype(str), df['銘柄名']))
        return {"prime": prime, "standard": standard, "names": names}
    except:
        # 失敗時のバックアップ（空リスト）
        return {"prime": [], "standard": [], "names": {}}

# 名簿の読み込み
jpx = get_jpx_master()

def load_saved_list():
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

def save_list(text):
    items = [i.strip() for i in text.replace('\n', ',').split(',') if i.strip()]
    cleaned_text = ", ".join(sorted(set(items), key=items.index))
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        f.write(cleaned_text)

def add_bulk_to_list(ticker_codes):
    current = load_saved_list()
    current_items = [i.strip() for i in current.split(',') if i.strip()]
    new_items = [i.replace(".T", "").strip() for i in ticker_codes]
    combined = current_items + new_items
    save_list(", ".join(combined))
    return len(set(combined)) - len(set(current_items))

# --- 3. 解析エンジン ---
def analyze_stock(ticker, min_p, max_p, is_force=False):
    try:
        tkr = yf.Ticker(ticker)
        df_d = tkr.history(period="6mo", interval="1d")
        if df_d.empty or len(df_d) < 60: return None
        price = df_d.iloc[-1]['Close']
        if not is_force and not (min_p <= price <= max_p): return None

        df_d['MA20'] = df_d['Close'].rolling(20).mean()
        df_d['MA60'] = df_d['Close'].rolling(60).mean()
        macd = ta.macd(df_d['Close'])
        df_d = pd.concat([df_d, macd], axis=1)
        df_d['RSI'] = ta.rsi(df_d['Close'], length=14)
        
        low_60 = df_d['Low'].tail(60).min()
        high_60 = df_d['High'].tail(60).max()
        std20 = df_d['Close'].rolling(20).std().iloc[-1]
        
        score = 0
        if price <= low_60 * 1.015: score += 30
        if all(df_d['Close'].tail(3) > df_d['Open'].tail(3)): score += 20
        if df_d['MACDh_12_26_9'].iloc[-1] > 0: score += 20
        if df_d['RSI'].iloc[-1] < 35: score += 30
        if price >= high_60 * 0.985: score -= 30
        if all(df_d['Close'].tail(3) < df_d['Open'].tail(3)): score -= 20
        if df_d['MACDh_12_26_9'].iloc[-1] < 0: score -= 20
        if df_d['RSI'].iloc[-1] > 65: score -= 30

        p_floor = int((df_d['MA20'].iloc[-1] - (std20 * 2) + low_60) / 2)
        p_ceiling = int((df_d['MA20'].iloc[-1] + (std20 * 2) + high_60) / 2)

        is_buy = score >= 0
        entry_target = p_floor if is_buy else p_ceiling
        dist_yen = price - entry_target if is_buy else entry_target - price
        dist_pct = (dist_yen / price) * 100

        if score >= 60: judge = "🚀 超精密買"
        elif score >= 20: judge = "✨ 買目線"
        elif score <= -60: judge = "📉 特級売"
        elif score <= -20: judge = "☔ 売目線"
        else: judge = "☁️ 様子見"

        target1 = int(df_d['MA20'].iloc[-1])
        target2 = int(df_d['MA60'].iloc[-1]) if is_buy else p_floor

        # 銘柄名をJPXリストから取得
        code_only = ticker.replace(".T","")
        stock_name = jpx["names"].get(code_only, "不明銘柄")

        return {
            "コード": code_only, "和名": stock_name,
            "現在値": int(price), "判定": judge, "スコア": int(score), 
            "指値(入口)": entry_target, "利確1": target1, "利確2": target2,
            "距離": f"あと {int(dist_yen)}円 ({dist_pct:.1f}%)" if dist_yen > 0 else "🎯 射程内",
            "df": df_d, "is_buy": is_buy
        }
    except: return None

# --- 4. 画面構築 ---
st.title("🏹 Stock Sniper Strategy Pro")

# サイドバー
st.sidebar.title("💰 検索・保存管理")
mode = st.sidebar.radio("検索対象", ["📊 プライム全件", "🏛️ スタンダード全件", "⭐ 保存リスト", "📝 自由入力"])
saved_text = load_saved_list()

if mode == "📊 プライム全件":
    ticker_list = [f"{c}.T" for c in jpx["prime"]]
    is_force = False
elif mode == "🏛️ スタンダード全件":
    ticker_list = [f"{c}.T" for c in jpx["standard"]]
    is_force = False
elif mode == "⭐ 保存リスト":
    input_area = st.sidebar.text_area("ウォッチリスト", saved_text, height=150)
    c_s, c_c = st.sidebar.columns(2)
    if c_s.button("💾 保存"): save_list(input_area); st.rerun()
    if c_c.button("🗑️ 全消去"): save_list(""); st.rerun()
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_area.split(',') if t.strip()]
    is_force = True
else:
    input_area = st.sidebar.text_area("銘柄入力", "9984, 6330", height=100)
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_area.split(',') if t.strip()]
    is_force = True

min_p = st.sidebar.number_input("株価下限", 0, 100000, 1000)
max_p = st.sidebar.number_input("株価上限", 0, 100000, 100000)

if 'scan_results' not in st.session_state: st.session_state.scan_results = None

c1, c2, c3 = st.columns(3)
if c1.button("📑 全件スキャン"): st.session_state.scan_results = ("all", ticker_list)
if c2.button("🚀 買い・反発狙い"): st.session_state.scan_results = ("buy", ticker_list)
if c3.button("📉 空売り狙い"): st.session_state.scan_results = ("short", ticker_list)

if st.session_state.scan_results:
    s_type, targets = st.session_state.scan_results
    results = []
    bar = st.progress(0)
    
    # 解析実行（件数が多いので進捗バーを表示）
    for i, t in enumerate(targets):
        res = analyze_stock(t, min_p, max_p, is_force)
        if res: results.append(res)
        bar.progress((i + 1) / len(targets))
    
    if results:
        df_res = pd.DataFrame(results).sort_values("スコア", ascending=False)
        if s_type == "buy": df_res = df_res[df_res['スコア'] >= 20]
        elif s_type == "short": df_res = df_res[df_res['スコア'] <= -20]

        st.success(f"{len(df_res)} 件の有力銘柄が見つかりました！")
        
        for _, row in df_res.iterrows():
            label = f"{row['判定']} | {row['和名']} ({row['コード']}) 🟢 {row['距離']} | 🎯1:{row['利確1']}円 / 🎯2:{row['利確2']}円"
            with st.expander(label):
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=row['df'].index, open=row['df']['Open'], high=row['df']['High'], low=row['df']['Low'], close=row['df']['Close'], name='価格'))
                fig.add_trace(go.Scatter(x=row['df'].index, y=row['df']['MA20'], line=dict(color='green', width=1), name='20MA'))
                fig.add_trace(go.Scatter(x=row['df'].index, y=row['df']['MA60'], line=dict(color='orange', width=1), name='60MA'))
                
                fig.add_hline(y=row['指値(入口)'], line_dash="dash", line_color="royalblue", annotation_text="指値")
                fig.add_hline(y=row['利確1'], line_dash="dash", line_color="green", annotation_text="利確1")
                fig.add_hline(y=row['利確2'], line_dash="dash", line_color="red", annotation_text="利確2")
                
                fig.update_layout(height=450, margin=dict(l=0, r=0, b=0, t=0), showlegend=False, xaxis_rangeslider_visible=False, yaxis=dict(fixedrange=True), xaxis=dict(fixedrange=True))
                st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
                
                c_inf, c_btn = st.columns([2, 1])
                with c_inf:
                    st.write(f"**現在:** {row['現在値']}円 | **指値:** {row['指値(入口)']}円")
                    st.write(f"**利確1:** {row['利確1']}円 | **利確2:** {row['利確2']}円")
                with c_btn:
                    if st.button(f"⭐ 保存", key=f"add_{s_type}_{row['コード']}"):
                        if add_bulk_to_list([row['コード']]): st.success("保存完了"); st.rerun()
        st.divider()
        st.dataframe(df_res.drop(columns=['df', 'is_buy']), use_container_width=True)
