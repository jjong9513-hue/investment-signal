# signal_breakout.py
# 데이트레이딩 돌파 신호 감지 (15분/30분봉)
# 3가지 조건 모두 충족 시에만 텔레그램 알람 발송

import yfinance as yf
import pandas as pd
import numpy as np
import requests, os, sys
from datetime import datetime, timezone, timedelta

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8386728044:AAH27uG-7OWKlQG4Nr97sJli6Wnjes_wcvw")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "936157775")

# ── 설정값 (수정 가능) ────────────────────────────────
LOOKBACK    = 15    # 기준 봉 수
VOL_MULT    = 1.5   # 거래량 배수
OBV_PERIOD  = 20    # OBV EMA 기간
INTERVALS   = ["15m", "30m"]  # 체크할 봉 단위

# ── 종목 리스트 ───────────────────────────────────────
STOCKS_KR = [
    ("005930.KS", "삼성전자",       "KR"),
    ("000660.KS", "SK하이닉스",     "KR"),
    ("005380.KS", "현대차",         "KR"),
    ("051910.KS", "LG화학",         "KR"),
    ("035420.KS", "NAVER",          "KR"),
    ("042700.KS", "한미반도체",     "KR"),
    ("247540.KS", "에코프로비엠",   "KR"),
    ("034020.KS", "두산에너빌리티", "KR"),
    ("352820.KS", "하이브",         "KR"),
    ("196170.KS", "알테오젠",       "KR"),
]

STOCKS_US = [
    ("NVDA",  "엔비디아",           "US"),
    ("TSLA",  "테슬라",             "US"),
    ("META",  "메타",               "US"),
    ("AAPL",  "애플",               "US"),
    ("AMD",   "AMD",                "US"),
    ("MSTR",  "마이크로스트래티지", "US"),
    ("SMCI",  "슈퍼마이크로",       "US"),
    ("RIOT",  "라이엇플랫폼",       "US"),
    ("SOUN",  "사운드하운드",       "US"),
    ("RKLB",  "로켓랩",             "US"),
]

def send(msg):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
        timeout=15
    )
    print("전송:", "OK" if r.status_code == 200 else r.text[:80])

def calc_obv(df):
    """OBV 계산"""
    obv = [0]
    for i in range(1, len(df)):
        if df["Close"].iloc[i] > df["Close"].iloc[i-1]:
            obv.append(obv[-1] + df["Volume"].iloc[i])
        elif df["Close"].iloc[i] < df["Close"].iloc[i-1]:
            obv.append(obv[-1] - df["Volume"].iloc[i])
        else:
            obv.append(obv[-1])
    return pd.Series(obv, index=df.index)

def check_signal(sym, name, market, interval):
    """3개 조건 체크 - 모두 충족 시 True 반환"""
    try:
        ticker = yf.Ticker(sym)
        df = ticker.history(period="5d", interval=interval)

        if df is None or len(df) < LOOKBACK + 2:
            return False, {}

        # ── 현재봉 vs 이전봉 ──
        cur  = df.iloc[-1]   # 현재 봉
        prev = df.iloc[-2]   # 직전 봉
        lookback_candles = df.iloc[-(LOOKBACK+1):-1]  # 이전 15봉

        # ── 조건 1: 현재 종가 > 이전 15봉 최고가 ──
        high_15    = lookback_candles["High"].max()
        prev_high  = df.iloc[-(LOOKBACK+2):-2]["High"].max() if len(df) >= LOOKBACK+2 else high_15
        cond1      = cur["Close"] > high_15
        # 신규 돌파 확인 (이전 봉은 돌파 전이어야 함)
        new_break  = prev["Close"] <= prev_high

        # ── 조건 2: 현재 거래량 > 이전 15봉 평균 거래량 × 1.5 ──
        avg_vol  = lookback_candles["Volume"].mean()
        vol_ratio = cur["Volume"] / avg_vol if avg_vol > 0 else 0
        cond2    = vol_ratio > VOL_MULT

        # ── 조건 3: OBV > OBV EMA ──
        obv     = calc_obv(df)
        obv_ema = obv.ewm(span=OBV_PERIOD, adjust=False).mean()
        cond3   = float(obv.iloc[-1]) > float(obv_ema.iloc[-1])

        all_ok = cond1 and cond2 and cond3 and new_break

        details = {
            "price":    float(cur["Close"]),
            "high_15":  float(high_15),
            "vol":      int(cur["Volume"]),
            "avg_vol":  int(avg_vol),
            "vol_ratio":vol_ratio,
            "obv":      float(obv.iloc[-1]),
            "obv_ema":  float(obv_ema.iloc[-1]),
            "cond1":    cond1,
            "cond2":    cond2,
            "cond3":    cond3,
            "new_break":new_break,
        }
        return all_ok, details

    except Exception as e:
        print(f"  [{sym}] 오류: {e}")
        return False, {}

def fmt_price(price, market):
    return f"{price:,.0f}원" if market == "KR" else f"${price:.2f}"

def run():
    kst    = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    now_str = now_kst.strftime("%m/%d %H:%M KST")
    weekday = now_kst.weekday()  # 0=월 ~ 6=일

    print(f"=== {now_str} 돌파 신호 체크 시작 ===")

    # 주말 스킵
    if weekday >= 5:
        print("주말 - 스킵")
        return

    signals_found = []

    all_stocks = STOCKS_KR + STOCKS_US
    for sym, name, market in all_stocks:
        print(f"  {name} 체크중...")
        for interval in INTERVALS:
            ok, d = check_signal(sym, name, market, interval)
            if ok:
                signals_found.append({
                    "sym": sym, "name": name, "market": market,
                    "interval": interval, "d": d
                })
                print(f"  ★ {name} [{interval}] 신호 발생!")

    # ── 신호 없으면 조용히 종료 ──
    if not signals_found:
        print("신호 없음 - 알람 미발송")
        return

    # ── 신호 있으면 텔레그램 발송 ──
    msg = f"<b>🚀 돌파 매수 신호!</b> ({now_str})\n"
    msg += "━━━━━━━━━━━━━━━━━\n"
    msg += "<b>3가지 조건 모두 충족!</b>\n\n"

    for s in signals_found:
        d   = s["d"]
        flag = "🇰🇷" if s["market"] == "KR" else "🇺🇸"
        price_str = fmt_price(d["price"], s["market"])

        msg += f"{flag} <b>{s['name']}</b> [{s['interval']}봉]\n"
        msg += f"  현재가: <b>{price_str}</b>\n"
        msg += f"  ✅ 조건1 가격돌파: {fmt_price(d['price'], s['market'])} > {fmt_price(d['high_15'], s['market'])} (15봉 최고)\n"
        msg += f"  ✅ 조건2 거래량:   {d['vol_ratio']:.2f}배 (기준 {VOL_MULT}배 초과)\n"
        msg += f"  ✅ 조건3 OBV:      {d['obv']:,.0f} > EMA {d['obv_ema']:,.0f}\n"
        msg += "\n"

    msg += "⚡ 손절선 설정 필수! ⚠️ 투자 책임은 본인에게 있습니다."
    send(msg)
    print(f"=== {len(signals_found)}개 신호 발송 완료 ===")

if __name__ == "__main__":
    run()
