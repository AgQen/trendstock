"""LLM 일일 분석 자동 실행 (프로덕션).

전제: 환경변수 ANTHROPIC_API_KEY 설정.
실행: python -m llm.run [--date YYYY-MM-DD] [--model claude-sonnet-4-6]

흐름:
  1) DB에서 가격/거래량/섹터/펀더 컨텍스트 수집
  2) prompt.build_messages() 로 LLM 입력 구성
  3) Anthropic API 호출
  4) schema.DailyAnalysis 로 검증 (할루시네이션 방어 19.3.4)
  5) collectors.save_analysis.save() 로 DB에 박아넣기

검증 실패 시 1회 재시도 (다른 시드).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date as date_cls

# 패키지 import 경로 보장 (python -m llm.run 또는 직접 실행 모두 대응)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.db import get_conn, init_db
from collectors.save_analysis import save
from collectors.token_logger import log_from_anthropic_response
from llm.prompt import build_messages
from llm.schema import DailyAnalysis

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 16000


def collect_context(analysis_date: str) -> dict:
    """DB에서 LLM 입력에 필요한 컨텍스트 일괄 조회."""
    with get_conn() as conn:
        # 활성 자산 (allowed_assets)
        assets = conn.execute(
            "SELECT ticker, name, country, sector, asset_class "
            "FROM assets WHERE is_active = 1"
        ).fetchall()
        allowed = [a["ticker"] for a in assets]

        # 자산별 1d / 5d / 20d 수익률
        moves = conn.execute(
            """
            WITH p AS (
                SELECT asset_id, date, close,
                       ROW_NUMBER() OVER (
                           PARTITION BY asset_id ORDER BY date DESC
                       ) AS rn
                FROM price_history
            )
            SELECT a.ticker, a.country, a.sector,
                   MAX(CASE WHEN p.rn=1  THEN p.close END) AS c_now,
                   MAX(CASE WHEN p.rn=2  THEN p.close END) AS c_1d,
                   MAX(CASE WHEN p.rn=6  THEN p.close END) AS c_5d,
                   MAX(CASE WHEN p.rn=21 THEN p.close END) AS c_20d
            FROM assets a
            JOIN p ON p.asset_id = a.asset_id
            WHERE a.is_active = 1 AND p.rn <= 21
            GROUP BY a.asset_id
            """
        ).fetchall()

        def _ret(now, base):
            if now and base and base != 0:
                return round((now / base - 1) * 100, 2)
            return None

        price_movements = [
            {
                "ticker": r["ticker"],
                "country": r["country"],
                "sector": r["sector"],
                "close_now": r["c_now"],
                "change_1d_pct":  _ret(r["c_now"], r["c_1d"]),
                "change_5d_pct":  _ret(r["c_now"], r["c_5d"]),
                "change_20d_pct": _ret(r["c_now"], r["c_20d"]),
            }
            for r in moves if r["c_now"]
        ]

        # 거래량 이상 (오늘 vs 20일 평균)
        vol = conn.execute(
            """
            WITH p AS (
                SELECT asset_id, volume,
                       ROW_NUMBER() OVER (
                           PARTITION BY asset_id ORDER BY date DESC
                       ) AS rn
                FROM price_history
            ),
            today AS (SELECT asset_id, volume FROM p WHERE rn = 1),
            avg20 AS (
                SELECT asset_id, AVG(volume) AS av
                FROM p WHERE rn BETWEEN 2 AND 21
                GROUP BY asset_id
            )
            SELECT a.ticker, ROUND(t.volume / av.av, 2) AS ratio
            FROM today t
            JOIN avg20 av ON av.asset_id = t.asset_id
            JOIN assets a ON a.asset_id = t.asset_id
            WHERE av.av > 0 AND t.volume / av.av >= 1.5
            ORDER BY ratio DESC
            LIMIT 20
            """
        ).fetchall()
        volume_anomalies = [
            {"ticker": r["ticker"], "ratio_to_20d_avg": r["ratio"]}
            for r in vol
        ]

        # 섹터 요약 (간이)
        # 위 price_movements 에서 sector 별 평균을 즉시 계산해도 되지만
        # LLM 토큰 절약을 위해 이미 정렬된 형태로 압축 전달
        from collections import defaultdict
        sec = defaultdict(lambda: {"r1": [], "r5": [], "r20": [], "n": 0})
        for m in price_movements:
            if not m["sector"]:
                continue
            key = (m["country"], m["sector"])
            if m["change_1d_pct"]  is not None: sec[key]["r1"].append(m["change_1d_pct"])
            if m["change_5d_pct"]  is not None: sec[key]["r5"].append(m["change_5d_pct"])
            if m["change_20d_pct"] is not None: sec[key]["r20"].append(m["change_20d_pct"])
            sec[key]["n"] += 1

        sector_summary = []
        for (country, sector), d in sec.items():
            sector_summary.append({
                "country": country,
                "sector": sector,
                "n": d["n"],
                "avg_1d_pct":  round(sum(d["r1"]) / len(d["r1"]), 2)  if d["r1"]  else None,
                "avg_5d_pct":  round(sum(d["r5"]) / len(d["r5"]), 2)  if d["r5"]  else None,
                "avg_20d_pct": round(sum(d["r20"]) / len(d["r20"]), 2) if d["r20"] else None,
            })
        sector_summary.sort(key=lambda x: x["avg_1d_pct"] or 0, reverse=True)

        # 최근 7일간 leader history (반복 추천 페널티용)
        recent = conn.execute(
            """
            SELECT DISTINCT a.ticker, MAX(r.analysis_date) AS last_date,
                   COUNT(*) AS times
            FROM recommendations r
            JOIN assets a ON a.asset_id = r.asset_id
            WHERE r.rank <= 3 AND r.analysis_date >= date(?, '-7 days')
            GROUP BY a.ticker
            ORDER BY times DESC
            LIMIT 30
            """,
            (analysis_date,),
        ).fetchall()
        recent_leaders_history = [
            {"ticker": r["ticker"], "last_date": r["last_date"],
             "times_in_top3_last_7d": r["times"]}
            for r in recent
        ]

    return {
        "allowed_assets": allowed,
        "price_movements": price_movements,
        "volume_anomalies": volume_anomalies,
        "sector_summary": sector_summary,
        "fundamentals_pool": [],  # fundamentals.py 와 통합 시 채움
        "news_pool": [],          # NewsAPI 통합 시 채움
        "macro_snapshot": {},     # FRED 통합 시 채움
        "recent_leaders_history": recent_leaders_history,
    }


def call_claude(model: str, system: str, user: str,
                category: str = "daily_analysis",
                note: str | None = None) -> str:
    from anthropic import Anthropic
    client = Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # 토큰 사용 자동 기록
    try:
        cost = log_from_anthropic_response(category, model, resp, note=note)
        print(f"  [TOKEN] {category}  in={resp.usage.input_tokens} "
              f"out={resp.usage.output_tokens}  ≈ ${cost:.4f}")
    except Exception as e:
        print(f"  [WARN] 토큰 기록 실패: {e}")
    return resp.content[0].text


def _strip_code_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        parts = s.split("```", 2)
        s = parts[1] if len(parts) > 1 else s
        if s.lstrip().startswith("json"):
            s = s.lstrip()[4:]
        s = s.strip()
    return s


def run_daily(analysis_date: str | None = None,
              model: str = DEFAULT_MODEL) -> dict | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  [SKIP] ANTHROPIC_API_KEY 미설정 — LLM 분석 건너뜀.")
        print("         (룰 기반 등급/적중률은 정상 갱신됨)")
        return None

    init_db()
    if analysis_date is None:
        analysis_date = date_cls.today().isoformat()

    ctx = collect_context(analysis_date)
    system, user = build_messages(
        analysis_date=analysis_date,
        price_movements=ctx["price_movements"],
        volume_anomalies=ctx["volume_anomalies"],
        sector_summary=ctx["sector_summary"],
        fundamentals_pool=ctx["fundamentals_pool"],
        allowed_assets=ctx["allowed_assets"],
        news_pool=ctx["news_pool"],
        macro_snapshot=ctx["macro_snapshot"],
        recent_leaders_history=ctx["recent_leaders_history"],
    )

    # 1차 시도 + 1회 재시도
    for attempt in range(2):
        try:
            raw = call_claude(model, system, user)
            cleaned = _strip_code_fence(raw)
            parsed = json.loads(cleaned)
            parsed["model_name"] = model
            validated = DailyAnalysis.model_validate(parsed)
            break
        except Exception as e:
            print(f"  [WARN] 시도 {attempt+1} 실패: {type(e).__name__}: {e}")
            if attempt == 1:
                raise
            # 다음 시도엔 약간 강조한 프롬프트
            user += "\n\nIMPORTANT: 이전 응답이 JSON/스키마 검증에 실패했습니다. " \
                    "system rules 를 다시 확인하고 ONLY JSON 만 출력하세요."

    payload = validated.model_dump()
    save(payload)
    return payload


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None,
                   help="YYYY-MM-DD (기본: 오늘)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    args = p.parse_args()
    result = run_daily(args.date, args.model)
    if result is None:
        print("\n[DONE] LLM skip — 룰 기반 파이프라인만 실행됨.")
    else:
        print(f"\n[DONE] {len(result['current_trends'])}개 현재 트렌드 + "
              f"{len(result['predicted_trends'])}개 예측 트렌드 저장 완료.")


if __name__ == "__main__":
    main()
