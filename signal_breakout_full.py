# signal_breakout_full.py
# NASDAQ 전종목 + KOSDAQ 전종목 돌파 신호 스캐너
# 3가지 조건 모두 충족 시에만 텔레그램 알람

import yfinance as yf
import pandas as pd
import numpy as np
import requests, os, sys, time, re
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8386728044:AAH27uG-7OWKlQG4Nr97sJli6Wnjes_wcvw")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "936157775")

# ── 설정값 ─────────────────────────────────────────
LOOKBACK   = 15    # 기준 봉 수
VOL_MULT   = 1.5   # 거래량 배수 기준
OBV_PERIOD = 20    # OBV EMA 기간
INTERVALS  = ["30m"]
BATCH_SIZE = 50    # 한 번에 다운로드할 종목 수
MAX_ALERTS = 10    # 한 번에 최대 알람 수 (너무 많으면 분할)

# ── 최소 조건 (토스증권 거래 가능 종목 기준) ────────────────────────
# 토스증권은 유동성 있는 종목만 지원 → 거래량/가격 기준으로 필터링
MIN_PRICE_KR = 1000      # 최소 주가 (원) - 동전주 제외
MIN_PRICE_US = 5.0       # 최소 주가 ($) - 토스증권 미지원 저가주 제외
MIN_VOL_KR   = 50000     # 최소 거래량 (한국) - 유동성 확보
MIN_VOL_US   = 500000    # 최소 거래량 (미국) - 토스증권 거래 가능 수준

def send(msg):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
        timeout=15
    )
    return r.status_code == 200

def get_all_tickers():
    """미국 + 한국 종목 통합 반환 (us_tickers, kr_tickers, kr_names)"""

    # ── 미국 종목 (검증된 핵심 종목) ─────────────────────────────
    usa_tickers = [
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","AVGO","COST",
        "NFLX","AMD","QCOM","TMUS","AMAT","INTU","ISRG","TXN","BKNG","TQQQ","SOXL",
        "COIN","HOOD","MSTR","PLTR","MARA","RIOT","CLSK","IONQ","RGTI","SOUN",
        "CRWD","PANW","DDOG","NET","SNOW","PLTR","ARM","SMCI","MU","INTC",
        "JPM","V","MA","BAC","GS","PYPL","AFRM","SOFI","UPST",
        "MRNA","BNTX","NVAX","LLY","PFE","JNJ","ABBV",
        "ENPH","FSLR","NEE","VST","NRG",
        "RKLB","JOBY","ACHR","LUNR","AXON","LHX","LMT","NOC","GD","RTX",
        "DIS","SPOT","SNAP","RBLX","NTES","BIDU",
        "UBER","DASH","ABNB","LYFT",
        "LULU","NKE","ONON","CROX",
        # ── 밈/급등주 (스캘핑 특화) ──────────────────────────────────
        # 밈주 클래식
        "GME","AMC","BB","NOK",
        # EV 밈
        "RIVN","LCID","NKLA","FFIE","PSNY","WKHS",
        # 중국 EV (변동성 극강)
        "NIO","XPEV","LI",
        # AI 밈
        "BBAI","ASTS","RCAT","WOLF","OPEN",
        # 레버리지 ETF (단타 필수템)
        "TQQQ","SOXL","UVXY","LABU","FNGU","TNA","SPXL",
        # 단타 바이오
        "NVAX","SAVA","ACAD","SRPT","VKTX",
    ]
    usa_tickers = list(dict.fromkeys(usa_tickers))
    print(f"  미국 종목: {len(usa_tickers)}개")

    # ── 한국 종목 (pykrx - 시총 상위 자동 추출) ──────────────────
    # ── 한국 종목 (시총 상위 하드코딩 - KOSPI 40 + KOSDAQ 10) ──────────
    kr_names = {
        # KOSPI 상위 40
        "005930.KS":"삼성전자",   "000660.KS":"SK하이닉스",  "005380.KS":"현대차",
        "005490.KS":"POSCO홀딩스","035420.KS":"NAVER",       "051910.KS":"LG화학",
        "006400.KS":"삼성SDI",    "035720.KS":"카카오",       "000270.KS":"기아",
        "003550.KS":"LG",         "028260.KS":"삼성물산",     "066570.KS":"LG전자",
        "096770.KS":"SK이노베이션","017670.KS":"SK텔레콤",    "030200.KS":"KT",
        "086790.KS":"하나금융지주","105560.KS":"KB금융",      "055550.KS":"신한지주",
        "032830.KS":"삼성생명",    "018260.KS":"삼성에스디에스","009150.KS":"삼성전기",
        "010950.KS":"S-Oil",       "011200.KS":"HMM",         "012330.KS":"현대모비스",
        "034020.KS":"두산에너빌리티","316140.KS":"우리금융지주","024110.KS":"기업은행",
        "000810.KS":"삼성화재",    "139480.KS":"이마트",       "090430.KS":"아모레퍼시픽",
        "011070.KS":"LG이노텍",    "047050.KS":"포스코인터내셔널","003670.KS":"포스코퓨처엠",
        "207940.KS":"삼성바이오로직스","068270.KS":"셀트리온",  "000100.KS":"유한양행",
        "373220.KS":"LG에너지솔루션","267250.KS":"HD현대",     "042660.KS":"한화오션",
        "329180.KS":"HD현대중공업", "009830.KS":"한화솔루션",
        # KOSDAQ 상위 10
        "247540.KQ":"에코프로비엠", "086520.KQ":"에코프로",    "196170.KQ":"알테오젠",
        "058470.KQ":"리노공업",     "039030.KQ":"이오테크닉스", "357780.KQ":"솔브레인",
        "145020.KQ":"휴젤",         "091990.KQ":"셀트리온헬스케어","263750.KQ":"펄어비스",
        "122870.KQ":"와이지엔터테인먼트",
    }
    kr_tickers = list(kr_names.keys())
    print(f"  한국 종목: {len(kr_tickers)}개 (KOSPI 40 + KOSDAQ 10)")

    return usa_tickers, kr_tickers, kr_names

def calc_obv(close, volume):
    """OBV 벡터 계산"""
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()

def check_batch(tickers, market, name_map=None, interval="15m"):
    """종목별 개별 다운로드로 돌파 조건 체크"""
    signals = []

    for sym in tickers:
        try:
            df = yf.download(
                sym,
                interval=interval,
                period="3d",
                auto_adjust=True,
                progress=False,
            )
            if df is None or len(df) == 0:
                continue
            # 컬럼이 MultiIndex인 경우 단일 레벨로 변환
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(how="all")
            time.sleep(0.2)  # Rate limit 방지

            if df is None or len(df) < LOOKBACK + 3:
                continue

            close  = df["Close"].dropna()
            volume = df["Volume"].dropna()
            high   = df["High"].dropna()

            if len(close) < LOOKBACK + 3:
                continue

            cur_price = float(close.iloc[-1])
            cur_vol   = float(volume.iloc[-1])

            # 최소 조건 필터
            if market == "KR":
                if cur_price < MIN_PRICE_KR or cur_vol < MIN_VOL_KR:
                    continue
            else:
                if cur_price < MIN_PRICE_US or cur_vol < MIN_VOL_US:
                    continue

            # ── OBV / 거래량MA / SMA / RSI 계산 ──
            obv     = calc_obv(close, volume)
            obv_ema = obv.ewm(span=OBV_PERIOD, adjust=False).mean()
            vol_ma  = volume.rolling(LOOKBACK).mean()
            sma     = close.rolling(LOOKBACK).mean()

            # RSI(14)
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rsi   = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

            # ── 조건 1: crossover(close, highest(high[1], lookback)) ──
            # high[1] = 1봉 전부터 lookback개 봉의 최고가 (현재봉 제외)
            prev_high_max  = high.shift(1).rolling(LOOKBACK).max()
            cur_prev_high  = float(prev_high_max.iloc[-1])   # 현재봉 기준 이전 최고가
            prev_prev_high = float(prev_high_max.iloc[-2])   # 1봉 전 기준 이전 최고가
            prev_close     = float(close.iloc[-2])

            # crossover = 현재봉 close가 위로 교차 (이전봉은 아래였음)
            cond1 = (cur_price > cur_prev_high) and (prev_close <= prev_prev_high)

            if not cond1:
                continue

            # ── 조건 2: volume > vol_ma * vol_multiplier ──
            avg_vol   = float(vol_ma.iloc[-1])
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0
            cond2     = vol_ratio > VOL_MULT

            if not cond2:
                continue

            # ── 조건 3: OBV > OBV EMA ──
            cond3 = float(obv.iloc[-1]) > float(obv_ema.iloc[-1])

            if not cond3:
                continue

            # ── 매집 구간 체크 (추가 정보) ──
            obv_rising = all(obv.iloc[-i] > obv.iloc[-i-1] for i in range(1, 4))
            highest_lb = float(high.iloc[-LOOKBACK:].max())
            is_accum   = obv_rising and cur_price < highest_lb * 0.99

            cur_rsi = float(rsi.iloc[-1]) if not np.isnan(float(rsi.iloc[-1])) else 0

            # ── 3개 조건 모두 충족! ──
            name = name_map.get(sym, sym) if name_map else sym
            signals.append({
                "sym":          sym,
                "name":         name,
                "market":       market,
                "interval":     interval,
                "price":        cur_price,
                "high_15":      cur_prev_high,
                "vol_ratio":    vol_ratio,
                "obv":          float(obv.iloc[-1]),
                "obv_ema":      float(obv_ema.iloc[-1]),
                "rsi":          cur_rsi,
                "is_accum":     is_accum,
            })

        except Exception:
            continue

    return signals

def send_alerts(signals, interval, now_str):
    """신호 텔레그램 발송 - 시장별 분리 (최대 10개씩)"""
    kr_sigs = [s for s in signals if s["market"] == "KR"]
    us_sigs = [s for s in signals if s["market"] == "US"]

    for market, sigs in [("KR", kr_sigs), ("US", us_sigs)]:
        if not sigs:
            continue
        for i in range(0, len(sigs), MAX_ALERTS):
            chunk = sigs[i:i+MAX_ALERTS]
            if market == "KR":
                header = f"🇰🇷 <b>국내장 단타 적극추천!</b> [{interval}봉] ({now_str})"
            else:
                header = f"🇺🇸 <b>미국장 단타 적극추천!</b> [{interval}봉] ({now_str})"

            msg  = f"{header}\n"
            msg += f"━━━━━━━━━━━━━━━━━\n\n"

            for s in chunk:
                price = f"{s['price']:,.0f}원" if market == "KR" else f"${s['price']:.2f}"
                high  = f"{s['high_15']:,.0f}원" if market == "KR" else f"${s['high_15']:.2f}"
                accum = " 🟢매집" if s.get("is_accum") else ""
                msg  += f"<b>{s['name']}</b> ({s['sym']}){accum}\n"
                msg  += f"  💰 현재가: <b>{price}</b>\n"
                msg  += f"  ✅ 돌파: {high} 돌파\n"
                msg  += f"  🔥 거래량: {s['vol_ratio']:.1f}배↑\n"
                msg  += f"  📊 RSI: {s.get('rsi', 0):.1f}\n\n"

            msg += "⚡ 손절선 설정 필수! ⚠️ 투자 책임은 본인에게 있습니다."
            ok = send(msg)
        print(f"  알람 전송 {'OK' if ok else 'FAIL'}: {[s['name'] for s in chunk]}")
        time.sleep(1)

def is_kr_market_open(now_kst):
    """한국장 시간 체크 (09:00~15:30)"""
    h, m = now_kst.hour, now_kst.minute
    return (h == 9 and m >= 0) or (10 <= h <= 14) or (h == 15 and m <= 30)

def is_us_market_open(now_kst):
    """미국장 운영 시간 체크 (KST 기준)
    프리마켓:  월~금 17:00 ~ 22:30 KST
    정규장:    월~금 22:30 ~ 05:00 KST (다음날)
    애프터마켓: 화~토 05:00 ~ 09:00 KST
    완전 휴장: 토 09:00 ~ 일 17:00 KST
    """
    weekday = now_kst.weekday()  # 0=월 ... 6=일
    h, m    = now_kst.hour, now_kst.minute

    # 토요일 09:00 이후 ~ 일요일 16:59 → 완전 휴장
    if weekday == 5 and h >= 9:
        return False
    if weekday == 6 and h < 17:
        return False

    return True  # 그 외 시간은 프리/정규/애프터 운영

def run():
    kst     = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    now_str = now_kst.strftime("%m/%d %H:%M KST")
    weekday = now_kst.weekday()

    print(f"=== {now_str} 전종목 돌파 스캔 시작 ===")

    kr_open = (weekday < 5) and is_kr_market_open(now_kst)
    us_open = is_us_market_open(now_kst)

    if not us_open:
        print("주말 미국장 휴장 - 스킵 (토 09:00 ~ 일 17:00 KST)")

    # ── 종목 로드 (1회) ──────────────────────────────────────────────
    print("\n[종목 로드 중...]")
    us_tickers, kr_tickers, kr_names = get_all_tickers()

    all_signals = []

    # ── 한국장 스캔 (09:00~15:30만) ──────────────────────────────────
    if kr_open:
        print(f"\n[한국 종목 스캔] {len(kr_tickers)}개 (KOSPI+KOSDAQ 시총 상위)")
        for interval in INTERVALS:
            print(f"  {interval}봉 체크중...")
            for i in range(0, len(kr_tickers), BATCH_SIZE):
                batch = kr_tickers[i:i+BATCH_SIZE]
                sigs  = check_batch(batch, "KR", kr_names, interval)
                if sigs:
                    all_signals.extend(sigs)
                    print(f"    신호: {[s['name'] for s in sigs]}")
                time.sleep(0.5)
    else:
        print("\n[한국장] 장외시간 스킵 (09:00~15:30만 운영)")

    # ── 미국장 스캔 (휴장 시간 제외) ────────────────────────────────────
    if us_open:
        print(f"\n[미국 종목 스캔] {len(us_tickers)}개")
    else:
        print("\n[미국장] 휴장 스킵")

    us_names = {t: t for t in us_tickers}
    if us_open:
        for interval in INTERVALS:
            print(f"  {interval}봉 체크중...")
            for i in range(0, len(us_tickers), BATCH_SIZE):
                batch = us_tickers[i:i+BATCH_SIZE]
                sigs  = check_batch(batch, "US", us_names, interval)
                if sigs:
                    all_signals.extend(sigs)
                    print(f"    신호: {[s['name'] for s in sigs]}")
                time.sleep(0.5)

    # ── 중복 제거 (같은 종목 15m/30m 동시 신호) ──────────────────────
    seen = set()
    unique_signals = []
    for s in all_signals:
        key = (s["sym"], s["interval"])
        if key not in seen:
            seen.add(key)
            unique_signals.append(s)

    print(f"\n총 신호: {len(unique_signals)}개")

    if not unique_signals:
        print("신호 없음 - 알람 미발송")
        return

    # 봉 단위별 알람 발송
    for interval in INTERVALS:
        sigs = [s for s in unique_signals if s["interval"] == interval]
        if sigs:
            send_alerts(sigs, interval, now_str)
            print(f"  알람 발송: {[s['name'] for s in sigs]}")

    print("=== 스캔 완료 ===")

if __name__ == "__main__":
    run()
