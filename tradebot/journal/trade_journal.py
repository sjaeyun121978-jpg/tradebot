"""
trade_journal.py
호환 레이어 (Compatibility Wrapper)

기존 jobs.py에서 아래를 import했음:
  from tradebot.journal.trade_journal import (
      record_signal as journal_record,
      update_pending_results,
      format_stats_message,
  )

이 파일은 기존 import가 깨지지 않도록 유지하면서
내부적으로 새 storage/tracker/report를 호출한다.
"""

from tradebot.journal.storage import record_signal, get_open_signals
from tradebot.journal.tracker import update_open_signals
from tradebot.journal.report  import format_report_message, save_summary_csv


def update_pending_results(get_price_fn=None):
    """
    기존 호환: update_pending_results(get_current_price)
    → update_open_signals로 위임
    """
    try:
        return update_open_signals(price_fetcher=get_price_fn)
    except Exception as e:
        print(f"[TRADE JOURNAL] update_pending_results 실패: {e}", flush=True)
        return 0


def format_stats_message() -> str:
    """
    기존 호환: format_stats_message()
    → format_report_message()로 위임
    """
    try:
        return format_report_message()
    except Exception as e:
        return f"📊 통계 조회 실패: {e}"


# 기존 record_signal 시그니처 호환
# jobs.py에서 journal_record(symbol=..., signal_type=..., direction=..., price=...) 형태로 호출
def record_signal_compat(
    symbol:       str  = "",
    signal_type:  str  = "",
    direction:    str  = "WAIT",
    price:        float = 0,
    stop:         float = 0,
    tp1:          float = 0,
    tp2:          float = 0,
    confidence:   float = 0,
    score_gap:    float = 0,
    market_state: str  = "UNKNOWN",
    rr:           float = 0,
    reason:       str  = "",
    **kwargs,
) -> str:
    """
    기존 jobs.py의 journal_record(symbol=...) 형태 호환
    새 storage.record_signal(payload dict) 형태로 변환
    """
    payload = {
        "symbol":        symbol,
        "mode":          signal_type,
        "card_type":     signal_type,
        "direction":     direction,
        "market_state":  market_state,
        "trade_allowed": direction not in ("WAIT",) and stop > 0,
        "block_reason":  reason if direction == "WAIT" else "",
        "confidence":    confidence,
        "price_at_signal": price,
        "risk": {
            "entry": price,
            "stop":  stop,
            "tp1":   tp1,
            "tp2":   tp2,
            "rr":    rr,
        },
        "notes": reason,
    }
    try:
        return record_signal(payload)
    except Exception as e:
        print(f"[TRADE JOURNAL] record_signal_compat 실패: {e}", flush=True)
        return ""
