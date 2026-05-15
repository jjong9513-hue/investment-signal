# signal_breakout_full.py
# NASDAQ 전종목 + KOSDAQ 전종목 돌파 신호 스캐너
# 3가지 조건 모두 충족 시에만 텔레그램 알람

import yfinance as yf
import pandas as pd
import numpy as np
import requests, os, sys, time, re
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import FinanceDataReader as fdr

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8386728044:AAH27uG-7OWKlQG4Nr97sJli6Wnjes_wcvw")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "936157775")

# ── 설정값 ─────────────────────────────────────────
LOOKBACK   = 15    # 기준 봉 수
VOL_MULT   = 1.5   # 거래량 배수 기준
OBV_PERIOD = 20    # OBV EMA 기간
INTERVALS  = ["15m", "30m"]
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

def get_nasdaq_tickers():
    """NASDAQ 전종목 리스트 가져오기"""
    print("NASDAQ 종목 리스트 수집중...")

    # 방법 1: FinanceDataReader (KOSDAQ과 동일한 방식)
    try:
        df = fdr.StockListing('NASDAQ')
        tickers = []
        for _, row in df.iterrows():
            sym = str(row.get('Symbol', row.get('Code', ''))).strip()
            if sym and re.match(r'^[A-Z]{1,5}$', sym):
                tickers.append(sym)
        if len(tickers) > 100:
            print(f"  NASDAQ 종목 (FDR): {len(tickers)}개")
            return tickers
        else:
            raise ValueError(f"종목 수 부족: {len(tickers)}개")
    except Exception as e:
        print(f"  FDR 오류: {e}")

    # 방법 2: NASDAQ FTP (타임아웃 10초)
    try:
        import urllib.request
        url = "https://ftp.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode('utf-8')
        import io
        df = pd.read_csv(io.StringIO(content), sep="|")
        df = df[df["Market Category"] != ""].copy()
        df = df[df["Symbol"].str.match(r'^[A-Z]+$', na=False)]
        df = df[df["ETF"] != "Y"]
        tickers = df["Symbol"].tolist()
        if len(tickers) > 100:
            print(f"  NASDAQ 종목 (FTP): {len(tickers)}개")
            return tickers
        else:
            raise ValueError(f"종목 수 부족: {len(tickers)}개")
    except Exception as e:
        print(f"  FTP 오류: {e}")

    # 방법 3: GitHub 호스팅 CSV
    try:
        url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_tickers.txt"
        df = pd.read_csv(url, header=None, names=["Symbol"])
        tickers = [s.strip() for s in df["Symbol"].tolist()
                   if re.match(r'^[A-Z]{1,5}$', str(s).strip())]
        if len(tickers) > 100:
            print(f"  NASDAQ 종목 (GitHub CSV): {len(tickers)}개")
            return tickers
        else:
            raise ValueError(f"종목 수 부족: {len(tickers)}개")
    except Exception as e:
        print(f"  GitHub CSV 오류: {e}")

    # 최후 백업: S&P500 + 주요 NASDAQ 종목
    print("  ⚠️ 모든 방법 실패 - 주요 종목 100개로 대체")
    return [
        "NVDA","TSLA","META","AAPL","AMD","MSTR","SMCI","RIOT","SOUN","RKLB",
        "MSFT","GOOGL","AMZN","NFLX","INTC","QCOM","AVGO","MU","AMAT","LRCX",
        "PLTR","ARM","HOOD","COIN","MARA","CLSK","CIFR","IREN","BITF","HUT",
        "IONQ","RGTI","QUBT","QBTS","ARQQ","LUNR","RCAT","JOBY","ACHR","LILM",
        "CRWD","PANW","ZS","OKTA","NET","SNOW","DDOG","MDB","GTLB","HUBS",
        "CELH","SMST","AXON","ONON","DECK","LULU","NKE","UAA","SKX","CROX",
        "ENPH","FSLR","SEDG","CSIQ","RUN","PLUG","BLDP","FCEL","BE","NOVA",
        "MRNA","BNTX","NVAX","VRTX","REGN","BIIB","ILMN","PACB","RXRX","BEAM",
        "UBER","LYFT","DASH","ABNB","BKNG","EXPE","TRIP","PCLN","OPEN","RDFN",
        "SOFI","UPST","AFRM","LC","OPFI","DAVE","MQ","PAYO","FOUR","FLYW"
    ]

def get_kosdaq_tickers():
    """KOSDAQ 전종목 리스트 가져오기"""
    print("KOSDAQ 종목 리스트 수집중...")
    try:
        df = fdr.StockListing('KOSDAQ')
        # 종목코드에 .KQ 붙이기 (yfinance 형식)
        tickers = []
        names   = {}
        for _, row in df.iterrows():
            code = str(row.get('Code', row.get('Symbol', ''))).zfill(6)
            name = str(row.get('Name', row.get('ISU_ABBRV', code)))
            sym  = f"{code}.KQ"
            tickers.append(sym)
            names[sym] = name
        print(f"  KOSDAQ 종목: {len(tickers)}개")
        return tickers, names
    except Exception as e:
        print(f"  KOSDAQ 리스트 오류: {e}")
        return [], {}

def get_kospi_tickers():
    """KOSPI 전종목 리스트 가져오기 (토스증권 지원)"""
    print("KOSPI 종목 리스트 수집중...")
    try:
        df = fdr.StockListing('KOSPI')
        tickers = []
        names   = {}
        for _, row in df.iterrows():
            code = str(row.get('Code', row.get('Symbol', ''))).zfill(6)
            name = str(row.get('Name', row.get('ISU_ABBRV', code)))
            sym  = f"{code}.KS"
            tickers.append(sym)
            names[sym] = name
        print(f"  KOSPI 종목: {len(tickers)}개")
        return tickers, names
    except Exception as e:
        print(f"  KOSPI 리스트 오류: {e}")
        return [], {}

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

            # ── 조건 1: 현재가 > 이전 15봉 최고가 (신규 돌파) ──
            prev_15_high    = float(high.iloc[-(LOOKBACK+1):-1].max())
            prev_prev_close = float(close.iloc[-2])
            cond1 = cur_price > prev_15_high
            new_break = prev_prev_close <= float(high.iloc[-(LOOKBACK+2):-2].max()) if len(high) > LOOKBACK+2 else True

            if not (cond1 and new_break):
                continue

            # ── 조건 2: 현재 거래량 > 15봉 평균 × 1.5 ──
            avg_vol   = float(volume.iloc[-(LOOKBACK+1):-1].mean())
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0
            cond2 = vol_ratio > VOL_MULT

            if not cond2:
                continue

            # ── 조건 3: OBV > OBV EMA ──
            obv     = calc_obv(close, volume)
            obv_ema = obv.ewm(span=OBV_PERIOD, adjust=False).mean()
            cond3   = float(obv.iloc[-1]) > float(obv_ema.iloc[-1])

            if not cond3:
                continue

            # ── 3개 모두 충족! ──
            name = name_map.get(sym, sym) if name_map else sym
            signals.append({
                "sym":       sym,
                "name":      name,
                "market":    market,
                "interval":  interval,
                "price":     cur_price,
                "high_15":   prev_15_high,
                "vol_ratio": vol_ratio,
                "obv":       float(obv.iloc[-1]),
                "obv_ema":   float(obv_ema.iloc[-1]),
            })

        except Exception:
            continue

    return signals

def send_alerts(signals, interval, now_str):
    """신호 텔레그램 발송 (최대 10개씩)"""
    for i in range(0, len(signals), MAX_ALERTS):
        chunk = signals[i:i+MAX_ALERTS]
        flag_map = {"KR": "🇰🇷", "US": "🇺🇸"}
        msg = f"<b>🚀 돌파 매수 신호!</b> [{interval}봉] ({now_str})\n"
        msg += f"━━━━━━━━━━━━━━━━━\n"
        msg += f"✅ 3가지 조건 모두 충족 종목\n\n"

        for s in chunk:
            flag  = flag_map.get(s["market"], "")
            price = f"{s['price']:,.0f}원" if s["market"] == "KR" else f"${s['price']:.2f}"
            high  = f"{s['high_15']:,.0f}원" if s["market"] == "KR" else f"${s['high_15']:.2f}"
            msg  += f"{flag} <b>{s['name']}</b> ({s['sym']})\n"
            msg  += f"  현재가: <b>{price}</b>\n"
            msg  += f"  ✅ 가격돌파: {price} > {high}\n"
            msg  += f"  ✅ 거래량:   {s['vol_ratio']:.2f}배 (기준 {VOL_MULT}배)\n"
            msg  += f"  ✅ OBV:      EMA 상회 중\n\n"

        msg += "⚡ 손절선 설정 필수! ⚠️ 투자 책임은 본인에게 있습니다."
        ok = send(msg)
        print(f"  알람 전송 {'OK' if ok else 'FAIL'}: {[s['name'] for s in chunk]}")
        time.sleep(1)

def is_kr_market_open(now_kst):
    """한국장 시간 체크 (09:00~15:30)"""
    h, m = now_kst.hour, now_kst.minute
    return (h == 9 and m >= 0) or (10 <= h <= 14) or (h == 15 and m <= 30)

def is_us_market_open(now_kst):
    """미국장+프리마켓+애프터마켓 체크 (05:00~09:00 애프터, 17:00~05:00 프리+정규)"""
    h = now_kst.hour
    # 정규장: 22:30~05:00 KST / 프리마켓: 17:00~22:30 KST / 애프터마켓: 05:00~09:00 KST
    return True  # 24시간 - 데이터 없으면 자동으로 신호 없음

def run():
    kst     = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    now_str = now_kst.strftime("%m/%d %H:%M KST")
    weekday = now_kst.weekday()

    print(f"=== {now_str} 전종목 돌파 스캔 시작 ===")

    if weekday >= 5:
        print("주말 - 스킵")
        return

    kr_open = is_kr_market_open(now_kst)
    # 미국은 24시간 스캔 (프리마켓/정규/애프터마켓 포함)
    us_open = True

    all_signals = []

    # ── KOSPI + KOSDAQ 스캔 (한국장 09:00~15:30만) ──────────────────────────
    if kr_open:
        print("\n[KOSPI 전종목 스캔] (토스증권 지원)")
        kospi_tickers, kospi_names = get_kospi_tickers()
        for interval in INTERVALS:
            print(f"  {interval}봉 체크중...")
            for i in range(0, len(kospi_tickers), BATCH_SIZE):
                batch = kospi_tickers[i:i+BATCH_SIZE]
                sigs  = check_batch(batch, "KR", kospi_names, interval)
                if sigs:
                    all_signals.extend(sigs)
                    print(f"    신호: {[s['name'] for s in sigs]}")
                time.sleep(0.5)

        print("\n[KOSDAQ 전종목 스캔] (토스증권 지원)")
        kosdaq_tickers, kosdaq_names = get_kosdaq_tickers()
        for interval in INTERVALS:
            print(f"  {interval}봉 체크중...")
            for i in range(0, len(kosdaq_tickers), BATCH_SIZE):
                batch = kosdaq_tickers[i:i+BATCH_SIZE]
                sigs  = check_batch(batch, "KR", kosdaq_names, interval)
                if sigs:
                    all_signals.extend(sigs)
                    print(f"    신호: {[s['name'] for s in sigs]}")
                time.sleep(0.5)
    else:
        print("\n[한국장] 장외시간 스킵 (09:00~15:30만 운영)")

    # ── NASDAQ 스캔 (24시간 - 프리마켓/정규/애프터마켓) ──────────────────────────────────
    print("\n[NASDAQ 전종목 스캔] (24시간)")
    nasdaq_tickers = get_nasdaq_tickers()
    nasdaq_names   = {t: t for t in nasdaq_tickers}
    for interval in INTERVALS:
        print(f"  {interval}봉 체크중...")
        for i in range(0, len(nasdaq_tickers), BATCH_SIZE):
            batch = nasdaq_tickers[i:i+BATCH_SIZE]
            sigs  = check_batch(batch, "US", nasdaq_names, interval)
            if sigs:
                all_signals.extend(sigs)
                print(f"    신호: {[s['name'] for s in sigs]}")
            time.sleep(0.5)

    # ── 중복 제거 (같은 종목 15m/30m 동시 신호) ──────
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

    # 15분봉 / 30분봉 분리해서 발송
    for interval in INTERVALS:
        sigs = [s for s in unique_signals if s["interval"] == interval]
        if sigs:
            send_alerts(sigs, interval, now_str)

    print("=== 스캔 완료 ===")

if __name__ == "__main__":
    run()
