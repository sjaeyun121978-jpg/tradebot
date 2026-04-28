"""
jobs.py v8
스케줄러 — 언제 실행할지만 담당

핵심 변경 (v8):
  [2] 레이더 무음 없음 — 시장상태 나빠도 카드 전송, 방향만 WAIT
  [3] entry_filter 상태 변경 방식 — blocked여도 카드 전송
  [6] decision 통합 객체 — 모든 엔진 결과를 하나로 합침
  [7] 메시지 구조 통일 — 카드타입/시장상태/판정/금지사유/무효화 조건 표시
"""

import time
import traceback
from datetime import datetime
from collections import defaultdict

from tradebot.config.settings import (
    KST, SYMBOLS, LOOP_SLEEP_SEC, PRICE_SKIP_THRESHOLD,
    SAME_ALERT_COOLDOWN_SEC, MAX_LOOP_ERROR_COUNT,
    ENABLE_SHEETS, ENABLE_ENTRY_RADAR, ENABLE_HOURLY_DASHBOARD,
    ENABLE_DAILY_BRIEFING, ENABLE_PRE_REAL, ENABLE_INFO_ANALYSIS,
    ENABLE_AUTO_TRADE, ENTRY_ANALYSIS_INTERVAL_SEC, INFO_ANALYSIS_INTERVAL_SEC,
    ENABLE_MARKET_STATE, ENABLE_ENTRY_FILTER, ENABLE_SCENARIO,
    ENABLE_TRADE_JOURNAL, ENABLE_JOURNAL_UPDATE, JOURNAL_UPDATE_INTERVAL_SEC,
    ENABLE_JOURNAL,
)
from tradebot.data.bybit_client import collect_candles, get_current_price, collect_market_data
from tradebot.analysis import entry as entry_timing
from tradebot.analysis import structure as structure_analyzer
from tradebot.analysis import briefing as daily_weekly_briefing
from tradebot.analysis.market_state import classify_market, is_tradable
from tradebot.analysis.entry_filter import check_entry, should_block_entry
from tradebot.analysis.risk_engine import calculate_risk, format_risk_message
from tradebot.analysis.scenario_engine import build_scenarios, format_scenario_message
from tradebot.analysis.reversal_engine import analyze_reversal
from tradebot.journal.step_logger     import save_step_log, save_market_snapshot
from tradebot.analysis.backtest_engine import try_review_pending
from tradebot.analysis.report_engine   import build_report_text, save_report_json
from tradebot.analysis.tuning_engine   import build_tuning_text, save_tuning_report
from tradebot.journal.trade_journal import (
    record_signal as journal_record,
    update_pending_results,
    format_stats_message,
)
from tradebot.ai import claude_analyzers
from tradebot.render import chart_renderer
from tradebot.messages.hourly_payload import build_hourly_dashboard_payload, build_hourly_caption
from tradebot.messages.radar_payload import normalize_radar_signal
from tradebot.delivery import telegram
from tradebot.delivery import sheets
from tradebot.journal import signal_journal

# ── 상태 캐시 ────────────────────────────────────
price_cache                     = {}
last_entry_run                  = defaultdict(float)
last_info_run                   = defaultdict(float)
last_alert_sent                 = {}
last_hourly_dashboard_sent      = {}
last_daily_weekly_briefing_date = {}
last_radar_15m_slot             = None
last_journal_update             = 0.0
last_daily_journal_report_key   = None
last_advisor_report_key         = None
last_step_report_slot           = None

ENABLE_STEP_REPORT              = True
STEP_REPORT_INTERVAL_MIN        = 60
STEP_REPORT_LOOKBACK_HOURS      = 24

ENABLE_TUNING_REPORT            = True
TUNING_REPORT_HOUR              = 23
TUNING_REPORT_MINUTE            = 50
TUNING_REPORT_LOOKBACK_HOURS    = 72
last_tuning_report_key          = None
loop_error_count                = 0
_latest_signals                 = {}   # BTC/ETH 동시 과잉 신호 제어
_step_signal_state_store        = {}   # WAIT/PRE/REAL 이벤트 중복 발송 방지
last_step_closed_15m            = {}   # 15분봉 마감 슬롯 기반 중복 방지


# ── 기본 유틸 ─────────────────────────────────────

def now_kst():
    return datetime.now(KST)

def log(msg):
    print(f"[{now_kst().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def now_ts():
    return time.time()

def safe_call(func, *args, default=None, name="unknown", **kwargs):
    try:
        if func is None:
            return default
        return func(*args, **kwargs)
    except TypeError:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log(f"[ERROR] {name}: {e}")
            traceback.print_exc()
            return default
    except Exception as e:
        log(f"[ERROR] {name}: {e}")
        traceback.print_exc()
        return default

def should_run_interval(cache, key, interval_sec):
    current = now_ts()
    if current - cache.get(key, 0) >= interval_sec:
        cache[key] = current
        return True
    return False

def should_run_entry(symbol):
    return should_run_interval(last_entry_run, symbol, ENTRY_ANALYSIS_INTERVAL_SEC)

def should_run_info(symbol):
    return should_run_interval(last_info_run, symbol, INFO_ANALYSIS_INTERVAL_SEC)

def should_skip_by_price_change(symbol, price):
    if price is None:
        return True
    prev = price_cache.get(symbol)
    price_cache[symbol] = {"price": price, "ts": now_ts()}
    if not prev or prev["price"] <= 0:
        return False
    return abs(price - prev["price"]) / prev["price"] < PRICE_SKIP_THRESHOLD

def current_15m_slot(now=None):
    now = now or now_kst()
    slot_minute = (now.minute // 15) * 15
    return now.replace(minute=slot_minute, second=0, microsecond=0)

def is_new_15m_candle():
    """봇 시작 직후 오동작 방지 — 15분 경계일 때만 True"""
    global last_radar_15m_slot
    now = now_kst()
    if now.minute % 15 != 0:
        return False
    slot = current_15m_slot(now)
    if slot != last_radar_15m_slot:
        last_radar_15m_slot = slot
        return True
    return False

def make_alert_key(symbol, alert_type, direction=None):
    return f"{symbol}:{alert_type}:{direction or 'NONE'}"

def should_send_alert(symbol, alert_type, direction=None, cooldown_sec=SAME_ALERT_COOLDOWN_SEC):
    key     = make_alert_key(symbol, alert_type, direction)
    current = now_ts()
    if current - last_alert_sent.get(key, 0) < cooldown_sec:
        return False
    last_alert_sent[key] = current
    return True

def send_alert_safely(symbol, alert_type, message, direction=None, force=False):
    if not message:
        return False
    if not force and not should_send_alert(symbol, alert_type, direction):
        log(f"[SKIP ALERT] {symbol} {alert_type} {direction} cooldown")
        return False
    return telegram.send_message(message)

def record_to_sheet(symbol, event_type, payload):
    if not ENABLE_SHEETS:
        return
    row = [now_kst().strftime('%Y-%m-%d %H:%M:%S'), symbol, event_type, str(payload)]
    safe_call(sheets.save_to_sheets, "신호기록", row, default=None, name="sheets.save_to_sheets")

def record_to_journal(symbol, event_type, payload):
    if not ENABLE_SHEETS:
        return
    msg       = extract_message(payload) or ""
    direction = extract_direction(payload) or "INFO"
    price     = extract_number(payload, ["price", "current_price", "entry_price"])
    score     = extract_number(payload, ["score", "confidence", "confidence_score"])
    stop_loss = extract_number(payload, ["stop_loss", "sl", "stop"])
    tp1       = extract_number(payload, ["tp1", "target1", "take_profit_1"])
    tp2       = extract_number(payload, ["tp2", "target2", "take_profit_2"])
    safe_call(
        signal_journal.record_signal,
        symbol=symbol, signal=event_type, level=direction,
        price=price, score=score, stop_loss=stop_loss,
        tp1=tp1, tp2=tp2, detail=str(payload), raw_message=msg,
        default=None, name="signal_journal.record_signal",
    )

def record_to_trade_journal(symbol, signal_type, direction, sig, risk, market_state):
    # 레거시 경로 (ENABLE_TRADE_JOURNAL)
    if ENABLE_TRADE_JOURNAL:
        try:
            journal_record(
                symbol=symbol, signal_type=signal_type, direction=direction,
                price=float(sig.get("current_price", 0)),
                stop=float(risk.get("stop", 0)) if risk and risk.get("valid") else 0,
                tp1=float(risk.get("tp1", 0))   if risk and risk.get("valid") else 0,
                tp2=float(risk.get("tp2", 0))   if risk and risk.get("valid") else 0,
                confidence=float(sig.get("confidence", 0)),
                score_gap=float(sig.get("score_gap", 0)),
                market_state=market_state.get("state", "UNKNOWN") if market_state else "UNKNOWN",
                rr=float(risk.get("rr", 0)) if risk and risk.get("valid") else 0,
                reason=str(sig.get("reason", "")),
            )
        except Exception as e:
            log(f"[JOURNAL] 레거시 기록 실패: {e}")


# ── 추출 유틸 ─────────────────────────────────────

def extract_message(result):
    if result is None:
        return None
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ["message", "text", "telegram_message", "alert", "summary"]:
            if result.get(key):
                return str(result[key])
    return str(result)

def extract_number(result, keys):
    if not isinstance(result, dict):
        return None
    for key in keys:
        val = result.get(key)
        if val is None or val == "":
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            return val
    return None

def extract_direction(result):
    if result is None:
        return None
    if isinstance(result, dict):
        for key in ["direction", "side", "entry_side", "signal"]:
            val = result.get(key)
            if val:
                val = str(val).upper()
                if "LONG"  in val: return "LONG"
                if "SHORT" in val: return "SHORT"
                if "WAIT"  in val: return "WAIT"
                if "INFO"  in val: return "INFO"
    text = str(result).upper()
    if "LONG"  in text or "롱" in text:  return "LONG"
    if "SHORT" in text or "숏" in text:  return "SHORT"
    if "WAIT"  in text or "대기" in text: return "WAIT"
    return None

def extract_alert_type(result, default_type):
    if isinstance(result, dict):
        for key in ["type", "alert_type", "entry_type", "signal_type"]:
            if result.get(key):
                return str(result[key]).upper()
    text = str(result).upper()
    if "REAL ENTRY" in text:                        return "REAL_ENTRY"
    if "PRE-ENTRY" in text or "PRE ENTRY" in text:  return "PRE_ENTRY"
    if "RADAR" in text or "레이더" in text:          return "ENTRY_RADAR"
    if "DAILY" in text or "일봉" in text:            return "DAILY_BRIEFING"
    if "WEEKLY" in text or "주간" in text:           return "WEEKLY_PROGRESS_BRIEFING"
    if "WAIT" in text or "박스권" in text:           return "WAIT"
    return default_type


# ── [6] decision 통합 객체 생성 ────────────────────

def build_decision(
    symbol:       str,
    sig:          dict,
    market_state: dict,
    entry_check:  dict,
    risk:         dict,
    scenario:     dict,
    signal_type:  str,
) -> dict:
    """
    모든 엔진 결과를 하나의 decision 객체로 통합

    {
        "symbol":        str,
        "mode":          "REAL_ENTRY/PRE_ENTRY/ENTRY_RADAR/WAIT",
        "trade_allowed": bool,
        "block_reason":  str,
        "market_state":  str,
        "direction":     str,
        "scenario":      dict,
        "risk":          dict,
        "confidence":    float,
        "score_gap":     float,
        "long_score":    float,
        "short_score":   float,
    }
    """
    ms_state    = market_state.get("state", "UNKNOWN") if market_state else "UNKNOWN"
    ms_tradable = market_state.get("tradable", False)   if market_state else False
    ms_reason   = market_state.get("reason", "")        if market_state else ""

    ef_allowed  = entry_check.get("trade_allowed", True)  if entry_check else True
    ef_reason   = entry_check.get("block_reason", "")     if entry_check else ""
    ef_dir      = entry_check.get("direction", sig.get("direction", "WAIT"))

    rr_allowed  = risk.get("trade_allowed", True) if risk and risk.get("valid") else True
    rr_reason   = risk.get("reason", "")          if risk else ""

    # market_state는 CHAOS / NO_DATA만 hard block — 거래량 부족은 차단 아님
    hard_block_states = {"CHAOS", "NO_DATA"}
    hard_block = ms_state in hard_block_states

    # 최종 trade_allowed: hard_block + 진입필터 + RR
    trade_allowed = (not hard_block) and ef_allowed and rr_allowed

    # 금지 사유 우선순위
    if hard_block:
        block_reason = ms_reason or f"시장상태 {ms_state}"
    elif not ef_allowed:
        block_reason = ef_reason
    elif not rr_allowed:
        block_reason = rr_reason
    else:
        block_reason = ""

    # 후보 방향 보존 — trade_allowed=False여도 WAIT 덮어쓰기 금지
    candidate_direction = (
        entry_check.get("candidate_direction")
        or entry_check.get("direction")
        or sig.get("direction", "WAIT")
    ) if entry_check else sig.get("direction", "WAIT")

    direction = candidate_direction

    return {
        "symbol":               symbol,
        "mode":                 signal_type,
        "trade_allowed":        trade_allowed,
        "block_reason":         block_reason,
        "market_state":         ms_state,
        "market_reason":        ms_reason,
        "direction":            direction,
        "candidate_direction":  candidate_direction,
        "warnings":             entry_check.get("warnings", []) if entry_check else [],
        "scenario":             scenario or {},
        "risk":                 risk or {},
        "confidence":           float(sig.get("confidence", 0)),
        "score_gap":            float(sig.get("score_gap",  0)),
        "long_score":           float(sig.get("long_score",  0)),
        "short_score":          float(sig.get("short_score", 0)),
        "current_price":        float(sig.get("current_price", 0)),
    }


# ── [7] 통일된 메시지 포맷 ──────────────────────────

_STATE_EMOJI = {
    "TREND_UP":         "📈",
    "TREND_DOWN":       "📉",
    "RANGE":            "📦",
    "SQUEEZE":          "🔧",
    "CHAOS":            "⚡",
    "NO_DATA":          "🚫",
    "LOW_VOLUME":       "📉",
    "LOW_VOLUME_TREND": "📊",
    "UNKNOWN":          "❓",
}
_STATE_KO = {
    "TREND_UP":         "상승 추세장",
    "TREND_DOWN":       "하락 추세장",
    "RANGE":            "박스장",
    "SQUEEZE":          "변동성 수축",
    "CHAOS":            "급변동",
    "NO_DATA":          "데이터 부족",
    "LOW_VOLUME":       "거래량 부족",
    "LOW_VOLUME_TREND": "저거래량 추세 유지",
    "UNKNOWN":          "미확인",
}


def format_decision_message(decision: dict, base_message: str = "") -> str:
    """
    [7] 통일된 메시지 구조
    모든 카드에 표시:
      카드 타입 / 시장상태 / 최종판정 / 진입가능여부 / 금지사유 / 유효조건 / 무효화조건
    """
    symbol        = decision.get("symbol", "?")
    mode          = decision.get("mode",   "ENTRY_RADAR")
    trade_allowed = decision.get("trade_allowed", False)
    block_reason  = decision.get("block_reason",  "")
    ms_state      = decision.get("market_state",  "UNKNOWN")
    ms_reason     = decision.get("market_reason", "")
    direction     = decision.get("direction",     "WAIT")
    price         = decision.get("current_price", 0)
    long_score    = decision.get("long_score",    0)
    short_score   = decision.get("short_score",   0)
    confidence    = decision.get("confidence",    0)
    risk          = decision.get("risk",          {})
    scenario      = decision.get("scenario",      {})

    # 카드 타입 표시
    type_map = {
        "REAL_ENTRY":   "🔥 REAL ENTRY",
        "PRE_ENTRY":    "⚡ PRE-ENTRY",
        "ENTRY_RADAR":  "🔍 진입레이더",
        "WAIT":         "⏸ WAIT",
    }
    card_type = type_map.get(mode, f"📊 {mode}")

    # 시장상태 표시
    ms_emoji = _STATE_EMOJI.get(ms_state, "❓")
    ms_ko    = _STATE_KO.get(ms_state, ms_state)

    # 최종 판정
    if trade_allowed:
        verdict_line = f"✅ 진입 가능 — {direction}"
    else:
        verdict_line = f"⛔ 진입 금지 — {block_reason or '조건 미충족'}"

    # 방향 점수
    score_line = f"LONG {long_score:.0f}% · SHORT {short_score:.0f}% · 신뢰도 {confidence:.0f}%"

    # 리스크 정보
    risk_section = ""
    if risk and risk.get("valid") and trade_allowed:
        risk_section = (
            f"\n\n💰 진입가: {risk.get('entry', 0):,.2f}\n"
            f"🛑 손절:   {risk.get('stop', 0):,.2f}  (-{risk.get('stop_pct', 0):.1f}%)\n"
            f"🎯 1차:    {risk.get('tp1', 0):,.2f}  (+{risk.get('tp1_pct', 0):.1f}%)\n"
            f"🎯 2차:    {risk.get('tp2', 0):,.2f}\n"
            f"📐 손익비: 1:{risk.get('rr', 0):.1f}"
        )
    elif risk and not risk.get("trade_allowed", True):
        risk_section = f"\n\n⚠️ {risk.get('reason', '손익비 미달')}"

    # 시나리오 정보
    scenario_section = ""
    if scenario and (trade_allowed or ms_state in ("RANGE", "SQUEEZE")):
        trigger_long  = scenario.get("trigger_long",  "")
        trigger_short = scenario.get("trigger_short", "")
        wait_cond     = scenario.get("wait",          "")
        invalid_cond  = scenario.get("invalid",       "")
        scenario_section = (
            f"\n\n📋 시나리오\n"
            f"🟢 롱 트리거: {trigger_long}\n"
            f"🔴 숏 트리거: {trigger_short}"
        )
        if not trade_allowed and wait_cond:
            scenario_section += f"\n⏳ 대기: {wait_cond}"
        if invalid_cond:
            scenario_section += f"\n❌ 무효화: {invalid_cond}"

    # 무효화 조건 (거래 가능 시)
    invalidate_section = ""
    if trade_allowed and risk and risk.get("invalidate"):
        invalidate_section = f"\n\n❌ 무효화: {risk.get('invalidate')}"

    # 기본 메시지 (분석 내용)
    base_section = f"\n\n{base_message}" if base_message else ""

    msg = (
        f"{card_type}\n"
        f"{'─'*28}\n"
        f"심볼: {symbol}  |  현재가: {price:,.2f}\n"
        f"{ms_emoji} 시장: {ms_ko}\n"
        f"{'─'*28}\n"
        f"{verdict_line}\n"
        f"{score_line}"
        f"{base_section}"
        f"{risk_section}"
        f"{scenario_section}"
        f"{invalidate_section}\n\n"
        f"※ 자동진입 아님 / 15분봉 마감 기준"
    )
    return msg


# ── 핵심 분석 함수 ────────────────────────────────

def run_structure_analysis(symbol, candles_by_tf, market_data=None):
    return safe_call(
        structure_analyzer.analyze_structure,
        symbol, candles_by_tf, market_data,
        default=None, name="structure_analyzer.analyze_structure"
    )

def run_entry_timing(symbol, candles_by_tf, structure_result=None, market_data=None):
    try:
        return entry_timing.analyze_entry_timing(symbol, candles_by_tf, structure_result, market_data)
    except TypeError:
        return safe_call(
            entry_timing.analyze_entry_timing, symbol, candles_by_tf, structure_result,
            default=None, name="entry_timing.analyze_entry_timing"
        )
    except Exception as e:
        log(f"[ERROR] entry_timing: {e}")
        traceback.print_exc()
        return None

def run_market_state(symbol, candles_by_tf):
    if not ENABLE_MARKET_STATE:
        return {"state": "TREND_UP", "tradable": True, "trend_aligned": True,
                "reason": "시장상태 엔진 비활성", "details": {}}
    try:
        return classify_market(candles_by_tf)
    except Exception as e:
        log(f"[ERROR] market_state {symbol}: {e}")
        return {"state": "NO_DATA", "tradable": False, "trend_aligned": False,
                "reason": f"분류 오류: {e}", "details": {}}

def build_radar_album_caption(signals: list) -> str:
    symbols = []
    for sig in signals or []:
        sym = str(sig.get("symbol") or "").strip()
        if sym and sym not in symbols:
            symbols.append(sym)
    symbol_text = ", ".join(symbols) if symbols else "BTCUSDT, ETHUSDT"
    return (
        "📡 <b>진입레이더</b>\n"
        f"대상: {symbol_text}\n"
        "기준: 15분봉 마감 / 자동진입 아님"
    )


# ── WAIT/PRE/REAL 이벤트 발송 유틸 ─────────────────────────

def get_last_step_state(symbol):
    return _step_signal_state_store.get(symbol, {})


def _extract_step_type(alert_type, decision):
    text = str(alert_type or decision.get("mode", "")).upper()

    if "REAL" in text:
        return "REAL"
    if "PRE" in text:
        return "PRE"

    # 방향 없음 → 진짜 WAIT
    if decision.get("direction", "WAIT") == "WAIT":
        return "WAIT"

    # 방향 있음 + 진입 금지 → WAIT 카드 (방향 후보 표시)
    if not decision.get("trade_allowed", True):
        if (
            decision.get("block_reason")
            or decision.get("warnings")
            or decision.get("long_score", 0) >= 50
            or decision.get("short_score", 0) >= 50
        ):
            return "WAIT"

    # 방향 있음 + warnings만 있음 → WAIT 카드 (WATCH 상태)
    if decision.get("warnings"):
        return "WAIT"

    return None


def get_closed_15m_slot(candles_by_tf: dict):
    """
    최신 15분봉 직전 봉(마감 봉)의 open_time 반환.
    Bybit kline은 진행 중 봉이 포함되므로 [-2]를 기준으로 한다.
    """
    candles = candles_by_tf.get("15m") or []
    if len(candles) < 2:
        return None
    closed = candles[-2]
    if isinstance(closed, dict):
        return closed.get("open_time") or closed.get("close_time")
    elif isinstance(closed, (list, tuple)) and len(closed) > 0:
        return closed[0]
    return None


def should_process_step_on_closed_15m(symbol: str, candles_by_tf: dict) -> bool:
    """
    WAIT / EARLY / PRE / REAL 이벤트는 동일 15분봉에서 1회만 판단.
    """
    slot = get_closed_15m_slot(candles_by_tf)
    if not slot:
        return False
    prev = last_step_closed_15m.get(symbol)
    if prev == slot:
        log(f"[STEP 15M] {symbol} 동일 봉 슬롯 ({slot}) — 스킵")
        return False
    last_step_closed_15m[symbol] = slot
    return True


import hashlib

_last_wait_hash = {}   # symbol → hash (메모리 캐시, 재시작 시 초기화)


def make_wait_state_hash(symbol: str, decision: dict) -> str:
    """WAIT 상태 핵심 필드 hash — 동일 상태 반복 발송 방지용"""
    payload = {
        "symbol":           symbol,
        "step":             "WAIT",
        "direction":        decision.get("direction"),
        "candidate_dir":    decision.get("candidate_direction"),
        "reason":           (decision.get("block_reason") or "")[:40],
        "market_state":     decision.get("market_state"),
        "confidence_band":  int((float(decision.get("confidence") or 0)) / 10) * 10,
        "reversal_stage":   decision.get("reversal_stage"),
    }
    import json
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def should_send_wait_by_hash(symbol: str, decision: dict) -> bool:
    """WAIT 상태 변화 없으면 False 반환 — 스팸 방지"""
    current_hash = make_wait_state_hash(symbol, decision)
    prev_hash    = _last_wait_hash.get(symbol)
    if current_hash != prev_hash:
        _last_wait_hash[symbol] = current_hash
        return True
    log(f"[WAIT SKIP] {symbol} 상태 변화 없음")
    return False


def _step_fingerprint(step_type, decision):
    """
    같은 WAIT이라도 WATCH/EARLY 후보, reversal_stage 변화 시 새 이벤트로 처리.
    reversal_score는 5점 단위로 버킷팅해 민감도 조절.
    """
    return "|".join([
        str(step_type),
        str(decision.get("direction", "WAIT")),
        str(decision.get("candidate_direction", "")),
        str(decision.get("market_state", "UNKNOWN")),
        str(decision.get("reversal_stage", "NONE")),
        str(decision.get("reversal_direction", "NONE")),
        str(int(float(decision.get("reversal_score", 0)) // 5 * 5)),
        str(decision.get("block_reason", ""))[:40],
    ])


# WAIT은 상태 변화 없으면 절대 재발송 금지 (스팸 방지)
WAIT_REPEAT_COOLDOWN_SEC = 3600   # WAIT 동일 상태 재발송: 1시간

def should_send_step_event(symbol, step_type, decision, cooldown_sec=SAME_ALERT_COOLDOWN_SEC):
    if not step_type:
        return False

    current = now_ts()
    prev    = get_last_step_state(symbol)
    fp      = _step_fingerprint(step_type, decision)

    # 상태(fingerprint) 바뀌면 발송 후보
    if prev.get("fingerprint") != fp:
        # WAIT은 추가로 hash 비교 (더 세밀한 스팸 방지)
        if step_type == "WAIT" and not should_send_wait_by_hash(symbol, decision):
            return False
        _step_signal_state_store[symbol] = {"fingerprint": fp, "ts": current}
        return True

    # 동일 상태 반복:
    # WAIT/WATCH는 1시간 쿨다운 (스팸 방지)
    # PRE/REAL/EARLY는 기본 쿨다운 적용
    if step_type in ("WAIT",):
        effective_cooldown = max(cooldown_sec, WAIT_REPEAT_COOLDOWN_SEC)
    else:
        effective_cooldown = cooldown_sec

    if current - prev.get("ts", 0) >= effective_cooldown:
        _step_signal_state_store[symbol] = {"fingerprint": fp, "ts": current}
        return True

    log(f"[SKIP STEP] {symbol} {step_type} unchanged/cooldown ({effective_cooldown}s)")
    return False


def build_step_card_payload(symbol, result, decision):
    sig = normalize_radar_signal(symbol, result if isinstance(result, dict) else {})
    risk = decision.get("risk") or {}
    scenario = decision.get("scenario") or {}

    sig.update({
        "symbol":              symbol,
        "direction":           decision.get("direction", "WAIT"),
        "candidate_direction": decision.get("candidate_direction", decision.get("direction", "WAIT")),
        "current_price":       decision.get("current_price", sig.get("current_price", 0)),
        "trade_allowed":       decision.get("trade_allowed"),
        "block_reason":        decision.get("block_reason"),
        "warnings":            decision.get("warnings", []),
        "market_state":        decision.get("market_state"),
        "confidence":          decision.get("confidence", sig.get("confidence", 0)),
        "long_score":          decision.get("long_score", sig.get("long_score", 0)),
        "short_score":         decision.get("short_score", sig.get("short_score", 0)),
        "entry":               risk.get("entry") or sig.get("entry"),
        "stop":                risk.get("stop") or sig.get("stop"),
        "tp1":                 risk.get("tp1") or sig.get("tp1"),
        "tp2":                 risk.get("tp2") or sig.get("tp2"),
        "invalid":             risk.get("invalidate") or scenario.get("invalid"),
        "conditions": (
            result.get("conditions") if isinstance(result, dict) else None
        ) or (
            result.get("hits") if isinstance(result, dict) else None
        ),
        # 변곡점 엔진 결과
        "reversal_direction":   decision.get("reversal_direction"),
        "reversal_stage":       decision.get("reversal_stage"),
        "reversal_score":       decision.get("reversal_score"),
        "reversal_gap":         decision.get("reversal_gap"),
        "reversal_long_score":  decision.get("reversal_long_score"),
        "reversal_short_score": decision.get("reversal_short_score"),
        "reversal_reasons":     decision.get("reversal_reasons", []),
        "reversal_warnings":    decision.get("reversal_warnings", []),
        "reversal_invalid":     decision.get("reversal_invalid"),
        "reversal_block":       decision.get("reversal_block", False),
        "reversal_promoted":    decision.get("reversal_promoted", False),
    })

    return sig


def send_step_card_event(symbol, step_type, result, decision, candles_by_tf, market_data=None):
    candles_1h = candles_by_tf.get("1h", []) or candles_by_tf.get("15m", [])
    payload = build_step_card_payload(symbol, result, decision)
    result_dict = result if isinstance(result, dict) else {}

    # ── 필수 데이터 검증: symbol 없으면 렌더 금지
    # candles_1h 없어도 ensure_chart_data fallback이 처리하므로 차단하지 않음
    if not symbol:
        log(f"[STEP CARD SKIP] symbol 없음")
        return False

    # ── 렌더링: render_step_card 단일 진입점 (WAIT/PRE/REAL/EARLY 통합)
    try:
        risk     = decision.get("risk")     or {}
        scenario = decision.get("scenario") or {}
        levels   = result_dict.get("levels") or {}

        # entry / stop / tp / box 레벨 완전 병합
        payload.update({
            "entry":      payload.get("entry")      or risk.get("entry")      or levels.get("entry"),
            "stop":       payload.get("stop")       or risk.get("stop")       or risk.get("stop_loss")  or levels.get("stop")  or levels.get("stop_loss"),
            "stop_loss":  payload.get("stop_loss")  or risk.get("stop")       or risk.get("stop_loss")  or levels.get("stop")  or levels.get("stop_loss"),
            "tp1":        payload.get("tp1")        or risk.get("tp1")        or levels.get("tp1"),
            "tp2":        payload.get("tp2")        or risk.get("tp2")        or levels.get("tp2"),
            "support":    payload.get("support")    or levels.get("support")  or levels.get("range_low")  or scenario.get("support"),
            "resistance": payload.get("resistance") or levels.get("resistance") or levels.get("range_high") or scenario.get("resistance"),
            "range_low":  payload.get("range_low")  or levels.get("range_low")  or levels.get("support"),
            "range_high": payload.get("range_high") or levels.get("range_high") or levels.get("resistance"),
        })

        hits = result_dict.get("hits") or result_dict.get("conditions")
        if hits:
            payload["conditions"] = hits

        img = chart_renderer.render_step_card(step_type, payload, candles_1h)
    except Exception as _re:
        log(f"[STEP CARD RENDER ERROR] {symbol} {step_type}: {_re}")
        return False

    # ── 렌더 실패(None/빈 bytes) → 전송 차단
    if not img:
        log(f"[STEP CARD SKIP] {symbol} {step_type} 렌더 결과 없음")
        return False

    # caption=None 강제 — 하단 정보는 이미지 내부에 포함
    log(f"[STEP CARD SEND] {symbol} {step_type} img={len(img)}B")
    ok = telegram.send_photo(img, caption=None, parse_mode=None)

    if ok:
        log(f"[STEP CARD] {symbol} {step_type} 전송 완료")
        try:
            save_step_log(symbol, step_type, decision, candles_by_tf, result)
            save_market_snapshot(symbol, candles_by_tf, market_data or {})
        except Exception as _le:
            log(f"[STEP LOG] 저장 오류: {_le}")

    return ok


def build_claude_indicator_payload(candles_by_tf, structure_result=None):
    payload    = {"structure": structure_result or {}}
    latest_15m = (candles_by_tf.get("15m") or [])[-1:]
    if latest_15m:
        payload["price"] = latest_15m[0].get("close")
    return payload

def run_general_analyzers(symbol, candles_by_tf, structure_result=None):
    results = []
    payload = build_claude_indicator_payload(candles_by_tf, structure_result)
    price   = payload.get("price")
    adapters = [
        ("analyze_fact",      lambda f: f(symbol, price, payload)),
        ("analyze_mungkkul",  lambda f: f(symbol, candles_by_tf, structure_result)),
        ("run_all_analyzers", lambda f: f(symbol, candles_by_tf, structure_result)),
        ("analyze",           lambda f: f(symbol, candles_by_tf, structure_result)),
    ]
    for fname, caller in adapters:
        func = getattr(claude_analyzers, fname, None)
        if func is None:
            continue
        result = safe_call(caller, func, default=None, name=f"claude_analyzers.{fname}")
        if not result:
            continue
        if isinstance(result, list):
            results.extend([x for x in result if x])
        else:
            results.append(result)
    return results


# ── 블록별 실행 함수 ──────────────────────────────

def run_hourly_dashboard_if_needed(symbol, candles_by_tf, structure_result=None, market_data=None):
    if not ENABLE_HOURLY_DASHBOARD:
        return
    current  = now_kst()
    if current.minute > 4:
        return
    hour_key  = current.strftime("%Y-%m-%d %H")
    cache_key = f"{symbol}:{hour_key}"
    if last_hourly_dashboard_sent.get(cache_key):
        return
    log(f"[HOURLY DASHBOARD] {symbol} {hour_key}")
    if structure_result is None:
        structure_result = run_structure_analysis(symbol, candles_by_tf, market_data)
    if not structure_result:
        log(f"[WARN] {symbol} HOURLY_DASHBOARD 결과 없음")
        last_hourly_dashboard_sent[cache_key] = True
        return
    try:
        payload = build_hourly_dashboard_payload(symbol, structure_result)
        caption = build_hourly_caption(symbol, payload)
        png     = chart_renderer.render_dashboard_card(payload, candles_by_tf.get("1h", []))
        if telegram.send_photo(png, caption=caption):
            log(f"[DASHBOARD] {symbol} 이미지 전송 완료")
            record_to_sheet(symbol, "HOURLY_DASHBOARD", structure_result)
            record_to_journal(symbol, "HOURLY_DASHBOARD", structure_result)
            last_hourly_dashboard_sent[cache_key] = True
            return
    except Exception as e:
        log(f"[DASHBOARD] 이미지 실패 → 텍스트 fallback: {e}")
        traceback.print_exc()
    msg = extract_message(structure_result)
    if msg:
        send_alert_safely(symbol, "HOURLY_DASHBOARD", msg, extract_direction(structure_result), force=True)
        record_to_sheet(symbol, "HOURLY_DASHBOARD", structure_result)
        record_to_journal(symbol, "HOURLY_DASHBOARD", structure_result)
    last_hourly_dashboard_sent[cache_key] = True

def run_daily_weekly_briefings_if_needed(symbol, candles_by_tf):
    if not ENABLE_DAILY_BRIEFING:
        return
    current = now_kst()
    if current.hour != 9 or current.minute > 9:
        return
    today_key = current.strftime("%Y-%m-%d")
    cache_key = f"{symbol}:{today_key}"
    if last_daily_weekly_briefing_date.get(cache_key):
        return
    log(f"[DAILY/WEEKLY BRIEFING] {symbol} {today_key}")
    results = safe_call(daily_weekly_briefing.run_all_briefings, symbol, candles_by_tf,
                        default=[], name="briefing.run_all_briefings")
    for result in (results or []):
        msg        = extract_message(result)
        alert_type = extract_alert_type(result, "BRIEFING")
        if msg:
            send_alert_safely(symbol, alert_type, msg, "INFO", force=True)
            record_to_sheet(symbol, alert_type, result)
            record_to_journal(symbol, alert_type, result)
    last_daily_weekly_briefing_date[cache_key] = True


def run_entry_radar_on_15m_close(all_candles: dict, all_market: dict = None):
    """
    15분봉 마감 정기 브리핑 전용.
    WAIT/PRE/REAL STEP 카드는 여기서 절대 만들지 않는다.
    """
    if not ENABLE_ENTRY_RADAR:
        return

    signals    = []
    candles_map = {}

    for symbol in SYMBOLS:
        candles_by_tf = all_candles.get(symbol)
        if not candles_by_tf:
            continue

        try:
            result = entry_timing.run_entry_radar(
                symbol, candles_by_tf, (all_market or {}).get(symbol, {})
            )
        except Exception as e:
            log(f"[ERROR] radar {symbol}: {e}")
            traceback.print_exc()
            continue

        if not result:
            log(f"[WARN] {symbol} radar 결과 없음")
            continue

        sig_norm = normalize_radar_signal(symbol, result)

        # 정기 진입레이더는 현재 상황판만 담당.
        # STEP 상태(WAIT/PRE/REAL), event 발송, journal signal 기록은 여기서 처리하지 않는다.
        sig_norm.pop("state", None)
        sig_norm.pop("step",  None)
        sig_norm.pop("card_type", None)

        signals.append(sig_norm)
        candles_map[symbol] = candles_by_tf

    if not signals:
        log("[RADAR] 전송할 신호 없음")
        return

    # 이미지 앨범 전송: 반드시 진입레이더 카드만 사용
    try:
        images = []
        for sig in signals:
            sym     = sig.get("symbol", "")
            candles = candles_map.get(sym, {}).get("15m", [])
            images.append(chart_renderer.render_radar_card(sig, candles))

        if telegram.send_album(images, caption=build_radar_album_caption(signals)):
            log(f"[RADAR] 정기 브리핑 앨범 전송 완료 ({len(images)}장)")
            for sig in signals:
                record_to_sheet(sig.get("symbol", ""), "ENTRY_RADAR", sig)
            return
    except Exception as e:
        log(f"[RADAR] 이미지 생성 실패: {e}")
        traceback.print_exc()

    # fallback: 진입레이더 텍스트만 보낸다 (STEP 메시지 아님)
    for sig in signals:
        sym = sig.get("symbol", "")
        telegram.send_message(
            f"\U0001f4e1 진입레이더\n심볼: {sym}\n기준: 15분봉 마감 / 자동진입 아님"
        )


def run_entry_timing_if_needed(symbol, candles_by_tf, structure_result=None,
                                market_data=None, market_state=None):
    """
    WAIT/PRE/REAL 이벤트 전용.
    상태 변화 또는 쿨다운 만료 시 STEP 카드 이미지만 발송한다.
    """
    if not ENABLE_PRE_REAL:
        return

    # 15분봉 마감 기준으로만 STEP 판단 (동일 봉에서 중복 실행 방지)
    if not should_process_step_on_closed_15m(symbol, candles_by_tf):
        return

    # should_run_entry는 15분봉 마감 판단과 중복되므로 STEP에서는 사용하지 않음
    # if not should_run_entry(symbol):
    #     return

    ms = market_state or {}

    entry_result = run_entry_timing(symbol, candles_by_tf, structure_result, market_data)
    if not entry_result:
        log(f"[WARN] {symbol} entry_result 없음")
        return

    results = entry_result if isinstance(entry_result, list) else [entry_result]
    for result in results:
        sig_data   = result if isinstance(result, dict) else {}
        direction  = extract_direction(result) or "WAIT"
        alert_type = extract_alert_type(result, "ENTRY")

        # [3] entry_filter 상태 변경
        if ENABLE_ENTRY_FILTER:
            entry_check = check_entry(symbol, direction, sig_data, ms, _latest_signals)
        else:
            entry_check = {"trade_allowed": True, "blocked": False,
                           "block_reasons": [], "block_reason": "", "direction": direction}

        # 리스크 계산
        c15  = candles_by_tf.get("15m", [])
        c1h  = candles_by_tf.get("1h",  [])
        risk = calculate_risk(sig_data, c15, entry_check.get("direction", direction), c1h)

        # 시나리오
        scenario = {}
        if ENABLE_SCENARIO:
            try:
                scenario = build_scenarios(sig_data, risk, candles_by_tf, ms)
            except Exception as e:
                log(f"[SCENARIO] {symbol}: {e}")

        # [6] decision 통합
        decision = build_decision(symbol, sig_data, ms, entry_check, risk, scenario, alert_type)

        # ── 변곡점 엔진 실행 및 decision 병합 ──────────────
        try:
            reversal = analyze_reversal(sig_data, market_data or {})
        except Exception as _re:
            log(f"[REVERSAL] {symbol} 오류: {_re}")
            reversal = {
                "reversal_direction": "NONE", "reversal_stage": "NONE",
                "reversal_score": 0, "reversal_gap": 0,
                "reversal_long_score": 0, "reversal_short_score": 0,
                "reversal_reasons": [], "reversal_warnings": [],
                "reversal_invalid": "", "reversal_block": False,
            }
        decision.update(reversal)

        # step_type 판별
        step_type = _extract_step_type(alert_type, decision)

        # ENTRY_RADAR 등 alert_type이 매칭 안 돼도
        # reversal_stage가 WATCH/EARLY/PRE/REAL이면 카드 발송
        if not step_type:
            _rv_st  = decision.get("reversal_stage",    "NONE")
            _rv_dir = decision.get("reversal_direction", "NONE")
            if _rv_st in ("WATCH", "EARLY", "PRE", "REAL") and _rv_dir in ("LONG", "SHORT"):
                step_type = _rv_st
                decision["step_type"]         = _rv_st
                decision["candidate_direction"] = _rv_dir
                decision["direction"]           = _rv_dir
                log(f"[REVERSAL] {symbol} ENTRY_RADAR → {_rv_st} 카드 생성 ({_rv_dir})")

        if not step_type:
            continue

        # ── 변곡점 신호를 단계 판정에 반영 (5단계) ──────────
        rev_dir   = decision.get("reversal_direction", "NONE")
        rev_stage = decision.get("reversal_stage", "NONE")
        rev_block = decision.get("reversal_block", False)
        rev_score = decision.get("reversal_score", 0)

        # 0) 기존 방향 WAIT + 변곡 방향 확보 → 후보 방향 승격
        if decision.get("direction") == "WAIT" and rev_dir in ("LONG", "SHORT"):
            decision["direction"]           = rev_dir
            decision["candidate_direction"] = rev_dir
            log(f"[REVERSAL] {symbol} WAIT → {rev_dir} 방향 승격")

        # 공통: hard block 여부
        hard_block_states = {"CHAOS", "NO_DATA"}
        ms_state_now  = decision.get("market_state") or decision.get("state") or ""
        is_hard_block = ms_state_now in hard_block_states

        if not is_hard_block and not rev_block:
            # 1) WATCH 이상 감지 → WAIT를 WATCH로 상향
            if step_type == "WAIT" and rev_stage in ("WATCH", "EARLY", "PRE", "REAL")                     and rev_dir in ("LONG", "SHORT"):
                decision["candidate_direction"] = rev_dir
                step_type = "WAIT"   # 카드는 WAIT으로 유지 (WATCH 표시)
                log(f"[REVERSAL] {symbol} WATCH 감지 — 방향 후보: {rev_dir}")

            # 2) EARLY 승격 — 변곡 초입 진입 구간
            if rev_stage == "EARLY" and rev_dir in ("LONG", "SHORT"):
                step_type = "EARLY"
                decision["step_type"]           = "EARLY"
                decision["reversal_promoted"]   = True
                decision["trade_allowed"]       = True   # 거래량 부족 무시
                decision["early_entry"]         = True
                decision["direction"]           = rev_dir
                decision["candidate_direction"] = rev_dir
                decision.setdefault("warnings", []).append("EARLY 진입 — 저거래량 허용")
                log(f"[REVERSAL] {symbol} → EARLY 승격 ({rev_score}점, {rev_dir})")

            # 3) PRE 승격
            elif rev_stage == "PRE" and step_type in ("WAIT", "EARLY"):
                step_type = "PRE"
                decision["step_type"]         = "PRE"
                decision["reversal_promoted"] = True
                log(f"[REVERSAL] {symbol} → PRE 승격 ({rev_score}점)")

            # 4) REAL 승격
            elif rev_stage == "REAL" and step_type in ("WAIT", "EARLY", "PRE"):
                step_type = "REAL"
                decision["step_type"]         = "REAL"
                decision["reversal_promoted"] = True
                log(f"[REVERSAL] {symbol} → REAL 승격 ({rev_score}점)")

        # 5) 변곡 방향 충돌 → PRE/REAL/EARLY 차단
        cur_dir = decision.get("direction", "WAIT")
        if (rev_dir in ("LONG", "SHORT") and cur_dir in ("LONG", "SHORT")
                and rev_dir != cur_dir and rev_score >= 65):
            decision["trade_allowed"] = False
            decision.setdefault("warnings", []).append("변곡점 방향과 기존 방향 충돌")
            if step_type in ("PRE", "REAL", "EARLY"):
                step_type = "WAIT"
                decision["step_type"] = "WAIT"
                log(f"[REVERSAL] {symbol} 방향 충돌 — step_type WAIT 강등")

        # journal 기록 (WAIT/BLOCKED 포함)
        if ENABLE_JOURNAL:
            try:
                from tradebot.journal.storage import record_signal as _rec
                _rec(decision)
            except Exception as _je:
                log(f"[JOURNAL] record 실패: {_je}")

        # 상태 변화 없으면 스킵
        if not should_send_step_event(symbol, step_type, decision):
            continue

        # STEP 카드 이미지 발송 (텍스트 send_alert_safely 사용 금지)
        if not send_step_card_event(symbol, step_type, result, decision, candles_by_tf, market_data):
            log(f"[STEP CARD] {symbol} {step_type} 전송 실패")
            continue

        record_to_sheet(symbol, alert_type, result)
        record_to_journal(symbol, alert_type, result)

        if decision.get("trade_allowed"):
            _latest_signals[symbol] = sig_data
            record_to_trade_journal(
                symbol,
                alert_type,
                decision.get("direction", "WAIT"),
                sig_data,
                risk,
                ms,
            )


def run_info_analyzers_if_needed(symbol, candles_by_tf, structure_result=None, market_data=None):
    if not ENABLE_INFO_ANALYSIS:
        return
    if not should_run_info(symbol):
        return
    for result in run_general_analyzers(symbol, candles_by_tf, structure_result):
        msg        = extract_message(result)
        direction  = extract_direction(result)
        alert_type = extract_alert_type(result, "INFO_ANALYSIS")
        if msg:
            send_alert_safely(symbol, alert_type, msg, direction, force=False)
            record_to_sheet(symbol, alert_type, result)
            record_to_journal(symbol, alert_type, result)


def run_symbol_cycle(symbol, candles_by_tf, market_data=None):
    log(f"[START] {symbol} cycle")

    ms = run_market_state(symbol, candles_by_tf)
    log(f"[MARKET STATE] {symbol}: {ms.get('state')} — {ms.get('reason', '')}")

    structure_result = None
    if ENABLE_HOURLY_DASHBOARD or ENABLE_PRE_REAL or ENABLE_INFO_ANALYSIS:
        structure_result = run_structure_analysis(symbol, candles_by_tf, market_data)

    run_hourly_dashboard_if_needed(symbol, candles_by_tf, structure_result, market_data)
    run_daily_weekly_briefings_if_needed(symbol, candles_by_tf)

    price = get_current_price(symbol)
    should_skip_by_price_change(symbol, price)  # 기록만, 차단 없음

    # PRE / REAL / EARLY 판단은 가격 변화율 필터로 차단하지 않는다.
    # 가격 변화가 작아도 HL/CVD/MACD/OB 변화로 변곡 초입 신호가 나올 수 있음
    run_entry_timing_if_needed(symbol, candles_by_tf, structure_result, market_data, ms)

    run_info_analyzers_if_needed(symbol, candles_by_tf, structure_result, market_data)

    # 지연 복기: STEP 발생 후 충분한 봉(5개)이 쌓인 항목만 복기
    try:
        reviewed_n = try_review_pending(symbol, candles_by_tf.get("15m") or [])
        if reviewed_n:
            log(f"[BACKTEST] {symbol} {reviewed_n}건 지연 복기 완료")
    except Exception as _be:
        log(f"[BACKTEST] 복기 오류: {_be}")

    log(f"[END] {symbol} cycle")


def run_strategy_advisor_if_needed():
    """KST 기준 하루 1회 전략 어드바이저 리포트 전송"""
    global last_advisor_report_key
    from tradebot.config import settings
    if not getattr(settings, 'ENABLE_STRATEGY_ADVISOR', False):
        return
    if not getattr(settings, 'ENABLE_JOURNAL', False):
        return
    now = now_kst()
    if now.hour != getattr(settings, 'ADVISOR_REPORT_HOUR', 23):
        return
    if abs(now.minute - getattr(settings, 'ADVISOR_REPORT_MINUTE', 55)) > 2:
        return
    key = now.strftime('%Y-%m-%d')
    if last_advisor_report_key == key:
        return
    try:
        from tradebot.journal.advisor import run_advisor
        result = run_advisor()
        if getattr(settings, 'ADVISOR_TELEGRAM', True):
            from tradebot.journal.report_sender import send_text
            send_text(result.get('text', ''))
        last_advisor_report_key = key
        log('[ADVISOR] 전략 리포트 전송 완료')
    except Exception as e:
        log(f'[ADVISOR ERROR] {e}')


def should_send_step_report() -> bool:
    """STEP 복기 리포트는 STEP_REPORT_INTERVAL_MIN마다 1회만 발송한다."""
    global last_step_report_slot
    if not ENABLE_STEP_REPORT:
        return False
    now = now_kst()
    minute_slot = (now.minute // STEP_REPORT_INTERVAL_MIN) * STEP_REPORT_INTERVAL_MIN
    slot = now.strftime("%Y-%m-%d %H") + f":{minute_slot:02d}"
    if last_step_report_slot == slot:
        return False
    last_step_report_slot = slot
    return True


def run_step_report_if_needed():
    """최근 STEP_REPORT_LOOKBACK_HOURS 복기 결과를 요약해 텔레그램으로 발송한다."""
    try:
        if not should_send_step_report():
            return
        save_report_json(symbol=None, hours=STEP_REPORT_LOOKBACK_HOURS)
        text = build_report_text(symbol=None, hours=STEP_REPORT_LOOKBACK_HOURS)
        if telegram.send_message(text):
            log("[STEP_REPORT] 리포트 발송 완료")
        else:
            log("[STEP_REPORT] 리포트 발송 실패")
    except Exception as e:
        log(f"[STEP_REPORT] 리포트 생성/발송 오류: {e}")


def run_tuning_report_if_needed():
    """
    2~3일 누적 STEP 복기 데이터를 기반으로 튜닝 추천 리포트를 하루 1회 발송한다.
    조건 자동 변경은 하지 않는다.
    """
    global last_tuning_report_key

    if not ENABLE_TUNING_REPORT:
        return

    now = now_kst()
    if now.hour != TUNING_REPORT_HOUR:
        return
    if abs(now.minute - TUNING_REPORT_MINUTE) > 2:
        return

    key = now.strftime("%Y-%m-%d")
    if last_tuning_report_key == key:
        return

    try:
        save_tuning_report(hours=TUNING_REPORT_LOOKBACK_HOURS)
        text = build_tuning_text(hours=TUNING_REPORT_LOOKBACK_HOURS)

        if telegram.send_message(text):
            last_tuning_report_key = key
            log("[TUNING_REPORT] 튜닝 리포트 발송 완료")
        else:
            log("[TUNING_REPORT] 튜닝 리포트 발송 실패")
    except Exception as e:
        log(f"[TUNING_REPORT] 생성/발송 오류: {e}")


def run_daily_journal_report_if_needed():
    """KST 기준 하루 1회 복기 리포트 자동 전송"""
    global last_daily_journal_report_key
    from tradebot.config import settings
    if not getattr(settings, 'ENABLE_JOURNAL', False):
        return
    now = now_kst()
    try:
        from tradebot.journal.report_sender import should_send_daily_report, send_daily_journal_report
        if should_send_daily_report(now, last_daily_journal_report_key):
            send_daily_journal_report()
            last_daily_journal_report_key = now.strftime('%Y-%m-%d')
            log('[JOURNAL REPORT] 일일 리포트 전송 완료')
    except Exception as e:
        log(f'[JOURNAL REPORT ERROR] {e}')


def run_journal_update_if_needed(all_candles=None):
    global last_journal_update
    if not ENABLE_JOURNAL_UPDATE and not ENABLE_JOURNAL:
        return
    if now_ts() - last_journal_update < JOURNAL_UPDATE_INTERVAL_SEC:
        return
    last_journal_update = now_ts()
    # 레거시 업데이트
    if ENABLE_JOURNAL_UPDATE:
        try:
            update_pending_results(get_current_price)
            log("[JOURNAL] 레거시 결과 업데이트 완료")
        except Exception as e:
            log(f"[JOURNAL] 레거시 업데이트 실패: {e}")
    # 신규 journal 업데이트
    if ENABLE_JOURNAL:
        try:
            from tradebot.journal.tracker import update_open_signals
            from tradebot.journal.report import save_summary_csv
            cnt = update_open_signals(
                candles_by_symbol=all_candles,
                price_fetcher=get_current_price,
            )
            save_summary_csv()
            log(f"[JOURNAL] open signal {cnt}건 업데이트 / summary 저장")
        except Exception as e:
            log(f"[JOURNAL] 신규 업데이트 실패: {e}")


def send_startup_message():
    stats_msg = ""
    try:
        stats_msg = "\n\n" + format_stats_message()
    except Exception:
        pass
    msg = (
        "✅ TradeBot v8 시작\n\n"
        f"심볼: {', '.join(SYMBOLS)}\n\n"
        "수익형 엔진:\n"
        f"- 시장상태:   {'ON' if ENABLE_MARKET_STATE else 'OFF'}\n"
        f"- 진입금지:   {'ON' if ENABLE_ENTRY_FILTER else 'OFF'}\n"
        f"- 시나리오:   {'ON' if ENABLE_SCENARIO else 'OFF'}\n"
        f"- 복기시스템(레거시): {'ON' if ENABLE_TRADE_JOURNAL else 'OFF'}\n"
        f"- 복기시스템(v9):    {'ON' if ENABLE_JOURNAL else 'OFF'}\n"
        f"- Google Sheets:     {'ON' if getattr(__import__('tradebot.config.settings', fromlist=['settings']), 'ENABLE_GOOGLE_SHEETS', False) else 'OFF'}\n"
        f"- 일일 리포트:       {'ON' if getattr(__import__('tradebot.config.settings', fromlist=['settings']), 'ENABLE_DAILY_JOURNAL_REPORT', False) else 'OFF'}\n\n"
        "레이더: 시장상태 나빠도 카드 전송 (방향만 WAIT)\n"
        f"진입레이더={ENABLE_ENTRY_RADAR} / PRE+REAL={ENABLE_PRE_REAL}"
        + stats_msg
    )
    telegram.send_message(msg)


def main_loop():
    global loop_error_count
    send_startup_message()
    log("[BOT STARTED]")
    while True:
        try:
            all_candles = {}
            all_market  = {}
            for symbol in SYMBOLS:
                all_candles[symbol] = collect_candles(symbol)
                all_market[symbol]  = collect_market_data(symbol)

            if is_new_15m_candle():
                log("[15M CLOSE] 진입레이더 실행")
                run_entry_radar_on_15m_close(all_candles, all_market)

            for symbol in SYMBOLS:
                run_symbol_cycle(symbol, all_candles[symbol], all_market.get(symbol, {}))

            run_daily_journal_report_if_needed()
            run_strategy_advisor_if_needed()
            run_journal_update_if_needed(all_candles=all_candles)
            run_step_report_if_needed()
            run_tuning_report_if_needed()
            loop_error_count = 0
            time.sleep(LOOP_SLEEP_SEC)

        except KeyboardInterrupt:
            log("[STOP] KeyboardInterrupt")
            break
        except Exception as e:
            loop_error_count += 1
            log(f"[MAIN LOOP ERROR] count={loop_error_count}, error={e}")
            traceback.print_exc()
            if loop_error_count >= MAX_LOOP_ERROR_COUNT:
                telegram.send_message(
                    "🚨 TradeBot 오류 누적\n\n"
                    f"오류 횟수: {loop_error_count}\n"
                    f"에러: {e}\n\n120초 대기 후 재시도"
                )
                time.sleep(120)
                loop_error_count = 0
            else:
                time.sleep(10)
