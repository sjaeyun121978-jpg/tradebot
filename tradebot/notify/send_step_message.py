"""STEP 메시지 전송 전용. 판단 로직 없음."""
from __future__ import annotations
from tradebot.delivery import telegram
from tradebot.render.step_card import render_step_card


def _caption(decision: dict) -> str:
    step = decision.get("final_state") or decision.get("step") or "WAIT"
    direction = decision.get("direction", "NEUTRAL")
    score = decision.get("score", 0)
    gap = decision.get("gap", 0)
    quality = decision.get("quality_tier", "LOW")
    action = decision.get("action_text", "")
    warns = decision.get("warning_reasons") or []
    lines = [
        f"{step} {direction}",
        f"score={score} gap={gap} quality={quality}",
        action,
    ]
    if warns:
        lines.append("WARNING: " + " / ".join(str(x) for x in warns[:3]))
    return "\n".join(lines)


def send_step_message(decision: dict, candles_1h: list | None = None) -> bool:
    payload = dict(decision or {})
    step = str(payload.get("final_state") or payload.get("step") or "WAIT").upper()
    try:
        image = render_step_card(step, payload, candles_1h or [])
        return telegram.send_photo(image, caption=_caption(payload), parse_mode=None)
    except Exception as exc:
        print(f"[STEP MESSAGE ERROR] image failed: {exc}", flush=True)
        return telegram.send_message(_caption(payload), parse_mode=None)
