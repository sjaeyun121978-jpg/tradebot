# entry_timing.py v6
# 진입레이더 / PRE-ENTRY / REAL ENTRY
# v6: market_data → evaluate()에 전달, 하위 호환 함수 정리

from datetime import datetime, timezone, timedelta
from tradebot.analysis.core import analyze, pct_distance
from tradebot.analysis.signal import evaluate

# ── 신규 엔진 연결 (step_state_engine v1) ──────────────────────
# Deprecated:
# 기존 evaluate() 기반 PRE/REAL 판단은 보존하지만,
# 실제 STEP 판단은 decide_step_state() 결과를 사용한다.
try:
    from tradebot.analysis.engines.step_state_engine import decide_step_state as _decide_step_state
    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False
    _decide_step_state = None

KST = timezone(timedelta(hours=9))

_TREND_KO = {"UP": "상승", "DOWN": "하락", "SIDEWAYS": "횡보"}
_MACD_KO  = {
    "BULLISH": "강세↑", "BEARISH": "약세↓",
    "POSITIVE": "양전환", "NEGATIVE": "음전환", "NEUTRAL": "중립",
}
_DIV_KO = {
    "BULLISH_DIV": "상승 다이버전스",
    "BEARISH_DIV": "하락 다이버전스",
}


def _t(key, sig):
    return _TREND_KO.get(sig.get(key, "SIDEWAYS"), "횡보")


def _market_summary(sig) -> str:
    """진입레이더 메시지에 market_data 요약 한 줄 추가"""
    lines = []
    ob = sig.get("orderbook", {})
    if ob.get("usable"):
        lines.append(f"오더북:{ob.get('pressure','?')}/{ob.get('imbalance',1):.2f}")
    tr = sig.get("trades", {})
    if tr.get("usable"):
        lines.append(f"CVD:{tr.get('cvd_signal','?')}/{tr.get('buy_ratio',50):.0f}%")
    fr = sig.get("funding_rate", {})
    if fr.get("usable"):
        lines.append(f"펀딩:{fr.get('funding_rate',0):.4f}%")
    oi = sig.get("open_interest", {})
    if oi.get("usable"):
        lines.append(f"OI:{oi.get('oi_signal','?')}")
    return "   " + " · ".join(lines) if lines else ""


def make_radar_message(sig, reason=""):
    direction   = sig.get("direction", "WAIT")
    confidence  = sig.get("confidence", 0)
    long_score  = sig.get("long_score", 0)
    short_score = sig.get("short_score", 0)
    rsi_val     = sig.get("rsi", 50)
    cci_val     = sig.get("cci", 0)
    macd        = _MACD_KO.get(sig.get("macd_state", "NEUTRAL"), "중립")
    div         = _DIV_KO.get(sig.get("divergence"), "")
    div_line    = f"\n   {div}" if div else ""
    bb_sig      = sig.get("bb_signal", "NEUTRAL")
    bb_line     = f"\n   볼린저: {bb_sig}" if bb_sig != "NEUTRAL" else ""
    market_line = _market_summary(sig)
    market_txt  = f"\n{market_line}" if market_line else ""

    if direction == "SHORT":
        badge = "SHORT 지지"
        act_short = "박스 하단 이탈 확인 후"
        act_long  = "박스 상단 돌파 전 무시"
    elif direction == "LONG":
        badge = "LONG 지지"
        act_short = "박스 하단 이탈 전 무시"
        act_long  = "박스 상단 돌파 확인 후"
    else:
        badge = "방향 대기"
        act_short = "하단 이탈 확인"
        act_long  = "상단 돌파 확인"

    rsi_txt = "강세↑" if rsi_val >= 50 else "약세↓"
    cci_txt = "강세↑" if cci_val >= 0  else "약세↓"

    # 마켓 신호 / 경고 표시
    m_signals  = sig.get("market_signals",  [])
    m_warnings = sig.get("market_warnings", [])
    m_lines = ""
    if m_signals:
        m_lines += "\n📡 " + " / ".join(m_signals[:2])
    if m_warnings:
        m_lines += "\n⚠️ " + " / ".join(m_warnings[:2])

    return (
        f"🔍 {sig['symbol']} · 진입레이더 · 감시구간\n\n"
        f"⚡ {badge} | 조건 상태 {confidence}%\n"
        f"   LONG {long_score}% · SHORT {short_score}%\n\n"
        f"📊 {_t('trend_15m', sig)}(15M) · {_t('trend_1h', sig)}(1H) · {_t('trend_4h', sig)}(4H)\n"
        f"   RSI {rsi_val:.1f} {rsi_txt} · CCI {cci_val:.0f} {cci_txt} · MACD {macd}"
        f"{bb_line}{div_line}"
        f"{market_txt}"
        f"{m_lines}\n\n"
        f"⚠️ {reason if reason else '감시 중'}\n"
        f"▶ 숏: {act_short}\n"
        f"✗ 롱: {act_long}\n\n"
        f"⏳ 대기 중"
    )


def run_entry_radar(symbol: str, candles_by_tf: dict, market_data: dict = None,
                    current_position: dict = None) -> dict:
    """15분봉 마감마다 호출 — 레이더/PRE/REAL 판단"""

    sig         = analyze(symbol, candles_by_tf, market_data)
    candles_15m = candles_by_tf.get("15m", [])

    direction  = sig.get("direction",  "WAIT")
    confidence = sig.get("confidence", 0)
    score_gap  = sig.get("score_gap",  0)

    # ── 새 엔진 판단 (step_state_engine v1) ──────────────────
    # 기존 evaluate() 결과와 병행. 새 엔진 결과를 최종 STEP으로 사용.
    _new_decision = None
    if _ENGINE_AVAILABLE:
        try:
            # sig에 market_data 필드 병합 (safe — 기존 키 덮어쓰지 않음)
            merged = {**(market_data or {}), **sig}
            _new_decision = _decide_step_state(
                merged,
                current_position=current_position,
            )
        except Exception as _e:
            print(f"[STEP ENGINE] {symbol} 엔진 오류 fallback: {_e}", flush=True)
            _new_decision = None

    # ── 기존 evaluate() — Deprecated 상태로 보존 ──────────────
    # evaluate에 market_data 전달 (v6 핵심)
    evaluation = evaluate(sig, candles_15m, market_data)
    etype = evaluation["type"]

    # ── 최종 STEP 판단: 새 엔진 결과 우선 ───────────────────
    if _new_decision:
        new_state = _new_decision["final_state"]
        new_dir   = _new_decision["direction"]
        # NEUTRAL 방향이면 기존 direction 유지
        if new_dir == "NEUTRAL":
            new_dir = direction

        # 새 엔진 결과를 sig에 병합 (카드 렌더러에 전달)
        sig["_step_decision"]   = _new_decision
        sig["step_score"]       = _new_decision["score"]
        sig["step_long_score"]  = _new_decision["long_score"]
        sig["step_short_score"] = _new_decision["short_score"]
        sig["step_gap"]         = _new_decision["gap"]
        sig["step_warning"]     = _new_decision["warning"]
        sig["step_warning_reasons"] = _new_decision["warning_reasons"]
        sig["step_hold_score"]  = _new_decision["hold_score"]
        sig["step_exit_score"]  = _new_decision["exit_score"]
        sig["step_exit_type"]   = _new_decision["exit_type"]
        sig["step_action_text"] = _new_decision["action_text"]
        sig["step_main_reasons"]= _new_decision["main_reasons"]

        if new_state == "REAL":
            # REAL — 기존 levels 재사용 (있으면), 없으면 sig 그대로
            levels = evaluation.get("levels") or None
            return _result("REAL_ENTRY", {**sig, "direction": new_dir},
                           evaluation.get("message") or _make_engine_message(symbol, _new_decision, "REAL"),
                           "REAL ENTRY — 엔진 판단",
                           levels=levels)

        if new_state == "PRE":
            return _result("PRE_ENTRY", {**sig, "direction": new_dir},
                           evaluation.get("message") or _make_engine_message(symbol, _new_decision, "PRE"),
                           "PRE-ENTRY — 엔진 판단")

        if new_state == "EARLY":
            return _result("EARLY", {**sig, "direction": new_dir},
                           _make_engine_message(symbol, _new_decision, "EARLY"),
                           "EARLY — 엔진 판단")

        if new_state in ("HOLD", "EXIT"):
            # ── [수정 8] HOLD/EXIT는 보유 포지션 방향을 우선 사용 ──
            final_dir = new_dir
            if current_position:
                pos_dir = str(current_position.get("direction") or "").upper()
                if pos_dir in ("LONG", "SHORT"):
                    final_dir = pos_dir
            return _result(new_state, {**sig, "direction": final_dir},
                           _make_engine_message(symbol, _new_decision, new_state),
                           f"{new_state} — 엔진 판단")

        # WAIT — 기존 레이더 메시지 사용
        reason = "박스권 중앙" if (sig.get("is_range") and sig.get("range_pos") == "MIDDLE") else "방향 후보 감지"
        if _new_decision["warning_reasons"]:
            reason = _new_decision["warning_reasons"][0]
        return _result("WAIT", sig, make_radar_message(sig, reason), reason)

    # ── 엔진 없을 때 기존 로직 fallback ─────────────────────
    if direction == "WAIT" or confidence < 60 or score_gap < 12:
        return _result("WAIT", sig,
            f"⏸ {symbol} WAIT\n조건 상태 {confidence}% / 갭 {score_gap}%p", "방향 미확정")

    if etype == "REAL":
        return _result("REAL_ENTRY", sig,
            evaluation["message"], "REAL ENTRY 조건 충족",
            levels=evaluation["levels"])

    if etype == "PRE":
        return _result("PRE_ENTRY", sig,
            evaluation["message"], "PRE-ENTRY 조건 충족")

    reason = "박스권 중앙" if (sig.get("is_range") and sig.get("range_pos") == "MIDDLE") else "방향 후보 감지"
    fail_reasons = evaluation.get("reasons", [])
    if fail_reasons:
        reason += f" (PRE 미달: {', '.join(fail_reasons[:2])})"
    return _result("ENTRY_RADAR", sig, make_radar_message(sig, reason), reason)


def _make_engine_message(symbol: str, d: dict, step: str) -> str:
    """새 엔진 결과 기반 간단한 상태 메시지 (기존 UI 변경 없이 텍스트만)"""
    lines = [
        f"[{step}] {symbol}  {d['direction']}",
        f"점수 {d['score']:.0f}  LONG {d['long_score']:.0f}  SHORT {d['short_score']:.0f}  GAP {d['gap']:.0f}",
    ]
    if d.get("main_reasons"):
        lines.append("✔ " + " / ".join(d["main_reasons"][:3]))
    if d.get("warning") and d.get("warning_reasons"):
        lines.append("⚠ " + " / ".join(d["warning_reasons"][:2]))
    if d.get("action_text"):
        lines.append(d["action_text"])
    return "\n".join(lines)


def _result(rtype, sig, message, reason, levels=None):
    return {
        "type":       rtype,
        "alert_type": rtype,
        "direction":  sig.get("direction", "WAIT"),
        "message":    message,
        "reason":     reason,
        "levels":     levels,
        **sig,
    }


# ── 하위 호환 (필요한 것만 유지) ────────────────────────────────
def analyze_entry_timing(symbol, candles_by_tf, structure_result=None, market_data=None,
                         current_position=None):
    return run_entry_radar(symbol, candles_by_tf, market_data, current_position)

def run_entry_timing(symbol, candles_by_tf, structure_result=None, market_data=None,
                     current_position=None):
    return run_entry_radar(symbol, candles_by_tf, market_data, current_position)
