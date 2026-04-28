"""Entry radar payload normalizer."""


def normalize_radar_signal(symbol: str, result) -> dict:
    if isinstance(result, dict):
        payload = dict(result)
    else:
        payload = {"message": str(result) if result is not None else ""}
    payload.setdefault("symbol", symbol)
    return payload
