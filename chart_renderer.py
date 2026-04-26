# chart_renderer.py
# 진입레이더 카드 이미지(PNG) 생성

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
# 색상
# ─────────────────────────────────────────────

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

_MACD_KO = {
    "BULLISH":  ("강세↑",  GREEN,      "상승 추세 강화"),
    "BEARISH":  ("약세↓",  RED,        "하락 추세 강화"),
    "POSITIVE": ("양전환", GREEN,      "상승 전환 시도"),
    "NEGATIVE": ("음전환", RED,        "하락 전환 시도"),
    "NEUTRAL":  ("중립",   TEXT_MUTED, "방향 미확정"),
}

_DIV_KO = {
    "BULLISH_DIV": "상승 다이버전스",
    "BEARISH_DIV": "하락 다이버전스",
}


def _safe(v, d=0.0):
    try: return float(v) if v is not None else d
    except: return d


def _get(sig, *keys, default=None):
    for k in keys:
        if k in sig and sig[k] is not None:
            return sig[k]
    return default


def _split_symbol(sym):
    sym = str(sym or "")
    if sym.endswith("USDT"): return sym[:-4], "USDT"
    return sym[:3], sym[3:] if len(sym) > 3 else ("", "")


# ─────────────────────────────────────────────
# 메인 렌더 함수
# ─────────────────────────────────────────────

def render_radar_card(sig: dict, candles_15m: list) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.patches import FancyBboxPatch, Rectangle

    # ── 데이터 추출 ──────────────────────────
    symbol      = _get(sig, "symbol", default="UNKNOWN")
    direction   = _get(sig, "direction", default="WAIT")
    long_score  = int(_get(sig, "long_score",  default=0))
    short_score = int(_get(sig, "short_score", default=0))
    gap         = abs(long_score - short_score)

    rsi_val  = _safe(_get(sig, "rsi",  default=50))
    cci_val  = _safe(_get(sig, "cci",  default=0))
    macd_raw = _get(sig, "macd_state", default="NEUTRAL")

    trend_15m  = _get(sig, "trend_15m", default="SIDEWAYS")
    trend_1h   = _get(sig, "trend_1h",  default="SIDEWAYS")

    support    = _safe(_get(sig, "support",    default=0))
    resistance = _safe(_get(sig, "resistance", default=0))
    mid        = (support + resistance) / 2 if support and resistance else 0

    is_range  = bool(_get(sig, "is_range",  default=False))
    range_pos = _get(sig, "range_pos", default=None)

    volume       = _safe(_get(sig, "volume",      default=0))
    avg_volume   = _safe(_get(sig, "avg_volume",  default=0))
    volume_ratio = _safe(_get(sig, "volume_ratio", default=0))
    if volume_ratio == 0 and avg_volume > 0:
        volume_ratio = volume / avg_volume

    div    = _get(sig, "divergence", default=None)
    ts     = _get(sig, "timestamp",  default=datetime.now(KST).strftime("%H:%M"))
    is_btc = "BTC" in str(symbol).upper()
    accent = LIME_GREEN if is_btc else PURPLE

    # ── 신호 강도 ────────────────────────────
    if gap < 15:   strength = "매우 약한 신호"
    elif gap < 25: strength = "약한 신호"
    elif gap < 40: strength = "보통 신호"
    else:          strength = "강한 신호"

    # ── 배지 ─────────────────────────────────
    if direction == "SHORT":   badge_lbl, badge_c = "SHORT 지지", RED
    elif direction == "LONG":  badge_lbl, badge_c = "LONG 지지",  GREEN
    else:                      badge_lbl, badge_c = "방향 대기",  TEXT_MUTED

    # ── 캔들 ─────────────────────────────────
    candles   = (candles_15m or [])[-30:]
    n         = len(candles)
    opens     = [_safe(c.get("open"))   for c in candles]
    highs     = [_safe(c.get("high"))   for c in candles]
    lows      = [_safe(c.get("low"))    for c in candles]
    closes    = [_safe(c.get("close"))  for c in candles]
    now_price = closes[-1] if closes else 0

    def _ema(vals, p=20):
        if not vals: return []
        k = 2/(p+1); out=[vals[0]]
        for v in vals[1:]: out.append(v*k+out[-1]*(1-k))
        return out

    ema20 = _ema(closes)

    # ── RSI 해석 ─────────────────────────────
    if rsi_val < 30:   rsi_lbl, rsi_c = "강한 과매도 · 반등 신호", GREEN
    elif rsi_val < 45: rsi_lbl, rsi_c = "과매도 구간",              GREEN
    elif rsi_val < 55: rsi_lbl, rsi_c = "중립",                     TEXT_MUTED
    elif rsi_val < 70: rsi_lbl, rsi_c = "과매수 구간",              RED
    else:              rsi_lbl, rsi_c = "강한 과매수 · 조정 신호",  RED

    rsi_sub = {
        GREEN: "30↓ 강반등 · 50↑ 되어야 상승 확인",
        RED:   "70↑ 조정 위험 · 50↓ 되어야 하락 확인",
    }.get(rsi_c, "50 기준 방향 탐색 중")

    # ── CCI 해석 ─────────────────────────────
    if cci_val < -200:   cci_lbl, cci_c = "극단 과매도",    GREEN
    elif cci_val < -100: cci_lbl, cci_c = "강한 하락 압력", RED
    elif cci_val < 0:    cci_lbl, cci_c = "약한 하락",      TEXT_MUTED
    elif cci_val < 100:  cci_lbl, cci_c = "약한 상승",      TEXT_MUTED
    else:                cci_lbl, cci_c = "강한 상승 압력", GREEN

    cci_sub = "-100↓ 과열 · -200↓면 반등 유력" if cci_val < 0 else "100↑ 과열 · 200↑면 조정 유력"

    # ── MACD 해석 ────────────────────────────
    macd_str, macd_c, macd_sub = _MACD_KO.get(macd_raw, ("중립", TEXT_MUTED, "방향 미확정"))

    # ── 시간봉 종합 ──────────────────────────
    def _tf(t):
        if t=="UP":   return "상승", GREEN,     "매수 우세"
        if t=="DOWN": return "하락", RED,       "매도 우세"
        return               "횡보", TEXT_MUTED,"방향 미확정"

    t15_txt, t15_c, t15_sub = _tf(trend_15m)
    t1h_txt, t1h_c, t1h_sub = _tf(trend_1h)

    if trend_15m=="UP"   and trend_1h=="UP":
        tf_sum, tf_sum_c, tf_det = "단기·중기 상승 일치", GREEN, "추세 강함 · 눌림 후 롱 검토"
    elif trend_15m=="DOWN" and trend_1h=="DOWN":
        tf_sum, tf_sum_c, tf_det = "단기·중기 하락 일치", RED,   "하락 지속 · 반등 실패 후 숏 검토"
    elif trend_15m!=trend_1h and "SIDEWAYS" not in [trend_15m, trend_1h]:
        tf_sum, tf_sum_c, tf_det = "단기·중기 충돌",      AMBER, "1H 방향 확정 전 추격 위험"
    else:
        tf_sum, tf_sum_c, tf_det = "방향 미확정 · 대기",  TEXT_MUTED, "박스 이탈 방향 확인 후 진입"

    # ── 지표 충돌 ────────────────────────────
    conflict = (rsi_val < 45 and macd_raw in ("BULLISH","POSITIVE") and cci_val < -100)

    # ── 박스 위치 ────────────────────────────
    if not is_range:
        pos_c, pos_lbl = TEXT_MUTED, "추세 구간 · 박스권 아님 · 추세 방향 따라가기"
    elif range_pos=="MIDDLE":
        pos_c, pos_lbl = AMBER, f"박스 중앙 · {support:.0f}~{resistance:.0f} · 양방향 노이즈 · 진입 금지"
    elif range_pos=="TOP":
        pos_c, pos_lbl = RED,   "박스 상단 · 저항 근접 · 돌파 실패 시 숏 후보"
    else:
        pos_c, pos_lbl = GREEN, "박스 하단 · 지지 근접 · 이탈 실패 시 롱 후보"

    # ── 거래량 ───────────────────────────────
    vol_fill  = min(volume_ratio / 1.2, 1.0)
    vol_ok    = volume_ratio >= 1.2
    vol_bar_c = GREEN if vol_ok else AMBER
    vol_pct   = max(0, (1.2 - volume_ratio) / 1.2 * 100)
    vol_txt   = "조건 충족" if vol_ok else f"{vol_pct:.0f}% 부족"
    vol_txt_c = GREEN if vol_ok else RED

    # ══════════════════════════════════════════
    # Figure: 9개 행
    # [0] 헤더
    # [1] 지지방향 바
    # [2] 캔들차트
    # [3] 현재 위치
    # [4] 진입 조건 (숏/롱 한줄 + 거래량 바)
    # [5] 시간봉 구조
    # [6] 지표 분석
    # ══════════════════════════════════════════
    fig = plt.figure(figsize=(6, 15.5), facecolor=BG_DARK)
    fig.patch.set_facecolor(BG_DARK)

    gs = fig.add_gridspec(7, 1,
        height_ratios=[0.5, 0.5, 2.8, 0.25, 1.1, 1.1, 1.7],
        hspace=0.06,
        left=0.03, right=0.97, top=0.97, bottom=0.02)

    def new_ax(row, bg=BG_DARK):
        a = fig.add_subplot(gs[row])
        a.set_facecolor(bg); a.axis("off")
        a.set_xlim(0,1); a.set_ylim(0,1)
        return a

    def sep(a, y=0.05):
        a.axhline(y, color=BG_DARK2, linewidth=0.8)

    def card(a, x, y, w, h, bg=BG_CELL, ec=BG_DARK2):
        a.add_patch(FancyBboxPatch((x,y),w,h,
            boxstyle="round,pad=0.01",
            facecolor=bg, edgecolor=ec, linewidth=0.5,
            transform=a.transAxes))

    def rect(a, x, y, w, h, color):
        a.add_patch(Rectangle((x,y),w,h, facecolor=color, transform=a.transAxes))

    # ── 행0: 헤더 ────────────────────────────
    ax = new_ax(0)
    base, quote = _split_symbol(symbol)
    ax.text(0.02, 0.55, base,  color=accent,    fontsize=20, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.22, 0.55, quote, color=TEXT_WHITE, fontsize=14, va="center",      transform=ax.transAxes)
    ax.text(0.72, 0.55, "진입레이더", color="#ffffff", fontsize=10, va="center", ha="center",
            transform=ax.transAxes,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#7c3aed", edgecolor="none"))
    ax.text(0.97, 0.55, ts, color=TEXT_MUTED, fontsize=10, va="center", ha="right", transform=ax.transAxes)
    sep(ax)

    # ── 행1: 지지방향 바 ─────────────────────
    ax = new_ax(1)
    # 배지 + 강도 + 감시구간
    ax.text(0.02, 0.90, badge_lbl, color="white", fontsize=9, fontweight="bold",
            va="top", transform=ax.transAxes,
            bbox=dict(boxstyle="round,pad=0.28", facecolor=badge_c, edgecolor="none"))
    ax.text(0.28, 0.90, f"차이 {gap}%p · {strength}",
            color=TEXT_MUTED, fontsize=8, va="top", transform=ax.transAxes)
    ax.text(0.97, 0.90, "감시구간",
            color=TEXT_MUTED, fontsize=8, va="top", ha="right", transform=ax.transAxes)
    # 양방향 바
    rect(ax, 0.0, 0.38, 1.0, 0.26, BG_DARK2)
    rect(ax, 0.0, 0.38, long_score/100,  0.26, GREEN)
    rect(ax, 1.0-short_score/100, 0.38, short_score/100, 0.26, RED)
    # 레이블
    ax.text(0.02, 0.28, f"LONG {long_score}%",  color=GREEN, fontsize=9, fontweight="bold", va="top", transform=ax.transAxes)
    ax.text(0.97, 0.28, f"SHORT {short_score}%", color=RED,  fontsize=9, fontweight="bold", va="top", ha="right", transform=ax.transAxes)

    # ── 행2: 캔들차트 ────────────────────────
    ax_chart = fig.add_subplot(gs[2])
    ax_chart.set_facecolor(BG_CELL)
    for sp in ax_chart.spines.values(): sp.set_edgecolor(BG_DARK2)

    if n > 0 and any(closes):
        xs = range(n)
        for i,(o,h,l,c) in enumerate(zip(opens,highs,lows,closes)):
            col = GREEN if c>=o else RED
            ax_chart.plot([i,i],[l,h], color=col, linewidth=0.8, zorder=2)
            bh = abs(c-o) or max((h-l)*0.01, 0.0001)
            ax_chart.add_patch(Rectangle((i-0.3,min(o,c)),0.6,bh, color=col, zorder=3))
        if len(ema20)==n:
            ax_chart.plot(list(xs), ema20, color=AMBER, linewidth=1.3, zorder=4)
        hi=max(highs); lo=min(lows); pad=(hi-lo)*0.15 if hi!=lo else 1
        if is_range and resistance>0:
            ax_chart.axhline(resistance, color=RED,   lw=0.8, ls="--", alpha=0.75, zorder=5)
            ax_chart.text(n-0.5, resistance, f"박스상단 {resistance:.0f}", color=RED,   fontsize=7, va="bottom", ha="right")
        if is_range and mid>0:
            ax_chart.axhline(mid,        color=AMBER, lw=0.6, ls="--", alpha=0.4,  zorder=5)
            ax_chart.text(n-0.5, mid,    f"중앙 {mid:.0f}",             color=AMBER, fontsize=7, va="bottom", ha="right")
        if is_range and support>0:
            ax_chart.axhline(support,    color=GREEN, lw=0.8, ls="--", alpha=0.75, zorder=5)
            ax_chart.text(n-0.5, support, f"박스하단 {support:.0f}",   color=GREEN, fontsize=7, va="top",    ha="right")
        if now_price>0:
            ax_chart.axhline(now_price, color=TEXT_MUTED, lw=0.5, ls="--", alpha=0.6, zorder=5)
            ax_chart.text(n-0.5, now_price, f"{now_price:.1f}", color=TEXT_WHITE, fontsize=7, va="bottom", ha="right")
        ax_chart.set_xlim(-0.5, n+0.5)
        ax_chart.set_ylim(lo-pad, hi+pad)

    ax_chart.text(0.02, 0.97, "15M 캔들차트", color=TEXT_MUTED, fontsize=8, va="top", transform=ax_chart.transAxes)
    ax_chart.text(0.97, 0.97, "─ EMA20",      color=AMBER,      fontsize=8, va="top", ha="right", transform=ax_chart.transAxes)
    ax_chart.tick_params(colors=TEXT_MUTED, labelsize=7)
    ax_chart.yaxis.tick_right()

    # ── 행3: 현재 위치 한줄 ──────────────────
    ax = new_ax(3)
    ax.plot(0.02, 0.5, "o", color=pos_c, markersize=6, transform=ax.transAxes)
    ax.text(0.06, 0.5, pos_lbl, color=TEXT_WHITE, fontsize=8.5, va="center", transform=ax.transAxes)

    # ── 행4: 진입 조건 + 거래량 바 ──────────
    ax = new_ax(4)
    # 숏 한줄
    card(ax, 0.0, 0.72, 0.99, 0.25, bg="#1a0d0d", ec="#7f1d1d")
    ax.text(0.02, 0.845, "숏",                      color=RED,       fontsize=11, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.10, 0.845, f"{support:.0f} 이탈",     color=TEXT_WHITE,fontsize=10, va="center",       transform=ax.transAxes)
    ax.text(0.38, 0.845, "+",                       color=TEXT_MUTED,fontsize=10, va="center",       transform=ax.transAxes)
    ax.text(0.43, 0.845, "거래량 1.2배+",           color=TEXT_WHITE,fontsize=10, va="center",       transform=ax.transAxes)
    ax.text(0.97, 0.845, f"현재 {volume_ratio:.1f}배", color=AMBER,  fontsize=10, va="center", ha="right", transform=ax.transAxes)
    # 롱 한줄
    card(ax, 0.0, 0.45, 0.99, 0.25, bg="#0d1a0d", ec="#1a4d1a")
    ax.text(0.02, 0.575, "롱",                      color=GREEN,     fontsize=11, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.10, 0.575, f"{resistance:.0f} 돌파",  color=TEXT_WHITE,fontsize=10, va="center",       transform=ax.transAxes)
    ax.text(0.38, 0.575, "+",                       color=TEXT_MUTED,fontsize=10, va="center",       transform=ax.transAxes)
    ax.text(0.43, 0.575, "거래량 1.2배+",           color=TEXT_WHITE,fontsize=10, va="center",       transform=ax.transAxes)
    ax.text(0.97, 0.575, f"현재 {volume_ratio:.1f}배", color=AMBER,  fontsize=10, va="center", ha="right", transform=ax.transAxes)
    # 거래량 바 섹션
    card(ax, 0.0, 0.0, 0.99, 0.42, bg=BG_CELL)
    ax.text(0.03, 0.40, "거래량 진행도 (숏·롱 공통)", color=TEXT_MUTED, fontsize=8, va="top", transform=ax.transAxes)
    ax.text(0.97, 0.40, vol_txt, color=vol_txt_c, fontsize=8, va="top", ha="right", transform=ax.transAxes)
    rect(ax, 0.03, 0.18, 0.94, 0.12, BG_DARK2)
    rect(ax, 0.03, 0.18, 0.94*vol_fill, 0.12, vol_bar_c)
    ax.text(0.03, 0.15, "0배",       color=TEXT_MUTED, fontsize=8, va="top", transform=ax.transAxes)
    ax.text(0.97, 0.15, "기준 1.2배", color=GREEN,     fontsize=8, va="top", ha="right", transform=ax.transAxes)
    ax.text(0.03, 0.03,
            "거래량 없는 이탈/돌파 = 가짜 신호 가능성 높음 · 1.2배 미만이면 관망",
            color=TEXT_MUTED, fontsize=7.5, va="bottom", transform=ax.transAxes)

    # ── 행5: 시간봉 구조 ─────────────────────
    ax = new_ax(5)
    ax.text(0.02, 0.97, "시간봉 구조", color=TEXT_MUTED, fontsize=9, fontweight="bold", va="top", transform=ax.transAxes)
    # 15M 셀
    card(ax, 0.0, 0.42, 0.475, 0.50)
    ax.text(0.03, 0.88, "15M · 단기",  color=TEXT_MUTED, fontsize=8,  va="top", transform=ax.transAxes)
    ax.text(0.03, 0.72, t15_txt,       color=t15_c,      fontsize=14, fontweight="bold", va="top", transform=ax.transAxes)
    ax.text(0.03, 0.55, t15_sub,       color=TEXT_MUTED, fontsize=8,  va="top", transform=ax.transAxes)
    # 1H 셀
    card(ax, 0.525, 0.42, 0.475, 0.50)
    ax.text(0.545, 0.88, "1H · 중기", color=TEXT_MUTED, fontsize=8,  va="top", transform=ax.transAxes)
    ax.text(0.545, 0.72, t1h_txt,     color=t1h_c,      fontsize=14, fontweight="bold", va="top", transform=ax.transAxes)
    ax.text(0.545, 0.55, t1h_sub,     color=TEXT_MUTED, fontsize=8,  va="top", transform=ax.transAxes)
    # 종합 (황색 왼쪽 테두리)
    rect(ax, 0.0, 0.0, 0.99, 0.38, "#161b22")
    rect(ax, 0.0, 0.0, 0.004, 0.38, tf_sum_c)
    ax.text(0.03, 0.35, tf_sum,  color=tf_sum_c,  fontsize=10, fontweight="bold", va="top", transform=ax.transAxes)
    ax.text(0.03, 0.17, tf_det,  color=TEXT_MUTED, fontsize=8,  va="top", transform=ax.transAxes)

    # ── 행6: 지표 분석 ───────────────────────
    ax = new_ax(6)
    ax.text(0.02, 0.97, "지표 분석", color=TEXT_MUTED, fontsize=9, fontweight="bold", va="top", transform=ax.transAxes)

    indicators = [
        ("RSI",  f"{rsi_val:.1f}", rsi_lbl,  rsi_c,   rsi_sub),
        ("CCI",  f"{cci_val:.0f}", cci_lbl,  cci_c,   cci_sub),
        ("MACD", macd_str,         macd_lbl  if False else _MACD_KO.get(macd_raw,("","",""))[0],
                                              macd_c,  macd_sub),
    ]
    # 충돌 있으면 지표 3개 + 경고박스, 없으면 지표 3개만
    row_h = 0.23 if conflict else 0.26
    start_y = 0.88

    for idx, (lbl, val, meaning, col, sub) in enumerate(indicators):
        y_top = start_y - idx * row_h
        card(ax, 0.0, y_top - 0.20, 0.99, 0.20)
        ax.text(0.03, y_top-0.02, lbl,     color=TEXT_MUTED, fontsize=9,  va="top", transform=ax.transAxes)
        ax.text(0.16, y_top-0.02, val,     color=col,        fontsize=12, fontweight="bold", va="top", transform=ax.transAxes)
        ax.text(0.38, y_top-0.02, meaning, color=col,        fontsize=9,  fontweight="bold", va="top", transform=ax.transAxes)
        ax.text(0.38, y_top-0.12, sub,     color=TEXT_MUTED, fontsize=7.5,va="top", transform=ax.transAxes)

    # 지표 충돌 경고
    if conflict:
        card(ax, 0.0, 0.0, 0.99, 0.195, bg="#1a1200", ec=AMBER)
        ax.text(0.03, 0.175, "지표 충돌 — 방향 판단 보류",
                color=AMBER, fontsize=9, fontweight="bold", va="top", transform=ax.transAxes)
        ax.text(0.03, 0.105, "RSI 과매도 → 반등 가능 / CCI·MACD → 하락 압력 지속",
                color=TEXT_MUTED, fontsize=8, va="top", transform=ax.transAxes)
        ax.text(0.03, 0.045, "→ 지표 엇갈림 = 손절 확률 상승 · 이탈 후 일치 확인 필수",
                color=AMBER, fontsize=8, va="top", transform=ax.transAxes)

    # 다이버전스
    if div:
        ax.text(0.03, 0.01, _DIV_KO.get(div, div),
                color=GREEN if div=="BULLISH_DIV" else RED,
                fontsize=8, va="bottom", transform=ax.transAxes)

    # ── PNG 반환 ─────────────────────────────
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG_DARK)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────
# 텔레그램 전송 헬퍼
# ─────────────────────────────────────────────

async def send_radar_album(bot, chat_id: str, signals: list, candles_map: dict):
    try:
        from telegram import InputMediaPhoto
    except ImportError:
        raise RuntimeError("pip install python-telegram-bot 필요")
    media = []
    for sig in signals:
        symbol  = sig.get("symbol")
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


# ─────────────────────────────────────────────
# 1H 전광판 카드 렌더링
# ─────────────────────────────────────────────

def render_dashboard_card(sig: dict, candles_1h: list) -> bytes:
    """
    1H 전광판 카드 이미지 생성
    sig: core_analyzer.analyze() 결과
    candles_1h: 1시간봉 캔들 리스트
    반환: PNG bytes
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle

    # ── 데이터 추출 ──────────────────────────
    symbol      = _get(sig, "symbol", default="UNKNOWN")
    direction   = _get(sig, "direction", default="WAIT")
    long_score  = int(_get(sig, "long_score",  default=0))
    short_score = int(_get(sig, "short_score", default=0))
    confidence  = int(_get(sig, "confidence",  default=0))
    score_gap   = abs(long_score - short_score)

    rsi_val  = _safe(_get(sig, "rsi",  default=50))
    cci_val  = _safe(_get(sig, "cci",  default=0))
    macd_raw = _get(sig, "macd_state", default="NEUTRAL")

    trend_15m = _get(sig, "trend_15m", default="SIDEWAYS")
    trend_30m = _get(sig, "trend_30m", default="SIDEWAYS")
    trend_1h  = _get(sig, "trend_1h",  default="SIDEWAYS")
    trend_4h  = _get(sig, "trend_4h",  default="SIDEWAYS")

    support    = _safe(_get(sig, "support",    default=0))
    resistance = _safe(_get(sig, "resistance", default=0))
    mid        = (support + resistance) / 2 if support and resistance else 0

    is_range  = bool(_get(sig, "is_range",  default=False))
    range_pos = _get(sig, "range_pos", default=None)

    structure = _get(sig, "structure", default="UNKNOWN")
    div       = _get(sig, "divergence", default=None)
    bb_signal = _get(sig, "bb_signal",  default="NEUTRAL")
    bb_squeeze = bool(_get(sig, "bb_squeeze", default=False))

    ts     = _get(sig, "timestamp", default=datetime.now(KST).strftime("%H:%M"))
    is_btc = "BTC" in str(symbol).upper()
    accent = LIME_GREEN if is_btc else PURPLE

    # ── 판정 상태 ────────────────────────────
    if direction == "LONG":
        state_lbl, state_c, state_bg = "LONG 우세", GREEN,     "#1a2e1a"
    elif direction == "SHORT":
        state_lbl, state_c, state_bg = "SHORT 우세", RED,      "#1a0d0d"
    else:
        state_lbl, state_c, state_bg = "WAIT",       AMBER,    "#1a1200"

    # ── 신호강도 강도 텍스트 ─────────────────
    if score_gap < 15:   strength = "매우 약한 신호"
    elif score_gap < 25: strength = "약한 신호"
    elif score_gap < 40: strength = "보통 신호"
    else:                strength = "강한 신호"

    # ── 타임프레임 색상 ──────────────────────
    def _tf_color(t):
        if t == "UP":       return GREEN
        if t == "DOWN":     return RED
        return "#444444"

    def _tf_txt(t):
        if t == "UP":       return "상승"
        if t == "DOWN":     return "하락"
        return "횡보"

    # ── 타임프레임 종합 ──────────────────────
    trends = [trend_15m, trend_30m, trend_1h, trend_4h]
    ups    = trends.count("UP")
    downs  = trends.count("DOWN")
    if ups >= 3:
        tf_sum, tf_sum_c = "상승 정렬 우세", GREEN
    elif downs >= 3:
        tf_sum, tf_sum_c = "하락 정렬 우세", RED
    elif ups > downs:
        tf_sum, tf_sum_c = "상승 약우세 · 충돌 존재", AMBER
    elif downs > ups:
        tf_sum, tf_sum_c = "하락 약우세 · 충돌 존재", AMBER
    else:
        tf_sum, tf_sum_c = "방향 충돌 · 대기", AMBER

    # ── 가격 구조 ────────────────────────────
    struct_map = {
        "HH/HL": ("HH/HL", GREEN,     "상승 파동 진행 중"),
        "LH/LL": ("LH/LL", RED,       "하락 파동 진행 중"),
        "HH/LL": ("HH/LL", AMBER,     "변동성 확대 구간"),
        "LH/HL": ("LH/HL", AMBER,     "방향 압축 구간"),
    }
    struct_lbl, struct_c, struct_desc = struct_map.get(
        structure, ("SIDEWAYS", TEXT_MUTED, "방향 미확정"))

    # ── 다이버전스 ───────────────────────────
    if div == "BULLISH_DIV":
        div_dot_c, div_lbl, div_desc = GREEN, "상승 감지", "가격↓ RSI↑ — 반등 가능"
    elif div == "BEARISH_DIV":
        div_dot_c, div_lbl, div_desc = RED,   "하락 감지", "가격↑ RSI↓ — 조정 가능"
    else:
        div_dot_c, div_lbl, div_desc = "#444444", "없음", "반전 신호 미감지"

    # 파동 종합 해석
    if div == "BULLISH_DIV" and structure in ("HH/HL", "LH/HL"):
        wave_sum, wave_c = "상승 파동 + 상승 다이버전스 동시 감지 → 반등 주목", GREEN
    elif div == "BEARISH_DIV" and structure in ("LH/LL", "HH/LL"):
        wave_sum, wave_c = "하락 파동 + 하락 다이버전스 동시 감지 → 조정 주목", RED
    elif div and div != "BEARISH_DIV":
        wave_sum, wave_c = f"{struct_desc} · 다이버전스 감지 주목", AMBER
    else:
        wave_sum, wave_c = struct_desc, struct_c

    # ── RSI 해석 ─────────────────────────────
    if rsi_val < 30:   rsi_lbl, rsi_c = "강한과매도", GREEN
    elif rsi_val < 45: rsi_lbl, rsi_c = "과매도",    GREEN
    elif rsi_val < 55: rsi_lbl, rsi_c = "중립",      TEXT_MUTED
    elif rsi_val < 70: rsi_lbl, rsi_c = "과매수",    RED
    else:              rsi_lbl, rsi_c = "강한과매수", RED

    # ── CCI 해석 ─────────────────────────────
    if cci_val < -200:   cci_lbl, cci_c = "극단과매도", GREEN
    elif cci_val < -100: cci_lbl, cci_c = "강한하락",   RED
    elif cci_val < 0:    cci_lbl, cci_c = "약한하락",   TEXT_MUTED
    elif cci_val < 100:  cci_lbl, cci_c = "약한상승",   TEXT_MUTED
    else:                cci_lbl, cci_c = "강한상승",   GREEN

    # ── MACD 해석 ────────────────────────────
    _mmap = {
        "BULLISH":  ("강세↑",  GREEN),
        "BEARISH":  ("약세↓",  RED),
        "POSITIVE": ("양전환", GREEN),
        "NEGATIVE": ("음전환", RED),
        "NEUTRAL":  ("중립",   TEXT_MUTED),
    }
    macd_str, macd_c = _mmap.get(macd_raw, ("중립", TEXT_MUTED))

    # ── 캔들 데이터 ──────────────────────────
    candles   = (candles_1h or [])[-30:]
    n         = len(candles)
    opens     = [_safe(c.get("open"))  for c in candles]
    highs     = [_safe(c.get("high"))  for c in candles]
    lows      = [_safe(c.get("low"))   for c in candles]
    closes    = [_safe(c.get("close")) for c in candles]
    now_price = closes[-1] if closes else 0

    def _ema(vals, p=20):
        if not vals: return []
        k = 2/(p+1); out=[vals[0]]
        for v in vals[1:]: out.append(v*k+out[-1]*(1-k))
        return out

    ema20 = _ema(closes)

    # ── 박스 위치 ────────────────────────────
    if not is_range:
        pos_c, pos_lbl, pos_desc = TEXT_MUTED, "추세 구간", "박스권 아님 · 추세 방향 따라가기"
    elif range_pos == "MIDDLE":
        pos_c, pos_lbl, pos_desc = AMBER, "박스 중앙", f"{support:.0f}~{resistance:.0f} · 양방향 노이즈"
    elif range_pos == "TOP":
        pos_c, pos_lbl, pos_desc = RED,   "박스 상단", "저항 근접 · 돌파 실패 시 숏 후보"
    else:
        pos_c, pos_lbl, pos_desc = GREEN, "박스 하단", "지지 근접 · 이탈 실패 시 롱 후보"

    # ── 결론 ─────────────────────────────────
    if direction == "LONG":
        concl_c   = GREEN
        concl_ttl = "결론 — LONG 우세"
        concl_txt = f"{resistance:.0f} 돌파 + 거래량 확인 시 롱 주목"
    elif direction == "SHORT":
        concl_c   = RED
        concl_ttl = "결론 — SHORT 우세"
        concl_txt = f"{support:.0f} 이탈 + 거래량 확인 시 숏 주목"
    else:
        concl_c   = AMBER
        concl_ttl = "결론 — 관망"
        concl_txt = f"{support:.0f} 이탈 또는 {resistance:.0f} 돌파 확인 전 대기"

    # ══════════════════════════════════════════
    # Figure: 7개 행
    # [0] 헤더
    # [1] 판정 + 신호강도 바
    # [2] 1H 캔들차트
    # [3] 타임프레임 B안
    # [4] 파동 구조 + 다이버전스
    # [5] 지표 그리드
    # [6] 결론
    # ══════════════════════════════════════════
    fig = plt.figure(figsize=(6, 14.0), facecolor=BG_DARK)
    fig.patch.set_facecolor(BG_DARK)

    gs = fig.add_gridspec(7, 1,
        height_ratios=[0.5, 0.6, 2.8, 0.7, 0.9, 0.7, 0.5],
        hspace=0.07,
        left=0.03, right=0.97, top=0.97, bottom=0.02)

    def new_ax(row):
        a = fig.add_subplot(gs[row])
        a.set_facecolor(BG_DARK); a.axis("off")
        a.set_xlim(0,1); a.set_ylim(0,1)
        return a

    def card(a, x, y, w, h, bg=BG_CARD, ec=BG_DARK2):
        a.add_patch(FancyBboxPatch((x,y),w,h,
            boxstyle="round,pad=0.01",
            facecolor=bg, edgecolor=ec, linewidth=0.5,
            transform=a.transAxes))

    def rect(a, x, y, w, h, color):
        a.add_patch(Rectangle((x,y),w,h, facecolor=color, transform=a.transAxes))

    # ── 행0: 헤더 ────────────────────────────
    ax = new_ax(0)
    base, quote = _split_symbol(symbol)
    ax.text(0.02, 0.55, base,  color=accent,    fontsize=20, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.22, 0.55, quote, color=TEXT_WHITE, fontsize=14, va="center",      transform=ax.transAxes)
    ax.text(0.72, 0.55, "1H 전광판", color="#ffffff", fontsize=10, va="center", ha="center",
            transform=ax.transAxes,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a4d1a", edgecolor="none"))
    ax.text(0.97, 0.55, ts, color=TEXT_MUTED, fontsize=10, va="center", ha="right", transform=ax.transAxes)
    if now_price:
        ax.text(0.97, 0.15, f"{now_price:,.2f}", color=TEXT_WHITE, fontsize=11,
                fontweight="bold", va="bottom", ha="right", transform=ax.transAxes)
    ax.axhline(0.05, color=BG_DARK2, linewidth=0.8)

    # ── 행1: 판정 + 신호강도 바 ─────────────
    ax = new_ax(1)
    # 판정 배지
    ax.text(0.02, 0.92, state_lbl, color="white", fontsize=9, fontweight="bold",
            va="top", transform=ax.transAxes,
            bbox=dict(boxstyle="round,pad=0.28", facecolor=state_c, edgecolor="none"))
    ax.text(0.28, 0.92, strength, color=TEXT_MUTED, fontsize=8, va="top", transform=ax.transAxes)
    # 신호강도 레이블
    ax.text(0.02, 0.52, f"LONG {long_score}%",  color=GREEN, fontsize=9, fontweight="bold", va="top", transform=ax.transAxes)
    ax.text(0.50, 0.52, "신호강도",              color=TEXT_MUTED, fontsize=8, va="top", ha="center", transform=ax.transAxes)
    ax.text(0.97, 0.52, f"SHORT {short_score}%", color=RED,  fontsize=9, fontweight="bold", va="top", ha="right", transform=ax.transAxes)
    # 양방향 바
    rect(ax, 0.0, 0.18, 1.0, 0.26, BG_DARK2)
    rect(ax, 0.0, 0.18, long_score/100,  0.26, GREEN)
    rect(ax, 1.0-short_score/100, 0.18, short_score/100, 0.26, RED)

    # ── 행2: 1H 캔들차트 ────────────────────
    ax_chart = fig.add_subplot(gs[2])
    ax_chart.set_facecolor(BG_CELL)
    for sp in ax_chart.spines.values(): sp.set_edgecolor(BG_DARK2)

    if n > 0 and any(closes):
        xs = range(n)
        for i,(o,h,l,c) in enumerate(zip(opens,highs,lows,closes)):
            col = GREEN if c>=o else RED
            ax_chart.plot([i,i],[l,h], color=col, linewidth=0.8, zorder=2)
            bh = abs(c-o) or max((h-l)*0.01, 0.0001)
            ax_chart.add_patch(Rectangle((i-0.3,min(o,c)),0.6,bh, color=col, zorder=3))
        if len(ema20)==n:
            ax_chart.plot(list(xs), ema20, color=AMBER, linewidth=1.3, zorder=4)
        hi=max(highs); lo=min(lows); pad=(hi-lo)*0.15 if hi!=lo else 1
        if is_range and resistance>0:
            ax_chart.axhline(resistance, color=RED,   lw=0.8, ls="--", alpha=0.75, zorder=5)
            ax_chart.text(n-0.5, resistance, f"박스상단 {resistance:.0f}", color=RED,   fontsize=7, va="bottom", ha="right")
        if is_range and mid>0:
            ax_chart.axhline(mid,        color=AMBER, lw=0.6, ls="--", alpha=0.4,  zorder=5)
            ax_chart.text(n-0.5, mid,    f"중앙 {mid:.0f}",             color=AMBER, fontsize=7, va="bottom", ha="right")
        if is_range and support>0:
            ax_chart.axhline(support,    color=GREEN, lw=0.8, ls="--", alpha=0.75, zorder=5)
            ax_chart.text(n-0.5, support, f"박스하단 {support:.0f}",   color=GREEN, fontsize=7, va="top",    ha="right")
        if now_price>0:
            ax_chart.axhline(now_price, color=TEXT_MUTED, lw=0.5, ls="--", alpha=0.6, zorder=5)
            ax_chart.text(n-0.5, now_price, f"{now_price:.1f}", color=TEXT_WHITE, fontsize=7, va="bottom", ha="right")
        ax_chart.set_xlim(-0.5, n+0.5)
        ax_chart.set_ylim(lo-pad, hi+pad)

    ax_chart.text(0.02, 0.97, "1H 캔들차트", color=TEXT_MUTED, fontsize=8, va="top", transform=ax_chart.transAxes)
    ax_chart.text(0.97, 0.97, "─ EMA20",     color=AMBER,      fontsize=8, va="top", ha="right", transform=ax_chart.transAxes)
    ax_chart.tick_params(colors=TEXT_MUTED, labelsize=7)
    ax_chart.yaxis.tick_right()

    # 현재 위치 한줄 (차트 아래)
    ax_chart.text(0.02, 0.04, "●", color=pos_c, fontsize=9, va="bottom", transform=ax_chart.transAxes)
    ax_chart.text(0.06, 0.04, f"{pos_lbl}  {pos_desc}", color=TEXT_MUTED, fontsize=7.5, va="bottom", transform=ax_chart.transAxes)

    # ── 행3: 타임프레임 B안 ─────────────────
    ax = new_ax(3)
    card(ax, 0.0, 0.0, 0.99, 0.99)
    ax.text(0.03, 0.92, "타임프레임", color=TEXT_MUTED, fontsize=8, fontweight="bold", va="top", transform=ax.transAxes)

    tfs = [
        ("15M", trend_15m), ("30M", trend_30m),
        ("1H",  trend_1h),  ("4H",  trend_4h),
    ]
    for i, (lbl, t) in enumerate(tfs):
        x = 0.04 + i * 0.245
        ax.plot(x, 0.45, "o", color=_tf_color(t), markersize=7, transform=ax.transAxes)
        ax.text(x+0.03, 0.45, f"{lbl} {_tf_txt(t)}", color=TEXT_WHITE, fontsize=9.5, va="center", transform=ax.transAxes)

    # 종합 라인
    ax.add_patch(Rectangle((0.0, 0.0), 0.004, 0.30, facecolor=tf_sum_c, transform=ax.transAxes))
    ax.text(0.03, 0.22, tf_sum, color=tf_sum_c, fontsize=8, fontweight="bold", va="top", transform=ax.transAxes)

    # ── 행4: 파동 구조 + 다이버전스 ─────────
    ax = new_ax(4)
    card(ax, 0.0, 0.0, 0.99, 0.99)
    ax.text(0.03, 0.94, "파동 구조 · 다이버전스", color=TEXT_MUTED, fontsize=8, fontweight="bold", va="top", transform=ax.transAxes)

    # 가격 구조 (왼쪽)
    card(ax, 0.03, 0.42, 0.44, 0.44, bg=BG_DARK)
    ax.text(0.06, 0.80, "가격 구조",  color=TEXT_MUTED, fontsize=8, va="top", transform=ax.transAxes)
    ax.text(0.06, 0.65, struct_lbl,   color=struct_c,   fontsize=12, fontweight="bold", va="top", transform=ax.transAxes)
    ax.text(0.06, 0.50, struct_desc,  color=TEXT_MUTED, fontsize=7.5, va="top", transform=ax.transAxes)

    # 다이버전스 (오른쪽)
    card(ax, 0.52, 0.42, 0.45, 0.44, bg=BG_DARK)
    ax.text(0.55, 0.80, "다이버전스", color=TEXT_MUTED, fontsize=8, va="top", transform=ax.transAxes)
    ax.plot(0.57, 0.63, "o", color=div_dot_c, markersize=6, transform=ax.transAxes)
    ax.text(0.61, 0.65, div_lbl,  color=div_dot_c, fontsize=11, fontweight="bold", va="top", transform=ax.transAxes)
    ax.text(0.55, 0.50, div_desc, color=TEXT_MUTED, fontsize=7.5, va="top", transform=ax.transAxes)

    # 종합 해석
    ax.add_patch(Rectangle((0.0, 0.0), 0.004, 0.38, facecolor=wave_c, transform=ax.transAxes))
    ax.text(0.03, 0.36, wave_sum, color=wave_c, fontsize=8, fontweight="bold", va="top", transform=ax.transAxes)

    # ── 행5: 지표 그리드 ────────────────────
    ax = new_ax(5)
    card(ax, 0.0, 0.0, 0.99, 0.99)
    ax.text(0.03, 0.94, "지표", color=TEXT_MUTED, fontsize=8, fontweight="bold", va="top", transform=ax.transAxes)

    indicators = [
        ("RSI",  f"{rsi_val:.1f}", rsi_lbl,  rsi_c),
        ("CCI",  f"{cci_val:.0f}", cci_lbl,  cci_c),
        ("MACD", macd_str,         macd_str,  macd_c),
    ]
    for i, (lbl, val, meaning, col) in enumerate(indicators):
        x = 0.04 + i * 0.325
        card(ax, x, 0.05, 0.30, 0.72, bg=BG_DARK)
        ax.text(x+0.15, 0.70, lbl,     color=TEXT_MUTED, fontsize=8,  va="top", ha="center", transform=ax.transAxes)
        ax.text(x+0.15, 0.52, val,     color=col,        fontsize=11, fontweight="bold", va="top", ha="center", transform=ax.transAxes)
        ax.text(x+0.15, 0.22, meaning, color=col,        fontsize=7.5,va="top", ha="center", transform=ax.transAxes)

    # ── 행6: 결론 ────────────────────────────
    ax = new_ax(6)
    ax.add_patch(Rectangle((0.0, 0.0), 0.004, 1.0, facecolor=concl_c, transform=ax.transAxes))
    ax.text(0.03, 0.82, concl_ttl, color=concl_c,   fontsize=10, fontweight="bold", va="top", transform=ax.transAxes)
    ax.text(0.03, 0.48, concl_txt, color=TEXT_MUTED, fontsize=9,  va="top", transform=ax.transAxes)
    ax.text(0.03, 0.10, "REAL 신호 오기 전 진입 금지 · 자동진입 아님",
            color=AMBER, fontsize=8, va="bottom", transform=ax.transAxes)

    # ── PNG 반환 ─────────────────────────────
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG_DARK)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
