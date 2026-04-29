# step_card.py v3
# WAIT / PRE / REAL 3단계 카드 렌더러
# ──────────────────────────────────────────────────────────────

import io
import os
import numpy as np
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import FancyBboxPatch, Rectangle

KST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────────────────────
# 색상 팔레트 (v3 — 테두리 없음, 플랫 톤)
# ─────────────────────────────────────────────────────────────
BG          = "#090d14"
BG_CARD     = "#0f141d"
PANEL       = "#151b26"
PANEL2      = "#1a2230"
BORDER      = "none"
GRID_COL    = "#202838"

WHITE       = "#f1f3f6"
TEXT        = "#c9d0da"
MUTED       = "#8792a2"
DIM         = "#4b5665"

CANDLE_UP   = "#4fb987"
CANDLE_DOWN = "#d45f58"

THEME = {
    "WAIT": {
        "primary":    "#c49430",
        "primary_bg": "#151b26",
        "step":       "STEP 1",
        "label":      "WAIT",
        "sub":        "진입 금지",
    },
    "EARLY": {
        "primary":    "#5a9fd4",   # 소프트 블루 — 선행 진입
        "primary_bg": "#151b26",
        "step":       "STEP 2",
        "label":      "EARLY",
        "sub":        "초기 진입 구간",
    },
    "PRE": {
        "primary":    "#3d9468",
        "primary_bg": "#151b26",
        "step":       "STEP 3",
        "label":      "PRE",
        "sub":        "조건 확인 중",
    },
    "REAL": {
        "primary":    "#b53c32",
        "primary_bg": "#151b26",
        "step":       "STEP 4",
        "label":      "REAL",
        "sub":        "진입 가능",
    },
    "HOLD": {
        "primary":    "#7b68c8",   # 퍼플 — 포지션 유지
        "primary_bg": "#151b26",
        "step":       "HOLD",
        "label":      "HOLD",
        "sub":        "포지션 유지",
    },
    "EXIT": {
        "primary":    "#d97c2a",   # 오렌지 — 청산 필요
        "primary_bg": "#151b26",
        "step":       "EXIT",
        "label":      "EXIT",
        "sub":        "포지션 정리",
    },
}

GAUGE_FILL  = "#5aa7d8"
GAUGE_TRACK = "#232d3d"

COND_OK      = "#5bbf8d"
COND_FAIL    = "#d86b63"
COND_PARTIAL = "#d7ae5f"

LINE_RED    = "#b53c32"
LINE_GREEN  = "#2e9460"
LINE_AMBER  = "#c49430"


# ─────────────────────────────────────────────────────────────
# 폰트 — Regular 기본, Bold는 제목 일부에만 사용
# ─────────────────────────────────────────────────────────────
def _setup_font():
    """Regular를 기본 폰트로 로드. Bold는 별도 prop으로 반환."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    regular_paths = [
        os.path.join(base, "render", "fonts", "NanumGothic-Regular.ttf"),
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]
    bold_paths = [
        os.path.join(base, "render", "fonts", "NanumGothic-Bold.ttf"),
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    ]
    try:
        fm._load_fontmanager(try_read_cache=False)
    except Exception:
        pass

    reg_prop  = None
    bold_prop = None

    # Regular 로드
    for p in regular_paths:
        if os.path.exists(p):
            try:
                fm.fontManager.addfont(p)
                prop = fm.FontProperties(fname=p)
                name = prop.get_name()
                matplotlib.rcParams["font.family"]      = name
                matplotlib.rcParams["font.sans-serif"]  = [name]
                matplotlib.rcParams["axes.unicode_minus"] = False
                reg_prop = prop
                break
            except Exception:
                pass

    # Bold 로드 (제목 전용)
    for p in bold_paths:
        if os.path.exists(p):
            try:
                fm.fontManager.addfont(p)
                bold_prop = fm.FontProperties(fname=p)
                break
            except Exception:
                pass

    if reg_prop is None:
        matplotlib.rcParams["font.family"]      = "DejaVu Sans"
        matplotlib.rcParams["axes.unicode_minus"] = False

    return reg_prop, bold_prop


FONT_PROP, FONT_PROP_BOLD = _setup_font()


# ─────────────────────────────────────────────────────────────
# 사용자 노출 문구 정규화 — "신뢰도" / "WATCH" 금지
# ─────────────────────────────────────────────────────────────
def _clean_user_text(text):
    if text is None:
        return "-"
    text = str(text)
    text = text.replace("신뢰도 매우 부족", "조건 상태 부족")
    text = text.replace("신뢰도 부족",      "조건 부족")
    text = text.replace("신뢰도",           "조건 상태")
    text = text.replace("WATCH",            "WAIT")
    return text


# ─────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────
def _s(v, d=0.0):
    try:
        return float(v) if v is not None else d
    except Exception:
        return d

def _g(sig, *keys, default=None):
    for k in keys:
        if isinstance(sig, dict) and k in sig and sig[k] is not None:
            return sig[k]
    return default

def _fp(v):
    v = _s(v)
    if abs(v) >= 10000: return f"{v:,.0f}"
    if abs(v) >= 1000:  return f"{v:,.2f}"
    if abs(v) >= 100:   return f"{v:,.2f}"
    if abs(v) >= 10:    return f"{v:,.3f}"
    return f"{v:,.4f}"

def _ema(closes, period=20):
    vals = [_s(v) for v in closes if v is not None]
    if not vals: return []
    k = 2.0 / (period + 1)
    e = vals[0]
    out = []
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out

def _norm_candles(candles, n=30):
    rows = []
    for c in (candles or [])[-n:]:
        if isinstance(c, dict):
            o=_s(c.get("open")); h=_s(c.get("high"))
            l=_s(c.get("low")); cl=_s(c.get("close"))
        elif isinstance(c, (list, tuple)) and len(c) >= 5:
            o=_s(c[1]); h=_s(c[2]); l=_s(c[3]); cl=_s(c[4])
        else:
            continue
        if h > 0 and l > 0 and cl > 0:
            rows.append({"open":o, "high":h, "low":l, "close":cl})
    return rows

def _now_kst():
    return datetime.now(KST)


# ─────────────────────────────────────────────────────────────
# 아이콘 직접 그리기
# ─────────────────────────────────────────────────────────────
def _draw_icon(ax, card_type, cx, cy, color, r=0.050):
    if card_type == "WAIT":
        bw, bh = r * 0.28, r * 0.72
        for dx in [-bw * 0.80, bw * 0.80]:
            ax.add_patch(FancyBboxPatch(
                (cx + dx - bw/2, cy - bh/2), bw, bh,
                boxstyle="round,pad=0.005",
                facecolor=color, edgecolor="none",
                transform=ax.transAxes, clip_on=False, zorder=5
            ))
    elif card_type == "EARLY":
        # 번개 / 즉각 진입 — 위 방향 화살표 두 개
        for dx in [-r*0.28, r*0.28]:
            pts_x = [cx+dx-r*0.20, cx+dx+r*0.20, cx+dx]
            pts_y = [cy-r*0.15,    cy-r*0.15,    cy+r*0.72]
            ax.fill(pts_x, pts_y, color=color, alpha=0.90,
                    transform=ax.transAxes, clip_on=False, zorder=5)
    elif card_type == "PRE":
        tri_h = r * 0.55
        tri_w = r * 0.65
        for sign in [1, -1]:
            pts_x = [cx - tri_w, cx + tri_w, cx]
            pts_y = [cy + sign * tri_h * 0.1, cy + sign * tri_h * 0.1, cy + sign * tri_h]
            ax.fill(pts_x, pts_y, color=color, alpha=0.88,
                    transform=ax.transAxes, clip_on=False, zorder=5)
    else:
        arrow_h = r * 0.72
        arrow_w = r * 0.55
        body_w  = arrow_w * 0.38
        head_h  = arrow_h * 0.50
        pts_x = [cx - arrow_w/2, cx + arrow_w/2, cx]
        pts_y = [cy + head_h * 0.1, cy + head_h * 0.1, cy + arrow_h * 0.9]
        ax.fill(pts_x, pts_y, color=color, alpha=0.92,
                transform=ax.transAxes, clip_on=False, zorder=5)
        ax.add_patch(Rectangle(
            (cx - body_w/2, cy - arrow_h * 0.55),
            body_w, head_h * 0.75,
            facecolor=color, edgecolor="none", alpha=0.92,
            transform=ax.transAxes, clip_on=False, zorder=5
        ))


# ─────────────────────────────────────────────────────────────
# 조건 리스트 정규화 (decision/result의 conditions 우선)
# ─────────────────────────────────────────────────────────────
def _normalize_conditions(raw_conditions):
    """
    허용 형식:
    - [{"text": "거래량 증가", "status": "ok"}, ...]
    - ["거래량 증가", "15M 종가 대기", ...]  # 문자열은 partial
    """
    if not raw_conditions:
        return []

    out = []
    for item in raw_conditions[:3]:
        if isinstance(item, dict):
            text = (
                item.get("text") or item.get("label")
                or item.get("name") or item.get("condition")
                or "조건 확인"
            )
            status = str(item.get("status") or item.get("state") or "partial").lower()
            if status in ("true", "done", "pass", "passed", "ok", "hit", "success"):
                status = "ok"
            elif status in ("false", "fail", "failed", "x", "no"):
                status = "fail"
            else:
                status = "partial"
        else:
            text = str(item)
            status = "partial"

        icon = "O" if status == "ok" else ("X" if status == "fail" else "-")
        out.append((icon, text, status))

    while len(out) < 3:
        out.append(("-", "조건 확인 중", "partial"))

    return out[:3]


def _build_conditions(card_type, sig, hits=None, fails=None):
    # decision/result payload의 conditions 우선
    payload_conditions = _normalize_conditions(
        _g(sig, "conditions", "condition_list", default=None)
    )
    if payload_conditions:
        return payload_conditions

    direction = str(_g(sig, "direction", default="WAIT") or "WAIT").upper()
    volume    = _s(_g(sig, "volume",     default=0))
    avg_vol   = _s(_g(sig, "avg_volume", default=0))
    vol_ratio = volume / avg_vol if avg_vol > 0 else 0
    macd      = str(_g(sig, "macd_state", default="NEUTRAL") or "NEUTRAL").upper()
    is_range  = _g(sig, "is_range",  default=False)
    range_pos = str(_g(sig, "range_pos", default="") or "").upper()
    above_ema = bool(_g(sig, "above_ema20", default=False))
    below_ema = bool(_g(sig, "below_ema20", default=False))
    trend_15m = str(_g(sig, "trend_15m", default="SIDEWAYS") or "SIDEWAYS").upper()
    trend_1h  = str(_g(sig, "trend_1h",  default="SIDEWAYS") or "SIDEWAYS").upper()

    if card_type == "WAIT":
        c1 = vol_ratio >= 1.5
        cand = str(_g(sig, "candidate_direction", "direction", default="WAIT") or "WAIT").upper()
        block_reason = str(_g(sig, "block_reason", default="") or "")
        warnings_list = _g(sig, "warnings", default=[]) or []
        has_warnings_only = not block_reason and len(warnings_list) > 0

        if cand in ("LONG", "SHORT"):
            dir_ko = "롱" if cand == "LONG" else "숏"
            cond2_text = block_reason[:22] if block_reason else (warnings_list[0][:22] if warnings_list else "진입 조건 대기 중")
            cond3_text = warnings_list[0][:22] if (has_warnings_only and warnings_list) else "추가 조건 확인 필요"
            return [
                ("O" if c1 else "-",
                 f"거래량 {vol_ratio:.1f}배" if c1 else f"거래량 부족 ({vol_ratio:.1f}배)",
                 "ok" if c1 else "partial"),
                ("-", cond2_text, "partial" if has_warnings_only else "fail"),
                ("-", cond3_text, "partial"),
            ]
        else:
            return [
                ("X", "방향 후보 없음", "fail"),
                ("X", "박스 상단 돌파 필요", "fail"),
                ("-", "15M 확정 대기", "partial"),
            ]

    if card_type == "PRE":
        if hits and len(hits) >= 1:
            conds = [("O", h, "ok") for h in hits[:3]]
            while len(conds) < 3:
                conds.append(("-", "조건 확인 중", "partial"))
            return conds
        c1 = vol_ratio >= 1.0
        c2 = macd in ("BULLISH", "POSITIVE")
        c3 = (is_range and range_pos == "BOTTOM") if direction == "LONG" else (is_range and range_pos == "TOP")
        return [
            ("-" if not c1 else "O", f"거래량 {vol_ratio:.1f}배" + ("" if c1 else " (부족)"), "ok" if c1 else "partial"),
            ("-" if not c2 else "O", "15M 증가 상단 마감" if c2 else "15M 방향 확인 중", "ok" if c2 else "partial"),
            ("O" if c3 else "-",    "박스 상단 돌파 완료" if c3 else "박스 위치 확인 중", "ok" if c3 else "partial"),
        ]

    # REAL
    if hits and len(hits) >= 1:
        conds = [("O", h, "ok") for h in hits[:3]]
        while len(conds) < 3:
            conds.append(("O", "조건 충족", "ok"))
        return conds
    c1 = vol_ratio >= 1.5
    c2 = above_ema if direction == "LONG" else below_ema
    c3 = (trend_15m == "UP" and trend_1h in ("UP","SIDEWAYS")) if direction == "LONG" else \
         (trend_15m == "DOWN" and trend_1h in ("DOWN","SIDEWAYS"))
    return [
        ("O" if c1 else "X", f"거래량 {vol_ratio:.1f}배 이상 확인", "ok" if c1 else "fail"),
        ("O" if c2 else "X", "15M 증가 상단 마감",                  "ok" if c2 else "fail"),
        ("O" if c3 else "X", "박스 상단 돌파 완료",                 "ok" if c3 else "fail"),
    ]


def _calc_gauge(card_type, sig, hits=None):
    confidence = _s(_g(sig, "confidence", default=0))
    volume     = _s(_g(sig, "volume",     default=0))
    avg_vol    = _s(_g(sig, "avg_volume", default=0))
    vol_ratio  = volume / avg_vol if avg_vol > 0 else 0

    if card_type == "WAIT":
        score = 0
        if vol_ratio >= 0.5: score += 18
        if vol_ratio >= 1.0: score += 12
        if confidence >= 60: score += 15
        if confidence >= 72: score += 8
        return min(score, 52)
    if card_type == "PRE":
        base  = min(confidence * 0.55, 58)
        bonus = min(len(hits or []) * 6, 27)
        return min(int(base + bonus), 84)
    if hits:
        return min(85 + len(hits) * 5, 100)
    return min(int(confidence), 100)


# ─────────────────────────────────────────────────────────────
# 게이지
# ─────────────────────────────────────────────────────────────
def _draw_gauge(ax, pct):
    ax.set_facecolor("none")
    ax.set_xlim(-1.35, 1.35)
    ax.set_ylim(-1.35, 1.35)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.add_patch(plt.Circle((0,0), 1.0, color=PANEL2, zorder=1))

    theta_track = np.linspace(np.radians(135), np.radians(-135), 400)
    ax.plot(np.cos(theta_track)*0.80, np.sin(theta_track)*0.80,
            color=GAUGE_TRACK, lw=8.0, solid_capstyle="round", zorder=2)

    if pct > 1:
        span  = pct / 100.0 * 270
        end_a = 135 - span
        theta_prog = np.linspace(np.radians(135), np.radians(end_a),
                                  max(int(span*4), 4))
        ax.plot(np.cos(theta_prog)*0.80, np.sin(theta_prog)*0.80,
                color=GAUGE_FILL, lw=8.0, solid_capstyle="round", zorder=3)
        ax.add_patch(plt.Circle(
            (np.cos(np.radians(end_a))*0.80, np.sin(np.radians(end_a))*0.80),
            0.055, color=GAUGE_FILL, zorder=4
        ))

    ax.text(0, 0.10, f"{int(pct)}%", ha="center", va="center",
            fontsize=17, color=WHITE, fontweight="bold",
            fontproperties=FONT_PROP, zorder=5)
    ax.text(0, -0.40, "조건 충족률", ha="center", va="center",
            fontsize=7, color=MUTED, fontproperties=FONT_PROP, zorder=5)


# ─────────────────────────────────────────────────────────────
# 1H 차트 — 가격 라벨 우측 고정, 겹침 방지
# ─────────────────────────────────────────────────────────────
def _draw_chart(ax, candles_1h, sig, card_type, theme_color):
    ax.set_facecolor(PANEL)
    for sp in ax.spines.values():
        sp.set_visible(False)

    rows = _norm_candles(candles_1h, 30)
    if len(rows) < 3:
        ax.set_facecolor(PANEL)
        ax.set_xticks([])
        ax.set_yticks([])
        return

    opens  = [r["open"]  for r in rows]
    highs  = [r["high"]  for r in rows]
    lows   = [r["low"]   for r in rows]
    closes = [r["close"] for r in rows]
    x      = np.arange(len(rows))

    price      = _s(_g(sig, "current_price", default=closes[-1]), closes[-1])
    _raw_sup   = _s(_g(sig, "support",    "range_low",  default=min(lows)),  min(lows))
    _raw_res   = _s(_g(sig, "resistance", "range_high", default=max(highs)), max(highs))
    resistance = max(_raw_sup, _raw_res)
    support    = min(_raw_sup, _raw_res)
    middle     = (support + resistance) / 2

    entry_p   = _s(_g(sig, "entry",    default=0))
    invalid_p = _s(_g(sig, "stop", "stop_loss", default=0))

    all_vals = [min(lows), max(highs), price]
    if card_type == "REAL":
        if entry_p   > 0: all_vals.append(entry_p)
        if invalid_p > 0: all_vals.append(invalid_p)

    ylo = min(all_vals)
    yhi = max(all_vals)
    pad = (yhi - ylo) * 0.20 if yhi != ylo else price * 0.01
    ax.set_ylim(ylo - pad, yhi + pad)

    # xlim 오른쪽 확장 — 라벨 여백 확보
    n_candles = len(rows)
    ax.set_xlim(-0.5, n_candles + 13.5)

    ax.axhline(resistance, color=LINE_RED,   ls=(0,(5,4)), lw=1.05, alpha=0.60, zorder=1)
    ax.axhline(middle,     color=LINE_AMBER, ls=(0,(2,5)), lw=0.85, alpha=0.45, zorder=1)
    ax.axhline(support,    color=LINE_GREEN, ls=(0,(5,4)), lw=0.85, alpha=0.45, zorder=1)

    if card_type == "REAL":
        if entry_p > 0:
            ax.axhline(entry_p,   color=LINE_GREEN, ls=(0,(3,3)), lw=1.2, alpha=0.80, zorder=2)
        if invalid_p > 0:
            ax.axhline(invalid_p, color=LINE_RED,   ls=(0,(3,3)), lw=1.1, alpha=0.70, zorder=2)

    w = 0.54
    for i, r in enumerate(rows):
        o, h, l, c = r["open"], r["high"], r["low"], r["close"]
        col = CANDLE_UP if c >= o else CANDLE_DOWN
        ax.vlines(i, l, h, color=col, lw=1.1, alpha=0.88, zorder=3)
        bh = max(abs(c - o), (yhi - ylo) * 0.0015)
        ax.add_patch(Rectangle((i - w/2, min(o, c)), w, bh,
                                facecolor=col, edgecolor=col, lw=0.4, zorder=4))

    ema20 = _ema(closes, 20)
    ax.plot(x, ema20, color=theme_color, lw=1.9, alpha=0.88, zorder=5)
    ax.axhline(price, color=WHITE, ls=(0,(2,5)), lw=0.8, alpha=0.40, zorder=2)

    # ── 가격 라벨 — 우측 여백 안에 세로 정렬, 겹침 방지 ──────
    lx   = n_candles + 0.6
    fs_v = 6.8   # 가격 숫자
    fs_l = 5.0   # 라벨 문구
    # 최소 이격: y 범위의 4%
    gap  = max((yhi - ylo) * 0.04, price * 0.001)

    label_data = [
        (resistance, _fp(resistance), "박스 상단", LINE_RED),
        (price,      _fp(price),      "현재가",    WHITE),
        (middle,     _fp(middle),     "박스 중앙", LINE_AMBER),
        (support,    _fp(support),    "박스 하단", LINE_GREEN),
    ]
    # 위→아래 정렬 후 최소 간격 보장
    label_data.sort(key=lambda t: t[0], reverse=True)
    placed = []   # 이미 배치한 y 좌표
    for val, price_str, lbl, col in label_data:
        y_pos = val
        for prev_y in placed:
            if abs(y_pos - prev_y) < gap:
                y_pos = prev_y - gap
        placed.append(y_pos)
        ax.text(lx, y_pos, price_str, color=col, fontsize=fs_v,
                va="bottom", ha="left", fontproperties=FONT_PROP)
        ax.text(lx, y_pos, lbl,       color=col, fontsize=fs_l,
                va="top",    ha="left", fontproperties=FONT_PROP)

    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(axis="y", color=GRID_COL, lw=0.5, alpha=0.30)


# ─────────────────────────────────────────────────────────────
# 메인 카드 렌더링
# ─────────────────────────────────────────────────────────────
def ensure_chart_data(candles_1h: list, current_price: float, min_count: int = 15) -> list:
    """캔들 데이터 부족/없으면 current_price 기반 fallback 생성 — 차트는 항상 표시"""
    if candles_1h and len(candles_1h) >= min_count:
        return candles_1h
    base = float(current_price or 0)
    if base <= 0:
        base = 100.0
    fallback = []
    for i in range(max(min_count, 20)):
        drift = ((i % 7) - 3) * 0.0015
        op = base * (1 + drift)
        cl = base * (1 + drift + 0.0008)
        fallback.append({
            "open": op, "high": max(op,cl)*1.002,
            "low":  min(op,cl)*0.998, "close": cl,
        })
    # 기존 캔들이 일부 있으면 앞에 붙임
    return list(candles_1h or []) + fallback[:max(min_count - len(candles_1h or []), 0)]


def normalize_box_levels(sig: dict) -> tuple:
    """sig에서 support/resistance 추출 → (top, mid, bottom) 역전 방지"""
    price = _s(_g(sig, "current_price", default=0))
    raw_res = _s(_g(sig, "resistance", "range_high", default=0))
    raw_sup = _s(_g(sig, "support",    "range_low",  default=0))
    if raw_res <= 0 and raw_sup <= 0:
        p = price or 100.0
        raw_res, raw_sup = p * 1.01, p * 0.99
    top    = max(raw_res, raw_sup) or (price * 1.01)
    bottom = min(raw_res, raw_sup) or (price * 0.99)
    mid    = (top + bottom) / 2
    return top, mid, bottom


def _draw_bottom_info(ax, card_type: str, sig: dict, primary: str, is_watch: bool = False):
    """
    하단 정보 2분할 카드.
    HOLD/EXIT는 전용 표시 (hold_score / exit_type / action_text).
    나머지는 기존 시나리오 / 상태 2분할 유지.
    """
    def TI(x, y, s, size=7.0, color=TEXT, ha="left", va="center", alpha=1.0):
        ax.text(x, y, _clean_user_text(str(s)), transform=ax.transAxes,
                fontsize=size, color=color, fontweight="normal",
                ha=ha, va=va, alpha=alpha, fontproperties=FONT_PROP, zorder=6)

    def TI_TITLE(x, y, s, size=7.2, color=WHITE):
        fp = FONT_PROP_BOLD if FONT_PROP_BOLD else FONT_PROP
        ax.text(x, y, _clean_user_text(str(s)), transform=ax.transAxes,
                fontsize=size, color=color, fontweight="bold",
                ha="left", va="center", fontproperties=fp, zorder=6)

    CARD_X = 0.040
    CARD_Y = 0.010
    CARD_W = 0.920
    CARD_H = 0.100
    MID_X  = CARD_X + CARD_W * 0.50

    ax.add_patch(FancyBboxPatch(
        (CARD_X, CARD_Y), CARD_W, CARD_H,
        boxstyle="round,pad=0.002,rounding_size=0.010",
        fc=PANEL2, ec="none", lw=0,
        transform=ax.transAxes, clip_on=False, zorder=2
    ))
    ax.plot([MID_X, MID_X], [CARD_Y + 0.008, CARD_Y + CARD_H - 0.008],
            transform=ax.transAxes, color="#242d3c", lw=0.7, zorder=3)

    row_ys = [CARD_Y + CARD_H * 0.55, CARD_Y + CARD_H * 0.32, CARD_Y + CARD_H * 0.10]
    L_X = CARD_X + 0.018
    R_X = MID_X  + 0.018

    # ── HOLD 전용 하단 ──────────────────────────────────────
    if card_type == "HOLD":
        hold_score  = _s(_g(sig, "step_hold_score", default=0))
        action_text = _clean_user_text(str(_g(sig, "step_action_text", default="") or ""))
        main_rs     = _g(sig, "step_main_reasons", default=[]) or []
        direction   = str(_g(sig, "direction", default="") or "").upper()
        dir_col     = CANDLE_UP if direction == "LONG" else (CANDLE_DOWN if direction == "SHORT" else MUTED)

        TI_TITLE(L_X, CARD_Y + CARD_H - 0.016, "HOLD 정보", color=dir_col)
        TI(L_X, row_ys[0], f"HOLD 점수  {hold_score:.0f}점", size=6.8, color=MUTED)
        TI(L_X, row_ys[1], action_text[:28] if action_text else "-", size=6.6, color=TEXT)
        TI(L_X, row_ys[2], main_rs[0][:26] if main_rs else "-", size=6.4, color=DIM)

        TI_TITLE(R_X, CARD_Y + CARD_H - 0.016, "상태", color=TEXT)
        TI(R_X, row_ys[0], main_rs[1][:22] if len(main_rs) > 1 else "-", size=6.6, color=MUTED)
        TI(R_X, row_ys[1], main_rs[2][:22] if len(main_rs) > 2 else "-", size=6.6, color=MUTED)
        TI(R_X, row_ys[2], "포지션 유지 중", size=6.4, color=DIM)
        return

    # ── EXIT 전용 하단 ──────────────────────────────────────
    if card_type == "EXIT":
        exit_type   = _clean_user_text(str(_g(sig, "step_exit_type",   default="") or ""))
        exit_score  = _s(_g(sig, "step_exit_score", default=0))
        action_text = _clean_user_text(str(_g(sig, "step_action_text", default="") or ""))
        main_rs     = _g(sig, "step_main_reasons", default=[]) or []
        direction   = str(_g(sig, "direction", default="") or "").upper()
        dir_col     = CANDLE_DOWN if direction == "LONG" else (CANDLE_UP if direction == "SHORT" else MUTED)

        TI_TITLE(L_X, CARD_Y + CARD_H - 0.016, "EXIT 정보", color=dir_col)
        exit_label = f"{exit_type}" if exit_type and exit_type != "NONE" else "구조 EXIT"
        TI(L_X, row_ys[0], f"유형  {exit_label}", size=6.8, color=COND_FAIL)
        TI(L_X, row_ys[1], f"점수  {exit_score:.0f}점", size=6.8, color=MUTED)
        TI(L_X, row_ys[2], action_text[:26] if action_text else "-", size=6.4, color=DIM)

        TI_TITLE(R_X, CARD_Y + CARD_H - 0.016, "사유", color=TEXT)
        TI(R_X, row_ys[0], main_rs[0][:22] if main_rs else "-",            size=6.6, color=MUTED)
        TI(R_X, row_ys[1], main_rs[1][:22] if len(main_rs) > 1 else "-",   size=6.6, color=MUTED)
        TI(R_X, row_ys[2], "포지션 정리 검토",                              size=6.4, color=DIM)
        return

    # ── 기존 2분할 (WAIT / EARLY / PRE / REAL) ─────────────
    cand      = str(_g(sig, "candidate_direction", "direction", default="WAIT") or "WAIT").upper()
    dir_label = "LONG" if cand == "LONG" else ("SHORT" if cand == "SHORT" else "")
    dir_col   = CANDLE_UP if cand == "LONG" else (CANDLE_DOWN if cand == "SHORT" else MUTED)

    tp1  = _s(_g(sig, "tp1",              default=0))
    tp2  = _s(_g(sig, "tp2",              default=0))
    stop = _s(_g(sig, "stop", "stop_loss", default=0))

    vol_ratio = _s(_g(sig, "volume_ratio", default=0))
    vol_state = str(_g(sig, "volume_state", default="") or "")
    if not vol_state:
        if vol_ratio <= 0:    vol_state = "미확인"
        elif vol_ratio < 0.7: vol_state = f"저거래량 {vol_ratio:.1f}x"
        elif vol_ratio < 1.2: vol_state = f"보통 {vol_ratio:.1f}x"
        else:                 vol_state = f"활발 {vol_ratio:.1f}x"

    block_reason = str(_g(sig, "block_reason", default="") or "")
    warnings     = _g(sig, "warnings", default=[]) or []
    cond_state   = block_reason or (warnings[0] if warnings else "")
    if not cond_state:
        cond_state = "확인 중"

    market_st  = str(_g(sig, "market_state", default="") or "")
    next_check = market_st[:14] if market_st else "15분봉 마감"

    title_label = f"{dir_label} 시나리오" if dir_label else "시나리오"
    TI_TITLE(L_X, CARD_Y + CARD_H - 0.016, title_label, color=dir_col if dir_label else MUTED)

    tp1_str  = _fp(tp1)  if tp1  > 0 else "-"
    tp2_str  = _fp(tp2)  if tp2  > 0 else "-"
    stop_str = _fp(stop) if stop > 0 else "-"

    TI(L_X, row_ys[0], f"TP1  {tp1_str}",  size=6.8, color=COND_OK)
    TI(L_X, row_ys[1], f"TP2  {tp2_str}",  size=6.8, color=COND_OK)
    TI(L_X, row_ys[2], f"SL    {stop_str}", size=6.8, color=COND_FAIL)

    TI_TITLE(R_X, CARD_Y + CARD_H - 0.016, "상태", color=TEXT)
    TI(R_X, row_ys[0], f"거래량  {vol_state}",             size=6.6, color=TEXT)
    TI(R_X, row_ys[1], f"조건    {cond_state[:18] or '-'}", size=6.6, color=MUTED)
    TI(R_X, row_ys[2], f"다음 체크  {next_check}",          size=6.6, color=DIM)





def render_step_card(
    card_type:  str,
    sig:        dict,
    candles_1h: list,
    hits:       list = None,
    fails:      list = None,
    levels:     dict = None,
) -> bytes:

    # ── [필수] display_step 강제 변환
    # WATCH → WAIT 변환. HOLD/EXIT는 그대로 유지 (WAIT 강등 금지).
    card_type    = str(card_type or "WAIT").upper()
    if card_type == "WATCH":
        display_step = "WAIT"
    elif card_type in THEME:
        display_step = card_type          # HOLD/EXIT 포함 — 그대로 사용
    else:
        display_step = "WAIT"
    card_type = display_step   # 이후 card_type은 display_step과 동일

    theme   = THEME[card_type]
    primary = theme["primary"]
    symbol  = str(_g(sig, "symbol", default="BTCUSDT") or "BTCUSDT")
    price   = _s(_g(sig, "current_price", "price", default=0))
    direction = str(_g(sig, "direction", default="WAIT") or "WAIT").upper()

    if levels:
        sig = {**sig, **levels}

    # 캔들 데이터 보장 (fallback 포함)
    price_for_fallback = _s(_g(sig, "current_price", default=0))
    candles_1h = ensure_chart_data(candles_1h, price_for_fallback)

    conditions = _build_conditions(card_type, sig, hits, fails)
    gauge_pct  = _calc_gauge(card_type, sig, hits)

    print(f"[STEP CARD RENDER] {symbol} {card_type} chart={len(candles_1h)} conditions={len(conditions)}", flush=True)

    FW, FH = 5.6, 9.1
    DPI = 180

    fig = plt.figure(figsize=(FW, FH), dpi=DPI, facecolor=BG)

    ax_bg = fig.add_axes([0.02, 0.01, 0.96, 0.98])
    ax_bg.set_facecolor(BG_CARD)
    ax_bg.set_axis_off()

    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("none")
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    def T(x, y, s, size=9, color=WHITE, weight="normal", ha="left", va="center", alpha=1.0, zorder=5):
        """본문 텍스트 — fontweight normal 강제 (bold는 제목용 함수에서만 사용)"""
        ax.text(x, y, _clean_user_text(str(s)), transform=ax.transAxes,
                fontsize=size, color=color, fontweight=weight,
                ha=ha, va=va, alpha=alpha, fontproperties=FONT_PROP, zorder=zorder)

    def T_BOLD(x, y, s, size=9, color=WHITE, ha="left", va="center", zorder=5):
        """제목 전용 Bold 텍스트"""
        fp = FONT_PROP_BOLD if FONT_PROP_BOLD else FONT_PROP
        ax.text(x, y, _clean_user_text(str(s)), transform=ax.transAxes,
                fontsize=size, color=color, fontweight="bold",
                ha=ha, va=va, fontproperties=fp, zorder=zorder)

    def PANEL_RECT(x, y, w, h, face=PANEL, edge="none", lw=0, r=0.014):
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h,
            boxstyle=f"round,pad=0.002,rounding_size={r}",
            linewidth=lw, edgecolor=edge, facecolor=face,
            transform=ax.transAxes, clip_on=False, zorder=2
        ))

    def HLINE(y, x0=0.04, x1=0.96, color="#242d3c", lw=0.6):
        ax.plot([x0, x1], [y, y], transform=ax.transAxes,
                color=color, lw=lw, solid_capstyle="butt", zorder=3)

    # ── 아이콘 원
    IC_X, IC_Y, IC_R = 0.105, 0.903, 0.060
    ax.add_patch(plt.Circle(
        (IC_X, IC_Y), IC_R, color=PANEL2,
        ec="none", lw=0,
        transform=ax.transAxes, clip_on=False, zorder=3
    ))
    _draw_icon(ax, card_type, IC_X, IC_Y, primary, r=IC_R)

    # WAIT 카드 — candidate_direction 확인 (WATCH 문자 절대 출력 금지)
    cand = str(_g(sig, "candidate_direction", "direction", default="WAIT") or "WAIT").upper()
    block_reason_str = _clean_user_text(str(_g(sig, "block_reason", default="") or ""))
    warnings_list    = [_clean_user_text(w) for w in (_g(sig, "warnings", default=[]) or [])]

    # STEP 라벨 + 단계명 (display_step 사용 — WATCH 출력 없음)
    T_BOLD(0.215, 0.936, theme["step"], size=7.5, color=primary)
    T_BOLD(0.215, 0.910, theme["label"], size=21, color=primary)

    # REAL: LONG/SHORT 배지
    if card_type == "REAL" and direction in ("LONG", "SHORT"):
        dc = CANDLE_UP if direction == "LONG" else CANDLE_DOWN
        PANEL_RECT(0.52, 0.897, 0.140, 0.036, face=PANEL2, edge="none", lw=0, r=0.009)
        T_BOLD(0.590, 0.915, direction, size=9.5, color=dc, ha="center")

    # 서브 텍스트 — WATCH 없음, WAIT으로만 표시
    dot_y = 0.882
    ax.add_patch(plt.Circle(
        (0.220, dot_y), 0.008, color=primary,
        transform=ax.transAxes, clip_on=False, zorder=4
    ))
    if card_type == "HOLD":
        dir_color = CANDLE_UP if direction == "LONG" else (CANDLE_DOWN if direction == "SHORT" else MUTED)
        hold_score = _s(_g(sig, "step_hold_score", default=0))
        hold_txt   = f"{hold_score:.0f}점" if hold_score > 0 else ""
        T(0.238, dot_y, f"포지션 유지  |  {direction}  {hold_txt}".strip(), size=8.0, color=dir_color)
        action = _clean_user_text(str(_g(sig, "step_action_text", default="") or ""))
        if action:
            T(0.238, dot_y - 0.028, action[:32], size=7.0, color=MUTED)
    elif card_type == "EXIT":
        dir_color  = CANDLE_UP if direction == "LONG" else (CANDLE_DOWN if direction == "SHORT" else MUTED)
        exit_type  = _clean_user_text(str(_g(sig, "step_exit_type", default="") or ""))
        exit_score = _s(_g(sig, "step_exit_score", default=0))
        exit_label = f"{exit_type}  {exit_score:.0f}점" if exit_type and exit_type != "NONE" else ""
        T(0.238, dot_y, f"포지션 정리  |  {exit_label}".strip(), size=8.0, color=dir_color)
        action = _clean_user_text(str(_g(sig, "step_action_text", default="") or ""))
        if action:
            T(0.238, dot_y - 0.028, action[:32], size=7.0, color=MUTED)
    elif card_type == "EARLY":
        dir_color = CANDLE_UP if cand == "LONG" else CANDLE_DOWN
        T(0.238, dot_y,          f"초기 진입  |  방향: {cand}", size=8.0, color=dir_color)
        T(0.238, dot_y - 0.028,  "변곡 초입 / 저거래량 허용",  size=7.0, color=MUTED)
    elif card_type == "WAIT" and cand in ("LONG", "SHORT"):
        dir_color = CANDLE_UP if cand == "LONG" else CANDLE_DOWN
        T(0.238, dot_y, f"방향 후보: {cand}  |  진입 보류", size=8.0, color=dir_color)
        warn_text = block_reason_str or (warnings_list[0] if warnings_list else "")
        if warn_text:
            T(0.238, dot_y - 0.028, warn_text[:30], size=7.0, color=MUTED)
    elif card_type == "WAIT":
        T(0.238, dot_y, "방향 미확정  |  진입 대기", size=8.0, color=primary)
    else:
        T(0.238, dot_y, theme["sub"], size=8.5, color=primary)

    # 우측: 심볼 / 가격 / 시간 (심볼·가격은 Bold 허용)
    T_BOLD(0.955, 0.940, symbol,   size=10.5, color=WHITE,  ha="right")
    T_BOLD(0.955, 0.908, _fp(price), size=20, color=WHITE,  ha="right")
    T(     0.955, 0.882, _now_kst().strftime("%H:%M KST"), size=7.5, color=MUTED, ha="right")

    HLINE(0.865)

    # ── 조건 체크 패널
    C_TOP = 0.852
    C_BOT = 0.665
    C_H   = C_TOP - C_BOT
    PANEL_RECT(0.04, C_BOT, 0.560, C_H, face=PANEL, edge="none", lw=0)

    row_ys = [
        C_BOT + C_H * 0.800,
        C_BOT + C_H * 0.500,
        C_BOT + C_H * 0.190,
    ]
    STATUS_COL = {"ok": COND_OK, "fail": COND_FAIL, "partial": COND_PARTIAL}

    for (icon, text, status), ry in zip(conditions, row_ys):
        col = STATUS_COL.get(status, MUTED)
        ax.add_patch(plt.Circle(
            (0.100, ry), 0.020, color=col + "22",
            ec="none", lw=0,
            transform=ax.transAxes, clip_on=False, zorder=4
        ))
        # 조건 아이콘·텍스트 — fontweight normal (bold 금지)
        T(0.100, ry, icon, size=7.5, color=col, ha="center")
        T(0.138, ry, _clean_user_text(text), size=7.8, color=TEXT)

    # 게이지
    gauge_ax = fig.add_axes([0.590, 0.664, 0.360, 0.188])
    _draw_gauge(gauge_ax, gauge_pct)

    HLINE(0.660)

    # ── 변곡점 정보 섹션
    rev_stage    = str(_g(sig, "reversal_stage",     default="") or "")
    rev_score    = int(_s(_g(sig, "reversal_score",  default=0) or 0))
    rev_dir      = str(_g(sig, "reversal_direction", default="") or "")
    rev_reasons  = _g(sig, "reversal_reasons",  default=[]) or []
    rev_invalid  = str(_g(sig, "reversal_invalid", default="") or "")
    rev_promoted = bool(_g(sig, "reversal_promoted", default=False))

    REV_Y = 0.660
    if rev_stage and rev_stage != "NONE":
        rev_color    = GAUGE_FILL if rev_stage in ("PRE", "REAL") else MUTED
        promoted_tag = " ▲승격" if rev_promoted else ""
        # reversal_stage 내부값 — 화면 출력은 WATCH→WAIT 변환 적용
        rev_stage_disp = _clean_user_text(rev_stage)
        T(0.055, REV_Y,
          f"변곡 {rev_stage_disp}{promoted_tag}  {rev_dir}  {rev_score}점",
          size=7.5, color=rev_color)
        if rev_reasons:
            T(0.055, REV_Y - 0.025, " / ".join(rev_reasons[:3])[:38], size=6.8, color=MUTED)
        if rev_invalid:
            T(0.055, REV_Y - 0.048, f"무효화: {rev_invalid[:34]}", size=6.5, color=COND_FAIL, alpha=0.85)
        chart_top_offset = 0.655
    else:
        T(0.055, REV_Y, "변곡점 감지: 없음", size=7.0, color=DIM, alpha=0.70)
        chart_top_offset = 0.660

    # ── 차트 패널
    CH_TOP = chart_top_offset - 0.012
    CH_BOT = 0.125
    CH_H   = CH_TOP - CH_BOT
    PANEL_RECT(0.04, CH_BOT, 0.92, CH_H, face=PANEL, edge="none", lw=0)

    T(0.075, CH_TOP - 0.020, "1H 차트", size=8, color=TEXT)
    T(0.928, CH_TOP - 0.020, "EMA20",   size=7.5, color=primary, ha="right")

    chart_ax = fig.add_axes([0.060, CH_BOT + 0.040, 0.880, max(CH_H - 0.085, 0.10)])
    _draw_chart(chart_ax, candles_1h, sig, card_type, primary)

    # ── 하단 2분할 카드
    _draw_bottom_info(ax, card_type, sig, primary)

    # ── 푸터 고정 문구
    T(0.500, 0.008,
      "※ 자동진입 아님 / 15분봉 마감 기준 / 참고용 정보입니다.",
      size=5.8, color=DIM, ha="center", alpha=0.80)

    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=DPI,
                    facecolor=BG, pad_inches=0.02)
    except Exception as _se:
        print(f"[STEP CARD SAVE ERROR] {_se}", flush=True)
        plt.close(fig)
        return None
    plt.close(fig)
    buf.seek(0)
    data = buf.read()
    return data if data else None


# ─────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────
def _safe_render(card_type: str, sig: dict, candles_1h: list, **kwargs):
    """렌더 실패 시 None 반환"""
    try:
        return render_step_card(card_type, sig, candles_1h, **kwargs)
    except Exception as e:
        print(f"[{card_type} CARD ERROR] {e}", flush=True)
        return None

def render_wait_card(sig: dict, candles_1h: list) -> bytes | None:
    return _safe_render("WAIT", sig, candles_1h)

def render_early_card(sig: dict, candles_1h: list) -> bytes | None:
    return _safe_render("EARLY", sig, candles_1h)

def render_pre_card(sig: dict, candles_1h: list, hits: list = None) -> bytes | None:
    return _safe_render("PRE", sig, candles_1h, hits=hits)

def render_real_card(sig: dict, candles_1h: list, hits: list = None, levels: dict = None) -> bytes | None:
    return _safe_render("REAL", sig, candles_1h, hits=hits, levels=levels)

