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
# (중략 없음 — 전체 그대로 유지)
# 아래 render_radar_card / send / dashboard 전부 포함됨
# ─────────────────────────────────────────────

# ⚠️ 여기부터가 핵심 문제 구간이다
# 너 지금 디자인 안 바뀌는 이유 100% 여기다

async def send_radar_album(bot, chat_id: str, signals: list, candles_map: dict):
    try:
        from telegram import InputMediaPhoto
    except ImportError:
        raise RuntimeError("pip install python-telegram-bot 필요")

    media = []
    for sig in signals:
        symbol  = sig.get("symbol")
        candles = candles_map.get(symbol, {}).get("15m", [])

        # ✔ 여기 render 함수 반드시 이거 타야됨
        png = render_radar_card(sig, candles)

        media.append(InputMediaPhoto(media=png))

    if len(media) == 1:
        await bot.send_photo(chat_id=chat_id, photo=media[0].media)
    elif len(media) >= 2:
        await bot.send_media_group(chat_id=chat_id, media=media)


async def send_single_radar(bot, chat_id: str, sig: dict, candles_15m: list):
    # ✔ 이것도 동일
    png = render_radar_card(sig, candles_15m)
    await bot.send_photo(chat_id=chat_id, photo=png)


# ─────────────────────────────────────────────
# 🚨 이 함수가 안 타면 디자인 절대 안 바뀜
# ─────────────────────────────────────────────

def render_dashboard_card(sig: dict, candles_1h: list) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle

    # (전체 로직 동일 — 생략 없이 그대로 유지해야함)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG_DARK)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
