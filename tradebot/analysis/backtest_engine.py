"""
backtest_engine.py
STEP 이벤트 자동 복기 엔진

로직:
  1. step_log.json에서 미복기(reviewed=False) 항목 로드
  2. 발생 시점 이후 3~5봉 수익률 계산
  3. SUCCESS / FAIL / NEUTRAL 판정
  4. 통계 집계 + 잘못된 패턴 TOP5 추출
  5. 결과를 step_log.json에 반영

기준:
  LONG:  +1% 이상 → SUCCESS  /  -1% 이하 → FAIL
  SHORT: -1% 이하 → SUCCESS  /  +1% 이상 → FAIL
  그 외: NEUTRAL
"""

from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

KST       = timezone(timedelta(hours=9))
BASE_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
STEP_LOG  = os.path.join(BASE_DIR, "step_log.json")
RESULT_FILE = os.path.join(BASE_DIR, "backtest_result.json")

_lock = threading.Lock()

SUCCESS_PCT = 1.0    # +1% 이상 → 성공
FAIL_PCT    = -1.0   # -1% 이하 → 실패
REVIEW_BARS = 5      # 이후 N봉 추적


# ─────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────

def _safe_float(v, d=0.0):
    try:
        return float(v) if v is not None else d
    except Exception:
        return d


def _candle_time(c):
    """캔들에서 open_time 추출 (dict / list 모두 처리)"""
    if isinstance(c, dict):
        return c.get("open_time") or c.get("time") or c.get("t")
    if isinstance(c, (list, tuple)) and len(c) > 0:
        return c[0]
    return None


def _to_ts(v) -> float | None:
    """ISO 문자열 / ms타임스탬프 / s타임스탬프 → 초 단위 float"""
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


def _filter_after_entry(entry: dict, candles_15m: list) -> list:
    """
    STEP 발생 timestamp 이후 캔들만 반환한다.
    타임스탬프를 파싱할 수 없으면 빈 리스트 반환 (안전 우선).
    """
    entry_ts = _to_ts(entry.get("timestamp"))
    if not entry_ts:
        return []
    out = []
    for c in candles_15m or []:
        ct = _to_ts(_candle_time(c))
        if ct is not None and ct > entry_ts:
            out.append(c)
    return out


def _read_json(path: str, default: Any) -> Any:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _write_json(path: str, data: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


# ─────────────────────────────────────────────
# 복기 엔진 핵심
# ─────────────────────────────────────────────

def review_entry(entry: dict, candles_15m_after: list) -> dict:
    """
    단일 STEP 엔트리를 복기한다.

    candles_15m_after: STEP 발생 이후 최소 REVIEW_BARS개 캔들
    반환: 업데이트된 entry dict
    """
    direction = str(entry.get("direction") or entry.get("candidate_dir") or "WAIT").upper()
    if direction not in ("LONG", "SHORT"):
        entry["result_label"] = "SKIP"
        entry["reviewed"]     = True
        return entry

    entry_price = _safe_float(entry.get("price"))
    if entry_price <= 0 or len(candles_15m_after) < 1:
        return entry

    highs  = []
    lows   = []
    closes = []
    for c in candles_15m_after[:REVIEW_BARS]:
        if isinstance(c, dict):
            highs.append(_safe_float(c.get("high",  0)))
            lows.append( _safe_float(c.get("low",   0)))
            closes.append(_safe_float(c.get("close", 0)))
        elif isinstance(c, (list, tuple)) and len(c) >= 5:
            highs.append(_safe_float(c[2]))
            lows.append( _safe_float(c[3]))
            closes.append(_safe_float(c[4]))

    if not closes:
        return entry

    # 최종 종가 기준 수익률
    last_close  = closes[-1]
    result_pct  = (last_close - entry_price) / entry_price * 100

    # 방향별 최대 유리 / 최대 불리
    if direction == "LONG":
        max_fav = max(highs)  if highs  else last_close
        max_adv = min(lows)   if lows   else last_close
        fav_pct = (max_fav - entry_price) / entry_price * 100
        adv_pct = (max_adv - entry_price) / entry_price * 100
        if fav_pct >= SUCCESS_PCT:
            label = "SUCCESS"
        elif adv_pct <= FAIL_PCT:
            label = "FAIL"
        else:
            label = "NEUTRAL"
    else:  # SHORT
        max_fav = min(lows)  if lows  else last_close
        max_adv = max(highs) if highs else last_close
        fav_pct = (entry_price - max_fav) / entry_price * 100
        adv_pct = (entry_price - max_adv) / entry_price * 100
        if fav_pct >= SUCCESS_PCT:
            label = "SUCCESS"
        elif adv_pct <= FAIL_PCT:
            label = "FAIL"
        else:
            label = "NEUTRAL"

    entry["result_price"]  = round(last_close, 4)
    entry["result_pct"]    = round(result_pct, 3)
    entry["result_fav_pct"]= round(fav_pct, 3)
    entry["result_adv_pct"]= round(adv_pct, 3)
    entry["result_label"]  = label
    entry["reviewed"]      = True

    return entry


def run_backtest(candles_feed: dict[str, list] | None = None) -> dict:
    """
    미복기 항목을 일괄 복기하고 통계를 반환한다.

    candles_feed: {symbol: candles_15m_list} — None이면 파일에서만 처리

    반환 dict:
    {
      "total":           int,
      "reviewed_now":    int,
      "by_step": {
        "EARLY": {"total":N, "success":N, "fail":N, "neutral":N, "rate":0.xx},
        ...
      },
      "by_direction": {...},
      "worst_patterns": [...],   # 실패 TOP5
      "summary_text":  str,
    }
    """
    with _lock:
        logs = _read_json(STEP_LOG, [])

    reviewed_now = 0
    pending = [e for e in logs if not e.get("reviewed")]

    for entry in pending:
        symbol    = entry.get("symbol", "")
        candles   = (candles_feed or {}).get(symbol, [])
        if candles:
            after = _filter_after_entry(entry, candles)

            if len(after) < REVIEW_BARS:
                continue

            updated = review_entry(dict(entry), after[:REVIEW_BARS])

            if updated.get("reviewed"):
                entry.update(updated)
                reviewed_now += 1

    # log 업데이트 병합
    id_map = {e.get("id"): e for e in logs}
    for e in pending:
        if e.get("id") in id_map:
            id_map[e["id"]] = e
    updated_logs = list(id_map.values())

    with _lock:
        _write_json(STEP_LOG, updated_logs)

    # ── 통계 집계
    stats = _aggregate(updated_logs)
    stats["reviewed_now"] = reviewed_now
    stats["timestamp"]    = _now_iso()

    with _lock:
        _write_json(RESULT_FILE, stats)

    return stats


def _aggregate(logs: list) -> dict:
    """복기 완료 항목 통계 집계"""
    reviewed = [e for e in logs if e.get("reviewed") and e.get("result_label") not in (None, "SKIP")]

    # STEP별 집계
    by_step: dict[str, dict] = defaultdict(lambda: {"total":0,"success":0,"fail":0,"neutral":0})
    by_dir:  dict[str, dict] = defaultdict(lambda: {"total":0,"success":0,"fail":0,"neutral":0})

    fail_patterns: list[dict] = []

    for e in reviewed:
        step  = e.get("step",      "?")
        direc = e.get("direction", "?")
        label = e.get("result_label", "NEUTRAL")

        for bucket in [by_step[step], by_dir[direc]]:
            bucket["total"] += 1
            if label == "SUCCESS": bucket["success"] += 1
            elif label == "FAIL":  bucket["fail"] += 1
            else:                  bucket["neutral"] += 1

        if label == "FAIL":
            fail_patterns.append({
                "id":             e.get("id"),
                "ts":             e.get("timestamp"),
                "symbol":         e.get("symbol"),
                "step":           step,
                "direction":      direc,
                "price":          e.get("price"),
                "result_pct":     e.get("result_pct"),
                "reversal_stage": e.get("reversal_stage"),
                "reversal_score": e.get("reversal_score"),
                "market_state":   e.get("market_state"),
                "block_reason":   e.get("block_reason"),
                "reasons":        e.get("reversal_reasons", []),
            })

    # 승률 계산
    def rate(d):
        t = d["total"]
        return round(d["success"] / t * 100, 1) if t > 0 else 0.0

    for d in list(by_step.values()) + list(by_dir.values()):
        d["rate"] = rate(d)

    # 잘못된 패턴 TOP5 (result_pct 오름차순 = 가장 나쁜 순)
    fail_sorted = sorted(fail_patterns, key=lambda x: _safe_float(x.get("result_pct"), 0))[:5]

    # 전체 요약 텍스트
    total = len(reviewed)
    succ  = sum(1 for e in reviewed if e.get("result_label") == "SUCCESS")
    fail  = sum(1 for e in reviewed if e.get("result_label") == "FAIL")
    neut  = total - succ - fail
    overall_rate = round(succ / total * 100, 1) if total > 0 else 0.0

    lines = [
        f"[STEP 복기 결과]  복기 완료: {total}건",
        f"전체 승률: {overall_rate}%  (성공 {succ} / 실패 {fail} / 중립 {neut})",
        "",
        "[ 단계별 승률 ]",
    ]
    for step_name in ("REAL", "PRE", "EARLY", "WAIT"):
        d = by_step.get(step_name, {})
        if d.get("total", 0) > 0:
            lines.append(f"  {step_name:6s}: {d['rate']:5.1f}%  ({d['total']}건)")

    lines.append("")
    lines.append("[ 실패 패턴 TOP5 ]")
    for i, fp in enumerate(fail_sorted, 1):
        lines.append(
            f"  {i}. {fp['symbol']} {fp['step']} {fp['direction']} "
            f"rev:{fp.get('reversal_stage','?')} {fp.get('reversal_score','?')}pt "
            f"→ {fp.get('result_pct',0):+.2f}%  "
            f"[{fp.get('market_state','?')}]"
        )

    return {
        "total":         total,
        "success":       succ,
        "fail":          fail,
        "neutral":       neut,
        "overall_rate":  overall_rate,
        "by_step":       dict(by_step),
        "by_direction":  dict(by_dir),
        "worst_patterns":fail_sorted,
        "summary_text":  "\n".join(lines),
    }


# ─────────────────────────────────────────────
# 단건 복기용 훅 (jobs.py에서 호출)
# ─────────────────────────────────────────────

def try_review_pending(symbol: str, candles_15m: list) -> int:
    """
    symbol의 미복기 항목 중 candles_15m을 활용해 즉시 복기한다.
    반환: 복기된 건수
    """
    with _lock:
        logs = _read_json(STEP_LOG, [])

    pending = [e for e in logs if e.get("symbol") == symbol
               and not e.get("reviewed")
               and e.get("result_label") not in ("SKIP",)]

    if not pending:
        return 0

    count = 0
    updated_entries: dict[str, dict] = {}   # id → 복기 완료 entry

    for entry in pending:
        # entry 발생 시점 이후 캔들만 추출
        after = _filter_after_entry(entry, candles_15m)

        # 5개 15분봉이 쌓이기 전에는 복기 금지
        if len(after) < REVIEW_BARS:
            continue

        updated = review_entry(dict(entry), after[:REVIEW_BARS])   # 원본 복사 후 수정
        if updated.get("reviewed"):
            updated_entries[updated.get("id", "")] = updated
            count += 1

    if not count:
        return 0

    # 로그 병합: 복기 완료 항목만 교체
    id_map = {e.get("id"): e for e in logs}
    for eid, updated in updated_entries.items():
        if eid in id_map:
            id_map[eid] = updated

    with _lock:
        _write_json(STEP_LOG, list(id_map.values()))

    return count
