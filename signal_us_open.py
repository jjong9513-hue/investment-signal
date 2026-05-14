# signal_us_open.py
# 미국장 시작 1시간 전 (9:30 PM KST = 8:30 AM EDT) 프리장 분석 알람

import yfinance as yf
import pandas as pd
import requests, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import sys, os

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8386728044:AAH27uG-7OWKlQG4Nr97sJli6Wnjes_wcvw")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "936157775")

# ── 시장 지수 ────────────────────────────────────────
INDICES = [
    ("^GSPC",  "S&P500"),
    ("^IXIC",  "NASDAQ"),
    ("^VIX",   "VIX(공포지수)"),
    ("^TNX",   "미국채10년"),
    ("GC=F",   "금 선물"),
    ("CL=F",   "WTI 원유"),
    ("DX-Y.NYB","달러인덱스"),
]

# ── 미국 종목 ─────────────────────────────────────────
STOCKS = [
    ("NVDA", "엔비디아",          "대형주", "NVDA nvidia earnings"),
    ("TSLA", "테슬라",            "대형주", "TSLA tesla stock news"),
    ("META", "메타",              "대형주", "META facebook stock"),
    ("AAPL", "애플",              "대형주", "AAPL apple stock news"),
    ("AMD",  "AMD",               "대형주", "AMD semiconductor news"),
    ("MSTR", "마이크로스트래티지", "소형주", "MSTR microstrategy bitcoin"),
    ("SMCI", "슈퍼마이크로",      "소형주", "SMCI supermicro stock"),
    ("RIOT", "라이엇플랫폼",      "소형주", "RIOT bitcoin stock news"),
    ("SOUN", "사운드하운드",      "소형주", "SOUN soundhound AI stock"),
    ("RKLB", "로켓랩",            "소형주", "RKLB rocket lab space"),
]

def send(msg):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
        timeout=15
    )
    ok = r.status_code == 200
    print("전송:", "OK" if ok else r.text[:80])
    return ok

def get_news(query, hours=10):
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        root = ET.fromstring(resp.content)
        cutoff = datetime.now() - timedelta(hours=hours)
        items = []
        for item in root.findall(".//item")[:15]:
            title   = item.findtext("title", "").strip()
            pubdate = item.findtext("pubDate", "")
            try:
                pub_dt = parsedate_to_datetime(pubdate).replace(tzinfo=None)
                if pub_dt < cutoff:
                    continue
                time_str = pub_dt.strftime("%H:%M")
            except:
                time_str = ""
            if title:
                items.append(f"  [{time_str}] {title[:55]}")
            if len(items) >= 2:
                break
        return items
    except:
        return []

def get_indicators(sym):
    """주가 지표 계산"""
    try:
        t    = yf.Ticker(sym)
        hist = t.history(period="60d", interval="1d")
        if hist.empty or len(hist) < 5:
            return None

        close  = hist["Close"]
        high   = hist["High"]
        low    = hist["Low"]
        volume = hist["Volume"]

        # 현재가 (프리장 포함)
        info          = t.fast_info
        current_price = float(info.last_price) if info.last_price else float(close.iloc[-1])
        prev_close    = float(close.iloc[-1])
        pre_chg       = (current_price - prev_close) / prev_close * 100

        # 등락률
        chg_1d = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100) if len(close) >= 2 else 0.0
        chg_5d = float((close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100) if len(close) >= 6 else 0.0
        chg_20d= float((close.iloc[-1] - close.iloc[-21])/ close.iloc[-21]* 100) if len(close) >= 21 else 0.0

        # 거래량 분석
        vol_today = float(volume.iloc[-1])
        vol_avg5  = float(volume.iloc[-6:-1].mean()) if len(volume) >= 6 else float(volume.mean())
        vol_avg20 = float(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else float(volume.mean())
        vol_ratio5  = vol_today / vol_avg5  if vol_avg5  > 0 else 1.0
        vol_ratio20 = vol_today / vol_avg20 if vol_avg20 > 0 else 1.0

        # 거래대금 (백만달러)
        trade_val = float(close.iloc[-1]) * vol_today / 1_000_000

        # RSI 14일
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = float((100 - 100 / (1 + rs)).iloc[-1]) if float(loss.iloc[-1]) != 0 else 50.0

        # MACD (12,26,9)
        ema12  = close.ewm(span=12, adjust=False).mean()
        ema26  = close.ewm(span=26, adjust=False).mean()
        macd   = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = float((macd - signal).iloc[-1])
        macd_val  = float(macd.iloc[-1])
        macd_cross = "상향돌파" if macd_hist > 0 and float((macd - signal).iloc[-2]) <= 0 else \
                     "하향돌파" if macd_hist < 0 and float((macd - signal).iloc[-2]) >= 0 else \
                     "골든" if macd_hist > 0 else "데드"

        # 볼린저밴드 20일
        if len(close) >= 20:
            ma20  = float(close.rolling(20).mean().iloc[-1])
            std20 = float(close.rolling(20).std().iloc[-1])
        else:
            ma20  = float(close.mean())
            std20 = 0.0
        bb_upper = ma20 + 2 * std20
        bb_lower = ma20 - 2 * std20
        bb_pos   = (float(close.iloc[-1]) - bb_lower) / (bb_upper - bb_lower) * 100 \
                   if (bb_upper - bb_lower) > 0 else 50.0

        # ATR 5일 (단타 변동성)
        tr    = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr     = float(tr.rolling(5).mean().iloc[-1])
        atr_pct = atr / float(close.iloc[-1]) * 100

        # 52주 고저
        high52 = float(high.rolling(252).max().iloc[-1]) if len(high) >= 252 else float(high.max())
        low52  = float(low.rolling(252).min().iloc[-1])  if len(low)  >= 252 else float(low.min())
        pos52  = (float(close.iloc[-1]) - low52) / (high52 - low52) * 100 if (high52 - low52) > 0 else 50.0

        # 지지/저항 (최근 20일 고저)
        resist = float(high.iloc[-20:].max())
        support= float(low.iloc[-20:].min())

        # ── 단타 점수 (0~100) ──
        day_score = 0
        if atr_pct > 4:        day_score += 25
        elif atr_pct > 3:      day_score += 20
        elif atr_pct > 2:      day_score += 12
        elif atr_pct > 1:      day_score += 6
        if vol_ratio5 > 2.5:   day_score += 25
        elif vol_ratio5 > 2.0: day_score += 18
        elif vol_ratio5 > 1.5: day_score += 10
        if rsi < 30:           day_score += 25
        elif rsi < 40:         day_score += 15
        elif rsi > 70:         day_score += 15
        elif rsi > 60:         day_score += 8
        if bb_pos < 15:        day_score += 15
        elif bb_pos < 25:      day_score += 8
        elif bb_pos > 85:      day_score += 10
        if abs(pre_chg) > 3:   day_score += 10

        # ── 스윙 점수 (0~100) ──
        swing_score = 0
        if rsi < 35:           swing_score += 30
        elif rsi < 45:         swing_score += 18
        elif rsi < 55:         swing_score += 8
        if chg_5d < -8:        swing_score += 25
        elif chg_5d < -4:      swing_score += 15
        elif chg_5d < 0:       swing_score += 8
        if vol_ratio20 > 1.5:  swing_score += 15
        if bb_pos < 20:        swing_score += 20
        elif bb_pos < 35:      swing_score += 10
        if macd_cross in ("골든", "상향돌파"): swing_score += 10
        if pos52 < 30:         swing_score += 10  # 52주 저점 근처
        if pre_chg > 0 and rsi < 55: swing_score += 5

        return {
            "price": current_price, "prev": prev_close,
            "pre_chg": pre_chg,
            "chg_1d": chg_1d, "chg_5d": chg_5d, "chg_20d": chg_20d,
            "vol_ratio5": vol_ratio5, "vol_ratio20": vol_ratio20,
            "trade_val": trade_val,
            "rsi": rsi, "macd_hist": macd_hist, "macd_cross": macd_cross,
            "bb_pos": bb_pos, "atr_pct": atr_pct,
            "pos52": pos52, "high52": high52, "low52": low52,
            "resist": resist, "support": support,
            "day_score": day_score, "swing_score": swing_score,
        }
    except Exception as e:
        print(f"  지표오류({sym}): {e}")
        return None

def run():
    now_str  = datetime.now().strftime("%m/%d %H:%M KST")
    weekday  = datetime.now().weekday()

    if weekday >= 5:
        send(f"<b>📅 주말</b>\n미국 주식시장 휴장입니다. 월요일에 봬요!")
        return

    print(f"=== {now_str} 미국 프리장 분석 시작 ===")

    # ── 메시지1: 시장 지수 현황 ──────────────────────────
    print("시장 지수 수집중...")
    msg1 = f"<b>🇺🇸 미국장 시작 1시간 전 브리핑</b> ({now_str})\n"
    msg1 += "━━━━━━━━━━━━━━━━━\n"
    msg1 += "<b>📊 시장 지수 현황</b>\n"

    for sym, name in INDICES:
        try:
            t     = yf.Ticker(sym)
            info  = t.fast_info
            price = info.last_price
            prev  = info.previous_close
            chg   = (price - prev) / prev * 100 if prev else 0
            arrow = "📈" if chg >= 0 else "📉"
            msg1 += f"{arrow} {name}: {price:.2f} ({chg:+.2f}%)\n"
        except:
            msg1 += f"❓ {name}: 데이터없음\n"

    # 시장 분위기 판단
    try:
        vix = yf.Ticker("^VIX").fast_info.last_price
        if vix < 15:
            mood = "😎 안정 (VIX 낮음 - 매수 유리)"
        elif vix < 20:
            mood = "😐 보통 (VIX 보통)"
        elif vix < 30:
            mood = "😰 불안 (VIX 높음 - 변동성 주의)"
        else:
            mood = "😱 공포 (VIX 매우 높음 - 극도 주의)"
        msg1 += f"\n<b>시장분위기:</b> {mood}\n"
    except:
        pass

    msg1 += "\n<b>⚡ 오늘 미국장 전략 포인트</b>\n"
    msg1 += "• 프리장 급등 종목 → 갭업 단타 기회\n"
    msg1 += "• 프리장 급락 종목 → 반등 스윙 검토\n"
    msg1 += "• VIX 20 이상 → 포지션 축소 권장\n"
    send(msg1)

    # ── 종목 분석 ───────────────────────────────────────
    print("종목 분석중...")
    results = []
    for sym, name, cat, news_q in STOCKS:
        print(f"  {sym} {name}...")
        ind  = get_indicators(sym)
        news = get_news(news_q, hours=10)
        results.append({
            "sym": sym, "name": name, "cat": cat,
            "ind": ind, "news": news
        })

    valid = [r for r in results if r["ind"] is not None]

    # ── 메시지2: 단타 TOP5 ──────────────────────────────
    day_top = sorted(valid, key=lambda x: x["ind"]["day_score"], reverse=True)[:5]
    msg2 = f"<b>⚡ 미국 단타 TOP5</b> ({now_str})\n"
    msg2 += "━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(day_top, 1):
        d = r["ind"]
        arrow = "📈" if d["pre_chg"] >= 0 else "📉"
        stars = "🔥" if d["day_score"] >= 70 else ("⭐" if d["day_score"] >= 50 else "")
        msg2 += f"\n{i}위 {arrow} <b>{r['sym']} {r['name']}</b> {stars}\n"
        msg2 += f"  단타점수: <b>{d['day_score']}점</b> | 카테고리: {r['cat']}\n"
        msg2 += f"  프리장: ${d['price']:.2f} ({d['pre_chg']:+.2f}%)\n"
        msg2 += f"  전일대비: {d['chg_1d']:+.2f}% | 5일: {d['chg_5d']:+.2f}%\n"
        msg2 += f"  거래량: 5일평균 {d['vol_ratio5']:.1f}배 | 거래대금: ${d['trade_val']:.0f}M\n"
        msg2 += f"  RSI: {d['rsi']:.0f} | ATR변동폭: {d['atr_pct']:.1f}% | BB위치: {d['bb_pos']:.0f}%\n"
        msg2 += f"  지지: ${d['support']:.2f} | 저항: ${d['resist']:.2f}\n"
        if r["news"]:
            msg2 += "  뉴스:\n"
            for n in r["news"]:
                msg2 += f"{n}\n"
    msg2 += "\n⚠️ 손절선 -2~3% 필수 | 투자 책임은 본인에게 있습니다"
    send(msg2)

    # ── 메시지3: 스윙 TOP5 ──────────────────────────────
    swing_top = sorted(valid, key=lambda x: x["ind"]["swing_score"], reverse=True)[:5]
    msg3 = f"<b>📊 미국 스윙 TOP5</b> ({now_str})\n"
    msg3 += "━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(swing_top, 1):
        d = r["ind"]
        arrow = "📈" if d["pre_chg"] >= 0 else "📉"
        stars = "🔥" if d["swing_score"] >= 70 else ("⭐" if d["swing_score"] >= 50 else "")
        msg3 += f"\n{i}위 {arrow} <b>{r['sym']} {r['name']}</b> {stars}\n"
        msg3 += f"  스윙점수: <b>{d['swing_score']}점</b> | 카테고리: {r['cat']}\n"
        msg3 += f"  현재가: ${d['price']:.2f} ({d['pre_chg']:+.2f}%)\n"
        msg3 += f"  5일: {d['chg_5d']:+.2f}% | 20일: {d['chg_20d']:+.2f}%\n"
        msg3 += f"  RSI: {d['rsi']:.0f} | MACD: {d['macd_cross']} | BB: {d['bb_pos']:.0f}%\n"
        msg3 += f"  52주위치: {d['pos52']:.0f}% (고점${d['high52']:.2f} 저점${d['low52']:.2f})\n"
        msg3 += f"  거래량: 20일평균 {d['vol_ratio20']:.1f}배\n"
        if r["news"]:
            msg3 += "  뉴스:\n"
            for n in r["news"]:
                msg3 += f"{n}\n"
    msg3 += "\n💡 스윙 목표: 3~10% | 손절: -3~5% 설정 권장"
    send(msg3)

    # ── 메시지4: 전종목 요약표 ──────────────────────────
    msg4 = f"<b>📋 전종목 프리장 요약</b> ({now_str})\n"
    msg4 += "━━━━━━━━━━━━━━━━━\n"
    for r in results:
        if r["ind"] is None:
            msg4 += f"❓ {r['sym']} {r['name']}: 데이터없음\n"
            continue
        d = r["ind"]
        arrow = "📈" if d["pre_chg"] >= 0 else "📉"
        msg4 += (f"{arrow} <b>{r['sym']}</b> ${d['price']:.2f}"
                 f" ({d['pre_chg']:+.2f}%)"
                 f" | RSI {d['rsi']:.0f}"
                 f" | 거래량 {d['vol_ratio5']:.1f}배"
                 f" | 단타 {d['day_score']}점"
                 f" | 스윙 {d['swing_score']}점\n")
    send(msg4)

    print("=== 전송 완료 ===")

if __name__ == "__main__":
    run()
