import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from io import BytesIO

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Jack株AI: Stock Sniper Pro", page_icon="🏹")

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

# --- 3. 自作テクニカル計算 ---
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
    try:
        url = f"https://stooq.com/q/d/l/?s={code}.jp&i=d"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            df = pd.read_csv(BytesIO(res.content))
            if not df.empty and 'Close' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
                df = df.set_index('Date').sort_index()
                return df[['Open', 'High', 'Low', 'Close', 'Volume']].tail(250)
    except: pass
    try:
        df = yf.download(f"{code}.T", period="1y", interval="1d", progress=False, timeout=3)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            return df
    except: pass
    return pd.DataFrame()

# --- 5. 診断エンジン（Jack株AIロジック） ---
def diagnose_stock(code, min_v, rsi_t, rci_t):
    try:
        df = get_stock_data(code)
        if df.empty: return "データが見つかりません。"
        df = df.dropna(subset=['Close']).astype(float)
        
        c = df['Close']
        df['MA20'], df['MA60'], df['MA200'] = c.rolling(20).mean(), c.rolling(60).mean(), c.rolling(200).mean()
        df['RSI'] = calculate_rsi(c); df['RCI9'], df['RCI26'] = calculate_rci(c, 9), calculate_rci(c, 26)
        df['+DI'], df['-DI'], df['ADX'] = calculate_dmi(df)
        df['std'] = c.rolling(20).std(); df['BBL'], df['BBU'] = df['MA20'] - 3*df['std'], df['MA20'] + 3*df['std']
        
        cur, pre = df.iloc[-1], df.iloc[-2]
        p = cur['Close']

        # 🎯 Jack株AIロジック判定
        # 1. RCI反発（底値圏-80以下から上昇）
        rci_up = (pre['RCI9'] <= -80) and (cur['RCI9'] > pre['RCI9'])
        # 2. DMIゴールデンクロス (+DI > -DI)
        dmi_gc = (pre['+DI'] < pre['-DI']) and (cur['+DI'] >= cur['-DI'])
        # 3. ADX上昇
        adx_up = cur['ADX'] > pre['ADX']
        # 4. 確信（ADX > -DI）
        adx_strong = cur['ADX'] > cur['-DI']

        # 🛡️ だまし判定
        is_damashi = cur['+DI'] < cur['-DI'] and not adx_up

        chk = {
            "RCI短期 底値反発 (-80以下)": rci_up,
            "DMI ゴールデンクロス (+DI > -DI)": dmi_gc,
            "ADX 上向き (トレンド発生)": adx_up,
            "トレンド確信 (ADX > -DI)": adx_strong,
            "RSI・RCI 総合判断": cur['RSI'] <= rsi_t and cur['RCI9'] <= rci_t,
            "ボリンジャー ±3σ接近": (p <= cur['BBL']*1.03) or (p >= cur['BBU']*0.97),
            "出来高クリア": df['Volume'].tail(5).mean() >= min_v
        }

        # ⏱️ 究極のタイミング診断
        if dmi_gc and rci_up and adx_up:
            tmg, col = "🚀 【鉄板】大引け前に買うべき！ (ロケット発射合図)", "green"
        elif rci_up and (cur['+DI'] > pre['+DI']) and not dmi_gc:
            tmg, col = "🌅 翌朝の寄り付きで確認 (準備段階: GC待ち)", "blue"
        elif is_damashi and cur['RCI9'] > pre['RCI9']:
            tmg, col = "⚠️ 手出し無用！ (だまし: 一時的な自律反発)", "orange"
        elif cur['RCI9'] > 70 and pre['RCI9'] > cur['RCI9']:
            tmg, col = "⏳ 待機・利益確定 (天井圏)", "red"
        else:
            tmg, col = "☁️ 様子見 (条件未合致)", "gray"

        return {"name": jpx_names.get(code, "銘柄"), "code": code, "price": int(p), "timing": tmg, "color": col, "checks": chk, "df": df}
    except Exception as e: return f"エラー: {e}"

# --- 6. 画面構築 ---
st.title("🏹 Jack株AI: Stock Sniper Pro")
st.sidebar.markdown("### ⚙️ 精密診断設定")
min_v = st.sidebar.number_input("最低出来高", 0, 1000000, 100000)
rsi_t = st.sidebar.slider("RSI基準", 0, 100, 40)
rci_t = st.sidebar.slider("RCI基準", -100, 100, -50)

codes = st.text_area("診断したいコード (例: 9984, 7203)", "9984")
if st.button("🩺 Jack株AI 診断開始", type="primary"):
    for c in [x.strip() for x in codes.split(',') if x.strip()]:
        res = diagnose_stock(c, min_v, rsi_t, rci_t)
        if isinstance(res, dict):
            st.markdown(f"### {res['name']} ({res['code']}) : {res['price']:,}円")
            st.markdown(f"<h4 style='color:{res['color']}'>🤖 AI診断: {res['timing']}</h4>", unsafe_allow_html=True)
            
            col1, col2 = st.columns([1, 2])
            with col1:
                st.markdown("##### 📋 合否判定リスト")
                for k, v in res['checks'].items(): st.write(f"{'✅' if v else '❌'} {k}")
            
            with col2:
                df = res['df']
                # サブチャート付きのグラフ作成
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
                
                # メインチャート（ローソク足 + MA + BB）
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='価格'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='green', width=1), name='20MA'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['MA200'], line=dict(color='purple', width=1.5), name='200MA'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['BBL'], line=dict(color='lightblue', width=1, dash='dot'), name='-3σ'), row=1, col=1)
                
                # DMIチャート (+DI, -DI, ADX)
                fig.add_trace(go.Scatter(x=df.index, y=df['+DI'], line=dict(color='red', width=1.5), name='+DI (買勢)'), row=2, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['-DI'], line=dict(color='blue', width=1.5), name='-DI (売勢)'), row=2, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['ADX'], line=dict(color='orange', width=2), name='ADX (強度)'), row=2, col=1)
                fig.add_hline(y=25, line_dash="dash", line_color="gray", row=2, col=1)
                
                fig.update_layout(height=500, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False, showlegend=True)
                st.plotly_chart(fig, use_container_width=True)
            st.divider()
        else: st.error(f"{c}: {res}")
