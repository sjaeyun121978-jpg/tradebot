"""STEP 조합 전용. 직접 판단하지 않고 detect_step, decide_real, manage_position 결과만 조합한다."""
from __future__ import annotations
from tradebot.step.detect_step import detect_step
from tradebot.step.decide_real import decide_real
from tradebot.step.manage_position import manage_position


def _action_text(step: str, direction: str, warning: bool, exit_type: str = "NONE") -> str:
    if step == "EXIT": return f"{direction} EXIT({exit_type}) — 포지션 정리 검토"
    if step == "HOLD": return f"{direction} HOLD — 포지션 유지"
    if step == "REAL": return f"{direction} REAL — 고확률 진입 후보 / 자동진입 아님"
    if step == "PRE": return f"{direction} PRE — 진입 후보, 조건 확인"
    if step == "EARLY": return f"{direction} EARLY — 초기 방향 감지"
    return "WAIT — 방향성 없음"


def build_step(market_data: dict, indicator_result: dict = None, evidence_result: dict = None, current_position: dict | None = None, previous_decision: dict | None = None) -> dict:
    data = {**(market_data or {}), **(indicator_result or {})}
    detected = detect_step(data, evidence_result or {})
    decided = decide_real(detected, data, evidence_result or {})
    managed = manage_position(decided, data, current_position)
    step = managed.get("step") or managed.get("base_step") or "WAIT"
    final_state = managed.get("final_state") or step
    warning_reasons = list(managed.get("warnings") or [])
    direction = managed.get("direction", "NEUTRAL")
    evidence_result = evidence_result or {}
    managed.update({
        "final_state": final_state,
        "step": step,
        "direction": direction,
        "warning": bool(warning_reasons),
        "warning_reasons": warning_reasons,
        "main_reasons": managed.get("reasons", [])[:5],
        "action_text": _action_text(final_state, direction, bool(warning_reasons), managed.get("exit_type", "NONE")),
        "accumulation_score": (evidence_result.get("accumulation") or {}).get("score", 0),
        "distribution_score": (evidence_result.get("distribution") or {}).get("score", 0),
        "trap_risk_score": (evidence_result.get("trap") or {}).get("score", 0),
        "quality_reasons": [],
        "debug": {**managed.get("debug", {}), "evidence": evidence_result},
    })
    return managed
