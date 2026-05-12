# signal_cloud.py
# 매일 투자 신호 + 단타 추천 알람 (GitHub Actions 실행)

import requests
import sys
import os
from datetime import datetime, timedelta
import FinanceDataReader as fdr
import ta
import pandas as pd

# ── 설정 ────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8386728044:AAH27uG-7OWKlQG4Nr97sJli6Wnjes_wcvw")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "936157775")

# ── 종목 리스트 ──────────────────────────────────────────
# (코드, 이름, 시장, 카테고리)
WATCH = [
    # ── 한국 대형주 (5) ────────────────────────────────
    ("005930", "삼성전자",      "KR", "🇰🇷 한국 대형주"),
    ("000660", "SK하이닉스",    "KR", "🇰🇷 한국 대형주"),
    ("005380", "현대차",        "KR", "🇰🇷 한국 대형주"),
    ("051910", "LG화학",        "KR", "🇰🇷 한국 대형주"),
    ("035420", "NAVER",         "KR", "🇰🇷 한국 대형주"),

    # ── 한국 소형주/테마 단타 (5) ──────────────────────
    ("042700", "한미반도체",    "KR", "🇰🇷 한국 소형주"),
    ("247540", "에코프로비엠",  "KR", "🇰🇷 한국 소형주"),
    ("034020", "두산에너빌리티","KR", "🇰🇷 한국 소형주"),
    ("352820", "하이브",        "KR", "🇰🇷 한국 소형주"),
    ("196170", "알테오젠",      "KR", "🇰🇷 한국 소형주"),

    # ── 미국 대형주 (5) ────────────────────────────────
    ("NVDA",  "엔비디아",       "US", "🇺🇸 미국 대형주"),
    ("TSLA",  "테슬라",         "US", "🇺🇸 미국 대형주"),
    ("META",  "메타",           "US", "🇺🇸 미국 대형주"),
    ("AAPL",  "애플",           "US", "🇺🇸 미국 대형주"),
    ("AMD",   "AMD",            "US", "🇺🇸 미국 대형주"),

    # ── 미국 소형주/고변동 단타 (5) ────────────────────
    ("MSTR", "마이크로스트래티지","US", "🇺🇸 미국 소형주"),
    ("SMCI", "슈퍼마이크로",    "US", "🇺🇸 미국 소형주"),
    ("RIOT", "라이엇플랫폼",    "US", "🇺🇸 미국 소형주"),
    ("SOUN", "사운드하운드",    "US", "🇺🇸 미국 소형주"),
    ("RKLB", "로켓랩",          "US", "🇺🇸 미국 소형주"),
]

# ── 텔레그램 전송 ─────────────────────────────────────
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }, timeout=10)
    ok = resp.status_code == 200
    print("텔레그램:", "✅ 성공" if ok else f"❌ 실패 {resp.text}")
    return ok

# ── 지표 계산 ─────────────────────────────────────────
def get_indicators(code: str, market: str) -> dict:
    try:
        end   = datetime.today().strftime("%Y-%m-%d")
        start = (datetime.today() - timedelta(days=200)).strftime("%Y-%m-%d")
        df = fdr.DataReader(code, start, end)
        if df.empty or len(df) < 20:
            return {}

        close  = df["Close"]
        volume = df["Volume"]
        price  = float(close.iloc[-1])

        # RSI
        rsi = float(ta.momentum.RSIIndicator(close, 14).rsi().iloc[-1])

        # MACD
        macd_obj   = ta.trend.MACD(close)
        macd_val   = float(macd_obj.macd().iloc[-1])
        macd_sig   = float(macd_obj.macd_signal().iloc[-1])
        macd_prev  = float(macd_obj.macd().iloc[-2])
        macd_sprev = float(macd_obj.macd_signal().iloc[-2])
        if macd_val > macd_sig and macd_prev <= macd_sprev:
            macd_cross = "골든"
        elif macd_val < macd_sig and macd_prev >= macd_sprev:
            macd_cross = "데드"
        else:
            macd_cross = "위" if macd_val > macd_sig else "아래"

        # 볼린저밴드
        bb     = ta.volatility.BollingerBands(close, 20)
        bb_up  = float(bb.bollinger_hband().iloc[-1])
        bb_lo  = float(bb.bollinger_lband().iloc[-1])
        bb_pct = (price - bb_lo) / (bb_up - bb_lo) * 100 if bb_up != bb_lo else 50

        # 등락률
        chg_1d = float(df["Change"].iloc[-1]) * 100 if "Change" in df.columns else \
                 (price - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
        chg_5d = (price - float(close.iloc[-6])) / float(close.iloc[-6]) * 100 if len(df) >= 6 else 0

        # 거래량 급증 (오늘 vs 5일 평균)
        vol_today = float(volume.iloc[-1])
        vol_avg5  = float(volume.iloc[-6:-1].mean()) if len(df) >= 6 else vol_today
        vol_ratio = vol_today / vol_avg5 if vol_avg5 > 0 else 1.0

        # 단타 변동성 (고가-저가 / 종가 %)
        high_today = float(df["High"].iloc[-1]) if "High" in df.columns else price
        low_today  = float(df["Low"].iloc[-1])  if "Low"  in df.columns else price
        intraday_range = (high_today - low_today) / price * 100 if price > 0 else 0

        # 5일 ATR (평균 변동폭)
        if "High" in df.columns and "Low" in df.columns:
            atr = float(ta.volatility.AverageTrueRange(
                df["High"], df["Low"], close, window=5
            ).average_true_range().iloc[-1])
            atr_pct = atr / price * 100
        else:
            atr_pct = abs(chg_1d)

        return {
            "price": price, "rsi": rsi, "bb_pct": bb_pct,
            "macd_cross": macd_cross, "macd_above": macd_val > macd_sig,
            "chg_1d": chg_1d, "chg_5d": chg_5d,
            "vol_ratio": vol_ratio, "intraday_range": intraday_range,
            "atr_pct": atr_pct, "market": market,
        }
    except Exception as e:
        print(f"  [{code}] 오류: {e}")
        return {}

# ── 종합 점수 계산 ────────────────────────────────────
def score_stock(ind: dict) -> tuple:
    if not ind:
        return 50, [], []

    score = 50
    up, dn = [], []

    rsi  = ind.get("rsi", 50)
    bb   = ind.get("bb_pct", 50)
    chg5 = ind.get("chg_5d", 0)
    mc   = ind.get("macd_cross", "-")
    vr   = ind.get("vol_ratio", 1.0)

    # RSI
    if   rsi < 30:  score += 20; up.append(f"RSI 과매도({rsi:.0f})")
    elif rsi < 45:  score += 10; up.append(f"RSI 저평가({rsi:.0f})")
    elif rsi > 75:  score -= 22; dn.append(f"RSI 과매수({rsi:.0f})")
    elif rsi > 65:  score -= 10; dn.append(f"RSI 높음({rsi:.0f})")

    # 볼린저
    if   bb < 20:   score += 15; up.append(f"볼린저 하단({bb:.0f}%)")
    elif bb < 35:   score +=  7; up.append("볼린저 매수구간")
    elif bb > 85:   score -= 15; dn.append(f"볼린저 상단돌파({bb:.0f}%)")
    elif bb > 70:   score -=  7; dn.append(f"볼린저 과열({bb:.0f}%)")

    # MACD
    if   mc == "골든": score += 15; up.append("MACD 골든크로스🔔")
    elif mc == "데드":  score -= 15; dn.append("MACD 데드크로스🔔")
    elif ind.get("macd_above"): score += 5; up.append("MACD 상승추세")
    else:               score -=  5; dn.append("MACD 하락추세")

    # 5일 모멘텀
    if   chg5 > 15:  score -=  8; dn.append(f"5일 과열({chg5:+.1f}%)")
    elif chg5 >  5:  score +=  5; up.append(f"5일 상승({chg5:+.1f}%)")
    elif chg5 < -10: score += 10; up.append(f"5일 급락→반등기대({chg5:+.1f}%)")
    elif chg5 <  0:  score -=  3; dn.append(f"5일 하락({chg5:+.1f}%)")

    # 거래량 급증 보너스
    if vr >= 2.0:  score += 8;  up.append(f"거래량 급증({vr:.1f}배)🔥")
    elif vr >= 1.5: score += 4; up.append(f"거래량 증가({vr:.1f}배)")

    return max(0, min(100, score)), up, dn

# ── 단타 적합도 평가 ──────────────────────────────────
def daytrade_score(ind: dict) -> tuple:
    """단타 가능성 점수 (변동성·거래량 기반)"""
    if not ind:
        return 0, "❓"

    atr   = ind.get("atr_pct", 0)
    vr    = ind.get("vol_ratio", 1.0)
    rsi   = ind.get("rsi", 50)
    bb    = ind.get("bb_pct", 50)
    chg1  = abs(ind.get("chg_1d", 0))

    score = 0
    # 변동폭 클수록 단타 기회 많음
    if atr >= 5:   score += 30
    elif atr >= 3: score += 20
    elif atr >= 2: score += 10

    # 거래량 많을수록 진입/청산 쉬움
    if vr >= 2.0:   score += 25
    elif vr >= 1.5: score += 15
    elif vr >= 1.0: score += 5

    # RSI 극단 = 단기 반전 기회
    if rsi < 35 or rsi > 70: score += 20
    elif rsi < 45 or rsi > 60: score += 10

    # 볼린저 극단 = 반전 기회
    if bb < 15 or bb > 90: score += 15
    elif bb < 30 or bb > 75: score += 8

    # 오늘 이미 많이 움직임 = 추가 변동 여지
    if chg1 >= 5: score += 10
    elif chg1 >= 2: score += 5

    score = min(100, score)
    if score >= 70:   label = "🔥 단타 강력추천"
    elif score >= 50: label = "⚡ 단타 적합"
    elif score >= 30: label = "👀 단타 관망"
    else:             label = "😴 단타 부적합"

    return score, label

def fmt_price(price: float, market: str) -> str:
    return f"{price:,.0f}원" if market == "KR" else f"${price:.2f}"

def fmt_chg(chg: float) -> str:
    sign = "▲" if chg >= 0 else "▼"
    return f"{sign}{abs(chg):.1f}%"

# ── 메인 ─────────────────────────────────────────────
def run():
    today   = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().weekday()

    if weekday >= 5:
        send_telegram(f"📅 <b>{today} (주말)</b>\n주식시장 휴장입니다. 월요일에 봬요! 😊")
        return

    print(f"=== 신호 분석: {today} ===")

    # 전 종목 분석
    results = []
    for code, name, market, cat in WATCH:
        print(f"  {name}...")
        ind = get_indicators(code, market)
        score, up, dn = score_stock(ind)
        dt_score, dt_label = daytrade_score(ind)
        results.append({
            "code": code, "name": name, "market": market, "cat": cat,
            "ind": ind, "score": score, "up": up, "dn": dn,
            "dt_score": dt_score, "dt_label": dt_label,
        })

    # 카테고리별 그룹핑
    cats = ["🇰🇷 한국 대형주", "🇰🇷 한국 소형주", "🇺🇸 미국 대형주", "🇺🇸 미국 소형주"]

    # ── 메시지 1: 매수/매도 신호 ──────────────────────
    lines1 = [f"<b>📊 투자 신호 리포트 [{today}]</b>\n"]

    for cat in cats:
        group = sorted([r for r in results if r["cat"] == cat],
                       key=lambda x: x["score"], reverse=True)
        if not group:
            continue

        lines1.append(f"\n<b>{cat}</b>")
        lines1.append("━━━━━━━━━━━━━━")

        for r in group:
            ind  = r["ind"]
            p    = fmt_price(ind.get("price", 0), r["market"])
            c1   = fmt_chg(ind.get("chg_1d", 0))
            rsi  = ind.get("rsi", 0)
            sc   = r["score"]

            if sc >= 62:
                emoji = "🛒 <b>매수</b>"
            elif sc >= 52:
                emoji = "🟡 관망(매수우세)"
            elif sc >= 42:
                emoji = "⚪ 중립"
            elif sc >= 32:
                emoji = "🟡 관망(매도우세)"
            else:
                emoji = "🚨 <b>매도/회피</b>"

            reason = ""
            if r["up"]:   reason = f"📌 {r['up'][0]}"
            elif r["dn"]: reason = f"⚠️ {r['dn'][0]}"

            lines1.append(
                f"\n{emoji} <b>{r['name']}</b>  {p} {c1}"
                f"\n  점수:{sc}점 | RSI:{rsi:.0f} | {reason}"
            )

    lines1.append("\n⚠️ 참고용 정보. 투자 책임은 본인에게 있습니다.")
    msg1 = "\n".join(lines1)

    # ── 메시지 2: 단타 추천 ───────────────────────────
    lines2 = [f"<b>⚡ 단타 추천 [{today}]</b>\n"]

    for cat in cats:
        group = sorted([r for r in results if r["cat"] == cat],
                       key=lambda x: x["dt_score"], reverse=True)
        if not group:
            continue

        lines2.append(f"\n<b>{cat}</b>")
        lines2.append("━━━━━━━━━━━━━━")

        for r in group:
            ind     = r["ind"]
            p       = fmt_price(ind.get("price", 0), r["market"])
            c1      = fmt_chg(ind.get("chg_1d", 0))
            atr     = ind.get("atr_pct", 0)
            vr      = ind.get("vol_ratio", 1.0)
            rng     = ind.get("intraday_range", 0)
            dt_s    = r["dt_score"]
            dt_l    = r["dt_label"]

            lines2.append(
                f"\n{dt_l} <b>{r['name']}</b>  {p} {c1}"
                f"\n  변동폭:{atr:.1f}% | 거래량:{vr:.1f}배 | 당일범위:{rng:.1f}%"
            )

    lines2.append("\n⚡ 단타는 손절선(-2~3%) 필수 설정 후 진입하세요!")
    msg2 = "\n".join(lines2)

    # 전송
    send_telegram(msg1)
    send_telegram(msg2)

    # 콘솔 요약
    print("\n=== 결과 요약 ===")
    for cat in cats:
        group = [r for r in results if r["cat"] == cat]
        print(f"\n{cat}")
        for r in sorted(group, key=lambda x: x["score"], reverse=True):
            print(f"  {r['name']:<14} 신호:{r['score']}점  단타:{r['dt_score']}점 {r['dt_label']}")

if __name__ == "__main__":
    run()
