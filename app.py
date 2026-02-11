import streamlit as st
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# ⚙️ バリュー株（低PBR・高配当）厳選リスト
# ==========================================
SECTOR_TICKERS = {
    "銀行・金融 (低PBRの宝庫)": {
        "8306.T": "三菱UFJ", "8316.T": "三井住友", "8411.T": "みずほ", "8591.T": "オリックス",
        "8604.T": "野村HD", "8766.T": "東京海上", "8725.T": "MS&AD", "8750.T": "第一生命",
        "7182.T": "ゆうちょ", "8308.T": "りそな", "8309.T": "三井住友トラ"
    },
    "商社・卸売 (割安・高配当)": {
        "8001.T": "伊藤忠", "8002.T": "丸紅", "8031.T": "三井物産", "8053.T": "住友商事",
        "8058.T": "三菱商事", "2768.T": "双日", "8015.T": "豊田通商", "8020.T": "兼松"
    },
    "鉄鋼・非鉄・素材 (景気敏感)": {
        "5401.T": "日本製鉄", "5411.T": "JFE", "5406.T": "神戸製鋼", "5713.T": "住友鉱山",
        "5714.T": "DOWA", "5706.T": "三井金", "3407.T": "旭化成", "4005.T": "住友化学",
        "4183.T": "三井化学", "4208.T": "UBE", "5020.T": "ENEOS", "1605.T": "INPEX"
    },
    "建設・不動産 (内需バリュー)": {
        "1801.T": "大成建設", "1802.T": "大林組", "1803.T": "清水建設", "1812.T": "鹿島",
        "1925.T": "大和ハウス", "1928.T": "積水ハウス", "8801.T": "三井不動産",
        "8802.T": "三菱地所", "8830.T": "住友不動産", "3289.T": "東急不HD"
    },
    "自動車・輸送機 (円安恩恵)": {
        "7203.T": "トヨタ", "7267.T": "ホンダ", "7201.T": "日産自", "7270.T": "SUBARU",
        "7269.T": "スズキ", "7272.T": "ヤマハ発", "7011.T": "三菱重工", "7012.T": "川崎重工",
        "7013.T": "IHI"
    },
    "通信・インフラ (安定収益)": {
        "9432.T": "NTT", "9433.T": "KDDI", "9434.T": "ソフトバンク", "9501.T": "東電HD",
        "9503.T": "関西電力", "9531.T": "東京ガス", "9532.T": "大阪ガス",
        "9020.T": "JR東", "9021.T": "JR西", "9022.T": "JR東海", "9101.T": "日本郵船",
        "9104.T": "商船三井", "9107.T": "川崎汽船"
    }
}

# 全銘柄リストの作成
ALL_TICKERS = {}
for sector, tickers in SECTOR_TICKERS.items():
    ALL_TICKERS.update(tickers)

# ==========================================
# 🧠 テクニカル分析ロジック
# ==========================================

def get_analysis(ticker, name):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="6mo")
        if len(df) < 60: return None

        close = df['Close']
        high = df['High']
        low = df['Low']
        
        # --- 1. RSI (14日) ---
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        curr_rsi = rsi.iloc[-1]
        
        # --- 2. MACD ヒストグラム ---
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist_now = macd_line.iloc[-1] - signal_line.iloc[-1]
        hist_change = hist_now - (macd_line.iloc[-2] - signal_line.iloc[-2])

        # --- 3. 抵抗線・支持線 ---
        resistance = high.rolling(50).max().iloc[-1] # バリュー株は動きが遅いので50日高値を意識
        support = low.rolling(50).min().iloc[-1]
        curr_price = close.iloc[-1]

        # --- 4. スコアリング ---
        score = 50
        # バリュー株の「押し目買い」ロジック
        if curr_rsi < 35: score += 20     # 売られすぎ
        elif curr_rsi < 45: score += 10
        
        if hist_now < 0 and hist_change > 0: score += 15 # 反発の兆し
        
        # バリュー株の「戻り売り」ロジック
        if curr_rsi > 75: score -= 20
        elif curr_rsi > 65: score -= 10
        
        return {
            "name": name,
            "code": ticker.replace(".T", ""),
            "price": curr_price,
            "rsi": curr_rsi,
            "score": score,
            "resistance": resistance,
            "support": support,
            "signal": "買い" if score >= 70 else ("売り" if score <= 30 else "様子見")
        }
    except:
        return None

def run_scan(target_tickers, min_p, max_p):
    results = []
    
    # 辞書からリストへ変換
    scan_list = list(target_tickers.keys())
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_analysis, t, target_tickers[t]) for t in scan_list]
        for f in futures:
            res = f.result()
            if res and (min_p <= res["price"] <= max_p):
                results.append(res)
                
    return results

# ==========================================
# 📱 アプリ画面 UI
# ==========================================

st.set_page_config(page_title="バリュー株スカウター", layout="wide")
st.title("💎 バリュー株スカウター (低PBR特化)")
st.caption("東証プライム・スタンダードの「割安・高配当」銘柄からチャンスを探します")

# --- サイドバーで業種選択 ---
st.sidebar.header("📂 業種フィルター")
selected_sectors = []
for sector in SECTOR_TICKERS.keys():
    if st.sidebar.checkbox(sector, value=True):
        selected_sectors.append(sector)

# 選択された業種の銘柄だけを抽出
target_dict = {}
for s in selected_sectors:
    target_dict.update(SECTOR_TICKERS[s])

# --- メイン画面設定 ---
col1, col2 = st.columns([1, 2])
with col1:
    st.write("##### 💰 価格帯")
    p_min = st.number_input("下限 (円)", value=100, step=100)
    p_max = st.number_input("上限 (円)", value=10000, step=100)
    
with col2:
    st.info(f"現在、**{len(target_dict)}銘柄** が監視対象です。\n左上の「＞」メニューから業種を絞り込めます。")

if st.button("🚀 割安株をスキャン開始", use_container_width=True):
    with st.spinner('バリュー株の状況を確認中...'):
        data = run_scan(target_dict, p_min, p_max)
    
    # --- 結果の整理 ---
    df = pd.DataFrame(data)
    
    if not df.empty:
        # 買い推奨（スコア高い順）
        buys = df[df["score"] >= 65].sort_values("score", ascending=False)
        # 売り推奨（スコア低い順）
        sells = df[df["score"] <= 35].sort_values("score", ascending=True)

        st.subheader("🔥 買いチャンス (押し目・反発狙い)")
        if not buys.empty:
            st.dataframe(
                buys[["name", "code", "price", "rsi", "resistance", "support"]].rename(
                    columns={"name":"銘柄", "code":"コード", "price":"現在値", "rsi":"RSI", "resistance":"上値目処", "support":"下値目処"}
                ), 
                use_container_width=True
            )
        else:
            st.write("現在、明確な買いシグナルはありません。")

        st.subheader("🧊 売りチャンス (過熱感あり)")
        if not sells.empty:
            st.dataframe(
                sells[["name", "code", "price", "rsi", "support", "resistance"]].rename(
                    columns={"name":"銘柄", "code":"コード", "price":"現在値", "rsi":"RSI", "support":"下値目処", "resistance":"上値目処"}
                ),
                use_container_width=True
            )
        else:
            st.write("現在、明確な売りシグナルはありません。")
    else:
        st.warning("条件に合う銘柄が見つかりませんでした。価格帯などを変更してみてください。")
