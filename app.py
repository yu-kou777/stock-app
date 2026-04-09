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

def calculate_vwap(df, period=25):
    # 出来高加重平均価格（移動VWAP）
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    return (tp * df['Volume']).rolling(window=period).sum() / df['Volume'].rolling(window=period).sum()

# --- 4. データ取得 ---
def get_stock_data(code):
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
    try:
        df = yf.download(f"{code}.T", period="1y", interval="1d", progress=False)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            return df
    except: pass
    return pd.DataFrame()

# --- 5. 診断エンジン ---
def diagnose_stock(code, min_v):
    try:
        df = get_stock_data(code)
        if df.empty: return "データ取得失敗"
        df = df.dropna(subset=['Close']).astype(float)
        
        c = df['Close']
        df['MA20'] = c.rolling(20).mean()
        df['RCI9'] = calculate_rci(c, 9)
        df['RCI52'] = calculate_rci(c, 52) # 長期RCI(52)
        df['+DI'], df['-DI'], df['ADX'] = calculate_dmi(df)
        df['VWAP'] = calculate_vwap(df, 25) # 25日VWAP
        df['std'] = c.rolling(20).std(); df['BBU'] = df['MA20'] + 3*df['std']
        
        cur, pre = df.iloc[-1], df.iloc[-2]
        p = cur['Close']

        # フラグ
        dmi_gc = (pre['+DI'] < pre['-DI']) and (cur['+DI'] >= cur['-DI'])
        rci_gc = (pre['RCI9'] < pre['RCI52']) and (cur['RCI9'] >= cur['RCI52']) and (cur['RCI9'] < 0)
        rci_dc = (pre['RCI9'] > pre['RCI52']) and (cur['RCI9'] <= cur['RCI52']) and (cur['RCI9'] > 70)
        above_vwap = p > cur['VWAP']
        adx_up = cur['ADX'] > pre['ADX']
        vol_ok = df['Volume'].tail(5).mean() >= min_v

        # 判定
        if dmi_gc and vol_ok and (cur['RCI9'] > pre['RCI9']) and adx_up and above_vwap:
            status, color = "🚀 急騰直前 (High Potential)", "green"
        elif cur['ADX'] > cur['-DI'] and adx_up and cur['+DI'] > cur['-DI'] and above_vwap:
            status, color = "✨ 買い時 (Strong Buy)", "#00FF00"
        elif (p >= cur['BBU'] * 0.98) or rci_dc:
            status, color = "🛑 下落警戒 (Warning)", "red"
        elif cur['+DI'] > pre['+DI'] and (cur['+DI'] < cur['-DI'] or not above_vwap):
            status, color = "⚠️ だまし注意 (Fake Out)", "orange"
        else:
            status, color = "☁️ 様子見", "gray"

        checks = {
            "DMI ゴールデンクロス": dmi_gc,
            "RCI 短期・長期クロス(9>52)": rci_gc,
            "VWAP(25日)より上で推移": above_vwap,
            "ADX 上向き (勢いあり)": adx_up,
            "出来高クリア": vol_ok
        }

        return {"name": jpx_names.get(code, "銘柄"), "code": code, "price": int(p), "status": status, "color": color, "checks": checks, "df": df}
    except Exception as e: return f"エラー: {e}"

# --- 6. 画面構築 ---
st.title("🏹 Jack株AI: Sniper Precision")
st.sidebar.markdown("### ⚙️ パラメータ")
min_v = st.sidebar.number_input("最低出来高", 0, 1000000, 100000)

codes = st.text_area("診断コード (9984, 7203...)", "9984")
if st.button("🩺 精密診断 開始", type="primary"):
    for c in [x.strip() for x in codes.split(',') if x.strip()]:
        res = diagnose_stock(c, min_v)
        if isinstance(res, dict):
            st.markdown(f"### {res['name']} ({res['code']}) : {res['price']:,}円")
            st.markdown(f"<h3 style='color:{res['color']};'>判定: {res['status']}</h3>", unsafe_allow_html=True)
            
            c1, c2 = st.columns([1, 2])
            with c1:
                st.markdown("##### 📋 戦略チェック")
                for k, v in res['checks'].items(): st.write(f"{'✅' if v else '❌'} {k}")
            
            with c2:
                df = res['df']
                fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.5, 0.25, 0.25])
                
                # メイン: VWAPを追加(オレンジ点線)
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='価格'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['VWAP'], line=dict(color='orange', width=1.5, dash='dot'), name='25日VWAP'), row=1, col=1)
                
                # DMI
                fig.add_trace(go.Scatter(x=df.index, y=df['+DI'], line=dict(color='red', width=1.5), name='+DI'), row=2, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['-DI'], line=dict(color='blue', width=1.5), name='-DI'), row=2, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['ADX'], line=dict(color='orange', width=2), name='ADX'), row=2, col=1)
                
                # RCI (短期9 vs 長期52)
                fig.add_trace(go.Scatter(x=df.index, y=df['RCI9'], line=dict(color='red', width=1.5), name='RCI 短期(9)'), row=3, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['RCI52'], line=dict(color='navy', width=1.5), name='RCI 長期(52)'), row=3, col=1)
                fig.add_hline(y=0, line_dash="dash", line_color="gray", row=3, col=1)
                
                fig.update_layout(height=750, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
            st.divider()
