# chart_renderer.py
# 진입레이더 카드 이미지(PNG) 생성
# 기존 카드 디자인 유지 + Railway 한글 폰트 직접 로딩 안정 버전
# 수정 반영:
# 1. MACD 위치 오류 수정: RSI/CCI와 같은 지표 그리드에 포함
# 2. 제한 사유 개선: reason 단일값이 아니라 진입 제한 사유 자동 생성

import io
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────
# 한글 폰트 직접 로딩
# ─────────────────────────────────────────────

def _setup_korean_font():
    import matplotlib
    import matplotlib.font_manager as fm

    base_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(base_dir, "fonts")

    font_candidates = [
        "NanumGothic-Regular.ttf",
        "NanumGothic-Bold.ttf",
        "NanumGothic-ExtraBold.ttf",
        "NanumGothic.ttf",
        "NanumGothicBold.ttf",
        "NanumGothicExtraBold.ttf",
    ]

    for font_name in font_candidates:
        font_path = os.path.join(font_dir, font_name)
        if os.path.exists(font_path):
            fm.fontManager.addfont(font_path)
            prop = fm.FontProperties(fname=font_path)
            matplotlib.rcParams["font.family"] = prop.get_name()
            matplotlib.rcParams["axes.unicode_minus"] = False
            return prop.get_name()

    matplotlib.rcParams["font.family"] = "DejaVu Sans"
    matplotlib.rcParams["axes.unicode_minus"] = False
    return "DejaVu Sans"


_KOREAN_FONT = _setup_korean_font()


# ─────────────────────────────────────────────
# 색상 팔레트
# ─────────────────────────────────────────────

BG_DARK    = "#0d1117"
BG_CARD    = "#161b22"
BG_CELL    = "#1c2128"
TEXT_WHITE = "#e6edf3"
TEXT_MUTED = "#8b949e"
RED        = "#f85149"
GREEN      = "#3fb950"
AMBER      = "#d29922"
PURPLE     = "#a78bfa"
LIME_GREEN = "#4ade80"

_TREND_KO = {
    "UP": "상승",
    "DOWN": "하락",
    "SIDEWAYS": "횡보",
}

_MACD_KO = {
    "BULLISH": "강세↑",
    "BEARISH": "약세↓",
    "POSITIVE": "양전환",
    "NEGATIVE": "음전환",
    "NEUTRAL": "중립",
}

_DIV_KO = {
    "BULLISH_DIV": "상승 다이버전스",
    "BEARISH_DIV": "하락 다이버전스",
}


def _trend_color(trend):
    if trend == "UP":
        return GREEN
    if trend == "DOWN":
        return RED
    return TEXT_MUTED


def _safe_num(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _sig_get(sig, *keys, default=None):
    for key in keys:
        if key in sig and sig.get(key) is not None:
            return sig.get(key)
    return default


def _split_symbol(symbol):
    symbol = str(symbol or "")
    if symbol.endswith("USDT"):
        return symbol[:-4], "USDT"
    if len(symbol) > 4:
        return symbol[:3], symbol[3:]
    return symbol, ""


def _build_limit_reasons(sig):
    """
    제한 = 지금 진입하면 안 되는 이유
    reason 하나만 출력하지 않고, 현재 신호 데이터에서 제한 사유를 자동 생성한다.
    """
    reasons = []

    confidence = int(_sig_get(sig, "confidence", "confidence_score", default=0))
    direction = _sig_get(sig, "direction", default="WAIT")

    is_range = _sig_get(sig, "is_range", default=False)
    range_position = _sig_get(sig, "range_position", default=None)

    trend_15m = _sig_get(sig, "trend_15m", default="SIDEWAYS")
    trend_1h = _sig_get(sig, "trend_1h", default="SIDEWAYS")

    volume = _safe_num(_sig_get(sig, "volume", default=0))
    avg_volume = _safe_num(_sig_get(sig, "avg_volume_20", default=0))

    raw_reason = _sig_get(sig, "reason", default="")

    if confidence < 60:
        reasons.append("신뢰도 60% 미만")

    if is_range and range_position == "MIDDLE":
        reasons.append("박스권 중앙")

    if direction == "LONG":
        if trend_15m != "UP":
            reasons.append("15M 상승 미확정")
        if trend_1h == "DOWN":
            reasons.append("1H 하락 충돌")

    elif direction == "SHORT":
        if trend_15m != "DOWN":
            reasons.append("15M 하락 미확정")
        if trend_1h == "UP":
            reasons.append("1H 상승 충돌")

    else:
        reasons.append("방향 미확정")

    if avg_volume > 0 and volume < avg_volume * 0.8:
        reasons.append("거래량 부족")

    if not reasons:
        if raw_reason:
            reasons.append(raw_reason)
        else:
            reasons.append("진입 조건 미완성")

    # 중복 제거
    unique = []
    for r in reasons:
        if r and r not in unique:
            unique.append(r)

    return unique[:3]


# ─────────────────────────────────────────────
# 단일 카드 이미지 생성
# ─────────────────────────────────────────────

def render_radar_card(sig: dict, candles_15m: list) -> bytes:
    """
    sig: core_analyzer / entry_timing 분석 결과
    candles_15m: 최근 15분봉 캔들 리스트
    반환: PNG bytes
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch, Rectangle
    except ImportError:
        raise RuntimeError("pip install matplotlib 필요")

    # ── 데이터 추출 ──────────────────────────
    symbol      = _sig_get(sig, "symbol", default="UNKNOWN")
    direction   = _sig_get(sig, "direction", default="WAIT")
    long_score  = int(_sig_get(sig, "long_score", default=0))
    short_score = int(_sig_get(sig, "short_score", default=0))
    gap         = abs(long_score - short_score)

    rsi_val  = _safe_num(_sig_get(sig, "rsi", default=50))
    cci_val  = _safe_num(_sig_get(sig, "cci", default=0))
    macd_raw = _sig_get(sig, "macd_state", default="NEUTRAL")

    trend_15m  = _sig_get(sig, "trend_15m", default="SIDEWAYS")
    trend_1h   = _sig_get(sig, "trend_1h",  default="SIDEWAYS")

    support    = _safe_num(_sig_get(sig, "support",    default=0))
    resistance = _safe_num(_sig_get(sig, "resistance", default=0))
    mid        = (support + resistance) / 2 if support and resistance else 0

    is_range  = bool(_sig_get(sig, "is_range",  default=False))
    range_pos = _sig_get(sig, "range_pos", default=None)

    volume       = _safe_num(_sig_get(sig, "volume",     default=0))
    avg_volume   = _safe_num(_sig_get(sig, "avg_volume", default=0))
    volume_ratio = _safe_num(_sig_get(sig, "volume_ratio", default=0))
    if volume_ratio == 0 and avg_volume > 0:
        volume_ratio = volume / avg_volume

    div    = _sig_get(sig, "divergence", default=None)
    is_btc = "BTC" in str(symbol).upper()
    accent = LIME_GREEN if is_btc else PURPLE

    # 신호 강도
    if gap < 15:   strength = "매우 약한 신호"
    elif gap < 25: strength = "약한 신호"
    elif gap < 40: strength = "보통 신호"
    else:          strength = "강한 신호"

    # 지지방향 배지
    if direction == "SHORT":
        badge_label, badge_color = "SHORT 지지", RED
    elif direction == "LONG":
        badge_label, badge_color = "LONG 지지",  GREEN
    else:
        badge_label, badge_color = "방향 대기",  TEXT_MUTED

    # ── 캔들 ──────────────────────────────────
    candles = (candles_15m or [])[-30:]
    n = len(candles)

    def _f(c, k):
        try: return float(c.get(k, 0) or 0)
        except: return 0.0

    opens  = [_f(c,"open")  for c in candles]
    highs  = [_f(c,"high")  for c in candles]
    lows   = [_f(c,"low")   for c in candles]
    closes = [_f(c,"close") for c in candles]
    now_price = closes[-1] if closes else 0

    def ema_series(vals, period=20):
        if not vals: return []
        k = 2/(period+1); out=[vals[0]]
        for v in vals[1:]: out.append(v*k+out[-1]*(1-k))
        return out

    ema20_series = ema_series(closes)

    # ── RSI 해석 ─────────────────────────────
    if rsi_val < 30:   rsi_txt, rsi_c = "강한 과매도 · 반등 신호", GREEN
    elif rsi_val < 45: rsi_txt, rsi_c = "과매도 구간",              GREEN
    elif rsi_val < 55: rsi_txt, rsi_c = "중립",                     TEXT_MUTED
    elif rsi_val < 70: rsi_txt, rsi_c = "과매수 구간",              RED
    else:              rsi_txt, rsi_c = "강한 과매수 · 조정 신호",  RED

    # ── CCI 해석 ─────────────────────────────
    if cci_val < -200:   cci_txt, cci_c = "극단 과매도",    GREEN
    elif cci_val < -100: cci_txt, cci_c = "강한 하락 압력", RED
    elif cci_val < 0:    cci_txt, cci_c = "약한 하락",      TEXT_MUTED
    elif cci_val < 100:  cci_txt, cci_c = "약한 상승",      TEXT_MUTED
    else:                cci_txt, cci_c = "강한 상승 압력", GREEN

    # ── MACD 해석 ────────────────────────────
    _mmap = {
        "BULLISH":  ("강세↑",  GREEN,      "상승 추세 강화"),
        "BEARISH":  ("약세↓",  RED,        "하락 추세 강화"),
        "POSITIVE": ("양전환", GREEN,      "상승 전환 시도"),
        "NEGATIVE": ("음전환", RED,        "하락 전환 시도"),
        "NEUTRAL":  ("중립",   TEXT_MUTED, "방향 미확정"),
    }
    macd_str, macd_c, macd_desc = _mmap.get(macd_raw, ("중립", TEXT_MUTED, "방향 미확정"))

    # ── 시간봉 해석 ──────────────────────────
    def tf_info(t):
        if t == "UP":   return "상승", GREEN,     "매수 우세"
        if t == "DOWN": return "하락", RED,       "매도 우세"
        return                 "횡보", TEXT_MUTED,"방향 미확정"

    t15_txt, t15_c, t15_desc = tf_info(trend_15m)
    t1h_txt, t1h_c, t1h_desc = tf_info(trend_1h)

    if trend_15m == "UP"   and trend_1h == "UP":
        tf_summary, tf_sum_c = "단기·중기 상승 일치",        GREEN
    elif trend_15m == "DOWN" and trend_1h == "DOWN":
        tf_summary, tf_sum_c = "단기·중기 하락 일치",        RED
    elif trend_15m != trend_1h and "SIDEWAYS" not in [trend_15m, trend_1h]:
        tf_summary, tf_sum_c = "단기·중기 충돌 · 추격 위험", AMBER
    else:
        tf_summary, tf_sum_c = "방향 미확정 · 대기",         TEXT_MUTED

    # ── 지표 충돌 ────────────────────────────
    conflict = (rsi_val < 45 and macd_raw in ("BULLISH","POSITIVE") and cci_val < -100)

    # ── 박스 위치 ────────────────────────────
    if not is_range:
        pos_dot, pos_txt = TEXT_MUTED, "추세 구간 · 박스권 아님 · 추세 방향 따라가기"
    elif range_pos == "MIDDLE":
        pos_dot, pos_txt = AMBER, f"박스 중앙 · {support:.0f}~{resistance:.0f} · 양방향 노이즈 · 진입 금지"
    elif range_pos == "TOP":
        pos_dot, pos_txt = RED,   "박스 상단 · 저항 근접 · 돌파 실패 시 숏 후보"
    else:
        pos_dot, pos_txt = GREEN, "박스 하단 · 지지 근접 · 이탈 실패 시 롱 후보"

    # ── 거래량 바 ────────────────────────────
    vol_fill  = min(volume_ratio / 1.2, 1.0)
    vol_ok    = volume_ratio >= 1.2
    vol_bar_c = GREEN if vol_ok else AMBER
    vol_pct   = max(0, (1.2 - volume_ratio) / 1.2 * 100)
    vol_txt   = "조건 충족" if vol_ok else f"{vol_pct:.0f}% 부족"
    vol_txt_c = GREEN if vol_ok else RED

    # ── Figure ───────────────────────────────
    fig = plt.figure(figsize=(6, 13.0), facecolor=BG_DARK)
    fig.patch.set_facecolor(BG_DARK)
    gs = fig.add_gridspec(6, 1,
        height_ratios=[0.5, 0.55, 2.8, 0.3, 1.2, 2.0],
        hspace=0.07, left=0.03, right=0.97, top=0.97, bottom=0.02)

    # ── 행0: 헤더 ────────────────────────────
    ax = fig.add_subplot(gs[0])
    ax.set_facecolor(BG_DARK); ax.axis("off")
    base, quote = _split_symbol(symbol)
    ax.text(0.02, 0.55, base,  color=accent,    fontsize=20, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.22, 0.55, quote, color=TEXT_WHITE, fontsize=14, va="center",      transform=ax.transAxes)
    ax.text(0.72, 0.55, "진입레이더", color="#ffffff", fontsize=10, va="center", ha="center",
            transform=ax.transAxes,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#7c3aed", edgecolor="none"))
    ax.text(0.97, 0.55,
            _sig_get(sig, "timestamp", default=datetime.now(KST).strftime("%H:%M")),
            color=TEXT_MUTED, fontsize=10, va="center", ha="right", transform=ax.transAxes)
    ax.axhline(0.05, color="#21262d", linewidth=0.8)

    # ── 행1: 지지방향 바 ─────────────────────
    ax = fig.add_subplot(gs[1])
    ax.set_facecolor(BG_DARK); ax.axis("off")
    ax.set_xlim(0,1); ax.set_ylim(0,1)
    ax.text(0.02, 0.88, badge_label, color="white", fontsize=9, fontweight="bold",
            va="top", transform=ax.transAxes,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=badge_color, edgecolor="none"))
    ax.text(0.28, 0.88, f"차이 {gap}%p · {strength}", color=TEXT_MUTED, fontsize=8, va="top", transform=ax.transAxes)
    ax.text(0.97, 0.88, "감시구간", color=TEXT_MUTED, fontsize=8, va="top", ha="right", transform=ax.transAxes)
    bar_y, bar_h = 0.38, 0.28
    ax.barh(bar_y, 1.0,             height=bar_h, color="#21262d", align="edge", left=0)
    ax.barh(bar_y, long_score/100,  height=bar_h, color=GREEN,     align="edge", left=0)
    ax.barh(bar_y, short_score/100, height=bar_h, color=RED,       align="edge", left=1-(short_score/100))
    ax.text(0.02, 0.05, f"LONG {long_score}%",  color=GREEN, fontsize=9, fontweight="bold", va="bottom", transform=ax.transAxes)
    ax.text(0.97, 0.05, f"SHORT {short_score}%", color=RED,  fontsize=9, fontweight="bold", ha="right", va="bottom", transform=ax.transAxes)

    # ── 행2: 캔들차트 ────────────────────────
    ax_chart = fig.add_subplot(gs[2])
    ax_chart.set_facecolor(BG_CELL)
    for sp in ax_chart.spines.values(): sp.set_edgecolor("#21262d")
    if n > 0 and any(closes):
        xs = range(n)
        for i,(o,h,l,c) in enumerate(zip(opens,highs,lows,closes)):
            col = GREEN if c>=o else RED
            ax_chart.plot([i,i],[l,h], color=col, linewidth=0.8, zorder=2)
            bh = abs(c-o) or max((h-l)*0.01,0.0001)
            ax_chart.add_patch(Rectangle((i-0.3,min(o,c)),0.6,bh,color=col,zorder=3))
        if len(ema20_series)==n:
            ax_chart.plot(list(xs), ema20_series, color=AMBER, linewidth=1.3, zorder=4)
        hi  = max(highs); lo = min(lows)
        pad = (hi-lo)*0.12 if hi!=lo else 1
        if is_range and resistance>0:
            ax_chart.axhline(resistance, color=RED,   linewidth=0.8, linestyle="--", alpha=0.75, zorder=5)
            ax_chart.text(n-0.5, resistance, f"박스상단 {resistance:.0f}", color=RED,   fontsize=7, va="bottom", ha="right")
        if is_range and mid>0:
            ax_chart.axhline(mid,        color=AMBER, linewidth=0.6, linestyle="--", alpha=0.45, zorder=5)
            ax_chart.text(n-0.5, mid,        f"중앙 {mid:.0f}",         color=AMBER, fontsize=7, va="bottom", ha="right")
        if is_range and support>0:
            ax_chart.axhline(support,    color=GREEN, linewidth=0.8, linestyle="--", alpha=0.75, zorder=5)
            ax_chart.text(n-0.5, support,    f"박스하단 {support:.0f}",  color=GREEN, fontsize=7, va="top",    ha="right")
        if now_price>0:
            ax_chart.axhline(now_price, color=TEXT_MUTED, linewidth=0.5, linestyle="--", alpha=0.6, zorder=5)
            ax_chart.text(n-0.5, now_price, f"{now_price:.1f}", color=TEXT_WHITE, fontsize=7, va="bottom", ha="right")
        ax_chart.set_xlim(-0.5, n+0.5)
        ax_chart.set_ylim(lo-pad, hi+pad)
    ax_chart.text(0.02,0.96,"15M 캔들차트",color=TEXT_MUTED,fontsize=8,va="top",transform=ax_chart.transAxes)
    ax_chart.text(0.97,0.96,"─ EMA20",     color=AMBER,    fontsize=8,va="top",ha="right",transform=ax_chart.transAxes)
    ax_chart.tick_params(colors=TEXT_MUTED,labelsize=7)
    ax_chart.yaxis.tick_right()

    # ── 행3: 현재 위치 ───────────────────────
    ax = fig.add_subplot(gs[3])
    ax.set_facecolor(BG_DARK); ax.axis("off")
    ax.plot(0.02, 0.5, "o", color=pos_dot, markersize=6, transform=ax.transAxes)
    ax.text(0.06, 0.5, pos_txt, color=TEXT_WHITE, fontsize=8.5, va="center", transform=ax.transAxes)

    # ── 행4: 진입 조건 + 거래량 ─────────────
    ax = fig.add_subplot(gs[4])
    ax.set_facecolor(BG_DARK); ax.axis("off")
    ax.set_xlim(0,1); ax.set_ylim(0,1)
    # 숏
    ax.add_patch(FancyBboxPatch((0.0,0.74),0.99,0.22,boxstyle="round,pad=0.01",
        facecolor="#1a0d0d",edgecolor="#7f1d1d",linewidth=0.6,transform=ax.transAxes))
    ax.text(0.02,0.85,"숏",              color=RED,       fontsize=10,fontweight="bold",va="center",transform=ax.transAxes)
    ax.text(0.10,0.85,f"{support:.0f} 이탈",color=TEXT_WHITE,fontsize=9,va="center",transform=ax.transAxes)
    ax.text(0.38,0.85,"+",              color=TEXT_MUTED,fontsize=9,va="center",transform=ax.transAxes)
    ax.text(0.43,0.85,"거래량 1.2배+", color=TEXT_WHITE,fontsize=9,va="center",transform=ax.transAxes)
    ax.text(0.97,0.85,f"현재 {volume_ratio:.1f}배",color=AMBER,fontsize=9,ha="right",va="center",transform=ax.transAxes)
    # 롱
    ax.add_patch(FancyBboxPatch((0.0,0.50),0.99,0.22,boxstyle="round,pad=0.01",
        facecolor="#0d1a0d",edgecolor="#1a4d1a",linewidth=0.6,transform=ax.transAxes))
    ax.text(0.02,0.61,"롱",              color=GREEN,     fontsize=10,fontweight="bold",va="center",transform=ax.transAxes)
    ax.text(0.10,0.61,f"{resistance:.0f} 돌파",color=TEXT_WHITE,fontsize=9,va="center",transform=ax.transAxes)
    ax.text(0.38,0.61,"+",              color=TEXT_MUTED,fontsize=9,va="center",transform=ax.transAxes)
    ax.text(0.43,0.61,"거래량 1.2배+", color=TEXT_WHITE,fontsize=9,va="center",transform=ax.transAxes)
    ax.text(0.97,0.61,f"현재 {volume_ratio:.1f}배",color=AMBER,fontsize=9,ha="right",va="center",transform=ax.transAxes)
    # 거래량 바
    ax.add_patch(FancyBboxPatch((0.0,0.0),0.99,0.46,boxstyle="round,pad=0.01",
        facecolor=BG_CELL,edgecolor="#21262d",linewidth=0.5,transform=ax.transAxes))
    ax.text(0.03,0.42,"거래량 진행도 (숏·롱 공통)",color=TEXT_MUTED,fontsize=8,va="top",transform=ax.transAxes)
    ax.text(0.97,0.42,vol_txt,color=vol_txt_c,fontsize=8,ha="right",va="top",transform=ax.transAxes)
    ax.add_patch(Rectangle((0.03,0.18),0.94,0.14,     facecolor="#21262d",transform=ax.transAxes))
    ax.add_patch(Rectangle((0.03,0.18),0.94*vol_fill,0.14,facecolor=vol_bar_c,transform=ax.transAxes))
    ax.text(0.03,0.14,"0배",      color=TEXT_MUTED,fontsize=7.5,va="top",transform=ax.transAxes)
    ax.text(0.97,0.14,"기준 1.2배",color=GREEN,    fontsize=7.5,ha="right",va="top",transform=ax.transAxes)
    ax.text(0.03,0.04,"거래량 없는 이탈/돌파 = 가짜 신호 가능성 높음 · 1.2배 미만이면 관망",
            color=TEXT_MUTED,fontsize=7.5,va="bottom",transform=ax.transAxes)

    # ── 행5: 시간봉 + 지표 ───────────────────
    ax = fig.add_subplot(gs[5])
    ax.set_facecolor(BG_DARK); ax.axis("off")
    ax.set_xlim(0,1); ax.set_ylim(0,1)
    # 시간봉 패널
    ax.add_patch(FancyBboxPatch((0.0,0.0),0.455,0.99,boxstyle="round,pad=0.01",
        facecolor=BG_CELL,edgecolor="#21262d",linewidth=0.5,transform=ax.transAxes))
    ax.text(0.03,0.97,"시간봉 구조",color=TEXT_MUTED,fontsize=8,fontweight="bold",va="top",transform=ax.transAxes)
    # 15M
    ax.text(0.03,0.89,"15M · 단기",color=TEXT_MUTED,fontsize=7.5,va="top",transform=ax.transAxes)
    ax.text(0.03,0.79,t15_txt,    color=t15_c,     fontsize=13,fontweight="bold",va="top",transform=ax.transAxes)
    ax.text(0.03,0.69,t15_desc,   color=TEXT_MUTED,fontsize=7.5,va="top",transform=ax.transAxes)
    # 구분선
    ax.add_patch(Rectangle((0.03,0.635),0.415,0.005,facecolor="#21262d",transform=ax.transAxes))
    # 1H
    ax.text(0.03,0.62,"1H · 중기", color=TEXT_MUTED,fontsize=7.5,va="top",transform=ax.transAxes)
    ax.text(0.03,0.52,t1h_txt,     color=t1h_c,    fontsize=13,fontweight="bold",va="top",transform=ax.transAxes)
    ax.text(0.03,0.42,t1h_desc,    color=TEXT_MUTED,fontsize=7.5,va="top",transform=ax.transAxes)
    # 구분선
    ax.add_patch(Rectangle((0.03,0.365),0.415,0.005,facecolor="#21262d",transform=ax.transAxes))
    # 종합
    ax.text(0.03,0.34,"종합",      color=TEXT_MUTED,fontsize=7.5,va="top",transform=ax.transAxes)
    ax.text(0.03,0.24,tf_summary,  color=tf_sum_c, fontsize=8,fontweight="bold",va="top",transform=ax.transAxes)

    # 지표 패널
    ax.add_patch(FancyBboxPatch((0.47,0.0),0.53,0.99,boxstyle="round,pad=0.01",
        facecolor=BG_CELL,edgecolor="#21262d",linewidth=0.5,transform=ax.transAxes))
    ax.text(0.49,0.97,"지표 분석",color=TEXT_MUTED,fontsize=8,fontweight="bold",va="top",transform=ax.transAxes)
    for idx,(lbl,val,desc,col) in enumerate([
        ("RSI",  f"{rsi_val:.1f}", rsi_txt,   rsi_c),
        ("CCI",  f"{cci_val:.0f}", cci_txt,   cci_c),
        ("MACD", macd_str,         macd_desc,  macd_c),
    ]):
        yt = 0.87 - idx * 0.29
        ax.text(0.49, yt,       lbl,  color=TEXT_MUTED, fontsize=7.5, va="top", transform=ax.transAxes)
        ax.text(0.49, yt-0.09,  val,  color=col,        fontsize=11,  fontweight="bold", va="top", transform=ax.transAxes)
        ax.text(0.49, yt-0.18,  desc, color=TEXT_MUTED, fontsize=7.5, va="top", transform=ax.transAxes)
    if conflict:
        ax.add_patch(FancyBboxPatch((0.47,0.0),0.53,0.17,boxstyle="round,pad=0.01",
            facecolor="#1a1200",edgecolor="#d29922",linewidth=0.5,transform=ax.transAxes))
        ax.text(0.49,0.15,"지표 충돌",color=AMBER,fontsize=8,fontweight="bold",va="top",transform=ax.transAxes)
        ax.text(0.49,0.07,"손절 확률 상승 · 이탈 후 일치 확인",color=AMBER,fontsize=7,va="top",transform=ax.transAxes)
    if div:
        ax.text(0.49,0.01,_DIV_KO.get(div,div),
                color=GREEN if div=="BULLISH_DIV" else RED,fontsize=7.5,va="bottom",transform=ax.transAxes)

    # ── PNG 반환 ─────────────────────────────
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG_DARK)
    plt.close(fig)
    buf.seek(0)
    return buf.read()

async def send_radar_album(bot, chat_id: str, signals: list, candles_map: dict):
    """
    signals: [eth_sig, btc_sig]
    candles_map: {"ETHUSDT": {"15m": [...]}, "BTCUSDT": {"15m": [...]}}
    이미지 1~2장을 텔레그램 앨범으로 전송
    """
    try:
        from telegram import InputMediaPhoto
    except ImportError:
        raise RuntimeError("pip install python-telegram-bot 필요")

    media = []

    for sig in signals:
        symbol = sig.get("symbol")
        candles = candles_map.get(symbol, {}).get("15m", [])
        png = render_radar_card(sig, candles)
        media.append(InputMediaPhoto(media=png))

    if len(media) == 1:
        await bot.send_photo(chat_id=chat_id, photo=media[0].media)
    elif len(media) >= 2:
        await bot.send_media_group(chat_id=chat_id, media=media)


async def send_single_radar(bot, chat_id: str, sig: dict, candles_15m: list):
    """
    단일 종목 카드 전송
    """
    png = render_radar_card(sig, candles_15m)
    await bot.send_photo(chat_id=chat_id, photo=png)
