# chart_renderer.py
# Render facade / backward-compatible API
# - New code should import card modules directly.
# - Existing scheduler/legacy imports can keep using this file.

from tradebot.render.radar_card import render_radar_card, send_radar_album, send_single_radar
from tradebot.render.hourly_card import render_hourly_dashboard_card


def render_dashboard_card(sig: dict, candles_1h: list) -> bytes:
    """Backward-compatible 1H dashboard renderer."""
    return render_hourly_dashboard_card(sig, candles_1h)
