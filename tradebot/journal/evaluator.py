"""
evaluator.py
TP / SL 도달 여부 판정 엔진

역할: 캔들 high/low 기준으로 TP1/TP2/SL 도달 판정.
      순수 계산만 담당. 저장은 storage.py가 처리.
"""

from datetime import datetime, timezone, timedelta
from tradebot.journal.metrics import safe_float

KST = timezone(timedelta(hours=9))


def _now_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def evaluate_tp_sl(row: dict, candles: list) -> dict:
    """
    캔들 리스트 기준 TP1/TP2/SL 도달 여부 판정

    판정 기준:
      LONG:
        TP1 hit: candle high >= tp1
        TP2 hit: candle high >= tp2
        SL  hit: candle low  <= stop_price
      SHORT:
        TP1 hit: candle low  <= tp1
        TP2 hit: candle low  <= tp2
        SL  hit: candle high >= stop_price

    같은 캔들에서 TP와 SL 동시 → 보수적으로 SL_FIRST 처리

    반환: dict (업데이트할 필드들)
    """
    direction   = str(row.get("direction", "WAIT")).upper()
    entry_price = safe_float(row.get("entry_price"))
    stop_price  = safe_float(row.get("stop_price"))
    tp1         = safe_float(row.get("tp1"))
    tp2         = safe_float(row.get("tp2"))

    updates = {}

    # WAIT 또는 BLOCKED는 TP/SL 판정 안 함
    final_status = str(row.get("final_status", "OPEN")).upper()
    if final_status in ("WAIT_ONLY", "BLOCKED", "EXPIRED"):
        return updates

    if direction not in ("LONG", "SHORT"):
        return updates
    if entry_price <= 0 or stop_price <= 0 or tp1 <= 0:
        return updates

    tp1_hit = str(row.get("tp1_hit", "False")).lower() == "true"
    tp2_hit = str(row.get("tp2_hit", "False")).lower() == "true"
    sl_hit  = str(row.get("sl_hit",  "False")).lower() == "true"

    # 이미 모두 판정 완료면 skip
    if tp1_hit and sl_hit:
        return updates

    max_price = safe_float(row.get("max_price_after_signal"), entry_price)
    min_price = safe_float(row.get("min_price_after_signal"), entry_price)

    for candle in (candles or []):
        c_high = safe_float(candle.get("high"))
        c_low  = safe_float(candle.get("low"))
        c_time = str(candle.get("open_time", ""))

        if c_high <= 0 or c_low <= 0:
            continue

        # max/min 갱신
        max_price = max(max_price, c_high)
        min_price = min(min_price, c_low)

        if direction == "LONG":
            _tp1 = c_high >= tp1 if tp1 > 0 else False
            _tp2 = c_high >= tp2 if tp2 > 0 else False
            _sl  = c_low  <= stop_price

            # 같은 캔들에서 SL + TP1 동시 → SL 우선
            if _sl and _tp1 and not sl_hit:
                if not sl_hit:
                    updates["sl_hit"]    = "True"
                    updates["sl_hit_at"] = c_time
                    sl_hit = True
            else:
                if _tp1 and not tp1_hit:
                    updates["tp1_hit"]    = "True"
                    updates["tp1_hit_at"] = c_time
                    tp1_hit = True
                if _tp2 and not tp2_hit:
                    updates["tp2_hit"]    = "True"
                    updates["tp2_hit_at"] = c_time
                    tp2_hit = True
                if _sl and not sl_hit:
                    updates["sl_hit"]    = "True"
                    updates["sl_hit_at"] = c_time
                    sl_hit = True

        elif direction == "SHORT":
            _tp1 = c_low  <= tp1 if tp1 > 0 else False
            _tp2 = c_low  <= tp2 if tp2 > 0 else False
            _sl  = c_high >= stop_price

            if _sl and _tp1 and not sl_hit:
                if not sl_hit:
                    updates["sl_hit"]    = "True"
                    updates["sl_hit_at"] = c_time
                    sl_hit = True
            else:
                if _tp1 and not tp1_hit:
                    updates["tp1_hit"]    = "True"
                    updates["tp1_hit_at"] = c_time
                    tp1_hit = True
                if _tp2 and not tp2_hit:
                    updates["tp2_hit"]    = "True"
                    updates["tp2_hit_at"] = c_time
                    tp2_hit = True
                if _sl and not sl_hit:
                    updates["sl_hit"]    = "True"
                    updates["sl_hit_at"] = c_time
                    sl_hit = True

    updates["max_price_after_signal"] = str(max_price)
    updates["min_price_after_signal"] = str(min_price)

    return updates


def detect_first_hit(row: dict) -> str:
    """
    first_hit 판정:
      TP1_FIRST / TP2_FIRST / SL_FIRST / NONE

    hit_at 시간 비교 기준.
    시간 없으면 hit 여부만으로 판정.
    """
    tp1_hit = str(row.get("tp1_hit", "False")).lower() == "true"
    tp2_hit = str(row.get("tp2_hit", "False")).lower() == "true"
    sl_hit  = str(row.get("sl_hit",  "False")).lower() == "true"

    if not tp1_hit and not tp2_hit and not sl_hit:
        return "NONE"

    tp1_at = str(row.get("tp1_hit_at", ""))
    tp2_at = str(row.get("tp2_hit_at", ""))
    sl_at  = str(row.get("sl_hit_at",  ""))

    # 시간 비교 가능한 경우
    hit_times = {}
    if tp1_hit and tp1_at:
        hit_times["TP1_FIRST"] = tp1_at
    if tp2_hit and tp2_at:
        hit_times["TP2_FIRST"] = tp2_at
    if sl_hit and sl_at:
        hit_times["SL_FIRST"]  = sl_at

    if hit_times:
        return min(hit_times, key=lambda k: hit_times[k])

    # 시간 없으면 SL 우선 보수적 처리
    if sl_hit:
        return "SL_FIRST"
    if tp1_hit:
        return "TP1_FIRST"
    if tp2_hit:
        return "TP2_FIRST"
    return "NONE"


def evaluate_final_status(row: dict) -> str:
    """
    final_status 판정

    WAIT_ONLY  - trade_allowed=False + direction=WAIT
    BLOCKED    - trade_allowed=False + direction!=WAIT
    TP2_HIT    - tp2 도달
    TP1_HIT    - tp1 도달
    SL_HIT     - sl 도달
    EXPIRED    - 24H 초과 미판정
    NO_TOUCH   - 24H 경과했으나 TP/SL 미도달
    OPEN       - 아직 추적 중
    """
    current = str(row.get("final_status", "OPEN")).upper()

    # 이미 확정된 상태면 그대로
    if current in ("WAIT_ONLY", "BLOCKED", "EXPIRED"):
        return current

    trade_allowed = str(row.get("trade_allowed", "True")).lower() in ("true", "1")
    direction     = str(row.get("direction", "WAIT")).upper()

    if not trade_allowed:
        return "WAIT_ONLY" if direction == "WAIT" else "BLOCKED"

    tp1_hit = str(row.get("tp1_hit", "False")).lower() == "true"
    tp2_hit = str(row.get("tp2_hit", "False")).lower() == "true"
    sl_hit  = str(row.get("sl_hit",  "False")).lower() == "true"

    first_hit = detect_first_hit(row)

    if first_hit == "SL_FIRST":
        return "SL_HIT"
    if first_hit == "TP2_FIRST":
        return "TP2_HIT"
    if first_hit == "TP1_FIRST":
        return "TP1_HIT"

    # 단독 판정
    if sl_hit:
        return "SL_HIT"
    if tp2_hit:
        return "TP2_HIT"
    if tp1_hit:
        return "TP1_HIT"

    return current  # OPEN 유지
