import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🛡️ 銘柄マスタ (東洋エンジニアリング追加)
# ==========================================
NAME_MAP = {
    "7203.T": "トヨタ", "9984.T": "SBG", "8306.T": "三菱UFJ", "6758.T": "ソニーG",
    "6861.T": "キーエンス", "6098.T": "リクルート", "8035.T": "東エレク", "4063.T": "信越化学",
    "7974.T": "任天堂", "9432.T": "NTT", "8058.T": "三菱商事", "8316.T": "三井住友",
    "8630.T": "SOMPO", "8725.T": "MS&AD", "6701.T": "NEC", "4901.T": "富士フイルム",
    "6702.T": "富士通", "4503.T": "アステラス", "6971.T": "京セラ", "7211.T": "三菱自",
    "8591.T": "オリックス", "3003.T": "ヒューリック", "2702.T": "マクドナルド",
    "7049.T": "識学", "9101.T": "日本郵船", "4661.T": "OLC", "5401.T": "日本製鉄",
    "9501.T": "東電HD", "7267.T": "ホンダ", "4502.T": "武田薬品", "8001.T": "伊藤忠",
    "6330.T": "東洋エンジ", "7011.T": "三菱重工", "7012.T": "川崎重工", "1605.T": "INPEX"
}

# ==========================================
# 🌐 決算日チェック (株探連動)
# ==========================================
def scrape_earnings_date(code):
    clean_code = code.replace(".T", "")
    url = f"https://kabutan.jp/stock/finance?code={clean_code}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code != 200: return None
        soup = BeautifulSoup(res.text, "html.parser")
        target = soup.find(string=re.compile(r"決算発表予定日"))
        if target:
            match = re.search(r"(\d{2}/\d{2}/\d{2})", str(target.parent.get_text()))
            if match: return datetime.strptime("20" + match.group(1), "%Y/%m/%d").date()
    except: pass
    return None

# ==========================================
# 🧠 分析ロジック (決算空売り判定追加)
# ==========================================
def get_analysis(ticker, name, min_p, max_p):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 30: return None
        curr_price = int(hist["Close"].iloc[-1])
        
        # 価格フィルタ (空売り候補探しでも有効)
        if not (min_p <= curr_price <= max_p): return None

        # --- テクニカル指標 ---
        # 1. RSI
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]
        
        # 2. 移動平均乖離率 (25日線からの離れ具合)
        ma25 = hist['Close'].rolling(25).mean().iloc[-1]
        divergence = ((curr_price - ma25) / ma25) * 100 # %表記

        # 3. 勢い
        ma5 = hist['Close'].rolling(5).mean().iloc[-1]
        if curr_price > ma5: trend = "📈上昇"
        else: trend = "📉下落"

        # --- 決算日取得 ---
        earn_date = scrape_earnings_date(ticker)
        
        # --- 判定ロジック ---
        # A. 決算空売りフラグ (Earnings Short)
        is_earnings_short = False
        short_reason = ""
        days_to_earn = 999
        
        if earn_date:
            days_to_earn = (earn_date - datetime.now().date()).days
            # 決算が2週間以内〜直前 かつ 過熱感がある
            if 0 <= days_to_earn <= 14:
                if rsi > 70: 
                    is_earnings_short = True
                    short_reason = "🔥RSI過熱"
                elif divergence > 7: # 25日線より7%以上高い
                    is_earnings_short = True
                    short_reason = "🚀急騰中"

        # B. 通常の売買スコア
        buy_score, sell_score = 0, 0
        
        # 決算直前(3日以内)は、通常の買い推奨からは除外(リスク回避)
        is_risk = (0 <= days_to_earn <= 3) if earn_date else False

        if not is_risk:
            # 買い
            if rsi < 60:
                if rsi < 35: buy_score += 40
                if "上昇" in trend: buy_score += 20
            # 売り (通常のテクニカル売り)
            if rsi > 70: sell_score += 40
            if "下落" in trend: sell_score += 30

        # --- 戦略数値 ---
        # 空売りの場合: 決算期待で上げている分の逆回転を狙う
        # 利確: 25日移動平均線まで戻るのを想定
        short_tp = int(ma25) 
        # 損切: 現在値から+3% (踏み上げ防止)
        short_sl = int(curr_price * 1.03)

        return {
            "コード": ticker.replace(".T", ""), "銘柄名": name, "現在値": curr_price,
            "RSI": round(rsi, 1), "乖離率": round(divergence, 1),
            "勢い": trend,
            "決算日": earn_date if earn_date else "-",
            "is_earnings_short": is_earnings_short, # 決算空売り対象か
            "short_reason": short_reason,
            "buy_score": buy_score, "sell_score": sell_score,
            "short_tp": short_tp, "short_sl": short_sl,
            "res_line": int(hist['High'].tail(25).max())
        }
    except: return None

# ==========================================
# 📱 アプリ表示
# ==========================================
st.set_page_config(page_title="最強株スキャナー・決算空売り特化", layout="wide")
st.title("🦅 最強株スキャナー (決算スナイパー機能搭載)")

# --- 個別診断 ---
st.header("🔍 個別銘柄ピンポイント診断")
code_in = st.text_input("コード (例: 6330)", "").strip()

if code_in:
    full_c = code_in + ".T" if ".T" not in code_in else code_in
    d_name = NAME_MAP.get(full_c)
    if not d_name:
        try: d_name = yf.Ticker(full_c).info.get('longName', code_in)
        except: d_name = code_in
    
    with st.spinner("過熱感を分析中..."):
        r = get_analysis(full_c, d_name, 0, 10000000)
    
    if r:
        st.subheader(f"📊 {r['銘柄名']} ({r['コード']})")
        
        # 決算空売りのチャンスか判定
        if r["is_earnings_short"]:
            st.error(f"💀 【空売り注目】決算({r['決算日']})に向けて過熱しています！ ({r['short_reason']})")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("現在値", f"{r['現在値']}円", delta=f"乖離率: {r['乖離率']}%")
            if r['is_earnings_short']:
                st.write("📉 **決算空売り戦略**")
            elif r['buy_score'] >= 50:
                st.success("判定: 買い推奨 🚀")
            else:
                st.info("判定: 様子見 ☕")

        with c2:
            if r['is_earnings_short'] or r['sell_score'] >= 50:
                st.metric("空売り利確 (Target)", f"{r['short_tp']}円", help="25日移動平均線付近")
                st.metric("逆指値・損切 (Stop)", f"{r['short_sl']}円", delta_color="inverse", help="必須！踏み上げ防止")
            else:
                st.write("※買いの戦略はスキャン画面で確認")

        with c3:
            st.metric("RSI(14)", r['RSI'])
            st.write(f"**決算日:** {r['決算日']}")
            st.caption(f"直近高値: {r['res_line']}円")
            
        if r["is_earnings_short"]:
            st.warning("⚠️ 注意: 決算またぎはギャンブルです。発表直前に手仕舞うか、必ず逆指値を入れてください。")

    else: st.error("取得失敗")

st.divider()

# --- 一括スキャン ---
st.header("🚀 市場全体スキャン")
col_filt1, col_filt2 = st.columns(2)
with col_filt1: p_min = st.number_input("最低価格 (円)", value=1000, step=1000)
with col_filt2: p_max = st.number_input("最高価格 (円)", value=10000, step=1000)

if st.button("スキャン開始", use_container_width=True):
    with st.spinner("決算前の過熱銘柄を捜索中..."):
        with ThreadPoolExecutor(max_workers=5) as ex:
            fs = [ex.submit(get_analysis, t, n, p_min, p_max) for t, n in NAME_MAP.items()]
            ds = [f.result() for f in fs if f.result()]
    
    if ds:
        df = pd.DataFrame(ds)
        
        # 💀 決算前・過熱空売りリスト (ここが新機能！)
        st.subheader("💀 決算前・過熱空売り候補 (逆張り)")
        shorts = df[df["is_earnings_short"] == True]
        if not shorts.empty:
            st.error("以下の銘柄は、決算を前に「買われすぎ」の状態です。急落に注意してください。")
            st.dataframe(shorts[["コード","銘柄名","現在値","RSI","乖離率","決算日","short_tp","short_sl"]].rename(
                columns={"short_tp":"利確目安", "short_sl":"逆指値(必須)", "乖離率":"乖離(%)"}
            ), hide_index=True)
        else:
            st.info("現在、決算前に異常過熱している銘柄はありません。")

        st.divider()

        # 🔥 通常の買い推奨
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🔥 買い推奨 (押し目)")
            bs = df[df["buy_score"] >= 50].sort_values("buy_score", ascending=False)
            if not bs.empty:
                st.dataframe(bs[["コード","銘柄名","現在値","RSI","勢い"]], hide_index=True)
            else: st.info("なし")
        
        with c2:
            st.subheader("📉 通常の売り推奨 (テクニカル)")
            ss = df[df["sell_score"] >= 50].sort_values("sell_score", ascending=False)
            if not ss.empty:
                st.dataframe(ss[["コード","銘柄名","現在値","RSI","勢い"]], hide_index=True)
            else: st.info("なし")
    else:
        st.warning("該当なし")
