"""
report_engine.py
STEP 자동 복기 결과 기반 승률 리포트 + 오답 패턴 분석 엔진

입력: tradebot/logs/step_log.json (reviewed=True 항목)
출력: 텔레그램 텍스트 리포트 / step_report.json
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

BASE_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR         = os.path.join(BASE_DIR, "logs")
STEP_LOG_PATH   = os.path.join(LOG_DIR, "step_log.json")
REPORT_PATH     = os.path.join(LOG_DIR, "step_report.json")


# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────

def _load_json(path: str, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _safe_pct(a: int, b: int) -> float:
    return round(a / b * 100, 1) if b else 0.0


def _norm(v, default: str = "UNKNOWN") -> str:
    if v is None or str(v).strip() == "":
        return default
    return str(v)


def _parse_ts(v) -> float | None:
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return v / 1000.0 if v > 10_000_000_000 else float(v)
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None
    return None


def _is_success(e: dict) -> bool:
    return _norm(e.get("result_label")).upper() == "SUCCESS"


def _is_fail(e: dict) -> bool:
    return _norm(e.get("result_label")).upper() == "FAIL"


def _is_neutral(e: dict) -> bool:
    return _norm(e.get("result_label")).upper() == "NEUTRAL"


# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────

def load_reviewed_entries(
    symbol: str | None = None,
    hours:  int | None = None,
) -> list[dict]:
    """
    reviewed=True 인 STEP 로그를 로드한다.
    symbol / hours 필터 적용 가능.
    """
    rows = _load_json(STEP_LOG_PATH, [])
    if not isinstance(rows, list):
        return []

    now_ts = datetime.now(KST).timestamp()
    out = []

    for e in rows:
        if not e.get("reviewed"):
            continue
        if e.get("result_label") in (None, "SKIP"):
            continue
        if symbol and e.get("symbol") != symbol:
            continue
        if hours:
            ts = _parse_ts(e.get("timestamp"))
            if ts and now_ts - ts > hours * 3600:
                continue
        out.append(e)

    return out


# ─────────────────────────────────────────────
# 승률 집계
# ─────────────────────────────────────────────

def summarize_winrate(entries: list[dict]) -> dict:
    """STEP / 방향 / 심볼 기준 승률 집계"""
    total   = len(entries)
    success = sum(1 for e in entries if _is_success(e))
    fail    = sum(1 for e in entries if _is_fail(e))
    neutral = sum(1 for e in entries if _is_neutral(e))

    by_step:     dict = defaultdict(lambda: {"total":0,"success":0,"fail":0,"neutral":0})
    by_step_dir: dict = defaultdict(lambda: {"total":0,"success":0,"fail":0,"neutral":0})
    by_symbol:   dict = defaultdict(lambda: {"total":0,"success":0,"fail":0,"neutral":0})

    for e in entries:
        step    = _norm(e.get("step"))
        direc   = _norm(e.get("direction"))
        sym     = _norm(e.get("symbol"))

        for bucket in [by_step[step], by_step_dir[(step, direc)], by_symbol[sym]]:
            bucket["total"] += 1
            if _is_success(e): bucket["success"] += 1
            elif _is_fail(e):  bucket["fail"]    += 1
            else:              bucket["neutral"]  += 1

    # 승률 계산 (성공+실패 기준, 중립 제외)
    for d in list(by_step.values()) + list(by_step_dir.values()) + list(by_symbol.values()):
        sf = d["success"] + d["fail"]
        d["winrate"] = _safe_pct(d["success"], sf)

    return {
        "total":              total,
        "success":            success,
        "fail":               fail,
        "neutral":            neutral,
        "winrate":            _safe_pct(success, success + fail),
        "success_rate_all":   _safe_pct(success, total),
        "fail_rate_all":      _safe_pct(fail,    total),
        "neutral_rate_all":   _safe_pct(neutral, total),
        "by_step":            dict(by_step),
        "by_step_dir":        {f"{k[0]}_{k[1]}": v for k, v in by_step_dir.items()},
        "by_symbol":          dict(by_symbol),
    }


# ─────────────────────────────────────────────
# 오답 패턴 분석
# ─────────────────────────────────────────────

def analyze_failure_patterns(entries: list[dict]) -> dict:
    """FAIL 항목에서 오답 패턴 자동 집계"""
    fails = [e for e in entries if _is_fail(e)]
    if not fails:
        return {
            "fail_total": 0,
            "fail_by_step": [], "fail_by_step_direction": [],
            "fail_by_market_state": [], "fail_by_block_reason": [],
            "fail_by_reversal_stage": [], "fail_by_score_band": [],
            "fail_by_symbol": [], "worst_entries": [],
        }

    c_step        = Counter()
    c_step_dir    = Counter()
    c_market      = Counter()
    c_block       = Counter()
    c_rev_stage   = Counter()
    c_score_band  = Counter()
    c_symbol      = Counter()

    for e in fails:
        step      = _norm(e.get("step"))
        direc     = _norm(e.get("direction"))
        market    = _norm(e.get("market_state"))
        block     = _norm(e.get("block_reason"), "차단없음")[:50]
        rev_stage = _norm(e.get("reversal_stage"))
        sym       = _norm(e.get("symbol"))

        try:
            score = float(e.get("reversal_score") or 0)
            band  = f"{int(score//10)*10}-{int(score//10)*10+9}"
        except Exception:
            band = "UNKNOWN"

        c_step[step]              += 1
        c_step_dir[(step, direc)] += 1
        c_market[market]          += 1
        c_block[block]            += 1
        c_rev_stage[rev_stage]    += 1
        c_score_band[band]        += 1
        c_symbol[sym]             += 1

    # 최악 항목 TOP5 (result_pct 오름차순)
    worst = sorted(
        fails,
        key=lambda x: float(x.get("result_adv_pct") or x.get("result_pct") or 0)
    )[:5]
    worst_entries = [
        {
            "ts":             e.get("timestamp"),
            "symbol":         e.get("symbol"),
            "step":           e.get("step"),
            "direction":      e.get("direction"),
            "price":          e.get("price"),
            "result_pct":     e.get("result_pct"),
            "reversal_stage": e.get("reversal_stage"),
            "reversal_score": e.get("reversal_score"),
            "market_state":   e.get("market_state"),
        }
        for e in worst
    ]

    return {
        "fail_total":                len(fails),
        "fail_by_step":              c_step.most_common(10),
        "fail_by_step_direction":    [(f"{k[0]}_{k[1]}", v) for k, v in c_step_dir.most_common(10)],
        "fail_by_market_state":      c_market.most_common(10),
        "fail_by_block_reason":      c_block.most_common(10),
        "fail_by_reversal_stage":    c_rev_stage.most_common(10),
        "fail_by_score_band":        c_score_band.most_common(10),
        "fail_by_symbol":            c_symbol.most_common(10),
        "worst_entries":             worst_entries,
    }


# ─────────────────────────────────────────────
# 리포트 텍스트 생성
# ─────────────────────────────────────────────

def _fmt_group(title: str, data: dict) -> str:
    lines = [title]
    if not data:
        lines.append("  - 데이터 없음")
        return "\n".join(lines)
    for k, v in data.items():
        t  = v.get("total", 0)
        s  = v.get("success", 0)
        f  = v.get("fail",    0)
        n  = v.get("neutral", 0)
        wr = v.get("winrate", 0.0)
        lines.append(f"  {k}: {t}건  ✓{s} ✗{f} ={n}  승률 {wr}%")
    return "\n".join(lines)


def _add_counter(lines: list, label: str, rows: list, top: int = 5):
    lines.append(label)
    if not rows:
        lines.append("  - 없음")
        return
    for k, v in rows[:top]:
        lines.append(f"  · {k}: {v}건")


def build_report_text(symbol: str | None = None, hours: int = 24) -> str:
    """텔레그램 발송용 텍스트 리포트 생성"""
    entries = load_reviewed_entries(symbol=symbol, hours=hours)
    summary = summarize_winrate(entries)
    fail    = analyze_failure_patterns(entries)

    lbl = symbol or "전체"
    lines = [
        f"📊 STEP 자동 복기 리포트",
        f"대상: {lbl}  |  기간: 최근 {hours}시간",
        "",
        "[ 전체 성과 ]",
        f"복기 완료: {summary['total']}건",
        f"성공 {summary['success']} / 실패 {summary['fail']} / 중립 {summary['neutral']}",
        f"실전 승률: {summary['winrate']}%  (중립 제외)",
        f"전체 성공률: {summary['success_rate_all']}%",
        "",
    ]

    # STEP별 승률 테이블
    step_order = ["REAL", "PRE", "EARLY", "WAIT"]
    lines.append("[ STEP별 승률 ]")
    by_step = summary["by_step"]
    for s in step_order:
        if s in by_step:
            v = by_step[s]
            lines.append(f"  {s:6s}  {v['total']:3d}건  "
                         f"✓{v['success']} ✗{v['fail']} ={v['neutral']}  "
                         f"{v['winrate']}%")
    lines.append("")

    # 방향별 세분화
    lines.append("[ STEP + 방향별 승률 ]")
    for combo, v in sorted(summary["by_step_dir"].items()):
        lines.append(f"  {combo:16s}  {v['total']:3d}건  "
                     f"✓{v['success']} ✗{v['fail']}  {v['winrate']}%")
    lines.append("")

    # 오답 패턴
    lines.append("[ 오답 패턴 TOP5 ]")
    if fail["fail_total"] == 0:
        lines.append("  실패 데이터 없음")
    else:
        lines.append(f"  실패 총 {fail['fail_total']}건")
        _add_counter(lines, "  ① STEP별",       fail["fail_by_step"])
        _add_counter(lines, "  ② STEP+방향별",   fail["fail_by_step_direction"])
        _add_counter(lines, "  ③ 시장상태별",     fail["fail_by_market_state"])
        _add_counter(lines, "  ④ 점수대별",       fail["fail_by_score_band"])
        _add_counter(lines, "  ⑤ 차단사유별",     fail["fail_by_block_reason"])

        # 최악 사례
        if fail.get("worst_entries"):
            lines.append("  [ 최악 사례 ]")
            for w in fail["worst_entries"][:3]:
                lines.append(
                    f"  · {w.get('symbol')} {w.get('step')} {w.get('direction')} "
                    f"rev:{w.get('reversal_stage','?')} {w.get('reversal_score','?')}pt "
                    f"→ {w.get('result_pct', 0):+.2f}%"
                )
    lines.append("")

    # 판정
    lines.append("[ 판정 ]")
    if summary["total"] < 30:
        lines.append(f"  표본 부족 ({summary['total']}건 < 30건 기준)")
    elif summary["winrate"] >= 60:
        lines.append("  현재 조건 유지 가능")
    elif summary["winrate"] >= 50:
        lines.append("  조건 미세조정 필요")
    else:
        lines.append("  조건 재설계 필요")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# JSON 저장
# ─────────────────────────────────────────────

def save_report_json(symbol: str | None = None, hours: int = 24) -> tuple[str, dict]:
    """리포트 원본 데이터를 JSON으로 저장"""
    entries = load_reviewed_entries(symbol=symbol, hours=hours)
    data = {
        "created_at": datetime.now(KST).isoformat(),
        "symbol":     symbol or "ALL",
        "hours":      hours,
        "summary":    summarize_winrate(entries),
        "failure_patterns": analyze_failure_patterns(entries),
    }
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return REPORT_PATH, data
