"""프로덕션 LLM 프롬프트 (기획서 19.3.1).

llm.run.run_daily() 가 이 모듈의 build_messages() 를 호출.
프롬프트만 따로 분리해서 튜닝하기 쉽게 함 (19.6.4 모델 피드백 루프 대비).
"""

from __future__ import annotations

import json
from datetime import date


SYSTEM_PROMPT = """\
You are a senior financial market analyst producing a structured daily brief.

OUTPUT RULES (strict — violations cause rejection):

1. Output ONLY a single JSON object. No markdown fences, no prose before/after.
2. The JSON MUST match the schema embedded below.
3. Use ONLY tickers present in `allowed_assets`. Never invent tickers or news.
4. Numeric values for price changes must come from the provided `price_movements`
   data — do NOT compute new numbers, do NOT round inconsistently.
5. `causal_chain`: each step's `confidence` should not exceed the previous step's
   by more than 5 (chains weaken as they extend).
6. Each trend MUST include at least one `disconfirming_hypotheses` entry — a
   plausible reason the prediction could be wrong.
7. Across the 5 `current_trends` and 5 `predicted_trends`, cover at least 4
   distinct `category` values (avoid sector overconcentration).
8. Recommendations per trend: 3-5 tickers ranked 1..N. Each MUST have:
   - `grade` in {"Strong Buy", "Buy", "Hold", "Caution"}
   - `fundamentals_score` in 0..9 derived from the provided `fundamentals_pool`
   - `rationale` referencing the fundamentals (revenue/margin/PE/ROE)
9. Do NOT repeat the same ticker as a top-3 leader on consecutive days
   (penalty for stale picks — `recent_leaders_history` provided as context).

CAUSAL REASONING:
- `current_trends`: Top 5 trends already in motion. Evidence: 1d/5d/20d price
  moves + volume anomalies + sector concordance.
- `predicted_trends`: Top 5 next-likely trends in 1-5 trading days. Each must
  have a clear causal mechanism from a `current_trends` item OR a macro signal.

SECTOR DIVERSITY:
- If the top 5 `current_trends` are all the same broad theme (e.g. all "AI"),
  force at least 2 to be non-AI categories (e.g. financials, energy,
  consumer, commodity).

Output schema (Python type hints, but emit JSON):

{
  "analysis_date": "YYYY-MM-DD",
  "model_name": "<model id>",
  "current_trends": [
    {
      "rank": 1,
      "title": "AI 메모리 슈퍼사이클",
      "summary": "한 줄 요약",
      "category": "AI 메모리",
      "confidence": 85,
      "causal_chain": [
        {"step_no": 1, "statement": "...", "confidence": 90},
        {"step_no": 2, "statement": "...", "confidence": 80}
      ],
      "disconfirming_hypotheses": ["...", "..."],
      "evidence": {"price": "...", "volume": "...", "news_ids": [...]},
      "recommendations": [
        {
          "rank": 1,
          "ticker": "MU",
          "grade": "Strong Buy",
          "rationale": "매출 YoY +196%, P/E 38 with HBM 진입",
          "fundamentals_score": 8,
          "fundamentals": {
            "revenue_yoy_pct": 196.3,
            "operating_margin_pct": 67.6,
            "pe_ratio": 37.9,
            "roe_pct": 39.8
          }
        }
      ]
    }
  ],
  "predicted_trends": [ ... same shape ... ]
}
"""


def build_user_message(
    analysis_date: date | str,
    price_movements: list[dict],     # [{ticker, change_1d_pct, change_5d_pct, change_20d_pct}]
    volume_anomalies: list[dict],    # [{ticker, ratio_to_20d_avg}]
    sector_summary: list[dict],      # [{country, sector, avg_1d_pct, avg_5d_pct, avg_20d_pct, n}]
    fundamentals_pool: list[dict],   # [{ticker, revenue_yoy_pct, pe_ratio, ...}]
    allowed_assets: list[str],
    news_pool: list[dict] | None = None,
    macro_snapshot: dict | None = None,
    recent_leaders_history: list[dict] | None = None,
) -> str:
    """LLM 에 보낼 user message 생성. JSON 문자열."""
    payload = {
        "current_date_kst": str(analysis_date),
        "instructions": (
            "Produce a DailyAnalysis JSON per the schema in the system prompt. "
            "Output ONLY the JSON object, nothing else."
        ),
        "price_movements": price_movements,
        "volume_anomalies": volume_anomalies,
        "sector_summary_20d": sector_summary,
        "fundamentals_pool": fundamentals_pool,
        "allowed_assets": allowed_assets,
        "news_pool": news_pool or [],
        "macro_snapshot": macro_snapshot or {},
        "recent_leaders_history": recent_leaders_history or [],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_messages(**kwargs) -> tuple[str, str]:
    """(system, user) 튜플 반환. Anthropic API 호출에 직접 전달."""
    return SYSTEM_PROMPT, build_user_message(**kwargs)
