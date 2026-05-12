# signal_cloud.py
# GitHub Actions에서 실행되는 클라우드 버전
# 컴퓨터 꺼져도 매일 자동 알람 전송

import requests
import sys
import os
from datetime import datetime, timedelta
import FinanceDataReader as fdr
import ta

# ── 설정 ────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "8386728044:AAH27uG-7OWKlQG4Nr97sJli6Wnjes_wcvw")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "936157775")

# ── 모니터링 종목 ────────────────────────────────────────
WATCH = {
    "005930": ("삼성전자",     "KR"),
    "000660": ("SK하이닉스",   "KR"),
    "034020": ("두산에너빌리티","KR"),
    "042700": ("한미반도체",   "KR"),
    "NVDA":   ("엔비디아",     "US"),
    "GOOGL":  ("알파벳",       "US"),
    "TSLA":   ("테슬라",       "US"),
    "ASML":   ("ASML",         "US"),
    "TSM":    ("TSMC",         "US"),
    "SOXX":   ("반도체ETF",    "US"),
    "QQQ":    ("나스닥100ETF", "US"),
}

def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }, timeout=10)
    return resp.status_code == 200

def get_indicators(code: str, market: str) -> dict:
    try:
        end   = datetime.today().strftime("%Y-%m-%d")
        start = (datetime.today() - timedelta(days=200)).strftime("%Y-%m-%d")
        df = fdr.DataReader(code, start, end)
        if df.empty or len(df) < 20:
            return {}
        close = df["Close"]

        rsi  = ta.momentum.RSIIndicator(close, 14).rsi()
        macd = ta.trend.MACD(close)
        bb   = ta.volatility.BollingerBands(close, 20)

        price     = float(close.iloc[-1])
        rsi_val   = float(rsi.iloc[-1])
        macd_val  = float(macd.macd().iloc[-1])
        macd_sig  = float(macd.macd_signal().iloc[-1])
        bb_up     = float(bb.bollinger_hband().iloc[-1])
        bb_lo     = float(bb.bollinger_lband().iloc[-1])
        bb_pct    = (price - bb_lo) / (bb_up - bb_lo) * 100 if bb_up != bb_lo else 50

        chg_1d = float(df["Change"].iloc[-1]) * 100 if "Change" in df.columns else 0
        chg_5d = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100 if len(df) >= 6 else 0

        # MACD 크로스 확인
        if macd_val > macd_sig and float(macd.macd().iloc[-2]) <= float(macd.macd_signal().iloc[-2]):
            macd_cross = "골든"
        elif macd_val < macd_sig and float(macd.macd().iloc[-2]) >= float(macd.macd_signal().iloc[-2]):
            macd_cross = "데드"
        else:
            macd_cross = "위" if macd_val > macd_sig else "아래"

        return {
            "price": price, "rsi": rsi_val, "bb_pct": bb_pct,
            "macd_cross": macd_cross, "chg_1d": chg_1d, "chg_5d": chg_5d,
            "market": market,
        }
    except Exception as e:
        print(f"  [{code}] 지표 오류: {e}")
        return {}

def score_stock(ind: dict) -> tuple[int, list, list]:
    if not ind:
        return 50, [], []

    score = 50
    up, dn = [], []
    rsi = ind.get("rsi", 50)
    bb  = ind.get("bb_pct", 50)
    chg5= ind.get("chg_5d", 0)
    mc  = ind.get("macd_cross", "-")

    # RSI
    if rsi < 30:   score += 20; up.append(f"RSI 과매도({rsi:.0f})")
    elif rsi < 45: score += 10; up.append(f"RSI 저평가({rsi:.0f})")
    elif rsi > 75: score -= 22; dn.append(f"RSI 과매수({rsi:.0f})")
    elif rsi > 65: score -= 10; dn.append(f"RSI 높음({rsi:.0f})")

    # 볼린저밴드
    if bb < 20:    score += 15; up.append(f"볼린저 하단({bb:.0f}%)")
    elif bb < 35:  score += 7;  up.append(f"볼린저 매수구간")
    elif bb > 85:  score -= 15; dn.append(f"볼린저 상단돌파({bb:.0f}%)")
    elif bb > 70:  score -= 7;  dn.append(f"볼린저 과열({bb:.0f}%)")

    # MACD
    if mc == "골든":  score += 15; up.append("MACD 골든크로스🔔")
    elif mc == "데드": score -= 15; dn.append("MACD 데드크로스🔔")
    elif mc == "위":   score += 5;  up.append("MACD 상승추세")
    else:              score -= 5;  dn.append("MACD 하락추세")

    # 5일 모멘텀
    if chg5 > 15:   score -= 8;  dn.append(f"5일 과열({chg5:+.1f}%)")
    elif chg5 > 5:  score += 5;  up.append(f"5일 상승({chg5:+.1f}%)")
    elif chg5 < -10:score += 10; up.append(f"5일 급락 반등기대({chg5:+.1f}%)")
    elif chg5 < 0:  score -= 3;  dn.append(f"5일 하락({chg5:+.1f}%)")

    return max(0, min(100, score)), up, dn

def fmt_price(price: float, market: str) -> str:
    return f"{price:,.0f}원" if market == "KR" else f"${price:.2f}"

def run():
    today = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().weekday()
    if weekday >= 5:  # 토,일 휴장
        send_telegram(f"📅 <b>{today}</b>\n오늘은 주말 — 주식 시장 휴장입니다.")
        print("주말 — 스킵")
        return

    print(f"=== 신호 분석 시작: {today} ===")
    results = []

    for code, (name, market) in WATCH.items():
        print(f"  분석: {name}")
        ind = get_indicators(code, market)
        score, up, dn = score_stock(ind)
        results.append({
            "code": code, "name": name, "market": market,
            "ind": ind, "score": score, "up": up, "dn": dn,
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    buy_list   = [r for r in results if r["score"] >= 62]
    sell_list  = [r for r in results if r["score"] <= 38]
    watch_list = [r for r in results if 38 < r["score"] < 62]

    # ── 텔레그램 메시지 구성 ────────────────────────────
    lines = [f"<b>📊 매일 투자 신호 [{today}]</b>\n"]

    # 🛒 살 종목
    if buy_list:
        lines.append("━━━━━━━━━━━━━━━━")
        lines.append("🛒 <b>살 종목</b>")
        for r in buy_list:
            price_str = fmt_price(r["ind"].get("price", 0), r["market"])
            chg1 = r["ind"].get("chg_1d", 0)
            sign = "▲" if chg1 >= 0 else "▼"
            lines.append(
                f"\n  ✅ <b>{r['name']}</b>"
                f"  {price_str} {sign}{abs(chg1):.1f}%"
                f"\n  점수: {r['score']}점 | RSI: {r['ind'].get('rsi', 0):.0f}"
                f"\n  📌 {' / '.join(r['up'][:3])}"
            )
    else:
        lines.append("━━━━━━━━━━━━━━━━")
        lines.append("🛒 <b>살 종목</b>")
        lines.append("  ⚪ 오늘은 강한 매수 신호 없음")

    lines.append("")

    # 💰 팔/회피 종목
    if sell_list:
        lines.append("━━━━━━━━━━━━━━━━")
        lines.append("🚨 <b>팔 종목 / 진입 금지</b>")
        for r in sell_list:
            price_str = fmt_price(r["ind"].get("price", 0), r["market"])
            chg1 = r["ind"].get("chg_1d", 0)
            sign = "▲" if chg1 >= 0 else "▼"
            lines.append(
                f"\n  ❌ <b>{r['name']}</b>"
                f"  {price_str} {sign}{abs(chg1):.1f}%"
                f"\n  점수: {r['score']}점 | RSI: {r['ind'].get('rsi', 0):.0f}"
                f"\n  ⚠️ {' / '.join(r['dn'][:3])}"
            )
    else:
        lines.append("━━━━━━━━━━━━━━━━")
        lines.append("🚨 <b>팔 종목 / 진입 금지</b>")
        lines.append("  ⚪ 오늘은 강한 매도 신호 없음")

    lines.append("")

    # 👀 관망 종목
    if watch_list:
        lines.append("━━━━━━━━━━━━━━━━")
        lines.append("👀 <b>관망 (중립)</b>")
        for r in watch_list:
            emoji = "🟡" if r["score"] >= 52 else "⚪"
            lines.append(f"  {emoji} {r['name']} {r['score']}점")

    lines.append("\n━━━━━━━━━━━━━━━━")
    lines.append("⚠️ 본 신호는 참고용이며 투자 책임은 본인에게 있습니다.")

    msg = "\n".join(lines)
    ok = send_telegram(msg)
    print("텔레그램 전송:", "✅ 성공" if ok else "❌ 실패")
    print(f"\n살 종목: {[r['name'] for r in buy_list]}")
    print(f"팔 종목: {[r['name'] for r in sell_list]}")
    print(f"관망:    {[r['name'] for r in watch_list]}")

if __name__ == "__main__":
    run()
