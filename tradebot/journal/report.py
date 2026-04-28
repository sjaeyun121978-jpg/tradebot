"""
report.py
복기 통계 리포트 생성

역할:
  - signals.csv 기반 집계
  - 전체/심볼별/방향별/시장상태별/RR구간별 통계
  - journal_summary.csv 저장
  - 텔레그램용 요약 메시지 생성
"""

import csv
import os
from datetime import datetime, timezone, timedelta
from tradebot.journal.storage import load_signals
from tradebot.journal.metrics import safe_float

KST = timezone(timedelta(hours=9))

SUMMARY_COLUMNS = [
    "generated_at",
    "total_signals",
    "long_count",
    "short_count",
    "wait_count",
    "blocked_count",
    "open_count",
    "tp1_hit_count",
    "tp2_hit_count",
    "sl_hit_count",
    "no_touch_count",
    "tp1_hit_rate",
    "tp2_hit_rate",
    "sl_hit_rate",
    "avg_mfe",
    "avg_mae",
    "avg_rr",
    "best_symbol",
    "worst_symbol",
    "best_market_state",
    "worst_market_state",
]


def _now_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def _get_summary_path() -> str:
    from tradebot.config import settings
    journal_dir  = getattr(settings, "JOURNAL_DIR",          "data/journal")
    summary_file = getattr(settings, "JOURNAL_SUMMARY_FILE", "journal_summary.csv")
    return os.path.join(journal_dir, summary_file)


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator * 100, 2)


def _avg(values: list) -> float:
    vals = [safe_float(v) for v in values if v is not None and str(v) != ""]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def build_summary() -> dict:
    """
    전체 통계 집계
    """
    rows = load_signals()
    if not rows:
        return {}

    total    = len(rows)
    long_c   = sum(1 for r in rows if str(r.get("direction", "")).upper() == "LONG")
    short_c  = sum(1 for r in rows if str(r.get("direction", "")).upper() == "SHORT")
    wait_c   = sum(1 for r in rows if str(r.get("final_status", "")).upper() == "WAIT_ONLY")
    blocked_c = sum(1 for r in rows if str(r.get("final_status", "")).upper() == "BLOCKED")
    open_c   = sum(1 for r in rows if str(r.get("final_status", "")).upper() == "OPEN")
    tp1_c    = sum(1 for r in rows if str(r.get("tp1_hit", "False")).lower() == "true")
    tp2_c    = sum(1 for r in rows if str(r.get("tp2_hit", "False")).lower() == "true")
    sl_c     = sum(1 for r in rows if str(r.get("sl_hit",  "False")).lower() == "true")
    nt_c     = sum(1 for r in rows if str(r.get("final_status", "")).upper() == "NO_TOUCH")

    # 실제 진입 신호 기준 (trade_allowed=True)
    tradeable = [r for r in rows if str(r.get("trade_allowed", "True")).lower() in ("true", "1")]
    tradeable_c = len(tradeable)

    mfe_vals = [r.get("mfe") for r in tradeable if r.get("mfe") != ""]
    mae_vals = [r.get("mae") for r in tradeable if r.get("mae") != ""]
    rr_vals  = [r.get("rr")  for r in tradeable if r.get("rr")  != ""]

    return {
        "generated_at":    _now_str(),
        "total_signals":   total,
        "long_count":      long_c,
        "short_count":     short_c,
        "wait_count":      wait_c,
        "blocked_count":   blocked_c,
        "open_count":      open_c,
        "tp1_hit_count":   tp1_c,
        "tp2_hit_count":   tp2_c,
        "sl_hit_count":    sl_c,
        "no_touch_count":  nt_c,
        "tp1_hit_rate":    _rate(tp1_c, tradeable_c),
        "tp2_hit_rate":    _rate(tp2_c, tradeable_c),
        "sl_hit_rate":     _rate(sl_c,  tradeable_c),
        "avg_mfe":         _avg(mfe_vals),
        "avg_mae":         _avg(mae_vals),
        "avg_rr":          _avg(rr_vals),
    }


def build_summary_by_symbol() -> dict:
    """심볼별 통계"""
    rows = load_signals()
    result = {}
    for r in rows:
        sym = str(r.get("symbol", "UNKNOWN")).upper()
        if sym not in result:
            result[sym] = {"total": 0, "tp1": 0, "sl": 0, "rr_vals": []}
        result[sym]["total"] += 1
        if str(r.get("tp1_hit", "False")).lower() == "true":
            result[sym]["tp1"] += 1
        if str(r.get("sl_hit", "False")).lower() == "true":
            result[sym]["sl"] += 1
        if r.get("rr"):
            result[sym]["rr_vals"].append(r["rr"])

    for sym in result:
        t = result[sym]["total"]
        result[sym]["tp1_rate"] = _rate(result[sym]["tp1"], t)
        result[sym]["sl_rate"]  = _rate(result[sym]["sl"],  t)
        result[sym]["avg_rr"]   = _avg(result[sym]["rr_vals"])

    return result


def build_summary_by_direction() -> dict:
    """방향별 통계"""
    rows   = load_signals()
    result = {}
    for r in rows:
        d = str(r.get("direction", "WAIT")).upper()
        if d not in result:
            result[d] = {"total": 0, "tp1": 0, "sl": 0}
        result[d]["total"] += 1
        if str(r.get("tp1_hit", "False")).lower() == "true":
            result[d]["tp1"] += 1
        if str(r.get("sl_hit", "False")).lower() == "true":
            result[d]["sl"] += 1
    for d in result:
        t = result[d]["total"]
        result[d]["tp1_rate"] = _rate(result[d]["tp1"], t)
        result[d]["sl_rate"]  = _rate(result[d]["sl"],  t)
    return result


def build_summary_by_market_state() -> dict:
    """시장상태별 통계"""
    rows   = load_signals()
    result = {}
    for r in rows:
        ms = str(r.get("market_state", "UNKNOWN")).upper()
        if ms not in result:
            result[ms] = {"total": 0, "tp1": 0, "sl": 0, "blocked": 0}
        result[ms]["total"] += 1
        if str(r.get("tp1_hit", "False")).lower() == "true":
            result[ms]["tp1"] += 1
        if str(r.get("sl_hit", "False")).lower() == "true":
            result[ms]["sl"] += 1
        if str(r.get("final_status", "")).upper() == "BLOCKED":
            result[ms]["blocked"] += 1
    for ms in result:
        t = result[ms]["total"]
        result[ms]["tp1_rate"] = _rate(result[ms]["tp1"], t)
        result[ms]["sl_rate"]  = _rate(result[ms]["sl"],  t)
    return result


def build_summary_by_rr_bucket() -> dict:
    """
    RR 구간별 통계
    < 1 / 1~1.5 / 1.5~2 / >= 2
    """
    rows   = load_signals()
    buckets = {
        "RR_lt_1":    {"total": 0, "tp1": 0, "sl": 0},
        "RR_1_to_15": {"total": 0, "tp1": 0, "sl": 0},
        "RR_15_to_2": {"total": 0, "tp1": 0, "sl": 0},
        "RR_gte_2":   {"total": 0, "tp1": 0, "sl": 0},
    }
    for r in rows:
        rr = safe_float(r.get("rr"))
        if rr < 1:
            key = "RR_lt_1"
        elif rr < 1.5:
            key = "RR_1_to_15"
        elif rr < 2:
            key = "RR_15_to_2"
        else:
            key = "RR_gte_2"
        buckets[key]["total"] += 1
        if str(r.get("tp1_hit", "False")).lower() == "true":
            buckets[key]["tp1"] += 1
        if str(r.get("sl_hit", "False")).lower() == "true":
            buckets[key]["sl"] += 1
    for k in buckets:
        t = buckets[k]["total"]
        buckets[k]["tp1_rate"] = _rate(buckets[k]["tp1"], t)
        buckets[k]["sl_rate"]  = _rate(buckets[k]["sl"],  t)
    return buckets


def save_summary_csv() -> bool:
    """journal_summary.csv 저장"""
    try:
        from tradebot.journal.storage import ensure_journal_dir
        ensure_journal_dir()

        summary      = build_summary()
        by_symbol    = build_summary_by_symbol()
        by_direction = build_summary_by_direction()
        by_ms        = build_summary_by_market_state()
        by_rr        = build_summary_by_rr_bucket()

        # best/worst symbol
        sym_stats = {s: d for s, d in by_symbol.items() if d["total"] >= 3}
        best_sym  = max(sym_stats, key=lambda s: sym_stats[s]["tp1_rate"], default="")
        worst_sym = min(sym_stats, key=lambda s: sym_stats[s]["tp1_rate"], default="")
        best_ms   = max(by_ms,     key=lambda s: by_ms[s]["tp1_rate"],     default="")
        worst_ms  = min(by_ms,     key=lambda s: by_ms[s]["tp1_rate"],     default="")

        summary["best_symbol"]       = best_sym
        summary["worst_symbol"]      = worst_sym
        summary["best_market_state"] = best_ms
        summary["worst_market_state"] = worst_ms

        summary_path = _get_summary_path()
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerow({col: summary.get(col, "") for col in SUMMARY_COLUMNS})

        # Google Sheets summary 탭 동기화
        try:
            from tradebot.journal.sheets import safe_write_summary
            safe_write_summary(summary)
        except Exception as _se:
            print(f'[JOURNAL SHEETS] save_summary_csv sync 실패: {_se}', flush=True)

        return True
    except Exception as e:
        print(f"[JOURNAL REPORT] save_summary_csv 실패: {e}", flush=True)
        return False


def format_report_message() -> str:
    """텔레그램용 요약 메시지"""
    try:
        summary   = build_summary()
        by_symbol = build_summary_by_symbol()
        by_ms     = build_summary_by_market_state()
        by_rr     = build_summary_by_rr_bucket()

        if not summary:
            return "📊 복기 데이터 없음"

        total    = summary.get("total_signals", 0)
        tp1_rate = summary.get("tp1_hit_rate",  0)
        sl_rate  = summary.get("sl_hit_rate",   0)
        avg_mfe  = summary.get("avg_mfe",       0)
        avg_mae  = summary.get("avg_mae",       0)
        avg_rr   = summary.get("avg_rr",        0)
        blocked  = summary.get("blocked_count", 0)
        wait_c   = summary.get("wait_count",    0)

        # 심볼별 요약
        sym_lines = []
        for sym, d in by_symbol.items():
            sym_lines.append(f"  {sym}: {d['total']}건 TP1율 {d['tp1_rate']}% SL율 {d['sl_rate']}%")

        # 시장상태별
        ms_lines = []
        for ms, d in by_ms.items():
            ms_lines.append(f"  {ms}: {d['total']}건 TP1율 {d['tp1_rate']}%")

        # RR 구간별
        rr_lines = []
        for bucket, d in by_rr.items():
            rr_lines.append(f"  {bucket}: {d['total']}건 TP1율 {d['tp1_rate']}%")

        return (
            f"📊 복기 통계 리포트\n"
            f"{'─'*28}\n"
            f"총 신호: {total}건\n"
            f"  └ WAIT: {wait_c}건 / BLOCKED: {blocked}건\n"
            f"TP1 도달: {tp1_rate}% / SL 도달: {sl_rate}%\n"
            f"평균 MFE: {avg_mfe:+.2f}% / MAE: {avg_mae:+.2f}%\n"
            f"평균 RR: {avg_rr:.2f}\n\n"
            f"심볼별:\n" + "\n".join(sym_lines) + "\n\n"
            f"시장상태별:\n" + "\n".join(ms_lines) + "\n\n"
            f"RR 구간별:\n" + "\n".join(rr_lines) + "\n\n"
            f"생성: {summary.get('generated_at', '-')}"
        )
    except Exception as e:
        return f"📊 복기 리포트 생성 실패: {e}"
