"""LLM 토큰 사용 자동 기록.

llm/run.py 같은 곳에서 Anthropic 응답 받자마자 호출.

비용 단가 (2026-05 기준, $/MTok):
  - claude-sonnet-4-6:  input $3,   output $15,   cache_read $0.30
  - claude-opus-4-7:    input $15,  output $75,   cache_read $1.50
  - claude-haiku-4-5:   input $1,   output $5,    cache_read $0.10
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .db import get_conn, init_db, now_iso

PRICING = {
    "claude-sonnet-4-6":   {"input": 3.0,  "output": 15.0, "cache_read": 0.30},
    "claude-opus-4-7":     {"input": 15.0, "output": 75.0, "cache_read": 1.50},
    "claude-haiku-4-5":    {"input": 1.0,  "output": 5.0,  "cache_read": 0.10},
}


def _kst_date() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


def _model_pricing(model: str) -> dict:
    # 정확 매칭 우선, 못 찾으면 prefix 매칭
    if model in PRICING:
        return PRICING[model]
    for key, p in PRICING.items():
        if model.startswith(key.split("-4")[0]):  # 'claude-sonnet', 'claude-opus' 등
            return p
    return PRICING["claude-sonnet-4-6"]  # default


def log_usage(
    category: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    note: str | None = None,
    date: str | None = None,
) -> float:
    """토큰 사용 기록 + 비용 계산. cost_usd 반환."""
    init_db()
    p = _model_pricing(model)
    cost = (
        (input_tokens - cached_input_tokens) * p["input"] / 1_000_000
        + cached_input_tokens * p["cache_read"] / 1_000_000
        + output_tokens * p["output"] / 1_000_000
    )
    date = date or _kst_date()

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO token_usage
              (date, category, model, input_tokens, cached_input_tokens,
               output_tokens, cost_usd, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (date, category, model, input_tokens, cached_input_tokens,
             output_tokens, cost, note, now_iso()),
        )
        conn.commit()
    return cost


def log_from_anthropic_response(category: str, model: str, resp, note: str | None = None) -> float:
    """Anthropic SDK 응답 객체를 받아 자동 기록."""
    usage = getattr(resp, "usage", None)
    if not usage:
        return 0.0
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    return log_usage(category, model, inp, out, cached, note)


def aggregates(days: int = 30) -> dict:
    """최근 N일 토큰 집계 (카테고리별 + 합계)."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT category,
                   SUM(input_tokens)        AS input_tok,
                   SUM(cached_input_tokens) AS cached_tok,
                   SUM(output_tokens)       AS output_tok,
                   SUM(cost_usd)            AS cost_usd,
                   COUNT(*)                 AS calls
            FROM token_usage
            WHERE date >= date('now', '-{days} days')
            GROUP BY category
            ORDER BY cost_usd DESC
            """
        ).fetchall()
        total_row = conn.execute(
            f"""
            SELECT SUM(input_tokens)  AS input_tok,
                   SUM(output_tokens) AS output_tok,
                   SUM(cost_usd)      AS cost_usd,
                   COUNT(*)           AS calls
            FROM token_usage
            WHERE date >= date('now', '-{days} days')
            """
        ).fetchone()

    return {
        "window_days": days,
        "by_category": [
            {
                "category": r["category"],
                "input_tokens": r["input_tok"] or 0,
                "cached_input_tokens": r["cached_tok"] or 0,
                "output_tokens": r["output_tok"] or 0,
                "cost_usd": round(r["cost_usd"] or 0, 4),
                "calls": r["calls"] or 0,
            }
            for r in rows
        ],
        "total": {
            "input_tokens": total_row["input_tok"] or 0,
            "output_tokens": total_row["output_tok"] or 0,
            "cost_usd": round(total_row["cost_usd"] or 0, 4),
            "cost_krw": int(round((total_row["cost_usd"] or 0) * 1400)),
            "calls": total_row["calls"] or 0,
        },
    }
