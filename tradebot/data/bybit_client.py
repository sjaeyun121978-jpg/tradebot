"""
bybit_client.py v6
Bybit v5 공개 API 수집 모듈

기본:
  collect_candles()      - 캔들 OHLCV
  get_current_price()    - 현재가

마켓 데이터 (1~5순위):
  get_orderbook()        - 오더북 (매수벽/매도벽)
  get_recent_trades()    - 체결 데이터 (CVD)
  get_open_interest()    - 미결제약정 (OI)
  get_funding_rate()     - 펀딩비
  get_liquidations()     - 청산 데이터
  get_long_short_ratio() - 롱숏 비율
  collect_market_data()  - 위 전부 한 번에 수집
"""

import time
import requests
from tradebot.config.settings import (
    BYBIT_BASE_URL, BYBIT_CATEGORY, BYBIT_INTERVAL_MAP, CANDLE_TTL
)

_candle_cache = {}
_price_cache  = {}
_market_cache = {}

_MARKET_TTL = {
    "orderbook":        10,
    "recent_trades":    15,
    "open_interest":    60,
    "funding_rate":    300,
    "liquidations":     30,
    "long_short_ratio": 60,
}


# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────

def _normalize_symbol(symbol: str) -> str:
    symbol = (symbol or "").upper().replace("/", "").replace("-", "")
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    return symbol


def _normalize_kline(item):
    return {
        "open_time": int(item[0]),
        "open":      float(item[1]),
        "high":      float(item[2]),
        "low":       float(item[3]),
        "close":     float(item[4]),
        "volume":    float(item[5]),
        "close_time": int(item[0]),
    }


def _cached(key, ttl_key):
    c = _market_cache.get(key)
    if c and time.time() - c["ts"] < _MARKET_TTL.get(ttl_key, 60):
        return c["data"]
    return None


def _store(key, data):
    _market_cache[key] = {"ts": time.time(), "data": data}


# 실패 캐시 (30초) — API 실패 시 반복 호출 방지
_fail_cache = {}
_FAIL_TTL   = 30


def _get(url, params, timeout=10):
    # 실패 캐시 확인
    cache_key = f"{url}:{sorted(params.items())}"
    if cache_key in _fail_cache:
        if time.time() - _fail_cache[cache_key] < _FAIL_TTL:
            return {}
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        d = r.json()
        if d.get("retCode") != 0:
            print(f"[BYBIT] retCode={d.get('retCode')} {d.get('retMsg')} {url}", flush=True)
            _fail_cache[cache_key] = time.time()
            return {}
        # 성공 시 실패 캐시 제거
        _fail_cache.pop(cache_key, None)
        return d.get("result", {})
    except Exception as e:
        print(f"[BYBIT ERROR] {url} {e}", flush=True)
        _fail_cache[cache_key] = time.time()
        return {}


# ─────────────────────────────────────────────
# 기존: 캔들 / 현재가
# ─────────────────────────────────────────────

def fetch_klines(symbol, interval="15m", limit=200):
    bybit_interval = BYBIT_INTERVAL_MAP.get(interval, interval)
    url = f"{BYBIT_BASE_URL}/v5/market/kline"
    params = {"category": BYBIT_CATEGORY, "symbol": _normalize_symbol(symbol),
              "interval": bybit_interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit kline error: {data}")
    rows = data.get("result", {}).get("list", []) or []
    candles = [_normalize_kline(x) for x in rows]
    candles.sort(key=lambda x: x["open_time"])
    return candles


def get_cached_candles(symbol, interval="15m", limit=200):
    key = f"{_normalize_symbol(symbol)}:{interval}:{limit}"
    ttl = CANDLE_TTL.get(interval, 120)
    cached = _candle_cache.get(key)
    now = time.time()
    if cached and now - cached["ts"] < ttl:
        return cached["data"]
    candles = fetch_klines(symbol, interval, limit)
    _candle_cache[key] = {"ts": now, "data": candles}
    return candles


def collect_candles(symbol):
    return {
        "15m": get_cached_candles(symbol, "15m", 200),
        "30m": get_cached_candles(symbol, "30m", 200),
        "1h":  get_cached_candles(symbol, "1h",  200),
        "4h":  get_cached_candles(symbol, "4h",  200),
        "1d":  get_cached_candles(symbol, "1d",  200),
        "1w":  get_cached_candles(symbol, "1w",  100),
    }


def get_current_price(symbol):
    symbol = _normalize_symbol(symbol)
    cached = _price_cache.get(symbol)
    now = time.time()
    if cached and now - cached["ts"] < 5:
        return cached["price"]
    url = f"{BYBIT_BASE_URL}/v5/market/tickers"
    r = requests.get(url, params={"category": BYBIT_CATEGORY, "symbol": symbol}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit ticker error: {data}")
    price = float(data["result"]["list"][0]["lastPrice"])
    _price_cache[symbol] = {"ts": now, "price": price}
    return price


def get_candles(symbol, interval="15", limit=60):
    reverse = {v: k for k, v in BYBIT_INTERVAL_MAP.items()}
    app_interval = reverse.get(str(interval), str(interval))
    if app_interval.isdigit():
        app_interval = f"{app_interval}m"
    return get_cached_candles(symbol, app_interval, limit)


# ─────────────────────────────────────────────
# 1순위: 오더북
# ─────────────────────────────────────────────

def get_orderbook(symbol, depth=50):
    symbol = _normalize_symbol(symbol)
    key = f"ob:{symbol}:{depth}"
    cached = _cached(key, "orderbook")
    if cached:
        return cached

    result = _get(f"{BYBIT_BASE_URL}/v5/market/orderbook",
                  {"category": BYBIT_CATEGORY, "symbol": symbol, "limit": depth})
    if not result:
        return _empty_ob()

    bids = [(float(p), float(q)) for p, q in result.get("b", [])]
    asks = [(float(p), float(q)) for p, q in result.get("a", [])]
    if not bids or not asks:
        return _empty_ob()

    top_bids = sorted(bids, key=lambda x: x[0], reverse=True)[:10]
    top_asks = sorted(asks, key=lambda x: x[0])[:10]
    bid_total = sum(q for _, q in top_bids)
    ask_total = sum(q for _, q in top_asks)
    bid_wall  = max(bids, key=lambda x: x[1])
    ask_wall  = max(asks, key=lambda x: x[1])
    imbalance = bid_total / ask_total if ask_total > 0 else 1.0
    best_bid  = top_bids[0][0]
    best_ask  = top_asks[0][0]
    spread    = (best_ask - best_bid) / best_bid * 100 if best_bid > 0 else 0
    all_qty   = [q for _, q in bids + asks]
    avg_qty   = sum(all_qty) / len(all_qty) if all_qty else 1
    wall_ratio = max(bid_wall[1], ask_wall[1]) / avg_qty

    pressure = "BUY" if imbalance >= 1.3 else ("SELL" if imbalance <= 0.77 else "NEUTRAL")

    data = {
        "bid_wall":   {"price": bid_wall[0], "qty": bid_wall[1]},
        "ask_wall":   {"price": ask_wall[0], "qty": ask_wall[1]},
        "bid_total":  bid_total, "ask_total": ask_total,
        "imbalance":  round(imbalance, 3), "spread_pct": round(spread, 4),
        "pressure":   pressure, "wall_ratio": round(wall_ratio, 2),
        "best_bid":   best_bid, "best_ask":   best_ask, "usable": True,
    }
    _store(key, data)
    return data


def _empty_ob():
    return {"bid_wall": {"price": 0, "qty": 0}, "ask_wall": {"price": 0, "qty": 0},
            "bid_total": 0, "ask_total": 0, "imbalance": 1.0, "spread_pct": 0,
            "pressure": "NEUTRAL", "wall_ratio": 1, "best_bid": 0, "best_ask": 0, "usable": False}


# ─────────────────────────────────────────────
# 2순위: 체결 데이터 (CVD)
# ─────────────────────────────────────────────

def get_recent_trades(symbol, limit=500):
    symbol = _normalize_symbol(symbol)
    key = f"trades:{symbol}:{limit}"
    cached = _cached(key, "recent_trades")
    if cached:
        return cached

    result = _get(f"{BYBIT_BASE_URL}/v5/market/recent-trade",
                  {"category": BYBIT_CATEGORY, "symbol": symbol, "limit": limit})
    if not result:
        return _empty_trades()

    trades = result.get("list", [])
    buy_vol = sell_vol = 0.0
    sizes = []
    for t in trades:
        try:
            size = float(t.get("size", 0))
            sizes.append(size)
            if t.get("side", "").upper() == "BUY":
                buy_vol += size
            else:
                sell_vol += size
        except Exception:
            continue

    total     = buy_vol + sell_vol
    cvd       = buy_vol - sell_vol
    buy_ratio = buy_vol / total * 100 if total > 0 else 50
    avg_size  = sum(sizes) / len(sizes) if sizes else 0
    large     = sum(1 for s in sizes if s >= avg_size * 5)
    signal    = "BULLISH" if buy_ratio >= 58 else ("BEARISH" if buy_ratio <= 42 else "NEUTRAL")

    data = {"cvd": round(cvd, 4), "buy_volume": round(buy_vol, 4),
            "sell_volume": round(sell_vol, 4), "buy_ratio": round(buy_ratio, 2),
            "large_trades": large, "cvd_signal": signal,
            "avg_trade_size": round(avg_size, 4), "usable": True}
    _store(key, data)
    return data


def _empty_trades():
    return {"cvd": 0, "buy_volume": 0, "sell_volume": 0, "buy_ratio": 50,
            "large_trades": 0, "cvd_signal": "NEUTRAL", "avg_trade_size": 0, "usable": False}


# ─────────────────────────────────────────────
# 3순위: OI
# ─────────────────────────────────────────────

def get_open_interest(symbol):
    symbol = _normalize_symbol(symbol)
    key = f"oi:{symbol}"
    cached = _cached(key, "open_interest")
    if cached:
        return cached

    result = _get(f"{BYBIT_BASE_URL}/v5/market/open-interest",
                  {"category": BYBIT_CATEGORY, "symbol": symbol, "intervalTime": "1h", "limit": 3})
    if not result:
        return _empty_oi()

    oi_list = result.get("list", [])
    if not oi_list or len(oi_list) < 2:
        return _empty_oi()

    try:
        cur  = float(oi_list[0].get("openInterest", 0))
        prev = float(oi_list[1].get("openInterest", 0))
    except Exception:
        return _empty_oi()

    change = (cur - prev) / prev * 100 if prev > 0 else 0
    signal = "INCREASING" if change >= 2.0 else ("DECREASING" if change <= -2.0 else "STABLE")

    data = {"oi_value": round(cur, 2), "oi_1h_change": round(change, 3),
            "oi_signal": signal, "oi_divergence": "BULLISH" if signal == "INCREASING" else "NEUTRAL",
            "usable": True}
    _store(key, data)
    return data


def _empty_oi():
    return {"oi_value": 0, "oi_1h_change": 0, "oi_signal": "STABLE",
            "oi_divergence": "NEUTRAL", "usable": False}


# ─────────────────────────────────────────────
# 3순위: 펀딩비
# ─────────────────────────────────────────────

def get_funding_rate(symbol):
    symbol = _normalize_symbol(symbol)
    key = f"fr:{symbol}"
    cached = _cached(key, "funding_rate")
    if cached:
        return cached

    result = _get(f"{BYBIT_BASE_URL}/v5/market/tickers",
                  {"category": BYBIT_CATEGORY, "symbol": symbol})
    if not result:
        return _empty_fr()

    tl = result.get("list", [])
    if not tl:
        return _empty_fr()

    try:
        fr      = float(tl[0].get("fundingRate", 0)) * 100
        next_ms = int(tl[0].get("nextFundingTime", 0))
        minutes = max(0, (next_ms // 1000 - int(time.time())) // 60)
    except Exception:
        return _empty_fr()

    if fr >= 0.05:   signal = "LONG_OVERHEATED"
    elif fr <= -0.05: signal = "SHORT_OVERHEATED"
    elif fr >= 0.01:  signal = "LONG_MILD"
    elif fr <= -0.01: signal = "SHORT_MILD"
    else:             signal = "NEUTRAL"

    data = {"funding_rate": round(fr, 6), "minutes_to_fund": minutes,
            "signal": signal,
            "interpretation": f"펀딩비 {fr:.4f}% ({signal})",
            "usable": True}
    _store(key, data)
    return data


def _empty_fr():
    return {"funding_rate": 0, "minutes_to_fund": 0, "signal": "NEUTRAL",
            "interpretation": "펀딩비 데이터 없음", "usable": False}


# ─────────────────────────────────────────────
# 4순위: 청산
# ─────────────────────────────────────────────

def get_liquidations(symbol, limit=200):
    symbol = _normalize_symbol(symbol)
    key = f"liq:{symbol}"
    cached = _cached(key, "liquidations")
    if cached:
        return cached

    result = _get(f"{BYBIT_BASE_URL}/v5/market/liquidation",
                  {"category": BYBIT_CATEGORY, "symbol": symbol, "limit": limit})
    if not result:
        return _empty_liq()

    liq_list = result.get("list", [])
    if not liq_list:
        return _empty_liq()

    long_usd = short_usd = 0.0
    sizes = []
    for liq in liq_list:
        try:
            usd  = float(liq.get("size", 0)) * float(liq.get("price", 0))
            side = liq.get("side", "").upper()
            sizes.append(usd)
            if side == "BUY":
                long_usd += usd
            else:
                short_usd += usd
        except Exception:
            continue

    ratio    = long_usd / short_usd if short_usd > 0 else 1.0
    avg_liq  = sum(sizes) / len(sizes) if sizes else 0
    large    = sum(1 for s in sizes if s >= avg_liq * 5)
    dominant = "LONG_LIQUIDATED" if ratio >= 1.5 else ("SHORT_LIQUIDATED" if ratio <= 0.67 else "BALANCED")

    data = {"long_liq_usd": round(long_usd, 2), "short_liq_usd": round(short_usd, 2),
            "liq_ratio": round(ratio, 3), "dominant": dominant,
            "large_liq": large,
            "signal": f"{'롱' if dominant == 'LONG_LIQUIDATED' else '숏'} 청산 우세",
            "usable": True}
    _store(key, data)
    return data


def _empty_liq():
    return {"long_liq_usd": 0, "short_liq_usd": 0, "liq_ratio": 1,
            "dominant": "BALANCED", "large_liq": 0, "signal": "청산 데이터 없음", "usable": False}


# ─────────────────────────────────────────────
# 5순위: 롱숏 비율
# ─────────────────────────────────────────────

def get_long_short_ratio(symbol):
    symbol = _normalize_symbol(symbol)
    key = f"ls:{symbol}"
    cached = _cached(key, "long_short_ratio")
    if cached:
        return cached

    result = _get(f"{BYBIT_BASE_URL}/v5/market/account-ratio",
                  {"category": BYBIT_CATEGORY, "symbol": symbol, "period": "1h", "limit": 1})
    if not result:
        return _empty_ls()

    ls = result.get("list", [])
    if not ls:
        return _empty_ls()

    try:
        long_pct  = float(ls[0].get("buyRatio",  0)) * 100
        short_pct = float(ls[0].get("sellRatio", 0)) * 100
        ratio     = long_pct / short_pct if short_pct > 0 else 1.0
    except Exception:
        return _empty_ls()

    if long_pct >= 65:    signal = "LONG_CROWDED"
    elif short_pct >= 65: signal = "SHORT_CROWDED"
    elif long_pct >= 55:  signal = "LONG_MILD"
    elif short_pct >= 55: signal = "SHORT_MILD"
    else:                 signal = "NEUTRAL"

    data = {"long_pct": round(long_pct, 2), "short_pct": round(short_pct, 2),
            "ls_ratio": round(ratio, 3), "signal": signal,
            "contrarian": f"롱 {long_pct:.1f}% / 숏 {short_pct:.1f}% ({signal})",
            "usable": True}
    _store(key, data)
    return data


def _empty_ls():
    return {"long_pct": 50, "short_pct": 50, "ls_ratio": 1,
            "signal": "NEUTRAL", "contrarian": "롱숏 데이터 없음", "usable": False}


# ─────────────────────────────────────────────
# 통합 수집 (jobs.py에서 호출)
# ─────────────────────────────────────────────

def collect_market_data(symbol: str) -> dict:
    """1~5순위 마켓 데이터 한 번에 수집. 개별 실패해도 전체 죽지 않음."""
    def _safe(fn):
        try:
            return fn(symbol)
        except Exception as e:
            print(f"[MARKET DATA ERROR] {fn.__name__} {symbol}: {e}", flush=True)
            return {}

    return {
        "orderbook":        _safe(get_orderbook),
        "trades":           _safe(get_recent_trades),
        "open_interest":    _safe(get_open_interest),
        "funding_rate":     _safe(get_funding_rate),
        "liquidations":     _empty_liq(),
        "long_short_ratio": _safe(get_long_short_ratio),
    }
