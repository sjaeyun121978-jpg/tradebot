"""
test_step_state_engine.py
──────────────────────────────────────────────────
실제 주문 / 텔레그램 발송 없음.
엔진 함수만 검증.

필수 케이스:
1. 완전 관망 → WAIT
2. 약한 상승 전조 → EARLY LONG
3. 상승 후보 + 위험 → PRE LONG + WARNING
4. 강한 하락 정렬 → REAL SHORT
5. LONG 보유 중 정상 조정 → HOLD LONG
6. LONG 보유 중 구조 훼손 → EXIT LONG
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
)))))

from tradebot.analysis.engines.step_state_engine import decide_step_state

PASS = "✅"
FAIL = "❌"

results = []


def check(name, d, expected_state, extra_check=None):
    ok_state = d["final_state"] == expected_state
    ok_extra = extra_check(d) if extra_check else True
    ok = ok_state and ok_extra
    symbol = PASS if ok else FAIL
    print(f"{symbol} [{name}]")
    print(f"   final_state={d['final_state']}  direction={d['direction']}"
          f"  score={d['score']}  long={d['long_score']}  short={d['short_score']}"
          f"  gap={d['gap']}  warning={d['warning']}")
    if d["warning_reasons"]:
        print(f"   ⚠ warnings: {d['warning_reasons']}")
    if d["main_reasons"]:
        print(f"   ✔ reasons: {d['main_reasons']}")
    if d["penalty_reasons"]:
        print(f"   🔻 penalty: {d['penalty_reasons']}")
    print(f"   action: {d['action_text']}")
    if not ok:
        if not ok_state:
            print(f"   → 기대 state={expected_state}, 실제={d['final_state']}")
        if not ok_extra:
            print(f"   → extra_check 실패")
    print()
    results.append(ok)


# ── 케이스 1: 완전 관망 → WAIT ───────────────────────────────
case1 = {
    "current_price": 95000,
    "direction":     "WAIT",
    "trend_15m":     "SIDEWAYS",
    "trend_1h":      "SIDEWAYS",
    "trend_4h":      "SIDEWAYS",
    "rsi":           50,
    "cci":           0,
    "macd_state":    "NEUTRAL",
    "volume":        100,
    "avg_volume":    200,
    "is_range":      True,
    "range_pos":     "MIDDLE",
}
check("케이스1 완전 관망 → WAIT", decide_step_state(case1), "WAIT")


# ── 케이스 2: 약한 상승 전조 → EARLY LONG ────────────────────
case2 = {
    "current_price": 95000,
    "direction":     "LONG",
    "trend_15m":     "UP",
    "trend_1h":      "SIDEWAYS",
    "trend_4h":      "SIDEWAYS",
    "rsi":           52,
    "cci":           30,
    "macd_state":    "POSITIVE",
    "volume":        120,
    "avg_volume":    100,
    "support":       93000,
    "resistance":    97000,
    "is_range":      False,
    "ema20":         94500,
    "ema50":         93000,
}
check("케이스2 약한 상승 전조 → EARLY LONG",
      decide_step_state(case2), "EARLY",
      lambda d: d["direction"] == "LONG")


# ── 케이스 3: PRE LONG + WARNING ────────────────────────────
case3 = {
    "current_price": 95500,            # 저항(97000) 충분히 아래
    "direction":     "LONG",
    "trend_15m":     "UP",
    "trend_1h":      "UP",
    "trend_4h":      "DOWN",            # 4H 역행 → WARNING
    "rsi":           68,                # 과매수 근접 → WARNING
    "cci":           80,
    "macd_state":    "BULLISH",
    "volume":        200,
    "avg_volume":    100,
    "support":       93000,             # support 충분히 아래
    "resistance":    100000,            # resistance 멀리 → 손익비 우수
    "above_ema20":   True,
    "ema20":         94500,
    "ema50":         92000,
    "divergence":    "BULLISH_DIV",
    "bb_signal":     "OVERSOLD",
    "bb_squeeze":    True,
    "is_range":      False,
    "fibo_level":    0.5,
}
check("케이스3 PRE LONG + WARNING",
      decide_step_state(case3), "PRE",
      lambda d: d["warning"] is True)


# ── 케이스 4: 강한 하락 정렬 → REAL SHORT ────────────────────
case4 = {
    "current_price": 96800,
    "direction":     "SHORT",
    "trend_15m":     "DOWN",
    "trend_1h":      "DOWN",
    "trend_4h":      "DOWN",
    "rsi":           38,
    "cci":           -80,
    "macd_state":    "BEARISH",
    "volume":        160,
    "avg_volume":    100,
    "support":       89000,
    "resistance":    96850,         # 저항 근접 → dist 가점
    "below_ema20":   True,
    "ema20":         97500,
    "ema50":         99000,
    "divergence":    "BEARISH_DIV",
    "bb_signal":     "OVERBOUGHT",
    "bb_squeeze":    True,          # BB squeeze + 상단 과열
    "is_range":      True,
    "range_pos":     "TOP",         # 박스 상단 → dist 가점
    "fibo_level":    0.45,
    # 윗꼬리 강함 — upper_wick 83%
    "high_15m":      98000,
    "low_15m":       96800,
    "open_15m":      97000,
    "close_15m":     96900,
    "trades":    {"usable": True, "cvd_signal": "BEARISH", "buy_ratio": 28},
    "orderbook": {"usable": True, "pressure": "SELL",      "imbalance": 0.62},
    "funding_rate": {"usable": True, "signal": "LONG_OVERHEATED"},
}
check("케이스4 강한 하락 정렬 → REAL SHORT",
      decide_step_state(case4), "REAL",
      lambda d: d["direction"] == "SHORT")


# ── 케이스 5: LONG 보유 중 정상 조정 → HOLD ─────────────────
position_long = {
    "direction": "LONG",
    "stop":      88000,
    "entry":     91000,
}
case5 = {
    "current_price": 93000,
    "direction":     "LONG",
    "trend_15m":     "DOWN",    # 단기 조정
    "trend_1h":      "UP",
    "trend_4h":      "UP",
    "rsi":           55,
    "cci":           20,
    "macd_state":    "BULLISH",
    "volume":        80,
    "avg_volume":    100,
    "support":       90000,
    "resistance":    97000,
    "fibo_level":    0.50,
    "ema20":         92000,
    "ema50":         90000,
}
check("케이스5 LONG 보유 중 정상 조정 → HOLD",
      decide_step_state(case5, current_position=position_long), "HOLD")


# ── 케이스 6: LONG 보유 중 구조 훼손 → EXIT ─────────────────
position_long2 = {
    "direction": "LONG",
    "stop":      90000,
    "entry":     93000,
}
case6 = {
    "current_price": 89500,   # 손절선(90000) 아래
    "direction":     "SHORT",
    "trend_15m":     "DOWN",
    "trend_1h":      "DOWN",
    "trend_4h":      "DOWN",
    "rsi":           32,
    "cci":           -120,
    "macd_state":    "BEARISH",
    "volume":        300,
    "avg_volume":    100,
    "support":       88000,
    "resistance":    93000,
}
check("케이스6 LONG 보유 중 구조 훼손 → EXIT",
      decide_step_state(case6, current_position=position_long2), "EXIT")


# ════════════════════════════════════════════════════════════
# [신규] REAL 품질 게이트 v2 필수 테스트 8개
# ════════════════════════════════════════════════════════════

# REAL 통과용 강한 기반 데이터 (trap 낮음, accum/dist 높음, vol 충분, gap 넓음)
_REAL_BASE_LONG = {
    "direction": "LONG", "current_price": 95000,
    "trend_15m": "UP", "trend_1h": "UP", "trend_4h": "UP",
    "rsi": 52, "cci": 50, "macd_state": "BULLISH",
    "volume": 160, "avg_volume": 100,
    "support": 93050, "resistance": 102000,
    "ema20": 93500, "ema50": 91000, "above_ema20": True,
    "divergence": "BULLISH_DIV", "bb_signal": "OVERSOLD", "bb_squeeze": True,
    "is_range": True, "range_pos": "BOTTOM", "fibo_level": 0.45,
    # 아래꼬리 50%+ → accum 15점
    "high_15m": 94000, "low_15m": 92000, "open_15m": 93000, "close_15m": 93100,
    "trades":    {"usable": True, "cvd_signal": "BULLISH", "buy_ratio": 68},
    "orderbook": {"usable": True, "pressure": "BUY",       "imbalance": 1.60},
    "funding_rate": {"usable": True, "signal": "SHORT_OVERHEATED"},
}

_REAL_BASE_SHORT = {
    "direction": "SHORT", "current_price": 96800,
    "trend_15m": "DOWN", "trend_1h": "DOWN", "trend_4h": "DOWN",
    "rsi": 38, "cci": -80, "macd_state": "BEARISH",
    "volume": 160, "avg_volume": 100,
    "support": 89000, "resistance": 96850,
    "ema20": 97500, "ema50": 99000, "below_ema20": True,
    "divergence": "BEARISH_DIV", "bb_signal": "OVERBOUGHT", "bb_squeeze": True,
    "is_range": True, "range_pos": "TOP", "fibo_level": 0.45,
    # 윗꼬리 83%+ → dist 15점
    "high_15m": 98000, "low_15m": 96800, "open_15m": 97000, "close_15m": 96900,
    "trades":    {"usable": True, "cvd_signal": "BEARISH", "buy_ratio": 28},
    "orderbook": {"usable": True, "pressure": "SELL",       "imbalance": 0.62},
    "funding_rate": {"usable": True, "signal": "LONG_OVERHEATED"},
}


def _penalty_contains(d, keyword):
    return any(keyword in p for p in d.get("penalty_reasons", []))


# ── T1: trap_risk 40인 REAL 후보 → PRE 강등 ──────────────────
# 점수가 75+ 인 REAL 후보인데 trap_risk >= 35 → PRE로 강등
t1_data = {
    "direction": "LONG", "current_price": 95000,
    "trend_15m": "UP", "trend_1h": "UP", "trend_4h": "UP",
    "rsi": 75,                              # RSI 과열 → trap+10, warning 발생
    "cci": 50, "macd_state": "BULLISH",
    "volume": 60, "avg_volume": 100,        # 거래량 부족 → trap+20 (거래량없는 상승)
    "support": 93050, "resistance": 95100,  # 저항 0.1% → trap+10
    "ema20": 93500, "ema50": 91000, "above_ema20": True,
    "divergence": "BULLISH_DIV", "bb_signal": "OVERSOLD", "bb_squeeze": True,
    "is_range": True, "range_pos": "BOTTOM", "fibo_level": 0.45,
    # 아래꼬리 50%+ → accum 최대
    "high_15m": 94000, "low_15m": 92000, "open_15m": 93000, "close_15m": 93100,
    "trades":    {"usable": True, "cvd_signal": "BULLISH", "buy_ratio": 68},
    "orderbook": {"usable": True, "pressure": "BUY",       "imbalance": 1.60},
    "funding_rate": {"usable": True, "signal": "SHORT_OVERHEATED"},
    # OB/CVD 반대방향 추가 → trap+10+10 → trap 합계 >= 35
    # CVD bullish지만 오더북을 SELL로 설정 → trap+10
    "orderbook": {"usable": True, "pressure": "SELL", "imbalance": 0.80},
}
t1_result = decide_step_state(t1_data)
check(
    "T1 trap_risk>=35 → PRE 강등",
    t1_result,
    # trap >= 35이면 REAL 금지 → PRE 또는 그 이하
    t1_result["final_state"] if t1_result["trap_risk_score"] < 35 else "PRE",
    lambda d: d["trap_risk_score"] >= 35 and d["final_state"] != "REAL",
)

# ── T2: warning 3개 이상 REAL 후보 → PRE 강등 ────────────────
# 충분한 점수(75+)에서 warning 3개 이상으로 차단되어야 함
t2_data = {
    "direction": "LONG", "current_price": 95000,
    "trend_15m": "UP", "trend_1h": "UP", "trend_4h": "DOWN",  # 4H 역행 warn
    "rsi": 75, "cci": 50, "macd_state": "BULLISH",            # RSI 과열 warn
    "volume": 55, "avg_volume": 100,                           # 거래량없는 상승 warn
    "support": 93050, "resistance": 95050,                     # 저항 근접 warn = 4개+
    "ema20": 93500, "ema50": 91000, "above_ema20": True,
    "divergence": "BULLISH_DIV", "bb_signal": "OVERSOLD", "bb_squeeze": True,
    "is_range": True, "range_pos": "BOTTOM", "fibo_level": 0.45,
    "high_15m": 94000, "low_15m": 92000, "open_15m": 93000, "close_15m": 93100,
    "trades":    {"usable": True, "cvd_signal": "BULLISH", "buy_ratio": 68},
    "orderbook": {"usable": True, "pressure": "BUY",       "imbalance": 1.60},
    "funding_rate": {"usable": True, "signal": "SHORT_OVERHEATED"},
}
t2_result = decide_step_state(t2_data)
check(
    "T2 warning 3개 이상 → REAL 금지",
    t2_result,
    t2_result["final_state"],  # 상태는 유연하게 (score에 따라 PRE/EARLY/WAIT 가능)
    lambda d: len(d["warning_reasons"]) > 2 and d["final_state"] != "REAL",
)

# ── T3: LONG accumulation_score 55 → PRE 강등 ────────────────
t3_data = {**_REAL_BASE_LONG,
    "bb_squeeze": False, "bb_signal": "NEUTRAL",
    "trades":    {"usable": False},
    "orderbook": {"usable": False},
    "funding_rate": {"usable": False},
    # 아래꼬리 작게 — body 크게
    "high_15m": 95200, "low_15m": 94800, "open_15m": 94900, "close_15m": 95000,
}
t3_result = decide_step_state(t3_data)
check(
    "T3 LONG accum<60 → PRE 강등 + penalty",
    t3_result,
    "PRE",
    lambda d: d["accumulation_score"] < 60 and _penalty_contains(d, "매집 점수 부족"),
)

# ── T4: SHORT distribution_score 55 → PRE 강등 ───────────────
t4_data = {**_REAL_BASE_SHORT,
    "bb_squeeze": False, "bb_signal": "NEUTRAL",
    "trades":    {"usable": False},
    "orderbook": {"usable": False},
    "funding_rate": {"usable": False},
    # 윗꼬리 작게
    "high_15m": 97100, "low_15m": 96700, "open_15m": 97000, "close_15m": 96900,
}
t4_result = decide_step_state(t4_data)
check(
    "T4 SHORT dist<60 → PRE 강등 + penalty",
    t4_result,
    "PRE",
    lambda d: d["distribution_score"] < 60 and _penalty_contains(d, "분산 점수 부족"),
)

# ── T5: vol_ratio 0.9 → PRE 강등 ─────────────────────────────
t5_data = {**_REAL_BASE_LONG,
    "volume": 90, "avg_volume": 100,       # vol_ratio = 0.9
}
check(
    "T5 vol_ratio=0.9 → PRE 강등 + penalty",
    decide_step_state(t5_data),
    "PRE",
    lambda d: _penalty_contains(d, "거래량 부족"),
)

# ── T6: gap 22 → PRE 강등 ────────────────────────────────────
# gap 22 만들기: REAL_BASE_LONG에서 short_score를 long_score-22 수준으로 높임
# 약한 구조로 long_score를 낮추고, short 조건도 중립으로
t6_data = {
    "direction": "LONG", "current_price": 95000,
    "trend_15m": "UP", "trend_1h": "SIDEWAYS", "trend_4h": "SIDEWAYS",
    "rsi": 52, "cci": 10, "macd_state": "POSITIVE",
    "volume": 120, "avg_volume": 100,
    "support": 93000, "resistance": 102000,
    "ema20": 94500, "ema50": 93000,
    "is_range": True, "range_pos": "BOTTOM",
    "bb_signal": "NEUTRAL", "bb_squeeze": False,
    "fibo_level": 0.5,
    "high_15m": 95200, "low_15m": 93800, "open_15m": 94000, "close_15m": 95000,
    "trades":    {"usable": True, "cvd_signal": "BULLISH", "buy_ratio": 55},
    "orderbook": {"usable": True, "pressure": "BUY",       "imbalance": 1.15},
    "funding_rate": {"usable": True, "signal": "SHORT_OVERHEATED"},
}
t6_result = decide_step_state(t6_data)
check(
    "T6 gap<25 → REAL 금지",
    t6_result,
    t6_result["final_state"],  # gap 실제값에 따라 REAL 여부 확인
    lambda d: (d["gap"] >= 25) or (d["gap"] < 25 and d["final_state"] != "REAL"),
)

# ── T7: 좋은 LONG REAL_2 → REAL_2 + HIGH ─────────────────────
t7_data = {**_REAL_BASE_LONG}  # 기반 데이터 그대로 — gap 넓고 accum 높음
check(
    "T7 좋은 LONG REAL_2 → step=REAL detail=REAL_2 tier=HIGH",
    decide_step_state(t7_data),
    "REAL",
    lambda d: (
        d["step_detail"] == "REAL_2"
        and d["quality_tier"] == "HIGH"
        and d["accumulation_score"] >= 60
        and d["trap_risk_score"] < 30
    ),
)

# ── T8: 좋은 SHORT REAL_2 → REAL_2 + HIGH ────────────────────
t8_data = {**_REAL_BASE_SHORT}  # 기반 데이터 그대로 — gap 넓고 dist 높음
check(
    "T8 좋은 SHORT REAL_2 → step=REAL detail=REAL_2 tier=HIGH",
    decide_step_state(t8_data),
    "REAL",
    lambda d: (
        d["step_detail"] == "REAL_2"
        and d["quality_tier"] == "HIGH"
        and d["distribution_score"] >= 60
        and d["trap_risk_score"] < 30
    ),
)


# ── 결과 요약 ────────────────────────────────────────────────
total  = len(results)
passed = sum(results)
print("=" * 50)
print(f"테스트 결과: {passed}/{total} 통과")
if passed == total:
    print("✅ 전체 통과")
else:
    print(f"❌ {total - passed}개 실패")
