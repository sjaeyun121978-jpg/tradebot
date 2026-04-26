# main.py
# Railway Telegram Trading Bot
# 수정 반영:
# - TELEGRAM_TOKEN / TG_BOT_TOKEN 둘 다 지원
# - TELEGRAM_CHAT_ID / TG_CHAT_ID 둘 다 지원
# - import 실패 로그 출력
# - 매 정각 1H 종합 전광판 발송
# - 매일 09시 일봉/주간 브리핑 발송
# - price_skip은 PRE/PULLBACK/REAL에만 적용
# - 진입레이더/정보성 분석은 price_skip 영향 제거
# - [추가] 진입레이더: 15분봉 마감 기준 실행 (60초 반복 제거)
# - [추가] 진입레이더: ETH+BTC 동시 분석 후 이미지 앨범 전송

import os
import time
import traceback
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST)


def log(msg):
    print(f"[{now_kst().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# =========================
# 모듈 import 체크
# =========================

try:
    import entry_timing
    log("[IMPORT OK] entry_timing")
except Exception as e:
    log(f"[IMPORT FAIL] entry_timing: {e}")
    entry_timing = None

try:
    import scheduler
    log("[IMPORT OK] scheduler")
except Exception as e:
    log(f"[IMPORT FAIL] scheduler: {e}")
    scheduler = None

try:
    import structure_analyzer
    log("[IMPORT OK] structure_analyzer")
except Exception as e:
    log(f"[IMPORT FAIL] structure_analyzer: {e}")
    structure_analyzer = None

try:
    import analyzers
    log("[IMPORT OK] analyzers")
except Exception as e:
    log(f"[IMPORT FAIL] analyzers: {e}")
    analyzers = None

try:
    import indicators
    log("[IMPORT OK] indicators")
except Exception as e:
    log(f"[IMPORT FAIL] indicators: {e}")
    indicators = None

try:
    import sheets
    log("[IMPORT OK] sheets")
except Exception as e:
    log(f"[IMPORT FAIL] sheets: {e}")
    sheets = None

try:
    import signal_journal
    log("[IMPORT OK] signal_journal")
except Exception as e:
    log(f"[IMPORT FAIL] signal_journal: {e}")
    signal_journal = None

try:
    import daily_weekly_briefing
    log("[IMPORT OK] daily_weekly_briefing")
except Exception as e:
    log(f"[IMPORT FAIL] daily_weekly_briefing: {e}")
    daily_weekly_briefing = None

try:
    import core_analyzer
    log("[IMPORT OK] core_analyzer")
except Exception as e:
    log(f"[IMPORT FAIL] core_analyzer: {e}")
    core_analyzer = None

try:
    import chart_renderer
    log("[IMPORT OK] chart_renderer")
except Exception as e:
    log(f"[IMPORT FAIL] chart_renderer: {e}")
    chart_renderer = None


# =========================
# 환경 설정
# =========================

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_TOKEN")
    or os.getenv("TG_BOT_TOKEN")
    or ""
)

TELEGRAM_CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("TG_CHAT_ID")
    or ""
)

BINANCE_BASE_URL = "https://api.binance.com"
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
LOOP_SLEEP_SEC = int(os.getenv("LOOP_SLEEP_SEC", "20"))
PRICE_SKIP_THRESHOLD = float(os.getenv("PRICE_SKIP_THRESHOLD", "0.0008"))
SAME_ALERT_COOLDOWN_SEC = int(os.getenv("SAME_ALERT_COOLDOWN_SEC", "900"))
TELEGRAM_MIN_INTERVAL_SEC = float(os.getenv("TELEGRAM_MIN_INTERVAL_SEC", "1.2"))
MAX_LOOP_ERROR_COUNT = int(os.getenv("MAX_LOOP_ERROR_COUNT", "10"))
ENABLE_SHEETS = os.getenv("ENABLE_SHEETS", "false").lower() == "true"

CANDLE_TTL = {"15m": 60, "1h": 180, "4h": 600, "1d": 1800, "1w": 3600}
ENTRY_ANALYSIS_INTERVAL_SEC = int(os.getenv("ENTRY_ANALYSIS_INTERVAL_SEC", "60"))
INFO_ANALYSIS_INTERVAL_SEC  = int(os.getenv("INFO_ANALYSIS_INTERVAL_SEC",  "300"))


# =========================
# 전역 캐시
# =========================

candle_cache  = {}
price_cache   = {}
last_entry_run = defaultdict(float)
last_info_run  = defaultdict(float)
last_alert_sent = {}
last_telegram_sent_at = 0.0
last_hourly_dashboard_sent      = {}
last_daily_weekly_briefing_date = {}

# ★ 15분봉 마감 슬롯 추적
last_radar_15m_slot = None

loop_error_count = 0


# =========================
# 유틸
# =========================

def now_ts():
    return time.time()


def safe_call(func, *args, default=None, name="unknown", **kwargs):
    try:
        if func is None:
            return default
        return func(*args, **kwargs)
    except Exception as e:
        log(f"[ERROR] {name}: {e}")
        traceback.print_exc()
        return default


def get_func(module, candidates):
    if module is None:
        return None
    for name in candidates:
        if hasattr(module, name):
            return getattr(module, name)
    return None


# =========================
# Binance API
# =========================

def fetch_klines(symbol, interval, limit=200):
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    r.raise_for_status()
    return [
        {"open_time": i[0], "open": float(i[1]), "high": float(i[2]),
         "low": float(i[3]), "close": float(i[4]), "volume": float(i[5]), "close_time": i[6]}
        for i in r.json()
    ]


def get_cached_candles(symbol, interval, limit=200):
    key = f"{symbol}:{interval}:{limit}"
    cached = candle_cache.get(key)
    if cached and now_ts() - cached["ts"] < CANDLE_TTL.get(interval, 120):
        return cached["data"]
    candles = fetch_klines(symbol, interval, limit)
    candle_cache[key] = {"ts": now_ts(), "data": candles}
    return candles


def collect_candles(symbol):
    return {
        "15m": get_cached_candles(symbol, "15m", 200),
        "1h":  get_cached_candles(symbol, "1h",  200),
        "4h":  get_cached_candles(symbol, "4h",  200),
        "1d":  get_cached_candles(symbol, "1d",  200),
        "1w":  get_cached_candles(symbol, "1w",  100),
    }


def get_current_price(symbol):
    candles = get_cached_candles(symbol, "15m", 100)
    return candles[-1]["close"] if candles else None


# =========================
# 실행 조건
# =========================

def should_skip_by_price_change(symbol, price):
    if price is None:
        return True
    prev = price_cache.get(symbol)
    price_cache[symbol] = {"price": price, "ts": now_ts()}
    if not prev or prev["price"] <= 0:
        return False
    return abs(price - prev["price"]) / prev["price"] < PRICE_SKIP_THRESHOLD


def should_run_interval(cache, key, interval_sec):
    if now_ts() - cache.get(key, 0) >= interval_sec:
        cache[key] = now_ts()
        return True
    return False


def should_run_entry(symbol):
    return should_run_interval(last_entry_run, symbol, ENTRY_ANALYSIS_INTERVAL_SEC)


def should_run_info(symbol):
    return should_run_interval(last_info_run, symbol, INFO_ANALYSIS_INTERVAL_SEC)


# ★ 15분봉 마감 슬롯 체크
def current_15m_slot():
    now = now_kst()
    slot_min = (now.minute // 15) * 15
    return now.strftime(f"%Y-%m-%d %H:{slot_min:02d}")


def is_new_15m_candle():
    global last_radar_15m_slot
    slot = current_15m_slot()
    if slot != last_radar_15m_slot:
        last_radar_15m_slot = slot
        return True
    return False


# =========================
# Telegram 전송
# =========================

def make_alert_key(symbol, alert_type, direction=None):
    return f"{symbol}:{alert_type}:{direction or 'NONE'}"


def should_send_alert(symbol, alert_type, direction=None, cooldown_sec=SAME_ALERT_COOLDOWN_SEC):
    key = make_alert_key(symbol, alert_type, direction)
    if now_ts() - last_alert_sent.get(key, 0) < cooldown_sec:
        return False
    last_alert_sent[key] = now_ts()
    return True


def telegram_send(text):
    global last_telegram_sent_at
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("[WARN] 토큰/채팅ID 없음")
        print(text, flush=True)
        return False
    elapsed = now_ts() - last_telegram_sent_at
    if elapsed < TELEGRAM_MIN_INTERVAL_SEC:
        time.sleep(TELEGRAM_MIN_INTERVAL_SEC - elapsed)
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
        last_telegram_sent_at = now_ts()
        if r.status_code != 200:
            log(f"[TELEGRAM ERROR] {r.status_code} {r.text}")
            return False
        return True
    except Exception as e:
        log(f"[TELEGRAM SEND ERROR] {e}")
        return False


def telegram_send_photo(image_bytes: bytes, caption: str = ""):
    global last_telegram_sent_at
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    elapsed = now_ts() - last_telegram_sent_at
    if elapsed < TELEGRAM_MIN_INTERVAL_SEC:
        time.sleep(TELEGRAM_MIN_INTERVAL_SEC - elapsed)
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("card.png", image_bytes, "image/png")},
            timeout=20,
        )
        last_telegram_sent_at = now_ts()
        if r.status_code != 200:
            log(f"[PHOTO ERROR] {r.status_code} {r.text}")
            return False
        return True
    except Exception as e:
        log(f"[PHOTO SEND ERROR] {e}")
        return False


def telegram_send_album(image_bytes_list: list):
    global last_telegram_sent_at
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    if len(image_bytes_list) == 1:
        return telegram_send_photo(image_bytes_list[0])
    import json
    elapsed = now_ts() - last_telegram_sent_at
    if elapsed < TELEGRAM_MIN_INTERVAL_SEC:
        time.sleep(TELEGRAM_MIN_INTERVAL_SEC - elapsed)
    media = []
    files = {}
    for i, img in enumerate(image_bytes_list):
        key = f"photo{i}"
        media.append({"type": "photo", "media": f"attach://{key}"})
        files[key] = (f"card{i}.png", img, "image/png")
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMediaGroup",
            data={"chat_id": TELEGRAM_CHAT_ID, "media": json.dumps(media)},
            files=files,
            timeout=30,
        )
        last_telegram_sent_at = now_ts()
        if r.status_code != 200:
            log(f"[ALBUM ERROR] {r.status_code} {r.text}")
            return False
        return True
    except Exception as e:
        log(f"[ALBUM SEND ERROR] {e}")
        return False


def send_alert_safely(symbol, alert_type, message, direction=None, force=False):
    if not message:
        return False
    if not force and not should_send_alert(symbol, alert_type, direction):
        log(f"[SKIP ALERT] {symbol} {alert_type} {direction} cooldown")
        return False
    return telegram_send(message)


# =========================
# 모듈 연결
# =========================

def run_structure_analysis(symbol, candles_by_tf):
    func = get_func(structure_analyzer, [
        "analyze_structure", "run_structure_analysis",
        "fact_based_structure_analysis", "analyze",
    ])
    if func is None:
        log("[WARN] structure_analyzer 함수 없음")
        return None
    return safe_call(func, symbol, candles_by_tf, default=None, name="structure_analyzer")


def run_entry_timing(symbol, candles_by_tf, structure_result=None):
    func = get_func(entry_timing, [
        "analyze_entry_timing", "run_entry_timing", "check_entry", "analyze",
    ])
    if func is None:
        log("[WARN] entry_timing 함수 없음")
        return None
    try:
        return func(symbol, candles_by_tf, structure_result)
    except TypeError:
        return safe_call(func, symbol, candles_by_tf, default=None, name="entry_timing")


def run_general_analyzers(symbol, candles_by_tf, structure_result=None):
    results = []
    if analyzers is None:
        return results
    for fname in ["analyze_mungkkul", "analyze_candle_god", "analyze_dogpig",
                  "analyze_info_message", "run_all_analyzers", "analyze"]:
        if hasattr(analyzers, fname):
            func = getattr(analyzers, fname)
            try:
                result = func(symbol, candles_by_tf, structure_result)
            except TypeError:
                result = safe_call(func, symbol, candles_by_tf, default=None, name=f"analyzers.{fname}")
            if result:
                results.append(result)
    return results


# =========================
# 결과 추출
# =========================

def extract_message(result):
    if result is None: return None
    if isinstance(result, str): return result
    if isinstance(result, dict):
        for key in ["message", "text", "telegram_message", "alert", "summary"]:
            if result.get(key): return str(result[key])
    return str(result)


def extract_direction(result):
    if result is None: return None
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
            if result.get(key): return str(result[key]).upper()
    text = str(result).upper()
    if "REAL ENTRY" in text:                          return "REAL_ENTRY"
    if "PULLBACK"   in text:                          return "PULLBACK_ENTRY"
    if "PRE-ENTRY"  in text or "PRE ENTRY" in text:   return "PRE_ENTRY"
    if "RADAR"      in text or "레이더" in text:       return "ENTRY_RADAR"
    if "DAILY"      in text or "일봉"   in text:       return "DAILY_BRIEFING"
    if "WEEKLY"     in text or "주간"   in text:       return "WEEKLY_PROGRESS_BRIEFING"
    if "WAIT"       in text or "박스권" in text:       return "WAIT"
    return default_type


# =========================
# Google Sheets / Journal
# =========================

def record_to_sheet(symbol, event_type, payload):
    if not ENABLE_SHEETS or sheets is None: return
    func = get_func(sheets, ["append_signal", "record_signal", "write_signal", "save_signal", "append_row"])
    if func: safe_call(func, symbol, event_type, payload, default=None, name="sheets")


def record_to_journal(symbol, event_type, payload):
    if not ENABLE_SHEETS or signal_journal is None: return
    func = get_func(signal_journal, ["record", "record_signal", "append_signal", "save"])
    if func: safe_call(func, symbol, event_type, payload, default=None, name="signal_journal")


# =========================
# 정시 1H 전광판
# =========================

def run_hourly_dashboard_if_needed(symbol, candles_by_tf):
    current = now_kst()

    # 매 정각 00~20분 사이 1회 발송
    if current.minute > 20:
        return

    hour_key  = current.strftime("%Y-%m-%d %H")
    cache_key = f"{symbol}:{hour_key}"

    if last_hourly_dashboard_sent.get(cache_key):
        return

    log(f"[HOURLY DASHBOARD] {symbol} {hour_key}")

    structure_result = run_structure_analysis(symbol, candles_by_tf)
    msg = extract_message(structure_result)

    if msg:
        send_alert_safely(
            symbol=symbol,
            alert_type="HOURLY_DASHBOARD",
            message=msg,
            direction=extract_direction(structure_result),
            force=True,
        )
        record_to_sheet(symbol, "HOURLY_DASHBOARD", structure_result)
        record_to_journal(symbol, "HOURLY_DASHBOARD", structure_result)
    else:
        log(f"[WARN] {symbol} HOURLY_DASHBOARD 메시지 없음")

    last_hourly_dashboard_sent[cache_key] = True


# =========================
# 09시 일봉/주간 브리핑
# =========================

def run_daily_weekly_briefings_if_needed(symbol, candles_by_tf):
    if daily_weekly_briefing is None: return
    current = now_kst()
    if current.hour != 9 or current.minute > 9: return
    today_key = current.strftime("%Y-%m-%d")
    cache_key = f"{symbol}:{today_key}"
    if last_daily_weekly_briefing_date.get(cache_key): return
    func = get_func(daily_weekly_briefing, ["run_all_briefings"])
    if func is None:
        log("[WARN] daily_weekly_briefing.run_all_briefings 없음")
        return
    log(f"[DAILY/WEEKLY BRIEFING] {symbol} {today_key}")
    results = safe_call(func, symbol, candles_by_tf, default=[], name="daily_weekly_briefing")
    for result in (results or []):
        msg = extract_message(result)
        alert_type = extract_alert_type(result, "BRIEFING")
        if msg:
            send_alert_safely(symbol=symbol, alert_type=alert_type,
                              message=msg, direction="INFO", force=True)
            record_to_sheet(symbol, alert_type, result)
            record_to_journal(symbol, alert_type, result)
    last_daily_weekly_briefing_date[cache_key] = True


# =========================
# ★ 진입레이더 (15분봉 마감, ETH+BTC 앨범)
# =========================

def run_entry_radar_on_15m_close(all_candles: dict):
    """
    15분봉 마감 시 1회 실행.
    ETH + BTC 동시 분석 후 이미지 앨범 전송.
    chart_renderer 없으면 텍스트로 fallback.
    """
    if entry_timing is None:
        log("[SKIP] entry_timing 모듈 없음")
        return

    radar_func = get_func(entry_timing, [
        "run_entry_radar", "entry_radar", "analyze_radar", "check_radar",
    ])
    if radar_func is None:
        log("[WARN] entry_timing radar 함수 없음")
        return

    signals      = []   # 이미지 렌더용 sig
    candles_map  = {}   # 이미지 렌더용 캔들
    text_results = []   # 텍스트 fallback용

    for symbol in SYMBOLS:
        candles_by_tf = all_candles.get(symbol)
        if not candles_by_tf:
            continue
        try:
            result = radar_func(symbol, candles_by_tf)
        except Exception as e:
            log(f"[ERROR] radar {symbol}: {e}")
            continue
        if not result:
            log(f"[WARN] {symbol} radar 결과 없음")
            continue

        direction  = extract_direction(result)
        alert_type = extract_alert_type(result, "ENTRY_RADAR")

        if not should_send_alert(symbol, alert_type, direction):
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

    # ── 이미지 개별 전송 (풀사이즈) ─────────────
    if chart_renderer is not None:
        try:
            all_ok = True
            for sig, (sym, atype, res, _) in zip(signals, text_results):
                c15 = candles_map.get(sym, {}).get("15m", [])
                png = chart_renderer.render_radar_card(sig, c15)
                ok  = telegram_send_photo(png)
                if ok:
                    log(f"[RADAR] {sym} 이미지 전송 완료")
                    record_to_sheet(sym, atype, res)
                    record_to_journal(sym, atype, res)
                else:
                    all_ok = False
            if all_ok:
                return
        except Exception as e:
            log(f"[RADAR] 이미지 실패 → 텍스트 fallback: {e}")
            traceback.print_exc()

    # ── 텍스트 fallback ───────────────────────
    for sym, atype, result, direction in text_results:
        msg = extract_message(result)
        if msg:
            telegram_send(msg)
            record_to_sheet(sym, atype, result)
            record_to_journal(sym, atype, result)
            log(f"[RADAR TEXT] {sym} {atype} 전송")


# =========================
# PRE / PULLBACK / REAL
# =========================

def run_entry_timing_if_needed(symbol, candles_by_tf, structure_result=None):
    if not should_run_entry(symbol): return
    entry_result = run_entry_timing(symbol, candles_by_tf, structure_result)
    if not entry_result:
        log(f"[WARN] {symbol} entry_result 없음")
        return
    results = entry_result if isinstance(entry_result, list) else [entry_result]
    for result in results:
        msg = extract_message(result)
        if msg:
            send_alert_safely(
                symbol=symbol,
                alert_type=extract_alert_type(result, "ENTRY"),
                message=msg,
                direction=extract_direction(result),
                force=False,
            )
            record_to_sheet(symbol, extract_alert_type(result, "ENTRY"), result)
            record_to_journal(symbol, extract_alert_type(result, "ENTRY"), result)


# =========================
# 정보성 분석
# =========================

def run_info_analyzers_if_needed(symbol, candles_by_tf, structure_result=None):
    if not should_run_info(symbol): return
    for result in run_general_analyzers(symbol, candles_by_tf, structure_result):
        msg = extract_message(result)
        if msg:
            alert_type = extract_alert_type(result, "INFO_ANALYSIS")
            send_alert_safely(symbol=symbol, alert_type=alert_type,
                              message=msg, direction=extract_direction(result), force=False)
            record_to_sheet(symbol, alert_type, result)
            record_to_journal(symbol, alert_type, result)


# =========================
# Scheduler
# =========================

def run_scheduler_tasks():
    if scheduler is None: return
    func = get_func(scheduler, ["run_pending", "run_scheduler", "tick", "run"])
    if func: safe_call(func, default=None, name="scheduler")


# =========================
# 심볼별 사이클 (레이더 제외)
# =========================

def run_symbol_cycle(symbol, candles_by_tf):
    log(f"[START] {symbol} cycle")
    run_hourly_dashboard_if_needed(symbol, candles_by_tf)
    run_daily_weekly_briefings_if_needed(symbol, candles_by_tf)
    price = get_current_price(symbol)
    if not should_skip_by_price_change(symbol, price):
        run_entry_timing_if_needed(symbol, candles_by_tf)
    run_info_analyzers_if_needed(symbol, candles_by_tf)
    log(f"[END] {symbol} cycle")


# =========================
# 시작 메시지
# =========================

def send_startup_message():
    token_source = "TELEGRAM_TOKEN" if os.getenv("TELEGRAM_TOKEN") else "TG_BOT_TOKEN"
    chat_source  = "TELEGRAM_CHAT_ID" if os.getenv("TELEGRAM_CHAT_ID") else "TG_CHAT_ID"
    telegram_send(
        "✅ Railway Telegram Trading Bot 시작\n\n"
        f"Token: {token_source} / Chat: {chat_source}\n\n"
        "정시: 매 정각 전광판 · 09시 브리핑\n"
        "레이더: 15분봉 마감 기준 ETH+BTC 이미지 앨범\n"
        "진입: PRE / PULLBACK / REAL ENTRY\n"
        "보호: 캐싱 · rate limit · 쿨다운 · 무한루프 방지"
    )


# =========================
# 메인 루프
# =========================

def main_loop():
    global loop_error_count

    send_startup_message()
    log("[BOT STARTED]")

    while True:
        try:
            run_scheduler_tasks()

            # 전체 캔들 수집
            all_candles = {sym: collect_candles(sym) for sym in SYMBOLS}

            # ★ 15분봉 마감 → 레이더 (ETH+BTC 동시)
            if is_new_15m_candle():
                log("[15M CLOSE] 진입레이더 실행")
                run_entry_radar_on_15m_close(all_candles)

            # 심볼별 사이클
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
                telegram_send(
                    f"🚨 오류 누적 {loop_error_count}회\n{e}\n120초 후 재시도"
                )
                time.sleep(120)
                loop_error_count = 0
            else:
                time.sleep(10)


if __name__ == "__main__":
    main_loop()
