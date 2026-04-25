# chart_renderer.py
# 진입레이더 카드 이미지(PNG) 생성
# 한글 폰트 포함 완전 안정 버전

import io
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# ─────────────────────────────────────────────
# 🔥 폰트 직접 로딩 (핵심 수정)
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

    # fallback
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
LIME_GREEN = "#4ade80"

_TREND_KO = {"UP": "상승", "DOWN": "하락", "SIDEWAYS": "횡보"}

# ─────────────────────────────────────────────
# 핵심 렌더링
# ─────────────────────────────────────────────

def render_radar_card(sig: dict, candles_15m: list) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    symbol = sig["symbol"]
    direction = sig["direction"]
    confidence = sig["confidence"]

    fig = plt.figure(figsize=(6, 8), facecolor=BG_DARK)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG_CELL)
    ax.axis("off")

    # 제목
    ax.text(0.05, 0.9, symbol, color=TEXT_WHITE, fontsize=18, fontweight="bold")

    # 상태
    ax.text(0.05, 0.8, f"{direction} 감시", color=RED if direction=="SHORT" else GREEN, fontsize=14)

    # 신뢰도
    ax.text(0.05, 0.7, f"신뢰도 {confidence}%", color=TEXT_WHITE, fontsize=12)

    # 추세
    ax.text(0.05, 0.6, f"15M: {_TREND_KO.get(sig.get('trend_15m'))}", color=TEXT_MUTED)
    ax.text(0.05, 0.55, f"1H: {_TREND_KO.get(sig.get('trend_1h'))}", color=TEXT_MUTED)

    # 지표
    ax.text(0.05, 0.45, f"RSI: {sig.get('rsi'):.2f}", color=TEXT_WHITE)
    ax.text(0.05, 0.40, f"CCI: {sig.get('cci'):.2f}", color=TEXT_WHITE)
    ax.text(0.05, 0.35, f"MACD: {sig.get('macd_state')}", color=TEXT_WHITE)

    # 이유
    reason = sig.get("reason", "")
    ax.text(0.05, 0.25, f"제한: {reason}", color=AMBER)

    # 상태
    ax.text(0.05, 0.15, "대기 중", color=TEXT_MUTED)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=BG_DARK)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
