import pandas as pd
import ta


def calculate_divergence(df, indicator_col, lookback=20):
    """
    최근 lookback 구간에서 가격과 지표 방향이 반대로 움직이는지 판단
    - 가격 저점 하락 + 지표 저점 상승 = 상승 다이버전스
    - 가격 고점 상승 + 지표 고점 하락 = 하락 다이버전스
    """

    try:
        recent = df.tail(lookback).copy()

        price_low_first = recent["low"].iloc[:lookback // 2].min()
        price_low_second = recent["low"].iloc[lookback // 2:].min()

        price_high_first = recent["high"].iloc[:lookback // 2].max()
        price_high_second = recent["high"].iloc[lookback // 2:].max()

        ind_low_first = recent[indicator_col].iloc[:lookback // 2].min()
        ind_low_second = recent[indicator_col].iloc[lookback // 2:].min()

        ind_high_first = recent[indicator_col].iloc[:lookback // 2].max()
        ind_high_second = recent[indicator_col].iloc[lookback // 2:].max()

        bullish = price_low_second < price_low_first and ind_low_second > ind_low_first
        bearish = price_high_second > price_high_first and ind_high_second < ind_high_first

        if bullish:
            return "상승 다이버전스"
        if bearish:
            return "하락 다이버전스"

        return "없음"

    except Exception:
        return "판단불가"


def calculate_slope(series, period=5):
    try:
        if len(series) < period + 1:
            return "판단불가"

        start = series.iloc[-period]
        end = series.iloc[-1]

        if end > start:
            return "상승"
        if end < start:
            return "하락"

        return "횡보"

    except Exception:
        return "판단불가"


def calculate_indicators(candles):
    try:
        if len(candles) < 50:
            return None

        df = pd.DataFrame(
            candles,
            columns=["time", "open", "high", "low", "close", "volume", "turnover"]
        )

        df = df.iloc[::-1].reset_index(drop=True)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # RSI
        df["rsi"] = ta.momentum.RSIIndicator(
            close=df["close"],
            window=14
        ).rsi()

        # MACD
        macd = ta.trend.MACD(df["close"])
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_diff"] = macd.macd_diff()

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(
            close=df["close"],
            window=20,
            window_dev=2
        )
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_mid"] = bb.bollinger_mavg()
        df["bb_lower"] = bb.bollinger_lband()

        # EMA
        df["ema20"] = ta.trend.EMAIndicator(
            close=df["close"],
            window=20
        ).ema_indicator()

        df["ema50"] = ta.trend.EMAIndicator(
            close=df["close"],
            window=50
        ).ema_indicator()

        # CCI
        df["cci"] = ta.trend.CCIIndicator(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            window=20
        ).cci()

        # Volume
        df["vol_ma20"] = df["volume"].rolling(window=20).mean()

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        rsi_divergence = calculate_divergence(df, "rsi", lookback=20)
        cci_divergence = calculate_divergence(df, "cci", lookback=20)

        rsi_slope = calculate_slope(df["rsi"], period=5)
        cci_slope = calculate_slope(df["cci"], period=5)

        if latest["macd_diff"] > 0 and prev["macd_diff"] <= 0:
            macd_cross = "골든크로스"
        elif latest["macd_diff"] < 0 and prev["macd_diff"] >= 0:
            macd_cross = "데드크로스"
        else:
            macd_cross = "없음"

        ema_state = "정배열" if latest["ema20"] > latest["ema50"] else "역배열"

        vol_ratio = (
            latest["volume"] / latest["vol_ma20"]
            if latest["vol_ma20"] and latest["vol_ma20"] > 0
            else 0
        )

        return {
            "close": round(latest["close"], 4),
            "high": round(latest["high"], 4),
            "low": round(latest["low"], 4),

            "rsi": round(latest["rsi"], 2),
            "rsi_slope": rsi_slope,
            "rsi_divergence": rsi_divergence,

            "cci": round(latest["cci"], 2),
            "cci_slope": cci_slope,
            "cci_divergence": cci_divergence,

            "macd": round(latest["macd"], 4),
            "macd_signal": round(latest["macd_signal"], 4),
            "macd_diff": round(latest["macd_diff"], 4),
            "macd_cross": macd_cross,

            "bb_upper": round(latest["bb_upper"], 4),
            "bb_mid": round(latest["bb_mid"], 4),
            "bb_lower": round(latest["bb_lower"], 4),

            "ema20": round(latest["ema20"], 4),
            "ema50": round(latest["ema50"], 4),
            "ema_state": ema_state,

            "vol_ratio": round(vol_ratio, 2),
        }

    except Exception as e:
        print(f"[지표 계산 실패] {e}")
        return None
