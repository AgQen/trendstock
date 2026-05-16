"""토큰 최적화 유틸 (기획서 19.6.4 사전 준비).

세 가지 절감 전략을 제공:

1) **Prompt caching** — System prompt 를 Anthropic prompt caching 으로 등록.
   - 4 시간 캐시, cache_read 는 input 단가의 10% 만 청구.
   - System prompt 가 변하지 않으면 매일 50~70% 입력 토큰 절감.

2) **2단계 라우팅** — Haiku 로 트렌드 후보 추출 → Sonnet 으로 Top 5 만 심층 분석.
   - 1차: 가벼운 분류 (Haiku, 입력 적음)
   - 2차: 핵심만 정밀 (Sonnet, 출력 적음)
   - 총 비용 50% 절감 예상.

3) **컨텍스트 압축** — LLM 에 raw 가격 데이터 대신 룰 기반 후보만 전달.
   - 200 종목 × OHLCV 30일 → 사전 추출된 트렌드 후보 + 대장주 후보만 전달
   - 입력 토큰 80% 감소.
"""

from __future__ import annotations

from anthropic import Anthropic

from collectors.token_logger import log_from_anthropic_response

# ====================================================================
# 1) Prompt caching wrapper
# ====================================================================

def call_with_cache(
    client: Anthropic,
    model: str,
    system_text: str,
    user_text: str,
    category: str = "daily_analysis",
    max_tokens: int = 8000,
    note: str | None = None,
):
    """system block 에 cache_control 마킹 — 동일 system 재호출 시 read 비용으로.

    효과: system 토큰이 ~3000 일 때 매 호출 약 $0.008 → $0.0008 로 절감.
    """
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_text}],
    )
    log_from_anthropic_response(category, model, resp, note=note)
    return resp


# ====================================================================
# 2) 2단계 라우팅 — Haiku 분류 → Sonnet 심층
# ====================================================================

HAIKU_MODEL = "claude-haiku-4-5"
SONNET_MODEL = "claude-sonnet-4-6"

HAIKU_FILTER_PROMPT = """\
You are a market signal filter. Given price/volume snapshots, output ONLY a
JSON array of the top 8 candidate "themes" worth deeper analysis today.

Each candidate has: {theme: str, evidence: str (1 line), tickers: [str]}

DO NOT explain. DO NOT add prose. Output ONLY the JSON array.
"""


def stage1_filter_with_haiku(client: Anthropic, snapshot_text: str) -> str:
    """1차: Haiku 로 후보 테마 8개 추출. 출력 토큰 적음 (~300)."""
    resp = call_with_cache(
        client, HAIKU_MODEL, HAIKU_FILTER_PROMPT, snapshot_text,
        category="daily_analysis", max_tokens=800,
        note="stage1_filter (haiku)",
    )
    return resp.content[0].text


def stage2_deepdive_with_sonnet(
    client: Anthropic, system_prompt: str, full_context: str
) -> str:
    """2차: Sonnet 으로 최종 5 + 5 트렌드 + 추천 생성."""
    resp = call_with_cache(
        client, SONNET_MODEL, system_prompt, full_context,
        category="daily_analysis", max_tokens=8000,
        note="stage2_deepdive (sonnet)",
    )
    return resp.content[0].text


# ====================================================================
# 3) 컨텍스트 압축
# ====================================================================

def compress_price_movements(moves: list[dict], threshold_pct: float = 2.0) -> list[dict]:
    """1d 변동이 |threshold| 이상인 종목만 LLM 입력에 포함.

    200 종목 → 약 30~50 종목으로 압축 (토큰 75% 감소).
    """
    return [m for m in moves
            if abs(m.get("change_1d_pct") or 0) >= threshold_pct]


def compress_sector_summary(sectors: list[dict], top_n: int = 12) -> list[dict]:
    """1d 평균 기준 상위/하위 N개 섹터만 전달."""
    sorted_secs = sorted(sectors,
                         key=lambda s: abs(s.get("avg_1d_pct") or 0),
                         reverse=True)
    return sorted_secs[:top_n]


# ====================================================================
# 예상 토큰 절감 시뮬레이션
# ====================================================================

ESTIMATED_SAVINGS = {
    "baseline": {
        "input_tokens": 8000,
        "output_tokens": 3000,
        "cost_usd_per_day": 0.069,
        "cost_usd_per_month": 2.07,
        "description": "200 종목 raw + Sonnet 단일 호출",
    },
    "with_caching": {
        "input_tokens": 8000,  # but 80% cache read
        "output_tokens": 3000,
        "cost_usd_per_day": 0.030,
        "cost_usd_per_month": 0.90,
        "description": "위 + system prompt caching (입력 80% cache_read)",
    },
    "with_caching_and_compression": {
        "input_tokens": 2500,
        "output_tokens": 3000,
        "cost_usd_per_day": 0.020,
        "cost_usd_per_month": 0.60,
        "description": "위 + 가격/섹터 컨텍스트 압축 (변동 큰 종목만)",
    },
    "with_routing": {
        "input_tokens": 2500,
        "output_tokens": 1800,
        "cost_usd_per_day": 0.014,
        "cost_usd_per_month": 0.42,
        "description": "위 + Haiku 1차 필터 → Sonnet 2차 (출력 단축)",
    },
}


if __name__ == "__main__":
    print("=" * 60)
    print(" 토큰 최적화 시뮬레이션 (200 종목 / 일 1회 분석)")
    print("=" * 60)
    for k, v in ESTIMATED_SAVINGS.items():
        print(f"\n[{k}] {v['description']}")
        print(f"  입력 {v['input_tokens']:>5} / 출력 {v['output_tokens']:>4} tok")
        print(f"  ${v['cost_usd_per_day']:.4f}/일  ≈  "
              f"${v['cost_usd_per_month']:.2f}/월  "
              f"(₩{int(v['cost_usd_per_month'] * 1400):,})")

    base = ESTIMATED_SAVINGS["baseline"]["cost_usd_per_month"]
    best = ESTIMATED_SAVINGS["with_routing"]["cost_usd_per_month"]
    print(f"\n총 절감: {(1 - best/base)*100:.0f}%  "
          f"(월 ${base:.2f} → ${best:.2f})")
