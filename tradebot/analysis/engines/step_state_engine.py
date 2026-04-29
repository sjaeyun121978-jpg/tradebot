"""Deprecated compatibility wrapper.
새 STEP 판단은 tradebot.step.build_step.build_step을 사용한다.
"""
from tradebot.evidence import run_evidence
from tradebot.step.build_step import build_step

def decide_step_state(market_data: dict, current_position: dict = None, previous_decision: dict = None) -> dict:
    evidence = run_evidence(market_data or {}, market_data or {})
    return build_step(market_data or {}, market_data or {}, evidence, current_position, previous_decision)
