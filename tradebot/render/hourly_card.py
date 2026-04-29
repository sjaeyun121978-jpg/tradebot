# hourly_card.py
# 1H 마감 종합 전광판 이미지 카드 렌더러
# 역할: 1시간 브리핑 전용 UI만 담당한다. 분석과 전송은 담당하지 않는다.

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from tradebot.render.radar_card import (
    FONT_PROP,
    now_kst,
    BG,
    BG2,
    PANEL,
    PANEL2,
    BORDER,
    WHITE,
    TEXT,
    MUTED,
    DIM,
    GREEN,
    GREEN_DARK,
    RED,
    RED_DARK,
    AMBER,
    AMBER_DARK,
    PURPLE,
    GRAY_BAR,
    _safe,
    _get,
    _fmt,
    _fmt_price,
    _split_symbol,
    _trend_color,
    _trend_ko,
    _macd_ko,
    _entry_label,
    _compact_reason_text,
    _draw_chart,
)


def _bias_label(sig):
    if sig.get("bias"):
        return str(sig.get("bias"))
    ls = _safe(sig.get("long_score"), 0)
    ss = _safe(sig.get("short_score"), 0)
    gap = abs(ls - ss)
    if gap < 15:
        return "중립"
    if ls > ss:
        return "롱 우세" if gap >= 25 else "롱 약우세"
    return "숏 우세" if gap >= 25 else "숏 약우세"


def _state_to_badge(state, direction):
    txt = str(state or direction or "WAIT").upper()
    if "LONG" in txt:
        return "LONG", GREEN, GREEN_DARK
    if "SHORT" in txt:
        return "SHORT", RED, RED_DARK
    return "WAIT", AMBER, AMBER_DARK


def _div_label(v):
    m = {
        "BULLISH_DIV": ("상승 감지", GREEN, "가격/RSI 반등 가능"),
        "BEARISH_DIV": ("하락 감지", RED, "가격/RSI 조정 가능"),
        "NONE": ("없음", MUTED, "반전 신호 미감지"),
        None: ("없음", MUTED, "반전 신호 미감지"),
    }
    return m.get(v, (str(v), MUTED, "반전 신호 확인"))


def _structure_meaning(structure):
    s = str(structure or "-").upper()
    if "HH" in s and "HL" in s:
        return "상승 파동 진행 중", GREEN
    if "LH" in s and "LL" in s:
        return "하락 파동 진행 중", RED
    if s in ("-", "NONE", ""):
        return "구조 미확정", MUTED
    return "구조 확인 필요", AMBER


def _reason(sig):
    msg = _get(sig, "reason", "summary", default="")
    if msg:
        return _compact_reason_text(msg, max_len=28)
    is_range = bool(sig.get("is_range"))
    range_pos = str(sig.get("range_pos") or "").upper()
    vol = _safe(sig.get("volume_ratio"), 0)
    if is_range and range_pos == "MIDDLE":
        return "박스 중앙 / 방향 확정 대기"
    if is_range and range_pos == "TOP":
        return "박스 상단 / 돌파 확인 필요"
    if is_range and range_pos == "BOTTOM":
        return "박스 하단 / 이탈 확인 필요"
    if vol < 0.8:
        return "거래량 약함 / 추격 금지"
    return "1H 마감 기준 상황판"


def _conclusion(sig, support, resistance):
    direction = str(sig.get("direction") or "WAIT").upper()
    bias = _bias_label(sig)
    if "LONG" in direction:
        title = "결론 — LONG 우세"
        body1 = f"{_fmt(resistance)} 돌파 전 롱 추격 금지"
        body2 = f"{_fmt(support)} 이탈 시 관점 재검토"
        col = GREEN
    elif "SHORT" in direction:
        title = "결론 — SHORT 우세"
        body1 = f"{_fmt(support)} 이탈 전 숏 추격 금지"
        body2 = f"{_fmt(resistance)} 돌파 시 관점 재검토"
        col = RED
    else:
        title = "결론 — 관망"
        body1 = f"{_fmt(support)} 이탈 또는 {_fmt(resistance)} 돌파 전 진입 금지"
        body2 = "REAL 신호 오기 전 진입 금지"
        col = AMBER
    if bias and "우세" not in title and bias != "중립":
        title = f"결론 — {bias}"
    return title, body1, body2, col


def render_hourly_dashboard_card(sig: dict, candles_1h: list) -> bytes:
    """Render 1H dashboard card as PNG bytes."""
    sig = dict(sig or {})
    sig.setdefault("chart_tf", "1H")
    sig.setdefault("_chart_tf", "1H")

    symbol = _get(sig, "symbol", default="BTCUSDT")
    base, quote = _split_symbol(symbol)
    current_price = _safe(_get(sig, "current_price", "price", default=0))
    support = _safe(_get(sig, "support", "range_low", default=0))
    resistance = _safe(_get(sig, "resistance", "range_high", default=0))
    long_score = _safe(_get(sig, "long_score", default=0))
    short_score = _safe(_get(sig, "short_score", default=0))
    direction = str(_get(sig, "direction", default="WAIT") or "WAIT").upper()
    state = _get(sig, "state", default=direction)
    badge_txt, badge_color, badge_bg = _state_to_badge(state, direction)

    if current_price <= 0 and candles_1h:
        try:
            current_price = _safe(candles_1h[-1].get("close"))
        except Exception:
            pass

    total = max(long_score + short_score, 1)
    long_ratio = max(0.0, min(1.0, long_score / total))
    short_ratio = max(0.0, min(1.0, short_score / total))

    reason = _reason(sig)
    rsi = _safe(_get(sig, "rsi", default=50))
    cci = _safe(_get(sig, "cci", default=0))
    macd_label, macd_color, macd_desc = _macd_ko(_get(sig, "macd_state", default="NEUTRAL"))

    structure = str(_get(sig, "structure", default="-") or "-")
    structure_meaning, structure_color = _structure_meaning(structure)
    rsi_div, rsi_div_color, rsi_div_desc = _div_label(_get(sig, "divergence", default="NONE"))
    cci_div, cci_div_color, cci_div_desc = _div_label(_get(sig, "cci_divergence", default="NONE"))

    trend_15m = _get(sig, "trend_15m", default="SIDEWAYS")
    trend_30m = _get(sig, "trend_30m", default="SIDEWAYS")
    trend_1h = _get(sig, "trend_1h", default="SIDEWAYS")
    trend_4h = _get(sig, "trend_4h", default="SIDEWAYS")
    trend_1d = _get(sig, "trend_1d", default="SIDEWAYS")

    if sig.get("is_range"):
        range_pos = str(sig.get("range_pos") or "MIDDLE")
        pos_ko = {"TOP": "상단", "MIDDLE": "중앙", "BOTTOM": "하단"}.get(range_pos.upper(), range_pos)
        box_title = f"박스 {pos_ko}"
        box_text = f"{_fmt(support)}~{_fmt(resistance)} 사이 / 양방향 노이즈"
        box_color = AMBER if range_pos.upper() == "MIDDLE" else (RED if range_pos.upper() == "TOP" else GREEN)
    else:
        box_title = "감시구간"
        box_text = f"{_fmt(support)}~{_fmt(resistance)} / 돌파 확인"
        box_color = MUTED

    if trend_1h == trend_4h and trend_1h in ("UP", "DOWN"):
        tf_summary = f"상위봉 {_trend_ko(trend_1h)} 일치 / 단기 방향 확인"
        tf_color = _trend_color(trend_1h)
    else:
        tf_summary = "단기/중기 방향 충돌 / 확인 필요"
        tf_color = AMBER

    rsi_color = RED if rsi > 70 else (GREEN if rsi >= 55 else (RED if rsi <= 35 else TEXT))
    rsi_state = "과매수" if rsi > 70 else ("강세" if rsi >= 55 else ("과매도" if rsi <= 35 else "중립"))
    cci_color = GREEN if cci >= 100 else (RED if cci <= -100 else TEXT)
    cci_state = "상승압력" if cci >= 100 else ("하락압력" if cci <= -100 else ("약세" if cci < 0 else "강세"))
    conclusion_title, conclusion_body1, conclusion_body2, conclusion_color = _conclusion(sig, support, resistance)

    FIG_W, FIG_H, DPI = 7.2, 10.9, 160
    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    def T(x, y, s, size=10, color=WHITE, weight="normal", ha="left", va="center", alpha=1.0):
        ax.text(x, y, str(s), transform=ax.transAxes, fontsize=size, color=color,
                fontweight=weight, ha=ha, va=va, alpha=alpha, fontproperties=FONT_PROP)

    def RECT(x, y, w, h, face=PANEL, edge=BORDER, lw=1.0, r=0.018, alpha=1.0):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.002,rounding_size={r}",
                                    linewidth=lw, edgecolor=edge, facecolor=face,
                                    alpha=alpha, transform=ax.transAxes, clip_on=False))

    def HR(y, x0=0.045, x1=0.955, color=BORDER, lw=1.0):
        ax.plot([x0, x1], [y, y], transform=ax.transAxes, color=color, linewidth=lw)

    def DOT(x, y, r=0.006, color=GREEN):
        ax.add_patch(plt.Circle((x, y), r, color=color, transform=ax.transAxes, clip_on=False, zorder=5))

    RECT(0.030, 0.018, 0.940, 0.964, face=BG2, edge="#171b24", lw=1.0, r=0.030)

    # 카드 타입 라벨: 텔레그램에서 1H 브리핑임을 명확히 표시한다.
    T(0.060, 0.970, "1H 마감 브리핑", size=9.5, color=MUTED, weight="bold")

    # Header
    T(0.060, 0.945, base, size=27, color=PURPLE, weight="bold")
    T(0.185, 0.945, quote, size=17, color=WHITE, weight="bold")
    RECT(0.300, 0.925, 0.135, 0.040, face=badge_bg, edge=badge_color, lw=1.2, r=0.010)
    T(0.367, 0.945, "1H 전광판", size=10.5, color=badge_color, weight="bold", ha="center")
    T(0.367, 0.917, badge_txt, size=12.5, color=badge_color, weight="bold", ha="center")
    T(0.930, 0.952, _fmt_price(current_price), size=24, color=WHITE, weight="bold", ha="right")
    T(0.930, 0.915, now_kst().strftime("%H:%M KST"), size=13, color=MUTED, ha="right")
    HR(0.875, x0=0.030, x1=0.970, lw=1.2)

    # Signal block
    RECT(0.060, 0.826, 0.090, 0.034, face=badge_bg, edge=badge_color, lw=1.0, r=0.008)
    T(0.105, 0.843, badge_txt, size=11.5, color=badge_color, weight="bold", ha="center")
    T(0.170, 0.842, reason, size=12.4, color=MUTED, weight="bold")
    T(0.060, 0.803, f"LONG {long_score:.0f}%", size=12, color=GREEN, weight="bold")
    T(0.500, 0.803, "신호강도", size=11.5, color=MUTED, weight="bold", ha="center")
    T(0.925, 0.803, f"SHORT {short_score:.0f}%", size=12, color=RED, weight="bold", ha="right")
    BAR_X, BAR_Y, BAR_W, BAR_H = 0.060, 0.778, 0.865, 0.010
    RECT(BAR_X, BAR_Y, BAR_W, BAR_H, face=GRAY_BAR, edge=GRAY_BAR, lw=0, r=0.006)
    RECT(BAR_X, BAR_Y, BAR_W * long_ratio, BAR_H, face=GREEN, edge=GREEN, lw=0, r=0.006)
    if short_ratio >= 0.015:
        RECT(BAR_X + BAR_W * (1 - short_ratio), BAR_Y, BAR_W * short_ratio, BAR_H, face=RED, edge=RED, lw=0, r=0.006)
    HR(0.748, x0=0.030, x1=0.970, lw=1.1)

    # Chart card
    CHX, CHY, CHW, CHH = 0.060, 0.565, 0.865, 0.165
    RECT(CHX, CHY, CHW, CHH, face=PANEL, edge="#1e2530", lw=1.0, r=0.018)
    T(CHX + 0.025, CHY + CHH - 0.026, "1H 캔들차트", size=12.5, color=TEXT, weight="bold")
    T(CHX + CHW - 0.025, CHY + CHH - 0.026, "— EMA20", size=11.5, color=AMBER, weight="bold", ha="right")
    chart_ax = fig.add_axes([CHX + 0.025, CHY + 0.052, CHW - 0.050, CHH - 0.088])
    _draw_chart(chart_ax, candles_1h, sig, chart_tf="1H")
    DOT(CHX + 0.025, CHY + 0.023, r=0.007, color=box_color)
    T(CHX + 0.045, CHY + 0.023, box_title, size=12.5, color=box_color, weight="bold")
    T(CHX + 0.145, CHY + 0.023, box_text, size=11.8, color=TEXT)

    # Timeframe card
    TFX, TFY, TFW, TFH = 0.060, 0.465, 0.865, 0.078
    RECT(TFX, TFY, TFW, TFH, face=PANEL, edge="#1e2530", lw=1.0, r=0.014)
    T(TFX + 0.022, TFY + TFH - 0.022, "타임프레임", size=12, color=WHITE, weight="bold")
    tf_items = [("15M", trend_15m), ("30M", trend_30m), ("1H", trend_1h), ("4H", trend_4h)]
    for i, (lab, tr) in enumerate(tf_items):
        x = TFX + 0.040 + i * 0.205
        DOT(x, TFY + 0.040, r=0.006, color=_trend_color(tr))
        T(x + 0.017, TFY + 0.040, f"{lab} {_trend_ko(tr)}", size=10.8, color=TEXT, weight="bold")
    ax.plot([TFX + 0.024, TFX + 0.024], [TFY + 0.014, TFY + 0.028], transform=ax.transAxes, color=tf_color, linewidth=2.4)
    T(TFX + 0.043, TFY + 0.020, tf_summary, size=10.8, color=tf_color, weight="bold")

    # Structure / divergence card
    SX, SY, SW, SH = 0.060, 0.270, 0.865, 0.170
    RECT(SX, SY, SW, SH, face=PANEL, edge="#1e2530", lw=1.0, r=0.014)
    T(SX + 0.022, SY + SH - 0.023, "파동 구조 / 다이버전스", size=12, color=WHITE, weight="bold")
    RECT(SX + 0.022, SY + 0.105, SW - 0.044, 0.040, face="#10151f", edge="#10151f", lw=0, r=0.008)
    T(SX + 0.040, SY + 0.125, "가격 구조", size=9.5, color=MUTED, weight="bold")
    T(SX + 0.040, SY + 0.109, structure, size=13.5, color=structure_color, weight="bold")
    T(SX + SW - 0.040, SY + 0.125, "의미", size=9.5, color=MUTED, weight="bold", ha="right")
    T(SX + SW - 0.040, SY + 0.109, structure_meaning, size=11, color=structure_color, weight="bold", ha="right")
    cell_w = (SW - 0.060) / 2
    for j, (name, val, col, desc) in enumerate([
        ("RSI 다이버전스", rsi_div, rsi_div_color, rsi_div_desc),
        ("CCI 다이버전스", cci_div, cci_div_color, cci_div_desc),
    ]):
        x = SX + 0.022 + j * (cell_w + 0.016)
        RECT(x, SY + 0.040, cell_w, 0.052, face="#10151f", edge="#10151f", lw=0, r=0.008)
        T(x + 0.018, SY + 0.074, name, size=9.5, color=MUTED, weight="bold")
        DOT(x + 0.020, SY + 0.056, r=0.005, color=col)
        T(x + 0.035, SY + 0.056, val, size=10.5, color=col, weight="bold")
        T(x + 0.018, SY + 0.044, desc, size=8.5, color=MUTED)
    ax.plot([SX + 0.024, SX + 0.024], [SY + 0.014, SY + 0.033], transform=ax.transAxes, color=structure_color, linewidth=2.5)
    T(SX + 0.043, SY + 0.025, f"{structure_meaning} / {rsi_div if rsi_div != '없음' else '반전 신호 없음'}", size=10.5, color=structure_color, weight="bold")

    # Indicator + conclusion card
    IX, IY, IW, IH = 0.060, 0.045, 0.865, 0.200
    RECT(IX, IY, IW, IH, face=PANEL, edge="#1e2530", lw=1.0, r=0.014)
    T(IX + 0.022, IY + IH - 0.025, "지표", size=12, color=WHITE, weight="bold")
    card_y = IY + 0.088
    card_w = (IW - 0.076) / 3
    for j, (label, val, sub, col) in enumerate([
        ("RSI", f"{rsi:.1f}", rsi_state, rsi_color),
        ("CCI", f"{cci:.0f}", cci_state, cci_color),
        ("MACD", macd_label, macd_desc, macd_color),
    ]):
        x = IX + 0.022 + j * (card_w + 0.016)
        RECT(x, card_y, card_w, 0.064, face="#10151f", edge="#10151f", lw=0, r=0.008)
        T(x + card_w / 2, card_y + 0.044, label, size=9.5, color=MUTED, weight="bold", ha="center")
        T(x + card_w / 2, card_y + 0.028, val, size=13, color=col, weight="bold", ha="center")
        T(x + card_w / 2, card_y + 0.013, sub, size=8.8, color=col, weight="bold", ha="center")
    HR(IY + 0.075, x0=IX + 0.022, x1=IX + IW - 0.022, color=BORDER, lw=0.8)
    T(IX + 0.022, IY + 0.052, conclusion_title, size=12, color=conclusion_color, weight="bold")
    T(IX + 0.022, IY + 0.031, conclusion_body1, size=10.5, color=TEXT)
    T(IX + 0.022, IY + 0.014, conclusion_body2, size=10.5, color=AMBER if conclusion_color == AMBER else conclusion_color, weight="bold")
    T(0.500, 0.026, "※ 자동진입 아님 / 1H 마감 기준 상황판", size=8.5, color=DIM, ha="center")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight", facecolor=BG, pad_inches=0.015)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
