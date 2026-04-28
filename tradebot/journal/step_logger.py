"""
step_logger.py
STEP 이벤트 로그 + 시장 스냅샷 저장 모듈

저장 경로:
  logs/step_log.json        — STEP 발생 이력 (append)
  logs/market_snapshot.json — 시장 스냅샷 (symbol 키 기반 덮어쓰기)
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Any

KST = timezone(timedelta(hours=9))
BASE_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
STEP_LOG  = os.path.join(BASE_DIR, "step_log.json")
SNAP_FILE = os.path.join(BASE_DIR, "market_snapshot.json")

_lock = threading.Lock()

# ─────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────

def _ensure_dir():
    os.makedirs(BASE_DIR, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _read_json(path: str, default: Any) -> Any:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _write_json(path: str, data: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _safe_float(v, d=0.0):
    try:
        return float(v) if v is not None else d
    except Exception:
        return d


def _get(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default


# ─────────────────────────────────────────────
# [1] STEP 로그 저장
# ─────────────────────────────────────────────

def save_step_log(
    symbol:         str,
    step_type:      str,   # WAIT / EARLY / PRE / REAL
    decision:       dict,
    candles_by_tf:  dict,
    result:         dict | None = None,
) -> dict:
    """
    STEP 이벤트를 logs/step_log.json 에 append 저장한다.

    반환: 저장된 entry dict
    """
    _ensure_dir()

    candles_15m = candles_by_tf.get("15m") or []
    current_candle = candles_15m[-1] if candles_15m else {}
    if isinstance(current_candle, dict):
        price = _safe_float(_get(current_candle, "close", default=0))
    elif isinstance(current_candle, (list, tuple)) and len(current_candle) >= 5:
        price = _safe_float(current_candle[4])
    else:
        price = _safe_float(decision.get("current_price", 0))

    # reversal 정보
    rev_score  = int(_safe_float(decision.get("reversal_score",  0)))
    rev_stage  = str(decision.get("reversal_stage",  "NONE") or "NONE")
    rev_dir    = str(decision.get("reversal_direction", "NONE") or "NONE")

    # sig_data에서 추세/거래량 정보 추출 (result 또는 decision 병합값)
    sig_data   = result or {}
    trend_1h   = str(_get(sig_data, "trend_1h",  default="") or decision.get("trend_1h",  "") or "")
    trend_4h   = str(_get(sig_data, "trend_4h",  default="") or decision.get("trend_4h",  "") or "")
    vol_ratio  = _safe_float(_get(sig_data, "volume_ratio",
                             _get(sig_data, "vol_ratio",
                             decision.get("volume_ratio"))))

    entry = {
        "id":               f"{symbol}_{_now_iso().replace(':', '').replace('-', '')}",
        "timestamp":        _now_iso(),
        "symbol":           symbol,
        "step":             step_type,
        "direction":        str(decision.get("direction",           "WAIT") or "WAIT"),
        "candidate_dir":    str(decision.get("candidate_direction", "")    or ""),
        "price":            price,
        "reversal_score":   rev_score,
        "reversal_stage":   rev_stage,
        "reversal_dir":     rev_dir,
        "reversal_reasons": (decision.get("reversal_reasons") or [])[:4],
        "market_state":     str(decision.get("market_state", "") or ""),
        "block_reason":     str(decision.get("block_reason", "") or ""),
        "trade_allowed":    bool(decision.get("trade_allowed", False)),
        "confidence":       _safe_float(decision.get("confidence", 0)),
        # 오답 패턴 분석용 보강 필드
        "reversal_direction":    rev_dir,
        "reversal_long_score":   int(_safe_float(decision.get("reversal_long_score",  0))),
        "reversal_short_score":  int(_safe_float(decision.get("reversal_short_score", 0))),
        "early_confirm":         int(_safe_float(decision.get("reversal_early_confirm", 0))),
        "volume_ratio":          round(vol_ratio, 3),
        "trend_1h":              trend_1h,
        "trend_4h":              trend_4h,
        "early_entry":           bool(decision.get("early_entry", False)),
        "reversal_promoted":     bool(decision.get("reversal_promoted", False)),
        "reversal_block":        bool(decision.get("reversal_block", False)),
        # 복기용 결과 필드 (backtest_engine이 채움)
        "result_price":     None,
        "result_pct":       None,
        "result_fav_pct":   None,
        "result_adv_pct":   None,
        "result_label":     None,   # "SUCCESS" / "FAIL" / "NEUTRAL"
        "reviewed":         False,
    }

    with _lock:
        logs = _read_json(STEP_LOG, [])
        logs.append(entry)
        # 최대 2000개 유지
        if len(logs) > 2000:
            logs = logs[-2000:]
        _write_json(STEP_LOG, logs)

    return entry


# ─────────────────────────────────────────────
# [2] 시장 스냅샷 저장
# ─────────────────────────────────────────────

def _extract_indicators(candles_15m: list) -> dict:
    """15분봉에서 EMA20 / RSI / MACD 계산"""
    closes = []
    for c in candles_15m[-50:]:
        if isinstance(c, dict):
            v = _safe_float(c.get("close", 0))
        elif isinstance(c, (list, tuple)) and len(c) >= 5:
            v = _safe_float(c[4])
        else:
            continue
        if v > 0:
            closes.append(v)

    if not closes:
        return {}

    # EMA
    def ema(vals, p):
        k = 2 / (p + 1); e = vals[0]
        for v in vals: e = v*k + e*(1-k)
        return round(e, 4)

    ema20  = ema(closes, 20)
    ema50  = ema(closes, 50) if len(closes) >= 50 else None
    ema200 = ema(closes, 200) if len(closes) >= 200 else None

    # RSI (14)
    rsi = None
    if len(closes) >= 15:
        gains = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
        losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
        ag = sum(gains[-14:]) / 14
        al = sum(losses[-14:]) / 14
        rsi = round(100 - 100/(1 + ag/al), 2) if al != 0 else 100.0

    # MACD (12/26/9)
    macd_val = None
    if len(closes) >= 26:
        fast = ema(closes, 12)
        slow = ema(closes, 26)
        macd_val = round(fast - slow, 4)

    return {
        "ema20":  ema20,
        "ema50":  ema50,
        "ema200": ema200,
        "rsi":    rsi,
        "macd":   macd_val,
    }


def save_market_snapshot(
    symbol:        str,
    candles_by_tf: dict,
    market_data:   dict | None = None,
) -> None:
    """
    시장 스냅샷을 logs/market_snapshot.json 에 저장한다.
    symbol 키로 덮어쓴다 (최신 상태 유지).
    """
    _ensure_dir()

    candles_15m = candles_by_tf.get("15m") or []
    candles_1h  = candles_by_tf.get("1h")  or []
    candles_4h  = candles_by_tf.get("4h")  or []

    # 최근 10봉만 저장 (용량 절감)
    def slim_candles(cs, n=10):
        out = []
        for c in (cs[-n:] if len(cs) > n else cs):
            if isinstance(c, dict):
                out.append({
                    "t": c.get("open_time") or c.get("time"),
                    "o": _safe_float(c.get("open")),
                    "h": _safe_float(c.get("high")),
                    "l": _safe_float(c.get("low")),
                    "c": _safe_float(c.get("close")),
                    "v": _safe_float(c.get("volume")),
                })
            elif isinstance(c, (list, tuple)) and len(c) >= 6:
                out.append({"t":c[0],"o":_safe_float(c[1]),"h":_safe_float(c[2]),
                            "l":_safe_float(c[3]),"c":_safe_float(c[4]),"v":_safe_float(c[5])})
        return out

    md  = market_data or {}
    ind = _extract_indicators(candles_15m)

    snapshot = {
        "timestamp":   _now_iso(),
        "symbol":      symbol,
        "candles_15m": slim_candles(candles_15m, 10),
        "candles_1h":  slim_candles(candles_1h,  5),
        "candles_4h":  slim_candles(candles_4h,  3),
        "indicators": {
            "ema20":  ind.get("ema20"),
            "ema50":  ind.get("ema50"),
            "rsi":    ind.get("rsi"),
            "macd":   ind.get("macd"),
        },
        "orderbook": md.get("orderbook") or md.get("order_book"),
        "cvd":        md.get("cvd"),
        "oi":         md.get("open_interest") or md.get("oi"),
        "funding":    md.get("funding"),
    }

    with _lock:
        snaps = _read_json(SNAP_FILE, {})
        snaps[symbol] = snapshot
        _write_json(SNAP_FILE, snaps)
