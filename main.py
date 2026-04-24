# main.py
# Railway 기반 Telegram Trading Bot
# 목표:
# - 기존 기능 유지
# - 캔들 캐싱
# - API 호출 최소화
# - 메시지 rate limit
# - 구조 분석 주기 분리
# - 가격 변화 없으면 분석 생략
# - 알림 폭주 방지
# - 무한루프 방지

import os
import time
import traceback
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# =========================
# 기존 프로젝트 모듈
# =========================

try:
    import entry_timing
except Exception:
    entry_timing = None

try:
    import scheduler
except Exception:
    scheduler = None

try:
    import structure_analyzer
except Exception:
    structure_analyzer = None

try:
    import analyzers
except Exception:
    analyzers = None

try:
    import indicators
except Exception:
    indicators = None

try:
    import sheets
except Exception:
    sheets = None

try:
    import signal_journal
except Exception:
    signal_journal = None


# =========================
# 환경 설정
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BINANCE_BASE_URL = "https://api.binance.com"

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

TIMEFRAMES = ["15m", "1h", "4h", "1d"]

LOOP_SLEEP_SEC = int(os.getenv("LOOP_SLEEP_SEC", "20"))

PRICE_SKIP_THRESHOLD = float(os.getenv("PRICE_SKIP_THRESHOLD", "0.0008"))  # 0.08%

SAME_ALERT_COOLDOWN_SEC = int(os.getenv("SAME_ALERT_COOLDOWN_SEC", "900"))  # 15분

TELEGRAM_MIN_INTERVAL_SEC = float(os.getenv("TELEGRAM_MIN_INTERVAL_SEC", "1.2"))

MAX_LOOP_ERROR_COUNT = int(os.getenv("MAX_LOOP_ERROR_COUNT", "10"))

KST = timezone(timedelta(hours=9))


# =========================
# TTL 설정
# =========================

CANDLE_TTL = {
    "15m": 60,
    "1h": 180,
    "4h": 600,
    "1d": 1800,
}

STRUCTURE_INTERVAL = {
    "15m": 300,
    "1h": 900,
    "4h": 1800,
    "1d": 3600,
}

ENTRY_ANALYSIS_INTERVAL_SEC = 60
RADAR_ANALYSIS_INTERVAL_SEC = 60
INFO_ANALYSIS_INTERVAL_SEC = 300


# =========================
# 전역 캐시
# =========================

candle_cache = {}
price_cache = {}
last_structure_run = defaultdict(float)
last_entry_run = defaultdict(float)
last_radar_run = defaultdict(float)
last_info_run = defaultdict(float)
last_alert_sent = {}
last_telegram_sent_at = 0.0
loop_error_count = 0


# =========================
# 공통 유틸
# =========================

def now_kst():
    return datetime.now(KST)


def now_ts():
    return time.time()


def log(msg):
    print(f"[{now_kst().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


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
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    candles = []
    for item in data:
        candles.append({
            "open_time": item[0],
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5]),
            "close_time": item[6],
        })

    return candles


def get_cached_candles(symbol, interval, limit=200):
    key = f"{symbol}:{interval}:{limit}"
    ttl = CANDLE_TTL.get(interval, 120)
    current = now_ts()

    cached = candle_cache.get(key)

    if cached:
        age = current - cached["ts"]
        if age < ttl:
            return cached["data"]

    candles = fetch_klines(symbol, interval, limit)
    candle_cache[key] = {
        "ts": current,
        "data": candles,
    }

    return candles


def get_current_price(symbol):
    candles = get_cached_candles(symbol, "15m", 100)
    if not candles:
        return None
    return candles[-1]["close"]


# =========================
# 분석 실행 여부 판단
# =========================

def should_skip_by_price_change(symbol, price):
    if price is None:
        return True

    prev = price_cache.get(symbol)

    price_cache[symbol] = {
        "price": price,
        "ts": now_ts(),
    }

    if not prev:
        return False

    prev_price = prev["price"]

    if prev_price <= 0:
        return False

    change_rate = abs(price - prev_price) / prev_price

    return change_rate < PRICE_SKIP_THRESHOLD


def should_run_interval(cache, key, interval_sec):
    current = now_ts()
    last = cache.get(key, 0)

    if current - last >= interval_sec:
        cache[key] = current
        return True

    return False


def should_run_structure(symbol, timeframe):
    key = f"{symbol}:{timeframe}"
    interval = STRUCTURE_INTERVAL.get(timeframe, 900)
    return should_run_interval(last_structure_run, key, interval)


def should_run_entry(symbol):
    return should_run_interval(last_entry_run, symbol, ENTRY_ANALYSIS_INTERVAL_SEC)


def should_run_radar(symbol):
    return should_run_interval(last_radar_run, symbol, RADAR_ANALYSIS_INTERVAL_SEC)


def should_run_info(symbol):
    return should_run_interval(last_info_run, symbol, INFO_ANALYSIS_INTERVAL_SEC)


# =========================
# Telegram 발송 제한
# =========================

def make_alert_key(symbol, alert_type, direction=None):
    direction = direction or "NONE"
    return f"{symbol}:{alert_type}:{direction}"


def should_send_alert(symbol, alert_type, direction=None, cooldown_sec=SAME_ALERT_COOLDOWN_SEC):
    key = make_alert_key(symbol, alert_type, direction)
    current = now_ts()
    last = last_alert_sent.get(key, 0)

    if current - last < cooldown_sec:
        return False

    last_alert_sent[key] = current
    return True


def telegram_send(text):
    global last_telegram_sent_at

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("[WARN] TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID 없음")
        print(text)
        return False

    elapsed = now_ts() - last_telegram_sent_at

    if elapsed < TELEGRAM_MIN_INTERVAL_SEC:
        time.sleep(TELEGRAM_MIN_INTERVAL_SEC - elapsed)

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, data=payload, timeout=10)
        last_telegram_sent_at = now_ts()

        if r.status_code != 200:
            log(f"[TELEGRAM ERROR] {r.status_code} {r.text}")
            return False

        return True

    except Exception as e:
        log(f"[TELEGRAM SEND ERROR] {e}")
        return False


def send_alert_safely(symbol, alert_type, message, direction=None, force=False):
    if not message:
        return False

    if not force:
        if not should_send_alert(symbol, alert_type, direction):
            log(f"[SKIP ALERT] {symbol} {alert_type} {direction} cooldown")
            return False

    return telegram_send(message)


# =========================
# 기존 기능 연결부
# =========================

def run_structure_analysis(symbol, candles_by_tf):
    func = get_func(structure_analyzer, [
        "analyze_structure",
        "run_structure_analysis",
        "fact_based_structure_analysis",
        "analyze",
    ])

    if func is None:
        return None

    return safe_call(
        func,
        symbol,
        candles_by_tf,
        default=None,
        name="structure_analyzer"
    )


def run_entry_timing(symbol, candles_by_tf, structure_result=None):
    func = get_func(entry_timing, [
        "analyze_entry_timing",
        "run_entry_timing",
        "check_entry",
        "analyze",
    ])

    if func is None:
        return None

    try:
        return func(symbol, candles_by_tf, structure_result)
    except TypeError:
        return safe_call(
            func,
            symbol,
            candles_by_tf,
            default=None,
            name="entry_timing"
        )


def run_general_analyzers(symbol, candles_by_tf, structure_result=None):
    results = []

    if analyzers is None:
        return results

    candidate_funcs = [
        "analyze_mungkkul",
        "analyze_candle_god",
        "analyze_dogpig",
        "analyze_info_message",
        "run_all_analyzers",
        "analyze",
    ]

    for fname in candidate_funcs:
        if hasattr(analyzers, fname):
            func = getattr(analyzers, fname)
            try:
                result = func(symbol, candles_by_tf, structure_result)
            except TypeError:
                result = safe_call(
                    func,
                    symbol,
                    candles_by_tf,
                    default=None,
                    name=f"analyzers.{fname}"
                )

            if result:
                results.append(result)

    return results


def record_to_sheet(symbol, event_type, payload):
    if sheets is None:
        return

    func = get_func(sheets, [
        "append_signal",
        "record_signal",
        "write_signal",
        "save_signal",
        "append_row",
    ])

    if func is None:
        return

    safe_call(
        func,
        symbol,
        event_type,
        payload,
        default=None,
        name="sheets"
    )


def record_to_journal(symbol, event_type, payload):
    if signal_journal is None:
        return

    func = get_func(signal_journal, [
        "record",
        "record_signal",
        "append_signal",
        "save",
    ])

    if func is None:
        return

    safe_call(
        func,
        symbol,
        event_type,
        payload,
        default=None,
        name="signal_journal"
    )


# =========================
# 결과 해석 보조
# =========================

def extract_message(result):
    if result is None:
        return None

    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        for key in ["message", "text", "telegram_message", "alert", "summary"]:
            if key in result and result[key]:
                return str(result[key])

    return str(result)


def extract_direction(result):
    if result is None:
        return None

    if isinstance(result, dict):
        for key in ["direction", "side", "entry_side", "signal"]:
            value = result.get(key)
            if value:
                value = str(value).upper()
                if "LONG" in value:
                    return "LONG"
                if "SHORT" in value:
                    return "SHORT"
                if "WAIT" in value:
                    return "WAIT"

    text = str(result).upper()

    if "LONG" in text or "롱" in text:
        return "LONG"

    if "SHORT" in text or "숏" in text:
        return "SHORT"

    if "WAIT" in text or "대기" in text or "박스권" in text:
        return "WAIT"

    return None


def extract_alert_type(result, default_type):
    if isinstance(result, dict):
        for key in ["type", "alert_type", "entry_type", "signal_type"]:
            value = result.get(key)
            if value:
                return str(value).upper()

    text = str(result).upper()

    if "REAL ENTRY" in text:
        return "REAL_ENTRY"
    if "PULLBACK" in text:
        return "PULLBACK_ENTRY"
    if "PRE-ENTRY" in text or "PRE ENTRY" in text:
        return "PRE_ENTRY"
    if "RADAR" in text or "레이더" in text:
        return "RADAR"
    if "WAIT" in text or "박스권" in text:
        return "WAIT"

    return default_type


# =========================
# 심볼별 메인 사이클
# =========================

def collect_candles(symbol):
    return {
        "15m": get_cached_candles(symbol, "15m", 200),
        "1h": get_cached_candles(symbol, "1h", 200),
        "4h": get_cached_candles(symbol, "4h", 200),
        "1d": get_cached_candles(symbol, "1d", 200),
    }


def run_symbol_cycle(symbol):
    log(f"[START] {symbol} cycle")

    price = get_current_price(symbol)

    if price is None:
        log(f"[SKIP] {symbol} price 없음")
        return

    price_skip = should_skip_by_price_change(symbol, price)

    candles_by_tf = collect_candles(symbol)

    structure_result = None

    # 1. 정시 팩트기반구조분석
    for tf in TIMEFRAMES:
        if should_run_structure(symbol, tf):
            log(f"[STRUCTURE] {symbol} {tf}")

            structure_result = run_structure_analysis(symbol, candles_by_tf)

            msg = extract_message(structure_result)
            direction = extract_direction(structure_result)

            if msg:
                send_alert_safely(
                    symbol=symbol,
                    alert_type=f"STRUCTURE_{tf}",
                    message=msg,
                    direction=direction,
                    force=False,
                )

                record_to_sheet(symbol, f"STRUCTURE_{tf}", structure_result)
                record_to_journal(symbol, f"STRUCTURE_{tf}", structure_result)

            break

    # 가격 변화 없으면 진입 분석만 생략
    # 구조 분석, 정시 분석은 위에서 이미 주기 기반으로 처리
    if price_skip:
        log(f"[SKIP ENTRY] {symbol} price change too small")
        return

    # 2. 진입 레이더
    if should_run_radar(symbol):
        radar_func = get_func(entry_timing, [
            "run_entry_radar",
            "entry_radar",
            "analyze_radar",
            "check_radar",
        ])

        radar_result = None

        if radar_func:
            try:
                radar_result = radar_func(symbol, candles_by_tf, structure_result)
            except TypeError:
                radar_result = safe_call(
                    radar_func,
                    symbol,
                    candles_by_tf,
                    default=None,
                    name="entry_radar"
                )

        if radar_result:
            msg = extract_message(radar_result)
            direction = extract_direction(radar_result)

            if msg:
                send_alert_safely(
                    symbol=symbol,
                    alert_type="ENTRY_RADAR",
                    message=msg,
                    direction=direction,
                    force=False,
                )

                record_to_sheet(symbol, "ENTRY_RADAR", radar_result)
                record_to_journal(symbol, "ENTRY_RADAR", radar_result)

    # 3. PRE-ENTRY / PULLBACK ENTRY / REAL ENTRY
    if should_run_entry(symbol):
        entry_result = run_entry_timing(symbol, candles_by_tf, structure_result)

        if entry_result:
            results = entry_result if isinstance(entry_result, list) else [entry_result]

            for result in results:
                msg = extract_message(result)
                direction = extract_direction(result)
                alert_type = extract_alert_type(result, "ENTRY")

                if msg:
                    send_alert_safely(
                        symbol=symbol,
                        alert_type=alert_type,
                        message=msg,
                        direction=direction,
                        force=False,
                    )

                    record_to_sheet(symbol, alert_type, result)
                    record_to_journal(symbol, alert_type, result)

    # 4. 멍꿀, 캔들의신, 개돼지기법, 정보성 메시지 분석
    if should_run_info(symbol):
        analyzer_results = run_general_analyzers(symbol, candles_by_tf, structure_result)

        for result in analyzer_results:
            msg = extract_message(result)
            direction = extract_direction(result)
            alert_type = extract_alert_type(result, "INFO_ANALYSIS")

            if msg:
                send_alert_safely(
                    symbol=symbol,
                    alert_type=alert_type,
                    message=msg,
                    direction=direction,
                    force=False,
                )

                record_to_sheet(symbol, alert_type, result)
                record_to_journal(symbol, alert_type, result)

    log(f"[END] {symbol} cycle")


# =========================
# 스케줄러 호환
# =========================

def run_scheduler_tasks():
    if scheduler is None:
        return

    func = get_func(scheduler, [
        "run_pending",
        "run_scheduler",
        "tick",
        "run",
    ])

    if func:
        safe_call(func, default=None, name="scheduler")


# =========================
# 헬스 체크
# =========================

def send_startup_message():
    msg = (
        "✅ Railway Telegram Trading Bot 시작\n\n"
        "기능 유지:\n"
        "1. ETH/BTC 정시 팩트기반구조분석\n"
        "2. 진입 레이더\n"
        "3. PRE-ENTRY\n"
        "4. PULLBACK ENTRY\n"
        "5. REAL ENTRY\n"
        "6. 롱/숏 양방향 점수 판단\n"
        "7. 박스권 WAIT 처리\n"
        "8. 점수 차이 15% 미만 진입 금지\n"
        "9. 같은 방향 알림 15분 제한\n"
        "10. 멍꿀 급등주 분석\n"
        "11. 캔들의신 관점 해석\n"
        "12. 개돼지기법 분석\n"
        "13. 정보성 메시지 분석\n"
        "14. 구글시트 신호기록\n"
        "15. 무한루프 방지\n\n"
        "최적화:\n"
        "- 캔들 캐싱\n"
        "- API 호출 최소화\n"
        "- 메시지 rate limit\n"
        "- 구조 분석 주기 분리\n"
        "- 가격 변화 없으면 진입 분석 생략\n"
        "- 알림 폭주 방지"
    )

    telegram_send(msg)


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

            for symbol in SYMBOLS:
                run_symbol_cycle(symbol)

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
                msg = (
                    "🚨 Trading Bot 오류 누적 중단 위험\n\n"
                    f"오류 횟수: {loop_error_count}\n"
                    f"에러: {e}\n\n"
                    "무한루프 방지를 위해 긴 대기 후 재시도합니다."
                )
                telegram_send(msg)
                time.sleep(120)
                loop_error_count = 0
            else:
                time.sleep(10)


if __name__ == "__main__":
    main_loop()
