"""월별 가중치 자동 조정.

각 차원(펀더/모멘텀/타이밍/거래량)의 점수가 실제 30일 적중(hit_30d)과
얼마나 상관되는지 계산해, 예측력 높은 차원 가중치를 올리고
예측력 낮은 차원은 낮춘다.

조정 규격:
  - 최소 30건 이상의 검증 완료 데이터 필요
  - 차원당 최대 ±0.15 조정 (안정성)
  - 가중치 범위 [0.3, 2.0] 클램프
  - 같은 달에 이미 조정된 경우 스킵

실행: python -m collectors.weight_tune
"""

from __future__ import annotations

import json
from datetime import date as date_cls

from .db import get_conn, init_db, load_weights, now_iso, DEFAULT_WEIGHTS

MIN_N = 30          # 최소 검증 건수
MAX_ADJ = 0.15      # 차원당 최대 조정폭
W_MIN, W_MAX = 0.3, 2.0

DIMS = [
    ("fundamentals", "fund_weight"),
    ("momentum",     "momentum_weight"),
    ("timing",       "timing_weight"),
    ("volume",       "volume_weight"),
    ("rs",           "rs_weight"),
    ("risk",         "risk_weight"),
]


def _avg(lst: list) -> float | None:
    return sum(lst) / len(lst) if lst else None


def tune(dry_run: bool = False) -> dict | None:
    init_db()
    today = date_cls.today().isoformat()
    ym = today[:7]  # YYYY-MM

    with get_conn() as conn:
        # 이미 이번 달에 조정했으면 스킵
        existing = conn.execute(
            "SELECT weight_id FROM rule_weights WHERE effective_date LIKE ?",
            (ym + "%",),
        ).fetchone()
        if existing:
            print(f"  [SKIP] {ym} 에 이미 가중치 조정됨. 월 1회만 실행.")
            return None

        # 지난 60일 검증 완료 데이터
        recs = conn.execute(
            """
            SELECT hit_30d, rating_breakdown_json
            FROM recommendations
            WHERE hit_30d IS NOT NULL
              AND analysis_date >= date(?, '-60 days')
              AND rating_breakdown_json IS NOT NULL
            """,
            (today,),
        ).fetchall()

        if len(recs) < MIN_N:
            print(f"  [SKIP] 검증 완료 데이터 {len(recs)}건 < 필요 {MIN_N}건. 다음 달 재시도.")
            return None

        print(f"  검증 데이터 {len(recs)}건 기반으로 가중치 분석 중...")

        # 차원별 상관 분석
        current = load_weights(conn)
        new_weights = current.copy()
        adjustments = {}

        for dim_key, weight_key in DIMS:
            hit_scores, miss_scores = [], []
            for rec in recs:
                bd = json.loads(rec["rating_breakdown_json"] or "null")
                if not bd:
                    continue
                score = bd.get("dimensions", {}).get(dim_key, {}).get("score")
                if score is None:
                    continue
                if rec["hit_30d"] == 1:
                    hit_scores.append(score)
                else:
                    miss_scores.append(score)

            if not hit_scores or not miss_scores:
                adjustments[weight_key] = 0.0
                continue

            avg_hit  = _avg(hit_scores)
            avg_miss = _avg(miss_scores)
            diff = avg_hit - avg_miss  # 양수 = 이 차원이 적중과 양의 상관

            # diff 크기에 비례해 조정 (-MAX_ADJ ~ +MAX_ADJ)
            adj = max(-MAX_ADJ, min(MAX_ADJ, diff * 0.1))
            new_w = max(W_MIN, min(W_MAX, current[weight_key] + adj))
            adjustments[weight_key] = round(adj, 3)
            new_weights[weight_key] = round(new_w, 3)

            hit_n, miss_n = len(hit_scores), len(miss_scores)
            print(f"  {dim_key:<14}: hit avg={avg_hit:+.2f}(n={hit_n}) "
                  f"miss avg={avg_miss:+.2f}(n={miss_n}) "
                  f"diff={diff:+.2f} → adj={adj:+.3f} "
                  f"{current[weight_key]:.2f}→{new_weights[weight_key]:.2f}")

        note = (
            f"auto-tune {today}: "
            + ", ".join(f"{k}={v:+.3f}" for k, v in adjustments.items())
        )

        if dry_run:
            print(f"\n  [DRY-RUN] 실제 저장 안 함. note={note}")
            return new_weights

        conn.execute(
            "INSERT INTO rule_weights "
            "(effective_date, fund_weight, momentum_weight, timing_weight, volume_weight, rs_weight, risk_weight, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (today,
             new_weights["fund_weight"], new_weights["momentum_weight"],
             new_weights["timing_weight"], new_weights["volume_weight"],
             new_weights["rs_weight"], new_weights["risk_weight"],
             note, now_iso()),
        )
        conn.commit()
        print(f"\n  [OK] 새 가중치 저장: {new_weights}")
        return new_weights


def main() -> None:
    import sys
    dry = "--dry" in sys.argv
    result = tune(dry_run=dry)
    if result:
        print("\n[DONE] 가중치 조정 완료.")
    else:
        print("\n[DONE] 조정 없음.")


if __name__ == "__main__":
    main()
