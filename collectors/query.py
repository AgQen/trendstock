"""저장 결과 sanity check."""

from .db import get_conn


def main() -> None:
    with get_conn() as conn:
        print("\n=== 자산 통계 ===")
        rows = conn.execute(
            "SELECT country, COUNT(*) AS n FROM assets "
            "WHERE is_active = 1 GROUP BY country ORDER BY country"
        ).fetchall()
        for r in rows:
            print(f"  {r['country']:<3} : {r['n']:>3}건")

        print("\n=== 일일 변동률 Top 10 (절댓값) ===")
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT p.asset_id, p.date, p.close,
                       LAG(p.close) OVER (
                           PARTITION BY p.asset_id ORDER BY p.date
                       ) AS prev_close,
                       ROW_NUMBER() OVER (
                           PARTITION BY p.asset_id ORDER BY p.date DESC
                       ) AS rn
                FROM price_history p
            )
            SELECT a.ticker, a.name, a.country, r.date, r.close,
                   ROUND((r.close / r.prev_close - 1) * 100, 2) AS chg_pct
            FROM ranked r
            JOIN assets a ON a.asset_id = r.asset_id
            WHERE r.rn = 1 AND r.prev_close IS NOT NULL
            ORDER BY ABS(r.close / r.prev_close - 1) DESC
            LIMIT 10
            """
        ).fetchall()
        for r in rows:
            sign = "+" if (r["chg_pct"] or 0) >= 0 else ""
            print(
                f"  {r['country']:<3} {r['ticker']:<7} "
                f"{(r['name'] or ''):<20} "
                f"{r['date']}  {sign}{r['chg_pct']:>6.2f}%"
            )

        print("\n=== 최근 수집 로그 ===")
        rows = conn.execute(
            """
            SELECT source, started_at, finished_at, rows_added, error
            FROM collection_log
            ORDER BY log_id DESC
            LIMIT 5
            """
        ).fetchall()
        for r in rows:
            err = f"  ERR={r['error']}" if r["error"] else ""
            print(
                f"  {r['source']:<14} {r['started_at']}  "
                f"+{r['rows_added']} rows{err}"
            )

        print("\n=== 각 자산의 데이터 보유일수 (요약) ===")
        rows = conn.execute(
            """
            SELECT a.country, COUNT(DISTINCT p.date) AS days, COUNT(*) AS rows
            FROM price_history p
            JOIN assets a ON a.asset_id = p.asset_id
            GROUP BY a.country
            """
        ).fetchall()
        for r in rows:
            print(
                f"  {r['country']:<3} 영업일 종류={r['days']:>3}  "
                f"총 rows={r['rows']:>5}"
            )


if __name__ == "__main__":
    main()
