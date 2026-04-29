"""HOLD / EXIT 관리 전용. 신규 진입 판단과 REAL 판단을 하지 않는다."""
from __future__ import annotations
from tradebot.step.utils import num, text


def manage_position(step_result: dict, market_data: dict, current_position: dict | None = None) -> dict:
    result = dict(step_result or {})
    if not current_position:
        result.setdefault("hold_score", 0.0)
        result.setdefault("exit_score", 0.0)
        result.setdefault("exit_type", "NONE")
        return result

    direction = text(current_position, "direction", "side", default="").upper()
    price = num(market_data, "current_price", "price", "close")
    stop = num(current_position, "stop", "stop_loss", "sl", default=0.0)
    trend = text(market_data, "trend_15m", default="SIDEWAYS").upper()
    ema20 = num(market_data, "ema20")
    hold = 40.0
    exit_score = 0.0
    exit_type = "NONE"
    reasons = []

    if direction == "LONG":
        if ema20 and price > ema20: hold += 20; reasons.append("EMA20 상단 유지")
        if trend in ("UP", "SIDEWAYS"): hold += 20; reasons.append("구조 유지")
        if stop and price < stop: exit_score += 80; exit_type = "LOSS_EXIT"; reasons.append("손절선 이탈")
    elif direction == "SHORT":
        if ema20 and price < ema20: hold += 20; reasons.append("EMA20 하단 유지")
        if trend in ("DOWN", "SIDEWAYS"): hold += 20; reasons.append("구조 유지")
        if stop and price > stop: exit_score += 80; exit_type = "LOSS_EXIT"; reasons.append("손절선 이탈")

    if exit_score >= 75:
        result["step"] = "EXIT"
        result["final_state"] = "EXIT"
    elif hold >= 70:
        result["step"] = "HOLD"
        result["final_state"] = "HOLD"
    result["direction"] = direction or result.get("direction", "NEUTRAL")
    result["hold_score"] = min(hold, 100.0)
    result["exit_score"] = min(exit_score, 100.0)
    result["exit_type"] = exit_type
    result.setdefault("debug", {})["position_reasons"] = reasons
    return result
