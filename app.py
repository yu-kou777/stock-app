import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests
from io import BytesIO
import time

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Pro: 診断", page_icon="🦅")

# --- 2. 銘柄名取得（JPX） ---
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

# --- 3. 指標計算ロジック ---
def calculate_rsi(series, period=14):
    delta = series.diff(); up = delta.clip(lower=0); down = -1 * delta.clip(upper=0)
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
        # 💡 yf.download の最新仕様で取得（最もブロックに強い方法）
        df = yf.download(ticker, period="1y", interval="1d", progress=False, timeout=15)
        
        # 取得失敗時のリトライ
        if df.empty:
            time.sleep(2)
            df = yf.download(ticker, period="1y", interval="1d", progress=False)

        if df.empty: return "empty"

        # マルチインデックス対応（最新版のyfinance対策）
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 計算
        c = df['Close']
        df['MA20'], df['MA60'], df['MA200'] = c.rolling(20).mean(), c.rolling(60).mean(), c.rolling(200).mean()
        df['RSI'] = calculate_rsi(c); df['RCI9'], df['RCI26'] = calculate_rci(c, 9), calculate_rci(c, 26)
        df['+DI'], df['-DI'], df['ADX'] = calculate_dmi(df); df['std'] = c.rolling(20).std()
        df['BBL'], df['BBU'] = df['MA20'] - 3*df['std'], df['MA20'] + 3*df['std']
        
        cur, pre = df.iloc[-1], df.iloc[-2]
        p = float(cur['Close'])
        
        # 判定
        chk = {
            "出来高クリア": float(df['Volume'].tail(5).mean()) >= min_v,
            "RSI 底値圏": float(cur['RSI']) <= rsi_t,
            "RCI 底値圏": float(cur['RCI9']) <= rci_t,
            "BB ±3σ接近": (p <= float(cur['BBL'])*1.03) or (p >= float(cur['BBU'])*0.97),
            "PO (トレンド一致)": (cur['MA20']>pre['MA20'] and cur['MA60']>pre['MA60'] and cur['MA200']>pre['MA200']) or (cur['MA20']<pre['MA20'] and cur['MA60']<pre['MA60'] and cur['MA200']<pre['MA200']),
            "DMI (上昇気配)": cur['+DI']>pre['+DI'] and cur['ADX']>25,
            "RCI クロス": (pre['RCI9']<pre['RCI26'] and cur['RCI9']>cur['RCI26'] and cur['RCI9']<0) or (pre['RCI9']>pre['RCI26'] and cur['RCI9']<cur['RCI26'] and cur['RCI9']>70)
        }

        if (pre['RCI9']>pre['RCI26'] and cur['RCI9']<cur['RCI26'] and cur['RCI9']>70): tmg, col = "⏳ 待機 (天井圏DC)", "red"
        elif (pre['RCI9']<pre['RCI26'] and cur['RCI9']>cur['RCI26'] and cur['RCI9']<0): tmg, col = "🌇 大引け (反発GC)", "green"
        elif chk["RSI"] or chk["RCI"] or chk["BB"]: tmg, col = "🌅 翌朝寄り付き (反発確認)", "blue"
        else: tmg, col = "☁️ 様子見", "gray"

        return {"name": jpx_names.get(code, "銘柄"), "code": code, "price": int(p), "timing": tmg, "color": col, "checks": chk, "df": df}
    except Exception as e:
        return str(e)

# --- 5. 画面構築 ---
st.title("🏹 Stock Sniper Pro: 精密診断")
st.sidebar.markdown("### ⚙️ 設定")
min_v = st.sidebar.number_input("最低出来高", 0, 1000000, 100000)
rsi_t = st.sidebar.slider("RSI基準", 0, 100, 40)
rci_t = st.sidebar.slider("RCI基準", -100, 100, -50)

codes = st.text_area("銘柄コード (例: 9984, 7203)", "9984")
if st.button("🩺 診断開始", type="primary"):
    for c in [x.strip() for x in codes.split(',') if x.strip()]:
        res = diagnose_stock(c, min_v, rsi_t, rci_t)
        if isinstance(res, dict):
            st.markdown(f"### {res['name']} ({res['code']}) : {res['price']:,}円")
            st.markdown(f"<h4 style='color:{res['color']}'>🤖 判定: {res['timing']}</h4>", unsafe_allow_html=True)
            c1, c2 = st.columns([1, 2])
            with c1:
                for k, v in res['checks'].items(): st.write(f"{'✅' if v else '❌'} {k}")
            with c2:
                fig = go.Figure(data=[go.Candlestick(x=res['df'].index, open=res['df']['Open'], high=res['df']['High'], low=res['df']['Low'], close=res['df']['Close'])])
                fig.update_layout(height=300, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
            st.divider()
        else:
            st.error(f"{c}: データの取得に失敗しました。最新の部品(v0.2.52+)が正しく入っているか確認してください。")
