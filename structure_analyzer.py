import pandas as pd


def candles_to_df(candles):
    if not candles:
        return None

    df = pd.DataFrame(
        candles,
        columns=["time", "open", "high", "low", "close", "volume", "turnover"]
    )

    df = df.iloc[::-1].reset_index(drop=True)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df


def find_recent_swings(df, window=3):
    highs = []
    lows = []

    if df is None or len(df) < window * 2 + 1:
        return highs, lows

    for i in range(window, len(df) - window):
        current_high = df["high"].iloc[i]
        current_low = df["low"].iloc[i]

        left_high = df["high"].iloc[i - window:i].max()
        right_high = df["high"].iloc[i + 1:i + window + 1].max()

        left_low = df["low"].iloc[i - window:i].min()
        right_low = df["low"].iloc[i + 1:i + window + 1].min()

        if current_high > left_high and current_high > right_high:
            highs.append({
                "index": i,
                "price": round(current_high, 4)
            })

        if current_low < left_low and current_low < right_low:
            lows.append({
                "index": i,
                "price": round(current_low, 4)
            })

    return highs[-5:], lows[-5:]


def classify_structure(highs, lows):
    if len(highs) < 2 or len(lows) < 2:
        return "구조 부족"

    last_high = highs[-1]["price"]
    prev_high = highs[-2]["price"]

    last_low = lows[-1]["price"]
    prev_low = lows[-2]["price"]

    high_state = "HH" if last_high > prev_high else "LH"
    low_state = "HL" if last_low > prev_low else "LL"

    if high_state == "HH" and low_state == "HL":
        trend = "상승 구조"
    elif high_state == "LH" and low_state == "LL":
        trend = "하락 구조"
    else:
        trend = "전환/박스 구조"

    return f"{high_state}/{low_state} - {trend}"


def classify_wave(structure_text):
    if "HH/HL" in structure_text:
        return "상승파동 가능성"
    if "LH/LL" in structure_text:
        return "하락파동 가능성"
    if "전환/박스" in structure_text:
        return "조정파동 또는 박스권"
    return "파동 판단 보류"


def classify_elliott(structure_text, highs, lows):
    if len(highs) < 3 or len(lows) < 3:
        return "엘리엇 판단 보류"

    if "HH/HL" in structure_text:
        return "상승 3파 또는 상승 5파 진행 후보"

    if "LH/LL" in structure_text:
        return "하락 3파 또는 하락 5파 진행 후보"

    return "ABC 조정 또는 플랫 조정 후보"


def classify_similar_case(structure_text):
    if "LH/LL" in structure_text:
        return "하락 중 약반등 후 재하락 구조와 유사"

    if "HH/HL" in structure_text:
        return "상승 전환 후 눌림 재상승 구조와 유사"

    if "전환/박스" in structure_text:
        return "플랫 조정 또는 방향 대기 박스권과 유사"

    return "유사 구조 판단 보류"


def analyze_single_timeframe(candles):
    df = candles_to_df(candles)

    if df is None or len(df) < 30:
        return {
            "structure": "데이터 부족",
            "wave": "데이터 부족",
            "elliott": "데이터 부족",
            "similar_case": "데이터 부족",
            "recent_highs": [],
            "recent_lows": []
        }

    highs, lows = find_recent_swings(df)
    structure = classify_structure(highs, lows)
    wave = classify_wave(structure)
    elliott = classify_elliott(structure, highs, lows)
    similar_case = classify_similar_case(structure)

    return {
        "structure": structure,
        "wave": wave,
        "elliott": elliott,
        "similar_case": similar_case,
        "recent_highs": highs[-3:],
        "recent_lows": lows[-3:]
    }


def analyze_market_structure(candles_by_tf):
    result = {}

    for tf, candles in candles_by_tf.items():
        result[tf] = analyze_single_timeframe(candles)

    return result
