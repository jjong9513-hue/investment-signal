# signal_momentum_us.py
# 미국 급등주 실시간 스캐너 (1분봉/5분봉)
# 야후 파이낸스 거래량 상위 50종목 실시간 스캔 → 별도 텔레그램 알람

import yfinance as yf
import pandas as pd
import numpy as np
import requests, os, sys, time
from datetime import datetime, timezone, timedelta

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8386728044:AAH27uG-7OWKlQG4Nr97sJli6Wnjes_wcvw")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "936157775")

# ── 설정값 ─────────────────────────────────────────
LOOKBACK  = 10     # 기준 봉 수 (1분봉 10개 = 최근 10분)
VOL_MULT  = 5.0    # 거래량 5배 이상 급등
INTERVALS = ["1m", "5m"]
MIN_PRICE = 2.0    # 최소 주가 ($)
MIN_VOL   = 50000  # 1분봉 최소 거래량

# ── 텔레그램 ────────────────────────────────────────
def send(msg):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
        timeout=15
    )
    return r.status_code == 200

# ── 야후 파이낸스 거래량 상위 50종목 ─────────────────
def get_most_active_tickers():
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
        params = {
            "scrIds": "most_actives",
            "count":  50,
            "region": "US",
            "lang":   "en-US",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":     "application/json",
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data   = r.json()
        quotes = data["finance"]["result"][0]["quotes"]
        tickers = [q["symbol"] for q in quotes]
        print(f"  야후 거래량 상위: {len(tickers)}개 → {tickers[:5]}...")
        return tickers
    except Exception as e:
        print(f"  ⚠️ 거래량 상위 로드 실패: {e} → fallback 사용")
        return [
            "GME","AMC","NVDA","AMD","TSLA","AAPL","MSFT","META","AMZN",
            "COIN","MSTR","MARA","RIOT","CLSK","SOXL","TQQQ","UVXY",
            "PLTR","HOOD","SOFI","RIVN","LCID","NIO","XPEV","LI",
            "BBAI","ASTS","RCAT","SOUN","IONQ","RGTI",
            "GME","AMC","BB","NKLA","FFIE",
        ]

# ── OBV 계산 ────────────────────────────────────────
def calc_obv(close, volume):
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()

# ── 급등 조건 체크 ───────────────────────────────────
def check_momentum(tickers, interval="1m"):
    signals = []
    period  = "1d" if interval == "1m" else "2d"

    for sym in tickers:
        try:
            df = yf.download(
                sym,
                interval=interval,
                period=period,
                auto_adjust=True,
                progress=False,
            )
            if df is None or len(df) == 0:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(how="all")
            time.sleep(0.2)

            if len(df) < LOOKBACK + 3:
                continue

            close  = df["Close"].dropna()
            volume = df["Volume"].dropna()
            high   = df["High"].dropna()

            if len(close) < LOOKBACK + 3:
                continue

            cur_price = float(close.iloc[-1])
            cur_vol   = float(volume.iloc[-1])

            if cur_price < MIN_PRICE or cur_vol < MIN_VOL:
                continue

            # ── 조건 1: 거래량 VOL_MULT배 이상 급등 ──────────────
            vol_ma    = volume.rolling(LOOKBACK).mean()
            avg_vol   = float(vol_ma.iloc[-1])
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0
            if vol_ratio <= VOL_MULT:
                continue

            # ── 조건 2: 가격 돌파 crossover ──────────────────────
            prev_high_max  = high.shift(1).rolling(LOOKBACK).max()
            cur_prev_high  = float(prev_high_max.iloc[-1])
            prev_prev_high = float(prev_high_max.iloc[-2])
            prev_close     = float(close.iloc[-2])
            cond2 = (cur_price > cur_prev_high) and (prev_close <= prev_prev_high)
            if not cond2:
                continue

            # ── 조건 3: OBV > OBV EMA ─────────────────────────
            obv     = calc_obv(close, volume)
            obv_ema = obv.ewm(span=10, adjust=False).mean()
            if float(obv.iloc[-1]) <= float(obv_ema.iloc[-1]):
                continue

            # ── RSI 계산 (참고용) ──────────────────────────────
            delta   = close.diff()
            gain    = delta.clip(lower=0).rolling(14).mean()
            loss    = (-delta.clip(upper=0)).rolling(14).mean()
            rsi     = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
            cur_rsi = float(rsi.iloc[-1]) if not np.isnan(float(rsi.iloc[-1])) else 0

            # ── 3조건 모두 충족! ───────────────────────────────
            signals.append({
                "sym":       sym,
                "interval":  interval,
                "price":     cur_price,
                "high_lb":   cur_prev_high,
                "vol_ratio": vol_ratio,
                "rsi":       cur_rsi,
            })

        except Exception:
            continue

    return signals

# ── 텔레그램 알람 ────────────────────────────────────
def send_momentum_alert(signals, interval, now_str):
    msg  = f"<b>🔥 급등 스캘핑 신호!</b> [{interval}봉] ({now_str})\n"
    msg += f"━━━━━━━━━━━━━━━━━\n"
    msg += f"⚡ 거래량 폭발 + 가격 돌파!\n\n"

    for s in signals:
        msg += f"🇺🇸 <b>{s['sym']}</b>\n"
        msg += f"  현재가: <b>${s['price']:.2f}</b>\n"
        msg += f"  ✅ 돌파: ${s['high_lb']:.2f} 돌파\n"
        msg += f"  🔥 거래량: {s['vol_ratio']:.1f}배 폭발\n"
        msg += f"  📊 RSI: {s['rsi']:.1f}\n\n"

    msg += "⚡ 스캘핑 주의! 손절선 필수! ⚠️"
    ok   = send(msg)
    print(f"  급등 알람 {'OK' if ok else 'FAIL'}: {[s['sym'] for s in signals]}")
    time.sleep(1)

# ── 메인 ─────────────────────────────────────────────
def run_momentum():
    kst     = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    now_str = now_kst.strftime("%m/%d %H:%M KST")
    weekday = now_kst.weekday()

    print(f"\n=== [🔥 급등 스캐너] {now_str} ===")

    # 주말 미국장 없으면 스킵 (토요일 새벽 ~ 일요일 저녁)
    # 미국장: 월~금 22:30~05:00 KST (정규), 17:00~22:30 KST (프리)
    # 주말에도 프리/애프터 없으므로 토/일 스킵
    if weekday >= 5:
        h = now_kst.hour
        # 일요일 17:00 이후부터는 프리마켓 시작
        if not (weekday == 6 and h >= 17):
            print("  주말 - 미국장 없음 스킵")
            return

    # 거래량 상위 종목 로드
    tickers = get_most_active_tickers()

    all_signals = []
    for interval in INTERVALS:
        print(f"  {interval}봉 체크중... ({len(tickers)}개)")
        sigs = check_momentum(tickers, interval)
        if sigs:
            all_signals.extend(sigs)
            print(f"    신호: {[s['sym'] for s in sigs]}")
        time.sleep(0.5)

    # 중복 제거
    seen   = set()
    unique = []
    for s in all_signals:
        key = (s["sym"], s["interval"])
        if key not in seen:
            seen.add(key)
            unique.append(s)

    print(f"  급등 신호: {len(unique)}개")

    if not unique:
        print("  급등 신호 없음 - 알람 미발송")
        return

    for interval in INTERVALS:
        sigs = [s for s in unique if s["interval"] == interval]
        if sigs:
            send_momentum_alert(sigs, interval, now_str)

    print("=== 급등 스캔 완료 ===")

if __name__ == "__main__":
    run_momentum()
