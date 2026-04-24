import asyncio
from datetime import datetime, timedelta

from telegram_utils import send_telegram_message
from bybit_client import get_current_price, get_candles
from indicators import calculate_indicators
from analyzers import analyze_fact

# =========================
# 상태 저장 (중복 방지)
# =========================
last_signal = {}

# =========================
# 공용 함수
# =========================
async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


# =========================
# 1. 정시 팩트 분석 (ETH, BTC 분리 발송)
# =========================
async def hourly_fact_analysis_loop():
    while True:
        try:
            now = datetime.now()

            # 다음 정시까지 대기
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            wait_seconds = (next_hour - now).total_seconds()

            await asyncio.sleep(wait_seconds)

            for symbol in ["ETH", "BTC"]:
                price = await run_blocking(get_current_price, symbol)
                candles = await run_blocking(get_candles, symbol, "15", 60)
                indicators = await run_blocking(calculate_indicators, candles)

                result = await run_blocking(
                    analyze_fact,
                    symbol,
                    price,
                    indicators
                )

                send_telegram_message(
                    f"📊 {symbol} 정시 팩트기반구조분석\n"
                    f"시간: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"현재가: {price}\n\n"
                    f"{result}"
                )

        except Exception as e:
            print(f"[정시 분석 오류] {e}")
            await asyncio.sleep(60)


# =========================
# 2. 실시간 트리거 감시 (핵심)
# =========================
async def condition_monitor_loop(symbol):
    global last_signal

    prev_price = None
    last_alert_time = None

    while True:
        try:
            price = await run_blocking(get_current_price, symbol)
            candles = await run_blocking(get_candles, symbol, "15", 60)
            indicators = await run_blocking(calculate_indicators, candles)

            if not price or not indicators:
                await asyncio.sleep(60)
                continue

            ema20 = indicators["ema20"]
            ema50 = indicators["ema50"]
            vol = indicators["vol_ratio"]

            signal = None

            # =========================
            # 🔥 돌파 기반 트리거
            # =========================
            if prev_price:
                # 롱 돌파
                if prev_price <= ema20 and price > ema20 and vol >= 1.5:
                    signal = "LONG"

                # 숏 이탈
                elif prev_price >= ema50 and price < ema50 and vol >= 1.5:
                    signal = "SHORT"

            # =========================
            # ⛔ 쿨타임 (10분)
            # =========================
            now = datetime.now()

            if signal:
                if last_alert_time and (now - last_alert_time).seconds < 600:
                    signal = None

            # =========================
            # 알림 발송
            # =========================
            if signal:
                send_telegram_message(
                    f"🚨 {symbol} 트리거 발생\n"
                    f"현재가: {price}\n"
                    f"신호: {signal}\n"
                    f"거래량비율: {vol}\n\n"
                    f"※ 돌파 기반 1회 신호"
                )

                last_signal[symbol] = signal
                last_alert_time = now

            prev_price = price

        except Exception as e:
            print(f"[트리거 오류] {symbol}: {e}")

        await asyncio.sleep(60)


# =========================
# 3. 실행 스타터
# =========================
async def start_all_loops():
    asyncio.create_task(hourly_fact_analysis_loop())

    # ETH, BTC 각각 따로 감시
    asyncio.create_task(condition_monitor_loop("ETH"))
    asyncio.create_task(condition_monitor_loop("BTC"))
