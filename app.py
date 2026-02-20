import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
import numpy as np
from datetime import datetime, timedelta

# --- アプリ設定 ---
st.set_page_config(layout="wide", page_title="Stock Scanner Technical Pro")

# --- 銘柄データベース (主要貸借銘柄中心) ---
TICKER_MAP = {
    "8035.T": "東京エレク", "6920.T": "レーザーテク", "6857.T": "アドバンテ", "6723.T": "ルネサス",
    "6758.T": "ソニーG", "6501.T": "日立", "7735.T": "SCREEN", "6701.T": "NEC",
    "6702.T": "富士通", "6503.T": "三菱電機", "6861.T": "キーエンス", "6954.T": "ファナック",
    "6981.T": "村田製", "6971.T": "京セラ", "6902.T": "デンソー", "4063.T": "信越化",
    "7203.T": "トヨタ", "7267.T": "ホンダ", "7270.T": "SUBARU", "7201.T": "日産自",
    "6301.T": "コマツ", "6367.T": "ダイキン", "7011.T": "三菱重工", "7012.T": "川崎重工",
    "7013.T": "IHI", "8306.T": "三菱UFJ", "8316.T": "三井住友", "8411.T": "みずほ", 
    "8604.T": "野村HD", "8766.T": "東京海上", "8031.T": "三井物産", "8058.T": "三菱商事",
    "9101.T": "日本郵船", "9104.T": "商船三井", "9107.T": "川崎汽船", "5401.T": "日本製鉄",
    "5411.T": "JFE", "5406.T": "神戸鋼", "9984.T": "SBG", "9432.T": "NTT", 
    "6098.T": "リクルート", "4385.T": "メルカリ", "4755.T": "楽天G", "9983.T": "ファストリ", 
    "1605.T": "INPEX", "5020.T": "ENEOS", "6330.T": "東洋エンジ" # TOWA等も追加可能
}
MARKET_TICKERS = list(TICKER_MAP.keys())

# --- サイドバー ---
st.sidebar.title("🎛️ テクニカル特化・操作盤")
mode = st.sidebar.radio("戦術モード", ("デイトレ (5分足・遅延対策済み)", "スイング (日足・酒田五法＆トレンド)"))
search_source = st.sidebar.selectbox("検索対象", ("📊 市場全体 (主要株)", "📝 自由入力"))
show_all = st.sidebar.checkbox("☁️ 「様子見」も含めて全表示", value=False)

st.sidebar.subheader("💰 株価フィルタ")
col1, col2 = st.sidebar.columns(2)
min_price = col1.number_input("下限", value=0, step=100)
max_price = col2.number_input("上限", value=50000, step=100)

ticker_list = MARKET_TICKERS
if "自由入力" in search_source:
    input_tickers = st.sidebar.text_area("銘柄コード (カンマ区切り)", "6857, 9107, 7011")
    ticker_list = [f"{t.strip()}.T" if t.strip().isdigit() else t.strip() for t in input_tickers.split(',') if t.strip()]

# --- データ整形 ---
def flatten_data(df):
    if isinstance(df.columns, pd.MultiIndex):
        try: df.columns = df.columns.droplevel(1) 
        except: pass
    return df

# --- 酒田五法 判定ロジック (特級・1級中心) ---
def check_sakata_gohou(df):
    if len(df) < 4: return "-", 0
    signals = []
    score_change = 0
    
    # 直近3日間のデータ
    c0, o0, h0, l0 = df.iloc[-1]['Close'], df.iloc[-1]['Open'], df.iloc[-1]['High'], df.iloc[-1]['Low']
    c1, o1, h1, l1 = df.iloc[-2]['Close'], df.iloc[-2]['Open'], df.iloc[-2]['High'], df.iloc[-2]['Low']
    c2, o2, h2, l2 = df.iloc[-3]['Close'], df.iloc[-3]['Open'], df.iloc[-3]['High'], df.iloc[-3]['Low']
    
    body0, body1, body2 = abs(c0-o0), abs(c1-o1), abs(c2-o2)
    is_up0, is_up1, is_up2 = c0 > o0, c1 > o1, c2 > o2
    is_down0, is_down1, is_down2 = c0 < o0, c1 < o1, c2 < o2

    # 🔥 赤三兵 (買い特級)
    if is_up0 and is_up1 and is_up2 and c0 > c1 > c2:
        signals.append("🔥赤三兵(特級買)")
        score_change += 40
    # ⚠️ 黒三兵 (売り特級)
    if is_down0 and is_down1 and is_down2 and c0 < c1 < c2:
        signals.append("⚠️黒三兵(特級売)")
        score_change -= 40

    # ⚠️ 流れ星 (Shooting Star) - 高値圏での上ヒゲ
    upper_shadow0 = h0 - max(c0, o0)
    lower_shadow0 = min(c0, o0) - l0
    if upper_shadow0 > body0 * 2.0 and lower_shadow0 < body0 * 0.5:
        if df.iloc[-1]['Close'] > df.iloc[-1]['MA_Long']: # 上昇トレンド中
            signals.append("🌠流れ星(急落警戒)")
            score_change -= 50

    # 🔥 明けの明星 (Morning Star) - 底打ちシグナル
    if is_down2 and body2 > (h2-l2)*0.6 and body1 < (h1-l1)*0.3 and is_up0 and c0 > (o2+c2)/2:
        signals.append("🌅明けの明星(底打)")
        score_change += 50

    # ✨ 包み足（抱き線）
    if is_down1 and is_up0 and o0 < c1 and c0 > o1:
        signals.append("✨陽の包み足(反転買)")
        score_change += 20
    if is_up1 and is_down0 and o0 > c1 and c0 < o1:
        signals.append("☔陰の包み足(反転売)")
        score_change -= 20

    signal_text = " / ".join(signals) if signals else "なし"
    return signal_text, score_change

# --- トレンドライン・チャートパターン判定 ---
def check_trend_pattern(df):
    recent_20 = df.tail(20)
    high_max = recent_20['High'].max()
    low_min = recent_20['Low'].min()
    current_price = df.iloc[-1]['Close']
    
    # ボックス（スクウェア）判定: 20日間の高安値幅が5%以内
    box_width = (high_max - low_min) / low_min * 100
    if box_width < 5.0:
        pattern = f"📦ボックス (幅{box_width:.1f}%)"
    else:
        # 簡易的なトレンド判定
        if df.iloc[-1]['MA_Short'] > df.iloc[-1]['MA_Long']:
            pattern = "📈上昇トレンド"
        else:
            pattern = "📉下落トレンド"

    # サポート/レジスタンス接近判定
    support_dist = (current_price - low_min) / low_min * 100
    resist_dist = (high_max - current_price) / current_price * 100
    
    position = ""
    if support_dist < 1.5: position = "💡サポート反発狙い"
    elif resist_dist < 1.5: position = "⚠️レジスタンス警戒"

    return pattern, position

# --- 決算日チェック (簡易版) ---
def get_earnings_alert(ticker_obj):
    try:
        calendar = ticker_obj.calendar
        if calendar is not None and not calendar.empty:
            earning_date = calendar.iloc[0, 0] # 最初の決算日
            if isinstance(earning_date, datetime):
                days_to_earnings = (earning_date.date() - datetime.now().date()).days
                if 0 <= days_to_earnings <= 7:
                    return f"⚠️決算接近({days_to_earnings}日後)"
    except: pass
    return "OK"

# --- 解析エンジン ---
def analyze_stock(ticker, interval, min_p, max_p, mode_name):
    try:
        period = "5d" if interval == "5m" else "6mo"
        tkr = yf.Ticker(ticker)
        df = tkr.history(period=period, interval=interval)
        if len(df) < 25: return None
        
        df = flatten_data(df)
        
        # テクニカル指標
        df['MA_Short'] = ta.sma(df['Close'], length=5)
        df['MA_Long'] = ta.sma(df['Close'], length=25 if interval=="1d" else 20)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        price = float(latest['Close'])
        if not (min_p <= price <= max_p): return None 

        score = 0
        reasons = []
        judgement = "☁️ 様子見"
        
        # ボラティリティ (ATR / 株価)
        vola_pct = (latest['ATR'] / price) * 100

        res_dict = {
            "銘柄": ticker.replace(".T", ""),
            "社名": TICKER_MAP.get(ticker, "-"),
            "現在値": f"{int(price)}",
            "ボラ(ATR)": f"{vola_pct:.1f}%",
        }

        # ==========================================
        # 📉 スイングモード (日足: 酒田五法 ＆ トレンド)
        # ==========================================
        if "スイング" in mode_name:
            # 決算チェック
            earning_status = get_earnings_alert(tkr)
            if "警戒" in earning_status:
                score -= 20; reasons.append(earning_status)
            
            # トレンド・パターン認識
            pattern, position = check_trend_pattern(df)
            if position: reasons.append(position)
            
            # 酒田五法
            sakata_signal, sakata_score = check_sakata_gohou(df)
            score += sakata_score
            if sakata_signal != "なし": reasons.append(sakata_signal)

            # ゴールデン/デッドクロス判定
            if prev['MA_Short'] <= prev['MA_Long'] and latest['MA_Short'] > latest['MA_Long']:
                score += 30; reasons.append("✨Gクロス")
            elif prev['MA_Short'] >= prev['MA_Long'] and latest['MA_Short'] < latest['MA_Long']:
                score -= 30; reasons.append("💀Dクロス")

            res_dict["トレンド"] = pattern
            res_dict["酒田五法"] = sakata_signal
            res_dict["決算警戒"] = earning_status

        # ==========================================
        # 🚀 デイトレモード (5分足: 遅延対策 ヨコヨコ脱出)
        # ==========================================
        else:
            # ヨコヨコ（もみ合い）判定: 過去12本(1時間)の高安値幅が極小
            recent_12_high = df['High'].tail(12).max()
            recent_12_low = df['Low'].tail(12).min()
            box_pct = (recent_12_high - recent_12_low) / recent_12_low * 100
            
            is_yokoyoko = box_pct < 0.8 # 0.8%以内の値幅でエネルギー蓄積中
            state = "🔄 ヨコヨコ(蓄積中)" if is_yokoyoko else "⚡ トレンド発生中"
            
            macd_val = float(latest['MACDh_12_26_9'])
            macd_prev = float(prev['MACDh_12_26_9'])
            rsi_val = float(latest['RSI'])

            # ヨコヨコからのMACD好転（遅延していても初動を捉えやすい）
            if is_yokoyoko and macd_prev < 0 and macd_val > 0:
                score += 50
                reasons.append("🔥ヨコヨコ上抜け初動(MACD)")
                judgement = "🔥 買い(初動)"
            # ヨコヨコからの下抜け（売りドテンのタイミング）
            elif is_yokoyoko and macd_prev > 0 and macd_val < 0:
                score -= 50
                reasons.append("⚠️ヨコヨコ下抜け(MACD)")
                judgement = "📉 売り(初動)"

            # RSI極値
            if rsi_val < 25: score += 20; reasons.append("RSI売られすぎ")
            elif rsi_val > 75: score -= 30; reasons.append("RSI買われすぎ")

            res_dict["状態(5m)"] = state
            res_dict["RSI"] = f"{rsi_val:.1f}"
            res_dict["MACDヒスト"] = f"{macd_val:.2f}"

        # 総合判定
        if "様子見" in judgement:
            if score >= 40: judgement = "🔥 買・強気"
            elif score >= 20: judgement = "✨ 買・打診"
            elif score <= -40: judgement = "📉 売・逃げ推奨"
            elif score <= -20: judgement = "☔ 売・警戒"

        res_dict["判定"] = judgement
        res_dict["根拠"] = ", ".join(reasons) if reasons else "-"
        res_dict["スコア"] = score
        return res_dict

    except Exception as e:
        return None

# --- 画面表示 ---
st.title(f"🚀 株スキャナー Technical Pro：{mode.split(' ')[0]}")

if st.button('スキャン開始'):
    results = []
    interval = "5m" if "デイトレ" in mode else "1d"
    
    bar = st.progress(0)
    for i, t in enumerate(ticker_list):
        data = analyze_stock(t, interval, min_price, max_price, mode)
        if data: results.append(data)
        bar.progress((i + 1) / len(ticker_list))
        
    if results:
        df_res = pd.DataFrame(results)
        if not show_all: df_res = df_res[~df_res["判定"].str.contains("様子見")]

        if not df_res.empty:
            df_res["絶対値スコア"] = df_res["スコア"].abs()
            df_res = df_res.sort_values(by="絶対値スコア", ascending=False).drop(columns=["絶対値スコア"])
            
            # 列の並び替え
            if "デイトレ" in mode:
                cols = ["銘柄", "社名", "現在値", "判定", "状態(5m)", "RSI", "MACDヒスト", "ボラ(ATR)", "根拠", "スコア"]
            else:
                cols = ["銘柄", "社名", "現在値", "判定", "トレンド", "酒田五法", "決算警戒", "ボラ(ATR)", "根拠", "スコア"]
                
            st.dataframe(df_res[cols], use_container_width=True)
            
            if "デイトレ" in mode:
                st.success("🎯 デイトレモード：20分遅延を逆手に取り、「ヨコヨコでエネルギーを溜めてMACDが反転した瞬間の銘柄」を抽出しています。")
            else:
                st.success("🕯️ スイングモード：酒田五法（赤三兵、流れ星など）とトレンドライン接近による反転シグナルを監視しています。")
        else:
            st.warning("現在、強いサインが出ている銘柄はありません。")
    else:
        st.warning("データなし")
