import os
import time
import traceback
from datetime import datetime
from collections import defaultdict

from tradebot.config.settings import (
    KST,
    SYMBOLS,
    LOOP_SLEEP_SEC,
    PRICE_SKIP_THRESHOLD,
    SAME_ALERT_COOLDOWN_SEC,
    MAX_LOOP_ERROR_COUNT,
    ENABLE_SHEETS,
    ENTRY_ANALYSIS_INTERVAL_SEC,
    INFO_ANALYSIS_INTERVAL_SEC,
)
from tradebot.data.bybit_client import collect_candles, get_current_price
from tradebot.analysis import entry as entry_timing
from tradebot.analysis import structure as structure_analyzer
from tradebot.analysis import briefing as daily_weekly_briefing
from tradebot.ai import claude_analyzers
from tradebot.render import chart_renderer
from tradebot.delivery import telegram
from tradebot.delivery import sheets
from tradebot.journal import signal_journal

price_cache = {}
last_entry_run = defaultdict(float)
last_info_run = defaultdict(float)
last_alert_sent = {}
last_hourly_dashboard_sent = {}
last_daily_weekly_briefing_date = {}
last_radar_15m_slot = None
loop_error_count = 0


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


def current_15m_slot():
    now = now_kst()
    slot_minute = (now.minute // 15) * 15
    return now.strftime(f"%Y-%m-%d %H:{slot_minute:02d}")


def is_new_15m_candle():
    global last_radar_15m_slot
    slot = current_15m_slot()
    if slot != last_radar_15m_slot:
        last_radar_15m_slot = slot
        return True
    return False


def make_alert_key(symbol, alert_type, direction=None):
    return f"{symbol}:{alert_type}:{direction or 'NONE'}"


def should_send_alert(symbol, alert_type, direction=None, cooldown_sec=SAME_ALERT_COOLDOWN_SEC):
    key = make_alert_key(symbol, alert_type, direction)
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
    msg = extract_message(payload) or ""
    direction = extract_direction(payload) or "INFO"
    safe_call(signal_journal.record_signal, symbol, event_type, direction, msg, default=None, name="signal_journal.record_signal")


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


def extract_direction(result):
    if result is None:
        return None
    if isinstance(result, dict):
        for key in ["direction", "side", "entry_side", "signal"]:
            val = result.get(key)
            if val:
                val = str(val).upper()
                if "LONG" in val:
                    return "LONG"
                if "SHORT" in val:
                    return "SHORT"
                if "WAIT" in val:
                    return "WAIT"
                if "INFO" in val:
                    return "INFO"
    text = str(result).upper()
    if "LONG" in text or "롱" in text:
        return "LONG"
    if "SHORT" in text or "숏" in text:
        return "SHORT"
    if "WAIT" in text or "대기" in text:
        return "WAIT"
    return None


def extract_alert_type(result, default_type):
    if isinstance(result, dict):
        for key in ["type", "alert_type", "entry_type", "signal_type"]:
            if result.get(key):
                return str(result[key]).upper()
    text = str(result).upper()
    if "REAL ENTRY" in text:
        return "REAL_ENTRY"
    if "PULLBACK" in text:
        return "PULLBACK_ENTRY"
    if "PRE-ENTRY" in text or "PRE ENTRY" in text:
        return "PRE_ENTRY"
    if "RADAR" in text or "레이더" in text:
        return "ENTRY_RADAR"
    if "DAILY" in text or "일봉" in text:
        return "DAILY_BRIEFING"
    if "WEEKLY" in text or "주간" in text:
        return "WEEKLY_PROGRESS_BRIEFING"
    if "WAIT" in text or "박스권" in text:
        return "WAIT"
    return default_type


def run_structure_analysis(symbol, candles_by_tf):
    return safe_call(structure_analyzer.analyze_structure, symbol, candles_by_tf, default=None, name="structure_analyzer.analyze_structure")


def run_entry_timing(symbol, candles_by_tf, structure_result=None):
    try:
        return entry_timing.analyze_entry_timing(symbol, candles_by_tf, structure_result)
    except TypeError:
        return safe_call(entry_timing.analyze_entry_timing, symbol, candles_by_tf, default=None, name="entry_timing.analyze_entry_timing")
    except Exception as e:
        log(f"[ERROR] entry_timing: {e}")
        traceback.print_exc()
        return None


def run_general_analyzers(symbol, candles_by_tf, structure_result=None):
    # Claude 분석 계열은 함수명이 과거 버전마다 달랐기 때문에 존재하는 함수만 안전 실행한다.
    results = []
    for fname in ["analyze_mungkkul", "analyze_candle_god", "analyze_dogpig", "analyze_info_message", "run_all_analyzers", "analyze"]:
        func = getattr(claude_analyzers, fname, None)
        if func is None:
            continue
        try:
            result = func(symbol, candles_by_tf, structure_result)
        except TypeError:
            result = safe_call(func, symbol, candles_by_tf, default=None, name=f"claude_analyzers.{fname}")
        if result:
            results.append(result)
    return results


def run_hourly_dashboard_if_needed(symbol, candles_by_tf):
    current = now_kst()
    if current.minute > 4:
        return
    hour_key = current.strftime("%Y-%m-%d %H")
    cache_key = f"{symbol}:{hour_key}"
    if last_hourly_dashboard_sent.get(cache_key):
        return
    log(f"[HOURLY DASHBOARD] {symbol} {hour_key}")
    structure_result = run_structure_analysis(symbol, candles_by_tf)
    if not structure_result:
        log(f"[WARN] {symbol} HOURLY_DASHBOARD 결과 없음")
        last_hourly_dashboard_sent[cache_key] = True
        return
    try:
        png = chart_renderer.render_dashboard_card(structure_result, candles_by_tf.get("1h", []))
        if telegram.send_photo(png):
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
    current = now_kst()
    if current.hour != 9 or current.minute > 9:
        return
    today_key = current.strftime("%Y-%m-%d")
    cache_key = f"{symbol}:{today_key}"
    if last_daily_weekly_briefing_date.get(cache_key):
        return
    log(f"[DAILY/WEEKLY BRIEFING] {symbol} {today_key}")
    results = safe_call(daily_weekly_briefing.run_all_briefings, symbol, candles_by_tf, default=[], name="briefing.run_all_briefings")
    for result in (results or []):
        msg = extract_message(result)
        alert_type = extract_alert_type(result, "BRIEFING")
        if msg:
            send_alert_safely(symbol, alert_type, msg, "INFO", force=True)
            record_to_sheet(symbol, alert_type, result)
            record_to_journal(symbol, alert_type, result)
    last_daily_weekly_briefing_date[cache_key] = True


def run_entry_radar_on_15m_close(all_candles: dict):
    signals = []
    candles_map = {}
    text_results = []
    for symbol in SYMBOLS:
        candles_by_tf = all_candles.get(symbol)
        if not candles_by_tf:
            continue
        try:
            result = entry_timing.run_entry_radar(symbol, candles_by_tf)
        except Exception as e:
            log(f"[ERROR] radar {symbol}: {e}")
            traceback.print_exc()
            continue
        if not result:
            log(f"[WARN] {symbol} radar 결과 없음")
            continue
        direction = extract_direction(result)
        alert_type = extract_alert_type(result, "ENTRY_RADAR")
        if not should_send_alert(symbol, alert_type, direction, cooldown_sec=SAME_ALERT_COOLDOWN_SEC):
            log(f"[SKIP ALERT] {symbol} {alert_type} cooldown")
            continue
        sig = result if isinstance(result, dict) else {}
        sig["symbol"] = symbol
        signals.append(sig)
        candles_map[symbol] = candles_by_tf
        text_results.append((symbol, alert_type, result, direction))
    if not signals:
        log("[RADAR] 전송할 신호 없음")
        return
    try:
        images = []
        for sig in signals:
            symbol = sig.get("symbol", "")
            candles = candles_map.get(symbol, {}).get("15m", [])
            images.append(chart_renderer.render_radar_card(sig, candles))
        if telegram.send_album(images):
            log(f"[RADAR] 앨범 전송 완료 ({len(images)}장)")
            for symbol, alert_type, result, _ in text_results:
                record_to_sheet(symbol, alert_type, result)
                record_to_journal(symbol, alert_type, result)
            return
    except Exception as e:
        log(f"[RADAR] 이미지 생성 실패, 텍스트로 fallback: {e}")
        traceback.print_exc()
    for symbol, alert_type, result, direction in text_results:
        msg = extract_message(result)
        if msg:
            telegram.send_message(msg)
            record_to_sheet(symbol, alert_type, result)
            record_to_journal(symbol, alert_type, result)
            log(f"[RADAR TEXT] {symbol} {alert_type} 전송")


def run_entry_timing_if_needed(symbol, candles_by_tf, structure_result=None):
    if not should_run_entry(symbol):
        return
    entry_result = run_entry_timing(symbol, candles_by_tf, structure_result)
    if not entry_result:
        log(f"[WARN] {symbol} entry_result 없음")
        return
    results = entry_result if isinstance(entry_result, list) else [entry_result]
    for result in results:
        msg = extract_message(result)
        direction = extract_direction(result)
        alert_type = extract_alert_type(result, "ENTRY")
        if msg:
            send_alert_safely(symbol, alert_type, msg, direction, force=False)
            record_to_sheet(symbol, alert_type, result)
            record_to_journal(symbol, alert_type, result)


def run_info_analyzers_if_needed(symbol, candles_by_tf, structure_result=None):
    if not should_run_info(symbol):
        return
    for result in run_general_analyzers(symbol, candles_by_tf, structure_result):
        msg = extract_message(result)
        direction = extract_direction(result)
        alert_type = extract_alert_type(result, "INFO_ANALYSIS")
        if msg:
            send_alert_safely(symbol, alert_type, msg, direction, force=False)
            record_to_sheet(symbol, alert_type, result)
            record_to_journal(symbol, alert_type, result)


def run_symbol_cycle(symbol, candles_by_tf):
    log(f"[START] {symbol} cycle")
    run_hourly_dashboard_if_needed(symbol, candles_by_tf)
    run_daily_weekly_briefings_if_needed(symbol, candles_by_tf)
    price = get_current_price(symbol)
    price_skip = should_skip_by_price_change(symbol, price)
    if not price_skip:
        run_entry_timing_if_needed(symbol, candles_by_tf)
    run_info_analyzers_if_needed(symbol, candles_by_tf)
    log(f"[END] {symbol} cycle")


def send_startup_message():
    msg = (
        "✅ Bybit 기반 TradeBot 시작\n\n"
        "데이터 소스: Bybit v5 linear market\n"
        f"심볼: {', '.join(SYMBOLS)}\n\n"
        "정시 기능:\n"
        "- 매 정각 1H 종합 전광판\n"
        "- 매일 09시 일봉/주간 브리핑\n\n"
        "진입 기능:\n"
        "- 진입레이더: 15분봉 마감 기준 ETH+BTC 이미지 앨범\n"
        "- PRE-ENTRY / PULLBACK / REAL ENTRY\n\n"
        "보호 기능:\n"
        "- 캔들 캐싱 / API 최소화\n"
        "- 메시지 rate limit\n"
        "- 가격 변화 없으면 PRE/PULLBACK/REAL 생략\n"
        "- 알림 폭주 방지 / 무한루프 방지"
    )
    telegram.send_message(msg)


def main_loop():
    global loop_error_count
    send_startup_message()
    log("[BOT STARTED]")
    while True:
        try:
            all_candles = {}
            for symbol in SYMBOLS:
                all_candles[symbol] = collect_candles(symbol)
            if is_new_15m_candle():
                log("[15M CLOSE] 진입레이더 실행")
                run_entry_radar_on_15m_close(all_candles)
            for symbol in SYMBOLS:
                run_symbol_cycle(symbol, all_candles[symbol])
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
                    "🚨 Trading Bot 오류 누적\n\n"
                    f"오류 횟수: {loop_error_count}\n"
                    f"에러: {e}\n\n"
                    "무한루프 방지 — 120초 대기 후 재시도"
                )
                time.sleep(120)
                loop_error_count = 0
            else:
                time.sleep(10)
