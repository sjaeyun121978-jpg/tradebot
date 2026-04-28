"""1H dashboard payload normalizer."""


def build_hourly_dashboard_payload(symbol: str, structure_result) -> dict:
    if isinstance(structure_result, dict):
        payload = dict(structure_result)
    else:
        payload = {"message": str(structure_result) if structure_result is not None else ""}
    payload.setdefault("symbol", symbol)
    payload.setdefault("chart_tf", "1H")
    payload.setdefault("_chart_tf", "1H")
    return payload


def build_hourly_caption(symbol: str, payload: dict) -> str:
    state = payload.get("state") or payload.get("direction") or "WAIT"
    price = payload.get("current_price") or payload.get("price") or 0
    try:
        price_text = f"{float(price):,.2f}"
    except Exception:
        price_text = str(price)
    return (
        f"🕐 <b>1H 마감 브리핑</b>\n"
        f"{symbol} / {state} / 현재가 {price_text}\n"
        "※ 1시간봉 마감 기준 상황판"
    )
