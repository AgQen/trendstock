"""DB -> docs/data/analysis.json 추출.

웹 앱이 fetch 해서 렌더링하는 단일 JSON 파일을 만든다.
매일 run_all → save_analysis (또는 llm.run) 다음에 호출하면 새 데이터가 폰에 반영됨.
"""

from __future__ import annotations

import json
from pathlib import Path

from .db import get_conn, init_db, load_weights, weight_history
from .token_logger import aggregates as token_aggregates

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "docs" / "data" / "analysis.json"


def _trend_with_recs(conn, trend_row):
    recs = conn.execute(
        """
        SELECT a.ticker, a.name, a.country, r.rank, r.grade, r.rationale,
               r.entry_close, r.fundamentals_score, r.fundamentals_json,
               r.rating_score, r.rating_breakdown_json, r.detail_json,
               r.close_7d, r.alpha_7d, r.hit_7d,
               r.close_30d, r.alpha_30d, r.hit_30d
        FROM recommendations r
        JOIN assets a ON a.asset_id = r.asset_id
        WHERE r.trend_id = ?
        ORDER BY r.rank ASC
        """,
        (trend_row["trend_id"],),
    ).fetchall()

    recs_out = []
    for r in recs:
        recs_out.append({
            "ticker": r["ticker"],
            "name": r["name"],
            "country": r["country"],
            "rank": r["rank"],
            "grade": r["grade"],
            "rationale": r["rationale"],
            "entry_close": r["entry_close"],
            "fundamentals_score": r["fundamentals_score"],
            "fundamentals": json.loads(r["fundamentals_json"] or "{}"),
            "rating_score": r["rating_score"],
            "rating_breakdown": json.loads(r["rating_breakdown_json"] or "null"),
            "detail": json.loads(r["detail_json"] or "null"),
            "validation": {
                "close_7d": r["close_7d"],  "alpha_7d": r["alpha_7d"],  "hit_7d": r["hit_7d"],
                "close_30d": r["close_30d"], "alpha_30d": r["alpha_30d"], "hit_30d": r["hit_30d"],
            }
        })

    # timeframe 컬럼이 있을 때만 (구버전 DB 호환)
    try:
        timeframe = trend_row["timeframe"]
    except (IndexError, KeyError):
        timeframe = None

    return {
        "trend_id": trend_row["trend_id"],
        "rank": trend_row["rank"],
        "title": trend_row["title"],
        "summary": trend_row["summary"],
        "category": trend_row["category"],
        "timeframe": timeframe,
        "confidence": trend_row["confidence"],
        "causal_chain": json.loads(trend_row["causal_chain_json"] or "[]"),
        "disconfirming_hypotheses": json.loads(trend_row["disconfirming_json"] or "[]"),
        "evidence": json.loads(trend_row["evidence_json"] or "{}"),
        "recommendations": recs_out,
    }


def export(date: str | None = None) -> Path:
    init_db()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_conn() as conn:
        if date:
            snap = conn.execute(
                "SELECT * FROM analysis_snapshots WHERE analysis_date = ?",
                (date,),
            ).fetchone()
        else:
            snap = conn.execute(
                "SELECT * FROM analysis_snapshots "
                "ORDER BY analysis_date DESC LIMIT 1"
            ).fetchone()

        if not snap:
            raise RuntimeError("저장된 분석 스냅샷이 없음. save_analysis 먼저 실행.")

        current = conn.execute(
            "SELECT * FROM predicted_trends "
            "WHERE snapshot_id = ? AND kind = 'current' ORDER BY rank ASC",
            (snap["snapshot_id"],),
        ).fetchall()
        predicted = conn.execute(
            "SELECT * FROM predicted_trends "
            "WHERE snapshot_id = ? AND kind = 'predicted' ORDER BY rank ASC",
            (snap["snapshot_id"],),
        ).fetchall()

        # 시장 요약 (오늘 종가 기준 변동률 Top/Bottom)
        market = conn.execute(
            """
            WITH p AS (
                SELECT asset_id, date, close,
                       ROW_NUMBER() OVER (
                           PARTITION BY asset_id ORDER BY date DESC
                       ) AS rn
                FROM price_history
            )
            SELECT a.ticker, a.name, a.country, a.sector,
                   ROUND((MAX(CASE WHEN p.rn=1 THEN p.close END)
                          /MAX(CASE WHEN p.rn=2 THEN p.close END) - 1) * 100, 2) AS r1d
            FROM assets a JOIN p ON p.asset_id = a.asset_id
            WHERE p.rn <= 2 AND a.is_active = 1
            GROUP BY a.asset_id
            HAVING r1d IS NOT NULL
            ORDER BY r1d DESC
            """
        ).fetchall()
        top = [dict(r) for r in market[:5]]
        bottom = [dict(r) for r in market[-5:][::-1]]

        # 누적 적중률 (검증 완료된 것만)
        accuracy = {}
        for k in ("7d", "30d", "90d"):
            row = conn.execute(
                f"SELECT COUNT(*) AS n, "
                f"AVG(CAST(hit_{k} AS REAL))*100 AS hit, "
                f"AVG(alpha_{k})*100 AS alpha "
                f"FROM recommendations WHERE hit_{k} IS NOT NULL"
            ).fetchone()
            accuracy[k] = {
                "n": row["n"],
                "hit_rate_pct": round(row["hit"], 1) if row["hit"] is not None else None,
                "avg_alpha_pct": round(row["alpha"], 2) if row["alpha"] is not None else None,
            }

    # 히스토리 — 모든 과거 스냅샷의 추천 (날짜별 그룹)
    with get_conn() as hconn:
        all_recs = hconn.execute(
            """
            SELECT s.analysis_date, s.snapshot_id,
                   t.kind, t.title AS trend_title, t.category, t.timeframe,
                   t.confidence,
                   r.rec_id, r.rank, r.grade, r.rationale,
                   r.entry_close, r.rating_score, r.fundamentals_score,
                   r.close_7d, r.close_30d, r.close_90d,
                   r.alpha_7d, r.alpha_30d, r.alpha_90d,
                   r.hit_7d, r.hit_30d, r.hit_90d,
                   r.verified_at,
                   a.ticker, a.name, a.country
            FROM analysis_snapshots s
            JOIN predicted_trends t ON t.snapshot_id = s.snapshot_id
            JOIN recommendations  r ON r.trend_id    = t.trend_id
            JOIN assets a            ON a.asset_id   = r.asset_id
            ORDER BY s.analysis_date DESC, t.kind, t.rank, r.rank
            """
        ).fetchall()

        # 각 종목의 가장 최신 가격 (히스토리에서 "현재가" 컬럼용)
        latest_prices = {
            r["ticker"]: {"price": r["close"], "date": r["date"]}
            for r in hconn.execute(
                """
                WITH p AS (
                    SELECT asset_id, date, close,
                           ROW_NUMBER() OVER (
                               PARTITION BY asset_id ORDER BY date DESC
                           ) AS rn
                    FROM price_history
                )
                SELECT a.ticker, p.close, p.date
                FROM p JOIN assets a ON a.asset_id = p.asset_id
                WHERE p.rn = 1
                """
            ).fetchall()
        }

    history_by_date: dict = {}
    for r in all_recs:
        d = r["analysis_date"]
        latest = latest_prices.get(r["ticker"]) or {}
        cur_price = latest.get("price")
        cur_date = latest.get("date")
        # 진입가 대비 현재 수익률
        cur_ret = None
        if cur_price and r["entry_close"]:
            cur_ret = round((cur_price / r["entry_close"] - 1) * 100, 2)
        # ! 알림 트리거: |alpha_30d| >= 10% AND hit_30d=1
        alert = bool(
            r["alpha_30d"] is not None
            and abs(r["alpha_30d"]) * 100 >= 10
            and r["hit_30d"] == 1
        )
        rec_dict = {
            "ticker": r["ticker"],
            "name": r["name"],
            "country": r["country"],
            "trend_title": r["trend_title"],
            "trend_kind": r["kind"],
            "category": r["category"],
            "timeframe": r["timeframe"],
            "trend_confidence": r["confidence"],
            "grade": r["grade"],
            "rating_score": r["rating_score"],
            "fundamentals_score": r["fundamentals_score"],
            "rank": r["rank"],
            "rationale": r["rationale"],
            "entry_close": r["entry_close"],
            "entry_date": r["analysis_date"],
            "current_close": cur_price,
            "current_date": cur_date,
            "current_return_pct": cur_ret,
            "close_7d": r["close_7d"], "alpha_7d": r["alpha_7d"], "hit_7d": r["hit_7d"],
            "close_30d": r["close_30d"], "alpha_30d": r["alpha_30d"], "hit_30d": r["hit_30d"],
            "close_90d": r["close_90d"], "alpha_90d": r["alpha_90d"], "hit_90d": r["hit_90d"],
            "verified_at": r["verified_at"],
            "alert": alert,
        }
        history_by_date.setdefault(d, []).append(rec_dict)

    history = [
        {
            "date": d,
            "recommendations": recs,
            "alert_count": sum(1 for r in recs if r["alert"]),
        }
        for d, recs in sorted(history_by_date.items(), reverse=True)
    ]

    payload = {
        "analysis_date": snap["analysis_date"],
        "model_name": snap["model_name"],
        "generated_at": snap["created_at"],
        "summary": {
            "current_trends_count": len(current),
            "predicted_trends_count": len(predicted),
            "total_recommendations": sum(
                len(json.loads(t["causal_chain_json"] or "[]")) for t in current + predicted
            ),
            "top_movers_1d": top,
            "bottom_movers_1d": bottom,
        },
        "accuracy": accuracy,
        "tokens": token_aggregates(days=30),
        "weights": load_weights(conn),
        "weight_history": weight_history(conn),
        "current_trends": [_trend_with_recs(conn, t) for t in current],
        "predicted_trends": [_trend_with_recs(conn, t) for t in predicted],
        "history": history,
    }

    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  [OK] {OUT_PATH}  ({OUT_PATH.stat().st_size:,} bytes)")
    return OUT_PATH


def main() -> None:
    export()


if __name__ == "__main__":
    main()
