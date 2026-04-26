def render_radar_card(sig: dict, candles_15m: list) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    # ─────────────────────────────
    # 데이터 추출
    # ─────────────────────────────
    symbol = sig.get("symbol", "UNKNOWN")
    direction = sig.get("direction", "WAIT")

    long_score = int(sig.get("long_score", 0))
    short_score = int(sig.get("short_score", 0))
    gap = abs(long_score - short_score)

    rsi = float(sig.get("rsi", 50))
    cci = float(sig.get("cci", 0))
    macd = sig.get("macd_state", "NEUTRAL")

    trend_15m = sig.get("trend_15m", "SIDEWAYS")
    trend_1h = sig.get("trend_1h", "SIDEWAYS")

    support = float(sig.get("support", 0))
    resistance = float(sig.get("resistance", 0))
    mid = (support + resistance) / 2 if support and resistance else 0

    is_range = sig.get("is_range", False)
    range_pos = sig.get("range_pos")

    volume = sig.get("volume", 0)
    avg_volume = sig.get("avg_volume", 0)
    volume_ratio = sig.get("volume_ratio") or (volume / avg_volume if avg_volume else 0)

    now_price = candles_15m[-1]["close"] if candles_15m else 0

    # ─────────────────────────────
    # 시그널 강도
    # ─────────────────────────────
    if gap < 15:
        strength = "매우 약한 신호"
    elif gap < 25:
        strength = "약한 신호"
    elif gap < 40:
        strength = "보통 신호"
    else:
        strength = "강한 신호"

    # ─────────────────────────────
    # 캔들 데이터
    # ─────────────────────────────
    candles = candles_15m[-30:]
    xs = list(range(len(candles)))

    def f(c, k): return float(c.get(k, 0))
    o = [f(c,"open") for c in candles]
    h = [f(c,"high") for c in candles]
    l = [f(c,"low") for c in candles]
    c_ = [f(c,"close") for c in candles]

    def ema(vals, p=20):
        if not vals: return []
        k = 2/(p+1)
        out=[vals[0]]
        for v in vals[1:]:
            out.append(v*k + out[-1]*(1-k))
        return out

    ema20 = ema(c_)

    # ─────────────────────────────
    # FIG
    # ─────────────────────────────
    fig = plt.figure(figsize=(6, 9.5), facecolor=BG_DARK)
    gs = fig.add_gridspec(6,1,
        height_ratios=[0.6,0.5,2.8,0.3,0.9,1.4],
        hspace=0.1)

    # =========================
    # 0. HEADER
    # =========================
    ax = fig.add_subplot(gs[0]); ax.axis("off")

    ax.text(0.02,0.5,symbol,color=TEXT_WHITE,fontsize=16,weight="bold")
    ax.text(0.7,0.5,"진입레이더",color="white",fontsize=9,
        bbox=dict(boxstyle="round",fc=PURPLE))
    ax.text(0.95,0.5,sig.get("timestamp",""),ha="right",color=TEXT_MUTED)

    # =========================
    # 1. 방향 바
    # =========================
    ax = fig.add_subplot(gs[1]); ax.axis("off")

    ax.barh(0,1,color="#21262d",height=0.5)
    ax.barh(0,long_score/100,color=GREEN,height=0.5)
    ax.barh(0,short_score/100,left=1-(short_score/100),color=RED,height=0.5)

    label = "LONG 지지" if long_score>short_score else "SHORT 지지"
    label_color = GREEN if long_score>short_score else RED

    ax.text(0.01,0.9,label,color="white",fontsize=9,
        bbox=dict(boxstyle="round",fc=label_color))
    ax.text(0.2,0.9,f"차이 {gap}%p · {strength}",color=TEXT_WHITE,fontsize=9)
    ax.text(0.95,0.9,"감시구간",ha="right",color=TEXT_MUTED)

    ax.text(0.01,-0.2,f"LONG {long_score}%",color=GREEN)
    ax.text(0.95,-0.2,f"SHORT {short_score}%",ha="right",color=RED)

    ax.set_xlim(0,1)

    # =========================
    # 2. 캔들차트
    # =========================
    ax = fig.add_subplot(gs[2])
    ax.set_facecolor(BG_CELL)

    for i in range(len(xs)):
        color = GREEN if c_[i]>=o[i] else RED
        ax.plot([i,i],[l[i],h[i]],color=color)
        ax.add_patch(plt.Rectangle((i-0.3,min(o[i],c_[i])),0.6,abs(c_[i]-o[i]),color=color))

    if ema20:
        ax.plot(xs,ema20,color=AMBER)

    if is_range:
        ax.axhline(resistance,color=RED,linestyle="--")
        ax.axhline(mid,color=AMBER,linestyle="--",alpha=0.5)
        ax.axhline(support,color=GREEN,linestyle="--")

    ax.axhline(now_price,color=TEXT_MUTED,linestyle="--")

    ax.set_xticks([]); ax.set_yticks([])

    # =========================
    # 3. 위치 한줄
    # =========================
    ax = fig.add_subplot(gs[3]); ax.axis("off")

    if not is_range:
        txt="추세 구간 · 박스권 아님"
        color=TEXT_MUTED
    elif range_pos=="MIDDLE":
        txt=f"박스 중앙 · {support:.0f}~{resistance:.0f} · 진입 금지"
        color=AMBER
    elif range_pos=="TOP":
        txt="박스 상단 · 숏 후보"
        color=RED
    else:
        txt="박스 하단 · 롱 후보"
        color=GREEN

    ax.text(0.02,0.5,"●",color=color)
    ax.text(0.06,0.5,txt,color=TEXT_WHITE)

    # =========================
    # 4. 진입조건 + 거래량
    # =========================
    ax = fig.add_subplot(gs[4]); ax.axis("off")

    ax.text(0.02,0.8,f"숏: {support:.0f} 이탈 + 거래량 1.2배",color=RED)
    ax.text(0.02,0.55,f"롱: {resistance:.0f} 돌파 + 거래량 1.2배",color=GREEN)

    fill = min(volume_ratio/1.2,1)

    ax.barh(0.2,1,color="#21262d",height=0.2)
    ax.barh(0.2,fill,color=GREEN if volume_ratio>=1.2 else AMBER,height=0.2)

    txt = "조건 충족" if volume_ratio>=1.2 else f"{(1.2-volume_ratio)*100:.0f}% 부족"
    ax.text(0.5,0.2,txt,ha="center",color=GREEN if volume_ratio>=1.2 else RED)

    # =========================
    # 5. 시간봉 + 지표
    # =========================
    ax = fig.add_subplot(gs[5]); ax.axis("off")

    def trend_txt(t):
        if t=="UP": return "상승",GREEN
        if t=="DOWN": return "하락",RED
        return "횡보",TEXT_MUTED

    t15, c15 = trend_txt(trend_15m)
    t1h, c1h = trend_txt(trend_1h)

    ax.text(0.02,0.8,f"15M {t15}",color=c15)
    ax.text(0.02,0.6,f"1H {t1h}",color=c1h)

    # RSI
    if rsi<30: rsi_txt="강한 과매도"; rsi_c=GREEN
    elif rsi<45: rsi_txt="과매도"; rsi_c=GREEN
    elif rsi<55: rsi_txt="중립"; rsi_c=TEXT_MUTED
    elif rsi<70: rsi_txt="과매수"; rsi_c=RED
    else: rsi_txt="강한 과매수"; rsi_c=RED

    ax.text(0.5,0.8,f"RSI {rsi:.1f} {rsi_txt}",color=rsi_c)

    # CCI
    if cci<-200: cci_txt="극단 과매도"; cci_c=GREEN
    elif cci<-100: cci_txt="강한 하락"; cci_c=RED
    elif cci<0: cci_txt="약한 하락"; cci_c=TEXT_MUTED
    elif cci<100: cci_txt="약한 상승"; cci_c=TEXT_MUTED
    else: cci_txt="강한 상승"; cci_c=GREEN

    ax.text(0.5,0.6,f"CCI {cci:.1f} {cci_txt}",color=cci_c)

    # MACD
    macd_txt = _MACD_KO.get(macd,"중립")
    macd_c = GREEN if macd in ["BULLISH","POSITIVE"] else RED if macd in ["BEARISH","NEGATIVE"] else TEXT_MUTED
    ax.text(0.5,0.4,f"MACD {macd_txt}",color=macd_c)

    # 충돌 감지
    if rsi<45 and macd in ["BULLISH","POSITIVE"] and cci<-100:
        ax.text(0.02,0.1,
            "지표 충돌 — 손절 확률 상승",
            color=AMBER)

    buf = io.BytesIO()
    fig.savefig(buf,format="png",dpi=150,facecolor=BG_DARK)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
