# claude_analyzers.py v6
# Claude AI 분석기
# v6: JSON 구조화 응답 강제, market_data 프롬프트 반영
# ─────────────────────────────────────────────────────────────

import json
from tradebot.ai.claude_client import call_claude


# ─────────────────────────────────────────────────────────────
# market_data 프롬프트 섹션 빌더
# ─────────────────────────────────────────────────────────────

def build_market_data_section(market_data: dict) -> str:
    if not market_data:
        return ""
    lines = ["\n[시장 심층 데이터 — 기술적 지표보다 우선 반영]"]

    ob = market_data.get("orderbook", {})
    if ob.get("usable"):
        lines.append(
            f"오더북: {ob.get('pressure','NEUTRAL')} | "
            f"불균형 {ob.get('imbalance',1):.2f} | "
            f"스프레드 {ob.get('spread_pct',0):.4f}%"
        )
        bw = ob.get("bid_wall", {})
        aw = ob.get("ask_wall", {})
        if bw.get("qty", 0) > 0:
            lines.append(f"  매수벽: {bw.get('price',0):,.2f} (수량 {bw.get('qty',0):.2f})")
        if aw.get("qty", 0) > 0:
            lines.append(f"  매도벽: {aw.get('price',0):,.2f} (수량 {aw.get('qty',0):.2f})")

    tr = market_data.get("trades", {})
    if tr.get("usable"):
        lines.append(
            f"CVD: {tr.get('cvd_signal','NEUTRAL')} | "
            f"매수체결 {tr.get('buy_ratio',50):.1f}% | "
            f"대량체결 {tr.get('large_trades',0)}건"
        )

    oi = market_data.get("open_interest", {})
    if oi.get("usable"):
        lines.append(
            f"OI: {oi.get('oi_signal','STABLE')} | "
            f"1시간 변화 {oi.get('oi_1h_change',0):+.2f}%"
        )

    fr = market_data.get("funding_rate", {})
    if fr.get("usable"):
        lines.append(
            f"펀딩비: {fr.get('funding_rate',0):.4f}% "
            f"({fr.get('signal','NEUTRAL')}) | "
            f"{fr.get('minutes_to_fund',0)}분 후 정산"
        )

    liq = market_data.get("liquidations", {})
    if liq.get("usable"):
        lines.append(
            f"청산: {liq.get('dominant','BALANCED')} | "
            f"롱청산 ${liq.get('long_liq_usd',0):,.0f} | "
            f"숏청산 ${liq.get('short_liq_usd',0):,.0f}"
        )

    ls = market_data.get("long_short_ratio", {})
    if ls.get("usable"):
        lines.append(
            f"롱숏비율: 롱 {ls.get('long_pct',50):.1f}% / "
            f"숏 {ls.get('short_pct',50):.1f}% "
            f"({ls.get('signal','NEUTRAL')})"
        )

    return "\n".join(lines) if len(lines) > 1 else ""


# ─────────────────────────────────────────────────────────────
# JSON 응답 파서
# ─────────────────────────────────────────────────────────────

def _parse_json_response(text: str) -> dict:
    """
    Claude JSON 응답 파싱
    실패 시 텍스트 그대로 반환 (하위 호환)
    """
    if not text:
        return {}
    try:
        clean = text.strip()
        # ```json ... ``` 제거
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1]) if len(lines) > 2 else clean
        return json.loads(clean)
    except Exception:
        return {"message": text, "direction": "WAIT", "confidence": 0}


def _json_to_message(data: dict, symbol: str) -> str:
    """JSON 응답 → 텔레그램 메시지 포맷"""
    if not data or "message" in data:
        return data.get("message", "") if data else ""

    direction  = data.get("direction", "WAIT").upper()
    confidence = data.get("confidence", 0)
    summary    = data.get("summary", "")
    action     = data.get("action", "대기")
    long_pct   = data.get("long_pct", 50)
    short_pct  = data.get("short_pct", 50)
    trigger_long  = data.get("trigger_long", "-")
    trigger_short = data.get("trigger_short", "-")
    invalidate_long  = data.get("invalidate_long", "-")
    invalidate_short = data.get("invalidate_short", "-")
    scenario   = data.get("scenario", "-")
    warnings   = data.get("warnings", [])
    market_notes = data.get("market_notes", [])

    dir_emoji = {"LONG": "🟢", "SHORT": "🔴", "WAIT": "🟡"}.get(direction, "⚪")
    warn_txt  = "\n".join([f"  ⚠️ {w}" for w in warnings[:3]]) if warnings else ""
    mkt_txt   = "\n".join([f"  📡 {m}" for m in market_notes[:3]]) if market_notes else ""

    msg = (
        f"📊 {symbol} Claude 종합 분석\n"
        f"{'─'*28}\n"
        f"{dir_emoji} {direction} | 신뢰도 {confidence}%\n"
        f"📌 {summary}\n"
        f"▶ 행동: {action}\n\n"
        f"🚦 방향 점수\n"
        f"  롱 {long_pct}% / 숏 {short_pct}%\n\n"
        f"🎯 시나리오: {scenario}\n\n"
        f"🚨 트리거\n"
        f"  롱: {trigger_long}\n"
        f"  숏: {trigger_short}\n\n"
        f"🛑 무효화\n"
        f"  롱 무효: {invalidate_long}\n"
        f"  숏 무효: {invalidate_short}\n"
    )
    if mkt_txt:
        msg += f"\n📡 시장 심층\n{mkt_txt}\n"
    if warn_txt:
        msg += f"\n⚠️ 주의\n{warn_txt}\n"

    return msg.strip()


# ─────────────────────────────────────────────────────────────
# 핵심 분석 프롬프트 (JSON 구조화)
# ─────────────────────────────────────────────────────────────

def build_analysis_prompt(symbol: str, sig: dict, market_data: dict = None) -> str:
    price      = sig.get("current_price", 0)
    rsi        = sig.get("rsi", 50)
    cci        = sig.get("cci", 0)
    macd       = sig.get("macd_state", "NEUTRAL")
    trend_15m  = sig.get("trend_15m", "SIDEWAYS")
    trend_1h   = sig.get("trend_1h",  "SIDEWAYS")
    trend_4h   = sig.get("trend_4h",  "SIDEWAYS")
    trend_1d   = sig.get("trend_1d",  "SIDEWAYS")
    structure  = sig.get("structure", "-")
    divergence = sig.get("divergence", "없음") or "없음"
    support    = sig.get("support", 0)
    resistance = sig.get("resistance", 0)
    long_score = sig.get("long_score", 0)
    short_score = sig.get("short_score", 0)
    bb_signal  = sig.get("bb_signal", "NEUTRAL")
    is_range   = sig.get("is_range", False)
    range_pos  = sig.get("range_pos", "-")
    vol_ratio  = sig.get("volume_ratio", 0)

    market_section = build_market_data_section(market_data)

    return f"""
너는 실전 선물 트레이더다. 아래 데이터를 분석해서 반드시 JSON만 출력하라.
마크다운, 설명, 코드블록 없이 순수 JSON만.

절대 금지:
- 애매한 표현 ("가능성 있음", "주의 필요")
- 근거 없는 방향 제시
- JSON 외 텍스트 출력

===== 분석 데이터 =====

코인: {symbol}
현재가: {price:,.2f}
지지: {support:,.2f} / 저항: {resistance:,.2f}

[멀티타임프레임]
15M: {trend_15m} / 1H: {trend_1h} / 4H: {trend_4h} / 1D: {trend_1d}
구조: {structure}

[지표]
RSI: {rsi:.1f} / CCI: {cci:.0f} / MACD: {macd}
볼린저: {bb_signal} / 거래량비율: {vol_ratio:.2f}배
다이버전스: {divergence}
박스권: {"있음 (" + str(range_pos) + ")" if is_range else "없음"}

[점수]
LONG {long_score}% / SHORT {short_score}%
{market_section}

===== 출력 형식 (JSON) =====

{{
  "direction": "LONG 또는 SHORT 또는 WAIT",
  "confidence": 0~100 숫자,
  "long_pct": 0~100 숫자,
  "short_pct": 0~100 숫자,
  "summary": "현재 상황 한 줄 요약",
  "action": "즉시 롱 / 즉시 숏 / 대기 / 진입 금지 중 하나",
  "scenario": "1순위 시나리오 한 줄",
  "trigger_long": "롱 진입 트리거 조건",
  "trigger_short": "숏 진입 트리거 조건",
  "invalidate_long": "롱 무효화 조건",
  "invalidate_short": "숏 무효화 조건",
  "warnings": ["주의사항1", "주의사항2"],
  "market_notes": ["시장 심층 데이터 기반 주요 포인트"]
}}

규칙:
- long_pct + short_pct = 100
- confidence 차이 10% 미만이면 direction = "WAIT"
- 거래량 부족 (vol_ratio < 1.0) 이면 action = "대기"
- 오더북/CVD 역방향이면 반드시 warnings에 명시
- market_notes는 시장 심층 데이터 있을 때만 작성
"""


# ─────────────────────────────────────────────────────────────
# 메인 분석 함수 (jobs.py에서 호출)
# ─────────────────────────────────────────────────────────────

def analyze_with_claude(symbol: str, sig: dict, market_data: dict = None) -> dict:
    """
    핵심 Claude 분석 함수
    JSON 응답 → 파싱 → 메시지 생성
    반환: {"direction", "confidence", "message", "raw": dict}
    """
    prompt = build_analysis_prompt(symbol, sig, market_data)
    raw_text = call_claude(prompt, max_tokens=800)

    if not raw_text or raw_text.startswith("[Claude 호출 실패]"):
        return {
            "direction": "WAIT", "confidence": 0,
            "message": f"⚠️ {symbol} Claude 분석 실패\n{raw_text}",
            "raw": {}
        }

    data = _parse_json_response(raw_text)
    message = _json_to_message(data, symbol)

    return {
        "direction":  data.get("direction", "WAIT"),
        "confidence": data.get("confidence", 0),
        "long_pct":   data.get("long_pct", 50),
        "short_pct":  data.get("short_pct", 50),
        "action":     data.get("action", "대기"),
        "message":    message,
        "raw":        data,
    }


# ─────────────────────────────────────────────────────────────
# 하위 호환 함수들 (jobs.py safe_call 어댑터용)
# ─────────────────────────────────────────────────────────────

def build_fact_analysis_prompt(symbol, price, indicators, market_data=None):
    """레거시 호환 — analyze_with_claude 사용 권장"""
    sig = indicators or {}
    sig["current_price"] = price
    sig["symbol"] = symbol
    return build_analysis_prompt(symbol, sig, market_data)


def analyze_fact(symbol, price, indicators):
    sig = dict(indicators or {})
    sig["current_price"] = price
    sig["symbol"] = symbol
    result = analyze_with_claude(symbol, sig)
    return result.get("message", "")


def analyze_info(text):
    prompt = f"""
다음 트레이딩 상황을 분석해서 JSON으로만 응답하라.

{text}

출력:
{{"summary": "한줄요약", "direction": "LONG/SHORT/WAIT", "action": "행동지침"}}
"""
    raw = call_claude(prompt, max_tokens=300)
    data = _parse_json_response(raw)
    return data.get("summary") or data.get("message") or raw


def analyze_mungkkul(symbol, candles_by_tf, structure_result=None):
    """멍꼴단 채널용 간략 분석"""
    price = 0
    c15 = candles_by_tf.get("15m", [])
    if c15:
        try:
            price = float(c15[-1].get("close", 0))
        except Exception:
            pass
    sig = structure_result or {}
    sig["symbol"] = symbol
    sig["current_price"] = price
    result = analyze_with_claude(symbol, sig)
    return result.get("message", "")


def run_all_analyzers(symbol, candles_by_tf, structure_result=None):
    return analyze_mungkkul(symbol, candles_by_tf, structure_result)


def analyze(symbol, candles_by_tf, structure_result=None):
    return analyze_mungkkul(symbol, candles_by_tf, structure_result)
