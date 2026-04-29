"""실행 순서 전용. 판단 로직 없음."""
from __future__ import annotations
import time
import traceback
from datetime import datetime
from tradebot.config.settings import KST, SYMBOLS, LOOP_SLEEP_SEC, ENABLE_STEP_MESSAGE, STEP_COOLDOWN_SEC
from tradebot.data.get_market_data import get_market_data
from tradebot.evidence import run_evidence
from tradebot.step.build_step import build_step
from tradebot.notify.send_step_message import send_step_message

_last_sent = {}
_active_positions = {}

def now_kst():
    return datetime.now(KST)

def log(message: str):
    print(f"[{now_kst().strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

def _fingerprint(symbol: str, decision: dict) -> str:
    return "|".join([
        symbol,
        str(decision.get("final_state") or decision.get("step")),
        str(decision.get("direction")),
        str(int(float(decision.get("score", 0) or 0) // 5 * 5)),
        str(decision.get("quality_tier", "")),
        str(decision.get("step_detail", "")),
    ])

def _should_send(symbol: str, decision: dict) -> bool:
    fp = _fingerprint(symbol, decision)
    now = time.time()
    last = _last_sent.get(symbol)
    if last and last["fp"] == fp and now - last["ts"] < STEP_COOLDOWN_SEC:
        return False
    _last_sent[symbol] = {"fp": fp, "ts": now}
    return True

def _update_virtual_position(symbol: str, decision: dict):
    step = str(decision.get("final_state") or decision.get("step") or "").upper()
    direction = str(decision.get("direction") or "").upper()
    if step == "REAL" and direction in ("LONG", "SHORT"):
        _active_positions[symbol] = {
            "direction": direction,
            "entry": decision.get("current_price"),
            "stop": decision.get("stop") or decision.get("stop_loss"),
            "created_at": int(time.time()),
        }
    elif step == "EXIT":
        _active_positions.pop(symbol, None)

def run_symbol(symbol: str):
    market_data = get_market_data(symbol)
    indicators = {k: market_data.get(k) for k in ("rsi", "cci", "ema20", "ema50", "ema200", "macd_state", "macd_hist", "fibo_level", "divergence", "rsi_divergence", "cci_divergence")}
    evidence = run_evidence(market_data, indicators)
    decision = build_step(market_data, indicators, evidence, current_position=_active_positions.get(symbol))
    decision["symbol"] = symbol
    decision["current_price"] = market_data.get("current_price")
    decision["price"] = market_data.get("current_price")
    candles_1h = (market_data.get("candles_by_tf") or {}).get("1h") or []
    if ENABLE_STEP_MESSAGE and _should_send(symbol, decision):
        sent = send_step_message(decision, candles_1h)
        if sent:
            _update_virtual_position(symbol, decision)
        log(f"[STEP] {symbol} {decision.get('final_state')} {decision.get('direction')} score={decision.get('score')} sent={sent}")
    else:
        log(f"[STEP SKIP] {symbol} {decision.get('final_state')} {decision.get('direction')} score={decision.get('score')}")

def main_loop():
    log("tradebot_app started: STEP message only")
    while True:
        for symbol in SYMBOLS:
            try:
                run_symbol(symbol)
            except Exception as exc:
                log(f"[LOOP ERROR] {symbol}: {exc}")
                traceback.print_exc()
        time.sleep(LOOP_SLEEP_SEC)
