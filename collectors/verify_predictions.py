"""적중률 자동 검증 (cron 용).

매일 실행. 각 recommendation 에 대해:
  - prediction_date + 7/30/90 거래일 후의 종가가 DB에 존재하면
  - 알파 = (종목 수익률) - (벤치마크 수익률)을 계산해 저장.
  - hit_Nd = 1 if alpha > 0 else 0.

벤치마크: US -> SPY, KR -> 069500 (KODEX 200).

idempotent: 이미 검증된 시점(close_Nd 값 존재)은 건너뜀.
"""

from __future__ import annotations

import json
from datetime import datetime

from .db import finish_log, get_conn, init_db, now_iso, start_log

HORIZONS = [("7d", 7), ("30d", 30), ("90d", 90)]


def _benchmark_for(country: str) -> str:
    return "SPY" if country == "US" else "069500"


def _close_at_offset(conn, asset_id: int, base_date: str,
                     trading_days: int) -> tuple[str, float] | None:
    """base_date 기준 trading_days 거래일 이후의 종가 (DB에 있으면)."""
    row = conn.execute(
        """
        SELECT date, close
        FROM price_history
        WHERE asset_id = ? AND date > ?
        ORDER BY date ASC
        LIMIT 1 OFFSET ?
        """,
        (asset_id, base_date, max(trading_days - 1, 0)),
    ).fetchone()
    if not row:
        return None
    return row["date"], float(row["close"])


def verify() -> dict:
    init_db()
    log_id = start_log("verify_predictions")

    horizons_count = {"7d": 0, "30d": 0, "90d": 0}
    verified_total = 0
    error: str | None = None

    try:
        with get_conn() as conn:
            # 후보: close_90d 가 아직 NULL인 것 + 30일 미만 경과한 것 모두
            recs = conn.execute(
                """
                SELECT r.rec_id, r.analysis_date, r.asset_id, r.entry_close,
                       a.country, a.ticker
                FROM recommendations r
                JOIN assets a ON a.asset_id = r.asset_id
                WHERE r.close_90d IS NULL
                ORDER BY r.analysis_date ASC, r.rec_id ASC
                """
            ).fetchall()

            for rec in recs:
                changed = False
                updates: dict[str, float | None | int] = {}

                # 벤치마크 asset_id
                bench_ticker = _benchmark_for(rec["country"])
                bench_row = conn.execute(
                    "SELECT asset_id FROM assets WHERE ticker = ?",
                    (bench_ticker,),
                ).fetchone()
                if not bench_row:
                    continue
                bench_id = bench_row["asset_id"]

                # 분석 시점 벤치마크 종가 (or 가장 가까운 과거)
                bench_entry_row = conn.execute(
                    """
                    SELECT close FROM price_history
                    WHERE asset_id = ? AND date <= ?
                    ORDER BY date DESC LIMIT 1
                    """,
                    (bench_id, rec["analysis_date"]),
                ).fetchone()
                if not bench_entry_row:
                    continue
                bench_entry = float(bench_entry_row["close"])

                # 현재 row 상태 (이미 채워진 horizon은 건너뛰기)
                cur_state = conn.execute(
                    "SELECT close_7d, close_30d, close_90d FROM recommendations "
                    "WHERE rec_id = ?",
                    (rec["rec_id"],),
                ).fetchone()

                for key, days in HORIZONS:
                    col = f"close_{key}"
                    if cur_state[col] is not None:
                        continue

                    stock_at = _close_at_offset(
                        conn, rec["asset_id"], rec["analysis_date"], days
                    )
                    bench_at = _close_at_offset(
                        conn, bench_id, rec["analysis_date"], days
                    )
                    if not stock_at or not bench_at:
                        continue  # 아직 데이터 없음

                    _, stock_close = stock_at
                    _, bench_close = bench_at

                    stock_ret = stock_close / rec["entry_close"] - 1
                    bench_ret = bench_close / bench_entry - 1
                    alpha = stock_ret - bench_ret
                    hit = 1 if alpha > 0 else 0

                    updates[f"close_{key}"] = stock_close
                    updates[f"bench_{key}"] = bench_close
                    updates[f"alpha_{key}"] = alpha
                    updates[f"hit_{key}"] = hit
                    horizons_count[key] += 1
                    changed = True

                if changed:
                    set_clause = ", ".join(f"{k} = ?" for k in updates)
                    params = list(updates.values()) + [now_iso(), rec["rec_id"]]
                    conn.execute(
                        f"UPDATE recommendations SET {set_clause}, "
                        f"verified_at = ? WHERE rec_id = ?",
                        params,
                    )
                    verified_total += 1

            conn.commit()

        # 통계 출력
        print(f"  [OK] 검증 row 수: {verified_total}")
        print(f"       horizon 별: {horizons_count}")
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        print(f"  [FAIL] {error}")

    # 검증 로그 저장
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO verification_log "
            "(run_date, verified_count, horizons_json, error, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.utcnow().date().isoformat(),
                verified_total,
                json.dumps(horizons_count),
                error,
                now_iso(),
            ),
        )
        conn.commit()

    finish_log(log_id, verified_total, 0, error)
    return {"verified": verified_total, **horizons_count, "error": error}


def stats() -> None:
    """현재까지 누적된 적중률 통계 출력."""
    init_db()
    with get_conn() as conn:
        print("\n=== 누적 적중률 (검증 완료된 row 기준) ===")
        for key, _ in HORIZONS:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS n,
                       AVG(CAST(hit_{key} AS REAL)) * 100 AS hit_rate,
                       AVG(alpha_{key}) * 100 AS avg_alpha
                FROM recommendations
                WHERE hit_{key} IS NOT NULL
                """
            ).fetchone()
            if row["n"]:
                print(f"  {key:>4}  n={row['n']:>4}  "
                      f"적중률 {row['hit_rate']:.1f}%  "
                      f"평균 알파 {row['avg_alpha']:+.2f}%")
            else:
                print(f"  {key:>4}  데이터 없음 (분석 후 {key} 미경과)")

        print("\n=== 신뢰도 구간별 30일 적중률 ===")
        rows = conn.execute(
            """
            WITH joined AS (
                SELECT r.hit_30d, r.alpha_30d, t.confidence
                FROM recommendations r
                JOIN predicted_trends t ON t.trend_id = r.trend_id
                WHERE r.hit_30d IS NOT NULL
            )
            SELECT
                CASE
                    WHEN confidence >= 80 THEN '80-100%'
                    WHEN confidence >= 60 THEN '60-79%'
                    WHEN confidence >= 40 THEN '40-59%'
                    ELSE '0-39%'
                END AS bucket,
                COUNT(*) AS n,
                AVG(CAST(hit_30d AS REAL)) * 100 AS hit,
                AVG(alpha_30d) * 100 AS alpha
            FROM joined
            GROUP BY bucket
            ORDER BY bucket DESC
            """
        ).fetchall()
        if not rows:
            print("  (30일 검증 데이터 누적 후 표시)")
        for r in rows:
            print(f"  신뢰도 {r['bucket']:<8}  n={r['n']:>3}  "
                  f"적중률 {r['hit']:.1f}%  알파 {r['alpha']:+.2f}%")


def main() -> None:
    import sys as _sys
    if "stats" in _sys.argv:
        stats()
    else:
        verify()
        stats()


if __name__ == "__main__":
    main()
