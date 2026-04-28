# chart_renderer.py
# Render facade / backward-compatible API
# - New code should import card modules directly.
# - Existing scheduler/legacy imports can keep using this file.

from tradebot.render.radar_card import render_radar_card, send_radar_album, send_single_radar
from tradebot.render.hourly_card import render_hourly_dashboard_card

# ── WAIT / EARLY / PRE / REAL 5단계 카드 (step_card.py) ─────
from tradebot.render.step_card import (
    render_step_card,
    render_wait_card,
    render_early_card,
    render_pre_card,
    render_real_card,
)


def render_dashboard_card(sig: dict, candles_1h: list) -> bytes:
    """Backward-compatible 1H dashboard renderer."""
    return render_hourly_dashboard_card(sig, candles_1h)
