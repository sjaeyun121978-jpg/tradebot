import requests


BASE_URL = "https://api.bybit.com"


# =========================
# 현재가 조회
# =========================
def get_current_price(symbol):
    try:
        url = f"{BASE_URL}/v5/market/tickers"
        params = {
            "category": "linear",
            "symbol": f"{symbol}USDT"
        }

        r = requests.get(url, params=params, timeout=5).json()
        return float(r["result"]["list"][0]["lastPrice"])

    except Exception as e:
        print(f"[가격 조회 실패] {e}")
        return None


# =========================
# 캔들 조회
# =========================
def get_candles(symbol, interval="15", limit=60):
    try:
        url = f"{BASE_URL}/v5/market/kline"

        params = {
            "category": "linear",
            "symbol": f"{symbol}USDT",
            "interval": interval,
            "limit": limit
        }

        r = requests.get(url, params=params, timeout=5).json()
        return r["result"]["list"]

    except Exception as e:
        print(f"[캔들 조회 실패] {e}")
        return []
