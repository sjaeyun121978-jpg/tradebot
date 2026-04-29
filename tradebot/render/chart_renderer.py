# chart_renderer.py
# Render facade / backward-compatible API
# - New code should import card modules directly.
# - Existing scheduler/legacy imports can keep using this file.

from tradebot.render.radar_card import render_radar_card, send_radar_album, send_single_radar
from tradebot.render.hourly_card import render_hourly_dashboard_card

# ── STEP 카드 — render_step_card 단일 진입점 ─────────────────
# render_wait/pre/real_card는 하위 호환 유지 (내부적으로 render_step_card 경유)
from tradebot.render.step_card import (
    render_step_card,
    render_wait_card,
    render_early_card,
    render_pre_card,
    render_real_card,
    ensure_chart_data,
    normalize_box_levels,
)


def render_dashboard_card(sig: dict, candles_1h: list) -> bytes:
    """Backward-compatible 1H dashboard renderer."""
    return render_hourly_dashboard_card(sig, candles_1h)
