"""
tuning_engine.py
2~3일 누적 STEP 복기 데이터 기반 튜닝 추천 엔진

핵심 원칙:
- 매매 조건을 자동으로 수정하지 않는다
- 추천 리포트만 생성한다
- 실제 조건 변경은 사람이 검토 후 별도 반영한다
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

BASE_DIR          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR           = os.path.join(BASE_DIR, "logs")
STEP_LOG_PATH     = os.path.join(LOG_DIR, "step_log.json")
TUNING_REPORT_PATH = os.path.join(LOG_DIR, "tuning_report.json")

# ── 판정 임계값 (읽기 전용, 코드가 자동 변경 금지)
MIN_SAMPLE_TOTAL  = 50
MIN_STEP_SAMPLE   = 10
BAD_WINRATE       = 45.0
WARN_WINRATE      = 55.0


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


def _write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_ts(v) -> float | None:
    try:
        if not v:
            return None
        if isinstance(v, (int, float)):
            return v / 1000.0 if v > 10_000_000_000 else float(v)
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None
    return None


def _safe_pct(a: int, b: int) -> float:
    return round(a / b * 100, 1) if b else 0.0


def _norm(v, default: str = "UNKNOWN") -> str:
    if v is None or str(v).strip() == "":
        return default
    return str(v)


def _is_success(e: dict) -> bool:
    return _norm(e.get("result_label")).upper() == "SUCCESS"


def _is_fail(e: dict) -> bool:
    return _norm(e.get("result_label")).upper() == "FAIL"


def _is_neutral(e: dict) -> bool:
    return _norm(e.get("result_label")).upper() == "NEUTRAL"


def _bucket_score(score) -> str:
    try:
        s = float(score or 0)
        return f"{int(s // 10) * 10}-{int(s // 10) * 10 + 9}"
    except Exception:
        return "UNKNOWN"


def _bucket_volume(v) -> str:
    try:
        x = float(v or 0)
        if x <= 0:    return "UNKNOWN"
        if x < 0.7:   return "LOW"
        if x < 1.2:   return "NORMAL"
        return "HIGH"
    except Exception:
        return "UNKNOWN"


# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────

def load_reviewed_entries(hours: int = 72) -> list[dict]:
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
        ts = _parse_ts(e.get("timestamp"))
        if hours and ts and now_ts - ts > hours * 3600:
            continue
        out.append(e)
    return out


# ─────────────────────────────────────────────
# 그룹별 집계
# ─────────────────────────────────────────────

def summarize_group(entries: list[dict], key_func) -> dict:
    stat: dict = defaultdict(lambda: {"total":0, "success":0, "fail":0, "neutral":0})
    for e in entries:
        k = key_func(e)
        stat[k]["total"] += 1
        if _is_success(e):   stat[k]["success"] += 1
        elif _is_fail(e):    stat[k]["fail"]    += 1
        elif _is_neutral(e): stat[k]["neutral"] += 1

    result = {}
    for k, v in stat.items():
        sf = v["success"] + v["fail"]
        v["winrate"]      = _safe_pct(v["success"], sf)
        v["failrate_all"] = _safe_pct(v["fail"], v["total"])
        result[str(k)] = v
    return result


# ─────────────────────────────────────────────
# 튜닝 추천 생성 (추천만, 자동 변경 금지)
# ─────────────────────────────────────────────

def build_tuning_recommendations(entries: list[dict]) -> dict:
    """
    2~3일 데이터 기반 튜닝 추천 생성.
    실제 코드를 바꾸지 않고 추천만 생성한다.
    """
    total = len(entries)

    by_step        = summarize_group(entries, lambda e: _norm(e.get("step")))
    by_step_dir    = summarize_group(entries, lambda e: f"{_norm(e.get('step'))}_{_norm(e.get('direction'))}")
    by_market      = summarize_group(entries, lambda e: _norm(e.get("market_state")))
    by_stage       = summarize_group(entries, lambda e: _norm(e.get("reversal_stage")))
    by_score       = summarize_group(entries, lambda e: _bucket_score(e.get("reversal_score")))
    by_volume      = summarize_group(entries, lambda e: _bucket_volume(e.get("volume_ratio")))
    by_trend4h     = summarize_group(entries, lambda e: _norm(e.get("trend_4h")))

    fails = [e for e in entries if _is_fail(e)]

    fail_counter = {
        "step_dir":       Counter(),
        "market_state":   Counter(),
        "reversal_stage": Counter(),
        "score_band":     Counter(),
        "volume_band":    Counter(),
        "trend_4h":       Counter(),
        "block_reason":   Counter(),
    }
    for e in fails:
        fail_counter["step_dir"      ][f"{_norm(e.get('step'))}_{_norm(e.get('direction'))}"] += 1
        fail_counter["market_state"  ][_norm(e.get("market_state"))]                           += 1
        fail_counter["reversal_stage"][_norm(e.get("reversal_stage"))]                         += 1
        fail_counter["score_band"    ][_bucket_score(e.get("reversal_score"))]                 += 1
        fail_counter["volume_band"   ][_bucket_volume(e.get("volume_ratio"))]                  += 1
        fail_counter["trend_4h"      ][_norm(e.get("trend_4h"))]                               += 1
        fail_counter["block_reason"  ][_norm(e.get("block_reason"), "NO_BLOCK_REASON")[:60]]   += 1

    recommendations: list[dict] = []

    # 표본 부족
    if total < MIN_SAMPLE_TOTAL:
        recommendations.append({
            "level":  "WAIT",
            "target": "DATA",
            "reason": f"표본 부족: {total}건 / 최소 {MIN_SAMPLE_TOTAL}건 필요",
            "action": "조건 튜닝 금지. 데이터만 추가 수집.",
        })

    # STEP+방향별 승률
    for k, v in by_step_dir.items():
        if v["total"] < MIN_STEP_SAMPLE:
            continue
        if v["winrate"] < BAD_WINRATE:
            recommendations.append({
                "level":  "HIGH",
                "target": k,
                "reason": f"승률 {v['winrate']}%, 표본 {v['total']}건",
                "action": "해당 STEP+방향 조건 강화 또는 발송 제한 검토",
            })
        elif v["winrate"] < WARN_WINRATE:
            recommendations.append({
                "level":  "MEDIUM",
                "target": k,
                "reason": f"승률 {v['winrate']}%, 표본 {v['total']}건",
                "action": "점수 기준 또는 거래량 기준 미세조정 검토",
            })

    # 저거래량 구간
    low_vol = by_volume.get("LOW")
    if low_vol and low_vol["total"] >= MIN_STEP_SAMPLE and low_vol["winrate"] < WARN_WINRATE:
        recommendations.append({
            "level":  "HIGH",
            "target": "LOW_VOLUME",
            "reason": f"저거래량 구간 승률 {low_vol['winrate']}%, 표본 {low_vol['total']}건",
            "action": "LOW_VOLUME 구간 EARLY/PRE 발송 제한 또는 점수 기준 상향",
        })

    # 시장상태별
    for k, v in by_market.items():
        if v["total"] >= MIN_STEP_SAMPLE and v["winrate"] < BAD_WINRATE:
            recommendations.append({
                "level":  "HIGH",
                "target": f"MARKET_STATE_{k}",
                "reason": f"{k} 시장상태 승률 {v['winrate']}%, 표본 {v['total']}건",
                "action": "해당 시장상태에서 PRE/REAL 조건 강화 검토",
            })

    # 4H 추세별
    for k, v in by_trend4h.items():
        if v["total"] >= MIN_STEP_SAMPLE and v["winrate"] < BAD_WINRATE:
            recommendations.append({
                "level":  "MEDIUM",
                "target": f"TREND_4H_{k}",
                "reason": f"4H 추세 {k} 구간 승률 {v['winrate']}%, 표본 {v['total']}건",
                "action": "4H 역추세 REAL 제한 기준 재검토",
            })

    return {
        "created_at":         datetime.now(KST).isoformat(),
        "lookback_hours":     72,
        "sample_total":       total,
        "by_step":            by_step,
        "by_step_direction":  by_step_dir,
        "by_market_state":    by_market,
        "by_reversal_stage":  by_stage,
        "by_score_band":      by_score,
        "by_volume_band":     by_volume,
        "by_trend_4h":        by_trend4h,
        "fail_top": {
            k: v.most_common(10) for k, v in fail_counter.items()
        },
        "recommendations": recommendations,
    }


# ─────────────────────────────────────────────
# 리포트 텍스트 생성
# ─────────────────────────────────────────────

def build_tuning_text(hours: int = 72) -> str:
    entries = load_reviewed_entries(hours=hours)
    data    = build_tuning_recommendations(entries)

    lines = [
        "🧪 STEP 조건 튜닝 리포트",
        f"기간: 최근 {hours}시간",
        f"표본: {data['sample_total']}건",
        "",
        "[ STEP+방향별 성과 ]",
    ]

    if not data["by_step_direction"]:
        lines.append("  - 데이터 없음")
    else:
        for k, v in sorted(data["by_step_direction"].items()):
            lines.append(
                f"  {k}: {v['total']}건  "
                f"✓{v['success']} ✗{v['fail']} ={v['neutral']}  "
                f"승률 {v['winrate']}%"
            )

    lines.append("")
    lines.append("[ 실패 TOP ]")

    labels = {
        "step_dir":       "STEP+방향",
        "market_state":   "시장상태",
        "reversal_stage": "변곡단계",
        "score_band":     "점수대",
        "volume_band":    "거래량대",
        "trend_4h":       "4H추세",
        "block_reason":   "차단사유",
    }
    for key, label in labels.items():
        rows = data["fail_top"].get(key) or []
        if rows:
            lines.append(f"  [{label}]")
            for k, v in rows[:5]:
                lines.append(f"    · {k}: {v}건")

    lines.append("")
    lines.append("[ 튜닝 추천 ]")
    recs = data["recommendations"]
    if not recs:
        lines.append("  현재 데이터 기준 즉시 수정 권고 없음")
    else:
        for r in recs:
            lines.append(f"  [{r['level']}] {r['target']}")
            lines.append(f"    사유: {r['reason']}")
            lines.append(f"    조치: {r['action']}")

    lines += [
        "",
        "[ 운영 원칙 ]",
        "  이 리포트는 조건 변경 추천만 제공한다.",
        "  조건 자동 변경 금지.",
        "  최소 50건 미만에서는 튜닝 금지.",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────
# JSON 저장
# ─────────────────────────────────────────────

def save_tuning_report(hours: int = 72) -> tuple[str, dict]:
    entries = load_reviewed_entries(hours=hours)
    data    = build_tuning_recommendations(entries)
    _write_json(TUNING_REPORT_PATH, data)
    return TUNING_REPORT_PATH, data
