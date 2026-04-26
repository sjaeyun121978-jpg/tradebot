# chart_renderer.py
# 진입레이더 카드 이미지(PNG) 생성

import io
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST)


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


BG_DARK = "#0d1117"
BG_CARD = "#161b22"
BG_CELL = "#1c2128"
BG_CELL2 = "#20262e"
TEXT_WHITE = "#e6edf3"
TEXT_MUTED = "#8b949e"
TEXT_DIM = "#6e7681"
RED = "#f85149"
GREEN = "#3fb950"
AMBER = "#d29922"
PURPLE = "#a78bfa"
BLUE = "#58a6ff"


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


def _candle_value(c, key, default=0.0):
    if isinstance(c, dict):
        return _safe(c.get(key), default)
    return default


def _split_symbol(sym):
    sym = str(sym or "")
    if sym.endswith("USDT"):
        return sym[:-4], "USDT"
    if len(sym) > 3:
        return sym[:3], sym[3:]
    return sym, ""


def _ema(values, period=20):
    values = [_safe(v) for v in values if v is not None]
    if not values:
        return []
    k = 2 / (period + 1)
    out = []
    e = values[0]
    for v in values:
        e = (v * k) + (e * (1 - k))
        out.append(e)
    return out


def _trend_ko(v):
    return {
        "UP": "상승",
        "DOWN": "하락",
        "SIDEWAYS": "횡보",
        "UNKNOWN": "횡보",
    }.get(str(v or "").upper(), "횡보")


def _macd_ko(v):
    return {
        "BULLISH": ("강세↑", GREEN, "상승 추세 강화"),
        "BEARISH": ("약세↓", RED, "하락 추세 강화"),
        "POSITIVE": ("양전환", GREEN, "상승 전환 시도"),
        "NEGATIVE": ("음전환", RED, "하락 전환 시도"),
        "NEUTRAL": ("중립", TEXT_MUTED, "방향 미확정"),
    }.get(str(v or "NEUTRAL").upper(), ("중립", TEXT_MUTED, "방향 미확정"))


def _fmt_price(v):
    v = _safe(v)
    if v >= 1000:
        return f"{v:.0f}"
    if v >= 10:
        return f"{v:.2f}"
    return f"{v:.4f}"


def _score_label(long_score, short_score):
    gap = abs(long_score - short_score)
    if gap < 15:
        return f"차이 {gap:.0f}%p - 약한 신호", "감시구간"
    if long_score > short_score:
        return f"LONG 우세 {gap:.0f}%p", "롱 감시"
    return f"SHORT 우세 {gap:.0f}%p", "숏 감시"


def _decision(sig):
    direction = str(_get(sig, "direction", default="WAIT") or "WAIT").upper()
    long_score = _safe(_get(sig, "long_score", default=0))
    short_score = _safe(_get(sig, "short_score", default=0))

    if direction == "LONG" and long_score >= 85:
        return "롱 진입 후보", GREEN
    if direction == "SHORT" and short_score >= 85:
        return "숏 진입 후보", RED
    if direction == "LONG":
        return "방향 미확정 · 대기", TEXT_MUTED
    if direction == "SHORT":
        return "방향 미확정 · 대기", TEXT_MUTED
    return "방향 미확정 · 대기", TEXT_MUTED


def _draw_card(ax, x, y, w, h, face=BG_CARD, edge="#30363d", lw=1, radius=0.012):
    from matplotlib.patches import FancyBboxPatch

    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.004,rounding_size={radius}",
        linewidth=lw,
        edgecolor=edge,
        facecolor=face,
        transform=ax.transAxes,
        clip_on=False,
    )
    ax.add_patch(patch)
    return patch


def _draw_text(ax, x, y, text, size=10, color=TEXT_WHITE, weight="normal",
               ha="left", va="center", alpha=1.0):
    ax.text(
        x,
        y,
        str(text),
        transform=ax.transAxes,
        fontsize=size,
        color=color,
        fontweight=weight,
        ha=ha,
        va=va,
        alpha=alpha,
    )


def _draw_badge(ax, x, y, text, color, size=9):
    _draw_text(
        ax,
        x,
        y,
        text,
        size=size,
        color="white",
        weight="bold",
        ha="left",
        va="center",
    )


def _draw_progress(ax, x, y, w, h, value, color, bg="#22272e"):
    from matplotlib.patches import Rectangle

    value = max(0.0, min(1.0, _safe(value)))
    ax.add_patch(Rectangle((x, y), w, h, transform=ax.transAxes, facecolor=bg, edgecolor="#242b33", lw=0.8))
    ax.add_patch(Rectangle((x, y), w * value, h, transform=ax.transAxes, facecolor=color, edgecolor=color, lw=0.8))


def _normalize_candles(candles, max_count=30):
    candles = candles or []
    rows = []
    for c in candles[-max_count:]:
        o = _candle_value(c, "open")
        h = _candle_value(c, "high")
        l = _candle_value(c, "low")
        cl = _candle_value(c, "close")
        if h > 0 and l > 0 and cl > 0:
            rows.append({"open": o, "high": h, "low": l, "close": cl})
    return rows


def _draw_candle_chart(ax, candles, sig):
    import numpy as np
    from matplotlib.patches import Rectangle

    ax.set_facecolor("#1c2128")

    rows = _normalize_candles(candles, 30)
    if len(rows) < 2:
        ax.text(0.5, 0.5, "캔들 데이터 부족", transform=ax.transAxes,
                color=TEXT_MUTED, ha="center", va="center", fontsize=12)
        ax.set_xticks([])
        ax.set_yticks([])
        return

    opens = [r["open"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    closes = [r["close"] for r in rows]
    x = np.arange(len(rows))

    price = _safe(_get(sig, "current_price", default=closes[-1]), closes[-1])
    support = _safe(_get(sig, "support", "range_low", default=min(lows)), min(lows))
    resistance = _safe(_get(sig, "resistance", "range_high", default=max(highs)), max(highs))

    y_min = min(min(lows), support, price)
    y_max = max(max(highs), resistance, price)
    pad = (y_max - y_min) * 0.12 if y_max != y_min else max(price * 0.002, 1)
    ax.set_ylim(y_min - pad, y_max + pad)
    ax.set_xlim(-0.5, len(rows) - 0.5)

    width = 0.58
    for i, r in enumerate(rows):
        o, h, l, c = r["open"], r["high"], r["low"], r["close"]
        col = GREEN if c >= o else RED
        ax.vlines(i, l, h, color=col, linewidth=1.0, alpha=0.9)
        body_low = min(o, c)
        body_h = max(abs(c - o), (y_max - y_min) * 0.002)
        ax.add_patch(Rectangle((i - width / 2, body_low), width, body_h,
                               facecolor=col, edgecolor=col, linewidth=0.8))

    ema20 = _ema(closes, 20)
    ax.plot(x, ema20, color=AMBER, linewidth=1.4, alpha=0.9)

    ax.axhline(resistance, color=RED, linestyle="--", linewidth=0.8, alpha=0.65)
    ax.axhline(support, color=GREEN, linestyle="--", linewidth=0.8, alpha=0.65)
    ax.axhline(price, color=TEXT_MUTED, linestyle=":", linewidth=0.8, alpha=0.45)

    ax.text(0.02, 0.96, "15M 캔들차트", transform=ax.transAxes,
            color=TEXT_MUTED, fontsize=8, va="top")
    ax.text(0.97, 0.96, "— EMA20", transform=ax.transAxes,
            color=AMBER, fontsize=8, va="top", ha="right")

    ax.text(0.86, 0.86, f"박스상단 {_fmt_price(resistance)}", transform=ax.transAxes,
            color=RED, fontsize=7, ha="left", va="center")
    ax.text(0.86, 0.56, _fmt_price(price), transform=ax.transAxes,
            color=TEXT_WHITE, fontsize=7, ha="left", va="center")
    ax.text(0.86, 0.11, f"박스하단 {_fmt_price(support)}", transform=ax.transAxes,
            color=GREEN, fontsize=7, ha="left", va="center")

    ax.yaxis.tick_right()
    ax.tick_params(axis="both", colors=TEXT_DIM, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color("#242b33")
    ax.grid(axis="y", color="#30363d", alpha=0.25, linewidth=0.6)


def render_radar_card(sig: dict, candles_15m: list) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    symbol = _get(sig, "symbol", default="BTCUSDT")
    base, quote = _split_symbol(symbol)

    price = _safe(_get(sig, "current_price", default=0))
    support = _safe(_get(sig, "support", "range_low", default=0))
    resistance = _safe(_get(sig, "resistance", "range_high", default=0))
    long_score = _safe(_get(sig, "long_score", default=0))
    short_score = _safe(_get(sig, "short_score", default=0))
    volume_ratio = _safe(_get(sig, "volume_ratio", default=0))
    rsi = _safe(_get(sig, "rsi", default=50))
    cci = _safe(_get(sig, "cci", default=0))
    trend15 = _trend_ko(_get(sig, "trend_15m", default="SIDEWAYS"))
    trend1h = _trend_ko(_get(sig, "trend_1h", default="SIDEWAYS"))
    macd_label, macd_color, macd_desc = _macd_ko(_get(sig, "macd_state", default="NEUTRAL"))

    diff_text, zone_text = _score_label(long_score, short_score)
    decision_text, decision_color = _decision(sig)

    fig = plt.figure(figsize=(6, 14.8), dpi=150, facecolor=BG_DARK)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(BG_DARK)
    ax.set_axis_off()

    _draw_text(ax, 0.035, 0.972, base, size=20, color=GREEN, weight="normal")
    _draw_text(ax, 0.215, 0.972, quote, size=13, color=TEXT_WHITE)
    _draw_card(ax, 0.642, 0.961, 0.12, 0.025, face=PURPLE, edge=PURPLE, radius=0.006)
    _draw_text(ax, 0.702, 0.973, "진입레이더", size=8, color="white", weight="bold", ha="center")
    _draw_text(ax, 0.94, 0.972, now_kst().strftime("%H:%M"), size=9, color=TEXT_MUTED, ha="right")

    ax.plot([0.02, 0.98], [0.94, 0.94], transform=ax.transAxes, color="#242b33", lw=1)

    top_y = 0.912
    _draw_card(ax, 0.032, top_y, 0.125, 0.022, face=RED, edge=RED, radius=0.004)
    _draw_text(ax, 0.094, top_y + 0.011, "SHORT 지지", size=7.5, color="white", weight="bold", ha="center")
    _draw_text(ax, 0.36, top_y + 0.011, diff_text, size=7.2, color=TEXT_MUTED, ha="center")
    _draw_text(ax, 0.94, top_y + 0.011, zone_text, size=7.2, color=TEXT_MUTED, ha="right")

    bar_y = 0.888
    _draw_progress(ax, 0.018, bar_y, 0.47, 0.018, long_score / max(long_score + short_score, 1), GREEN)
    _draw_progress(ax, 0.488, bar_y, 0.47, 0.018, short_score / max(long_score + short_score, 1), RED)

    _draw_text(ax, 0.035, 0.874, f"LONG {long_score:.0f}%", size=8, color=GREEN)
    _draw_text(ax, 0.94, 0.874, f"SHORT {short_score:.0f}%", size=8, color=RED, ha="right")

    chart_ax = fig.add_axes([0.018, 0.51, 0.955, 0.33])
    _draw_candle_chart(chart_ax, candles_15m, sig)

    _draw_text(
        ax,
        0.035,
        0.488,
        f"●   박스 중앙 · {_fmt_price(support)}~{_fmt_price(resistance)} · 양방향 노이즈 · 진입 금지",
        size=7.5,
        color=TEXT_MUTED,
    )
    _draw_text(ax, 0.037, 0.488, "●", size=9, color=AMBER)

    y = 0.435
    _draw_card(ax, 0.02, y, 0.955, 0.048, face="#1f0f10", edge="#4a1f23", radius=0.006)
    _draw_text(ax, 0.04, y + 0.029, "숏", size=8, color=RED, weight="bold")
    _draw_text(ax, 0.10, y + 0.029, f"{_fmt_price(support)} 이탈", size=8, color=TEXT_WHITE)
    _draw_text(ax, 0.37, y + 0.029, "+", size=9, color=TEXT_MUTED)
    _draw_text(ax, 0.44, y + 0.029, "거래량 1.2배+", size=8, color=TEXT_WHITE)
    _draw_text(ax, 0.94, y + 0.029, f"현재 {volume_ratio:.1f}배", size=8, color=AMBER, ha="right")

    y2 = 0.386
    _draw_card(ax, 0.02, y2, 0.955, 0.048, face="#0f1f12", edge="#1f4a27", radius=0.006)
    _draw_text(ax, 0.04, y2 + 0.029, "롱", size=8, color=GREEN, weight="bold")
    _draw_text(ax, 0.10, y2 + 0.029, f"{_fmt_price(resistance)} 돌파", size=8, color=TEXT_WHITE)
    _draw_text(ax, 0.37, y2 + 0.029, "+", size=9, color=TEXT_MUTED)
    _draw_text(ax, 0.44, y2 + 0.029, "거래량 1.2배+", size=8, color=TEXT_WHITE)
    _draw_text(ax, 0.94, y2 + 0.029, f"현재 {volume_ratio:.1f}배", size=8, color=AMBER, ha="right")

    y3 = 0.325
    _draw_card(ax, 0.02, y3, 0.955, 0.057, face=BG_CARD, edge="#242b33", radius=0.005)
    _draw_text(ax, 0.045, y3 + 0.043, "거래량 진행도 (숏·롱 공통)", size=7, color=TEXT_MUTED)
    lack = max(0, int(round((1.2 - volume_ratio) / 1.2 * 100)))
    _draw_text(ax, 0.92, y3 + 0.043, f"{lack}% 부족" if volume_ratio < 1.2 else "충족", size=7, color=RED if volume_ratio < 1.2 else GREEN, ha="right")
    _draw_progress(ax, 0.045, y3 + 0.018, 0.90, 0.016, min(volume_ratio / 1.2, 1), AMBER)
    _draw_text(ax, 0.045, y3 + 0.004, "0배", size=6.5, color=TEXT_MUTED)
    _draw_text(ax, 0.90, y3 + 0.004, "기준 1.2배", size=6.5, color=GREEN, ha="right")

    y4 = 0.245
    _draw_text(ax, 0.035, y4 + 0.073, "시간봉 구조", size=8, color=TEXT_MUTED)

    _draw_card(ax, 0.02, y4, 0.46, 0.065, face=BG_CARD, edge="#242b33", radius=0.005)
    _draw_text(ax, 0.05, y4 + 0.048, "15M · 단기", size=7, color=TEXT_MUTED)
    _draw_text(ax, 0.05, y4 + 0.028, trend15, size=13, color=TEXT_MUTED)
    _draw_text(ax, 0.05, y4 + 0.010, "방향 미확정" if trend15 == "횡보" else "방향 확인", size=7, color=TEXT_MUTED)

    _draw_card(ax, 0.51, y4, 0.46, 0.065, face=BG_CARD, edge="#242b33", radius=0.005)
    _draw_text(ax, 0.54, y4 + 0.048, "1H · 중기", size=7, color=TEXT_MUTED)
    _draw_text(ax, 0.54, y4 + 0.028, trend1h, size=13, color=TEXT_MUTED)
    _draw_text(ax, 0.54, y4 + 0.010, "방향 미확정" if trend1h == "횡보" else "방향 확인", size=7, color=TEXT_MUTED)

    y5 = 0.188
    _draw_card(ax, 0.02, y5, 0.955, 0.052, face=BG_CARD, edge="#242b33", radius=0.002)
    ax.plot([0.022, 0.022], [y5, y5 + 0.052], transform=ax.transAxes, color="#9aa4b2", lw=1.0)
    _draw_text(ax, 0.045, y5 + 0.036, decision_text, size=8, color=decision_color)
    _draw_text(ax, 0.045, y5 + 0.016, "박스 이탈 방향 확인 후 진입", size=7, color=TEXT_MUTED)

    _draw_text(ax, 0.035, 0.164, "지표 분석", size=8, color=TEXT_MUTED)

    ind_y = 0.111
    _draw_card(ax, 0.02, ind_y, 0.955, 0.043, face=BG_CARD, edge="#242b33", radius=0.004)
    _draw_text(ax, 0.045, ind_y + 0.030, "RSI", size=7.5, color=TEXT_MUTED)
    _draw_text(ax, 0.17, ind_y + 0.030, f"{rsi:.1f}", size=11, color=TEXT_MUTED)
    _draw_text(ax, 0.37, ind_y + 0.030, "중립" if 45 <= rsi <= 55 else ("강세" if rsi > 55 else "약세"), size=7.5, color=TEXT_MUTED)
    _draw_text(ax, 0.37, ind_y + 0.010, "50 기준 방향 탐색 중", size=6.5, color=TEXT_DIM)

    ind_y2 = 0.058
    _draw_card(ax, 0.02, ind_y2, 0.955, 0.043, face=BG_CARD, edge="#242b33", radius=0.004)
    _draw_text(ax, 0.045, ind_y2 + 0.030, "CCI", size=7.5, color=TEXT_MUTED)
    _draw_text(ax, 0.17, ind_y2 + 0.030, f"{cci:.0f}", size=11, color=TEXT_MUTED)
    cci_state = "강한 상승" if cci >= 100 else ("강한 하락" if cci <= -100 else ("약한 상승" if cci > 0 else "약한 하락"))
    _draw_text(ax, 0.37, ind_y2 + 0.030, cci_state, size=7.5, color=TEXT_MUTED)
    _draw_text(ax, 0.37, ind_y2 + 0.010, "+100 / -100 기준 반응 유력", size=6.5, color=TEXT_DIM)

    ind_y3 = 0.005
    _draw_card(ax, 0.02, ind_y3, 0.955, 0.043, face=BG_CARD, edge="#242b33", radius=0.004)
    _draw_text(ax, 0.045, ind_y3 + 0.030, "MACD", size=7.5, color=TEXT_MUTED)
    _draw_text(ax, 0.17, ind_y3 + 0.030, macd_label, size=9, color=macd_color, weight="bold")
    _draw_text(ax, 0.37, ind_y3 + 0.030, macd_label.replace("↑", "").replace("↓", ""), size=7.5, color=macd_color)
    _draw_text(ax, 0.37, ind_y3 + 0.010, macd_desc, size=6.5, color=TEXT_DIM)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG_DARK, pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def render_dashboard_card(sig: dict, candles_1h: list) -> bytes:
    return render_radar_card(sig, candles_1h)


async def send_radar_album(bot, chat_id: str, signals: list, candles_map: dict):
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
    png = render_radar_card(sig, candles_15m)
    await bot.send_photo(chat_id=chat_id, photo=png)
