"""
storage.py
CSV 기반 저널 저장소

역할:
  - data/journal 폴더 자동 생성
  - signals.csv 헤더 포함 자동 생성
  - signal_id 중복 방지 (append_or_update)
  - 파일 깨짐 방어
  - 메인 봇이 죽지 않도록 모든 I/O를 try/except로 보호
"""

import csv
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# signals.csv 컬럼 정의 (지시서 기준)
SIGNAL_COLUMNS = [
    "signal_id",
    "created_at",
    "updated_at",
    "symbol",
    "direction",
    "mode",
    "card_type",
    "market_state",
    "trade_allowed",
    "block_reason",
    "confidence",
    "price_at_signal",
    "entry_price",
    "stop_price",
    "tp1",
    "tp2",
    "rr",
    "scenario_primary",
    "scenario_secondary",
    "scenario_invalid",
    "scenario_wait",
    "result_15m",
    "result_1h",
    "result_4h",
    "result_24h",
    "mfe",
    "mae",
    "tp1_hit",
    "tp1_hit_at",
    "tp2_hit",
    "tp2_hit_at",
    "sl_hit",
    "sl_hit_at",
    "first_hit",
    "final_status",
    "max_price_after_signal",
    "min_price_after_signal",
    "notes",
]


def _now_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def _get_paths():
    """환경변수 기반 경로 반환 (런타임에 읽어야 함)"""
    from tradebot.config import settings
    journal_dir  = getattr(settings, "JOURNAL_DIR",         "data/journal")
    signal_file  = getattr(settings, "JOURNAL_SIGNAL_FILE", "signals.csv")
    return journal_dir, os.path.join(journal_dir, signal_file)


def ensure_journal_dir() -> bool:
    """data/journal 폴더 및 signals.csv 자동 생성"""
    try:
        journal_dir, signal_path = _get_paths()
        os.makedirs(journal_dir, exist_ok=True)
        if not os.path.exists(signal_path):
            with open(signal_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=SIGNAL_COLUMNS)
                writer.writeheader()
        return True
    except Exception as e:
        print(f"[JOURNAL STORAGE] ensure_journal_dir 실패: {e}", flush=True)
        return False


def load_signals() -> list:
    """
    signals.csv 전체 로드
    실패 시 빈 리스트 반환 (메인 봇 보호)
    """
    try:
        _, signal_path = _get_paths()
        if not os.path.exists(signal_path):
            return []
        with open(signal_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # 누락 컬럼 빈 값으로 보완
                for col in SIGNAL_COLUMNS:
                    if col not in row:
                        row[col] = ""
                rows.append(dict(row))
            return rows
    except Exception as e:
        print(f"[JOURNAL STORAGE] load_signals 실패: {e}", flush=True)
        return []


def save_signals(rows: list) -> bool:
    """
    전체 rows를 signals.csv에 덮어쓰기
    실패 시 False 반환
    """
    try:
        _, signal_path = _get_paths()
        ensure_journal_dir()
        with open(signal_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SIGNAL_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({col: row.get(col, "") for col in SIGNAL_COLUMNS})
        return True
    except Exception as e:
        print(f"[JOURNAL STORAGE] save_signals 실패: {e}", flush=True)
        return False


def make_signal_id(payload: dict) -> str:
    """
    Deterministic signal_id 생성
    symbol + created_at_분단위 + direction + entry_price + card_type
    예: BTCUSDT_20260427T1300_LONG_94321.5_RADAR
    """
    try:
        symbol    = str(payload.get("symbol",    "UNKNOWN")).upper()
        direction = str(payload.get("direction", "WAIT")).upper()
        card_type = str(payload.get("card_type", payload.get("mode", "UNKNOWN"))).upper()
        price     = payload.get("entry_price") or payload.get("price_at_signal") or payload.get("current_price") or 0
        now       = datetime.now(KST).strftime("%Y%m%dT%H%M")
        price_str = f"{float(price):.1f}" if price else "0"
        return f"{symbol}_{now}_{direction}_{price_str}_{card_type}"
    except Exception:
        return f"UNKNOWN_{datetime.now(KST).strftime('%Y%m%dT%H%M%S')}"


def _normalize_row(payload: dict) -> dict:
    """
    payload dict → SIGNAL_COLUMNS 기준 row dict 변환
    decision 객체나 임의 dict 모두 수용
    """
    row = {col: "" for col in SIGNAL_COLUMNS}

    now_s = _now_str()

    # 기본 필드 매핑
    row["created_at"]     = now_s
    row["updated_at"]     = now_s
    row["symbol"]         = str(payload.get("symbol",         "")).upper()
    row["direction"]      = str(payload.get("direction",      "WAIT")).upper()
    row["mode"]           = str(payload.get("mode",           "")).upper()
    row["card_type"]      = str(payload.get("card_type",      payload.get("mode", ""))).upper()
    row["market_state"]   = str(payload.get("market_state",   "UNKNOWN")).upper()
    row["trade_allowed"]  = str(payload.get("trade_allowed",  False))
    row["block_reason"]   = str(payload.get("block_reason",   ""))
    row["confidence"]     = str(payload.get("confidence",     0))

    # 가격 정보
    price = payload.get("current_price") or payload.get("price_at_signal") or 0
    row["price_at_signal"] = str(price)

    risk = payload.get("risk") or {}
    row["entry_price"] = str(risk.get("entry") or price or 0)
    row["stop_price"]  = str(risk.get("stop",  0))
    row["tp1"]         = str(risk.get("tp1",   0))
    row["tp2"]         = str(risk.get("tp2",   0))
    row["rr"]          = str(risk.get("rr",    0))

    # 시나리오
    scenario = payload.get("scenario") or {}
    row["scenario_primary"]   = str(scenario.get("primary",   ""))
    row["scenario_secondary"] = str(scenario.get("secondary", ""))
    row["scenario_invalid"]   = str(scenario.get("invalid",   ""))
    row["scenario_wait"]      = str(scenario.get("wait",      ""))

    # 초기 상태
    row["result_15m"] = ""
    row["result_1h"]  = ""
    row["result_4h"]  = ""
    row["result_24h"] = ""
    row["mfe"]        = ""
    row["mae"]        = ""
    row["tp1_hit"]    = "False"
    row["tp1_hit_at"] = ""
    row["tp2_hit"]    = "False"
    row["tp2_hit_at"] = ""
    row["sl_hit"]     = "False"
    row["sl_hit_at"]  = ""
    row["first_hit"]  = "NONE"
    row["max_price_after_signal"] = str(price)
    row["min_price_after_signal"] = str(price)

    # final_status 초기값
    trade_allowed = str(payload.get("trade_allowed", "True")).lower() in ("true", "1", "yes")
    if not trade_allowed:
        if str(payload.get("direction", "")).upper() == "WAIT":
            row["final_status"] = "WAIT_ONLY"
        else:
            row["final_status"] = "BLOCKED"
    else:
        row["final_status"] = "OPEN"

    row["notes"] = str(payload.get("notes", ""))

    return row


def record_signal(payload: dict) -> str:
    """
    신호 기록 메인 함수
    decision 객체 또는 임의 dict 수용
    중복 signal_id면 skip
    실패 시 "" 반환 (메인 봇 보호)
    """
    try:
        ensure_journal_dir()
        row = _normalize_row(payload)

        # signal_id 생성 또는 payload에서 가져오기
        sid = payload.get("signal_id") or make_signal_id(payload)
        row["signal_id"] = sid

        rows = load_signals()

        # 중복 체크
        existing_ids = {r.get("signal_id", "") for r in rows}
        if sid in existing_ids:
            # 이미 있으면 skip (동일 분에 같은 신호 중복 방지)
            return sid

        rows.append(row)
        save_signals(rows)

        # Google Sheets 동기화 (실패해도 record_signal은 성공)
        try:
            from tradebot.journal.sheets import safe_write_signal
            safe_write_signal(row)
        except Exception as _se:
            print(f'[JOURNAL SHEETS] record_signal sync 실패: {_se}', flush=True)

        return sid

    except Exception as e:
        print(f"[JOURNAL STORAGE] record_signal 실패: {e}", flush=True)
        return ""


def update_signal(signal_id: str, updates: dict) -> bool:
    """
    특정 signal_id의 필드 업데이트
    실패 시 False 반환
    """
    try:
        rows = load_signals()
        found = False
        for row in rows:
            if row.get("signal_id") == signal_id:
                row["updated_at"] = _now_str()
                for k, v in updates.items():
                    if k in SIGNAL_COLUMNS:
                        row[k] = str(v) if v is not None else ""
                found = True
                break
        if found:
            save_signals(rows)
            # Google Sheets 동기화
            try:
                updated_row = next((r for r in rows if r.get('signal_id') == signal_id), None)
                if updated_row:
                    from tradebot.journal.sheets import safe_write_signal
                    safe_write_signal(updated_row)
            except Exception as _se:
                print(f'[JOURNAL SHEETS] update_signal sync 실패: {_se}', flush=True)
        return found
    except Exception as e:
        print(f"[JOURNAL STORAGE] update_signal 실패: {e}", flush=True)
        return False


def get_open_signals() -> list:
    """final_status == OPEN인 신호만 반환"""
    try:
        rows = load_signals()
        return [r for r in rows if r.get("final_status", "").upper() == "OPEN"]
    except Exception as e:
        print(f"[JOURNAL STORAGE] get_open_signals 실패: {e}", flush=True)
        return []


def append_or_update_signal(row: dict) -> str:
    """
    signal_id 있으면 update, 없으면 append
    """
    try:
        sid = row.get("signal_id", "")
        if not sid:
            return record_signal(row)

        rows = load_signals()
        existing_ids = {r.get("signal_id", "") for r in rows}
        if sid in existing_ids:
            return update_signal(sid, row) and sid or ""
        else:
            rows.append({col: row.get(col, "") for col in SIGNAL_COLUMNS})
            save_signals(rows)
            return sid
    except Exception as e:
        print(f"[JOURNAL STORAGE] append_or_update_signal 실패: {e}", flush=True)
        return ""
