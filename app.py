import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
import requests
import os
from datetime import datetime, timedelta, timezone

# --- 1. アプリ基本設定 ---
st.set_page_config(layout="wide", page_title="Stock Sniper Pro", page_icon="🦅")

# --- 2. 各種設定（Discord Webhook） ---
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1472281747000393902/Fbclh0R3R55w6ZnzhenJ24coaUPKy42abh3uPO-fRjfQulk9OwAq-Cf8cJQOe2U4SFme"

# --- 3. ロジック関数群 ---

def load_watchlist_from_excel():
    """エクセル(list.xlsx)から柔軟に銘柄を読み込む"""
    try:
        if not os.path.exists('list.xlsx'):
            return {"9984.T": "SBG", "6330.T": "東洋エンジ"}
        
        df = pd.read_excel('list.xlsx')
        df.columns = [str(c).strip().lower() for c in df.columns]
        
        # 銘柄コード列の探索
        code_candidates = ['code', 'コード', '銘柄コード', '証券コード']
        code_col = next((c for c in code_candidates if c in df.columns), None)
        
        # 銘柄名列の探索
        name_candidates = ['name', '銘柄名', '名前', '会社名']
        name_col = next((c for c in name_candidates if c in df.columns), None)

        if code_col is None: return {}

        watchlist = {}
        for _, row in df.iterrows():
            code = str(row[code_col]).strip()
            if '.' in code: code = code.split('.')[0]
            full_code = f"{code}.T" if code.isdigit() else code
            name = str(row[name_col]).strip() if name_col else f"銘柄:{code}"
            watchlist[full_code] = name
        return watchlist
    except:
        return {}

def calculate_heikin_ashi(df):
    """平均足を計算"""
    ha_df = df.copy()
    ha_df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    ha_df['HA_Open'] = 0.0
    ha_df.iloc[0, ha_df.columns.get_loc('HA_Open')] = (df.iloc[0]['Open'] + df.iloc[0]['Close']) / 2
    for i in range(1, len(df)):
        ha_df.iloc[i, ha_df.columns.get_loc('HA_Open')] = (ha_df.iloc[i-1]['HA_Open'] + ha_df.iloc[i-1]['HA_Close']) / 2
    return ha_df

def check_sakata(df):
    """酒田五法判定（赤三兵・黒三兵）"""
    if len(df) < 5: return "", 0
    c = df['Close'].values; o = df['Open'].values
    if c[-1]>o[-1] and c[-2]>o[-2] and c[-3]>o[-3] and c[-1]>c[-2]>c[-3]: return "🔥赤三兵", 40
    if c[-1]<o[-1] and c[-2]<o[-2] and c[-3]<o[-3] and c[-1]<c[-2]<c[-3]: return "⚠️黒三兵", -40
    return "", 0

def analyze_stock(ticker, name, min_p, max_p, is_force=False):
    """メイン解析エンジン"""
    try:
        tkr = yf.Ticker(ticker)
        df_d = tkr.history(period="6mo", interval="1d")
        df_w = tkr.history(period="2y", interval="1wk")
        if df_d.empty or df_w.empty: return None

        price = df_d.iloc[-1]['Close']
        if not is_force and not (min_p <= price <= max_p): return None

        # 指標計算
        df_w['MA20'] = df_w['Close'].rolling(20).mean()
        target_p = int(df_w['MA20'].iloc[-1])
        ha_w = calculate_heikin_ashi(df_w); w_l = ha_w.iloc[-1]
        ha_d = calculate_heikin_ashi(df_d); d_l = ha_d.iloc[-1]
        
        is_w_up = w_l['HA_Close'] > w_l['HA_Open']
        is_d_up = d_l['HA_Close'] > d_l['HA_Open']
        rsi_w = ta.rsi(df_w['Close'], length=14).iloc[-1]
        dev_w = (price - target_p) / target_p * 100

        # 反発フロア（ボリンジャーバンド-2σ相当）
        std20 = df_d['Close'].rolling(20).std().iloc[-1]
        ma20 = df_d['Close'].rolling(20).mean().iloc[-1]
        floor = int(ma20 - (std20 * 2))

        # 判定
        is_oversold = rsi_w < 35 or dev_w < -15
        if is_oversold:
            status_msg = f"🎯 反発開始 (目標:{target_p})" if is_d_up else f"⏳ 底打ち模索中 ({target_p})"
            color_hex = "#00ff00" if is_d_up else "#ffa500" # 緑 or オレンジ
        else:
            status_msg = "📈 順張り" if is_d_up else "📉 調整"
            color_hex = "#ffffff"

        sakata_msg, sakata_score = check_sakata(df_d)
        score = (50 if is_w_up else -50) + (40 if is_oversold else 0) + (30 if is_d_up else -30) + sakata_score
        if is_w_up != is_d_up: score *= 0.3

        return {
            "コード": ticker.replace(".T",""), "銘柄名": name, "現在値": int(price),
            "判定": status_msg, "スコア": int(score), "週RSI": round(rsi_w, 1),
            "予想底値": floor, "目標(20週)": target_p, "根拠": f"週:{'陽' if is_w_up else '陰'} / {sakata_msg}",
            "color": color_hex
        }
    except: return None

def send_discord(data):
    """Discordへの手動通知機能"""
    payload = {
        "username": "最強株哨戒機 🦅",
        "embeds": [{
            "title": f"🚀 狙い撃ち: {data['銘柄名']} ({data['コード']})",
            "description": f"**現在値: {data['現在値']}円**\n判定: {data['判定']}",
            "color": 3066993,
            "fields": [
                {"name": "🧠 スコア", "value": f"{data['スコア']}点", "inline": True},
                {"name": "🛡️ 予想底値", "value": f"{data['予想底値']}円", "inline": True},
                {"name": "🎯 利確目標", "value": f"{data['目標(20週)']}円", "inline": True}
            ]
        }]
    }
    requests.post(DISCORD_WEBHOOK_URL, json=payload)

# --- 4. 画面構築 (Streamlit UI) ---

st.title("🏹 Stock Sniper Strategy Pro")

# サイドバー：リスト管理
st.sidebar.title("⭐ 監視リスト管理")
watchlist = load_watchlist_from_excel()
st.sidebar.write(f"登録銘柄数: {len(watchlist)}")

mode = st.sidebar.radio("モード", ["⭐ エクセル銘柄", "📝 自由入力"])
min_p = st.sidebar.number_input("下限価格", 0, 100000, 0)
max_p = st.sidebar.number_input("上限価格", 0, 100000, 100000)

if mode == "📝 自由入力":
    raw_input = st.sidebar.text_area("コード入力(カンマ区切り)", "9984, 6330")
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in raw_input.split(',') if t.strip()]
    is_force = True
else:
    ticker_list = list(watchlist.keys())
    is_force = False

# メインボタン（スマホでも押しやすいサイズ）
c1, c2, c3 = st.columns(3)
btn_all = c1.button("📑 全銘柄スキャン")
btn_buy = c2.button("🚀 買い・反発狙い")
btn_short = c3.button("📉 空売り狙い")

if btn_all or btn_buy or btn_short:
    results = []
    bar = st.progress(0)
    for i, t in enumerate(ticker_list):
        name = watchlist.get(t, t)
        res = analyze_stock(t, name, min_p, max_p, is_force)
        if res: results.append(res)
        bar.progress((i + 1) / len(ticker_list))
    
    if results:
        df = pd.DataFrame(results).sort_values("スコア", ascending=False)
        if btn_buy: df = df[df['判定'].str.contains("買") | df['判定'].str.contains("反発")]
        elif btn_short: df = df[df['判定'].str.contains("売")]

        # 表示
        for idx, row in df.iterrows():
            with st.expander(f"{row['判定']} | {row['銘柄名']} ({row['コード']}) - {row['現在値']}円"):
                st.write(f"**スコア:** {row['スコア']}点 | **週RSI:** {row['週RSI']}")
                st.write(f"**予想底値（指値目安）:** {row['予想底値']}円")
                st.write(f"**利確目標（20週線）:** {row['目標(20週)']}円")
                st.write(f"**根拠:** {row['根拠']}")
                if st.button(f"🦅 {row['銘柄名']}をDiscordへ送る", key=row['コード']):
                    send_discord(row)
                    st.toast("通知完了！")
        
        st.divider()
        st.dataframe(df.drop(columns=['color']), use_container_width=True)
    else:
        st.warning("該当銘柄なし")

