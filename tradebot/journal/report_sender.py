"""
journal/report_sender.py
일일 복기 리포트 자동 전송

역할:
  - report.build_summary() 호출
  - 요약 텍스트 생성 (추천 문구 포함)
  - Google Sheets summary 탭에 저장
  - 텔레그램 전송
  - 모든 실패는 로그만, 메인 봇 보호
"""

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def _now_kst() -> datetime:
    return datetime.now(KST)


def format_pct(value) -> str:
    """퍼센트 포맷 (소수점 1자리)"""
    try:
        v = float(value)
        return f"{v:.1f}%"
    except Exception:
        return "-"


def format_num(value, decimals: int = 2) -> str:
    """숫자 포맷"""
    try:
        v = float(value)
        return f"{v:.{decimals}f}"
    except Exception:
        return "-"


def _build_recommendations(summary: dict, by_direction: dict, by_market: dict, by_rr: dict) -> list:
    """
    데이터 기반 자동 추천 문구 생성
    추천만 제공, 실제 매매 규칙 변경하지 않음
    """
    tips = []

    # 1. LONG TP1 도달률 낮음
    long_stats = by_direction.get("LONG", {})
    if long_stats.get("total", 0) >= 5:
        if long_stats.get("tp1_rate", 100) < 45:
            tips.append("⚠️ LONG TP1 도달률 낮음 → LONG 진입 조건 강화 검토")

    # 2. SHORT TP1 도달률 낮음
    short_stats = by_direction.get("SHORT", {})
    if short_stats.get("total", 0) >= 5:
        if short_stats.get("tp1_rate", 100) < 45:
            tips.append("⚠️ SHORT TP1 도달률 낮음 → SHORT 진입 조건 강화 검토")

    # 3. RANGE 구간 SL 비율 높음
    range_stats = by_market.get("RANGE", {})
    if range_stats.get("total", 0) >= 3:
        if range_stats.get("sl_rate", 0) > 50:
            tips.append("⚠️ RANGE 구간 SL 비율 높음 → RANGE 진입금지 필터 강화 검토")

    # 4. RR < 1.5 구간 SL 비율 높음
    rr_lt15 = by_rr.get("RR_lt_1", {})
    if rr_lt15.get("total", 0) >= 3 and rr_lt15.get("sl_rate", 0) > 50:
        tips.append("⚠️ RR 1.0 미만 구간 손실 큼 → RR 최소 기준 1.5 이상 유지 권장")

    rr_1_15 = by_rr.get("RR_1_to_15", {})
    if rr_1_15.get("total", 0) >= 3 and rr_1_15.get("sl_rate", 0) > 40:
        tips.append("💡 RR 1.0~1.5 구간 손실 빈번 → RR 기준 1.8 이상 상향 검토")

    # 5. WAIT/BLOCKED 이후 가격 변동 검토
    wait_c    = summary.get("wait_count",    0)
    blocked_c = summary.get("blocked_count", 0)
    total     = summary.get("total_signals", 1)
    if (wait_c + blocked_c) / max(total, 1) > 0.4:
        tips.append("✅ WAIT/BLOCKED 비율 높음 → 진입금지 필터 정상 작동 가능성 높음")

    # 추천 없으면 긍정 메시지
    if not tips:
        tips.append("✅ 현재 기준 특이 사항 없음 — 데이터 축적 후 재검토 권장")

    return tips


def build_report_text(summary: dict = None, by_direction: dict = None,
                      by_market: dict = None, by_rr: dict = None) -> str:
    """
    텔레그램용 복기 리포트 텍스트 생성
    """
    try:
        from tradebot.journal.report import (
            build_summary, build_summary_by_direction,
            build_summary_by_market_state, build_summary_by_rr_bucket,
        )

        if summary is None:
            summary = build_summary()
        if by_direction is None:
            by_direction = build_summary_by_direction()
        if by_market is None:
            by_market = build_summary_by_market_state()
        if by_rr is None:
            by_rr = build_summary_by_rr_bucket()

        if not summary:
            return "📊 복기 리포트\n\n데이터 없음 (신호 발생 후 24H 경과 필요)"

        total    = summary.get("total_signals", 0)
        long_c   = summary.get("long_count",    0)
        short_c  = summary.get("short_count",   0)
        wait_c   = summary.get("wait_count",    0)
        blocked_c = summary.get("blocked_count", 0)
        tp1_rate = format_pct(summary.get("tp1_hit_rate",  0))
        tp2_rate = format_pct(summary.get("tp2_hit_rate",  0))
        sl_rate  = format_pct(summary.get("sl_hit_rate",   0))
        avg_mfe  = format_num(summary.get("avg_mfe",       0))
        avg_mae  = format_num(summary.get("avg_mae",       0))
        avg_rr   = format_num(summary.get("avg_rr",        0))
        best_sym = summary.get("best_symbol",       "-")
        worst_sym = summary.get("worst_symbol",     "-")
        best_ms  = summary.get("best_market_state", "-")
        worst_ms = summary.get("worst_market_state","-")

        # 추천 문구
        tips = _build_recommendations(summary, by_direction, by_market, by_rr)
        tips_txt = "\n".join(tips)

        now_str = _now_kst().strftime("%Y-%m-%d %H:%M KST")

        return (
            f"📊 TradeBot 복기 리포트\n"
            f"{'─'*30}\n"
            f"기준: {now_str}\n\n"
            f"전체 신호: {total}개\n"
            f"LONG: {long_c}개 / SHORT: {short_c}개\n"
            f"WAIT: {wait_c}개 / BLOCKED: {blocked_c}개\n\n"
            f"TP1 도달률: {tp1_rate}\n"
            f"TP2 도달률: {tp2_rate}\n"
            f"SL 비율:   {sl_rate}\n\n"
            f"평균 MFE: +{avg_mfe}%\n"
            f"평균 MAE: {avg_mae}%\n"
            f"평균 RR:  {avg_rr}\n\n"
            f"우수 심볼: {best_sym}\n"
            f"취약 심볼: {worst_sym}\n"
            f"우수 시장상태: {best_ms}\n"
            f"취약 시장상태: {worst_ms}\n\n"
            f"판단:\n{tips_txt}\n\n"
            f"※ 자동매매 결과가 아닌 신호 복기 통계입니다."
        )

    except Exception as e:
        return f"📊 복기 리포트 생성 실패: {e}"


def send_daily_journal_report() -> bool:
    """
    일일 복기 리포트 전송 메인 함수

    동작:
      1. build_summary()
      2. save_summary_csv()
      3. Google Sheets summary 탭 저장
      4. 텔레그램 전송
      5. 실패해도 메인 루프 죽이지 않음
    """
    try:
        from tradebot.journal.report import (
            build_summary, save_summary_csv,
            build_summary_by_direction,
            build_summary_by_market_state,
            build_summary_by_rr_bucket,
        )
        from tradebot.journal.sheets import safe_write_summary
        from tradebot.delivery.telegram import send_message

        # 1. 요약 생성
        summary      = build_summary()
        by_direction = build_summary_by_direction()
        by_market    = build_summary_by_market_state()
        by_rr        = build_summary_by_rr_bucket()

        # 2. CSV 저장
        save_summary_csv()

        # 3. Google Sheets summary 탭 저장
        if summary:
            comment = "; ".join(
                _build_recommendations(summary, by_direction, by_market, by_rr)
            )
            summary["comment"] = comment
            safe_write_summary(summary)

        # 4. 텔레그램 전송
        report_text = build_report_text(summary, by_direction, by_market, by_rr)
        result = send_message(report_text)
        if result:
            print("[JOURNAL REPORT] sent", flush=True)
        else:
            print("[JOURNAL REPORT] telegram 전송 실패 (CSV/Sheets는 저장됨)", flush=True)

        return True

    except Exception as e:
        print(f"[JOURNAL REPORT ERROR] send_daily_journal_report: {e}", flush=True)
        return False


def should_send_daily_report(now: datetime, last_sent_key: str) -> bool:
    """
    일일 리포트 전송 여부 판단

    now:           KST 기준 현재 시각
    last_sent_key: 마지막 전송 날짜 문자열 (YYYY-MM-DD)
    """
    from tradebot.config import settings

    if not getattr(settings, "ENABLE_DAILY_JOURNAL_REPORT", True):
        return False

    target_hour   = getattr(settings, "DAILY_JOURNAL_REPORT_HOUR",   23)
    target_minute = getattr(settings, "DAILY_JOURNAL_REPORT_MINUTE", 50)

    if now.hour != target_hour:
        return False
    # 루프 지연 허용: ±2분
    if abs(now.minute - target_minute) > 2:
        return False

    today = now.strftime("%Y-%m-%d")
    if last_sent_key == today:
        return False

    return True


def send_text(text: str) -> bool:
    """텍스트를 텔레그램으로 전송하는 단순 래퍼"""
    try:
        from tradebot.delivery.telegram import send_message
        result = send_message(text)
        if result:
            print("[JOURNAL] send_text 전송 완료", flush=True)
        return result
    except Exception as e:
        print(f"[JOURNAL] send_text 실패: {e}", flush=True)
        return False
