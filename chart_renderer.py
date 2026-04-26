# chart_renderer.py
# 진입레이더 카드 이미지(PNG) 생성 — Image 2 디자인 기준
# ─────────────────────────────────────────────────────────
# 레이아웃:
#   ① 헤더: ETH · USDT · 진입레이더 배지 · 시간
#   ② 방향배지 + 점수차 + 감시구간
#   ③ 점수바 (LONG % ↔ SHORT %)
#   ④ 캔들차트 (15M, EMA20, 박스상단/하단 점선)
#   ⑤ 상황 불릿 (박스 중앙/하단 설명)
#   ⑥ 타임프레임 (15M / 30M / 1H / 4H 불릿 + 추세)
#   ⑦ 지표 카드 3열 (RSI / CCI / MACD)
#   ⑧ 결론 섹션

import io
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST)


# ─── 폰트 셋업 ───────────────────────────────────────────

def _setup_korean_font():
    import matplotlib
    import matplotlib.font_manager as fm

    base_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(base_dir, "fonts")

    for name in [
        "NanumGothic-Bold.ttf",
        "NanumGothic-Regular.ttf",
        "NanumGothic-ExtraBold.ttf",
        "NanumGothic.ttf",
    ]:
        path = os.path.join(font_dir, name)
        if os.path.exists(path):
            fm.fontManager.addfont(path)
            prop = fm.FontProperties(fname=path)
            matplotlib.rcParams["font.family"] = prop.get_name()
            matplotlib.rcParams["axes.unicode_minus"] = False
            return prop.get_name()

    matplotlib.rcParams["font.family"] = "DejaVu Sans"
    matplotlib.rcParams["axes.unicode_minus"] = False
    return "DejaVu Sans"


_KOREAN_FONT = _setup_korean_font()


# ─── 팔레트 ──────────────────────────────────────────────

BG         = "#111318"
PANEL      = "#1a1d24"
BORDER     = "#2a2d36"
GREEN      = "#2ecc71"
RED        = "#e74c3c"
AMBER      = "#f39c12"
PURPLE     = "#9b59b6"
GRAY_BULL  = "#95a5a6"
WHITE      = "#e8ecf0"
MUTED      = "#8a8f9e"
DIM        = "#555a6a"
RSI_OVER   = "#e74c3c"


# ─── 공통 유틸 ───────────────────────────────────────────

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


def _fmt(v):
    v = _safe(v)
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 10:
        return f"{v:.2f}"
    return f"{v:.4f}"


def _split_symbol(sym):
    sym = str(sym or "")
    if sym.endswith("USDT"):
        return sym[:-4], "USDT"
    if len(sym) > 3:
        return sym[:3], sym[3:]
    return sym, ""


def _ema(values, period=20):
    vals = [_safe(v) for v in values if v is not None]
    if not vals:
        return []
    k = 2 / (period + 1)
    e, out = vals[0], []
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _trend_color(v):
    t = str(v or "").upper()
    if t == "UP":   return GREEN
    if t == "DOWN": return RED
    return GRAY_BULL


def _macd_ko(v):
    return {
        "BULLISH":  ("양전환", GREEN, "상승전환"),
        "BEARISH":  ("음전환", RED,   "하락전환"),
        "POSITIVE": ("양전환", GREEN, "상승전환"),
        "NEGATIVE": ("음전환", RED,   "하락전환"),
        "NEUTRAL":  ("중립",   MUTED, "방향미확정"),
    }.get(str(v or "NEUTRAL").upper(), ("중립", MUTED, "방향미확정"))


# ─── 캔들 정규화 ─────────────────────────────────────────

def _norm_candles(candles, n=40):
    rows = []
    for c in (candles or [])[-n:]:
        if not isinstance(c, dict):
            continue
        o  = _safe(c.get("open"))
        h  = _safe(c.get("high"))
        l  = _safe(c.get("low"))
        cl = _safe(c.get("close"))
        if h > 0 and l > 0 and cl > 0:
            rows.append({"open": o, "high": h, "low": l, "close": cl})
    return rows


# ─── 캔들차트 axes ────────────────────────────────────────

def _draw_chart(ax, candles, sig):
    import numpy as np
    from matplotlib.patches import Rectangle

    ax.set_facecolor(PANEL)
    for spine in ax.spines.values():
        spine.set_color(BORDER)

    rows = _norm_candles(candles, 40)
    if len(rows) < 3:
        ax.text(0.5, 0.5, "데이터 부족", transform=ax.transAxes,
                color=MUTED, ha="center", va="center", fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
        return

    opens  = [r["open"]  for r in rows]
    highs  = [r["high"]  for r in rows]
    lows   = [r["low"]   for r in rows]
    closes = [r["close"] for r in rows]
    x      = np.arange(len(rows))

    price      = _safe(_get(sig, "current_price", default=closes[-1]), closes[-1])
    support    = _safe(_get(sig, "support",    "range_low",  default=min(lows)), min(lows))
    resistance = _safe(_get(sig, "resistance", "range_high", default=max(highs)), max(highs))

    ylo = min(min(lows), support,    price)
    yhi = max(max(highs), resistance, price)
    pad = (yhi - ylo) * 0.10 if yhi != ylo else price * 0.005
    ax.set_ylim(ylo - pad, yhi + pad)
    ax.set_xlim(-0.8, len(rows) - 0.2)

    # 박스 상단/하단 점선
    ax.axhline(resistance, color=RED,   linestyle="--", linewidth=1.0, alpha=0.7, zorder=1)
    ax.axhline(support,    color=GREEN, linestyle="--", linewidth=1.0, alpha=0.7, zorder=1)

    # 캔들
    w = 0.55
    for i, r in enumerate(rows):
        o, h, l, c = r["open"], r["high"], r["low"], r["close"]
        col = GREEN if c >= o else RED
        ax.vlines(i, l, h, color=col, linewidth=0.9, alpha=0.95, zorder=2)
        bh = max(abs(c - o), (yhi - ylo) * 0.001)
        ax.add_patch(Rectangle(
            (i - w / 2, min(o, c)), w, bh,
            facecolor=col, edgecolor=col, linewidth=0.5, zorder=2,
        ))

    # EMA20
    ema20 = _ema(closes, 20)
    ax.plot(x, ema20, color=AMBER, linewidth=1.8, alpha=0.95, zorder=3)

    # 현재가 점
    ax.scatter([len(rows) - 1], [price], color=AMBER, s=28, zorder=5)

    # 가격 레이블 (우측)
    ax.text(len(rows) - 0.4, resistance, f" {_fmt(resistance)}", color=RED,
            fontsize=7.5, va="center", ha="left")
    ax.text(len(rows) - 0.4, price,      f" {_fmt(price)}",      color=AMBER,
            fontsize=7.5, va="center", ha="left", fontweight="bold")
    ax.text(len(rows) - 0.4, support,    f" {_fmt(support)}",    color=GREEN,
            fontsize=7.5, va="center", ha="left")

    # 좌상단 레이블
    ax.text(0.012, 0.97, "15M 캔들차트", transform=ax.transAxes,
            color=MUTED, fontsize=8.5, va="top")
    ax.text(0.99, 0.97, "— EMA20", transform=ax.transAxes,
            color=AMBER, fontsize=8.5, va="top", ha="right")

    ax.yaxis.tick_right()
    ax.tick_params(axis="y", colors=DIM, labelsize=7)
    ax.tick_params(axis="x", colors=DIM, labelsize=6)
    ax.grid(axis="y", color=BORDER, linewidth=0.5, alpha=0.5)
    ax.set_xticks([])


# ─── 메인 렌더링 함수 ─────────────────────────────────────

def render_radar_card(sig: dict, candles_15m: list) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle

    # ── 데이터 추출 ──────────────────────────
    symbol      = _get(sig, "symbol", default="BTCUSDT")
    base, quote = _split_symbol(symbol)

    price       = _safe(_get(sig, "current_price", default=0))
    support     = _safe(_get(sig, "support",       default=0))
    resistance  = _safe(_get(sig, "resistance",    default=0))
    long_score  = _safe(_get(sig, "long_score",    default=0))
    short_score = _safe(_get(sig, "short_score",   default=0))
    vol_ratio   = _safe(_get(sig, "volume_ratio",  default=0))
    rsi         = _safe(_get(sig, "rsi",           default=50))
    cci         = _safe(_get(sig, "cci",           default=0))
    direction   = str(_get(sig, "direction", default="WAIT") or "WAIT").upper()
    is_range    = _get(sig, "is_range",   default=False)
    range_pos   = _get(sig, "range_pos",  default=None)
    bb_squeeze  = _get(sig, "bb_squeeze", default=False)

    trend_15m = _get(sig, "trend_15m", default="SIDEWAYS")
    trend_30m = _get(sig, "trend_30m", default="SIDEWAYS")
    trend_1h  = _get(sig, "trend_1h",  default="SIDEWAYS")
    trend_4h  = _get(sig, "trend_4h",  default="SIDEWAYS")

    macd_label, macd_color, macd_desc = _macd_ko(_get(sig, "macd_state", default="NEUTRAL"))

    score_gap   = abs(long_score - short_score)
    total       = max(long_score + short_score, 1)
    long_ratio  = long_score  / total
    short_ratio = short_score / total

    # 방향 배지
    if direction == "LONG":
        badge_txt, badge_color = "LONG 지지",  GREEN
    elif direction == "SHORT":
        badge_txt, badge_color = "SHORT 지지", RED
    else:
        badge_txt, badge_color = "대기",        MUTED

    gap_strength = "강한 신호" if score_gap >= 30 else ("중간 신호" if score_gap >= 15 else "약한 신호")
    gap_text     = f"차이 {score_gap:.0f}%p · {gap_strength}"

    # 상황 불릿
    if is_range and range_pos == "MIDDLE":
        bullet_color = AMBER
        bullet_text  = f"박스 중앙 · {_fmt(support)}~{_fmt(resistance)} · 양방향 노이즈 · 진입 금지"
    elif is_range and range_pos == "BOTTOM":
        bullet_color = GREEN
        bullet_text  = f"박스 하단 지지 근접 · 이탈 실패 시 롱 후보"
    elif is_range and range_pos == "TOP":
        bullet_color = RED
        bullet_text  = f"박스 상단 저항 근접 · 돌파 실패 시 숏 후보"
    elif bb_squeeze:
        bullet_color = AMBER
        bullet_text  = "볼린저밴드 수축 · 큰 움직임 임박 · 방향 확인 필수"
    else:
        bullet_color = MUTED
        bullet_text  = f"박스 구간 {_fmt(support)}~{_fmt(resistance)} · 방향 돌파 확인 후 진입"

    # 타임프레임 항목
    tf_items = [
        (f"15M {'상승' if trend_15m=='UP' else ('하락' if trend_15m=='DOWN' else '횡보')}", _trend_color(trend_15m)),
        (f"30M {'상승' if trend_30m=='UP' else ('하락' if trend_30m=='DOWN' else '횡보')}", _trend_color(trend_30m)),
        (f"1H {'상승' if trend_1h=='UP' else ('하락' if trend_1h=='DOWN' else '횡보')}",   _trend_color(trend_1h)),
        (f"4H {'상승' if trend_4h=='UP' else ('하락' if trend_4h=='DOWN' else '횡보')}",   _trend_color(trend_4h)),
    ]

    # 타임프레임 요약
    if trend_1h == trend_4h and trend_1h in ("UP", "DOWN"):
        dir_ko       = "상승" if trend_1h == "UP" else "하락"
        tf_summary   = f"중기·장기 {dir_ko} 일치 · 단기 방향 확인 중"
        tf_sum_color = _trend_color(trend_1h)
    elif trend_1h == "SIDEWAYS" and trend_4h == "SIDEWAYS":
        tf_summary   = "전 타임프레임 횡보 · 방향 미확정"
        tf_sum_color = MUTED
    else:
        tf_summary   = "타임프레임 혼재 · 상위봉 방향 우선"
        tf_sum_color = AMBER

    # 결론
    if direction == "LONG":
        conclusion_main, conclusion_color = "LONG 우세", GREEN
    elif direction == "SHORT":
        conclusion_main, conclusion_color = "SHORT 우세", RED
    else:
        conclusion_main, conclusion_color = "방향 대기", MUTED

    warn_parts = []
    if trend_1h != trend_4h and "SIDEWAYS" not in (trend_1h, trend_4h):
        warn_parts.append("1H·4H 방향 불일치 · 추세 정렬 확인")
    if rsi > 65:
        warn_parts.append("RSI 과매수 주의")
    elif rsi < 35:
        warn_parts.append("RSI 과매도 주의")

    warn1 = warn_parts[0] if warn_parts else ""
    warn2 = "돌파/이탈 + 거래량 확인 전 진입 금지"

    # RSI/CCI 색상
    rsi_color = RSI_OVER if rsi > 65 else (GREEN if rsi > 55 else (RED if rsi < 35 else WHITE))
    rsi_state = "과매수" if rsi > 65 else ("강세" if rsi > 55 else ("과매도" if rsi < 35 else "중립"))

    cci_color = GREEN if cci >= 100 else (RED if cci <= -100 else WHITE)
    cci_state = "상승압력" if cci >= 100 else ("하락압력" if cci <= -100 else ("약세" if cci < 0 else "강세"))

    # ════════════════════════════════════════
    # Figure 생성
    # ════════════════════════════════════════
    FIG_W, FIG_H = 6.0, 14.2
    DPI = 160

    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI, facecolor=BG)
    ax  = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(BG)
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # ── 헬퍼 ─────────────────────────────────
    def T(x, y, s, size=10, color=WHITE, weight="normal", ha="left", va="center", alpha=1.0):
        ax.text(x, y, str(s), transform=ax.transAxes,
                fontsize=size, color=color, fontweight=weight,
                ha=ha, va=va, alpha=alpha)

    def HR(y, x0=0.03, x1=0.97, color=BORDER, lw=0.8):
        ax.plot([x0, x1], [y, y], transform=ax.transAxes,
                color=color, linewidth=lw, solid_capstyle="butt")

    def RECT(x, y, w, h, face=PANEL, edge=BORDER, lw=0.8, r=0.010):
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h,
            boxstyle=f"round,pad=0.002,rounding_size={r}",
            linewidth=lw, edgecolor=edge, facecolor=face,
            transform=ax.transAxes, clip_on=False,
        ))

    def DOT(x, y, r=0.007, color=GREEN):
        ax.add_patch(plt.Circle((x, y), r, color=color,
                                transform=ax.transAxes, clip_on=False, zorder=5))

    # ════════════════════════════════════════
    # ① 헤더
    # ════════════════════════════════════════
    HDR_Y = 0.962

    T(0.04,  HDR_Y, base,  size=22, color=GREEN, weight="bold")
    T(0.185, HDR_Y, quote, size=13, color=WHITE)

    RECT(0.46, HDR_Y - 0.017, 0.165, 0.034,
         face=PURPLE, edge=PURPLE, r=0.007)
    T(0.542, HDR_Y, "진입레이더", size=8.5, color=WHITE, weight="bold", ha="center")

    T(0.97, HDR_Y, now_kst().strftime("%H:%M"), size=10, color=MUTED, ha="right")

    HR(0.943)

    # ════════════════════════════════════════
    # ② 방향 배지 + 점수차
    # ════════════════════════════════════════
    BADGE_Y = 0.921

    RECT(0.03, BADGE_Y - 0.017, 0.18, 0.034,
         face=badge_color, edge=badge_color, r=0.007)
    T(0.12, BADGE_Y, badge_txt, size=9.5, color=WHITE, weight="bold", ha="center")

    T(0.255, BADGE_Y, gap_text, size=8.5, color=MUTED)
    T(0.97,  BADGE_Y, "감시구간", size=8.5, color=MUTED, ha="right")

    # LONG % / SHORT % 행
    SB_Y = 0.899
    T(0.04,  SB_Y, f"LONG {long_score:.0f}%",  size=8.5, color=GREEN, weight="bold")
    T(0.455, SB_Y, "신호강도",                   size=8,   color=MUTED, ha="center")
    T(0.97,  SB_Y, f"SHORT {short_score:.0f}%", size=8.5, color=RED,   weight="bold", ha="right")

    # ════════════════════════════════════════
    # ③ 점수바
    # ════════════════════════════════════════
    BAR_Y = 0.876
    BAR_H = 0.026
    BX    = 0.03
    BW    = 0.94

    ax.add_patch(Rectangle((BX, BAR_Y), BW, BAR_H,
                            transform=ax.transAxes, facecolor=BORDER, edgecolor="none"))
    ax.add_patch(Rectangle((BX, BAR_Y), BW * long_ratio, BAR_H,
                            transform=ax.transAxes, facecolor=GREEN, edgecolor="none"))
    ax.add_patch(Rectangle((BX + BW * (1 - short_ratio), BAR_Y),
                            BW * short_ratio, BAR_H,
                            transform=ax.transAxes, facecolor=RED, edgecolor="none"))

    HR(0.863)

    # ════════════════════════════════════════
    # ④ 캔들차트
    # ════════════════════════════════════════
    CHART_B = 0.550
    CHART_T = 0.857
    chart_ax = fig.add_axes([0.03, CHART_B, 0.93, CHART_T - CHART_B])
    _draw_chart(chart_ax, candles_15m, sig)

    # ════════════════════════════════════════
    # ⑤ 상황 불릿
    # ════════════════════════════════════════
    BUL_Y = 0.534
    DOT(0.044, BUL_Y, r=0.006, color=bullet_color)
    T(0.066, BUL_Y, bullet_text, size=8.5, color=MUTED)

    HR(0.518)

    # ════════════════════════════════════════
    # ⑥ 타임프레임
    # ════════════════════════════════════════
    TF_HDR_Y = 0.500
    T(0.04, TF_HDR_Y, "타임프레임", size=9.5, color=WHITE, weight="bold")

    TF_ROW_Y = 0.473
    tf_xs    = [0.03, 0.265, 0.50, 0.735]
    for (label, col), bx in zip(tf_items, tf_xs):
        DOT(bx + 0.010, TF_ROW_Y, r=0.006, color=col)
        T(bx + 0.028, TF_ROW_Y, label, size=8.5, color=WHITE)

    TF_SUM_Y = 0.447
    ax.plot([0.04, 0.04], [TF_SUM_Y - 0.013, TF_SUM_Y + 0.013],
            transform=ax.transAxes, color=tf_sum_color, linewidth=2.5)
    T(0.060, TF_SUM_Y, tf_summary, size=8.5, color=tf_sum_color)

    HR(0.428)

    # ════════════════════════════════════════
    # ⑦ 지표 카드 3열
    # ════════════════════════════════════════
    IND_HDR_Y = 0.412
    T(0.04, IND_HDR_Y, "지표", size=9.5, color=WHITE, weight="bold")

    CW, CH = 0.285, 0.075
    CY     = 0.325
    CXS    = [0.030, 0.357, 0.685]

    ind_data = [
        ("RSI",  f"{rsi:.1f}", rsi_state, rsi_color),
        ("CCI",  f"{cci:.0f}", cci_state, cci_color),
        ("MACD", macd_label,   macd_desc, macd_color),
    ]

    for i, (label, val, state, col) in enumerate(ind_data):
        cx = CXS[i]
        cy = CY
        RECT(cx, cy, CW, CH, face=PANEL, edge=BORDER, r=0.007)
        T(cx + 0.018, cy + CH - 0.016, label, size=8,  color=MUTED)
        T(cx + 0.018, cy + CH * 0.46,  val,   size=15, color=col, weight="bold")
        T(cx + 0.018, cy + 0.010,      state, size=8,  color=col)

    HR(0.316)

    # ════════════════════════════════════════
    # ⑧ 결론
    # ════════════════════════════════════════
    CONC_Y = 0.288
    T(0.04,  CONC_Y, "결론 —",       size=9.5, color=WHITE,            weight="bold")
    T(0.148, CONC_Y, conclusion_main, size=9.5, color=conclusion_color, weight="bold")

    W1_Y = 0.260
    if warn1:
        T(0.04, W1_Y, warn1, size=8.5, color=MUTED)

    W2_Y = 0.235 if warn1 else 0.260
    T(0.04, W2_Y, warn2, size=8.5, color=conclusion_color)

    # 하단 주석
    T(0.5, 0.012, "※ 자동진입 아님 · 15분봉 마감 기준",
      size=7.5, color=DIM, ha="center", alpha=0.7)

    # ════════════════════════════════════════
    # PNG 출력
    # ════════════════════════════════════════
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI,
                bbox_inches="tight", facecolor=BG, pad_inches=0.08)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─── 전광판 (1H 마감) ─────────────────────────────────────

def render_dashboard_card(sig: dict, candles_1h: list) -> bytes:
    return render_radar_card(sig, candles_1h)


# ─── 레거시 async 함수 ────────────────────────────────────

async def send_radar_album(bot, chat_id: str, signals: list, candles_map: dict):
    try:
        from telegram import InputMediaPhoto
    except ImportError:
        raise RuntimeError("pip install python-telegram-bot 필요")

    media = []
    for sig in signals:
        symbol  = sig.get("symbol", "")
        candles = candles_map.get(symbol, {}).get("15m", [])
        png     = render_radar_card(sig, candles)
        media.append(InputMediaPhoto(media=png))

    if len(media) == 1:
        await bot.send_photo(chat_id=chat_id, photo=media[0].media)
    elif len(media) >= 2:
        await bot.send_media_group(chat_id=chat_id, media=media)


async def send_single_radar(bot, chat_id: str, sig: dict, candles_15m: list):
    png = render_radar_card(sig, candles_15m)
    await bot.send_photo(chat_id=chat_id, photo=png)
