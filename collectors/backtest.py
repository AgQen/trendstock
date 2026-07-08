"""추천 신호 백테스트 — 매수/매도 신호가 실제로 수익이 나는지, 위험은 통제되는지 검증.

전략 정의 (프론트 computeSignals 와 동일한 신호 상태기계):
  - 매수 신호(isBuyCond): grade == 'Strong Buy' 항상, 'Buy' 는 재무점수 ≥ 평균일 때만.
  - 매도 신호(isSellSig): 직전 재무 ≥ 평균인데 현재 재무가 -2 이상 하락,
    또는 직전이 매수등급인데 현재가 매수등급이 아님.
  - 티커는 매수 신호 시점에 편입, 매도 신호 시점에 청산 → 보유 구간.

포트폴리오:
  - 매 거래일, 보유 중인 티커를 동일가중.
  - 일간 포트폴리오 수익률 = 보유 티커들의 일간 수익률 평균 (미보유 시 현금 0%).

산출 지표:
  - 총수익률, 연율화 수익률(CAGR), 연율화 변동성, 샤프지수(rf=0), 최대낙폭(MDD).
  - SPY 매수후보유 대비 초과성과.

실행: python -m collectors.backtest
"""

from __future__ import annotations

import json
import math
from datetime import date as date_cls

from .db import get_conn, init_db

BUY_GRADES = {"Strong Buy", "Buy"}
TRADING_DAYS = 252
RF_ANNUAL = 0.0   # 무위험 수익률 (단순화)


def _load_recs(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.analysis_date, r.grade, r.fundamentals_score, a.ticker
        FROM recommendations r
        JOIN assets a ON a.asset_id = r.asset_id
        ORDER BY r.analysis_date ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _avg_fund(recs: list[dict]) -> float:
    vals = [r["fundamentals_score"] for r in recs if r["fundamentals_score"] is not None]
    return sum(vals) / len(vals) if vals else 4.0


def _is_buy(r: dict, avg_fund: float, mode: str = "all") -> bool:
    g = r["grade"]
    if mode == "strong":
        # Strong Buy 만 (고신뢰)
        return g == "Strong Buy"
    if mode == "strong_highfund":
        # Strong Buy + 재무 평균보다 확실히 높은 것만 (매우 선별적)
        return g == "Strong Buy" and (r["fundamentals_score"] or 0) >= avg_fund + 1
    # mode == "all": Strong Buy 항상, Buy 는 재무 ≥ 평균
    if g == "Strong Buy":
        return True
    if g == "Buy":
        fs = r["fundamentals_score"]
        return fs is not None and fs >= avg_fund
    return False


def _is_sell(curr: dict, prev: dict, avg_fund: float) -> bool:
    pf = prev["fundamentals_score"]
    if pf is None:
        return False
    if pf >= avg_fund:
        cf = curr["fundamentals_score"]
        if cf is not None and cf <= pf - 2:
            return True
    was_buy = prev["grade"] in BUY_GRADES
    is_buy = curr["grade"] in BUY_GRADES
    return was_buy and not is_buy


def _holding_intervals(recs: list[dict], avg_fund: float,
                       mode: str = "all") -> dict[str, list[tuple[str, str | None]]]:
    """티커별 보유 구간 [(buy_date, sell_date|None), ...] 반환."""
    by_ticker: dict[str, list[dict]] = {}
    for r in recs:
        by_ticker.setdefault(r["ticker"], []).append(r)

    intervals: dict[str, list[tuple[str, str | None]]] = {}
    for ticker, rs in by_ticker.items():
        rs.sort(key=lambda x: x["analysis_date"])
        holding = False
        entry = None
        prev = None
        spans: list[tuple[str, str | None]] = []
        for r in rs:
            if not holding:
                if _is_buy(r, avg_fund, mode):
                    holding = True
                    entry = r["analysis_date"]
            else:
                if prev and _is_sell(r, prev, avg_fund):
                    spans.append((entry, r["analysis_date"]))
                    holding = False
                    entry = None
            prev = r
        if holding and entry:
            spans.append((entry, None))  # 아직 보유 중
        if spans:
            intervals[ticker] = spans
    return intervals


def _price_series(conn) -> tuple[list[str], dict[str, dict[str, float]]]:
    """거래일 리스트 + {ticker: {date: close}} 반환."""
    rows = conn.execute(
        """
        SELECT a.ticker, p.date, p.close
        FROM price_history p JOIN assets a ON a.asset_id = p.asset_id
        WHERE p.close IS NOT NULL
        ORDER BY p.date ASC
        """
    ).fetchall()
    prices: dict[str, dict[str, float]] = {}
    dates: set[str] = set()
    for r in rows:
        prices.setdefault(r["ticker"], {})[r["date"]] = float(r["close"])
        dates.add(r["date"])
    return sorted(dates), prices


def _held_on(intervals: dict, ticker: str, day: str) -> bool:
    for entry, exit_ in intervals.get(ticker, []):
        if entry <= day and (exit_ is None or day < exit_):
            return True
    return False


def _metrics(daily_returns: list[float]) -> dict:
    n = len(daily_returns)
    if n == 0:
        return {"days": 0}
    equity = [1.0]
    for r in daily_returns:
        equity.append(equity[-1] * (1 + r))
    total_return = equity[-1] - 1
    mean = sum(daily_returns) / n
    var = sum((r - mean) ** 2 for r in daily_returns) / n if n > 1 else 0.0
    std = math.sqrt(var)
    ann_return = (1 + total_return) ** (TRADING_DAYS / n) - 1 if n > 0 else 0.0
    ann_vol = std * math.sqrt(TRADING_DAYS)
    sharpe = ((mean * TRADING_DAYS) - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0.0
    # 최대낙폭
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return {
        "days": n,
        "total_return_pct": round(total_return * 100, 2),
        "ann_return_pct": round(ann_return * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(mdd * 100, 2),
    }


STRATEGIES = {
    "all":            "모든 매수신호 (Strong Buy + Buy≥평균재무)",
    "strong":         "Strong Buy 만",
    "strong_highfund": "Strong Buy + 재무 평균+1 이상 (최고 선별)",
}


def _run_strategy(recs, avg_fund, all_dates, prices, mode, bench_daily_cache):
    intervals = _holding_intervals(recs, avg_fund, mode)
    first_signal = min(
        (sp[0] for spans in intervals.values() for sp in spans), default=None,
    )
    if first_signal is None:
        return None
    dates = [d for d in all_dates if d >= first_signal]
    strat_daily, exposure = [], []
    for i in range(1, len(dates)):
        d0, d1 = dates[i - 1], dates[i]
        held = [t for t in intervals if _held_on(intervals, t, d0)]
        rets = []
        for t in held:
            p0 = prices.get(t, {}).get(d0)
            p1 = prices.get(t, {}).get(d1)
            if p0 and p1:
                rets.append(p1 / p0 - 1)
        strat_daily.append(sum(rets) / len(rets) if rets else 0.0)
        exposure.append(len(rets))

    # 같은 구간 SPY 벤치마크
    spy = prices.get("SPY", {})
    bench_daily = []
    for i in range(1, len(dates)):
        p0 = spy.get(dates[i - 1])
        p1 = spy.get(dates[i])
        bench_daily.append((p1 / p0 - 1) if (p0 and p1) else 0.0)

    strat = _metrics(strat_daily)
    bench = _metrics(bench_daily)
    alpha = round(strat.get("total_return_pct", 0) - bench.get("total_return_pct", 0), 2)
    return {
        "mode": mode,
        "desc": STRATEGIES.get(mode, mode),
        "period": {"start": dates[0], "end": dates[-1]},
        "avg_positions": round(sum(exposure) / len(exposure), 1) if exposure else 0,
        "strategy": strat,
        "benchmark_spy": bench,
        "excess_return_pct": alpha,
        "verdict": _verdict(strat, alpha),
    }


def run() -> dict:
    init_db()
    with get_conn() as conn:
        recs = _load_recs(conn)
        if not recs:
            print("  [SKIP] 추천 데이터 없음.")
            return {}
        avg_fund = _avg_fund(recs)
        all_dates, prices = _price_series(conn)

        results = {}
        for mode in STRATEGIES:
            r = _run_strategy(recs, avg_fund, all_dates, prices, mode, None)
            if r:
                results[mode] = r

        # 샤프 기준 최고 전략
        best = max(results.values(),
                   key=lambda r: r["strategy"].get("sharpe", -99), default=None)
        return {"strategies": results, "best_mode": best["mode"] if best else None}


def _verdict(strat: dict, alpha: float) -> str:
    profitable = strat.get("total_return_pct", 0) > 0
    sharpe_ok = strat.get("sharpe", 0) >= 1.0
    dd_ok = strat.get("max_drawdown_pct", -100) >= -10.0  # MDD 10% 이내
    beats = alpha > 0
    checks = []
    checks.append(("수익", profitable))
    checks.append(("샤프≥1.0", sharpe_ok))
    checks.append(("MDD≤10%", dd_ok))
    checks.append(("SPY초과", beats))
    passed = sum(1 for _, ok in checks if ok)
    tag = "PASS" if passed >= 3 else "FAIL"
    detail = " ".join(f"{'O' if ok else 'X'} {name}" for name, ok in checks)
    return f"[{tag}] {detail}"


def main() -> None:
    result = run()
    if not result or not result.get("strategies"):
        print("\n[DONE] 백테스트 결과 없음.")
        return
    print("\n" + "=" * 60)
    print(" 추천 신호 백테스트 — 전략별 비교")
    print("=" * 60)
    for mode, r in result["strategies"].items():
        s = r["strategy"]
        star = " ★최고" if mode == result["best_mode"] else ""
        print(f"\n [{mode}] {r['desc']}{star}")
        print(f"   기간 {r['period']['start']}~{r['period']['end']} · 평균보유 {r['avg_positions']}개")
        print(f"   총수익 {s['total_return_pct']:+.2f}%  샤프 {s['sharpe']:.2f}  "
              f"MDD {s['max_drawdown_pct']:.2f}%  변동성 {s['ann_vol_pct']:.1f}%  "
              f"vs SPY {r['excess_return_pct']:+.2f}%p")
        print(f"   판정: {r['verdict']}")
    print("\n" + "=" * 60)
    if result["best_mode"]:
        print(f" 샤프 기준 최고 전략: [{result['best_mode']}]")
    print("=" * 60)


if __name__ == "__main__":
    main()
