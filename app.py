import yfinance as yf
import pandas as pd
import pandas_ta as ta
import streamlit as st
from datetime import datetime

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
    "1605.T": "INPEX", "5020.T": "ENEOS", "6330.T": "東洋エンジ"
}
MARKET_TICKERS = list(TICKER_MAP.keys())

# --- サイドバー ---
st.sidebar.title("🎛️ テクニカル特化・操作盤")
mode = st.sidebar.radio("戦術モード", ("デイトレ (5分足・遅延対策済み)", "スイング (日足・60日線＆酒田五法)"))
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

# --- 酒田五法 判定ロジック ---
def check_sakata_gohou(df):
    if len(df) < 4: return "-", 0
    signals = []
    score_change = 0
    
    c0, o0, h0, l0 = df.iloc[-1]['Close'], df.iloc[-1]['Open'], df.iloc[-1]['High'], df.iloc[-1]['Low']
    c1, o1, h1, l1 = df.iloc[-2]['Close'], df.iloc[-2]['Open'], df.iloc[-2]['High'], df.iloc[-2]['Low']
    c2, o2, h2, l2 = df.iloc[-3]['Close'], df.iloc[-3]['Open'], df.iloc[-3]['High'], df.iloc[-3]['Low']
    
    body0 = abs(c0-o0); body1 = abs(c1-o1); body2 = abs(c2-o2)
    is_up0 = c0 > o0; is_up1 = c1 > o1; is_up2 = c2 > o2
    is_down0 = c0 < o0; is_down1 = c1 < o1; is_down2 = c2 < o2

    if is_up0 and is_up1 and is_up2 and c0 > c1 > c2:
        signals.append("🔥赤三兵(特級買)")
        score_change += 40
    if is_down0 and is_down1 and is_down2 and c0 < c1 < c2:
        signals.append("⚠️黒三兵(特級売)")
        score_change -= 40

    upper_shadow0 = h0 - max(c0, o0)
    lower_shadow0 = min(c0, o0) - l0
    if upper_shadow0 > body0 * 2.0 and lower_shadow0 < body0 * 0.5:
        if df.iloc[-1]['Close'] > df.iloc[-1]['MA_60']: 
            signals.append("🌠流れ星(急落警戒)")
            score_change -= 50

    if is_down2 and body2 > (h2-l2)*0.6 and body1 < (h1-l1)*0.3 and is_up0 and c0 > (o2+c2)/2:
        signals.append("🌅明けの明星(特級買)")
        score_change += 50

    signal_text = " / ".join(signals) if signals else "なし"
    return signal_text, score_change

# --- 解析エンジン ---
def analyze_stock(ticker, interval, min_p, max_p, mode_name):
    try:
        # スイング時は正確な60日線を引くため1年分取得
        period = "5d" if interval == "5m" else "1y" 
        tkr = yf.Ticker(ticker)
        df = tkr.history(period=period, interval=interval)
        if len(df) < 65: return None
        
        df = flatten_data(df)
        
        # テクニカル指標の計算
        df['MA_Short'] = ta.sma(df['Close'], length=5)
        df['MA_Long'] = ta.sma(df['Close'], length=25 if interval=="1d" else 20)
        
        # ★ 60日移動平均線の追加 ★
        if interval == "1d":
            df['MA_60'] = ta.sma(df['Close'], length=60)
        else:
            df['MA_60'] = df['MA_Long'] # デイトレ時はダミー
            
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
        
        vola_pct = (latest['ATR'] / price) * 100
        res_dict = {
            "銘柄": ticker.replace(".T", ""),
            "社名": TICKER_MAP.get(ticker, "-"),
            "現在値": f"{int(price)}",
            "ボラ(ATR)": f"{vola_pct:.1f}%",
        }

        # ==========================================
        # 📉 スイングモード (日足: 60日線 ＆ 酒田五法)
        # ==========================================
        if "スイング" in mode_name:
            ma60_val = float(latest['MA_60'])
            ma60_prev = float(df.iloc[-5]['MA_60']) # 5日前の60日線（傾き確認用）
            
            # 60日線との距離（%）
            dist_ma60 = (price - ma60_val) / ma60_val * 100

            # ★ 1. 60日線サポート反発狙い (最強の買い根拠)
            if 0 <= dist_ma60 <= 2.5: # 60日線の少し上〜ピッタリ
                if ma60_val >= ma60_prev: # 60日線が横ばい〜上向き
                    score += 40
                    reasons.append("🎯60日線サポート接近")
            
            # ★ 2. 下落トレンドのストッパー (ダマシ回避)
            is_downtrend = price < ma60_val and ma60_val < ma60_prev
            if is_downtrend:
                score -= 50
                reasons.append("⚠️完全下落トレンド(MA60下)")

            # 酒田五法判定
            sakata_signal, sakata_score = check_sakata_gohou(df)
            score += sakata_score
            if sakata_signal != "なし": reasons.append(sakata_signal)

            # ゴールデン/デッドクロス判定
            if prev['MA_Short'] <= prev['MA_Long'] and latest['MA_Short'] > latest['MA_Long']:
                score += 30; reasons.append("✨Gクロス(5/25)")
            elif prev['MA_Short'] >= prev['MA_Long'] and latest['MA_Short'] < latest['MA_Long']:
                score -= 30; reasons.append("💀Dクロス(5/25)")

            # 下落トレンド中の厳格な判定上書き
            if is_downtrend and "特級買" not in sakata_signal:
                judgement = "🚫 買厳禁(ダマシ警戒)"
            elif score >= 40: judgement = "🔥 買・強気"
            elif score >= 20: judgement = "✨ 買・打診"
            elif score <= -40: judgement = "📉 売・逃げ推奨"
            elif score <= -20: judgement = "☔ 売・警戒"

            res_dict["トレンド(60MA)"] = "📉 下落(MA60下)" if is_downtrend else f"乖離 {dist_ma60:.1f}%"
            res_dict["酒田五法"] = sakata_signal

        # ==========================================
        # 🚀 デイトレモード (5分足: ヨコヨコ脱出)
        # ==========================================
        else:
            recent_12_high = df['High'].tail(12).max()
            recent_12_low = df['Low'].tail(12).min()
            box_pct = (recent_12_high - recent_12_low) / recent_12_low * 100
            
            is_yokoyoko = box_pct < 0.8
            state = "🔄 ヨコヨコ(蓄積中)" if is_yokoyoko else "⚡ トレンド発生中"
            
            macd_val = float(latest['MACDh_12_26_9'])
            macd_prev = float(prev['MACDh_12_26_9'])
            rsi_val = float(latest['RSI'])

            if is_yokoyoko and macd_prev < 0 and macd_val > 0:
                score += 50; reasons.append("🔥ヨコヨコ上抜け初動")
                judgement = "🔥 買い(初動)"
            elif is_yokoyoko and macd_prev > 0 and macd_val < 0:
                score -= 50; reasons.append("⚠️ヨコヨコ下抜け")
                judgement = "📉 売り(初動)"

            if rsi_val < 25: score += 20; reasons.append("RSI売られすぎ")
            elif rsi_val > 75: score -= 30; reasons.append("RSI買われすぎ")

            if "様子見" in judgement:
                if score >= 40: judgement = "🔥 買・強気"
                elif score >= 20: judgement = "✨ 買・打診"
                elif score <= -40: judgement = "📉 売・逃げ推奨"
                elif score <= -20: judgement = "☔ 売・警戒"

            res_dict["状態(5m)"] = state
            res_dict["RSI"] = f"{rsi_val:.1f}"
            res_dict["MACDヒスト"] = f"{macd_val:.2f}"

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
            
            if "デイトレ" in mode:
                cols = ["銘柄", "社名", "現在値", "判定", "状態(5m)", "RSI", "MACDヒスト", "ボラ(ATR)", "根拠", "スコア"]
            else:
                cols = ["銘柄", "社名", "現在値", "判定", "トレンド(60MA)", "酒田五法", "ボラ(ATR)", "根拠", "スコア"]
                
            st.dataframe(df_res[cols], use_container_width=True)
            
            if "スイング" in mode:
                st.success("🛡️ 60日移動平均線を基準に、強力なサポート反発狙いと、下落トレンド中の「買い厳禁」フィルターを稼働させています。")
        else:
            st.warning("現在、強いサインが出ている銘柄はありません。")
    else:
        st.warning("データなし")
