import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from io import BytesIO
import numpy as np

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Jack株AI: Sniper Precision v5.0", page_icon="🏹")

# --- 2. 共通計算ロジック ---
def calculate_rci(series, period):
    def rci_logic(s):
        n = len(s); tr = list(range(n, 0, -1)); pr = pd.Series(s).rank(ascending=False).tolist()
        return (1 - (6 * sum((t - p) ** 2 for t, p in zip(tr, pr))) / (n * (n**2 - 1))) * 100
    return series.rolling(window=period).apply(rci_logic)

def calculate_dmi(df, period=14):
    h, l, c = df['High'], df['Low'], df['Close']; pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    um, dm = h - h.shift(1), l.shift(1) - l
    pdm = um.where((um > dm) & (um > 0), 0); mdm = dm.where((dm > um) & (dm > 0), 0)
    def rma(s, p): return s.ewm(alpha=1/p, adjust=False).mean()
    atr = rma(tr, period); pdi = 100 * rma(pdm, period) / atr; mdi = 100 * rma(mdm, period) / atr
    adx = rma(100 * (pdi - mdi).abs() / (pdi + mdi), period)
    return pdi, mdi, adx

def calculate_psychological(df, period=12):
    diff = df['Close'].diff(); positive = (diff > 0).astype(int)
    return (positive.rolling(window=period).sum() / period) * 100

def calculate_vwap(df, period=25):
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    return (tp * df['Volume']).rolling(window=period).sum() / df['Volume'].rolling(window=period).sum()

@st.cache_data(ttl=86400)
def get_jpx_names():
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}; res = requests.get(url, headers=headers)
        df = pd.read_excel(BytesIO(res.content), engine='xlrd')
        return dict(zip(df['コード'].astype(str), df['銘柄名']))
    except: return {}

jpx_names = get_jpx_names()

# --- 3. 診断エンジン ---
def diagnose_stock(code, min_v):
    try:
        df = yf.download(f"{code}.T", period="2y", interval="1d", progress=False)
        if df.empty: return "データ取得失敗"
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=['Close']).astype(float)
        
        c = df['Close']
        df['R9'] = calculate_rci(c, 9); df['R27'] = calculate_rci(c, 27)
        df['PDI'], df['MDI'], df['ADX'] = calculate_dmi(df)
        df['Psy'] = calculate_psychological(df, 12); df['VWAP'] = calculate_vwap(df, 25)
        df['MA200'] = c.rolling(200).mean()
        
        cur, pre = df.iloc[-1], df.iloc[-2]
        p = cur['Close']

        # 判定ロジック
        rci_gc = (pre['R9'] < pre['R27']) and (cur['R9'] >= cur['R27']) and (cur['R9'] <= 0)
        dmi_gc = (pre['PDI'] < pre['MDI']) and (cur['PDI'] >= cur['MDI'])
        psy_50_plus = (cur['Psy'] >= 50)
        psy_75_plus = (cur['Psy'] >= 75)
        
        if rci_gc and psy_50_plus:
            status, color = "🎯 第1段階：最速狙撃 (RCI GC + Psy 50)", "#00FFFF"
        elif dmi_gc and psy_50_plus:
            status, color = "🔥 第2段階：トレンド追撃 (DMI GC)", "#00FF00"
        elif psy_75_plus and cur['R27'] > pre['R27']:
            status, color = "🚀 第3段階：加速・フル乗車 (Psy 75+)", "orange"
        elif cur['R27'] < pre['R27'] or cur['Psy'] < 50:
            status, color = "🛑 最終：撤退・利確警告", "red"
        else:
            status, color = "☁️ 条件待機・巡回中", "gray"

        checks = {
            "RCI ゴールデンクロス (0以下)": rci_gc,
            "サイコロジカル 50%以上 (心理好転)": psy_50_plus,
            "DMI ゴールデンクロス (+DI > -DI)": dmi_gc,
            "サイコロジカル 75%以上 (強気継続)": psy_75_plus,
            "25日VWAPより上で推移": p > cur['VWAP']
        }
        return {"name": jpx_names.get(code, "銘柄"), "code": code, "price": int(p), "status": status, "color": color, "df": df, "checks": checks}
    except Exception as e: return f"エラー: {e}"

# --- 4. UI構築 ---
st.title("🏹 Jack株AI: Sniper Precision v5.0")
codes_input = st.text_area("診断コード (カンマ区切り)", "9984, 8035, 6226, 6146")
if st.button("🩺 スナイパー診断 実行", type="primary"):
    code_list = [x.strip() for x in codes_input.split(',') if x.strip()]
    for c in code_list:
        res = diagnose_stock(c, 100000)
        if isinstance(res, dict):
            st.markdown(f"### {res['name']} ({res['code']})")
            st.markdown(f"<h2 style='color:{res['color']};'>{res['status']}</h2>", unsafe_allow_html=True)
            col_l, col_r = st.columns([1, 3])
            with col_l:
                st.write(f"**現在値: {res['price']:,}円**")
                for k, v in res['checks'].items(): st.write(f"{'✅' if v else '❌'} {k}")
            with col_r:
                d = res['df'].tail(50); fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03)
                fig.add_trace(go.Candlestick(x=d.index, open=d['Open'], high=d['High'], low=d['Low'], close=d['Close'], name='価格'), row=1, col=1)
                fig.add_trace(go.Scatter(x=d.index, y=d['VWAP'], line=dict(color='orange', width=2), name='VWAP'), row=1, col=1)
                fig.add_trace(go.Scatter(x=d.index, y=d['PDI'], line=dict(color='red'), name='+DI'), row=2, col=1)
                fig.add_trace(go.Scatter(x=d.index, y=d['-DI'], line=dict(color='blue'), name='-DI'), row=2, col=1)
                fig.add_trace(go.Scatter(x=d.index, y=d['ADX'], line=dict(color='orange', width=2), name='ADX'), row=2, col=1)
                fig.add_trace(go.Scatter(x=d.index, y=d['R9'], line=dict(color='red'), name='RCI9'), row=3, col=1)
                fig.add_trace(go.Scatter(x=d.index, y=d['R27'], line=dict(color='cyan'), name='RCI27'), row=3, col=1)
                fig.add_trace(go.Scatter(x=d.index, y=d['Psy'], line=dict(color='lime', width=2), fill='tozeroy', name='Psy'), row=4, col=1)
                fig.add_hline(y=50, line_dash="dash", row=4, col=1); fig.update_layout(height=800, template="plotly_dark", xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
            st.divider()
