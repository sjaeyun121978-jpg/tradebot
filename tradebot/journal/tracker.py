"""
tracker.py
오픈 신호 추적 엔진

역할:
  - OPEN 상태 신호 읽기
  - created_at + 15M/1H/4H/24H 경과 여부 확인
  - 캔들 high/low 기준 result 업데이트
  - MFE/MAE 갱신
  - TP1/TP2/SL 도달 판정
  - EXPIRE 처리
"""

from datetime import datetime, timezone, timedelta

from tradebot.journal.storage import (
    get_open_signals, update_signal, load_signals, save_signals,
)
from tradebot.journal.evaluator import evaluate_tp_sl, detect_first_hit, evaluate_final_status
from tradebot.journal.metrics import (
    safe_float, calc_return_pct, calc_mfe_mae, update_max_min,
)

KST = timezone(timedelta(hours=9))


def _now_kst() -> datetime:
    return datetime.now(KST)


def _now_str() -> str:
    return _now_kst().strftime("%Y-%m-%d %H:%M:%S")


def _parse_dt(s: str):
    """created_at 문자열 → datetime 파싱. 실패 시 None."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def should_update_horizon(created_at_str: str, horizon: str) -> bool:
    """
    created_at 기준으로 horizon 경과 여부 확인

    horizon: "15M" / "1H" / "4H" / "24H"
    """
    created = _parse_dt(created_at_str)
    if not created:
        return False

    delta_map = {
        "15M": timedelta(minutes=15),
        "1H":  timedelta(hours=1),
        "4H":  timedelta(hours=4),
        "24H": timedelta(hours=24),
    }
    delta = delta_map.get(horizon.upper())
    if not delta:
        return False

    return _now_kst() >= created + delta


def update_signal_result(row: dict, candles: list, current_price: float = 0) -> dict:
    """
    단일 신호 행 업데이트

    candles: 신호 이후 캔들 (15m 기준)
    반환: updates dict
    """
    updates = {}
    direction   = str(row.get("direction", "WAIT")).upper()
    entry_price = safe_float(row.get("entry_price"))
    created_at  = row.get("created_at", "")

    if entry_price <= 0:
        return updates

    # ── 1. result_15M/1H/4H/24H 기록 ─────────────
    from tradebot.config import settings

    price_now = current_price if current_price > 0 else safe_float(row.get("price_at_signal"))

    if settings.JOURNAL_TRACK_15M and should_update_horizon(created_at, "15M"):
        if not row.get("result_15m"):
            ret = calc_return_pct(direction, entry_price, price_now)
            updates["result_15m"] = str(round(ret, 4))

    if settings.JOURNAL_TRACK_1H and should_update_horizon(created_at, "1H"):
        if not row.get("result_1h"):
            ret = calc_return_pct(direction, entry_price, price_now)
            updates["result_1h"] = str(round(ret, 4))

    if settings.JOURNAL_TRACK_4H and should_update_horizon(created_at, "4H"):
        if not row.get("result_4h"):
            ret = calc_return_pct(direction, entry_price, price_now)
            updates["result_4h"] = str(round(ret, 4))

    if settings.JOURNAL_TRACK_24H and should_update_horizon(created_at, "24H"):
        if not row.get("result_24h"):
            ret = calc_return_pct(direction, entry_price, price_now)
            updates["result_24h"] = str(round(ret, 4))

    # ── 2. TP/SL 판정 ─────────────────────────────
    tp_sl_updates = evaluate_tp_sl(row, candles)
    updates.update(tp_sl_updates)

    # max/min 병합 후 MFE/MAE 계산
    merged_row = {**row, **updates}
    max_p = safe_float(merged_row.get("max_price_after_signal"), entry_price)
    min_p = safe_float(merged_row.get("min_price_after_signal"), entry_price)

    mfe, mae = calc_mfe_mae(direction, entry_price, max_p, min_p)
    updates["mfe"] = str(mfe)
    updates["mae"] = str(mae)

    # ── 3. first_hit 판정 ─────────────────────────
    updates["first_hit"] = detect_first_hit(merged_row)

    # ── 4. final_status 판정 ─────────────────────
    updated_final = evaluate_final_status(merged_row)
    updates["final_status"] = updated_final

    # ── 5. EXPIRE 체크 ────────────────────────────
    expire_hours = getattr(settings, "JOURNAL_EXPIRE_HOURS", 24)
    if should_update_horizon(created_at, f"{expire_hours * 1}H".replace("1H", "24H")):
        # 24H 초과 + 아직 OPEN이면 EXPIRED 또는 NO_TOUCH
        if updated_final == "OPEN":
            tp1_hit = str(merged_row.get("tp1_hit", "False")).lower() == "true"
            sl_hit  = str(merged_row.get("sl_hit",  "False")).lower() == "true"
            updates["final_status"] = "NO_TOUCH" if not tp1_hit and not sl_hit else updated_final

    return updates


def update_open_signals(
    candles_by_symbol: dict = None,
    price_fetcher=None,
) -> int:
    """
    OPEN 상태 신호 전체 업데이트 메인 함수

    candles_by_symbol: {symbol: candles_by_tf dict} (jobs.py all_candles 형태)
    price_fetcher:     symbol → float 함수

    반환: 업데이트된 신호 수
    """
    try:
        open_signals = get_open_signals()
        if not open_signals:
            return 0

        updated_count = 0
        all_rows = load_signals()
        rows_map = {r.get("signal_id", ""): r for r in all_rows}

        for row in open_signals:
            sid    = row.get("signal_id", "")
            symbol = row.get("symbol", "")

            if not sid:
                continue

            # 캔들 가져오기
            candles = []
            if candles_by_symbol and symbol in candles_by_symbol:
                tf_data = candles_by_symbol[symbol]
                if isinstance(tf_data, dict):
                    candles = tf_data.get("15m", []) or tf_data.get("1h", []) or []
                elif isinstance(tf_data, list):
                    candles = tf_data

            # 현재가 가져오기
            current_price = 0.0
            if price_fetcher:
                try:
                    current_price = float(price_fetcher(symbol) or 0)
                except Exception:
                    pass

            updates = update_signal_result(row, candles, current_price)

            if updates:
                if sid in rows_map:
                    rows_map[sid].update({
                        k: v for k, v in updates.items() if k in rows_map[sid]
                    })
                    rows_map[sid]["updated_at"] = _now_str()
                updated_count += 1

        if updated_count > 0:
            save_signals(list(rows_map.values()))

        return updated_count

    except Exception as e:
        print(f"[JOURNAL TRACKER] update_open_signals 실패: {e}", flush=True)
        return 0
