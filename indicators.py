import pandas as pd
import ta


def calculate_indicators(candles):
    try:
        if len(candles) < 20:
            return None

        df = pd.DataFrame(
            candles,
            columns=["time", "open", "high", "low", "close", "volume", "turnover"]
        )

        df = df.iloc[::-1].reset_index(drop=True)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # =========================
        # RSI
        # =========================
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

        # =========================
        # MACD
        # =========================
        macd = ta.trend.MACD(df["close"])
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_diff"] = macd.macd_diff()

        # =========================
        # 볼린저밴드
        # =========================
        bb = ta.volatility.BollingerBands(df["close"], window=20)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_mid"] = bb.bollinger_mavg()

        # =========================
        # EMA
        # =========================
        df["ema20"] = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator()
        df["ema50"] = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()

        # =========================
        # 거래량 평균
        # =========================
        df["vol_ma20"] = df["volume"].rolling(window=20).mean()

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        return {
            "rsi": round(latest["rsi"], 2),

            "macd": round(latest["macd"], 4),
            "macd_signal": round(latest["macd_signal"], 4),
            "macd_diff": round(latest["macd_diff"], 4),

            "macd_cross": "골든크로스"
            if latest["macd_diff"] > 0 and prev["macd_diff"] <= 0
            else "데드크로스"
            if latest["macd_diff"] < 0 and prev["macd_diff"] >= 0
            else "없음",

            "bb_upper": round(latest["bb_upper"], 4),
            "bb_lower": round(latest["bb_lower"], 4),
            "bb_mid": round(latest["bb_mid"], 4),

            "ema20": round(latest["ema20"], 4),
            "ema50": round(latest["ema50"], 4),
            "ema_cross": "정배열" if latest["ema20"] > latest["ema50"] else "역배열",

            "vol_ratio": round(
                latest["volume"] / latest["vol_ma20"], 2
            ) if latest["vol_ma20"] > 0 else 0,

            "close": round(latest["close"], 4),
            "high": round(latest["high"], 4),
            "low": round(latest["low"], 4),
        }

    except Exception as e:
        print(f"[지표 계산 실패] {e}")
        return None
