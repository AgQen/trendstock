"""객관적 룰 기반 종합 등급 (펀더 + 모멘텀 + 타이밍).

LLM 주관 없이 동일 입력 → 동일 등급. 매일 자동 재계산 가능.

총점 범위 [-4, +6]
  - 펀더    (0 ~ +3) : yfinance info
  - 모멘텀  (-2 ~ +2): DB 20거래일 종가
  - 타이밍  (-2 ~ +1): 신고가 돌파, 과열, 밸류

등급 매핑:
  ≥ 4 : Strong Buy
  ≥ 2 : Buy
  ≥ 0 : Hold
   < 0 : Caution
"""

from __future__ import annotations

from typing import Iterable


# --- 펀더 ---------------------------------------------------------------------

def fundamental_dim(info: dict) -> tuple[int, list[str]]:
    rev = info.get("revenueGrowth") or 0
    opm = info.get("operatingMargins") or 0
    roe = info.get("returnOnEquity") or 0
    dte = info.get("debtToEquity") or 0

    strong = []
    if rev >= 0.20: strong.append(f"매출 YoY +{rev*100:.0f}%")
    if opm >= 0.20: strong.append(f"영업이익률 {opm*100:.0f}%")
    if roe >= 0.20: strong.append(f"ROE {roe*100:.0f}%")
    if 0 < dte < 50: strong.append(f"부채/자본 {dte:.0f} (낮음)")

    moderate = []
    if 0.10 <= rev < 0.20: moderate.append(f"매출 YoY +{rev*100:.0f}%")
    if 0.10 <= opm < 0.20: moderate.append(f"영업이익률 {opm*100:.0f}%")
    if 0.10 <= roe < 0.20: moderate.append(f"ROE {roe*100:.0f}%")

    if len(strong) >= 4:
        return 3, [f"펀더 4지표 전부 강함 ({', '.join(strong[:3])} 등)"]
    if len(strong) >= 3:
        return 3, [f"펀더 3개 강함 ({', '.join(strong)})"]
    if len(strong) >= 2:
        return 2, [f"펀더 2개 강함 ({', '.join(strong)})"]
    if len(strong) >= 1 or len(moderate) >= 2:
        joined = ", ".join((strong + moderate)[:3])
        return 1, [f"펀더 일부 양호 ({joined})"]
    if rev < 0:
        return 0, [f"매출 감소 ({rev*100:.0f}%)"]
    return 0, ["펀더 데이터 부족 또는 평이"]


# --- 모멘텀 -------------------------------------------------------------------

def momentum_dim(prices_asc: list[float]) -> tuple[int, list[str]]:
    """prices_asc: 오래된 -> 최신 순. 최소 6개, 권장 21개."""
    if not prices_asc or len(prices_asc) < 6:
        return 0, ["모멘텀 데이터 부족"]

    now = prices_asc[-1]
    d20 = prices_asc[0]
    d5 = prices_asc[-6]

    r20 = (now / d20 - 1) * 100 if d20 else 0
    r5  = (now / d5  - 1) * 100 if d5  else 0

    reasons = []
    score = 0

    if r20 >= 10 and r5 > 0:
        score = 2
        reasons.append(f"20d +{r20:.0f}% & 5d {'+' if r5>=0 else ''}{r5:.0f}% 강한 우상향")
    elif r20 >= 5:
        score = 1
        reasons.append(f"20d +{r20:.0f}% 우상향")
    elif r20 > -5:
        score = 0
        reasons.append(f"20d {'+' if r20>=0 else ''}{r20:.0f}% 횡보")
    elif r20 >= -15:
        score = -1
        reasons.append(f"20d {r20:.0f}% 약세")
    else:
        score = -2
        reasons.append(f"20d {r20:.0f}% 추세 붕괴")

    return score, reasons


# --- 타이밍/밸류 --------------------------------------------------------------

def timing_dim(prices_asc: list[float], info: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    if prices_asc and len(prices_asc) >= 6:
        now = prices_asc[-1]
        d20 = prices_asc[0]
        max_prev = max(prices_asc[:-1])
        r20 = (now / d20 - 1) * 100 if d20 else 0

        # 신고가 돌파 (+1)
        if now > max_prev:
            score += 1
            reasons.append("20일 신고가 돌파")

        # 과열 패널티
        if r20 >= 50:
            score -= 2
            reasons.append(f"20d +{r20:.0f}% 극심한 과열")
        elif r20 >= 30:
            score -= 1
            reasons.append(f"20d +{r20:.0f}% 과열")

    # 밸류 (P/E)
    pe = info.get("trailingPE") or 0
    if pe >= 60:
        score -= 2
        reasons.append(f"P/E {pe:.0f} 극심한 고평가")
    elif pe >= 40:
        score -= 1
        reasons.append(f"P/E {pe:.0f} 고평가")
    elif 0 < pe < 20:
        # 저평가는 가산 없음 (이미 펀더에서 평가됨), 다만 reason 기록
        reasons.append(f"P/E {pe:.0f} 합리")

    # 하한 클램프
    if score < -2:
        score = -2
    if score > 1:
        score = 1
    return score, reasons


# --- 거래량 -------------------------------------------------------------------

def volume_dim(volumes_asc: list[float], prices_asc: list[float]) -> tuple[int, list[str]]:
    """5일 평균 거래량 vs 이전 평균, 가격 방향 확인."""
    if len(volumes_asc) < 6 or len(prices_asc) < 6:
        return 0, []

    avg_recent5 = sum(volumes_asc[-5:]) / 5
    n_old = max(len(volumes_asc) - 5, 1)
    avg_old = sum(volumes_asc[:-5]) / n_old if len(volumes_asc) > 5 else avg_recent5
    if avg_old == 0:
        return 0, []

    vol_ratio = avg_recent5 / avg_old
    now = prices_asc[-1]
    p5  = prices_asc[-6]
    r5  = (now / p5 - 1) * 100 if p5 else 0

    if vol_ratio >= 1.6:
        if r5 >= 5:
            return 1, [f"거래량 {vol_ratio:.1f}배 급증 · 5d {r5:+.0f}% 상승 동반"]
        if r5 <= -5:
            return -1, [f"거래량 {vol_ratio:.1f}배 급증 · 5d {r5:+.0f}% 하락 동반"]

    return 0, []


# --- 종합 ---------------------------------------------------------------------

def grade_from_total(total: int) -> str:
    if total >= 4: return "Strong Buy"
    if total >= 2: return "Buy"
    if total >= 0: return "Hold"
    return "Caution"


def compute_rating(info: dict, prices_asc: list[float],
                   volumes_asc: list[float] | None = None,
                   weights: dict | None = None) -> dict:
    fw = (weights or {}).get("fund_weight",     1.0)
    mw = (weights or {}).get("momentum_weight", 0.7)
    tw = (weights or {}).get("timing_weight",   1.3)
    vw = (weights or {}).get("volume_weight",   1.3)

    f_score, f_reasons = fundamental_dim(info)
    m_score, m_reasons = momentum_dim(prices_asc)
    t_score, t_reasons = timing_dim(prices_asc, info)
    v_score, v_reasons = volume_dim(volumes_asc or [], prices_asc)

    total = round(f_score * fw + m_score * mw + t_score * tw + v_score * vw)
    return {
        "grade":   grade_from_total(total),
        "total":   total,
        "weights": {"fund": fw, "momentum": mw, "timing": tw, "volume": vw},
        "dimensions": {
            "fundamentals": {"score": f_score, "weighted": round(f_score * fw, 2), "reasons": f_reasons},
            "momentum":     {"score": m_score, "weighted": round(m_score * mw, 2), "reasons": m_reasons},
            "timing":       {"score": t_score, "weighted": round(t_score * tw, 2), "reasons": t_reasons},
            "volume":       {"score": v_score, "weighted": round(v_score * vw, 2), "reasons": v_reasons},
        },
    }


def yahoo_ticker(ticker: str, exchange: str | None = None,
                 country: str | None = None) -> str:
    """assets.ticker 를 yfinance 형태로 변환.

    KOSPI -> .KS, KOSDAQ -> .KQ. 미국 종목은 그대로.
    BRK-B 같이 이미 -B suffix 가 있는 미국 종목은 그대로.
    """
    if "." in ticker:
        return ticker
    if exchange == "KOSPI":
        return f"{ticker}.KS"
    if exchange == "KOSDAQ":
        return f"{ticker}.KQ"
    if country == "KR":
        return f"{ticker}.KS"  # fallback
    return ticker
