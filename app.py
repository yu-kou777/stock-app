import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import requests
from io import BytesIO
import time

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Pro: 診断", page_icon="🦅")

# --- 2. 銘柄名取得（JPX公式） ---
@st.cache_data(ttl=86400)
def get_jpx_names():
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=headers)
        df = pd.read_excel(BytesIO(res.content), engine='xlrd')
        return dict(zip(df['コード'].astype(str), df['銘柄名']))
    except: return {}

jpx_names = get_jpx_names()

# --- 3. 自作テクニカル指標 ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0); down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period-1, adjust=False).mean()
    ema_down = down.ewm(com=period-1, adjust=False).mean()
    return 100 - (100 / (1 + (ema_up / ema_down)))

def calculate_rci(series, period):
    def rci_logic(s):
        n = len(s); tr = list(range(n, 0, -1)); pr = pd.Series(s).rank(ascending=False).tolist()
        return (1 - (6 * sum((t - p) ** 2 for t, p in zip(tr, pr))) / (n * (n**2 - 1))) * 100
    return series.rolling(window=period).apply(rci_logic)

def calculate_dmi(df, period=14):
    h, l, c = df['High'], df['Low'], df['Close']; pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    um, dm = h - h.shift(1), l.shift(1) - l
    pdm, mdm = pd.Series(0.0, index=df.index), pd.Series(0.0, index=df.index)
    pdm[(um > dm) & (um > 0)] = um; mdm[(dm > um) & (dm > 0)] = dm
    def rma(s, p): return s.ewm(alpha=1/p, adjust=False).mean()
    atr = rma(tr, period); pdi = 100 * rma(pdm, period) / atr; mdi = 100 * rma(mdm, period) / atr
    adx = rma(100 * (pdi - mdi).abs() / (pdi + mdi), period)
    return pdi, mdi, adx

# --- 4. 診断エンジン ---
def diagnose_stock(code, min_v, rsi_t, rci_t):
    ticker = f"{code}.T"
    try:
        # 💡 Yahooのブロックを突破する変装設定
        headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1'}
        
        # yfinanceの最新のやり方でデータ取得
        df = yf.download(ticker, period="1y", interval="1d", progress=False, timeout=10)
        
        # データが取れなかった時のリトライ
        if df.empty:
            time.sleep(2)
            df = yf.download(ticker, period="1y", interval="1d", progress=False)

        if df.empty: return None

        # 列名の整理（マルチインデックス対策）
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 指標計算
        c = df['Close']; p = c.iloc[-1]; pre_p = c.iloc[-2]
        df['MA20'], df['MA60'], df['MA200'] = c.rolling(20).mean(), c.rolling(60).mean(), c.rolling(200).mean()
        df['RSI'] = calculate_rsi(c)
        df['RCI9'], df['RCI26'] = calculate_rci(c, 9), calculate_rci(c, 26)
        df['+DI'], df['-DI'], df['ADX'] = calculate_dmi(df)
        df['std'] = c.rolling(20).std(); df['BBL'], df['BBU'] = df['MA20'] - 3*df['std'], df['MA20'] + 3*df['std']
        
        cur_rsi, cur_rci9, cur_rci26 = df['RSI'].iloc[-1], df['RCI9'].iloc[-1], df['RCI26'].iloc[-1]
        pre_rci9, pre_rci26 = df['RCI9'].iloc[-2], df['RCI26'].iloc[-2]

        # 判定
        chk = {
            "出来高クリア": df['Volume'].tail(5).mean() >= min_v,
            "RSI 底値圏": cur_rsi <= rsi_t,
            "RCI 底値圏": cur_rci9 <= rci_t,
            "BB ±3σ接近": (p <= df['BBL'].iloc[-1]*1.03) or (p >= df['BBU'].iloc[-1]*0.97),
            "トレンド一致": (df['MA20'].iloc[-1]>df['MA20'].iloc[-3] and df['MA60'].iloc[-1]>df['MA60'].iloc[-3] and df['MA200'].iloc[-1]>df['MA200'].iloc[-3]),
            "DMI 上昇気配": df['+DI'].iloc[-1]>df['+DI'].iloc[-2] and df['ADX'].iloc[-1]>25,
            "RCI クロス": (pre_rci9 < pre_rci26 and cur_rci9 > cur_rci26 and cur_rci9 < 0) or (pre_rci9 > pre_rci26 and cur_rci9 < cur_rci26 and cur_rci9 > 70)
        }

        # タイミング診断
        if (pre_rci9 > pre_rci26 and cur_rci9 < cur_rci26 and cur_rci9 > 70): tmg, col = "⏳ 数日待つべき (天井圏DC)", "red"
        elif (pre_rci9 < pre_rci26 and cur_rci9 > cur_rci26 and cur_rci9 < 0): tmg, col = "🌇 大引け前に買うべき (反発初動)", "green"
        elif chk["RSI"] or chk["RCI"] or chk["BB"]: tmg, col = "🌅 翌朝の寄り付きで買うべき (底打ち確認)", "blue"
        else: tmg, col = "☁️ 様子見", "gray"

        return {"name": jpx_names.get(code, "不明"), "code": code, "price": int(p), "timing": tmg, "color": col, "checks": chk, "df": df}
    except: return None

# --- 5. 画面構築 ---
st.title("🏹 Stock Sniper Pro: 精密診断")
st.sidebar.markdown("### ⚙️ 判定基準")
min_v = st.sidebar.number_input("最低出来高", 0, 1000000, 100000)
rsi_t = st.sidebar.slider("RSI基準", 0, 100, 40)
rci_t = st.sidebar.slider("RCI基準", -100, 100, -50)

codes = st.text_area("銘柄コード (例: 9984, 7203)", "9984")
if st.button("🩺 診断を開始", type="primary"):
    for c in [x.strip() for x in codes.split(',') if x.strip()]:
        res = diagnose_stock(c, min_v, rsi_t, rci_t)
        if res:
            st.markdown(f"### {res['name']} ({res['code']}) : {res['price']:,}円")
            st.markdown(f"<h4 style='color:{res['color']}'>🤖 AI診断: {res['timing']}</h4>", unsafe_allow_html=True)
            c1, c2 = st.columns([1, 2])
            with c1:
                for k, v in res['checks'].items(): st.write(f"{'✅' if v else '❌'} {k}")
            with c2:
                fig = go.Figure(data=[go.Candlestick(x=res['df'].index, open=res['df']['Open'], high=res['df']['High'], low=res['df']['Low'], close=res['df']['Close'])])
                fig.update_layout(height=300, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
            st.divider()
        else:
            st.error(f"{c}: 現在データが取れません。時間をおいて再試行してください。")
