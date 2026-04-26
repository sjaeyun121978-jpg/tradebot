# chart_renderer.py
# Telegram Trading Bot 카드 이미지(PNG) 렌더링
# - render_radar_card(): 진입레이더 최종 디자인 반영
# - render_dashboard_card(): 1H 전광판 기존 함수 유지

import io
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


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

BG_DARK    = "#0d1117"
BG_CARD    = "#161b22"
BG_CELL    = "#1c2128"
BG_DARK2   = "#21262d"
TEXT_WHITE = "#e6edf3"
TEXT_MUTED = "#8b949e"
RED        = "#f85149"
GREEN      = "#3fb950"
AMBER      = "#d29922"
PURPLE     = "#a78bfa"
LIME_GREEN = "#4ade80"
DARK_INNER = "#0b1018"

_MACD_KO = {
    "BULLISH":  ("강세↑",  GREEN,      "상승 추세 강화"),
    "BEARISH":  ("약세↓",  RED,        "하락 추세 강화"),
    "POSITIVE": ("양전환", GREEN,      "상승전환"),
    "NEGATIVE": ("음전환", RED,        "하락전환"),
    "NEUTRAL":  ("중립",   TEXT_MUTED, "방향미확정"),
}

_DIV_KO = {
    "BULLISH_DIV": "상승 다이버전스",
    "BEARISH_DIV": "하락 다이버전스",
}


def _safe(v, d=0.0):
    try:
        return float(v) if v is not None else d
    except Exception:
        return d


def _get(sig, *keys, default=None):
    for k in keys:
        if isinstance(sig, dict) and k in sig and sig[k] is not None:
            return sig[k]
    return default


def _split_symbol(sym):
    sym = str(sym or "")
    if sym.endswith("USDT"):
        return sym[:-4], "USDT"
    return sym[:3], sym[3:] if len(sym) > 3 else ("", "")


def _fmt_price(v):
    v = _safe(v)
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 100:
        return f"{v:,.1f}"
    return f"{v:,.2f}"


def _trend_txt(t):
    if t == "UP":
        return "상승", GREEN
    if t == "DOWN":
        return "하락", RED
    return "횡보", TEXT_MUTED


def _draw_round(ax, x, y, w, h, fc, ec=None, lw=0.0, radius=0.025, alpha=1.0):
    from matplotlib.patches import FancyBboxPatch
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        transform=ax.transAxes,
        facecolor=fc,
        edgecolor=ec or fc,
        linewidth=lw,
        alpha=alpha,
        clip_on=False,
    ))


def _draw_rect(ax, x, y, w, h, fc, ec=None, lw=0.0, alpha=1.0):
    from matplotlib.patches import Rectangle
    ax.add_patch(Rectangle(
        (x, y), w, h,
        transform=ax.transAxes,
        facecolor=fc,
        edgecolor=ec or fc,
        linewidth=lw,
        alpha=alpha,
        clip_on=False,
    ))


def render_radar_card(sig: dict, candles_15m: list) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    symbol      = _get(sig, "symbol", default="UNKNOWN")
    direction   = _get(sig, "direction", default="WAIT")
    long_score  = int(_safe(_get(sig, "long_score", default=0)))
    short_score = int(_safe(_get(sig, "short_score", default=0)))
    gap         = abs(long_score - short_score)

    rsi_val  = _safe(_get(sig, "rsi", default=50))
    cci_val  = _safe(_get(sig, "cci", default=0))
    macd_raw = _get(sig, "macd_state", default="NEUTRAL")

    trend_15m = _get(sig, "trend_15m", default="SIDEWAYS")
    trend_30m = _get(sig, "trend_30m", default="SIDEWAYS")
    trend_1h  = _get(sig, "trend_1h",  default="SIDEWAYS")
    trend_4h  = _get(sig, "trend_4h",  default="SIDEWAYS")

    support    = _safe(_get(sig, "support", default=0))
    resistance = _safe(_get(sig, "resistance", default=0))
    mid        = (support + resistance) / 2 if support and resistance else 0
    is_range   = bool(_get(sig, "is_range", default=False))
    range_pos  = _get(sig, "range_pos", default=None)

    volume       = _safe(_get(sig, "volume", default=0))
    avg_volume   = _safe(_get(sig, "avg_volume", default=0))
    volume_ratio = _safe(_get(sig, "volume_ratio", default=0))
    if volume_ratio == 0 and avg_volume > 0:
        volume_ratio = volume / avg_volume

    ts = str(_get(sig, "timestamp", default=datetime.now(KST).strftime("%H:%M")))
    if len(ts) > 5 and ":" in ts:
        ts = ts[-5:]

    base, quote = _split_symbol(symbol)
    is_btc = "BTC" in str(symbol).upper()
    accent = LIME_GREEN if is_btc else PURPLE

    if gap < 15:
        strength = "매우 약한 신호"
    elif gap < 25:
        strength = "약한 신호"
    elif gap < 40:
        strength = "보통 신호"
    else:
        strength = "강한 신호"

    if direction == "LONG":
        badge_lbl, badge_c, badge_bg, badge_ec = "LONG 지지", GREEN, "#12351f", "#1a4d1a"
    elif direction == "SHORT":
        badge_lbl, badge_c, badge_bg, badge_ec = "SHORT 지지", RED, "#3a1515", "#7f1d1d"
    else:
        badge_lbl, badge_c, badge_bg, badge_ec = "WAIT", AMBER, "#1a1200", "#d2992244"

    candles = (candles_15m or [])[-30:]
    n = len(candles)
    opens  = [_safe(c.get("open")) for c in candles]
    highs  = [_safe(c.get("high")) for c in candles]
    lows   = [_safe(c.get("low")) for c in candles]
    closes = [_safe(c.get("close")) for c in candles]
    now_price = closes[-1] if closes else _safe(_get(sig, "price", "current_price", default=0))

    def _ema(vals, p=20):
        if not vals:
            return []
        k = 2 / (p + 1)
        out = [vals[0]]
        for v in vals[1:]:
            out.append(v * k + out[-1] * (1 - k))
        return out

    ema20 = _ema(closes)

    if not is_range:
        pos_dot, pos_title, pos_desc = TEXT_MUTED, "추세 구간", "박스권 아님 · 추세 방향 따라가기"
    elif range_pos == "TOP":
        pos_dot, pos_title, pos_desc = RED, "박스 상단", "저항 근접 · 돌파 실패 시 숏 후보"
    elif range_pos == "BOTTOM":
        pos_dot, pos_title, pos_desc = GREEN, "박스 하단", "지지 근접 · 이탈 실패 시 롱 후보"
    else:
        pos_dot, pos_title, pos_desc = AMBER, "박스 중앙", f"{_fmt_price(support)}~{_fmt_price(resistance)} 사이 · 양방향 노이즈"

    tf_items = [("15M", trend_15m), ("30M", trend_30m), ("1H", trend_1h), ("4H", trend_4h)]
    ups = [t for _, t in tf_items].count("UP")
    downs = [t for _, t in tf_items].count("DOWN")
    if trend_1h == "UP" and trend_4h == "UP":
        tf_sum, tf_c = "중기·장기 상승 일치 · 단기 방향 확인 중", GREEN
    elif trend_1h == "DOWN" and trend_4h == "DOWN":
        tf_sum, tf_c = "중기·장기 하락 일치 · 단기 반등 확인 중", RED
    elif ups > 0 and downs > 0:
        tf_sum, tf_c = "단기 숏 · 중기 미확정 · 장기 롱 — 충돌", AMBER
    else:
        tf_sum, tf_c = "방향 미확정 · 대기", TEXT_MUTED

    if rsi_val < 30:
        rsi_lbl, rsi_c = "과매도", GREEN
    elif rsi_val < 45:
        rsi_lbl, rsi_c = "약세", GREEN
    elif rsi_val < 55:
        rsi_lbl, rsi_c = "중립", TEXT_MUTED
    elif rsi_val < 70:
        rsi_lbl, rsi_c = "과매수", RED
    else:
        rsi_lbl, rsi_c = "강한과매수", RED

    if cci_val < -200:
        cci_lbl, cci_c = "극단과매도", GREEN
    elif cci_val < -100:
        cci_lbl, cci_c = "강한하락", RED
    elif cci_val < 0:
        cci_lbl, cci_c = "약한하락", TEXT_MUTED
    elif cci_val < 100:
        cci_lbl, cci_c = "약한상승", TEXT_MUTED
    else:
        cci_lbl, cci_c = "상승압력", GREEN

    macd_str, macd_c, macd_sub = _MACD_KO.get(macd_raw, ("중립", TEXT_MUTED, "방향미확정"))

    if direction == "LONG":
        concl_c, concl_title = GREEN, "결론 — LONG 우세"
        concl_1 = "1H·4H 상승 정렬 · RSI 과매수 주의"
    elif direction == "SHORT":
        concl_c, concl_title = RED, "결론 — SHORT 우세"
        concl_1 = "15M·1H 하락 압력 · 반등 실패 주의"
    else:
        concl_c, concl_title = AMBER, "결론 — 관망"
        concl_1 = f"{_fmt_price(support)} 이탈 시 숏 · {_fmt_price(resistance)} 돌파 시 롱"

    fig = plt.figure(figsize=(6.0, 11.2), dpi=150, facecolor=BG_DARK)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor(BG_DARK)

    ax.text(0.035, 0.972, base, color=accent, fontsize=20, fontweight="bold", va="top", ha="left", transform=ax.transAxes)
    ax.text(0.215, 0.966, quote, color=TEXT_WHITE, fontsize=13, va="top", ha="left", transform=ax.transAxes)
    _draw_round(ax, 0.615, 0.946, 0.13, 0.032, "#1a0e2e", "#7c3aed44", 0.7, 0.008)
    ax.text(0.680, 0.962, "진입레이더", color=PURPLE, fontsize=8.5, fontweight="bold", ha="center", va="center", transform=ax.transAxes)
    ax.text(0.94, 0.965, ts, color=TEXT_MUTED, fontsize=10, va="top", ha="right", transform=ax.transAxes)
    _draw_rect(ax, 0.018, 0.925, 0.964, 0.001, BG_DARK2)

    _draw_round(ax, 0.030, 0.880, 0.18, 0.037, badge_bg, badge_ec, 0.7, 0.008)
    ax.text(0.120, 0.898, badge_lbl, color=badge_c, fontsize=9.5, fontweight="bold", ha="center", va="center", transform=ax.transAxes)
    ax.text(0.280, 0.899, f"차이 {gap}%p · {strength}", color=TEXT_MUTED, fontsize=8.5, ha="left", va="center", transform=ax.transAxes)
    ax.text(0.940, 0.899, "감시구간", color=TEXT_MUTED, fontsize=8.5, ha="right", va="center", transform=ax.transAxes)
    ax.text(0.035, 0.860, f"LONG {long_score}%", color=GREEN, fontsize=9.5, fontweight="bold", ha="left", va="center", transform=ax.transAxes)
    ax.text(0.500, 0.860, "신호강도", color=TEXT_MUTED, fontsize=10, fontweight="bold", ha="center", va="center", transform=ax.transAxes)
    ax.text(0.940, 0.860, f"SHORT {short_score}%", color=RED, fontsize=9.5, fontweight="bold", ha="right", va="center", transform=ax.transAxes)
    _draw_round(ax, 0.035, 0.835, 0.905, 0.014, BG_DARK2, radius=0.007)
    _draw_rect(ax, 0.035, 0.835, 0.905 * max(0, min(long_score, 100)) / 100,
