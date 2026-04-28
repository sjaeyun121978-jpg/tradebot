# chart_renderer.py
# Telegram Trading Bot - Radar/Dashboard card renderer
# 목적:
# - 진입레이더 차트 상단과 차트 영역을 카드형 UI로 개선
# - 기존 호출부(render_radar_card, render_dashboard_card, send_radar_album, send_single_radar) 호환 유지
# - 한글 폰트 포함 환경과 Railway 환경 모두 대응

import io
import os
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

KST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────────────────────
# 폰트 셋업
# ─────────────────────────────────────────────────────────────

def _setup_korean_font():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    candidates = [
        os.path.join(base_dir, "tradebot", "render", "fonts", "NanumGothic-Regular.ttf"),
        os.path.join(base_dir, "tradebot", "render", "fonts", "NanumGothic-Bold.ttf"),
        os.path.join(base_dir, "render", "fonts", "NanumGothic-Regular.ttf"),
        os.path.join(base_dir, "render", "fonts", "NanumGothic-Bold.ttf"),
        os.path.join(base_dir, "fonts", "NanumGothic-Regular.ttf"),
        os.path.join(base_dir, "fonts", "NanumGothic-Bold.ttf"),
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic-Regular.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic-Bold.ttf",
    ]

    fm._load_fontmanager(try_read_cache=False)

    for path in candidates:
        if os.path.exists(path):
            try:
                fm.fontManager.addfont(path)
                prop = fm.FontProperties(fname=path)
                font_name = prop.get_name()

                matplotlib.rcParams["font.family"] = font_name
                matplotlib.rcParams["font.sans-serif"] = [font_name]
                matplotlib.rcParams["axes.unicode_minus"] = False

                print(f"[FONT] loaded: {font_name} / {path}", flush=True)
                return prop
            except Exception as e:
                print(f"[FONT ERROR] {path}: {e}", flush=True)

    matplotlib.rcParams["font.family"] = "DejaVu Sans"
    matplotlib.rcParams["axes.unicode_minus"] = False
    print("[FONT] Nanum not found. fallback: DejaVu Sans", flush=True)
    return None


FONT_PROP = _setup_korean_font()


def now_kst():
    return datetime.now(KST)


# ─────────────────────────────────────────────────────────────
# 팔레트
# ─────────────────────────────────────────────────────────────

BG = "#0f1118"
BG2 = "#11151e"
PANEL = "#171c25"
PANEL2 = "#1a202a"
PANEL3 = "#202632"
BORDER = "#2a303b"
GRID = "#2a3038"
WHITE = "#f1f3f5"
TEXT = "#d5d8de"
MUTED = "#9da3ad"
DIM = "#626a76"
GREEN = "#28d36f"
GREEN_DARK = "#12391f"
RED = "#ff4b43"
RED_DARK = "#3a1718"
AMBER = "#f0ae2d"
AMBER_DARK = "#3a2b0f"
PURPLE = "#a681ff"
BLUE = "#4da3ff"
GRAY_BAR = "#252c33"


# ─────────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────────

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
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 10:
        return f"{v:,.2f}"
    return f"{v:,.4f}"


def _fmt_price(v):
    v = _safe(v)
    if abs(v) >= 1000:
        return f"{v:,.2f}"
    if abs(v) >= 100:
        return f"{v:,.2f}"
    if abs(v) >= 10:
        return f"{v:,.3f}"
    return f"{v:,.4f}"


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
    e = vals[0]
    out = []
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _trend_color(v):
    t = str(v or "").upper()
    if t == "UP":
        return GREEN
    if t == "DOWN":
        return RED
    return MUTED


def _trend_ko(v):
    t = str(v or "").upper()
    if t == "UP":
        return "상승"
    if t == "DOWN":
        return "하락"
    return "횡보"


def _macd_ko(v):
    return {
        "BULLISH": ("양전환", GREEN, "상승전환"),
        "BEARISH": ("음전환", RED, "하락전환"),
        "POSITIVE": ("양전환", GREEN, "상승전환"),
        "NEGATIVE": ("음전환", RED, "하락전환"),
        "NEUTRAL": ("중립", MUTED, "방향미확정"),
    }.get(str(v or "NEUTRAL").upper(), ("중립", MUTED, "방향미확정"))


def _entry_label(direction, is_range=False, range_pos=None, long_score=0, short_score=0):
    direction = str(direction or "WAIT").upper()
    if direction == "LONG":
        return "LONG", GREEN, GREEN_DARK
    if direction == "SHORT":
        return "SHORT", RED, RED_DARK
    return "WAIT", AMBER, AMBER_DARK



def _compact_reason_text(text, max_len=24):
    """상단 사유 문구 전용 보정.
    - 잘린 괄호 자동 보정
    - 너무 긴 괄호형 상세 문구는 카드 폭에 맞게 축약
    """
    t = str(text or "").replace("·", "/").strip()
    while "  " in t:
        t = t.replace("  ", " ")

    if t.count("(") > t.count(")"):
        t += ")"

    if len(t) <= max_len:
        return t

    normalized = (
        t.replace("(", " / ")
         .replace(")", "")
         .replace(":", " / ")
         .replace("<", " ")
         .replace(">", " ")
    )
    parts = [x.strip() for x in normalized.split("/") if x.strip()]

    if parts:
        out = parts[0]
        for part in parts[1:]:
            candidate = f"{out} / {part}"
            if len(candidate) <= max_len:
                out = candidate
            else:
                break
        if out:
            return out

    cut = t[:max_len].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip("(/: ")

def _reason_text(sig):
    reason = _get(sig, "reason", "message", "summary", default=None)
    if reason:
        return _compact_reason_text(reason, max_len=24)

    is_range = _get(sig, "is_range", default=False)
    range_pos = _get(sig, "range_pos", default=None)
    bb_squeeze = _get(sig, "bb_squeeze", default=False)
    trend_1h = _get(sig, "trend_1h", default="SIDEWAYS")
    trend_4h = _get(sig, "trend_4h", default="SIDEWAYS")

    if is_range and range_pos == "MIDDLE":
        return "박스 중앙 / 타임프레임 충돌 / 거래량 약함"
    if is_range and range_pos == "TOP":
        return "박스 상단 근접 / 저항 돌파 확인 필요"
    if is_range and range_pos == "BOTTOM":
        return "박스 하단 근접 / 지지 이탈 확인 필요"
    if bb_squeeze:
        return "변동성 수축 / 방향 확정 대기"
    if trend_1h != trend_4h:
        return "타임프레임 혼재 / 상위봉 우선 확인"
    return "방향 확인 중 / 거래량 확인 필요"


# ─────────────────────────────────────────────────────────────
# 캔들 정규화
# ─────────────────────────────────────────────────────────────

def _norm_candles(candles, n=34):
    rows = []
    for c in (candles or [])[-n:]:
        if isinstance(c, dict):
            o = _safe(c.get("open"))
            h = _safe(c.get("high"))
            l = _safe(c.get("low"))
            cl = _safe(c.get("close"))
        elif isinstance(c, (list, tuple)) and len(c) >= 5:
            # Bybit raw list 호환: [time, open, high, low, close, volume, ...]
            o = _safe(c[1])
            h = _safe(c[2])
            l = _safe(c[3])
            cl = _safe(c[4])
        else:
            continue

        if h > 0 and l > 0 and cl > 0:
            rows.append({"open": o, "high": h, "low": l, "close": cl})
    return rows


# ─────────────────────────────────────────────────────────────
# 차트 영역
# ─────────────────────────────────────────────────────────────

def _draw_chart(ax, candles, sig, chart_tf="15M"):
    import numpy as np
    from matplotlib.patches import Rectangle

    ax.set_facecolor(PANEL)
    for spine in ax.spines.values():
        spine.set_visible(False)

    rows = _norm_candles(candles, 34)
    if len(rows) < 3:
        ax.text(
            0.5,
            0.5,
            "데이터 부족",
            transform=ax.transAxes,
            color=MUTED,
            ha="center",
            va="center",
            fontsize=18,
            fontproperties=FONT_PROP,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        return

    opens = [r["open"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    closes = [r["close"] for r in rows]
    x = np.arange(len(rows))

    price = _safe(_get(sig, "current_price", "price", default=closes[-1]), closes[-1])
    support = _safe(_get(sig, "support", "range_low", default=min(lows)), min(lows))
    resistance = _safe(_get(sig, "resistance", "range_high", default=max(highs)), max(highs))
    middle = (support + resistance) / 2 if support and resistance else price

    ylo = min(min(lows), support, price, middle)
    yhi = max(max(highs), resistance, price, middle)
    pad = (yhi - ylo) * 0.26 if yhi != ylo else price * 0.012
    ax.set_ylim(ylo - pad, yhi + pad)
    ax.set_xlim(-1.0, len(rows) + 6.4)

    # 박스 기준선
    ax.axhline(resistance, color=RED, linestyle=(0, (5, 5)), linewidth=1.25, alpha=0.70, zorder=1)
    ax.axhline(middle, color=AMBER, linestyle=(0, (1.5, 5)), linewidth=1.05, alpha=0.55, zorder=1)
    ax.axhline(support, color=GREEN, linestyle=(0, (5, 5)), linewidth=1.05, alpha=0.55, zorder=1)

    # 캔들
    w = 0.56
    for i, r in enumerate(rows):
        o, h, l, c = r["open"], r["high"], r["low"], r["close"]
        col = GREEN if c >= o else RED
        ax.vlines(i, l, h, color=col, linewidth=1.4, alpha=0.95, zorder=3)
        body_h = max(abs(c - o), (yhi - ylo) * 0.002)
        ax.add_patch(Rectangle(
            (i - w / 2, min(o, c)),
            w,
            body_h,
            facecolor=col,
            edgecolor=col,
            linewidth=0.7,
            zorder=4,
        ))

    # EMA20
    ema20 = _ema(closes, 20)
    ax.plot(x, ema20, color=AMBER, linewidth=2.3, alpha=0.95, zorder=5)

    # 현재가 점선과 마커
    ax.axhline(price, color=WHITE, linestyle=(0, (2, 6)), linewidth=1.05, alpha=0.55, zorder=2)
    ax.scatter([len(rows) - 1], [price], color=WHITE, s=18, zorder=6)

    # 우측 라벨
    lx = len(rows) + 0.95
    ax.text(lx, resistance, f"박스상단 {_fmt(resistance)}", color=RED,
            fontsize=11.5, va="center", ha="left", fontweight="bold", fontproperties=FONT_PROP)
    ax.text(lx, middle, f"중앙 {_fmt(middle)}", color=AMBER,
            fontsize=11.5, va="center", ha="left", fontweight="bold", fontproperties=FONT_PROP)
    ax.text(lx + 3.25, price, _fmt(price), color=WHITE,
            fontsize=12.5, va="center", ha="left", fontweight="bold", fontproperties=FONT_PROP)
    ax.text(lx, support, f"박스하단 {_fmt(support)}", color=GREEN,
            fontsize=11.5, va="center", ha="left", fontweight="bold", fontproperties=FONT_PROP)

    # 축 스타일
    ax.yaxis.tick_right()
    ax.tick_params(axis="y", colors=DIM, labelsize=8, length=0)
    ax.tick_params(axis="x", colors=DIM, labelsize=7, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8, alpha=0.38)
    ax.set_xticks([])
    ax.set_yticklabels([])


# ─────────────────────────────────────────────────────────────
# 메인 렌더링 함수
# ─────────────────────────────────────────────────────────────

def render_radar_card(sig: dict, candles_15m: list) -> bytes:
    from matplotlib.patches import FancyBboxPatch, Rectangle

    symbol = _get(sig, "symbol", default="BTCUSDT")
    base, quote = _split_symbol(symbol)

    current_price = _safe(_get(sig, "current_price", "price", default=0))
    support = _safe(_get(sig, "support", "range_low", default=0))
    resistance = _safe(_get(sig, "resistance", "range_high", default=0))
    long_score = _safe(_get(sig, "long_score", default=0))
    short_score = _safe(_get(sig, "short_score", default=0))
    rsi = _safe(_get(sig, "rsi", default=50))
    cci = _safe(_get(sig, "cci", default=0))
    direction = str(_get(sig, "direction", default="WAIT") or "WAIT").upper()
    is_range = _get(sig, "is_range", default=False)
    range_pos = _get(sig, "range_pos", default=None)
    bb_squeeze = _get(sig, "bb_squeeze", default=False)
    chart_tf = str(_get(sig, "chart_tf", "timeframe", "_chart_tf", default="15M") or "15M").upper()

    if current_price <= 0:
        rows = _norm_candles(candles_15m, 1)
        if rows:
            current_price = rows[-1]["close"]

    trend_15m = _get(sig, "trend_15m", default="SIDEWAYS")
    trend_30m = _get(sig, "trend_30m", default="SIDEWAYS")
    trend_1h = _get(sig, "trend_1h", default="SIDEWAYS")
    trend_4h = _get(sig, "trend_4h", default="SIDEWAYS")

    macd_label, macd_color, macd_desc = _macd_ko(_get(sig, "macd_state", default="NEUTRAL"))

    total = max(long_score + short_score, 1)
    long_ratio = max(0.0, min(1.0, long_score / total))
    short_ratio = max(0.0, min(1.0, short_score / total))

    badge_txt, badge_color, badge_bg = _entry_label(direction, is_range, range_pos, long_score, short_score)
    reason_text = _reason_text(sig)

    if is_range and range_pos == "MIDDLE":
        bullet_color = AMBER
        bullet_title = "박스 중앙"
        bullet_text = f"{_fmt(support)}~{_fmt(resistance)} 사이 · 양방향 노이즈"
    elif is_range and range_pos == "BOTTOM":
        bullet_color = GREEN
        bullet_title = "박스 하단"
        bullet_text = "지지 근접 · 이탈 실패 시 롱 후보"
    elif is_range and range_pos == "TOP":
        bullet_color = RED
        bullet_title = "박스 상단"
        bullet_text = "저항 근접 · 돌파 실패 시 숏 후보"
    elif bb_squeeze:
        bullet_color = AMBER
        bullet_title = "변동성 수축"
        bullet_text = "큰 움직임 임박 · 방향 확인 필수"
    else:
        bullet_color = MUTED
        bullet_title = "감시구간"
        bullet_text = f"{_fmt(support)}~{_fmt(resistance)} · 돌파 확인 후 진입"

    tf_items = [
        (f"15M {_trend_ko(trend_15m)}", _trend_color(trend_15m)),
        (f"30M {_trend_ko(trend_30m)}", _trend_color(trend_30m)),
        (f"1H {_trend_ko(trend_1h)}", _trend_color(trend_1h)),
        (f"4H {_trend_ko(trend_4h)}", _trend_color(trend_4h)),
    ]

    if trend_1h == trend_4h and trend_1h in ("UP", "DOWN"):
        dir_ko = "상승" if trend_1h == "UP" else "하락"
        tf_summary = f"상위봉 {dir_ko} 일치 · 단기 방향 확인"
        tf_sum_color = _trend_color(trend_1h)
    elif trend_1h == "SIDEWAYS" and trend_4h == "SIDEWAYS":
        tf_summary = "상위봉 횡보 · 방향 미확정"
        tf_sum_color = MUTED
    else:
        tf_summary = "타임프레임 혼재 · 상위봉 방향 우선"
        tf_sum_color = AMBER

    if direction == "LONG":
        conclusion_main, conclusion_color = "LONG 우세", GREEN
    elif direction == "SHORT":
        conclusion_main, conclusion_color = "SHORT 우세", RED
    else:
        conclusion_main, conclusion_color = "진입 대기", AMBER

    warn_parts = []
    if trend_1h != trend_4h and "SIDEWAYS" not in (trend_1h, trend_4h):
        warn_parts.append("1H 4H 방향 불일치 · 추세 정렬 확인")
    if rsi > 65:
        warn_parts.append("RSI 과매수 주의")
    elif rsi < 35:
        warn_parts.append("RSI 과매도 주의")

    warn1 = warn_parts[0] if warn_parts else "돌파 이탈 + 거래량 확인 전 진입 금지"

    rsi_color = RED if rsi > 70 else (GREEN if rsi >= 55 else (RED if rsi <= 35 else TEXT))
    rsi_state = "과매수" if rsi > 70 else ("강세" if rsi >= 55 else ("과매도" if rsi <= 35 else "중립"))

    cci_color = GREEN if cci >= 100 else (RED if cci <= -100 else TEXT)
    cci_state = "상승압력" if cci >= 100 else ("하락압력" if cci <= -100 else ("약세" if cci < 0 else "강세"))

    # 모바일 텔레그램에서 읽기 쉬운 세로형 카드
    FIG_W, FIG_H = 7.6, 11.6
    DPI = 160

    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(BG)
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    def T(x, y, s, size=10, color=WHITE, weight="normal", ha="left", va="center", alpha=1.0):
        ax.text(
            x,
            y,
            str(s),
            transform=ax.transAxes,
            fontsize=size,
            color=color,
            fontweight=weight,
            ha=ha,
            va=va,
            alpha=alpha,
            fontproperties=FONT_PROP,
        )

    def HR(y, x0=0.035, x1=0.965, color=BORDER, lw=1.0):
        ax.plot([x0, x1], [y, y], transform=ax.transAxes,
                color=color, linewidth=lw, solid_capstyle="butt")

    def RECT(x, y, w, h, face=PANEL, edge=BORDER, lw=1.0, r=0.018, alpha=1.0):
        ax.add_patch(FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0.002,rounding_size={r}",
            linewidth=lw,
            edgecolor=edge,
            facecolor=face,
            alpha=alpha,
            transform=ax.transAxes,
            clip_on=False,
        ))

    def DOT(x, y, r=0.007, color=GREEN):
        ax.add_patch(plt.Circle((x, y), r, color=color,
                                transform=ax.transAxes, clip_on=False, zorder=5))

    # 배경 메인 카드
    RECT(0.018, 0.018, 0.964, 0.964, face=BG2, edge="#171b24", lw=1.0, r=0.030)

    # 카드 타입 라벨: 텔레그램에서 여러 이미지가 동시에 와도 용도를 즉시 구분한다.
    T(0.055, 0.965, "진입레이더", size=10.5, color=MUTED, weight="bold")

    # ── Header: 오른쪽 예시처럼 크게 표시
    HDR_Y = 0.925
    T(0.055, HDR_Y, base, size=31, color=PURPLE, weight="bold")
    T(0.205, HDR_Y, quote, size=21, color=WHITE, weight="bold")

    RECT(0.355, HDR_Y - 0.026, 0.170, 0.042, face=badge_bg, edge=badge_color, lw=1.4, r=0.011)
    T(0.440, HDR_Y - 0.004, badge_txt, size=16, color=badge_color, weight="bold", ha="center")

    T(0.940, HDR_Y + 0.004, _fmt_price(current_price), size=28, color=WHITE, weight="bold", ha="right")
    T(0.940, HDR_Y - 0.038, now_kst().strftime("%H:%M KST"), size=17, color=MUTED, ha="right")

    HR(0.875, x0=0.020, x1=0.980, color=BORDER, lw=1.2)

    # ── Signal status: 겹침 방지용 3행 구조
    # 1행: 방향 배지 + 사유
    STATUS_Y = 0.842
    RECT(0.055, STATUS_Y - 0.026, 0.135, 0.046, face=badge_bg, edge=badge_color, lw=1.4, r=0.012)
    T(0.122, STATUS_Y - 0.002, badge_txt, size=16.5, color=badge_color, weight="bold", ha="center")
    T(0.220, STATUS_Y, reason_text, size=13.2, color=MUTED, weight="bold")

    # 2행: LONG/신호강도/SHORT 라벨
    SCORE_Y = 0.775
    T(0.055, SCORE_Y, f"LONG {long_score:.0f}%", size=14.2, color=GREEN, weight="bold", va="bottom")
    T(0.500, SCORE_Y, "신호강도", size=13.8, color=MUTED, weight="bold", ha="center", va="bottom")
    T(0.945, SCORE_Y, f"SHORT {short_score:.0f}%", size=14.2, color=RED, weight="bold", ha="right", va="bottom")

    # 3행: 강도 바
    BAR_X = 0.055
    BAR_W = 0.890
    BAR_H = 0.013
    BAR_Y = 0.742
    RECT(BAR_X, BAR_Y, BAR_W, BAR_H, face=GRAY_BAR, edge=GRAY_BAR, lw=0, r=0.007)
    ax.add_patch(FancyBboxPatch(
        (BAR_X, BAR_Y), BAR_W * long_ratio, BAR_H,
        boxstyle="round,pad=0.002,rounding_size=0.007",
        linewidth=0, facecolor=GREEN, transform=ax.transAxes, clip_on=False,
    ))
    if short_ratio >= 0.015:
        ax.add_patch(FancyBboxPatch(
            (BAR_X + BAR_W * (1 - short_ratio), BAR_Y), BAR_W * short_ratio, BAR_H,
            boxstyle="round,pad=0.002,rounding_size=0.007",
            linewidth=0, facecolor=RED, transform=ax.transAxes, clip_on=False,
        ))

    HR(0.708, x0=0.020, x1=0.980, color=BORDER, lw=1.2)

    # ── Chart card: 둥근 패널 + 내부 차트
    CHART_CARD_X = 0.055
    CHART_CARD_Y = 0.398
    CHART_CARD_W = 0.890
    CHART_CARD_H = 0.300
    RECT(CHART_CARD_X, CHART_CARD_Y, CHART_CARD_W, CHART_CARD_H,
         face=PANEL, edge="#1e2530", lw=1.1, r=0.020)

    # 차트 헤더는 axes 밖에 배치해 가격 라벨과 겹치지 않게 한다.
    T(CHART_CARD_X + 0.035, CHART_CARD_Y + CHART_CARD_H - 0.035, f"{chart_tf} 캔들차트",
      size=16.5, color=TEXT, weight="bold")
    T(CHART_CARD_X + CHART_CARD_W - 0.035, CHART_CARD_Y + CHART_CARD_H - 0.035, "— EMA20",
      size=14.5, color=AMBER, weight="bold", ha="right")

    chart_ax = fig.add_axes([
        CHART_CARD_X + 0.028,
        CHART_CARD_Y + 0.078,
        CHART_CARD_W - 0.056,
        CHART_CARD_H - 0.130,
    ])
    _draw_chart(chart_ax, candles_15m, sig, chart_tf=chart_tf)

    # 차트 하단 박스 설명
    DOT(CHART_CARD_X + 0.038, CHART_CARD_Y + 0.040, r=0.010, color=bullet_color)
    T(CHART_CARD_X + 0.065, CHART_CARD_Y + 0.040, bullet_title, size=16.5, color=bullet_color, weight="bold")
    T(CHART_CARD_X + 0.190, CHART_CARD_Y + 0.040, bullet_text, size=15.2, color=TEXT)

    # ── Timeframe
    TF_TOP = 0.355
    T(0.055, TF_TOP, "타임프레임", size=16, color=WHITE, weight="bold")

    TF_ROW_Y = 0.320
    tf_xs = [0.055, 0.287, 0.520, 0.752]
    for (label, col), bx in zip(tf_items, tf_xs):
        DOT(bx, TF_ROW_Y, r=0.007, color=col)
        T(bx + 0.020, TF_ROW_Y, label, size=13.5, color=TEXT, weight="bold")

    ax.plot([0.055, 0.055], [0.276, 0.302], transform=ax.transAxes, color=tf_sum_color, linewidth=3.0)
    T(0.073, 0.289, tf_summary, size=13.5, color=tf_sum_color, weight="bold")

    HR(0.260, color=BORDER)

    # ── Indicators
    T(0.055, 0.235, "지표", size=16, color=WHITE, weight="bold")

    CW, CH = 0.278, 0.080
    CY = 0.130
    CXS = [0.055, 0.361, 0.667]

    ind_data = [
        ("RSI", f"{rsi:.1f}", rsi_state, rsi_color),
        ("CCI", f"{cci:.0f}", cci_state, cci_color),
        ("MACD", macd_label, macd_desc, macd_color),
    ]

    for i, (label, val, state, col) in enumerate(ind_data):
        cx = CXS[i]
        RECT(cx, CY, CW, CH, face=PANEL2, edge=BORDER, lw=1.0, r=0.010)
        T(cx + 0.020, CY + CH - 0.020, label, size=10.5, color=MUTED, weight="bold")
        T(cx + 0.020, CY + CH * 0.45, val, size=18, color=col, weight="bold")
        T(cx + 0.020, CY + 0.014, state, size=10.5, color=col, weight="bold")

    HR(0.108, color=BORDER)

    # ── Conclusion
    T(0.055, 0.075, "결론 —", size=14, color=TEXT, weight="bold")
    T(0.150, 0.075, conclusion_main, size=14, color=conclusion_color, weight="bold")
    T(0.055, 0.047, warn1, size=12.5, color=conclusion_color, weight="bold")

    T(0.500, 0.022, "※ 자동진입 아님 · 봉 마감 기준", size=9.5, color=DIM, ha="center", alpha=0.85)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight", facecolor=BG, pad_inches=0.02)
    plt.close(fig)
    buf.seek(0)
    return buf.read()



async def send_radar_album(bot, chat_id: str, signals: list, candles_map: dict):
    try:
        from telegram import InputMediaPhoto
    except ImportError:
        raise RuntimeError("pip install python-telegram-bot 필요")

    media = []
    for sig in signals:
        symbol = sig.get("symbol", "")
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
