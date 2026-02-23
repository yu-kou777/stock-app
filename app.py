import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
import plotly.graph_objects as go
import os

# --- 1. アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Pro", page_icon="🦅")

# --- 2. データベース & 保存機能 ---
SAVE_FILE = "watchlist.txt"

NAME_MAP = {
    "8035.T": "東京エレクトロン", "6920.T": "レーザーテック", "6857.T": "アドバンテスト",
    "6723.T": "ルネサス", "6758.T": "ソニーグループ", "6501.T": "日立製作所",
    "7735.T": "SCREEN", "6701.T": "NEC", "6702.T": "富士通", "6503.T": "三菱電機",
    "6861.T": "キーエンス", "6954.T": "ファナック", "6981.T": "村田製作所", "6971.T": "京セラ",
    "6902.T": "デンソー", "4063.T": "信越化学", "7203.T": "トヨタ自動車", "7267.T": "ホンダ",
    "7270.T": "SUBARU", "7201.T": "日産自動車", "6301.T": "小松製作所", "6367.T": "ダイキン工業",
    "7011.T": "三菱重工業", "7012.T": "川崎重工業", "7013.T": "IHI", "8306.T": "三菱UFJ",
    "8316.T": "三井住友", "8411.T": "みずほ", "8604.T": "野村HD", "8766.T": "東京海上",
    "8031.T": "三井物産", "8058.T": "三菱商事", "9101.T": "日本郵船", "9104.T": "商船三井",
    "9107.T": "川崎汽船", "5401.T": "日本製鉄", "5411.T": "JFE", "5406.T": "神戸製鋼所",
    "9984.T": "ソフトバンクG", "9432.T": "NTT", "6098.T": "リクルート", "4385.T": "メルカリ",
    "4755.T": "楽天グループ", "9983.T": "ファーストリテイリング", "1605.T": "INPEX",
    "5020.T": "ENEOS", "6330.T": "東洋エンジニアリング"
}

def load_saved_list():
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

def save_list(text):
    items = [i.strip() for i in text.split(',') if i.strip()]
    cleaned_text = ", ".join(items)
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        f.write(cleaned_text)

def add_to_list(ticker_code):
    current = load_saved_list()
    code_only = ticker_code.replace(".T", "")
    items = [i.strip() for i in current.split(',') if i.strip()]
    if code_only not in items:
        items.append(code_only)
        save_list(", ".join(items))
        return True
    return False

# --- 3. 高精度解析エンジン ---
def analyze_stock(ticker, min_p, max_p, is_force=False):
    try:
        tkr = yf.Ticker(ticker)
        df_d = tkr.history(period="6mo", interval="1d")
        if df_d.empty or len(df_d) < 60: return None

        price = df_d.iloc[-1]['Close']
        if not is_force and not (min_p <= price <= max_p): return None

        # テクニカル指標算出
        df_d['MA20'] = df_d['Close'].rolling(20).mean()
        df_d['MA60'] = df_d['Close'].rolling(60).mean()
        
        # MACD
        macd = ta.macd(df_d['Close'])
        df_d = pd.concat([df_d, macd], axis=1)
        
        # RSI
        df_d['RSI'] = ta.rsi(df_d['Close'], length=14)
        
        # 平均足
        ha_df = ta.ha(df_d['Open'], df_d['High'], df_d['Low'], df_d['Close'])
        df_d = pd.concat([df_d, ha_df], axis=1)

        # --- パターン検知ロジック ---
        patterns = []
        pattern_score = 0
        
        # 1. ダブルボトム近傍 (過去60日安値との乖離1.5%以内)
        low_60 = df_d['Low'].tail(60).min()
        if price <= low_60 * 1.015:
            patterns.append("🏺 Wボトム圏")
            pattern_score += 30
            
        # 2. フラッグ/スクエア (直近10日の振幅が3%以内)
        recent_range = (df_d['High'].tail(10).max() - df_d['Low'].tail(10).min()) / price
        if recent_range < 0.03:
            patterns.append("🏁 旗形/保合")
            pattern_score += 20

        # 3. 酒田五法 (赤三兵)
        if all(df_d['Close'].tail(3) > df_d['Open'].tail(3)) and all(df_d['Close'].tail(3).diff().dropna() > 0):
            patterns.append("🔥 赤三兵")
            pattern_score += 40

        # 精密指値 (コンフルエンス)
        # ボリバン-2σと過去安値の平均をとる
        std20 = df_d['Close'].rolling(20).std().iloc[-1]
        bb_low = df_d['MA20'].iloc[-1] - (std20 * 2)
        precision_floor = int((bb_low + low_60) / 2)

        # 判定
        score = pattern_score
        if df_d['MACDh_12_26_9'].iloc[-1] > 0: score += 20 # MACDヒストグラム陽転
        if df_d['HA_close'].iloc[-1] > df_d['HA_open'].iloc[-1]: score += 20 # 平均足陽線
        if df_d['RSI'].iloc[-1] < 35: score += 30 # RSI売られすぎ

        if score >= 70: judge = "🚀 超精密買"
        elif score >= 30: judge = "✨ 買目線"
        elif score <= -30: judge = "☔ 売目線"
        else: judge = "☁️ 様子見"

        return {
            "コード": ticker.replace(".T",""), "和名": NAME_MAP.get(ticker, "不明"),
            "現在値": int(price), "判定": judge, "スコア": int(score), 
            "RSI": round(df_d['RSI'].iloc[-1], 1), "精密指値": precision_floor, 
            "目標1(20日)": int(df_d['MA20'].iloc[-1]), "目標2(60日)": int(df_d['MA60'].iloc[-1]), 
            "df": df_d, "型": " / ".join(patterns) if patterns else "平常"
        }
    except: return None

# --- 4. 画面構築 ---
st.title("🏹 Stock Sniper Strategy Pro")

with st.expander("📚 解析ロジックの解説"):
    st.markdown("""
    - **精密指値 (青点線)**: 統計的下限と過去の反発安値を合成した、最も反発確率の高い価格。
    - **目標1 (緑点線)**: 現実的なリバウンド目標（20日線）。
    - **目標2 (赤点線)**: トレンド転換の壁（60日線）。
    - **型**: 酒田五法やチャートパターンから「現在の局面」を自動判別。
    """)

# サイドバー
st.sidebar.title("💰 検索・保存管理")
mode = st.sidebar.radio("検索対象", ["📊 市場全体", "⭐ 保存リスト", "📝 自由入力"])

saved_text = load_saved_list()

if mode == "📊 市場全体":
    ticker_list = list(NAME_MAP.keys()); is_force = False
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

min_p = st.sidebar.number_input("下限", 0, 100000, 1000)
max_p = st.sidebar.number_input("上限", 0, 100000, 100000)

if 'scan_results' not in st.session_state: st.session_state.scan_results = None

c1, c2, c3 = st.columns(3)
if c1.button("📑 全件スキャン"): st.session_state.scan_results = ("all", ticker_list)
if c2.button("🚀 買い・反発狙い"): st.session_state.scan_results = ("buy", ticker_list)
if c3.button("📉 空売り狙い"): st.session_state.scan_results = ("short", ticker_list)

if st.session_state.scan_results:
    s_type, targets = st.session_state.scan_results
    results = []
    bar = st.progress(0)
    for i, t in enumerate(targets):
        res = analyze_stock(t, min_p, max_p, is_force)
        if res: results.append(res)
        bar.progress((i + 1) / len(targets))
    
    if results:
        df_res = pd.DataFrame(results).sort_values("スコア", ascending=False)
        if s_type == "buy": df_res = df_res[df_res['スコア'] >= 20]
        elif s_type == "short": df_res = df_res[df_res['スコア'] <= -20]

        for _, row in df_res.iterrows():
            with st.expander(f"{row['判定']} | {row['和名']} ({row['コード']}) {row['型']}"):
                # --- チャート表示 ---
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=row['df'].index, open=row['df']['Open'], high=row['df']['High'], low=row['df']['Low'], close=row['df']['Close'], name='価格'))
                fig.add_trace(go.Scatter(x=row['df'].index, y=row['df']['MA20'], line=dict(color='green', width=1), name='20MA'))
                fig.add_trace(go.Scatter(x=row['df'].index, y=row['df']['MA60'], line=dict(color='orange', width=1), name='60MA'))
                
                # 水平線
                fig.add_hline(y=row['精密指値'], line_dash="dash", line_color="royalblue", annotation_text="精密指値")
                fig.add_hline(y=row['目標1(20日)'], line_dash="dash", line_color="green", annotation_text="目標1")
                fig.add_hline(y=row['目標2(60日)'], line_dash="dash", line_color="red", annotation_text="目標2")
                
                fig.update_layout(height=450, margin=dict(l=0, r=0, b=0, t=0), showlegend=False, xaxis_rangeslider_visible=False, yaxis=dict(fixedrange=True), xaxis=dict(fixedrange=True))
                st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
                
                # 情報表示 & 保存
                c_inf, c_btn = st.columns([2, 1])
                with c_inf:
                    st.write(f"**スコア:** {row['スコア']} | **型:** {row['型']}")
                    st.write(f"**精密指値:** {row['精密指値']}円 / **RSI:** {row['RSI']}")
                with c_btn:
                    if st.button(f"⭐ 保存", key=f"add_{s_type}_{row['コード']}"):
                        if add_to_list(row['コード']): st.success(f"保存しました"); st.rerun()
        
        st.divider()
        st.dataframe(df_res.drop(columns=['df']), use_container_width=True)
