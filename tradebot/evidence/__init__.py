from tradebot.evidence.detect_trend import detect_trend
from tradebot.evidence.detect_accumulation import detect_accumulation
from tradebot.evidence.detect_distribution import detect_distribution
from tradebot.evidence.detect_trap import detect_trap
from tradebot.evidence.detect_reversal import detect_reversal

def run_evidence(market_data: dict, indicator_result: dict = None) -> dict:
    data = {**(market_data or {}), **(indicator_result or {})}
    trend = detect_trend(data)
    accumulation = detect_accumulation(data)
    distribution = detect_distribution(data)
    reversal = detect_reversal(data)
    # 방향 후보 후 trap 재계산
    long_base = trend.get("long_score", 0) + accumulation.get("score", 0) + (reversal.get("long_score", 0) or 0)
    short_base = trend.get("short_score", 0) + distribution.get("score", 0) + (reversal.get("short_score", 0) or 0)
    direction = "LONG" if long_base > short_base + 5 else ("SHORT" if short_base > long_base + 5 else "NEUTRAL")
    trap = detect_trap(data, direction)
    return {"trend": trend, "accumulation": accumulation, "distribution": distribution, "reversal": reversal, "trap": trap, "direction_hint": direction, "long_evidence": long_base, "short_evidence": short_base}
