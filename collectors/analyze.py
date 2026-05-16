"""룰 기반 트렌드 탐지 (LLM 없이).

산출물
  1. 진행 중인 트렌드 Top 5 — 섹터 평균 1d 수익률 기준
  2. 각 트렌드의 대장주 Top 3
  3. 다음 트렌드 후보 A — 가속 시그널 (단기 모멘텀 / 중기 모멘텀 비율)
  4. 다음 트렌드 후보 B — 스필오버 (핫 섹터 내 아직 안 움직인 종목)
  5. 다음 트렌드 후보 C — 개별 돌파 (현재가가 20일 고가 갱신)
"""

from collections import defaultdict

from .db import get_conn

# rn 인덱스 (최신=1)
RN_NOW = 1     # 오늘 종가
RN_PREV = 2    # 1거래일 전
RN_5D = 6      # 5거래일 전
RN_20D = 21    # 20거래일 전 (≈1개월)


def _safe_ret(now, base):
    if now is None or base is None or base == 0:
        return None
    return (now / base - 1) * 100


def main() -> None:
    conn = get_conn()

    rows = conn.execute(
        f"""
        WITH p AS (
            SELECT asset_id, date, close,
                   ROW_NUMBER() OVER (
                       PARTITION BY asset_id ORDER BY date DESC
                   ) AS rn
            FROM price_history
        )
        SELECT a.asset_id, a.ticker, a.name, a.country, a.sector,
               MAX(CASE WHEN p.rn = {RN_NOW}  THEN p.close END) AS close_now,
               MAX(CASE WHEN p.rn = {RN_PREV} THEN p.close END) AS close_1d,
               MAX(CASE WHEN p.rn = {RN_5D}   THEN p.close END) AS close_5d,
               MAX(CASE WHEN p.rn = {RN_20D}  THEN p.close END) AS close_20d
        FROM assets a
        JOIN p ON p.asset_id = a.asset_id
        WHERE a.is_active = 1 AND p.rn <= {RN_20D}
        GROUP BY a.asset_id, a.ticker, a.name, a.country, a.sector
        """
    ).fetchall()

    items = []
    for r in rows:
        d = dict(r)
        d["ret_1d"] = _safe_ret(d["close_now"], d["close_1d"])
        d["ret_5d"] = _safe_ret(d["close_now"], d["close_5d"])
        d["ret_20d"] = _safe_ret(d["close_now"], d["close_20d"])
        items.append(d)

    # === 섹터 집계 ===
    sectors = defaultdict(lambda: {"items": [], "r1": [], "r5": [], "r20": []})
    for it in items:
        key = f"{it['country']}/{it['sector'] or '(미분류)'}"
        sectors[key]["items"].append(it)
        if it["ret_1d"]  is not None: sectors[key]["r1"].append(it["ret_1d"])
        if it["ret_5d"]  is not None: sectors[key]["r5"].append(it["ret_5d"])
        if it["ret_20d"] is not None: sectors[key]["r20"].append(it["ret_20d"])

    summary = []
    for key, d in sectors.items():
        if not d["r1"]:
            continue
        avg = lambda xs: (sum(xs) / len(xs)) if xs else 0.0
        summary.append({
            "key": key,
            "n": len(d["items"]),
            "avg_1d":  avg(d["r1"]),
            "avg_5d":  avg(d["r5"]),
            "avg_20d": avg(d["r20"]),
            "up_count": sum(1 for x in d["r1"] if x > 0),
            "items": d["items"],
        })
    summary.sort(key=lambda x: x["avg_1d"], reverse=True)

    bar = "=" * 76
    print(bar)
    print(" TrendStock — 오늘의 트렌드 (룰 기반, LLM 미사용)")
    if items:
        print(f" 기준 종가일: 최신   |   비교: 1d / 5d / 20d (≈1개월)")
    print(bar)

    # === 1. 진행 중인 트렌드 Top 5 ===
    print("\n■ 1. 진행 중인 트렌드 Top 5  (섹터 평균 1일 수익률 기준)\n")
    for i, s in enumerate(summary[:5], 1):
        print(
            f"  [{i}] {s['key']:<22} "
            f"1d {s['avg_1d']:+6.2f}%   "
            f"5d {s['avg_5d']:+6.2f}%   "
            f"20d {s['avg_20d']:+6.2f}%   "
            f"({s['up_count']}/{s['n']} 상승)"
        )
        leaders = sorted(s["items"], key=lambda x: (x["ret_1d"] or 0), reverse=True)[:3]
        for l in leaders:
            print(
                f"        대장 - {l['ticker']:<7} {(l['name'] or '')[:14]:<14}  "
                f"1d {l['ret_1d'] or 0:+6.2f}%   "
                f"5d {l['ret_5d'] or 0:+6.2f}%   "
                f"20d {l['ret_20d'] or 0:+6.2f}%"
            )
        print()

    # === 2. 가속 시그널 ===
    print("■ 2. 다음 트렌드 후보 A — 가속 시그널\n")
    print("    (단기 1d 평균을 중기 20d 평균과 비교. 최근 며칠 사이 모멘텀이 폭발한 섹터)\n")
    accel = []
    for s in summary:
        if abs(s["avg_20d"]) >= 0.5:
            ratio = s["avg_1d"] / s["avg_20d"]
            accel.append((ratio, s))
    accel.sort(key=lambda x: x[0], reverse=True)
    if not accel:
        print("    (데이터 부족)")
    for ratio, s in accel[:5]:
        arrow = "▲" if s["avg_1d"] > s["avg_20d"] else "▼"
        print(
            f"    {arrow} {s['key']:<22} 가속비 {ratio:>+6.2f}x  "
            f"20d {s['avg_20d']:+5.2f}%  →  1d {s['avg_1d']:+5.2f}%"
        )
    print()

    # === 3. 스필오버 (핫 섹터의 lag 종목) ===
    print("■ 3. 다음 트렌드 후보 B — 스필오버 후보\n")
    print("    (Top3 섹터 안에서 아직 평균만큼 못 따라간 종목 — 늦게 합류할 가능성)\n")
    found = False
    for s in summary[:3]:
        if s["n"] < 3:
            continue
        laggards = [
            l for l in s["items"]
            if l["ret_1d"] is not None and l["ret_1d"] < s["avg_1d"] - 1.0
        ]
        laggards.sort(key=lambda x: x["ret_1d"])
        for l in laggards[:2]:
            found = True
            print(
                f"    {s['key']:<22} {l['ticker']:<7} {(l['name'] or '')[:14]:<14}  "
                f"1d {l['ret_1d']:+5.2f}%  (섹터 평균 {s['avg_1d']:+5.2f}%, 5d {l['ret_5d'] or 0:+5.2f}%)"
            )
    if not found:
        print("    (해당 종목 없음 — 핫 섹터가 균등하게 상승 중)")
    print()

    # === 4. 개별 돌파 ===
    print("■ 4. 다음 트렌드 후보 C — 개별 돌파\n")
    print("    (현재가가 직전 20거래일 최고가를 넘어선 종목)\n")
    breakouts = conn.execute(
        f"""
        WITH p AS (
            SELECT asset_id, date, close,
                   ROW_NUMBER() OVER (
                       PARTITION BY asset_id ORDER BY date DESC
                   ) AS rn
            FROM price_history
        ),
        latest AS (SELECT asset_id, close AS cur FROM p WHERE rn = 1),
        ref AS (
            SELECT asset_id, MAX(close) AS hi
            FROM p WHERE rn BETWEEN 2 AND {RN_20D}
            GROUP BY asset_id
        )
        SELECT a.ticker, a.name, a.country, a.sector,
               ROUND((l.cur / r.hi - 1) * 100, 2) AS pct
        FROM latest l
        JOIN ref r ON r.asset_id = l.asset_id
        JOIN assets a ON a.asset_id = l.asset_id
        WHERE l.cur > r.hi
        ORDER BY pct DESC
        LIMIT 10
        """
    ).fetchall()
    if not breakouts:
        print("    (없음)")
    for b in breakouts:
        print(
            f"    {b['country']:<3} {b['ticker']:<7} {(b['name'] or '')[:14]:<14}  "
            f"20일 고가 +{b['pct']:>4.2f}%  ({b['sector']})"
        )
    print()

    print(bar)
    print(" 주의: 가격 데이터만 사용한 룰 기반 신호. 뉴스/거시/펀더멘털 근거 없음.")
    print("       인과 추론·신뢰도 산출은 LLM 통합 후 추가 (기획서 19.3).")
    print(bar)


if __name__ == "__main__":
    main()
