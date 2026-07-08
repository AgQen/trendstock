"""분석 결과 JSON -> SQLite 영속화.

입력 JSON 구조 (기획서 19.3.1 변형):
{
  "analysis_date": "2026-05-14",
  "model_name": "manual-by-claude-code" | "claude-sonnet-4-6" | ...,
  "current_trends": [
    {
      "rank": 1,
      "title": "...",
      "summary": "...",
      "category": "AI 메모리",
      "confidence": 85,
      "causal_chain": [{"step_no": 1, "statement": "...", "confidence": 90}, ...],
      "disconfirming_hypotheses": ["...", "..."],
      "evidence": {"price": "...", "volume": "..."},
      "recommendations": [
        {
          "rank": 1, "ticker": "MU", "grade": "Strong Buy",
          "rationale": "메모리 3사 막내, P/E 38",
          "fundamentals_score": 8,
          "fundamentals": {"revenue_yoy": 196.3, "op_margin": 67.6, ...}
        },
        ...
      ]
    }
  ],
  "predicted_trends": [ {... same shape ...} ]
}

진입 시점 종가는 DB의 price_history에서 자동 조회.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .db import get_conn, init_db, now_iso


def _latest_close(conn, asset_id: int) -> float | None:
    row = conn.execute(
        "SELECT close FROM price_history WHERE asset_id = ? "
        "ORDER BY date DESC LIMIT 1",
        (asset_id,),
    ).fetchone()
    return float(row["close"]) if row else None


def _asset_id(conn, ticker: str) -> int | None:
    # 한국 종목은 .KS / .KQ 접미사 떼기 (yfinance 접미사 변환)
    raw_ticker = ticker.replace(".KS", "").replace(".KQ", "")
    row = conn.execute(
        "SELECT asset_id FROM assets WHERE ticker = ?",
        (raw_ticker,),
    ).fetchone()
    return row["asset_id"] if row else None


def save(analysis: dict) -> int:
    """분석 dict를 받아 snapshot/trends/recommendations에 박아넣고 snapshot_id 반환."""
    init_db()
    date = analysis["analysis_date"]
    model = analysis.get("model_name") or "manual-by-claude-code"

    with get_conn() as conn:
        # 기존 같은 날짜 스냅샷 있으면 교체 (idempotent)
        old = conn.execute(
            "SELECT snapshot_id FROM analysis_snapshots WHERE analysis_date = ?",
            (date,),
        ).fetchone()
        if old:
            old_id = old["snapshot_id"]
            # 종속 데이터 삭제
            conn.execute(
                "DELETE FROM recommendations WHERE snapshot_id = ?", (old_id,)
            )
            conn.execute(
                "DELETE FROM predicted_trends WHERE snapshot_id = ?", (old_id,)
            )
            conn.execute(
                "DELETE FROM analysis_snapshots WHERE snapshot_id = ?", (old_id,)
            )

        # 스냅샷
        cur = conn.execute(
            "INSERT INTO analysis_snapshots "
            "(analysis_date, model_name, raw_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (date, model, json.dumps(analysis, ensure_ascii=False), now_iso()),
        )
        snapshot_id = cur.lastrowid

        # 트렌드 (current + predicted)
        for kind in ("current", "predicted"):
            key = f"{kind}_trends"
            for t in analysis.get(key, []):
                # timeframe 기본값: current=ongoing, predicted=imminent
                default_tf = "ongoing" if kind == "current" else "imminent"
                cur = conn.execute(
                    """
                    INSERT INTO predicted_trends
                      (snapshot_id, analysis_date, kind, rank, title, summary,
                       category, timeframe, confidence,
                       causal_chain_json, disconfirming_json, evidence_json,
                       trend_score, trend_direction, secondary_effect, trend_risk,
                       tier1_json, tier2_json, action_label, cycle_adjustment)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id, date, kind, t["rank"], t["title"],
                        t.get("summary"), t.get("category"),
                        t.get("timeframe") or default_tf,
                        t.get("confidence"),
                        json.dumps(t.get("causal_chain", []), ensure_ascii=False),
                        json.dumps(t.get("disconfirming_hypotheses", []),
                                   ensure_ascii=False),
                        json.dumps(t.get("evidence", {}), ensure_ascii=False),
                        t.get("trend_score"), t.get("trend_direction"),
                        t.get("secondary_effect"), t.get("trend_risk"),
                        json.dumps(t.get("tier1_tickers", []), ensure_ascii=False),
                        json.dumps(t.get("tier2_tickers", []), ensure_ascii=False),
                        t.get("action_label"), t.get("cycle_adjustment"),
                    ),
                )
                trend_id = cur.lastrowid

                # 추천 종목
                for r in t.get("recommendations", []):
                    aid = _asset_id(conn, r["ticker"])
                    if aid is None:
                        print(f"  [WARN] 미등록 티커 스킵: {r['ticker']} "
                              f"(트렌드 '{t['title']}')")
                        continue
                    entry = _latest_close(conn, aid)
                    if entry is None:
                        print(f"  [WARN] 가격 데이터 없음: {r['ticker']}")
                        continue
                    conn.execute(
                        """
                        INSERT INTO recommendations
                          (trend_id, snapshot_id, analysis_date, asset_id, rank,
                           grade, rationale, entry_close,
                           fundamentals_score, fundamentals_json, detail_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            trend_id, snapshot_id, date, aid, r.get("rank"),
                            r.get("grade"), r.get("rationale"), entry,
                            r.get("fundamentals_score"),
                            json.dumps(r.get("fundamentals", {}),
                                       ensure_ascii=False),
                            json.dumps(r.get("detail"), ensure_ascii=False)
                            if r.get("detail") else None,
                        ),
                    )
        conn.commit()

    print(f"  [OK] snapshot_id={snapshot_id}  date={date}")
    return snapshot_id


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m collectors.save_analysis <path-to-analysis.json>")
        sys.exit(1)
    path = Path(sys.argv[1])
    analysis = json.loads(path.read_text(encoding="utf-8"))
    save(analysis)


if __name__ == "__main__":
    main()
