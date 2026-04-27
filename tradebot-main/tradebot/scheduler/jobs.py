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
loop_error_count                = 0
_latest_signals                 = {}   # BTC/ETH 동시 과잉 신호 제어


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

    # 최종 trade_allowed: 시장상태 + 진입필터 + RR 모두 통과해야
    trade_allowed = ms_tradable and ef_allowed and rr_allowed

    # 금지 사유 우선순위
    if not ms_tradable:
        block_reason = ms_reason or f"시장상태 {ms_state}"
    elif not ef_allowed:
        block_reason = ef_reason
    elif not rr_allowed:
        block_reason = rr_reason
    else:
        block_reason = ""

    direction = "WAIT" if not trade_allowed else ef_dir

    return {
        "symbol":        symbol,
        "mode":          signal_type,
        "trade_allowed": trade_allowed,
        "block_reason":  block_reason,
        "market_state":  ms_state,
        "market_reason": ms_reason,
        "direction":     direction,
        "scenario":      scenario or {},
        "risk":          risk or {},
        "confidence":    float(sig.get("confidence", 0)),
        "score_gap":     float(sig.get("score_gap",  0)),
        "long_score":    float(sig.get("long_score",  0)),
        "short_score":   float(sig.get("short_score", 0)),
        "current_price": float(sig.get("current_price", 0)),
    }


# ── [7] 통일된 메시지 포맷 ──────────────────────────

_STATE_EMOJI = {
    "TREND_UP":   "📈",
    "TREND_DOWN": "📉",
    "RANGE":      "📦",
    "SQUEEZE":    "🔧",
    "CHAOS":      "⚡",
    "WEAK":       "😴",
    "UNKNOWN":    "❓",
}
_STATE_KO = {
    "TREND_UP":   "상승 추세장",
    "TREND_DOWN": "하락 추세장",
    "RANGE":      "박스장",
    "SQUEEZE":    "변동성 수축",
    "CHAOS":      "급변동",
    "WEAK":       "거래량 부족",
    "UNKNOWN":    "미확인",
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
        return {"state": "WEAK", "tradable": False, "trend_aligned": False,
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
    [2] 레이더는 절대 무음 없음
    시장상태 나빠도 카드 전송 — 방향만 WAIT/진입금지로 표시
    """
    if not ENABLE_ENTRY_RADAR:
        return

    signals      = []
    candles_map  = {}
    decisions    = []

    for symbol in SYMBOLS:
        candles_by_tf = all_candles.get(symbol)
        if not candles_by_tf:
            continue

        # 시장상태 분류
        ms = run_market_state(symbol, candles_by_tf)
        log(f"[MARKET STATE] {symbol}: {ms.get('state')} — {ms.get('reason', '')}")

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

        sig_data  = result if isinstance(result, dict) else {}
        direction = extract_direction(result) or "WAIT"
        alert_type = extract_alert_type(result, "ENTRY_RADAR")

        # [3] entry_filter: skip 대신 상태 변경
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

        # [7] 통일 메시지
        base_msg = extract_message(result) or ""
        full_msg = format_decision_message(decision, base_msg)

        # 신규 journal 기록 (WAIT/BLOCKED 포함 모든 신호)
        if ENABLE_JOURNAL:
            try:
                from tradebot.journal.storage import record_signal as _rec
                _rec(decision)
            except Exception as _je:
                log(f"[JOURNAL] record 실패: {_je}")

        # 쿨다운 체크 — trade_allowed든 아니든 동일하게 적용
        final_dir = decision.get("direction", "WAIT")
        if not should_send_alert(symbol, alert_type, final_dir, cooldown_sec=SAME_ALERT_COOLDOWN_SEC):
            log(f"[SKIP ALERT] {symbol} {alert_type} cooldown")
            continue

        if decision.get("trade_allowed"):
            _latest_signals[symbol] = sig_data

        sig_norm = normalize_radar_signal(symbol, result)
        # decision 정보를 카드 렌더링용 payload에 병합
        sig_norm.update({
            "trade_allowed": decision.get("trade_allowed"),
            "block_reason":  decision.get("block_reason"),
            "market_state":  decision.get("market_state"),
        })
        signals.append(sig_norm)
        candles_map[symbol] = candles_by_tf
        decisions.append((symbol, alert_type, result, decision, full_msg))

    if not signals:
        log("[RADAR] 전송할 신호 없음")
        return

    # 이미지 앨범 전송
    try:
        images = []
        for sig in signals:
            sym     = sig.get("symbol", "")
            candles = candles_map.get(sym, {}).get("15m", [])
            images.append(chart_renderer.render_radar_card(sig, candles))
        if telegram.send_album(images, caption=build_radar_album_caption(signals)):
            log(f"[RADAR] 앨범 전송 완료 ({len(images)}장)")
            for symbol, alert_type, result, decision, _ in decisions:
                record_to_sheet(symbol, alert_type, result)
                record_to_journal(symbol, alert_type, result)
                if decision.get("trade_allowed"):
                    risk_d = decision.get("risk", {})
                    ms_d   = {"state": decision.get("market_state", "UNKNOWN")}
                    record_to_trade_journal(symbol, alert_type,
                                            decision.get("direction", "WAIT"),
                                            result if isinstance(result, dict) else {},
                                            risk_d, ms_d)
            return
    except Exception as e:
        log(f"[RADAR] 이미지 생성 실패, 텍스트 fallback: {e}")
        traceback.print_exc()

    # 텍스트 fallback — 통일 메시지 전송
    for symbol, alert_type, result, decision, full_msg in decisions:
        if telegram.send_message(full_msg):
            record_to_sheet(symbol, alert_type, result)
            record_to_journal(symbol, alert_type, result)
            log(f"[RADAR TEXT] {symbol} {alert_type} 전송")


def run_entry_timing_if_needed(symbol, candles_by_tf, structure_result=None,
                                market_data=None, market_state=None):
    if not ENABLE_PRE_REAL:
        return
    if not should_run_entry(symbol):
        return

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

        if not extract_message(result):
            continue

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
        decision  = build_decision(symbol, sig_data, ms, entry_check, risk, scenario, alert_type)
        base_msg  = extract_message(result) or ""
        full_msg  = format_decision_message(decision, base_msg)

        # 신규 journal 기록 (WAIT/BLOCKED 포함 모든 신호)
        if ENABLE_JOURNAL:
            try:
                from tradebot.journal.storage import record_signal as _rec
                _rec(decision)
            except Exception as _je:
                log(f"[JOURNAL] record 실패: {_je}")

        final_dir = decision.get("direction", "WAIT")
        if not send_alert_safely(symbol, alert_type, full_msg, final_dir, force=False):
            continue

        record_to_sheet(symbol, alert_type, result)
        record_to_journal(symbol, alert_type, result)

        if decision.get("trade_allowed"):
            _latest_signals[symbol] = sig_data
            record_to_trade_journal(symbol, alert_type, final_dir, sig_data, risk, ms)


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

    price      = get_current_price(symbol)
    price_skip = should_skip_by_price_change(symbol, price)
    if not price_skip:
        run_entry_timing_if_needed(symbol, candles_by_tf, structure_result, market_data, ms)
    run_info_analyzers_if_needed(symbol, candles_by_tf, structure_result, market_data)
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
