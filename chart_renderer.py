# chart_renderer.py
# 진입레이더 카드 이미지(PNG) 생성
# 기존 카드 디자인 유지 + Railway 한글 폰트 직접 로딩 안정 버전

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
        from matplotlib.patches import FancyBboxPatch
    except ImportError:
        raise RuntimeError("pip install matplotlib 필요")

    symbol = _sig_get(sig, "symbol", default="UNKNOWN")
    direction = _sig_get(sig, "direction", default="WAIT")
    confidence = int(_sig_get(sig, "confidence", "confidence_score", default=0))
    long_score = int(_sig_get(sig, "long_score", default=0))
    short_score = int(_sig_get(sig, "short_score", default=0))

    rsi_val = _safe_num(_sig_get(sig, "rsi", default=50))
    cci_val = _safe_num(_sig_get(sig, "cci", default=0))
    macd_raw = _sig_get(sig, "macd_state", default="NEUTRAL")
    macd_str = _MACD_KO.get(macd_raw, str(macd_raw))

    trend_15m = _sig_get(sig, "trend_15m", default="SIDEWAYS")
    trend_1h = _sig_get(sig, "trend_1h", default="SIDEWAYS")

    div = _sig_get(sig, "divergence", default=None)
    reason = _sig_get(sig, "reason", default="")

    is_btc = "BTC" in str(symbol).upper()
    accent = LIME_GREEN if is_btc else PURPLE

    badge_color = RED if direction == "SHORT" else GREEN if direction == "LONG" else TEXT_MUTED
    badge_label = f"{direction} 감시" if direction != "WAIT" else "방향 대기"

    candles = (candles_15m or [])[-30:]
    n = len(candles)

    def _f(c, k):
        try:
            return float(c.get(k, 0) or 0)
        except Exception:
            return 0.0

    opens = [_f(c, "open") for c in candles]
    highs = [_f(c, "high") for c in candles]
    lows = [_f(c, "low") for c in candles]
    closes = [_f(c, "close") for c in candles]

    def ema_series(vals, period=20):
        if not vals:
            return []
        k = 2 / (period + 1)
        out = [vals[0]]
        for v in vals[1:]:
            out.append(v * k + out[-1] * (1 - k))
        return out

    ema20_series = ema_series(closes)
    range_low = _sig_get(sig, "range_low", default=None)

    fig = plt.figure(figsize=(6, 8.2), facecolor=BG_DARK)
    fig.patch.set_facecolor(BG_DARK)

    gs = fig.add_gridspec(
        6, 1,
        height_ratios=[0.7, 0.6, 0.25, 2.8, 2.2, 0.8],
        hspace=0.08,
        left=0.04,
        right=0.96,
        top=0.97,
        bottom=0.02,
    )

    # ─── 헤더 ────────────────────────────────
    ax_hdr = fig.add_subplot(gs[0])
    ax_hdr.set_facecolor(BG_DARK)
    ax_hdr.axis("off")

    base, quote = _split_symbol(symbol)

    ax_hdr.text(
        0.02, 0.55, base,
        color=accent,
        fontsize=20,
        fontweight="bold",
        va="center",
        transform=ax_hdr.transAxes,
    )

    ax_hdr.text(
        0.14, 0.55, quote,
        color=TEXT_WHITE,
        fontsize=14,
        va="center",
        transform=ax_hdr.transAxes,
    )

    ax_hdr.text(
        0.72, 0.55, "진입레이더",
        color="#ffffff",
        fontsize=10,
        va="center",
        ha="center",
        transform=ax_hdr.transAxes,
        bbox=dict(
            boxstyle="round,pad=0.3",
            facecolor="#7c3aed",
            edgecolor="none",
        ),
    )

    ax_hdr.text(
        0.95, 0.55,
        _sig_get(sig, "timestamp", default=datetime.now(KST).strftime("%H:%M")),
        color=TEXT_MUTED,
        fontsize=10,
        va="center",
        ha="right",
        transform=ax_hdr.transAxes,
    )

    ax_hdr.axhline(0.05, color="#21262d", linewidth=0.8)

    # ─── 상태 행 ─────────────────────────────
    ax_st = fig.add_subplot(gs[1])
    ax_st.set_facecolor(BG_DARK)
    ax_st.axis("off")

    ax_st.text(
        0.02, 0.6, badge_label,
        color="#ffffff",
        fontsize=11,
        fontweight="bold",
        va="center",
        transform=ax_st.transAxes,
        bbox=dict(
            boxstyle="round,pad=0.35",
            facecolor=badge_color,
            edgecolor="none",
            alpha=0.9,
        ),
    )

    ax_st.text(
        0.30, 0.6, "신뢰도",
        color=TEXT_MUTED,
        fontsize=10,
        va="center",
        transform=ax_st.transAxes,
    )

    ax_st.text(
        0.42, 0.6, f"{confidence}%",
        color=TEXT_WHITE,
        fontsize=14,
        fontweight="bold",
        va="center",
        transform=ax_st.transAxes,
    )

    ax_st.text(
        0.80, 0.6, "레이더 감시구간",
        color=TEXT_MUTED,
        fontsize=9,
        va="center",
        ha="right",
        transform=ax_st.transAxes,
    )

    ax_st.text(
        0.02, 0.08, f"LONG {long_score}%",
        color=TEXT_MUTED,
        fontsize=9,
        va="center",
        transform=ax_st.transAxes,
    )

    ax_st.text(
        0.80, 0.08, f"SHORT {short_score}%",
        color=RED if direction == "SHORT" else TEXT_MUTED,
        fontsize=9,
        fontweight="bold",
        ha="right",
        va="center",
        transform=ax_st.transAxes,
    )

    # ─── 방향 바 ─────────────────────────────
    ax_bar = fig.add_subplot(gs[2])
    ax_bar.set_facecolor(BG_DARK)
    ax_bar.axis("off")

    ax_bar.barh(0, 1.0, color="#21262d", height=0.6)

    if direction == "SHORT":
        fill = max(0, min(short_score / 100, 1))
        fill_color = RED
    elif direction == "LONG":
        fill = max(0, min(long_score / 100, 1))
        fill_color = GREEN
    else:
        fill = max(0, min(confidence / 100, 1))
        fill_color = TEXT_MUTED

    ax_bar.barh(0, fill, color=fill_color, height=0.6)
    ax_bar.set_xlim(0, 1)

    # ─── 캔들 차트 ───────────────────────────
    ax_chart = fig.add_subplot(gs[3])
    ax_chart.set_facecolor(BG_CELL)

    for spine in ax_chart.spines.values():
        spine.set_edgecolor("#21262d")

    if n > 0 and any(closes):
        xs = range(n)

        for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
            color = GREEN if c >= o else RED
            ax_chart.plot([i, i], [l, h], color=color, linewidth=0.8, zorder=2)

            body_height = abs(c - o)
            if body_height == 0:
                body_height = max((h - l) * 0.01, 0.0001)

            ax_chart.add_patch(
                plt.Rectangle(
                    (i - 0.3, min(o, c)),
                    0.6,
                    body_height,
                    color=color,
                    zorder=3,
                )
            )

        if len(ema20_series) == n:
            ax_chart.plot(
                list(xs),
                ema20_series,
                color=AMBER,
                linewidth=1.2,
                zorder=4,
            )

        if range_low and _safe_num(range_low) > 0:
            ax_chart.axhline(
                _safe_num(range_low),
                color=AMBER,
                linewidth=0.8,
                linestyle="--",
                alpha=0.6,
            )

            ax_chart.text(
                n - 1,
                _safe_num(range_low),
                "박스하단",
                color=AMBER,
                fontsize=7,
                va="bottom",
                ha="right",
            )

        ax_chart.set_xlim(-0.5, n + 0.5)

        hi = max(highs)
        lo = min(lows)
        padding = (hi - lo) * 0.08 if hi != lo else 1
        ax_chart.set_ylim(lo - padding, hi + padding)

    ax_chart.text(
        0.02, 0.94, "15M 캔들차트",
        color=TEXT_MUTED,
        fontsize=8,
        va="top",
        transform=ax_chart.transAxes,
    )

    ax_chart.text(
        0.98, 0.94, "─ EMA20",
        color=AMBER,
        fontsize=8,
        va="top",
        ha="right",
        transform=ax_chart.transAxes,
    )

    ax_chart.tick_params(colors=TEXT_MUTED, labelsize=7)
    ax_chart.yaxis.tick_right()

    # ─── 지표 그리드 ─────────────────────────
    ax_ind = fig.add_subplot(gs[4])
    ax_ind.set_facecolor(BG_DARK)
    ax_ind.axis("off")

    cells = [
        ("15M", _TREND_KO.get(trend_15m, "횡보"), _trend_color(trend_15m)),
        ("1H", _TREND_KO.get(trend_1h, "횡보"), _trend_color(trend_1h)),
        ("RSI", f"{rsi_val:.2f} {'약세↓' if rsi_val < 50 else '강세↑'}", RED if rsi_val < 50 else GREEN),
        ("CCI", f"{cci_val:.2f} {'약세↓' if cci_val < 0 else '강세↑'}", RED if cci_val < 0 else GREEN),
    ]

    for idx, (label, val, color) in enumerate(cells):
        col = idx % 2
        row = idx // 2
        x = 0.02 + col * 0.50
        y = 0.80 - row * 0.42

        ax_ind.add_patch(
            FancyBboxPatch(
                (x, y - 0.28),
                0.46,
                0.30,
                boxstyle="round,pad=0.01",
                facecolor=BG_CELL,
                edgecolor="#21262d",
                linewidth=0.6,
                transform=ax_ind.transAxes,
            )
        )

        ax_ind.text(
            x + 0.03,
            y - 0.04,
            label,
            color=TEXT_MUTED,
            fontsize=8,
            va="top",
            transform=ax_ind.transAxes,
        )

        ax_ind.text(
            x + 0.03,
            y - 0.18,
            val,
            color=color,
            fontsize=10,
            fontweight="bold",
            va="top",
            transform=ax_ind.transAxes,
        )

    ax_ind.add_patch(
        FancyBboxPatch(
            (0.02, 0.0),
            0.96,
            0.28,
            boxstyle="round,pad=0.01",
            facecolor=BG_CELL,
            edgecolor="#21262d",
            linewidth=0.6,
            transform=ax_ind.transAxes,
        )
    )

    macd_color = (
        RED if macd_raw in ("BEARISH", "NEGATIVE")
        else GREEN if macd_raw in ("BULLISH", "POSITIVE")
        else TEXT_MUTED
    )

    ax_ind.text(
        0.05, 0.24, "MACD",
        color=TEXT_MUTED,
        fontsize=8,
        va="top",
        transform=ax_ind.transAxes,
    )

    ax_ind.text(
        0.05, 0.10, f"{macd_raw} {macd_str}",
        color=macd_color,
        fontsize=10,
        fontweight="bold",
        va="top",
        transform=ax_ind.transAxes,
    )

    # ─── 하단 행동 ───────────────────────────
    ax_bot = fig.add_subplot(gs[5])
    ax_bot.set_facecolor(BG_DARK)
    ax_bot.axis("off")
    ax_bot.axhline(0.92, color="#21262d", linewidth=0.8)

    lines = []

    if reason:
        lines.append(("제한", reason, AMBER))

    if direction == "SHORT":
        lines.append(("숏", "박스 하단 이탈 확인 후", RED))
        lines.append(("롱", "박스 상단 돌파 전 무시", TEXT_MUTED))
    elif direction == "LONG":
        lines.append(("롱", "박스 상단 돌파 확인 후", GREEN))
        lines.append(("숏", "박스 하단 이탈 전 무시", TEXT_MUTED))
    else:
        lines.append(("대기", "상단 돌파 또는 하단 이탈 확인", TEXT_MUTED))

    if div:
        div_color = GREEN if div == "BULLISH_DIV" else RED
        lines.append(("다이버전스", _DIV_KO.get(div, str(div)), div_color))

    for i, (lbl, txt, col) in enumerate(lines[:3]):
        y = 0.75 - i * 0.28

        ax_bot.text(
            0.02,
            y,
            lbl,
            color=col,
            fontsize=9,
            fontweight="bold",
            va="center",
            transform=ax_bot.transAxes,
        )

        ax_bot.text(
            0.16,
            y,
            txt,
            color=TEXT_MUTED,
            fontsize=9,
            va="center",
            transform=ax_bot.transAxes,
        )

    ax_bot.plot(
        0.02,
        0.08,
        "o",
        color=AMBER,
        markersize=5,
        transform=ax_bot.transAxes,
    )

    ax_bot.text(
        0.06,
        0.08,
        "대기 중",
        color=TEXT_MUTED,
        fontsize=9,
        va="center",
        transform=ax_bot.transAxes,
    )

    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=150,
        bbox_inches="tight",
        facecolor=BG_DARK,
    )
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────
# 텔레그램 전송 헬퍼
# ─────────────────────────────────────────────

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
