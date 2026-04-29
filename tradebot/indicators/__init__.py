from tradebot.indicators.rsi import calculate_rsi
from tradebot.indicators.cci import calculate_cci
from tradebot.indicators.ema import calculate_ema
from tradebot.indicators.macd import calculate_macd
from tradebot.indicators.fibo import calculate_fibo_zone
from tradebot.indicators.divergence import detect_divergence

def run_indicators(candles_by_tf: dict) -> dict:
    c15 = candles_by_tf.get("15m") or []
    c1h = candles_by_tf.get("1h") or c15
    rsi = calculate_rsi(c15)
    cci = calculate_cci(c15)
    macd = calculate_macd(c15)
    fibo = calculate_fibo_zone(c1h)
    div = detect_divergence(c15, rsi, cci)
    return {
        "rsi": rsi,
        "cci": cci,
        "ema20": calculate_ema(c15, 20),
        "ema50": calculate_ema(c15, 50),
        "ema200": calculate_ema(c15, 200),
        "macd": macd.get("macd"),
        "macd_hist": macd.get("hist"),
        "macd_state": macd.get("state"),
        **fibo,
        **div,
    }
