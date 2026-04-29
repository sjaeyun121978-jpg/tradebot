"""REAL / REAL_1 / REAL_2 승인 전용.
PRE 상태에서만 REAL을 승인한다. 실패 시 WAIT/EARLY가 아니라 PRE로 유지한다.
"""
from __future__ import annotations
from tradebot.step.utils import vol_ratio, clamp

_REAL_TRAP_MAX = 35
_REAL_DIR_SCORE_MIN = 60
_REAL_WARNING_MAX = 2
_REAL_VOL_MIN = 1.1
_REAL_STRONG_GAP = 25
_REAL2_TRAP_MAX = 30
_REAL2_DIR_SCORE_MIN = 70
_REAL2_WARNING_MAX = 1


def decide_real(step_result: dict, market_data: dict, evidence: dict) -> dict:
    result = dict(step_result or {})
    if result.get("base_step") != "PRE":
        result["step"] = result.get("base_step", "WAIT")
        result["step_detail"] = f"{result['step']}_1" if result["step"] in ("EARLY", "PRE") else "WAIT_LOW"
        result["quality_tier"] = "LOW"
        result.setdefault("penalty_reasons", [])
        return result

    direction = result.get("direction", "NEUTRAL")
    gap = float(result.get("gap", 0) or 0)
    score = float(result.get("score", 0) or 0)
    evidence = evidence or {}
    acc = float((evidence.get("accumulation") or {}).get("score", 0) or 0)
    dist = float((evidence.get("distribution") or {}).get("score", 0) or 0)
    trap = float((evidence.get("trap") or {}).get("score", 0) or 0)
    warnings = list(result.get("warnings") or [])
    vr = vol_ratio(market_data or {})
    dir_score = acc if direction == "LONG" else dist if direction == "SHORT" else 0.0

    penalties = []
    if score < 75:
        penalties.append("REAL 차단: STEP 점수 부족")
    if trap >= _REAL_TRAP_MAX:
        penalties.append("REAL 차단: Trap Risk 높음")
    if len(warnings) > _REAL_WARNING_MAX:
        penalties.append("REAL 차단: WARNING 과다")
    if direction == "LONG" and acc < _REAL_DIR_SCORE_MIN:
        penalties.append("REAL 차단: 매집 점수 부족")
    if direction == "SHORT" and dist < _REAL_DIR_SCORE_MIN:
        penalties.append("REAL 차단: 분산 점수 부족")
    if vr < _REAL_VOL_MIN:
        penalties.append("REAL 차단: 거래량 부족")
    if gap < _REAL_STRONG_GAP:
        penalties.append("REAL 차단: GAP 부족")

    if penalties:
        result["step"] = "PRE"
        result["step_detail"] = "PRE_2" if score >= 68 else "PRE_1"
        result["score"] = min(score, 74.0)
        result["penalty_reasons"] = penalties
        result["quality_tier"] = "MID" if trap < 45 else "LOW"
        return result

    real2 = (
        trap < _REAL2_TRAP_MAX and dir_score >= _REAL2_DIR_SCORE_MIN and
        gap >= _REAL_STRONG_GAP and len(warnings) <= _REAL2_WARNING_MAX and vr >= _REAL_VOL_MIN
    )
    result["step"] = "REAL"
    result["step_detail"] = "REAL_2" if real2 else "REAL_1"
    result["score"] = clamp(score, 75, 100)
    result["penalty_reasons"] = []
    result["quality_tier"] = "HIGH" if real2 else "MID"
    return result
