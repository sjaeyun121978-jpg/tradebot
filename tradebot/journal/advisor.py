"""
journal/advisor.py
전략 어드바이저 엔진

역할:
  - signals.csv 기반 세그먼트별 성능 분석
  - 자동 추천 문구 생성 (적용 X, 제안만)
  - 전략 파라미터 제안 JSON 저장
  - 텍스트 리포트 생성

설계 원칙:
  - 읽기 전용: 매매 규칙 자동 변경 절대 없음
  - 모든 오류는 try/except로 메인 루프 보호
  - ENABLE_JOURNAL=false면 즉시 종료
"""

import csv
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def _now_kst() -> datetime:
    return datetime.now(KST)


def _now_str() -> str:
    return _now_kst().strftime("%Y-%m-%d %H:%M:%S")


def _safe_float(v, d=0.0) -> float:
    try:
        return float(v) if v not in (None, "", "None") else d
    except Exception:
        return d


def _rate(n: int, d: int) -> float:
    return round(n / d, 4) if d > 0 else 0.0


def _get_settings():
    from tradebot.config import settings
    return settings


# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────

def load_signals(path: str = None) -> list:
    """
    signals.csv 로드
    path 미지정 시 settings.JOURNAL_DIR/JOURNAL_SIGNAL_FILE 사용
    """
    if not path:
        s    = _get_settings()
        path = os.path.join(
            getattr(s, "JOURNAL_DIR",         "data/journal"),
            getattr(s, "JOURNAL_SIGNAL_FILE", "signals.csv"),
        )
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(r) for r in reader]
    except Exception as e:
        print(f"[ADVISOR] load_signals 실패: {e}", flush=True)
        return []


def filter_min_samples(rows: list, min_n: int = None) -> list:
    """표본 수 체크용 — 실제 필터링은 세그먼트별로 함"""
    if min_n is None:
        s     = _get_settings()
        min_n = getattr(s, "ADVISOR_MIN_SIGNALS", 50)
    return rows  # 전체 반환, 세그먼트에서 insufficient 처리


def split_recent(rows: list, days: int = None) -> tuple:
    """
    최근 N일 / 전체 분리

    반환: (recent_rows, all_rows)
    """
    if days is None:
        s    = _get_settings()
        days = getattr(s, "ADVISOR_RECENT_DAYS", 7)

    cutoff = _now_kst() - timedelta(days=days)
    recent = []
    for r in rows:
        try:
            dt_str = r.get("created_at", "")
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = datetime.strptime(dt_str, fmt).replace(tzinfo=KST)
                    if dt >= cutoff:
                        recent.append(r)
                    break
                except ValueError:
                    continue
        except Exception:
            continue

    return recent, rows


# ─────────────────────────────────────────────
# 지표 계산
# ─────────────────────────────────────────────

def _is_tradeable(row: dict) -> bool:
    """실제 진입 신호 (WAIT/BLOCKED 제외)"""
    status = str(row.get("final_status", "")).upper()
    if status in ("WAIT_ONLY", "BLOCKED"):
        return False
    ta = str(row.get("trade_allowed", "True")).lower()
    return ta in ("true", "1")


def calc_winrate(rows: list, direction: str = None) -> float:
    """TP1_HIT 이상을 성공으로 간주. WAIT/BLOCKED 제외."""
    filtered = [r for r in rows if _is_tradeable(r)]
    if direction:
        filtered = [r for r in filtered if str(r.get("direction", "")).upper() == direction.upper()]
    if not filtered:
        return 0.0
    wins = sum(
        1 for r in filtered
        if str(r.get("tp1_hit", "False")).lower() == "true" or
           str(r.get("final_status", "")).upper() in ("TP1_HIT", "TP2_HIT")
    )
    return _rate(wins, len(filtered))


def calc_tp1_rate(rows: list) -> float:
    """TP1 도달률 (전체 대상)"""
    tradeable = [r for r in rows if _is_tradeable(r)]
    if not tradeable:
        return 0.0
    hits = sum(1 for r in tradeable if str(r.get("tp1_hit", "False")).lower() == "true")
    return _rate(hits, len(tradeable))


def calc_sl_rate(rows: list) -> float:
    """SL 비율 (전체 대상)"""
    tradeable = [r for r in rows if _is_tradeable(r)]
    if not tradeable:
        return 0.0
    hits = sum(1 for r in tradeable if str(r.get("sl_hit", "False")).lower() == "true")
    return _rate(hits, len(tradeable))


def calc_tp2_rate(rows: list) -> float:
    tradeable = [r for r in rows if _is_tradeable(r)]
    if not tradeable:
        return 0.0
    hits = sum(1 for r in tradeable if str(r.get("tp2_hit", "False")).lower() == "true")
    return _rate(hits, len(tradeable))


def calc_avg_mfe(rows: list) -> float:
    vals = [_safe_float(r.get("mfe")) for r in rows if r.get("mfe") not in ("", None)]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def calc_avg_mae(rows: list) -> float:
    vals = [_safe_float(r.get("mae")) for r in rows if r.get("mae") not in ("", None)]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def calc_avg_rr(rows: list) -> float:
    vals = [_safe_float(r.get("rr")) for r in rows if r.get("rr") not in ("", None)]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def _segment_stats(rows: list, label: str, min_n: int = 5) -> dict:
    """단일 세그먼트 통계"""
    total      = len(rows)
    tradeable  = [r for r in rows if _is_tradeable(r)]
    wait_c     = sum(1 for r in rows if str(r.get("final_status", "")).upper() == "WAIT_ONLY")
    blocked_c  = sum(1 for r in rows if str(r.get("final_status", "")).upper() == "BLOCKED")
    open_c     = sum(1 for r in rows if str(r.get("final_status", "")).upper() == "OPEN")

    if len(tradeable) < min_n:
        return {
            "label":       label,
            "total":       total,
            "tradeable":   len(tradeable),
            "wait":        wait_c,
            "blocked":     blocked_c,
            "open":        open_c,
            "insufficient": True,
        }

    return {
        "label":       label,
        "total":       total,
        "tradeable":   len(tradeable),
        "wait":        wait_c,
        "blocked":     blocked_c,
        "open":        open_c,
        "winrate":     calc_winrate(rows),
        "tp1_rate":    calc_tp1_rate(rows),
        "tp2_rate":    calc_tp2_rate(rows),
        "sl_rate":     calc_sl_rate(rows),
        "avg_mfe":     calc_avg_mfe(tradeable),
        "avg_mae":     calc_avg_mae(tradeable),
        "avg_rr":      calc_avg_rr(tradeable),
        "insufficient": False,
    }


# ─────────────────────────────────────────────
# 그룹핑
# ─────────────────────────────────────────────

def group_by(rows: list, key: str) -> dict:
    """key 필드 기준으로 그룹핑"""
    result = {}
    for r in rows:
        val = str(r.get(key, "UNKNOWN")).upper()
        result.setdefault(val, []).append(r)
    return result


def bucket_by_rr(rows: list) -> dict:
    """RR 구간별 그룹핑"""
    buckets = {"<1": [], "1-1.5": [], "1.5-2": [], ">=2": []}
    for r in rows:
        rr = _safe_float(r.get("rr"))
        if rr < 1:
            buckets["<1"].append(r)
        elif rr < 1.5:
            buckets["1-1.5"].append(r)
        elif rr < 2:
            buckets["1.5-2"].append(r)
        else:
            buckets[">=2"].append(r)
    return buckets


# ─────────────────────────────────────────────
# 세그먼트 요약
# ─────────────────────────────────────────────

def summarize_segments(rows: list) -> dict:
    """
    전체 세그먼트 통계 산출

    반환:
    {
      "global": {...},
      "by_direction": {"LONG": {...}, "SHORT": {...}},
      "by_market_state": {"TREND_UP": {...}, "RANGE": {...}, ...},
      "by_rr": {"<1": {...}, "1-1.5": {...}, ...},
      "by_card_type": {"ENTRY_RADAR": {...}, ...},
    }
    """
    s     = _get_settings()
    min_n = max(3, getattr(s, "ADVISOR_MIN_SIGNALS", 50) // 10)

    # 전체
    global_stats = _segment_stats(rows, "GLOBAL", min_n=5)

    # 방향별
    dir_groups = group_by(rows, "direction")
    by_dir = {}
    for d in ("LONG", "SHORT", "WAIT"):
        grp = dir_groups.get(d, [])
        by_dir[d] = _segment_stats(grp, d, min_n=min_n)

    # 시장상태별
    ms_groups = group_by(rows, "market_state")
    by_ms = {}
    for ms, grp in ms_groups.items():
        by_ms[ms] = _segment_stats(grp, ms, min_n=min_n)

    # RR 구간별
    rr_buckets = bucket_by_rr(rows)
    by_rr = {}
    for bucket, grp in rr_buckets.items():
        by_rr[bucket] = _segment_stats(grp, bucket, min_n=min_n)

    # 카드타입별
    ct_groups = group_by(rows, "card_type")
    by_ct = {}
    for ct, grp in ct_groups.items():
        by_ct[ct] = _segment_stats(grp, ct, min_n=min_n)

    return {
        "global":          global_stats,
        "by_direction":    by_dir,
        "by_market_state": by_ms,
        "by_rr":           by_rr,
        "by_card_type":    by_ct,
        "sample_size":     len(rows),
        "generated_at":    _now_str(),
    }


# ─────────────────────────────────────────────
# 추천 로직
# ─────────────────────────────────────────────

def build_recommendations(stats: dict) -> list:
    """
    세그먼트 통계 기반 추천 문구 생성
    자동교정 아님 — 제안만
    """
    s     = _get_settings()
    recs  = []

    long_wr  = getattr(s, "THRESH_LONG_WINRATE_LOW",  0.45)
    short_wr = getattr(s, "THRESH_SHORT_WINRATE_LOW", 0.45)
    range_sl = getattr(s, "THRESH_RANGE_SL_HIGH",     0.50)
    thresh_rr = getattr(s, "THRESH_LOW_RR",           1.5)
    tp1_good  = getattr(s, "THRESH_TP1_RATE_GOOD",    0.55)

    # 1. LONG 약세
    long_stats = stats.get("by_direction", {}).get("LONG", {})
    if not long_stats.get("insufficient") and long_stats.get("tradeable", 0) >= 5:
        if long_stats.get("winrate", 1.0) < long_wr:
            recs.append(
                f"⚠️ LONG 조건 강화 필요 — 승률 {long_stats['winrate']*100:.1f}% (기준 {long_wr*100:.0f}%)"
            )

    # 2. SHORT 약세
    short_stats = stats.get("by_direction", {}).get("SHORT", {})
    if not short_stats.get("insufficient") and short_stats.get("tradeable", 0) >= 5:
        if short_stats.get("winrate", 1.0) < short_wr:
            recs.append(
                f"⚠️ SHORT 조건 강화 필요 — 승률 {short_stats['winrate']*100:.1f}% (기준 {short_wr*100:.0f}%)"
            )

    # 3. RANGE 구간 SL 높음
    for ms_key in ("RANGE", "RANGE_UP", "RANGE_DOWN"):
        ms_stats = stats.get("by_market_state", {}).get(ms_key, {})
        if not ms_stats.get("insufficient") and ms_stats.get("tradeable", 0) >= 3:
            if ms_stats.get("sl_rate", 0.0) > range_sl:
                recs.append(
                    f"⚠️ {ms_key} 구간 진입금지 강화 필요 — SL {ms_stats['sl_rate']*100:.1f}%"
                )

    # 4. RR < 1.5 구간 손실 집중
    for bucket in ("<1", "1-1.5"):
        rr_stats = stats.get("by_rr", {}).get(bucket, {})
        if not rr_stats.get("insufficient") and rr_stats.get("tradeable", 0) >= 3:
            if rr_stats.get("sl_rate", 0.0) > 0.5:
                recs.append(
                    f"⚠️ RR {bucket} 구간 손실 집중 (SL {rr_stats['sl_rate']*100:.1f}%) → RR {thresh_rr} 이상 유지 권장"
                )

    # 5. TP1 도달률 양호
    global_stats = stats.get("global", {})
    if not global_stats.get("insufficient"):
        if global_stats.get("tp1_rate", 0.0) > tp1_good:
            recs.append(
                f"✅ TP1 도달률 양호 ({global_stats['tp1_rate']*100:.1f}%) → 부분 익절 전략 유효"
            )

    # 6. WAIT/BLOCKED 비율 높음 → 진입금지 필터 정상
    total      = global_stats.get("total", 1)
    wait_c     = global_stats.get("wait",    0)
    blocked_c  = global_stats.get("blocked", 0)
    if total > 0 and (wait_c + blocked_c) / total > 0.40:
        recs.append(
            f"✅ WAIT/BLOCKED 비율 {(wait_c+blocked_c)/total*100:.1f}% — 진입금지 필터 정상 작동 가능성"
        )

    # 7. TREND 구간 TP1 양호
    for ms_key in ("TREND_UP", "TREND_DOWN", "TREND"):
        ms_stats = stats.get("by_market_state", {}).get(ms_key, {})
        if not ms_stats.get("insufficient") and ms_stats.get("tradeable", 0) >= 3:
            if ms_stats.get("tp1_rate", 0.0) >= tp1_good:
                recs.append(
                    f"✅ {ms_key} 구간 TP1 도달률 양호 ({ms_stats['tp1_rate']*100:.1f}%) — 추세장 전략 유효"
                )

    if not recs:
        recs.append("📊 현재 데이터 기준 특이 사항 없음 — 데이터 축적 후 재검토 권장")

    return recs


# ─────────────────────────────────────────────
# 전략 파라미터 제안
# ─────────────────────────────────────────────

def build_strategy_suggestions(stats: dict) -> dict:
    """
    전략 파라미터 제안 JSON 생성
    적용 X — 제안 파일로만 저장
    """
    s          = _get_settings()
    suggestions = {}
    reasons     = []

    long_wr  = getattr(s, "THRESH_LONG_WINRATE_LOW",  0.45)
    short_wr = getattr(s, "THRESH_SHORT_WINRATE_LOW", 0.45)
    range_sl = getattr(s, "THRESH_RANGE_SL_HIGH",     0.50)
    tp1_good  = getattr(s, "THRESH_TP1_RATE_GOOD",    0.55)

    # LONG 강화 여부
    long_stats = stats.get("by_direction", {}).get("LONG", {})
    strengthen_long = (
        not long_stats.get("insufficient") and
        long_stats.get("winrate", 1.0) < long_wr
    )
    if strengthen_long:
        reasons.append(f"LONG 승률 {long_stats.get('winrate', 0)*100:.1f}%로 기준 미달")

    # SHORT 강화 여부
    short_stats = stats.get("by_direction", {}).get("SHORT", {})
    strengthen_short = (
        not short_stats.get("insufficient") and
        short_stats.get("winrate", 1.0) < short_wr
    )
    if strengthen_short:
        reasons.append(f"SHORT 승률 {short_stats.get('winrate', 0)*100:.1f}%로 기준 미달")

    # RANGE 차단 강화
    range_stats  = stats.get("by_market_state", {}).get("RANGE", {})
    block_range  = (
        not range_stats.get("insufficient") and
        range_stats.get("sl_rate", 0.0) > range_sl
    )
    if block_range:
        reasons.append(f"RANGE 구간 SL {range_stats.get('sl_rate', 0)*100:.1f}%")

    # RR 기준 상향
    rr_lt15   = stats.get("by_rr", {}).get("<1", {})
    rr_1_15   = stats.get("by_rr", {}).get("1-1.5", {})
    raise_rr   = False
    min_rr_suggest = 1.5
    if (not rr_lt15.get("insufficient") and rr_lt15.get("sl_rate", 0) > 0.5):
        raise_rr = True
        min_rr_suggest = 1.8
        reasons.append("RR<1.0 구간 손실 집중")
    if (not rr_1_15.get("insufficient") and rr_1_15.get("sl_rate", 0) > 0.5):
        raise_rr = True
        min_rr_suggest = max(min_rr_suggest, 1.8)
        reasons.append("RR 1.0~1.5 구간 손실 집중")

    # TP1 기반 부분 익절 유효
    global_stats    = stats.get("global", {})
    partial_tp_valid = (
        not global_stats.get("insufficient") and
        global_stats.get("tp1_rate", 0.0) > tp1_good
    )

    suggestions["strengthen_long_filter"]  = strengthen_long
    suggestions["strengthen_short_filter"] = strengthen_short
    suggestions["block_range"]             = block_range
    suggestions["raise_rr_threshold"]      = raise_rr
    suggestions["min_rr"]                  = min_rr_suggest
    suggestions["use_partial_tp"]          = partial_tp_valid

    if not reasons:
        reasons.append("현재 기준 특이 사항 없음")

    return {
        "suggested_changes": suggestions,
        "reason":            reasons,
        "generated_at":      _now_str(),
        "note":              "⚠️ 이 파일은 제안만 합니다. 실제 매매 규칙은 수동으로 적용하세요.",
    }


# ─────────────────────────────────────────────
# 파일 저장
# ─────────────────────────────────────────────

def _get_advisor_dir() -> str:
    s = _get_settings()
    return getattr(s, "JOURNAL_DIR", "data/journal")


def save_advisor_json(payload: dict) -> bool:
    """data/journal/advisor_latest.json 저장"""
    try:
        d    = _get_advisor_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "advisor_latest.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[ADVISOR] save_advisor_json 실패: {e}", flush=True)
        return False


def save_advisor_history(payload: dict) -> bool:
    """data/journal/advisor_history.csv에 이력 append"""
    try:
        import csv as csv_mod
        d    = _get_advisor_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "advisor_history.csv")
        write_header = not os.path.exists(path)

        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv_mod.writer(f)
            if write_header:
                writer.writerow(["generated_at", "sample_size", "summary_json"])
            writer.writerow([
                payload.get("generated_at", _now_str()),
                payload.get("sample_size", 0),
                json.dumps(payload.get("suggestions", {}), ensure_ascii=False),
            ])
        return True
    except Exception as e:
        print(f"[ADVISOR] save_advisor_history 실패: {e}", flush=True)
        return False


# ─────────────────────────────────────────────
# 리포트 텍스트 생성
# ─────────────────────────────────────────────

def _pct(v, decimals=1) -> str:
    try:
        return f"{float(v)*100:.{decimals}f}%"
    except Exception:
        return "-"


def build_text_report(stats: dict, recs: list) -> str:
    """텔레그램용 전략 리포트 텍스트"""
    try:
        s            = _get_settings()
        recent_days  = getattr(s, "ADVISOR_RECENT_DAYS", 7)
        global_st    = stats.get("global", {})
        by_dir       = stats.get("by_direction", {})
        by_ms        = stats.get("by_market_state", {})
        by_rr        = stats.get("by_rr", {})

        total    = global_st.get("total", 0)
        long_c   = by_dir.get("LONG",  {}).get("total", 0)
        short_c  = by_dir.get("SHORT", {}).get("total", 0)
        wait_c   = global_st.get("wait",    0)
        blocked_c = global_st.get("blocked", 0)

        long_wr  = by_dir.get("LONG",  {}).get("winrate")
        short_wr = by_dir.get("SHORT", {}).get("winrate")
        tp1_rate = global_st.get("tp1_rate")
        sl_rate  = global_st.get("sl_rate")

        # 취약 구간
        weak_lines = []
        for ms, d in by_ms.items():
            if d.get("insufficient"):
                continue
            if d.get("sl_rate", 0) > 0.4:
                weak_lines.append(f"  - {ms}: SL {_pct(d['sl_rate'])}")
        for bucket, d in by_rr.items():
            if d.get("insufficient"):
                continue
            if d.get("sl_rate", 0) > 0.4:
                weak_lines.append(f"  - RR{bucket}: SL {_pct(d['sl_rate'])}")

        # 양호 구간
        good_lines = []
        for ms, d in by_ms.items():
            if d.get("insufficient"):
                continue
            if d.get("tp1_rate", 0) >= 0.55:
                good_lines.append(f"  - {ms}: TP1 {_pct(d['tp1_rate'])}")
        for bucket, d in by_rr.items():
            if d.get("insufficient"):
                continue
            if d.get("tp1_rate", 0) >= 0.55:
                good_lines.append(f"  - RR{bucket}: TP1 {_pct(d['tp1_rate'])}")

        recs_txt = "\n".join(f"  {r}" for r in recs) if recs else "  특이 사항 없음"
        weak_txt = "\n".join(weak_lines) if weak_lines else "  없음"
        good_txt = "\n".join(good_lines) if good_lines else "  없음"

        now_str  = _now_kst().strftime("%Y-%m-%d %H:%M KST")

        return (
            f"📊 전략 리포트 (최근 {recent_days}일)\n"
            f"{'─'*30}\n"
            f"기준: {now_str}\n"
            f"표본: {total}건 (총 누적)\n\n"
            f"LONG: {long_c}건 / SHORT: {short_c}건\n"
            f"WAIT: {wait_c}건 / BLOCKED: {blocked_c}건\n\n"
            f"LONG 승률:  {_pct(long_wr)  if long_wr  is not None else '데이터 부족'}\n"
            f"SHORT 승률: {_pct(short_wr) if short_wr is not None else '데이터 부족'}\n\n"
            f"TP1 도달률: {_pct(tp1_rate) if tp1_rate is not None else '-'}\n"
            f"SL 비율:    {_pct(sl_rate)  if sl_rate  is not None else '-'}\n\n"
            f"📉 취약 구간\n{weak_txt}\n\n"
            f"📈 양호 구간\n{good_txt}\n\n"
            f"🧠 전략 추천\n{recs_txt}\n\n"
            f"※ 자동교정 아님. 수동 반영 필요."
        )
    except Exception as e:
        return f"📊 전략 리포트 생성 실패: {e}"


# ─────────────────────────────────────────────
# 메인 진입점
# ─────────────────────────────────────────────

def run_advisor() -> dict:
    """
    어드바이저 메인 실행 함수

    반환:
    {
      "text":    str,     # 텔레그램 리포트 텍스트
      "json":    dict,    # 전략 제안 JSON
      "stats":   dict,    # 세그먼트 통계
      "recs":    list,    # 추천 문구
    }
    """
    try:
        from tradebot.config import settings
        if not getattr(settings, "ENABLE_JOURNAL", False):
            return {"text": "[ADVISOR] ENABLE_JOURNAL=false", "json": {}, "stats": {}, "recs": []}

        # 1. 데이터 로드
        all_rows = load_signals()
        if not all_rows:
            return {
                "text":  "📊 전략 리포트\n\n신호 데이터 없음 (signals.csv 비어 있음)",
                "json":  {},
                "stats": {},
                "recs":  [],
            }

        min_n = getattr(settings, "ADVISOR_MIN_SIGNALS", 50)
        days  = getattr(settings, "ADVISOR_RECENT_DAYS",  7)

        # 2. 최근/전체 분리
        recent_rows, all_rows = split_recent(all_rows, days)

        # 표본 충분 여부 (최근 우선, 부족하면 전체)
        working_rows = recent_rows if len(recent_rows) >= 10 else all_rows

        if len(working_rows) < 5:
            return {
                "text":  f"📊 전략 리포트\n\n표본 부족 ({len(working_rows)}건) — 신호 {min_n}건 이상 쌓인 후 재시도",
                "json":  {},
                "stats": {},
                "recs":  [],
            }

        # 3. 세그먼트 분석
        stats = summarize_segments(working_rows)
        stats["sample_size"] = len(working_rows)
        stats["using_recent"] = len(recent_rows) >= 10

        # 4. 추천 생성
        recs = build_recommendations(stats)

        # 5. 전략 제안 JSON
        suggestions = build_strategy_suggestions(stats)

        # 6. JSON 저장
        save_payload = {
            "stats":        stats,
            "suggestions":  suggestions,
            "recs":         recs,
            "generated_at": _now_str(),
            "sample_size":  len(working_rows),
        }
        save_advisor_json(save_payload)
        save_advisor_history(save_payload)

        # 7. 텍스트 리포트
        text = build_text_report(stats, recs)

        return {
            "text":  text,
            "json":  suggestions,
            "stats": stats,
            "recs":  recs,
        }

    except Exception as e:
        print(f"[ADVISOR] run_advisor 실패: {e}", flush=True)
        return {
            "text":  f"📊 전략 리포트 오류: {e}",
            "json":  {},
            "stats": {},
            "recs":  [],
        }
