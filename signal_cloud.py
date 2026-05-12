# signal_cloud.py
# 매일 투자 신호 + 단타 추천 + 뉴스 이유 알람 (GitHub Actions)

import requests
import sys, os, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import FinanceDataReader as fdr
import ta

# ── 설정 ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8386728044:AAH27uG-7OWKlQG4Nr97sJli6Wnjes_wcvw")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "936157775")

# ── 종목 리스트 (코드, 이름, 시장, 카테고리, 뉴스검색어, 뉴스언어) ──
WATCH = [
    # 한국 대형주
    ("005930", "삼성전자",       "KR", "🇰🇷 한국 대형주", "삼성전자 주가",       "ko"),
    ("000660", "SK하이닉스",     "KR", "🇰🇷 한국 대형주", "SK하이닉스 주가",     "ko"),
    ("005380", "현대차",         "KR", "🇰🇷 한국 대형주", "현대차 주가",         "ko"),
    ("051910", "LG화학",         "KR", "🇰🇷 한국 대형주", "LG화학 주가",         "ko"),
    ("035420", "NAVER",          "KR", "🇰🇷 한국 대형주", "네이버 주가",         "ko"),
    # 한국 소형주
    ("042700", "한미반도체",     "KR", "🇰🇷 한국 소형주", "한미반도체 주가",     "ko"),
    ("247540", "에코프로비엠",   "KR", "🇰🇷 한국 소형주", "에코프로비엠 주가",   "ko"),
    ("034020", "두산에너빌리티", "KR", "🇰🇷 한국 소형주", "두산에너빌리티 주가", "ko"),
    ("352820", "하이브",         "KR", "🇰🇷 한국 소형주", "하이브 주가",         "ko"),
    ("196170", "알테오젠",       "KR", "🇰🇷 한국 소형주", "알테오젠 주가",       "ko"),
    # 미국 대형주
    ("NVDA",  "엔비디아",        "US", "🇺🇸 미국 대형주", "NVDA nvidia stock",   "en"),
    ("TSLA",  "테슬라",          "US", "🇺🇸 미국 대형주", "TSLA tesla stock",    "en"),
    ("META",  "메타",            "US", "🇺🇸 미국 대형주", "META stock news",     "en"),
    ("AAPL",  "애플",            "US", "🇺🇸 미국 대형주", "AAPL apple stock",    "en"),
    ("AMD",   "AMD",             "US", "🇺🇸 미국 대형주", "AMD stock news",      "en"),
    # 미국 소형주
    ("MSTR", "마이크로스트래티지","US", "🇺🇸 미국 소형주", "MSTR microstrategy",  "en"),
    ("SMCI", "슈퍼마이크로",     "US", "🇺🇸 미국 소형주", "SMCI supermicro stock","en"),
    ("RIOT", "라이엇플랫폼",     "US", "🇺🇸 미국 소형주", "RIOT stock bitcoin",  "en"),
    ("SOUN", "사운드하운드",     "US", "🇺🇸 미국 소형주", "SOUN soundhound stock","en"),
    ("RKLB", "로켓랩",           "US", "🇺🇸 미국 소형주", "RKLB rocket lab",     "en"),
]

# ── 텔레그램 전송 ────────────────────────────────────
def send_telegram(message: str):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }, timeout=10)
    ok = resp.status_code == 200
    print("텔레그램:", "✅" if ok else f"❌ {resp.text[:100]}")
    return ok

# ── 뉴스 수집 (Google News RSS) ──────────────────────
def get_news(query: str, lang: str = "ko", hours: int = 36) -> list:
    """최근 N시간 이내 뉴스 최대 2개 반환"""
    if lang == "ko":
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    else:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en&gl=US&ceid=US:en"

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    cutoff  = datetime.now() - timedelta(hours=hours)
    items   = []
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            title   = item.findtext("title", "").strip()
            pubdate = item.findtext("pubDate", "")
            source  = item.findtext("source", "")
            try:
                pub_dt = parsedate_to_datetime(pubdate).replace(tzinfo=None)
                if pub_dt < cutoff:
                    continue
                time_str = pub_dt.strftime("%m/%d %H:%M")
            except:
                time_str = "최근"

            # 광고/무관 기사 필터
            skip_words = ["etf", "fund", "index", "how to", "quiz", "광고"]
            if any(w in title.lower() for w in skip_words):
                continue

            # 제목 정리 - 출처 제거 (마지막 " - 출처" 패턴)
            if " - " in title:
                title = title.rsplit(" - ", 1)[0].strip()

            if title:
                items.append({"title": title, "time": time_str})
            if len(items) >= 2:
                break
    except Exception as e:
        pass
    return items

# ── 지표 계산 ────────────────────────────────────────
def get_indicators(code: str, market: str) -> dict:
    try:
        end   = datetime.today().strftime("%Y-%m-%d")
        start = (datetime.today() - timedelta(days=200)).strftime("%Y-%m-%d")
        df    = fdr.DataReader(code, start, end)
        if df.empty or len(df) < 20:
            return {}

        close  = df["Close"]
        volume = df["Volume"]
        price  = float(close.iloc[-1])

        rsi = float(ta.momentum.RSIIndicator(close, 14).rsi().iloc[-1])

        macd_obj = ta.trend.MACD(close)
        mv, ms   = float(macd_obj.macd().iloc[-1]), float(macd_obj.macd_signal().iloc[-1])
        mv2, ms2 = float(macd_obj.macd().iloc[-2]), float(macd_obj.macd_signal().iloc[-2])
        if mv > ms and mv2 <= ms2:   macd_cross = "골든"
        elif mv < ms and mv2 >= ms2: macd_cross = "데드"
        else:                        macd_cross = "위" if mv > ms else "아래"

        bb    = ta.volatility.BollingerBands(close, 20)
        bb_up = float(bb.bollinger_hband().iloc[-1])
        bb_lo = float(bb.bollinger_lband().iloc[-1])
        bb_pct = (price - bb_lo) / (bb_up - bb_lo) * 100 if bb_up != bb_lo else 50

        chg_1d = float(df["Change"].iloc[-1]) * 100 if "Change" in df.columns else \
                 (price - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
        chg_5d = (price - float(close.iloc[-6])) / float(close.iloc[-6]) * 100 if len(df) >= 6 else 0

        vol_today = float(volume.iloc[-1])
        vol_avg5  = float(volume.iloc[-6:-1].mean()) if len(df) >= 6 else vol_today
        vol_ratio = round(vol_today / vol_avg5, 2) if vol_avg5 > 0 else 1.0

        if "High" in df.columns and "Low" in df.columns:
            hi, lo = float(df["High"].iloc[-1]), float(df["Low"].iloc[-1])
            intraday = (hi - lo) / price * 100
            atr = float(ta.volatility.AverageTrueRange(
                df["High"], df["Low"], close, window=5
            ).average_true_range().iloc[-1])
            atr_pct = atr / price * 100
        else:
            intraday = abs(chg_1d)
            atr_pct  = abs(chg_1d)

        return {
            "price": price, "rsi": rsi, "bb_pct": bb_pct,
            "macd_cross": macd_cross, "macd_above": mv > ms,
            "chg_1d": chg_1d, "chg_5d": chg_5d,
            "vol_ratio": vol_ratio, "intraday": intraday,
            "atr_pct": atr_pct,
        }
    except Exception as e:
        print(f"  [{code}] 지표 오류: {e}")
        return {}

# ── 신호 점수 ────────────────────────────────────────
def score_stock(ind: dict):
    if not ind: return 50, [], []
    score = 50; up = []; dn = []
    rsi=ind["rsi"]; bb=ind["bb_pct"]; chg5=ind["chg_5d"]
    mc=ind["macd_cross"]; vr=ind["vol_ratio"]

    if   rsi < 30:  score+=20; up.append(f"RSI 과매도({rsi:.0f})")
    elif rsi < 45:  score+=10; up.append(f"RSI 저평가({rsi:.0f})")
    elif rsi > 75:  score-=22; dn.append(f"RSI 과매수({rsi:.0f})")
    elif rsi > 65:  score-=10; dn.append(f"RSI 높음({rsi:.0f})")

    if   bb < 20:   score+=15; up.append(f"볼린저 하단({bb:.0f}%)")
    elif bb < 35:   score+=7;  up.append("볼린저 매수구간")
    elif bb > 85:   score-=15; dn.append(f"볼린저 상단돌파({bb:.0f}%)")
    elif bb > 70:   score-=7;  dn.append(f"볼린저 과열({bb:.0f}%)")

    if   mc=="골든": score+=15; up.append("MACD 골든크로스🔔")
    elif mc=="데드":  score-=15; dn.append("MACD 데드크로스🔔")
    elif ind["macd_above"]: score+=5; up.append("MACD 상승추세")
    else:            score-=5;  dn.append("MACD 하락추세")

    if   chg5>15:  score-=8;  dn.append(f"5일 과열({chg5:+.1f}%)")
    elif chg5>5:   score+=5;  up.append(f"5일 상승({chg5:+.1f}%)")
    elif chg5<-10: score+=10; up.append(f"5일 급락→반등기대({chg5:+.1f}%)")
    elif chg5<0:   score-=3;  dn.append(f"5일 하락({chg5:+.1f}%)")

    if   vr>=2.0: score+=8;  up.append(f"거래량 급증({vr:.1f}배)🔥")
    elif vr>=1.5: score+=4;  up.append(f"거래량 증가({vr:.1f}배)")

    return max(0,min(100,score)), up, dn

# ── 단타 점수 ────────────────────────────────────────
def daytrade_score(ind: dict):
    if not ind: return 0, "❓"
    s=0
    atr=ind["atr_pct"]; vr=ind["vol_ratio"]; rsi=ind["rsi"]
    bb=ind["bb_pct"];   c1=abs(ind["chg_1d"])

    if atr>=5: s+=30
    elif atr>=3: s+=20
    elif atr>=2: s+=10

    if vr>=2.0: s+=25
    elif vr>=1.5: s+=15
    elif vr>=1.0: s+=5

    if rsi<35 or rsi>70: s+=20
    elif rsi<45 or rsi>60: s+=10

    if bb<15 or bb>90: s+=15
    elif bb<30 or bb>75: s+=8

    if c1>=5: s+=10
    elif c1>=2: s+=5

    s = min(100,s)
    if s>=70:   lbl="🔥 단타 강력추천"
    elif s>=50: lbl="⚡ 단타 적합"
    elif s>=30: lbl="👀 단타 관망"
    else:       lbl="😴 단타 부적합"
    return s, lbl

def fmt_price(p, mkt): return f"{p:,.0f}원" if mkt=="KR" else f"${p:.2f}"
def fmt_chg(c):        return f"{'▲' if c>=0 else '▼'}{abs(c):.1f}%"

# ── 메인 ────────────────────────────────────────────
def run():
    today   = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().weekday()

    if weekday >= 5:
        send_telegram(f"📅 <b>{today} (주말)</b>\n주식시장 휴장. 월요일에 봬요! 😊")
        return

    print(f"=== {today} 신호 분석 시작 ===")

    results = []
    for code, name, market, cat, news_q, news_lang in WATCH:
        print(f"  {name} 분석중...")
        ind                = get_indicators(code, market)
        score, up, dn      = score_stock(ind)
        dt_s, dt_l         = daytrade_score(ind)
        news               = get_news(news_q, news_lang)
        results.append({
            "code":code, "name":name, "market":market, "cat":cat,
            "ind":ind, "score":score, "up":up, "dn":dn,
            "dt_score":dt_s, "dt_label":dt_l, "news":news,
        })

    cats = ["🇰🇷 한국 대형주","🇰🇷 한국 소형주","🇺🇸 미국 대형주","🇺🇸 미국 소형주"]

    # ════════════════════════════════════
    #  메시지 빌더 (카테고리별 분할 전송)
    # ════════════════════════════════════
    def build_signal_msg(cat: str, group: list) -> str:
        lines = [f"<b>📊 투자 신호 [{today}]</b>  {cat}\n"]
        for r in group:
            ind = r["ind"]
            if not ind:
                continue
            p   = fmt_price(ind["price"], r["market"])
            c1  = fmt_chg(ind["chg_1d"])
            sc  = r["score"]
            rsi = ind["rsi"]

            if   sc >= 65: sig = "🛒 <b>매수</b>"
            elif sc >= 55: sig = "🟡 관망(매수우세)"
            elif sc >= 45: sig = "⚪ 중립"
            elif sc >= 35: sig = "🟡 관망(매도우세)"
            else:          sig = "🚨 <b>매도/회피</b>"

            tech = (r["up"] + r["dn"])[:2]
            tech_str = " | ".join(tech) if tech else "-"

            lines.append(f"\n{sig} <b>{r['name']}</b>  {p} {c1}")
            lines.append(f"  📊 {sc}점 | RSI:{rsi:.0f} | {tech_str}")
            if r["news"]:
                for n in r["news"][:2]:
                    lines.append(f"  📰 [{n['time']}] {n['title'][:50]}")
            else:
                lines.append("  📰 최근 뉴스 없음")
        lines.append("\n⚠️ 참고용. 투자 책임은 본인에게 있습니다.")
        return "\n".join(lines)

    def build_daytrade_msg(cat: str, group: list) -> str:
        lines = [f"<b>⚡ 단타 추천 [{today}]</b>  {cat}\n"]
        for r in group:
            ind = r["ind"]
            if not ind:
                continue
            p   = fmt_price(ind["price"], r["market"])
            c1  = fmt_chg(ind["chg_1d"])
            atr = ind["atr_pct"]
            vr  = ind["vol_ratio"]
            rng = ind["intraday"]

            lines.append(f"\n{r['dt_label']} <b>{r['name']}</b>  {p} {c1}")
            lines.append(f"  변동폭:{atr:.1f}% | 거래량:{vr:.1f}배 | 당일범위:{rng:.1f}%")
            if r["news"]:
                lines.append(f"  📰 [{r['news'][0]['time']}] {r['news'][0]['title'][:50]}")
        lines.append("\n⚡ 손절선 -2~3% 필수! ⚠️ 투자 책임은 본인에게 있습니다.")
        return "\n".join(lines)

    # 카테고리별 4개 메시지 전송 (신호 2개 + 단타 2개)
    # 한국 묶음 / 미국 묶음으로 2+2 전송
    kr_group_sig = []
    us_group_sig = []
    kr_group_dt  = []
    us_group_dt  = []

    for cat in ["🇰🇷 한국 대형주", "🇰🇷 한국 소형주"]:
        g = sorted([r for r in results if r["cat"]==cat], key=lambda x: x["score"], reverse=True)
        kr_group_sig.extend(g)
        g2 = sorted([r for r in results if r["cat"]==cat], key=lambda x: x["dt_score"], reverse=True)
        kr_group_dt.extend(g2)

    for cat in ["🇺🇸 미국 대형주", "🇺🇸 미국 소형주"]:
        g = sorted([r for r in results if r["cat"]==cat], key=lambda x: x["score"], reverse=True)
        us_group_sig.extend(g)
        g2 = sorted([r for r in results if r["cat"]==cat], key=lambda x: x["dt_score"], reverse=True)
        us_group_dt.extend(g2)

    send_telegram(build_signal_msg("🇰🇷 한국", kr_group_sig))
    send_telegram(build_signal_msg("🇺🇸 미국", us_group_sig))
    send_telegram(build_daytrade_msg("🇰🇷 한국", kr_group_dt))
    send_telegram(build_daytrade_msg("🇺🇸 미국", us_group_dt))
    print("✅ 완료")

if __name__ == "__main__":
    run()
