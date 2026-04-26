import time
import requests
from tradebot.config.settings import BYBIT_BASE_URL, BYBIT_CATEGORY, BYBIT_INTERVAL_MAP, CANDLE_TTL

_candle_cache = {}
_price_cache = {}


def _normalize_symbol(symbol: str) -> str:
    symbol = (symbol or "").upper().replace("/", "").replace("-", "")
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    return symbol


def _normalize_kline(item):
    # Bybit v5 kline: [startTime, open, high, low, close, volume, turnover]
    return {
        "open_time": int(item[0]),
        "open": float(item[1]),
        "high": float(item[2]),
        "low": float(item[3]),
        "close": float(item[4]),
        "volume": float(item[5]),
        "close_time": int(item[0]),
    }


def fetch_klines(symbol: str, interval: str = "15m", limit: int = 200):
    bybit_interval = BYBIT_INTERVAL_MAP.get(interval, interval)
    url = f"{BYBIT_BASE_URL}/v5/market/kline"
    params = {
        "category": BYBIT_CATEGORY,
        "symbol": _normalize_symbol(symbol),
        "interval": bybit_interval,
        "limit": limit,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit kline error: {data}")
    rows = data.get("result", {}).get("list", []) or []
    candles = [_normalize_kline(x) for x in rows]
    candles.sort(key=lambda x: x["open_time"])
    return candles


def get_cached_candles(symbol: str, interval: str = "15m", limit: int = 200):
    key = f"{_normalize_symbol(symbol)}:{interval}:{limit}"
    ttl = CANDLE_TTL.get(interval, 120)
    cached = _candle_cache.get(key)
    now = time.time()
    if cached and now - cached["ts"] < ttl:
        return cached["data"]
    candles = fetch_klines(symbol, interval, limit)
    _candle_cache[key] = {"ts": now, "data": candles}
    return candles


def collect_candles(symbol: str):
    return {
        "15m": get_cached_candles(symbol, "15m", 200),
        "30m": get_cached_candles(symbol, "30m", 200),
        "1h": get_cached_candles(symbol, "1h", 200),
        "4h": get_cached_candles(symbol, "4h", 200),
        "1d": get_cached_candles(symbol, "1d", 200),
        "1w": get_cached_candles(symbol, "1w", 100),
    }


def get_current_price(symbol: str):
    symbol = _normalize_symbol(symbol)
    cached = _price_cache.get(symbol)
    now = time.time()
    if cached and now - cached["ts"] < 5:
        return cached["price"]
    url = f"{BYBIT_BASE_URL}/v5/market/tickers"
    params = {"category": BYBIT_CATEGORY, "symbol": symbol}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit ticker error: {data}")
    price = float(data["result"]["list"][0]["lastPrice"])
    _price_cache[symbol] = {"ts": now, "price": price}
    return price


def get_candles(symbol: str, interval="15", limit=60):
    # legacy compatibility: interval may be "15", "60", "D" or app interval like "15m".
    reverse = {v: k for k, v in BYBIT_INTERVAL_MAP.items()}
    app_interval = reverse.get(str(interval), str(interval))
    if app_interval.isdigit():
        app_interval = f"{app_interval}m"
    return get_cached_candles(symbol, app_interval, limit)
