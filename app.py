import yfinance as yf
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import requests
from io import BytesIO

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Pro: 診断 Edition", page_icon="🦅")

# --- 2. データベース & JPX全銘柄名簿の自動取得 ---
@st.cache_data(ttl=86400)
def get_jpx_master():
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        df = pd.read_excel(BytesIO(res.content), engine='xlrd')
        names = dict(zip(df['コード'].astype(str), df['銘柄名']))
        return names
    except Exception as e:
        return {}

jpx_names = get_jpx_master()

# --- 3. テクニカル指標の完全自作関数 ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period-1, adjust=False).mean()
    ema_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))

def calculate_rci(series, period):
    def rci_logic(s):
        n = len(s)
        time_ranks = list(range(n, 0, -1))
        price_ranks = pd.Series(s).rank(ascending=False).tolist()
        sum_d2 = sum((tr - pr) ** 2 for tr, pr in zip(time_ranks, price_ranks))
        return (1 - (6 * sum_d2) / (n * (n**2 - 1))) * 100
    return series.rolling(window=period).apply(rci_logic)

def calculate_dmi(df, period=14):
    # DMI (+DI, -DI, ADX) の計算
    high = df['High']
    low = df['Low']
    close = df['Close']
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

    def rma(series, p): return series.ewm(alpha=1/p, adjust=False).mean()
    
    atr = rma(tr, period)
    plus_di = 100 * rma(plus_dm, period) / atr
    minus_di = 100 * rma(minus_dm, period) / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = rma(dx, period)
    return plus_di, minus_di, adx

# --- 4. 個別銘柄の精密診断エンジン ---
def diagnose_stock(ticker, min_vol, rsi_target, rci_target):
    try:
        tkr = yf.Ticker(ticker)
        df = tkr.history(period="1y", interval="1d", actions=False)
        if df.empty or len(df) < 200: return None

        # 指標計算
        price = df['Close'].iloc[-1]
        open_p = df['Open'].iloc[-1]
        avg_vol = df['Volume'].tail(5).mean()
        
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        df['MA200'] = df['Close'].rolling(200).mean()
        
        df['std20'] = df['Close'].rolling(20).std()
        df['BB_up3'] = df['MA20'] + 3 * df['std20']
        df['BB_low3'] = df['MA20'] - 3 * df['std20']
        
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        df['VWAP'] = (typical_price * df['Volume']).rolling(20).sum() / df['Volume'].rolling(20).sum()

        df['RSI'] = calculate_rsi(df['Close'], 14)
        df['RCI_9'] = calculate_rci(df['Close'], 9)
        df['RCI_26'] = calculate_rci(df['Close'], 26)
        df['+DI'], df['-DI'], df['ADX'] = calculate_dmi(df, 14)

        # 直近の数値取得
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        high20 = df['High'].tail(20).max()
        low20 = df['Low'].tail(20).min()

        # 🎯 7つの合否判定 (True/False)
        chk_vol = avg_vol >= min_vol
        chk_rsi = curr['RSI'] <= rsi_target
        chk_rci = curr['RCI_9'] <= rci_target
        chk_bb = (price <= curr['BB_low3'] * 1.03) or (price >= curr['BB_up3'] * 0.97)
        
        # パーフェクトオーダー (MA20,60,200が全て上昇 または 全て下降)
        ma_all_up = (curr['MA20'] > prev['MA20']) and (curr['MA60'] > prev['MA60']) and (curr['MA200'] > prev['MA200'])
        ma_all_down = (curr['MA20'] < prev['MA20']) and (curr['MA60'] < prev['MA60']) and (curr['MA200'] < prev['MA200'])
        chk_po = ma_all_up or ma_all_down

        chk_sudden = (price <= high20 * 0.8) or (price >= low20 * 1.2)
        
        # DMI判定 (+DI上昇 かつ ADX上昇 かつ ADX>25)
        chk_dmi = (curr['+DI'] > prev['+DI']) and (curr['ADX'] > prev['ADX']) and (curr['ADX'] > 25)

        # RCIクロス判定
        rci_gc = (prev['RCI_9'] < prev['RCI_26']) and (curr['RCI_9'] > curr['RCI_26']) and (curr['RCI_9'] < 0)
        rci_dc = (prev['RCI_9'] > prev['RCI_26']) and (curr['RCI_9'] < curr['RCI_26']) and (curr['RCI_9'] > 70)
        chk_rci_cross = rci_gc or rci_dc

        # ⏱️ エントリータイミングのAI判定
        is_yosen = price > open_p
        
        if rci_dc:
            timing = "⏳ 数日待つべき (天井からの下落警戒・落ちるナイフ)"
            color = "red"
        elif rci_gc and (chk_dmi or is_yosen):
            timing = "🌇 大引け前に買うべき (反発シグナル点灯・翌日のGU狙い)"
            color = "green"
        elif chk_rci or chk_rsi or (price <= curr['BB_low3'] * 1.03):
            if curr['-DI'] > curr['+DI'] and curr['ADX'] > 25:
                timing = "⏳ 数日待つべき (売られすぎだが、下落トレンドが強すぎる)"
                color = "orange"
            else:
                timing = "🌅 翌日の寄り付きで買うべき (底値圏だが反発の確認が必要)"
                color = "blue"
        elif chk_dmi and ma_all_up:
            timing = "🌇 大引け前に買うべき (強い上昇トレンド・順張り)"
            color = "green"
        else:
            timing = "☁️ 様子見 (明確なシグナルなし)"
            color = "gray"

        return {
            "ticker": ticker.replace(".T", ""),
            "name": jpx_names.get(ticker.replace(".T", ""), "不明銘柄"),
            "price": int(price),
            "timing": timing,
            "color": color,
            "checks": {
                "出来高クリア": chk_vol,
                "RSI 底値圏": chk_rsi,
                "RCI 底値圏": chk_rci,
                "ボリンジャー±3σ接近": chk_bb,
                "MAパーフェクトオーダー": chk_po,
                "直近20日 急騰/急落": chk_sudden,
                "DMI トレンド強気 (+DI上昇 & ADX>25)": chk_dmi,
                "RCI クロス発生 (GC<0 または DC>70)": chk_rci_cross
            },
            "data": {
                "rsi": curr['RSI'], "rci9": curr['RCI_9'], "rci26": curr['RCI_26'],
                "vol": avg_vol, "adx": curr['ADX']
            },
            "df": df
        }
    except Exception as e:
        return None

# --- 5. 画面構築 ---
st.title("🏹 Stock Sniper Pro: 精密診断・タイミング判定 Edition")
st.markdown("気になっている銘柄のコードを入力すると、7つの独自基準で現在の健康状態を丸裸にし、**「いつ買うべきか」** をズバリ診断します。")

st.sidebar.title("⚙️ 診断基準の設定")
min_vol = st.sidebar.number_input("合格とする最低出来高", 0, 100000000, 100000, step=50000)
rsi_target = st.sidebar.slider("RSI 底値圏の基準", 0, 100, 40)
rci_target = st.sidebar.slider("RCI 底値圏の基準", -100, 100, -50)

# 入力エリア
st.subheader("🔍 診断したい銘柄コードを入力")
input_tickers = st.text_area("カンマ区切りで入力してください (例: 7203, 9984, 8035)", "9984, 6701, 7203")

if st.button("🩺 複数銘柄を 一斉診断する", type="primary"):
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_tickers.split(',') if t.strip()]
    
    if not ticker_list:
        st.warning("銘柄コードを入力してください。")
    else:
        bar = st.progress(0)
        for i, t in enumerate(ticker_list):
            res = diagnose_stock(t, min_vol, rsi_target, rci_target)
            if res:
                # --- 結果のカード表示 ---
                with st.container():
                    st.markdown(f"### {res['name']} ({res['ticker']}) - 現在値: {res['price']:,}円")
                    
                    # タイミング判定を大きく表示
                    st.markdown(f"<h4 style='color: {res['color']};'>🤖 AIタイミング診断: {res['timing']}</h4>", unsafe_allow_html=True)
                    
                    col1, col2 = st.columns([1, 2])
                    
                    # 左側：7つの〇×判定リスト
                    with col1:
                        st.markdown("##### 📋 7つの合否判定")
                        for label, passed in res['checks'].items():
                            icon = "✅" if passed else "❌"
                            st.write(f"{icon} {label}")
                        
                        st.markdown("---")
                        st.markdown(f"**現在のRSI**: {res['data']['rsi']:.1f}")
                        st.markdown(f"**RCI (9日/26日)**: {res['data']['rci9']:.1f} / {res['data']['rci26']:.1f}")
                        st.markdown(f"**DMI (ADX)**: {res['data']['adx']:.1f}")

                    # 右側：チャート表示
                    with col2:
                        df = res['df']
                        fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='価格')])
                        fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='green', width=1), name='20MA(緑)'))
                        fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='orange', width=1), name='60MA(橙)'))
                        fig.add_trace(go.Scatter(x=df.index, y=df['MA200'], line=dict(color='purple', width=1.5), name='200MA(紫)'))
                        fig.add_trace(go.Scatter(x=df.index, y=df['VWAP'], line=dict(color='cyan', width=1.5, dash='dot'), name='VWAP(水色点線)'))
                        fig.add_trace(go.Scatter(x=df.index, y=df['BB_up3'], line=dict(color='pink', width=1, dash='dot'), name='+3σ'))
                        fig.add_trace(go.Scatter(x=df.index, y=df['BB_low3'], line=dict(color='lightblue', width=1, dash='dot'), name='-3σ'))
                        
                        fig.update_layout(height=400, margin=dict(l=0, r=0, b=0, t=0), xaxis_rangeslider_visible=False, showlegend=False)
                        st.plotly_chart(fig, use_container_width=True)
                st.divider()
            else:
                st.error(f"{t}: データの取得に失敗したか、上場から間もない銘柄です。")
            
            bar.progress((i + 1) / len(ticker_list))
        st.success("✅ 全銘柄の診断が完了しました！")
