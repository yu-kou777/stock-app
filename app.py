import streamlit as st
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# ⚙️ 設定エリア
# ==========================================

# 監視対象：日経225銘柄（代表的なものを抜粋）
TICKERS = [
    "7203.T", "9984.T", "8306.T", "6758.T", "6861.T", "6920.T", "6098.T", "8035.T",
    "4063.T", "7974.T", "9432.T", "8058.T", "7267.T", "4502.T", "6501.T", "7741.T",
    "6367.T", "6902.T", "4543.T", "3382.T", "4519.T", "6273.T", "6954.T", "7269.T",
    "9101.T", "9104.T", "9107.T", "5401.T", "8316.T", "8411.T", "8766.T", "8801.T",
    "1605.T", "1925.T", "2413.T", "2502.T", "2801.T", "2914.T", "3407.T", "4503.T",
    "4507.T", "4523.T", "4568.T", "4578.T", "4661.T", "4901.T", "4911.T", "5020.T",
    "5108.T", "5713.T", "6146.T", "6301.T", "6326.T", "6503.T", "6594.T", "6702.T",
    "6723.T", "6752.T", "6762.T", "6857.T", "6971.T", "6981.T", "7011.T", "7201.T",
    "7270.T", "7272.T", "7733.T", "7751.T", "7832.T", "8001.T", "8002.T", "8015.T",
    "8031.T", "8053.T", "8604.T", "8630.T", "8725.T", "8750.T", "8802.T", "8830.T",
    "9020.T", "9021.T", "9022.T", "9202.T", "9735.T", "9843.T", "9983.T"
]

# ==========================================
# 🧠 分析ロジック
# ==========================================

def get_stock_data(ticker):
    """株価データを取得して指標を計算する"""
    try:
        stock = yf.Ticker(ticker)
        # 過去半年分のデータを取得
        hist = stock.history(period="6mo")
        
        if len(hist) < 30: return None

        # テクニカル指標の計算
        close = hist['Close']
        
        # 移動平均線 (SMA)
        sma5 = close.rolling(5).mean()
        sma25 = close.rolling(25).mean()
        
        # RSI (14日)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        
        # 直近データ
        curr_price = close.iloc[-1]
        curr_rsi = rsi.iloc[-1]
        
        # トレンド判定 (25日線の傾き)
        slope_25 = (sma25.iloc[-1] - sma25.iloc[-5]) / 5
        
        return {
            "code": ticker,
            "price": curr_price,
            "rsi": curr_rsi,
            "sma5": sma5.iloc[-1],
            "sma25": sma25.iloc[-1],
            "slope_25": slope_25,
            # 出来高急増度（直近 / 5日平均）
            "volume_ratio": hist['Volume'].iloc[-1] / (hist['Volume'].rolling(5).mean().iloc[-1] + 1)
        }
    except:
        return None

def analyze_market(min_price, max_price):
    """市場全体をスキャンしてスコアリングする"""
    results_buy = []
    results_sell = []
    
    # 並列処理で高速化
    with ThreadPoolExecutor(max_workers=10) as executor:
        data_list = list(executor.map(get_stock_data, TICKERS))
    
    for data in data_list:
        if data is None: continue
        
        price = data["price"]
        
        # 1. 価格帯フィルター
        if not (min_price <= price <= max_price): continue
        
        # --- 買いスコア (Swing Long) ---
        buy_score = 0
        if data["slope_25"] > 0: buy_score += 30 # 上昇トレンド
        if 30 <= data["rsi"] <= 50: buy_score += 40 # 押し目買いゾーン
        if data["price"] > data["sma25"]: buy_score += 20 # 25日線より上
        if data["volume_ratio"] > 1.5: buy_score += 10 # 出来高増加
        
        if buy_score >= 60:
            results_buy.append({**data, "score": buy_score})

        # --- 売りスコア (Swing Short / 信用売り) ---
        sell_score = 0
        if data["slope_25"] < 0: sell_score += 30 # 下落トレンド
        if 60 <= data["rsi"] <= 80: sell_score += 40 # 戻り売りゾーン
        if data["price"] < data["sma25"]: sell_score += 20 # 25日線より下
        
        if sell_score >= 60:
            results_sell.append({**data, "score": sell_score})

    # ランキング作成 (スコア順)
    results_buy = sorted(results_buy, key=lambda x: x["score"], reverse=True)[:10]
    results_sell = sorted(results_sell, key=lambda x: x["score"], reverse=True)[:10]
    
    return results_buy, results_sell

# ==========================================
# 📱 アプリ画面 (Streamlit)
# ==========================================

st.title("📈 翌日狙い目スキャナー")
st.write("日足チャートから、10日以内に利益が出そうな銘柄をAIが選定します。")

# サイドバー設定
st.sidebar.header("検索条件")
price_range = st.sidebar.slider("株価の範囲 (円)", 100, 20000, (1000, 5000))

# 分析ボタン
if st.button("🔍 市場をスキャンして分析開始"):
    st.info("データ取得中... (約10〜30秒かかります)")
    buy_list, sell_list = analyze_market(price_range[0], price_range[1])
    
    # --- 買い候補の表示 ---
    st.header(f"🚀 買い (Long) 推奨 TOP{len(buy_list)}")
    st.success("上昇トレンド中の押し目、または反発狙いの銘柄です。")
    if buy_list:
        df_buy = pd.DataFrame(buy_list)[["code", "price", "rsi", "score"]]
        df_buy.columns = ["コード", "現在値", "RSI", "スコア"]
        st.table(df_buy)
    else:
        st.write("条件に合う買い銘柄が見つかりませんでした。")

    # --- 売り候補の表示 ---
    st.header(f"📉 空売り (Short) 推奨 TOP{len(sell_list)}")
    st.error("下落トレンド中の戻り、または加熱感のある銘柄です（信用取引）。")
    if sell_list:
        df_sell = pd.DataFrame(sell_list)[["code", "price", "rsi", "score"]]
        df_sell.columns = ["コード", "現在値", "RSI", "スコア"]
        st.table(df_sell)
    else:
        st.write("条件に合う売り銘柄が見つかりませんでした。")
