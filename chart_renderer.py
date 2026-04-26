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


# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────

def _safe(v, d=0.0):
    try:
        return float(v) if v is not None else d
    except:
        return d


def _get(sig, *keys, default=None):
    for k in keys:
        if k in sig and sig[k] is not None:
            return sig[k]
    return default


def _split_symbol(sym):
    sym = str(sym or "")
    if sym.endswith("USDT"):
        return sym[:-4], "USDT"
    return sym[:3], sym[3:] if len(sym) > 3 else ("", "")


# ─────────────────────────────────────────────
# 🔥 핵심 렌더 (최종 안정 버전)
# ─────────────────────────────────────────────

def render_radar_card(sig: dict, candles_15m: list) -> bytes:
    print("🔥 RADAR_RENDER_V3_CALLED", flush=True)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, FancyBboxPatch

    symbol      = _get(sig, "symbol", default="UNKNOWN")
    direction   = _get(sig, "direction", default="WAIT")
    long_score  = int(_get(sig, "long_score",  default=0))
    short_score = int(_get(sig, "short_score", default=0))
    confidence  = int(_get(sig, "confidence",  default=0))

    rsi_val  = _safe(_get(sig, "rsi", default=50))
    cci_val  = _safe(_get(sig, "cci", default=0))
    macd_raw = _get(sig, "macd_state", default="NEUTRAL")

    support    = _safe(_get(sig, "support", default=0))
    resistance = _safe(_get(sig, "resistance", default=0))

    ts = _get(sig, "timestamp", default=datetime.now(KST).strftime("%H:%M"))

    fig = plt.figure(figsize=(6, 9), facecolor=BG_DARK)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG_CELL)
    ax.axis("off")

    base, quote = _split_symbol(symbol)

    # ── 헤더
    ax.text(0.05, 0.92, base, color=GREEN, fontsize=20, fontweight="bold")
    ax.text(0.25, 0.92, quote, color=TEXT_WHITE, fontsize=14)

    ax.text(0.75, 0.92, "진입레이더",
            color="white",
            bbox=dict(facecolor=PURPLE, boxstyle="round,pad=0.3"))

    ax.text(0.95, 0.92, ts, color=TEXT_MUTED, ha="right")

    # ── 방향
    ax.text(0.05, 0.80, direction,
            color=GREEN if direction=="LONG" else RED,
            fontsize=18)

    ax.text(0.05, 0.74, f"신뢰도 {confidence}%", color=TEXT_WHITE)

    # ── 점수
    ax.text(0.05, 0.65, f"LONG {long_score}%", color=GREEN)
    ax.text(0.80, 0.65, f"SHORT {short_score}%", color=RED)

    gap = abs(long_score - short_score)
    ax.text(0.40, 0.60, f"차이 {gap}%", color=TEXT_MUTED)

    # ── 지표
    ax.text(0.05, 0.50, f"RSI {rsi_val:.2f}", color=TEXT_WHITE)
    ax.text(0.05, 0.45, f"CCI {cci_val:.2f}", color=TEXT_WHITE)
    ax.text(0.05, 0.40, f"MACD {macd_raw}", color=TEXT_WHITE)

    # ── 상태
    if confidence < 60:
        ax.text(0.05, 0.30, "조건 미충족 · 대기", color=AMBER)
    else:
        ax.text(0.05, 0.30, "진입 가능 구간", color=GREEN)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=BG_DARK)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
