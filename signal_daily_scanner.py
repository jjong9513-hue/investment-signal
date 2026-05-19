# signal_daily_scanner.py
# 한국/미국 단타 추천 일일 스캐너
# 한국장 08:50 KST, 미국장 22:20 KST 자동 발송

import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os, sys, time
from datetime import datetime, timezone, timedelta

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8386728044:AAH27uG-7OWKlQG4Nr97sJli6Wnjes_wcvw")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "936157775")
KST     = timezone(timedelta(hours=9))

# ── 한국 종목 ─────────────────────────────────────────
KR_STOCKS = {
    "005930.KS":"삼성전자",   "000660.KS":"SK하이닉스",  "005380.KS":"현대차",
    "005490.KS":"POSCO홀딩스","035420.KS":"NAVER",       "051910.KS":"LG화학",
    "006400.KS":"삼성SDI",    "035720.KS":"카카오",       "000270.KS":"기아",
    "028260.KS":"삼성물산",    "066570.KS":"LG전자",      "017670.KS":"SK텔레콤",
    "086790.KS":"하나금융지주","105560.KS":"KB금융",      "055550.KS":"신한지주",
    "009150.KS":"삼성전기",    "012330.KS":"현대모비스",   "207940.KS":"삼성바이오로직스",
    "068270.KS":"셀트리온",    "003670.KS":"포스코퓨처엠", "373220.KS":"LG에너지솔루션",
    "042660.KS":"한화오션",    "329180.KS":"HD현대중공업", "267250.KS":"HD현대",
    "247540.KQ":"에코프로비엠","086520.KQ":"에코프로",    "196170.KQ":"알테오젠",
    "058470.KQ":"리노공업",    "039030.KQ":"이오테크닉스", "145020.KQ":"휴젤",
}

# ── 미국 종목 ─────────────────────────────────────────
US_STOCKS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO",
    "AMD","COIN","MSTR","MARA","RIOT","PLTR","HOOD","SOFI",
    "CRWD","PANW","ARM","SMCI","MU","GME","AMC","RIVN",
    "NIO","XPEV","SOXL","TQQQ","UVXY","IONQ","RGTI","SOUN",
    "RKLB","JOBY","ASTS","BBAI","SNAP","RBLX","UBER","DASH",
    "JPM","V","MA","GS","BAC","PYPL","AFRM","UPST",
    "LLY","MRNA","BNTX","ABBV","SRPT","VKTX",
    "ENPH","FSLR","VST","NRG",
    "LMT","RTX","NOC","GD","AXON",
]

# ── 텔레그램 ──────────────────────────────────────────
def send(msg):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=15
        )
        return r.status_code == 200
    except:
        return False

# ── 일일 통계 계산 ────────────────────────────────────
def get_daily_stats(ticker):
    try:
        df = yf.download(ticker, period="10d", interval="1d",
                         auto_adjust=True, progress=False)
        if df is None or len(df) < 2:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(how="all")
        if len(df) < 2:
            return None

        today    = df.iloc[-1]
        prev     = df.iloc[-2]
        avg_vol  = float(df["Volume"].iloc[:-1].mean())

        open_p   = float(today["Open"])
        high_p   = float(today["High"])
        low_p    = float(today["Low"])
        close_p  = float(today["Close"])
        volume   = float(today["Volume"])
        prev_cls = float(prev["Close"])

        if open_p <= 0 or prev_cls <= 0:
            return None

        change_pct = (close_p - prev_cls) / prev_cls * 100
        volatility = (high_p - low_p) / open_p * 100
        day_range  = (high_p - low_p) / prev_cls * 100
        vol_ratio  = volume / avg_vol if avg_vol > 0 else 0

        return {
            "ticker":     ticker,
            "price":      close_p,
            "change_pct": change_pct,
            "volatility": volatility,
            "day_range":  day_range,
            "vol_ratio":  vol_ratio,
        }
    except:
        return None

# ── 뉴스 가져오기 ─────────────────────────────────────
def get_news(ticker):
    try:
        t    = yf.Ticker(ticker)
        news = t.news
        if not news:
            return None
        n        = news[0]
        title    = n.get("title", "")
        pub_time = datetime.fromtimestamp(n.get("providerPublishTime", 0), tz=KST)
        time_str = pub_time.strftime("%m/%d %H:%M")
        return f"[{time_str}] {title}"
    except:
        return None

# ── 등급 결정 ─────────────────────────────────────────
def rate_stock(stats):
    v   = stats["volatility"]
    vol = stats["vol_ratio"]
    if v >= 6 and vol >= 1.5:
        return "🔥 단타 강력추천"
    elif v >= 4 and vol >= 1.0:
        return "⚡ 단타 적합"
    else:
        return "👀 단타 관망"

# ── 한국장 스캔 ───────────────────────────────────────
def scan_kr():
    print("[한국장 스캔 중...]")
    results = []
    for ticker, name in KR_STOCKS.items():
        stats = get_daily_stats(ticker)
        time.sleep(0.3)
        if stats is None or stats["volatility"] < 3:
            continue
        stats["name"]   = name
        stats["rating"] = rate_stock(stats)
        stats["news"]   = get_news(ticker)
        results.append(stats)
        print(f"  {name}: 변동폭 {stats['volatility']:.1f}% | 거래량 {stats['vol_ratio']:.1f}배")

    results.sort(key=lambda x: (
        0 if "강력" in x["rating"] else 1 if "적합" in x["rating"] else 2,
        -x["volatility"]
    ))
    return results[:12]

# ── 미국장 스캔 ───────────────────────────────────────
def scan_us():
    print("[미국장 스캔 중...]")
    results = []
    for ticker in US_STOCKS:
        stats = get_daily_stats(ticker)
        time.sleep(0.3)
        if stats is None or stats["volatility"] < 2:
            continue
        stats["name"]   = ticker
        stats["rating"] = rate_stock(stats)
        stats["news"]   = get_news(ticker)
        results.append(stats)
        print(f"  {ticker}: 변동폭 {stats['volatility']:.1f}% | 거래량 {stats['vol_ratio']:.1f}배")

    results.sort(key=lambda x: (
        0 if "강력" in x["rating"] else 1 if "적합" in x["rating"] else 2,
        -x["volatility"]
    ))
    return results[:12]

# ── 메시지 포맷 ───────────────────────────────────────
def format_message(results, market, date_str):
    flag = "🇰🇷 한국" if market == "KR" else "🇺🇸 미국"
    msg  = f"⚡ 단타 추천 [{date_str}]  {flag}\n\n\n"

    for s in results:
        change = f"▲{s['change_pct']:.1f}%" if s['change_pct'] >= 0 else f"▼{abs(s['change_pct']):.1f}%"
        if market == "KR":
            price = f"{s['price']:,.0f}원"
        else:
            price = f"${s['price']:.2f}"

        msg += f"{s['rating']} {s['name']}  {price} {change}\n"
        msg += f"  변동폭:{s['volatility']:.1f}% | 거래량:{s['vol_ratio']:.1f}배 | 당일범위:{s['day_range']:.1f}%\n"
        if s.get("news"):
            msg += f"  📰 {s['news']}\n"
        msg += "\n"

    msg += "⚡ 손절선 -2~3% 필수! ⚠️ 투자 책임은 본인에게 있습니다."
    return msg

# ── 메인 루프 ─────────────────────────────────────────
def run():
    kr_sent_today = None
    us_sent_today = None

    print("=== 단타 추천 스캐너 시작 ===")

    while True:
        now     = datetime.now(KST)
        weekday = now.weekday()
        date_str = now.strftime("%Y-%m-%d")
        h, m    = now.hour, now.minute

        # ── 한국장: 평일 08:50 KST 발송 ──────────────
        if weekday < 5 and h == 8 and m == 50 and kr_sent_today != date_str:
            print(f"\n[{now.strftime('%H:%M')}] 한국장 단타 추천 발송 시작")
            results = scan_kr()
            if results:
                msg = format_message(results, "KR", date_str)
                ok  = send(msg)
                print(f"  한국장 알람 {'OK' if ok else 'FAIL'}")
            kr_sent_today = date_str

        # ── 미국장: 평일 22:20 KST 발송 ──────────────
        if weekday < 5 and h == 22 and m == 20 and us_sent_today != date_str:
            print(f"\n[{now.strftime('%H:%M')}] 미국장 단타 추천 발송 시작")
            results = scan_us()
            if results:
                msg = format_message(results, "US", date_str)
                ok  = send(msg)
                print(f"  미국장 알람 {'OK' if ok else 'FAIL'}")
            us_sent_today = date_str

        time.sleep(60)  # 1분마다 체크

if __name__ == "__main__":
    run()
