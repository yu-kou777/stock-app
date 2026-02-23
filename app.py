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

# 主要銘柄の和名辞書（適宜追加可能です）
NAME_MAP = {
    "8035.T": "東京エレクトロン", "6920.T": "レーザーテック", "6857.T": "アドバンテスト",
    "6723.T": "ルネサスエレクトロニクス", "6758.T": "ソニーグループ", "6501.T": "日立製作所",
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
    return "9984, 6330"

def save_list(text):
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        f.write(text)

def add_to_list(ticker_code):
    current = load_saved_list()
    # 銘柄がまだリストにない場合のみ追加
    code_only = ticker_code.replace(".T", "")
    if code_only not in current:
        new_list = f"{current}, {code_only}" if current else code_only
        save_list(new_list)
        return True
    return False

# --- 3. 解析エンジン ---
def analyze_stock(ticker, min_p, max_p, is_force=False):
    try:
        tkr = yf.Ticker(ticker)
        df_d = tkr.history(period="6mo", interval="1d")
        df_w = tkr.history(period="2y", interval="1wk")
        if df_d.empty or df_w.empty: return None

        price = df_d.iloc[-1]['Close']
        if not is_force and not (min_p <= price <= max_p): return None

        # 指標
        df_d['MA60'] = df_d['Close'].rolling(60).mean()
        df_w['MA20'] = df_w['Close'].rolling(20).mean()
        target_p = int(df_w['MA20'].iloc[-1])
        rsi_w = ta.rsi(df_w['Close'], length=14).iloc[-1]
        dev_w = (price - target_p) / target_p * 100

        # 底値予測
        std20 = df_d['Close'].rolling(20).std().iloc[-1]
        ma20 = df_d['Close'].rolling(20).mean().iloc[-1]
        floor = int(ma20 - (std20 * 2))

        # トレンド
        is_w_up = df_w['Close'].iloc[-1] > df_w['Open'].iloc[-1]
        is_d_up = df_d['Close'].iloc[-1] > df_d['Open'].iloc[-1]
        
        # スコア
        score = (50 if is_w_up else -50) + (30 if is_d_up else -30)
        is_oversold = rsi_w < 35 or dev_w < -15
        if is_oversold: score += 40

        # 判定
        if score >= 60: judge = "🔥 特級買"
        elif score >= 20: judge = "✨ 買目線"
        elif score <= -60: judge = "📉 特級売"
        elif score <= -20: judge = "☔ 売目線"
        else: judge = "☁️ 様子見"

        return {
            "コード": ticker.replace(".T",""), "和名": NAME_MAP.get(ticker, "不明"),
            "現在値": int(price), "判定": judge, "スコア": int(score), 
            "週RSI": round(rsi_w, 1), "予想底値": floor, "目標": target_p, 
            "df": df_d, "反発": "🎯 反発開始" if (is_oversold and is_d_up) else ("⏳ 底打ち模索" if is_oversold else "-")
        }
    except: return None

# --- 4. 画面構築 ---
st.title("🏹 Stock Sniper Pro")

# 📚 全判定の説明プルダウン
with st.expander("📚 戦略ガイド：判定の定義と使い方"):
    st.markdown("""
    ### 【判定カテゴリー】
    * **🔥 特級買 (Score 60+)**: 週足・日足が共に陽転。物理的な上昇トレンドの「本流」に乗っている状態。
    * **✨ 買目線 (Score 20+)**: トレンドは上向きだが、勢いが限定的。押し目買いの候補。
    * **📉 特級売 (Score -60-)**: 週足・日足が共に陰転。空売りの物理的優位性が高い状態。
    * **☔ 売目線 (Score -20-)**: 下落傾向。戻り売りのポイントを探る局面。
    * **☁️ 様子見**: 方向感が不透明。無理に手を出さず、次の波を待つ時間。

    ### 【特殊シグナル】
    * **🎯 反発開始**: 売られすぎ（RSI低）から日足が陽転。短期リバウンドの「指値成功」の瞬間。
    * **⏳ 底打ち模索**: まだ下げ止まっていないが、反発フロア（青点線）に接近している警戒態勢。

    ### 【チャート活用】
    * **青点線 (予想底値)**: 過去の統計から導いた反発の地面。ここに**指値**を置く。
    * **赤点線 (目標)**: 週足移動平均線。ここが**利確（エグジット）**の目安。
    """)

# サイドバー：戦略司令室
st.sidebar.title("💰 検索・保存管理")
mode = st.sidebar.radio("検索対象", ["📊 市場全体", "⭐ 保存リスト", "📝 自由入力"])

if mode == "📊 市場全体":
    ticker_list = list(NAME_MAP.keys()); is_force = False
elif mode == "⭐ 保存リスト":
    saved_text = load_saved_list()
    input_area = st.sidebar.text_area("ウォッチリスト編集", saved_text, height=150)
    col_save, col_clear = st.sidebar.columns(2)
    if col_save.button("💾 保存"): save_list(input_area); st.sidebar.success("保存完了")
    if col_clear.button("🗑️ 全消去"): save_list(""); st.rerun() # 再読み込み
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_area.split(',') if t.strip()]
    is_force = True
else:
    input_area = st.sidebar.text_area("銘柄コード入力", "9984, 6330", height=100)
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_area.split(',') if t.strip()]
    is_force = True

min_p = st.sidebar.number_input("下限価格", 0, 100000, 1000)
max_p = st.sidebar.number_input("上限価格", 0, 100000, 100000)

c1, c2, c3 = st.columns(3)
btn_all = c1.button("📑 全件スキャン")
btn_buy = c2.button("🚀 買い・反発狙い")
btn_short = c3.button("📉 空売り狙い")

if btn_all or btn_buy or btn_short:
    results = []
    bar = st.progress(0)
    for i, t in enumerate(ticker_list):
        res = analyze_stock(t, min_p, max_p, is_force)
        if res: results.append(res)
        bar.progress((i + 1) / len(ticker_list))
    
    if results:
        df_res = pd.DataFrame(results).sort_values("スコア", ascending=False)
        if btn_buy: df_res = df_res[df_res['スコア'] >= 20]
        elif btn_short: df_res = df_res[df_res['スコア'] <= -20]

        for _, row in df_res.iterrows():
            with st.expander(f"{row['判定']} | {row['和名']} ({row['コード']}) - {row['現在値']}円"):
                # --- グラフ表示 ---
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=row['df'].index, open=row['df']['Open'], high=row['df']['High'], low=row['df']['Low'], close=row['df']['Close'], name='価格'))
                fig.add_trace(go.Scatter(x=row['df'].index, y=row['df']['MA60'], line=dict(color='orange', width=1.5), name='60MA'))
                fig.add_hline(y=row['予想底値'], line_dash="dash", line_color="royalblue", annotation_text="指値目安")
                fig.add_hline(y=row['目標'], line_dash="dash", line_color="crimson", annotation_text="目標")
                fig.update_layout(height=400, margin=dict(l=0, r=0, b=0, t=0), showlegend=False, xaxis_rangeslider_visible=False, yaxis=dict(fixedrange=True), xaxis=dict(fixedrange=True))
                st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
                
                # 情報表示 & 保存ボタン
                c_inf, c_btn = st.columns([2, 1])
                with c_inf:
                    st.write(f"スコア: {row['スコア']}点 | 週RSI: {row['週RSI']} | 指値目安: {row['予想底値']}円")
                with c_btn:
                    if st.button(f"⭐ リストに追加", key=f"add_{row['コード']}"):
                        if add_to_list(row['コード']): st.toast(f"{row['和名']} を保存しました！")
                        else: st.toast("既にリストにあります")
        
        st.divider()
        st.dataframe(df_res.drop(columns=['df', '反発']), use_container_width=True)
    else: st.warning("該当なし")
