"""WAIT / EARLY / PRE 감지 전용.
REAL 조건은 여기서 절대 보지 않는다.
조건 부족은 WAIT이 아니라 EARLY/PRE + WARNING으로 남긴다.
"""
from __future__ import annotations
from tradebot.step.utils import num, text, vol_ratio, candle_ratios, clamp


def _indicator_score(data: dict, direction: str) -> tuple[float, list]:
    rsi = num(data, "rsi", default=50)
    cci = num(data, "cci", default=0)
    macd_state = text(data, "macd_state", default="NEUTRAL").upper()
    reasons = []
    score = 0.0
    if direction == "LONG":
        if 35 <= rsi <= 65: score += 10; reasons.append(f"RSI 우호({rsi:.1f})")
        if cci > -100: score += 8; reasons.append(f"CCI 회복({cci:.0f})")
        if macd_state in ("BULLISH", "POSITIVE"): score += 8; reasons.append("MACD 상방")
    elif direction == "SHORT":
        if 35 <= rsi <= 65: score += 10; reasons.append(f"RSI 우호({rsi:.1f})")
        if cci < 100: score += 8; reasons.append(f"CCI 둔화({cci:.0f})")
        if macd_state in ("BEARISH", "NEGATIVE"): score += 8; reasons.append("MACD 하방")
    return score, reasons


def detect_step(market_data: dict, evidence: dict) -> dict:
    data = market_data or {}
    evidence = evidence or {}
    trend = evidence.get("trend", {})
    acc = evidence.get("accumulation", {})
    dist = evidence.get("distribution", {})
    rev = evidence.get("reversal", {})
    trap = evidence.get("trap", {})

    long_score = float(trend.get("long_score", 0) or 0) + float(acc.get("score", 0) or 0) + float(rev.get("long_score", 0) or 0)
    short_score = float(trend.get("short_score", 0) or 0) + float(dist.get("score", 0) or 0) + float(rev.get("short_score", 0) or 0)

    il, il_reasons = _indicator_score(data, "LONG")
    is_, is_reasons = _indicator_score(data, "SHORT")
    long_score += il
    short_score += is_

    long_score = clamp(long_score)
    short_score = clamp(short_score)
    gap = abs(long_score - short_score)

    if long_score > short_score and gap >= 8:
        direction = "LONG"
        score = long_score
        reasons = (trend.get("reasons", []) + acc.get("reasons", []) + rev.get("reasons", []) + il_reasons)[:8]
    elif short_score > long_score and gap >= 8:
        direction = "SHORT"
        score = short_score
        reasons = (trend.get("reasons", []) + dist.get("reasons", []) + rev.get("reasons", []) + is_reasons)[:8]
    else:
        direction = "NEUTRAL"
        score = max(long_score, short_score) * 0.5
        reasons = ["방향 우위 부족"]

    warnings = []
    warnings.extend(trap.get("warnings", [])[:3])
    vr = vol_ratio(data)
    if 0 < vr < 1.0:
        warnings.append(f"거래량 부족({vr:.1f}x) — REAL 제한")

    # 핵심: WAIT은 방향 없음일 때만.
    if direction == "NEUTRAL":
        base_step = "WAIT"
    elif score >= 60 or gap >= 18:
        base_step = "PRE"
    else:
        base_step = "EARLY"

    # 최근 캔들 방향 전환 보정: 하락/상승이 명확하면 최소 EARLY 유지
    cr = candle_ratios(data)
    if base_step == "WAIT":
        if cr["close"] < cr["open"] and num(data, "current_price", "price") < num(data, "ema20", default=0):
            base_step, direction = "EARLY", "SHORT"
            reasons.append("EMA20 하단 + 음봉 전환")
        elif cr["close"] > cr["open"] and num(data, "current_price", "price") > num(data, "ema20", default=10**12):
            base_step, direction = "EARLY", "LONG"
            reasons.append("EMA20 상단 + 양봉 전환")

    return {
        "base_step": base_step,
        "direction": direction,
        "score": round(score, 1),
        "long_score": round(long_score, 1),
        "short_score": round(short_score, 1),
        "gap": round(gap, 1),
        "reasons": reasons,
        "warnings": warnings,
        "debug": {"trend": trend, "accumulation": acc, "distribution": dist, "reversal": rev, "trap": trap},
    }
