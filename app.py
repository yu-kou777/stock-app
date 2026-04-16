import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from io import BytesIO
import numpy as np

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Jack株AI: Sniper Precision", page_icon="🏹")

# --- 2. 銘柄名取得（JPX公式データ） ---
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

# --- 3. 指標計算ロジック ---
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
    atr = rma(tr, period); pdi = 100 * rma(pdm, period) / atr; mdi = 100 * mdm.rolling(window=period).mean() / atr # 修正
    pdi = 100 * rma(pdm, period) / atr
    mdi = 100 * rma(mdm, period) / atr
    adx = rma(100 * (pdi - mdi).abs() / (pdi + mdi), period)
    return pdi, mdi, adx

def calculate_vwap(df, period=25):
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    return (tp * df['Volume']).rolling(window=period).sum() / df['Volume'].rolling(window=period).sum()

def calculate_psychological(df, period=12):
    """サイコロジカルラインの計算"""
    diff = df['Close'].diff()
    positive = (diff > 0).astype(int)
    return (positive.rolling(window=period).sum() / period) * 100

# --- 4. データ取得エンジン ---
def get_stock_data(code):
    try:
        df = yf.download(f"{code}.T", period="2y", interval="1d", progress=False)
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
        df['RCI9'] = calculate_rci(c, 9)
        df['RCI27'] = calculate_rci(c, 27)
        df['+DI'], df['-DI'], df['ADX'] = calculate_dmi(df)
        df['VWAP'] = calculate_vwap(df, 25)
        df['Psy'] = calculate_psychological(df, 12)
        
        # 移動平均線
        df['MA25'] = c.rolling(25).mean()
        df['MA60'] = c.rolling(60).mean()
        df['MA200'] = c.rolling(200).mean()
        
        # ボリンジャー
        df['std'] = c.rolling(20).std(); df['MA20'] = c.rolling(20).mean(); df['BBU'] = df['MA20'] + 3*df['std']
        
        cur, pre = df.iloc[-1], df.iloc[-2]
        p = cur['Close']

        # --- 判定フラグ ---
        dmi_gc = (pre['+DI'] < pre['-DI']) and (cur['+DI'] >= cur['-DI'])
        rci_gc = (pre['RCI9'] < pre['RCI27']) and (cur['RCI9'] >= cur['RCI27']) and (cur['RCI9'] < 0)
        
        # サイコロジカル 50ボーダー ＆ 75トレンド
        psy_strong = cur['Psy'] >= 75
        psy_break = (pre['Psy'] <= 50) and (cur['Psy'] > 50)
        
        # DMI反転初動 (ADX低位 & +DI上昇開始)
        dmi_reversal = (cur['+DI'] > pre['+DI']) and (cur['ADX'] < 25) and (cur['+DI'] < 20)
        
        # トレンド判定 (Perfect Order)
        po_up = (p > cur['MA25']) and (cur['MA25'] > cur['MA60']) and (cur['MA60'] > cur['MA200'])
        
        above_vwap = p > cur['VWAP']
        adx_up = cur['ADX'] > pre['ADX']
        vol_ok = df['Volume'].tail(5).mean() >= min_v
        bb_limit = p >= cur['BBU'] * 0.98

        # --- AI総合ステータス判定 ---
        if po_up and psy_strong and above_vwap:
            status, color = "🚀 最強上昇トレンド (Perfect Order)", "#00FF00"
        elif dmi_gc and psy_break and vol_ok:
            status, color = "✨ 本格上昇開始 (Strong Signal)", "#00FFFF"
        elif dmi_reversal and rci_gc:
            status, color = "🐣 大底反転の初動 (Recovery Start)", "yellow"
        elif bb_limit or (cur['RCI9'] < pre['RCI9'] and cur['RCI9'] > 80):
            status, color = "🛑 下落警戒 (Overbought)", "red"
        elif (cur['+DI'] < cur['-DI']) and not above_vwap:
            status, color = "📉 下落トレンド継続 (Wait)", "orange"
        else:
            status, color = "☁️ 様子見 (Neutral)", "gray"

        checks = {
            "DMI ゴールデンクロス": dmi_gc,
            "RCI ゴールデンクロス": rci_gc,
            "VWAP(25日)より上で推移": above_vwap,
            "サイコロジカル 50%超え": cur['Psy'] > 50,
            "サイコロジカル 75%以上(強気)": psy_strong,
            "ADX 上向き (勢いあり)": adx_up,
            "パーフェクトオーダー成立": po_up
        }

        return {"name": jpx_names.get(code, "銘柄"), "code": code, "price": int(p), "status": status, "color": color, "df": df, "checks": checks}
    except Exception as e: return f"エラー: {e}"

# --- 6. UI構築 ---
st.title("🏹 Jack株AI: Sniper Precision v2.0")
st.sidebar.markdown("### ⚙️ 精密設定")
min_v = st.sidebar.number_input("最低出来高(5日平均)", 0, 1000000, 100000)

codes_input = st.text_area("診断銘柄コード (カンマ区切り)", "9984, 8035, 6226, 6146")
if st.button("🩺 スナイパー診断 開始", type="primary"):
    code_list = [x.strip() for x in codes_input.split(',') if x.strip()]
    hit_codes = [] 
    
    for c in code_list:
        res = diagnose_stock(c, min_v)
        if isinstance(res, dict):
            hit_codes.append(res['code'])
            display_df = res['df'].tail(40) # 40日分表示してトレンドを見やすく
            
            st.markdown(f"### {res['name']} ({res['code']}) : {res['price']:,}円")
            st.markdown(f"<h2 style='color:{res['color']}; text-shadow: 1px 1px 2px black;'>AI判定: {res['status']}</h2>", unsafe_allow_html=True)
            
            col_left, col_right = st.columns([1, 3])
            
            with col_left:
                st.markdown("##### 📋 戦略合致チェック")
                for k, v in res['checks'].items():
                    st.write(f"{'✅' if v else '❌'} {k}")
                
                # サイコロジカル補足
                cur_psy = res['df']['Psy'].iloc[-1]
                st.metric("サイコロジカル(12日)", f"{cur_psy:.1f}%")
                if cur_psy >= 75: st.success("🔥 市場は非常に強気です")
                elif cur_psy <= 25: st.warning("❄️ 市場は総悲観(底値圏)")

            with col_right:
                # 4段構成: 価格/DMI/RCI/サイコロジカル
                fig = make_subplots(
                    rows=4, cols=1, 
                    shared_xaxes=True, 
                    vertical_spacing=0.03, 
                    row_heights=[0.4, 0.2, 0.2, 0.2]
                )
                
                # 1. メイン (VWAP & MA200)
                fig.add_trace(go.Candlestick(x=display_df.index, open=display_df['Open'], high=display_df['High'], low=display_df['Low'], close=display_df['Close'], name='価格'), row=1, col=1)
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['VWAP'], line=dict(color='orange', width=2, dash='dot'), name='25日VWAP'), row=1, col=1)
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA200'], line=dict(color='rgba(255,255,255,0.5)', width=1), name='200日線'), row=1, col=1)
                
                # 2. DMI
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['+DI'], line=dict(color='red', width=1.5), name='+DI'), row=2, col=1)
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['-DI'], line=dict(color='blue', width=1.5), name='-DI'), row=2, col=1)
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['ADX'], line=dict(color='orange', width=2.5), name='ADX'), row=2, col=1)
                
                # 3. RCI
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['RCI9'], line=dict(color='red', width=2), name='RCI 9'), row=3, col=1)
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['RCI27'], line=dict(color='cyan', width=2), name='RCI 27'), row=3, col=1)
                fig.add_hline(y=0, line_dash="dash", line_color="gray", row=3, col=1)
                
                # 4. サイコロジカルライン
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['Psy'], line=dict(color='lime', width=2), fill='tozeroy', name='Psychological'), row=4, col=1)
                fig.add_hline(y=75, line_dash="dot", line_color="red", row=4, col=1)
                fig.add_hline(y=50, line_dash="dash", line_color="white", row=4, col=1)
                fig.add_hline(y=25, line_dash="dot", line_color="blue", row=4, col=1)
                
                fig.update_layout(height=850, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            st.divider()
        else: st.error(f"{c}: {res}")
    
    if hit_codes:
        st.subheader("📋 診断済み銘柄コード")
        st.code(",".join(hit_codes), language="text")
