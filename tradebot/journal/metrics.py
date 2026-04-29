"""
metrics.py
수익률 / MFE / MAE / RR 계산 엔진

역할: 순수 계산만 담당. 외부 의존성 없음.
"""


def safe_float(value, default=0.0):
    """안전한 float 변환"""
    if value is None or value == "" or value == "None":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def calc_return_pct(direction: str, entry_price: float, current_price: float) -> float:
    """
    방향 기반 수익률 계산 (%)

    LONG:  (current - entry) / entry * 100
    SHORT: (entry - current) / entry * 100
    """
    entry   = safe_float(entry_price)
    current = safe_float(current_price)
    if entry <= 0:
        return 0.0
    if str(direction).upper() == "LONG":
        return (current - entry) / entry * 100
    elif str(direction).upper() == "SHORT":
        return (entry - current) / entry * 100
    return 0.0


def calc_mfe_mae(
    direction:   str,
    entry_price: float,
    max_price:   float,
    min_price:   float,
) -> tuple:
    """
    MFE (Maximum Favorable Excursion) / MAE (Maximum Adverse Excursion) 계산

    반환: (mfe_pct, mae_pct)
      mfe: 신호 이후 최대 유리한 방향 이동 (%)
      mae: 신호 이후 최대 불리한 방향 이동 (%)

    LONG:
      MFE = (max_price - entry) / entry * 100  (양수: 유리)
      MAE = (min_price - entry) / entry * 100  (음수: 불리)

    SHORT:
      MFE = (entry - min_price) / entry * 100  (양수: 유리)
      MAE = (entry - max_price) / entry * 100  (음수: 불리)
    """
    entry = safe_float(entry_price)
    hi    = safe_float(max_price)
    lo    = safe_float(min_price)

    if entry <= 0:
        return 0.0, 0.0

    direction = str(direction).upper()
    if direction == "LONG":
        mfe = (hi - entry) / entry * 100 if hi > 0 else 0.0
        mae = (lo - entry) / entry * 100 if lo > 0 else 0.0
    elif direction == "SHORT":
        mfe = (entry - lo) / entry * 100 if lo > 0 else 0.0
        mae = (entry - hi) / entry * 100 if hi > 0 else 0.0
    else:
        return 0.0, 0.0

    return round(mfe, 4), round(mae, 4)


def calc_rr(
    entry_price: float,
    stop_price:  float,
    tp1:         float,
    direction:   str,
) -> float:
    """
    손익비 계산

    RR = reward / risk
    risk가 0이면 0 반환
    """
    entry = safe_float(entry_price)
    stop  = safe_float(stop_price)
    tp    = safe_float(tp1)

    if entry <= 0:
        return 0.0

    risk   = abs(entry - stop)
    reward = abs(tp - entry)

    if risk == 0:
        return 0.0

    return round(reward / risk, 4)


def update_max_min(
    direction:          str,
    entry_price:        float,
    current_high:       float,
    current_low:        float,
    prev_max:           float,
    prev_min:           float,
) -> tuple:
    """
    누적 max_price / min_price 갱신

    반환: (new_max, new_min)
    """
    hi = safe_float(current_high)
    lo = safe_float(current_low)
    mx = safe_float(prev_max, default=safe_float(entry_price))
    mn = safe_float(prev_min, default=safe_float(entry_price))

    new_max = max(mx, hi) if hi > 0 else mx
    new_min = min(mn, lo) if lo > 0 else mn

    return round(new_max, 6), round(new_min, 6)
