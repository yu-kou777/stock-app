import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import os
import requests
from io import BytesIO
import concurrent.futures

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Pro", page_icon="🦅")

# --- 2. データベース & JPX全銘柄名簿の自動取得 ---
SAVE_FILE = "watchlist.txt"

@st.cache_data(ttl=86400)
def get_jpx_master():
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        
        df = pd.read_excel(BytesIO(res.content), engine='xlrd')
        prime = df[df['市場・商品区分'].str.contains('プライム', na=False)]['コード'].astype(str).tolist()
        standard = df[df['市場・商品区分'].str.contains('スタンダード', na=False)]['コード'].astype(str).tolist()
        names = dict(zip(df['コード'].astype(str), df['銘柄名']))
        return {"prime": prime, "standard": standard, "names": names}
    except Exception as e:
        st.error(f"銘柄リストの取得に失敗しました: {e}")
        return {"prime": [], "standard": [], "names": {}}

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

# --- テクニカル指標の自作計算関数 ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period-1, adjust=False).mean()
    ema_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))

def calculate_rci(series, period=9):
    def rci_logic(s):
        n = len(s)
        time_ranks = list(range(n, 0, -1))
        price_ranks = pd.Series(s).rank(ascending=False).tolist()
        sum_d2 = sum((tr - pr) ** 2 for tr, pr in zip(time_ranks, price_ranks))
        return (1 - (6 * sum_d2) / (n * (n**2 - 1))) * 100
    return series.rolling(window=period).apply(rci_logic)

# --- 3. 解析エンジン ---
def analyze_stock(ticker, min_p, max_p, rsi_range, rci_range, ma60_filter, ma200_filter, is_force=False):
    try:
        tkr = yf.Ticker(ticker)
        # MA200を計算するため、データ取得期間を「1年」に延長
        df = tkr.history(period="1y", interval="1d", actions=False)
        if df.empty or len(df) < 200: return None
        
        price = df.iloc[-1]['Close']
        if not is_force and not (min_p <= price <= max_p): return None

        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        df['MA200'] = df['Close'].rolling(200).mean() # 追加：200日移動平均線
        df['RSI'] = calculate_rsi(df['Close'], period=14)
        df['RCI'] = calculate_rci(df['Close'], period=9)
        
        curr_rsi = df['RSI'].iloc[-1]
        curr_rci = df['RCI'].iloc[-1]
        curr_ma60 = df['MA60'].iloc[-1]
        curr_ma200 = df['MA200'].iloc[-1]

        # フィルタリング機能
        if not is_force:
            if not (rsi_range[0] <= curr_rsi <= rsi_range[1]): return None
            if not (rci_range[0] <= curr_rci <= rci_range[1]): return None
            
            # オンオフボタンの条件（MAの上下5%以内を「付近」と定義）
            if ma60_filter:
                if pd.isna(curr_ma60) or not (0.95 <= price / curr_ma60 <= 1.05): return None
            if ma200_filter:
                if pd.isna(curr_ma200) or not (0.95 <= price / curr_ma200 <= 1.05): return None

        low_60 = df['Low'].tail(60).min()
        std20 = df['Close'].rolling(20).std().iloc[-1]
        score = 0
        if curr_rsi < 30: score += 30
        if curr_rci < -80: score += 30
        if price <= low_60 * 1.015: score += 20
        
        p_floor = int((df['MA20'].iloc[-1] - (std20 * 2) + low_60) / 2)
        judge = "🚀 超精密買" if score >= 50 else "✨ 買目線" if score >= 20 else "☁️ 様子見"

        code_only = ticker.replace(".T","")
        return {
            "コード": code_only, "和名": jpx["names"].get(code_only, "不明"),
            "現在値": int(price), "判定": judge, "スコア": int(score), 
            "RSI": round(curr_rsi, 1), "RCI": round(curr_rci, 1),
            "指値": p_floor, "df": df
        }
    except: return None

# --- 4. 画面構築 ---
st.title("🏹 Stock Sniper Pro: RSI & RCI Edition")

# 📖 評価図柄（アイコン）と機能の説明
with st.expander("📖 評価図柄（アイコン）と機能の説明を見る", expanded=False):
    st.markdown("""
    ### 🎯 判定アイコンの意味
    * **🚀 超精密買 (スコア50以上)**: RSI・RCIが共に底値圏にあり、直近安値に接近している「最強の反発チャンス」銘柄です。
    * **✨ 買目線 (スコア20以上)**: 売られすぎ水準に入り始めており、エントリーの準備・監視をしても良い銘柄です。
    * **☁️ 様子見 (スコア20未満)**: 現在は明確な反発シグナルが出ていない、または下落の途中の銘柄です。

    ### 📈 MA（移動平均線）反発フィルタ
    サイドバーのスイッチをオンにすると、以下の条件に合致する銘柄のみを抽出します。
    * **🟢 MA60付近**: 株価が「60日移動平均線」の上下5%以内に接近している銘柄。中期的な反発ラインとして強く意識されます。
    * **🔴 MA200付近**: 株価が「200日移動平均線」の上下5%以内に接近している銘柄。長期的な大底や、絶好の押し目買いチャンスになります。
    """)

# サイドバー設定
st.sidebar.title("💰 検索・フィルタ")
mode = st.sidebar.radio("対象市場", ["📊 プライム", "🏛️ スタンダード", "⭐ 保存リスト"])

saved_text = load_saved_list()
is_force = False

if mode == "⭐ 保存リスト":
    input_area = st.sidebar.text_area("ウォッチリスト (カンマ区切り)", saved_text, height=150)
    c_s, c_c = st.sidebar.columns(2)
    if c_s.button("💾 保存"): save_list(input_area); st.rerun()
    if c_c.button("🗑️ 全消去"): save_list(""); st.rerun()
    targets = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_area.split(',') if t.strip()]
    is_force = True
else:
    targets = [f"{c}.T" for c in (jpx["prime"] if mode=="📊 プライム" else jpx["standard"])]

st.sidebar.divider()
st.sidebar.subheader("🎯 反発ライン絞り込み")
# ★追加：MA60とMA200のオンオフスイッチ（トグル）
ma60_filter = st.sidebar.toggle("🟢 MA60(60日線)付近の銘柄", value=False)
ma200_filter = st.sidebar.toggle("🔴 MA200(200日線)付近の銘柄", value=False)

st.sidebar.divider()
min_p = st.sidebar.number_input("株価下限", 0, 100000, 500)
max_p = st.sidebar.number_input("株価上限", 0, 100000, 5000)

st.sidebar.subheader("📈 指標フィルタ")
rsi_range = st.sidebar.slider("RSI範囲", 0, 100, (0, 40)) 
rci_range = st.sidebar.slider("RCI範囲", -100, 100, (-100, -50))

# 実行ボタン
if st.button("🛰️ スキャン開始"):
    if not targets:
        st.warning("⚠️ 検索対象の銘柄がありません。")
    else:
        results = []
        bar = st.progress(0)
        MAX_DISPLAY = 50
        
        # 並列処理で爆速スキャン
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_ticker = {executor.submit(analyze_stock, t, min_p, max_p, rsi_range, rci_range, ma60_filter, ma200_filter, is_force): t for t in targets}
            
            for i, future in enumerate(concurrent.futures.as_completed(future_to_ticker)):
                res = future.result()
                if res:
                    results.append(res)
                    if not is_force and len(results) >= MAX_DISPLAY:
                        st.warning(f"⚠️ ヒット数が多いため、上位{MAX_DISPLAY}件で停止しました。")
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                
                bar.progress(min((i + 1) / len(targets), 1.0))

        if results:
            df_res = pd.DataFrame(results).sort_values("スコア", ascending=False)
            st.success(f"🎯 検索が完了しました（{len(results)} 件）")
            
            for _, row in df_res.iterrows():
                with st.expander(f"{row['判定']} | {row['和名']} ({row['コード']}) RSI:{row['RSI']} / RCI:{row['RCI']}"):
                    fig = go.Figure(data=[go.Candlestick(x=row['df'].index, open=row['df']['Open'], high=row['df']['High'], low=row['df']['Low'], close=row['df']['Close'], name='価格')])
                    
                    # ★追加：移動平均線をチャートに表示
                    fig.add_trace(go.Scatter(x=row['df'].index, y=row['df']['MA20'], line=dict(color='green', width=1), name='20MA(緑)'))
                    fig.add_trace(go.Scatter(x=row['df'].index, y=row['df']['MA60'], line=dict(color='orange', width=1), name='60MA(橙)'))
                    fig.add_trace(go.Scatter(x=row['df'].index, y=row['df']['MA200'], line=dict(color='purple', width=1.5), name='200MA(紫)'))

                    fig.add_hline(y=row['指値'], line_dash="dash", line_color="royalblue", annotation_text="指値")
                    fig.update_layout(height=400, margin=dict(l=0, r=0, b=0, t=0), xaxis_rangeslider_visible=False, showlegend=True)
                    st.plotly_chart(fig, use_container_width=True)
                    st.write(f"現在値: {row['現在値']}円 / **指値目安: {row['指値']}円**")
        else:
            st.info("条件に合う銘柄は見つかりませんでした。フィルタ設定を見直してください。")

