import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from io import BytesIO

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Jack株AI: Sniper Precision", page_icon="🏹")

# --- 2. 銘柄名取得（JPX） ---
@st.cache_data(ttl=86400)
def get_jpx_names():
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers)
        df = pd.read_excel(BytesIO(res.content), engine='xlrd')
        return dict(zip(df['コード'].astype(str), df['銘柄名']))
    except: return {}

jpx_names = get_jpx_names()

# --- 3. テクニカル計算関数 ---
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

# --- 4. データ取得エンジン ---
def get_stock_data(code):
    # ルート1：Stooq (CSV直接)
    try:
        url = f"https://stooq.com/q/d/l/?s={code}.jp&i=d"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            df = pd.read_csv(BytesIO(res.content))
            if not df.empty and 'Close' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
                df = df.set_index('Date').sort_index()
                return df[['Open', 'High', 'Low', 'Close', 'Volume']].tail(250)
    except: pass
    # ルート2：Yahoo
    try:
        df = yf.download(f"{code}.T", period="1y", interval="1d", progress=False)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            return df
    except: pass
    return pd.DataFrame()

# --- 5. 診断エンジン（改良型Jackロジック） ---
def diagnose_stock(code, min_v, rsi_t, rci_t):
    try:
        df = get_stock_data(code)
        if df.empty: return "データ取得失敗"
        df = df.dropna(subset=['Close']).astype(float)
        
        c = df['Close']
        df['MA20'], df['MA60'], df['MA200'] = c.rolling(20).mean(), c.rolling(60).mean(), c.rolling(200).mean()
        df['RSI'] = calculate_rsi(c); df['RCI9'] = calculate_rci(c, 9)
        df['+DI'], df['-DI'], df['ADX'] = calculate_dmi(df)
        df['std'] = c.rolling(20).std(); df['BBL'], df['BBU'] = df['MA20'] - 3*df['std'], df['MA20'] + 3*df['std']
        
        cur, pre = df.iloc[-1], df.iloc[-2]
        avg_vol = df['Volume'].tail(5).mean()
        p = cur['Close']

        # 各種フラグ
        dmi_gc = (pre['+DI'] < pre['-DI']) and (cur['+DI'] >= cur['-DI'])
        dmi_dc = (pre['+DI'] > pre['-DI']) and (cur['+DI'] <= cur['-DI'])
        vol_ok = avg_vol >= min_v
        rci_up = cur['RCI9'] > pre['RCI9'] and pre['RCI9'] <= -80
        adx_up = cur['ADX'] > pre['ADX']
        adx_down = cur['ADX'] < pre['ADX']
        adx_strong = cur['ADX'] > cur['-DI']
        bb_limit = (p <= cur['BBL']*1.03) or (p >= cur['BBU']*0.97)
        bb_over_upper = p >= cur['BBU'] * 0.98

        # 🎯 4段階判定
        if dmi_gc and vol_ok and rci_up and adx_up:
            status, color = "🚀 急騰直前 (High Potential)", "green"
        elif adx_strong and adx_up and cur['+DI'] > cur['-DI'] and not bb_limit:
            status, color = "✨ 買い時 (Strong Buy)", "#00FF00" # 明るい緑
        elif bb_over_upper or (cur['RSI'] >= 70 and adx_down) or dmi_dc:
            status, color = "🛑 下落気配 (Warning / Sell)", "red"
        elif cur['+DI'] > pre['+DI'] and (cur['+DI'] < cur['-DI'] or not adx_up):
            status, color = "⚠️ だまし注意 (Fake Out / 自律反発)", "orange"
        else:
            status, color = "☁️ 様子見 (Wait / Neutral)", "gray"

        checks = {
            "DMI ゴールデンクロス": dmi_gc,
            "出来高クリア": vol_ok,
            "RCI短期 底値反発": cur['RCI9'] > pre['RCI9'],
            "ADX 上向き (勢いあり)": adx_up,
            "トレンド確信 (ADX > -DI)": adx_strong,
            "過熱感なし (BB±3σ未到達)": not bb_limit
        }

        return {"name": jpx_names.get(code, "銘柄"), "code": code, "price": int(p), "status": status, "color": color, "checks": checks, "df": df}
    except Exception as e: return f"エラー: {e}"

# --- 6. 画面構築 ---
st.title("🏹 Jack株AI: Sniper Precision")
st.sidebar.markdown("### ⚙️ 戦略パラメータ")
min_v = st.sidebar.number_input("最低出来高", 0, 1000000, 100000)
rsi_t = st.sidebar.slider("RSI 底値圏基準", 0, 100, 40)
rci_t = st.sidebar.slider("RCI 底値圏基準", -100, 100, -50)

codes = st.text_area("診断したいコード (例: 9984, 7203)", "9984")
if st.button("🩺 精密スナイパー診断 開始", type="primary"):
    for c in [x.strip() for x in codes.split(',') if x.strip()]:
        res = diagnose_stock(c, min_v, rsi_t, rci_t)
        if isinstance(res, dict):
            st.markdown(f"### {res['name']} ({res['code']}) : {res['price']:,}円")
            st.markdown(f"<h3 style='color:{res['color']}; background-color: rgba(0,0,0,0.1); padding: 10px; border-radius: 5px;'>判定: {res['status']}</h3>", unsafe_allow_html=True)
            
            c1, c2 = st.columns([1, 2])
            with c1:
                st.markdown("##### 📋 戦略合致チェック")
                for k, v in res['checks'].items():
                    st.write(f"{'✅' if v else '❌'} {k}")
                if "だまし" in res['status']:
                    st.warning("【分析】$+DI$の上昇が見られますが、$-DI$を抜けていないかADXが弱いため、一時的な反発に終わるリスクが高いです。GCまで待機！")
            
            with c2:
                df = res['df']
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='価格'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='green', width=1), name='20MA'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['BBU'], line=dict(color='pink', width=1, dash='dot'), name='+3σ'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['BBL'], line=dict(color='lightblue', width=1, dash='dot'), name='-3σ'), row=1, col=1)
                
                fig.add_trace(go.Scatter(x=df.index, y=df['+DI'], line=dict(color='red', width=1.5), name='+DI'), row=2, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['-DI'], line=dict(color='blue', width=1.5), name='-DI'), row=2, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['ADX'], line=dict(color='orange', width=2.5), name='ADX'), row=2, col=1)
                fig.update_layout(height=550, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
            st.divider()
        else: st.error(f"{c}: {res}")
