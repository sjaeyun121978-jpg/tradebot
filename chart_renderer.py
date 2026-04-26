# chart_renderer.py
# 진입레이더 카드 이미지(PNG) 생성 - 전광판 V3

import io
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# ─────────────────────────────────────────────
# 폰트 설정 (기존 유지)
# ─────────────────────────────────────────────

def _setup_korean_font():
    import matplotlib
    import matplotlib.font_manager as fm

    base_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(base_dir, "fonts")

    font_candidates = [
        "NanumGothic-Regular.ttf",
        "NanumGothic-Bold.ttf",
        "NanumGothic-ExtraBold.ttf"
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

BG_DARK = "#0d1117"
BG_CELL = "#1c2128"
TEXT_WHITE = "#e6edf3"
TEXT_MUTED = "#8b949e"
RED = "#f85149"
GREEN = "#3fb950"
AMBER = "#d29922"
PURPLE = "#a78bfa"

# ─────────────────────────────────────────────
# 진입레이더 (전광판 V3)
# ─────────────────────────────────────────────

def render_radar_card(sig: dict, candles_15m: list) -> bytes:
    print("🔥 RADAR_RENDER_V3_CALLED", flush=True)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    symbol = sig.get("symbol", "UNKNOWN")
    direction = sig.get("direction", "NEUTRAL")
    confidence = sig.get("confidence", 0)
    long_score = sig.get("long_score", 0)
    short_score = sig.get("short_score", 0)
    gap = abs(long_score - short_score)

    rsi = sig.get("rsi", 0)
    cci = sig.get("cci", 0)
    macd = sig.get("macd_state", "NEUTRAL")

    fig = plt.figure(figsize=(6, 8), facecolor=BG_DARK)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG_CELL)
    ax.axis("off")

    # ───── 헤더 ─────
    ax.text(0.05, 0.92, f"{symbol}", color=TEXT_WHITE, fontsize=16, fontweight="bold")
    ax.text(0.95, 0.92, "진입레이더", color=PURPLE, fontsize=10, ha="right")

    # ───── 상태 ─────
    color = GREEN if direction == "LONG" else RED if direction == "SHORT" else TEXT_MUTED
    ax.text(0.05, 0.84, f"{direction}", color=color, fontsize=14, fontweight="bold")

    # ───── 신뢰도 ─────
    ax.text(0.05, 0.78, f"신뢰도 {confidence}%", color=TEXT_WHITE, fontsize=12)

    # ───── 점수 ─────
    ax.text(0.05, 0.70, f"LONG {long_score}%", color=GREEN)
    ax.text(0.95, 0.70, f"SHORT {short_score}%", color=RED, ha="right")

    # ───── gap 판단 ─────
    if gap < 15:
        strength = "매우 약함"
    elif gap < 25:
        strength = "약함"
    elif gap < 40:
        strength = "보통"
    else:
        strength = "강함"

    ax.text(0.5, 0.65, f"차이 {gap}% · {strength}", color=TEXT_MUTED, ha="center")

    # ───── 지표 ─────
    ax.text(0.05, 0.55, f"RSI {rsi:.2f}", color=TEXT_WHITE)
    ax.text(0.05, 0.50, f"CCI {cci:.2f}", color=TEXT_WHITE)
    ax.text(0.05, 0.45, f"MACD {macd}", color=TEXT_WHITE)

    # ───── 판단 ─────
    if confidence < 60:
        msg = "조건 미충족 · 대기"
        msg_color = AMBER
    else:
        msg = "진입 가능 구간"
        msg_color = GREEN if direction == "LONG" else RED

    ax.text(0.05, 0.35, msg, color=msg_color, fontsize=12, fontweight="bold")

    # ───── footer ─────
    now = datetime.now(KST).strftime("%H:%M")
    ax.text(0.95, 0.05, now, color=TEXT_MUTED, ha="right", fontsize=9)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=BG_DARK)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
